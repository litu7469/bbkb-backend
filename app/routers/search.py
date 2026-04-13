from fastapi import APIRouter, Query
from typing import Optional
from app.services.search_service import hybrid_search

router = APIRouter(prefix="/search", tags=["Search"])

@router.get("/")
async def search(
    q:            str           = Query(..., min_length=2, description="Search query"),
    mode:         str           = Query("hybrid", description="hybrid | semantic | keyword"),
    issuing_body: Optional[str] = Query(None),
    department:   Optional[str] = Query(None),
    date_from:    Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to:      Optional[str] = Query(None, description="YYYY-MM-DD"),
    limit:        int           = Query(20, ge=1, le=50),
):
    """
    Smart hybrid search combining semantic AI search with keyword matching.
    mode=hybrid  → uses both semantic + keyword (recommended)
    mode=semantic → AI semantic only (best for concept search)
    mode=keyword  → traditional keyword only (fastest)
    """
    return hybrid_search(
        query        = q,
        limit        = limit,
        issuing_body = issuing_body,
        department   = department,
        date_from    = date_from,
        date_to      = date_to,
        mode         = mode,
    )