"""Source provenance API: lightweight recovery metadata per Work (issue #5)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..db import get_conn, get_read_conn
from ..source_provenance import record as record_prov, query as query_prov, export_catalog

router = APIRouter()


class ProvenanceBody(BaseModel):
    work_id: str
    source_file_id: str | None = None
    landing_url: str = ""
    direct_url: str = ""
    backup_url: str = ""
    source_type: str = ""
    doi: str = ""
    arxiv_id: str = ""
    known_sha256: str = ""
    known_bytes: int | None = Field(default=None, ge=0, strict=True)
    first_obtained_at: str = ""
    last_verified_at: str = ""
    access_notes: str = ""


@router.post("/provenance")
def record_provenance(body: ProvenanceBody):
    """Record or update provenance metadata for a Work."""
    conn = get_conn()
    try:
        conn.execute('BEGIN IMMEDIATE')
        exists = conn.execute("SELECT 1 FROM works WHERE id=?", (body.work_id,)).fetchone()
        if not exists:
            raise HTTPException(404, f"work {body.work_id} not found")
        if body.source_file_id:
            source = conn.execute(
                'SELECT work_id, content_sha256, file_size FROM source_files WHERE id=?',
                (body.source_file_id,)).fetchone()
            if not source:
                raise HTTPException(404, 'source not found')
            if source['work_id'] != body.work_id:
                raise HTTPException(400, 'source does not belong to work')
            if body.known_sha256 and source['content_sha256'] and body.known_sha256.lower() != source['content_sha256'].lower():
                raise HTTPException(400, 'source SHA256 differs from registered source')
            if body.known_bytes is not None and source['file_size'] is not None and body.known_bytes != source['file_size']:
                raise HTTPException(400, 'source bytes differ from registered source')
        result = record_prov(conn, **body.model_dump(exclude_unset=True))
        conn.commit()
        return {"ok": True, "provenance": result}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        conn.close()


@router.get("/provenance/{work_id}")
def get_provenance(work_id: str):
    """Read provenance records for a Work. Read-only; no schema creation."""
    conn = get_read_conn()
    try:
        records = query_prov(conn, work_id)
        return {"work_id": work_id, "records": records}
    finally:
        conn.close()


@router.get("/provenance-export")
def export_provenance(limit: int = Query(default=5000, ge=1, le=5000)):
    """Export the full provenance catalog as a versioned integrity-checkable manifest."""
    conn = get_read_conn()
    try:
        catalog = export_catalog(conn, limit=limit)
        return catalog
    finally:
        conn.close()
