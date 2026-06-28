"""Intake (collector A2 review) API routes. Thin adapters over collector core.

Single-nucleus: this module writes no business logic. Candidate reads are inline
SQL (matching the metadata.py read pattern); every state change delegates to
collector.candidate_store / collector.gate / collector.ingest_bridge / collector.topics.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..db import get_conn, LIBRARY_ROOT
from collector import candidate_store, gate, ingest_bridge, topics

router = APIRouter()

RESOLUTIONS = (
    "pending", "new", "exact_hit", "title_candidate",
    "needs_better_copy", "sha256_duplicate", "fetch_failed",
)


@router.get("/intake/candidates")
def list_candidates(
    resolution: str | None = Query(None),
    review_status: str | None = Query(None),
    topic: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: str = Query(""),
):
    conn = get_conn()
    try:
        where, params = [], []
        if resolution:
            where.append("ic.resolution = ?"); params.append(resolution)
        if review_status:
            where.append("ic.review_status = ?"); params.append(review_status)
        if topic:
            where.append("ic.collection_topic_id = ?"); params.append(topic)
        if search:
            where.append("(ic.title LIKE ? OR ic.arxiv_id LIKE ? OR ic.id LIKE ?)")
            s = f"%{search}%"
            params.extend([s, s, s])
        where_clause = ("WHERE " + " AND ".join(where)) if where else ""

        total = conn.execute(
            f"SELECT COUNT(*) FROM intake_candidates ic {where_clause}", params
        ).fetchone()[0]

        offset = (page - 1) * per_page
        rows = conn.execute(
            f"""SELECT ic.*, ct.name AS topic_name
                FROM intake_candidates ic
                LEFT JOIN collection_topics ct ON ct.id = ic.collection_topic_id
                {where_clause}
                ORDER BY ic.collected_at DESC NULLS LAST
                LIMIT ? OFFSET ?""",
            params + [per_page, offset],
        ).fetchall()

        candidates = []
        for r in rows:
            d = dict(r)
            if d.get("raw_meta"):
                try:
                    d["raw_meta"] = json.loads(d["raw_meta"])
                except (json.JSONDecodeError, TypeError):
                    pass
            candidates.append(d)
        return {"candidates": candidates, "total": total, "page": page, "per_page": per_page}
    finally:
        conn.close()


@router.get("/intake/stats")
def intake_stats():
    conn = get_conn()
    try:
        resolution = {r: 0 for r in RESOLUTIONS}
        for row in conn.execute(
            "SELECT resolution, COUNT(*) n FROM intake_candidates GROUP BY resolution"
        ).fetchall():
            resolution[row["resolution"]] = row["n"]
        review = {"pending": 0, "approved": 0, "rejected": 0}
        for row in conn.execute(
            "SELECT review_status, COUNT(*) n FROM intake_candidates GROUP BY review_status"
        ).fetchall():
            review[row["review_status"]] = row["n"]
        return {
            "resolution": resolution,
            "review": review,
            "total": conn.execute("SELECT COUNT(*) FROM intake_candidates").fetchone()[0],
        }
    finally:
        conn.close()


class ResolveBody(BaseModel):
    ids: list[str] | None = None
    limit: int | None = None


@router.post("/intake/resolve")
def intake_resolve(body: ResolveBody):
    """Trigger the heavy (SHA256) gate. Delegates entirely to gate.resolve_pending."""
    results = gate.resolve_pending(ids=body.ids, limit=body.limit)
    return {
        "resolved": len(results),
        "results": [{"id": cid, "resolution": res} for cid, res in results],
    }


class ReviewBody(BaseModel):
    review_status: str
    note: str | None = None


@router.patch("/intake/candidates/{candidate_id}/review")
def review_candidate(candidate_id: str, body: ReviewBody):
    if body.review_status not in candidate_store.VALID_REVIEW:
        raise HTTPException(400, f"review_status must be one of {sorted(candidate_store.VALID_REVIEW)}")
    try:
        candidate_store.set_review_status(candidate_id, body.review_status, note=body.note)
    except KeyError:
        raise HTTPException(404, f"candidate not found: {candidate_id}")
    return {"ok": True, "id": candidate_id, "review_status": body.review_status}


class PromoteBody(BaseModel):
    ids: list[str]


@router.post("/intake/promote")
def promote_candidates(body: PromoteBody):
    """A2 batch promote → reuse ingest_bridge (single nucleus). Collector never
    writes works directly. Returns per-id results; a single failure does not
    abort the batch."""
    if not body.ids:
        raise HTTPException(400, "ids is required and must be non-empty")
    promoted, failed = [], []
    for cid in body.ids:
        try:
            work_id = ingest_bridge.promote(cid, library_root=LIBRARY_ROOT)
            promoted.append({"id": cid, "work_id": work_id})
        except Exception as e:  # noqa: BLE001 — batch must not abort on one failure
            failed.append({"id": cid, "error": str(e)})
    return {"promoted": promoted, "failed": failed}
