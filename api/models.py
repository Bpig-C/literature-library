"""Pydantic models for API request/response."""

from __future__ import annotations

from pydantic import BaseModel


class WorkUpdate(BaseModel):
    title: str | None = None
    authors: list[str] | None = None
    year: int | None = None
    month: int | None = None
    doc_type: str | None = None
    language: str | None = None
    read_status: str | None = None
    publication_date_json: str | None = None
    # Classification v0.2 fields
    primary_doc_type: str | None = None
    secondary_doc_type: str | None = None
    publication_status: str | None = None
    ingestion_state: str | None = None
    priority: str | None = None
    is_core_literature: bool | None = None
    primary_source_actor_type: str | None = None
    region: str | None = None
    canonical_file_format: str | None = None


class RelationCreate(BaseModel):
    work_id_a: str
    work_id_b: str
    relation_type: str
    note: str = ""
    relation_category: str = "content"  # content / versioning / document_structure
    source: str = "human"


class DuplicateReview(BaseModel):
    decision: str
    note: str = ""


class QuarantineAction(BaseModel):
    reason: str = ""


class MetadataReviewAction(BaseModel):
    review_status: str  # approved | needs_fix | rejected
    review_note: str = ""
    edited_fields: dict | None = None  # optional field overrides to merge into extracted_json


class MetadataSupersedeAction(BaseModel):
    review_note: str = ""
    edited_fields: dict | None = None  # new/overridden extraction fields from agent or external rerun
