"""Relations API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..db import get_conn
from ..models import RelationCreate

router = APIRouter()


@router.get("/relations")
def list_relations():
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM work_relations ORDER BY work_id_a, work_id_b"
        ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            # Enrich with work titles
            for key in ("work_id_a", "work_id_b"):
                partner = conn.execute(
                    "SELECT title FROM works WHERE id = ?", (d[key],)
                ).fetchone()
                d[f"{key}_title"] = partner["title"] if partner else d[key]
            results.append(d)
        return {"relations": results, "total": len(results)}
    finally:
        conn.close()


@router.post("/relations")
def create_relation(body: RelationCreate):
    VALID_TYPES = {
        "same_work", "not_duplicate", "version_of",
        "translation_of", "supersedes", "part_of",
    }
    if body.relation_type not in VALID_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid relation_type: {body.relation_type}. Must be one of: {VALID_TYPES}",
        )

    conn = get_conn()
    try:
        # Check works exist
        for wid in (body.work_id_a, body.work_id_b):
            if not conn.execute("SELECT 1 FROM works WHERE id = ?", (wid,)).fetchone():
                raise HTTPException(status_code=404, detail=f"Work not found: {wid}")

        conn.execute(
            "INSERT OR REPLACE INTO work_relations (work_id_a, work_id_b, relation_type, confirmed, note) VALUES (?, ?, ?, 0, ?)",
            (body.work_id_a, body.work_id_b, body.relation_type, body.note),
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@router.delete("/relations")
def delete_relation(body: RelationCreate):
    conn = get_conn()
    try:
        conn.execute(
            "DELETE FROM work_relations WHERE work_id_a = ? AND work_id_b = ? AND relation_type = ?",
            (body.work_id_a, body.work_id_b, body.relation_type),
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()
