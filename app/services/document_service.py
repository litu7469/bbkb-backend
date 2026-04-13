from app.database import supabase
from app.schemas.document import DocumentCreate, DocumentUpdate
import hashlib
from loguru import logger

import time

def execute_with_retry(query, retries=3, delay=0.5):
    """Retry Supabase queries on connection errors."""
    for attempt in range(retries):
        try:
            return query.execute_with_retry(query)
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(delay)
                continue
            raise e

def get_all_documents(
    issuing_body: str = None,
    category: str = None,
    status: str = "active",
    search: str = None,
    limit: int = 20,
    offset: int = 0
):
    """Fetch documents with optional filters."""
    query = supabase.table("documents").select("*")

    if status:
        query = query.eq("status", status)
    if issuing_body:
        query = query.eq("issuing_body", issuing_body)
    if category:
        query = query.eq("category_primary", category)

    query = query.order("issue_date", desc=True).range(offset, offset + limit - 1)

    result = query.execute_with_retry(query)
    return result.data

def get_document_by_id(document_id: str):
    """Fetch a single document by ID."""
    result = supabase.table("documents").select("*").eq("id", document_id).single().execute_with_retry(query)
    return result.data

def create_document(doc: DocumentCreate):
    """Insert a new document into the database."""
    data = doc.model_dump(exclude_none=True)

    # Convert date objects to strings for Supabase
    for field in ["issue_date", "effective_date", "compliance_deadline"]:
        if field in data and data[field]:
            data[field] = str(data[field])

    # Check if document with same URL already exists
    existing = supabase.table("documents").select("id").eq("primary_url", data["primary_url"]).execute_with_retry(query)
    if existing.data:
        logger.info(f"Document already exists: {data['primary_url']}")
        return existing.data[0]

    result = supabase.table("documents").insert(data).execute_with_retry(query)
    logger.info(f"Created document: {data.get('title_en', 'Unknown')}")
    return result.data[0] if result.data else None

def update_document(document_id: str, updates: DocumentUpdate):
    """Update document fields."""
    data = updates.model_dump(exclude_none=True)
    if "superseded_by" in data:
        data["superseded_by"] = str(data["superseded_by"])
    result = supabase.table("documents").update(data).eq("id", document_id).execute_with_retry(query)
    return result.data[0] if result.data else None

def search_documents(query: str, limit: int = 20):
    """Simple text search across title and summary."""
    # Supabase text search using ilike for Phase 1
    result = supabase.table("documents").select("*").or_(
        f"title_en.ilike.%{query}%,"
        f"summary_en.ilike.%{query}%,"
        f"circular_ref.ilike.%{query}%"
    ).eq("status", "active").limit(limit).execute_with_retry(query)
    return result.data

def get_documents_by_issuing_body(body: str, limit: int = 50):
    """Get all documents from a specific regulatory body."""
    result = (
        supabase.table("documents")
        .select("*")
        .eq("issuing_body", body)
        .eq("status", "active")
        .order("issue_date", desc=True)
        .limit(limit)
        .execute_with_retry(query)
    )
    return result.data