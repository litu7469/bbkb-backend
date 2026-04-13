from pydantic import BaseModel
from typing import Optional, List
from uuid import UUID

class QueryRequest(BaseModel):
    query_text: str
    language:   str = "auto"   # auto | en | bn

class Citation(BaseModel):
    document_id:  UUID
    title_en:     str
    title_bn:     Optional[str]  = None
    circular_ref: Optional[str]  = None
    issuing_body: str
    issue_date:   str
    primary_url:  str
    status:       str
    language:     Optional[str]  = "english"

class QueryResponse(BaseModel):
    answer:                  str
    citations:               List[Citation]
    model_used:              str
    latency_ms:              int
    query_language:          str  = "en"
    disclaimer:              str  = ""
    has_superseded_citation: bool = False