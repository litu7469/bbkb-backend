"""
Hybrid search service combining:
1. Semantic search (vector similarity via pgvector)
2. Keyword search (PostgreSQL ILIKE)
Results are merged and ranked.
"""
from functools import lru_cache
from loguru import logger
from app.database import supabase


@lru_cache(maxsize=1)
def get_embedding_model():
    """Load once at startup, reuse for all searches."""
    from sentence_transformers import SentenceTransformer
    logger.info("Loading embedding model for search...")
    model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    logger.info("Search model ready!")
    return model


def embed_query(query: str) -> list:
    """Convert search query to embedding vector."""
    model = get_embedding_model()
    embedding = model.encode(query, normalize_embeddings=True)
    return embedding.tolist()


def semantic_search(
    query: str,
    limit: int         = 20,
    issuing_body: str  = None,
    department: str    = None,
    date_from: str     = None,
    date_to: str       = None,
    threshold: float   = 0.3,
) -> list:
    """
    Find documents semantically similar to the query.
    Uses pgvector cosine similarity on pre-computed embeddings.
    threshold: minimum similarity score (0-1). Lower = more results.
    """
    try:
        # Generate query embedding
        query_embedding = embed_query(query)

        # Build the RPC call for vector search
        # We use a Postgres function for this
        result = supabase.rpc(
            'semantic_search',
            {
                'query_embedding': query_embedding,
                'match_count':     limit * 2,  # fetch more, filter after
                'similarity_threshold': threshold,
                'filter_issuing_body': issuing_body,
                'filter_department':   department,
                'filter_date_from':    date_from,
                'filter_date_to':      date_to,
            }
        ).execute()

        return result.data or []

    except Exception as e:
        logger.error(f"Semantic search error: {e}")
        # Fall back to keyword search
        return keyword_search(query, limit, issuing_body, department)


def keyword_search(
    query: str,
    limit: int        = 20,
    issuing_body: str = None,
    department: str   = None,
    date_from: str    = None,
    date_to: str      = None,
) -> list:
    """
    Traditional keyword search using ILIKE.
    Searches across title, circular_ref, summary.
    """
    try:
        words   = query.strip().split()[:8]
        filters = []

        for word in words:
            if len(word) < 2:
                continue
            filters.append(
                f"title_en.ilike.%{word}%,"
                f"title_bn.ilike.%{word}%,"
                f"circular_ref.ilike.%{word}%,"
                f"summary_en.ilike.%{word}%"
            )

        db_query = supabase.table("documents").select(
            "id, title_en, title_bn, circular_ref, issuing_body, "
            "department, issue_date, status, primary_url, "
            "category_primary, topic_tags, summary_en"
        ).eq("status", "active")

        if filters:
            db_query = db_query.or_(",".join(filters))
        if issuing_body:
            db_query = db_query.eq("issuing_body", issuing_body)
        if department:
            db_query = db_query.eq("department", department)
        if date_from:
            db_query = db_query.gte("issue_date", date_from)
        if date_to:
            db_query = db_query.lte("issue_date", date_to)

        result = db_query.order("issue_date", desc=True).limit(limit).execute()
        return result.data or []

    except Exception as e:
        logger.error(f"Keyword search error: {e}")
        return []


def hybrid_search(
    query: str,
    limit: int        = 20,
    issuing_body: str = None,
    department: str   = None,
    date_from: str    = None,
    date_to: str      = None,
    mode: str         = "hybrid",  # hybrid | semantic | keyword
) -> dict:
    """
    Hybrid search combining semantic + keyword results.
    Deduplicates and ranks by combining both signals.
    """
    semantic_results = []
    keyword_results  = []

    if mode in ("hybrid", "semantic"):
        semantic_results = semantic_search(
            query, limit, issuing_body, department, date_from, date_to
        )

    if mode in ("hybrid", "keyword"):
        keyword_results = keyword_search(
            query, limit, issuing_body, department, date_from, date_to
        )

    # Merge and deduplicate
    seen = set()
    merged = []

    # Semantic results first (higher quality)
    for doc in semantic_results:
        doc_id = doc.get("id") or doc.get("document_id")
        if doc_id and doc_id not in seen:
            seen.add(doc_id)
            doc["_source"] = "semantic"
            merged.append(doc)

    # Add keyword results not already in semantic
    for doc in keyword_results:
        doc_id = doc.get("id")
        if doc_id and doc_id not in seen:
            seen.add(doc_id)
            doc["_source"] = "keyword"
            merged.append(doc)

    return {
        "items":            merged[:limit],
        "total":            len(merged),
        "semantic_count":   len(semantic_results),
        "keyword_count":    len(keyword_results),
        "query":            query,
        "mode":             mode,
    }