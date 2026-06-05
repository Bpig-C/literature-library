"""Pydantic models for API request/response."""

from __future__ import annotations

from pydantic import BaseModel


class WorkUpdate(BaseModel):
    title: str | None = None
    authors: list[str] | None = None
    year: int | None = None
    doc_type: str | None = None
    language: str | None = None
    read_status: str | None = None


class RelationCreate(BaseModel):
    work_id_a: str
    work_id_b: str
    relation_type: str
    note: str = ""


class DuplicateReview(BaseModel):
    decision: str
    note: str = ""


class QuarantineAction(BaseModel):
    reason: str = ""
