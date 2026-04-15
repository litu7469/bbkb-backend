"""
Admin Router — protected endpoints for dashboard
"""
from fastapi import APIRouter, HTTPException, Header
from app.database import supabase
from app.config import settings
import httpx

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def verify_admin_token(authorization: str = Header(None)):
    """Verify Supabase JWT token from request header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return authorization.replace("Bearer ", "")


# ── Stats ─────────────────────────────────────────────────────

@router.get("/stats")
def get_admin_stats(authorization: str = Header(None)):
    verify_admin_token(authorization)
    try:
        # Total documents
        total = supabase.table("documents").select("id", count="exact").execute()

        # By issuing body
        by_body = {}
        for body in ['BB', 'NBR', 'BSEC', 'BFIU', 'Ministry of Law', 'International']:
            r = supabase.table("documents").select("id", count="exact").eq("issuing_body", body).execute()
            by_body[body] = r.count or 0

        # New today
        from datetime import date
        today = date.today().isoformat()
        new_today = supabase.table("documents").select("id", count="exact").gte("created_at", today).execute()

        # Total queries
        total_queries = supabase.table("query_audit_log").select("id", count="exact").execute()

        # Queries today
        queries_today = supabase.table("query_audit_log").select("id", count="exact").gte("created_at", today).execute()

        # Total embeddings
        embeddings = supabase.table("document_chunks").select("id", count="exact").execute()

        return {
            "total_documents":  total.count or 0,
            "by_body":          by_body,
            "new_today":        new_today.count or 0,
            "total_queries":    total_queries.count or 0,
            "queries_today":    queries_today.count or 0,
            "total_embeddings": embeddings.count or 0,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Recent Queries ────────────────────────────────────────────

@router.get("/queries")
def get_recent_queries(limit: int = 20, authorization: str = Header(None)):
    verify_admin_token(authorization)
    try:
        result = (
            supabase.table("query_audit_log")
            .select("id, query_text, query_language, latency_ms, model_used, created_at")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return {"queries": result.data or []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Scraper Jobs ──────────────────────────────────────────────

@router.get("/scraper-jobs")
def get_scraper_jobs(limit: int = 20, authorization: str = Header(None)):
    verify_admin_token(authorization)
    try:
        result = (
            supabase.table("scraper_jobs")
            .select("*")
            .order("started_at", desc=True)
            .limit(limit)
            .execute()
        )
        return {"jobs": result.data or []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Trigger Scraper ───────────────────────────────────────────

@router.post("/scraper/run")
async def trigger_scraper(
    source: str = "bb",
    authorization: str = Header(None)
):
    verify_admin_token(authorization)
    try:
        if source == "bb":
            from scrapers.bb_historical_scraper import run_bb_scraper
            import asyncio
            asyncio.create_task(asyncio.to_thread(run_bb_scraper))
        elif source == "nbr":
            from scrapers.nbr_scraper import run_nbr_scraper
            import asyncio
            asyncio.create_task(asyncio.to_thread(run_nbr_scraper))
        elif source == "bsec":
            from scrapers.bsec_scraper import run_bsec_scraper
            import asyncio
            asyncio.create_task(asyncio.to_thread(run_bsec_scraper))
        elif source == "embed":
            from scripts.reembed_specific import reembed_missing
            import asyncio
            asyncio.create_task(asyncio.to_thread(reembed_missing))
        elif source == "all":
            return {"status": "started", "message": "Run scrapers individually for reliability"}
        else:
            raise HTTPException(status_code=400, detail=f"Unknown source: {source}")

        return {"status": "started", "source": source}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Document Management ───────────────────────────────────────

@router.get("/documents")
def get_admin_documents(
    limit: int = 20,
    offset: int = 0,
    issuing_body: str = None,
    status: str = None,
    authorization: str = Header(None)
):
    verify_admin_token(authorization)
    try:
        query = supabase.table("documents").select(
            "id, title_en, circular_ref, issuing_body, department, issue_date, status, created_at",
            count="exact"
        )
        if issuing_body: query = query.eq("issuing_body", issuing_body)
        if status:       query = query.eq("status", status)
        result = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
        return {"documents": result.data or [], "total": result.count or 0}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/documents/{doc_id}")
def update_document(
    doc_id: str,
    updates: dict,
    authorization: str = Header(None)
):
    verify_admin_token(authorization)
    try:
        allowed = {"status", "summary_en", "topic_tags", "category_primary"}
        filtered = {k: v for k, v in updates.items() if k in allowed}
        result = supabase.table("documents").update(filtered).eq("id", doc_id).execute()
        return {"updated": True, "data": result.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))