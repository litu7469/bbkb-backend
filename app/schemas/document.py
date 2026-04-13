from pydantic import BaseModel, HttpUrl
from typing import Optional, List
from datetime import date, datetime
from uuid import UUID

class DocumentCreate(BaseModel):
    circular_ref: Optional[str] = None
    title_en: str
    title_bn: Optional[str] = None
    issuing_body: str
    department: Optional[str] = None
    doc_type: str = "Circular"
    issue_date: date
    effective_date: Optional[date] = None
    language: str = "english"
    status: str = "active"
    primary_url: str
    mirror_url: Optional[str] = None
    doc_format: str = "pdf"
    applies_to: Optional[List[str]] = None
    compliance_deadline: Optional[date] = None
    category_primary: Optional[str] = None
    category_sub: Optional[str] = None
    topic_tags: Optional[List[str]] = None
    summary_en: Optional[str] = None
    added_by: str = "system"

class DocumentUpdate(BaseModel):
    title_en: Optional[str] = None
    status: Optional[str] = None
    summary_en: Optional[str] = None
    category_primary: Optional[str] = None
    category_sub: Optional[str] = None
    topic_tags: Optional[List[str]] = None
    superseded_by: Optional[UUID] = None

class DocumentResponse(BaseModel):
    id: UUID
    circular_ref: Optional[str]
    title_en: str
    title_bn: Optional[str]
    issuing_body: str
    department: Optional[str]
    doc_type: str
    issue_date: date
    status: str
    primary_url: str
    category_primary: Optional[str]
    category_sub: Optional[str]
    topic_tags: Optional[List[str]]
    summary_en: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True