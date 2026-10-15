"""Source provenance API: lightweight recovery metadata per Work (issue #5)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..db import get_conn
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
    known_bytes: int | None = None
    first_obtained_at: str = ""
    last_verified_at: str = ""
    access_notes: str = ""


@router.post("/provenance")
def record_provenance(body: ProvenanceBody):
    """Record or update provenance metadata for a Work."""
    conn = get_conn()
    try:
        exists = conn.execute("SELECT 1 FROM works WHERE id=?", (body.work_id,)).fetchone()
        if not exists:
            raise HTTPException(404, f"work {body.work_id} not found")
        result = record_prov(conn, **body.model_dump())
        conn.commit()
        return {"ok": True, "provenance": result}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        conn.close()


@router.get("/provenance/{work_id}")
def get_provenance(work_id: str):
    """Read provenance records for a Work. Read-only; no schema creation."""
    conn = get_conn()
    try:
        records = query_prov(conn, work_id)
        return {"work_id": work_id, "records": records}
    finally:
        conn.close()


@router.get("/provenance-export")
def export_provenance(limit: int = Query(default=5000, ge=1, le=5000)):
    """Export the full provenance catalog as a versioned integrity-checkable manifest."""
    conn = get_conn()
    try:
        catalog = export_catalog(conn, limit=limit)
        return catalog
    finally:
        conn.close()
