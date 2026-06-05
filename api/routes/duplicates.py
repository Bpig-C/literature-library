"""Duplicates API routes."""

from __future__ import annotations

from fastapi import APIRouter

from ..db import get_conn
from ..models import DuplicateReview

router = APIRouter()


@router.get("/duplicates")
def list_duplicates():
    conn = get_conn()
    try:
        groups = [
            dict(r) for r in conn.execute("SELECT * FROM duplicate_groups ORDER BY id").fetchall()
        ]
        candidates = [
            dict(r) for r in conn.execute("SELECT * FROM duplicate_candidates ORDER BY group_id, id").fetchall()
        ]

        # Enrich candidates with work info
        for c in candidates:
            work = conn.execute(
                "SELECT title, authors, year, doc_type, language, parse_status, read_status FROM works WHERE id = ?",
                (c["work_id"],),
            ).fetchone()
            if work:
                c["work_title"] = work["title"] or c["work_id"]
                c["work_year"] = work["year"]
                c["work_doc_type"] = work["doc_type"] or ""
                c["work_language"] = work["language"] or ""
                c["work_parse_status"] = work["parse_status"] or ""
                c["work_read_status"] = work["read_status"] or ""
            # Source file info
            src = conn.execute(
                "SELECT original_name, relative_source_path FROM source_files WHERE id = ?",
                (c.get("source_file_id") or "",),
            ).fetchone()
            if src:
                c["source_original_name"] = src["original_name"] or ""

        # Group candidates
        cands_by_group: dict[str, list] = {}
        for c in candidates:
            gid = c.get("group_id", "")
            cands_by_group.setdefault(gid, []).append(c)

        for g in groups:
            g["candidates"] = cands_by_group.get(g["id"], [])
            work_ids = list({c["work_id"] for c in g["candidates"] if c.get("work_id")})
            work_ids.sort()
            g["work_ids"] = work_ids
            g["auto_confirmed"] = g["duplicate_type"] == "exact_sha256"

        return {"groups": groups, "total_groups": len(groups), "total_candidates": len(candidates)}
    finally:
        conn.close()


@router.post("/duplicates/{group_id}/review")
def review_duplicate(group_id: str, body: DuplicateReview):
    VALID_DECISIONS = {
        "same_work", "not_duplicate", "version_of",
        "translation_of", "supersedes", "part_of", "quarantine",
    }
    if body.decision not in VALID_DECISIONS:
        return {"ok": False, "error": f"Invalid decision: {body.decision}"}

    conn = get_conn()
    try:
        # Mark candidates as reviewed
        conn.execute(
            "UPDATE duplicate_candidates SET reviewed = 1 WHERE group_id = ?",
            (group_id,),
        )

        # Handle quarantine
        if body.decision == "quarantine":
            cands = conn.execute(
                "SELECT DISTINCT work_id FROM duplicate_candidates WHERE group_id = ?",
                (group_id,),
            ).fetchall()
            for c in cands:
                conn.execute(
                    "UPDATE works SET read_status = 'quarantined' WHERE id = ?",
                    (c["work_id"],),
                )
                try:
                    conn.execute(
                        "INSERT INTO work_codes (work_id, source_file_id, code, reason) VALUES (?, '', 'bad_source', ?)",
                        (c["work_id"], body.note or f"quarantine: {group_id}"),
                    )
                except Exception:
                    pass

        conn.commit()
        return {"ok": True}
    finally:
        conn.close()
