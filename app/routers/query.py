from fastapi import APIRouter, HTTPException
from app.schemas.query import QueryRequest, QueryResponse
from app.services.rag_service import process_query
from loguru import logger

router = APIRouter(prefix="/query", tags=["AI Query"])

@router.post("/", response_model=QueryResponse)
async def ai_query(request: QueryRequest):
    """
    Submit a question in English or Bangla about Bangladesh banking regulations.
    Language is auto-detected — no need to specify manually.
    Returns an AI-generated answer in the same language as the query.
    """
    if len(request.query_text.strip()) < 3:
        raise HTTPException(status_code=400, detail="Query is too short.")

    if len(request.query_text) > 2000:
        raise HTTPException(status_code=400, detail="Query too long (max 2000 chars).")

    logger.info(f"Query received: {request.query_text[:80]}")

    result = await process_query(
        query_text=request.query_text,
        language=request.language,
        user_id=None,
    )

    return QueryResponse(**result)