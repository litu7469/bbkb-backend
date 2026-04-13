from fastapi import APIRouter
from app.database import supabase

router = APIRouter(tags=["Health"])

@router.get("/health")
def health_check():
    """Check if the API and database are running."""
    try:
        # Try a simple DB query
        supabase.table("documents").select("id").limit(1).execute()
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {str(e)}"

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "api": "ok",
        "database": db_status,
        "version": "1.0.0"
    }