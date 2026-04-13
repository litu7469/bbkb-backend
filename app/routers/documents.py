from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from app.database import supabase
from app.services.document_service import (
    get_document_by_id,
    create_document,
    search_documents,
)
from app.schemas.document import DocumentCreate

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.get("/stats")
def get_document_stats():
    """Single endpoint returning all stats for the home page."""
    try:
        total_result = (
            supabase.table("documents")
            .select("id", count="exact")
            .execute()
        )
        total = total_result.count or 0

        by_body = {}
        for body in ['BB', 'NBR', 'BSEC', 'BFIU']:
            try:
                result = (
                    supabase.table("documents")
                    .select("id", count="exact")
                    .eq("issuing_body", body)
                    .execute()
                )
                by_body[body] = result.count or 0
            except Exception:
                by_body[body] = 0

        return {
            "total":   total,
            "by_body": by_body,
        }
    except Exception as e:
        return {"total": 0, "by_body": {}, "error": str(e)}


@router.get("/")
def list_documents(
    issuing_body: Optional[str] = Query(None, description="Filter by: BB, NBR, BSEC, BFIU"),
    department:   Optional[str] = Query(None),
    status:       Optional[str] = Query(None, description="active, superseded, or empty for all"),
    category:     Optional[str] = Query(None),
    topic:        Optional[str] = Query(None,              description="Filter by topic tag"),
    date_from:    Optional[str] = Query(None,              description="YYYY-MM-DD"),
    date_to:      Optional[str] = Query(None,              description="YYYY-MM-DD"),
    order:        Optional[str] = Query("issue_date.desc", description="field.asc or field.desc"),
    limit:        int           = Query(20, ge=1, le=100),
    offset:       int           = Query(0, ge=0),
):
    """List documents with filters, sorting and pagination."""
    query = (
        supabase.table("documents")
        .select("*", count="exact")
    )

    if issuing_body: query = query.eq("issuing_body",    issuing_body)
    if department:   query = query.eq("department",      department)
    if status:       query = query.eq("status",          status)
    if category:     query = query.eq("category_primary", category)
    if date_from:    query = query.gte("issue_date",     date_from)
    if date_to:      query = query.lte("issue_date",     date_to)
    if topic:        query = query.contains("topic_tags", [topic])

    # Parse order param e.g. "issue_date.desc" or "title_en.asc"
    order_col  = "issue_date"
    order_desc = True
    if order:
        parts = order.split('.')
        if len(parts) == 2:
            order_col  = parts[0]
            order_desc = parts[1].lower() == 'desc'

    query = (
        query
        .order(order_col, desc=order_desc)
        .range(offset, offset + limit - 1)
    )

    try:
        result = query.execute()
        return {
            "documents": result.data  or [],
            "total":     result.count or 0,
            "limit":     limit,
            "offset":    offset,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search")
def search(q: str = Query(..., min_length=2)):
    """Search documents by keyword."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    results = search_documents(q)
    return {"items": results, "query": q, "count": len(results)}


@router.get("/{document_id}")
def get_document(document_id: str):
    """Get a single document by ID."""
    doc = get_document_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.post("/", status_code=201)
def add_document(doc: DocumentCreate):
    """Add a new document manually."""
    result = create_document(doc)
    if not result:
        raise HTTPException(status_code=400, detail="Failed to create document")
    return result