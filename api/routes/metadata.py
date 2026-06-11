"""Metadata review API routes."""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from ..db import get_conn, ensure_metadata_review_columns, table_exists, LIBRARY_ROOT
from ..models import MetadataReviewAction, MetadataSupersedeAction, QuarantineAction
from ..risk import compute_risk

router = APIRouter()

# Fields that can be applied to works (overwrite on approve)
APPLY_FIELDS = {
    "title": "title",
    "doi": "doi",
    "arxiv_id": "arxiv_id",
    "venue": "venue",
    "url": "url",
    "abstract": "abstract",
    "title_zh": "title_zh",
    "authors": "authors",
    "contributors": "contributors",
    "publication_date": "publication_date_json",
}

# Fields edited by a human reviewer are treated as confirmed for apply.
HUMAN_CONFIRMED_FIELDS = set(APPLY_FIELDS) | {"date", "institutions", "author_count"}

# Valid quarantine reasons
QUARANTINE_REASONS = {"bad_source", "out_of_scope", "not_literature", "duplicate_residual", "user_removed", "needs_rerun"}


def _enrich_extraction(row: dict, conn) -> dict:
    """Add work info and parse extracted_json/confidence_json."""
    ext = dict(row)
    ext["extracted_json"] = json.loads(ext["extracted_json"]) if ext["extracted_json"] else {}
    ext["confidence_json"] = json.loads(ext["confidence_json"]) if ext["confidence_json"] else {}
    ext["risk_reasons"] = json.loads(ext["risk_reasons"]) if ext.get("risk_reasons") else []

    work = conn.execute(
        "SELECT title, year, authors, doi, arxiv_id, venue, url, abstract, title_zh "
        ", read_status "
        "FROM works WHERE id = ?", (ext["work_id"],)
    ).fetchone()
    if work:
        ext["work_title"] = work["title"] or ext["work_id"]
        ext["work_year"] = work["year"]
        ext["work_read_status"] = work["read_status"]
        ext["current"] = {
            "title": work["title"], "year": work["year"],
            "authors": json.loads(work["authors"]) if work["authors"] else [],
            "doi": work["doi"], "arxiv_id": work["arxiv_id"],
            "venue": work["venue"], "url": work["url"],
            "abstract": work["abstract"], "title_zh": work["title_zh"],
        }
    else:
        ext["work_title"] = ext["work_id"]
        ext["work_year"] = None
        ext["current"] = {}
    return ext


@router.get("/metadata")
def list_metadata(
    status: str = Query("pending"),
    risk: str = Query("all"),
    model: str = Query("all"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: str = Query(""),
    include_quarantined: bool = Query(False),
):
    conn = get_conn()
    try:
        ensure_metadata_review_columns(conn)

        # Base filter: exclude quarantined works unless requested
        quarantined_filter = "" if include_quarantined else "AND w.read_status != 'quarantined'"

        # Summary counts by review status (excluding quarantined works)
        summary = {}
        for s in ("pending", "approved", "needs_fix", "rejected"):
            count = conn.execute(
                f"SELECT COUNT(*) FROM metadata_extractions me "
                f"JOIN works w ON w.id = me.work_id "
                f"WHERE me.review_status = ? {quarantined_filter}",
                (s,),
            ).fetchone()[0]
            summary[s] = count
        summary["all"] = sum(summary.values())

        # Risk summary (follows status filter, excluding quarantined)
        risk_status_filter = "" if status == "all" else f"AND me.review_status = '{status}'"
        risk_summary = {}
        risk_total = conn.execute(
            f"SELECT COUNT(*) FROM metadata_extractions me "
            f"JOIN works w ON w.id = me.work_id "
            f"WHERE 1=1 {risk_status_filter} {quarantined_filter}",
        ).fetchone()[0]
        risk_summary["all"] = risk_total
        for r in ("low", "medium", "high"):
            risk_summary[r] = conn.execute(
                f"SELECT COUNT(*) FROM metadata_extractions me "
                f"JOIN works w ON w.id = me.work_id "
                f"WHERE me.risk_level = ? {risk_status_filter} {quarantined_filter}",
                (r,),
            ).fetchone()[0]
        summary["risk"] = risk_summary

        # Model summary (follows status filter, excluding quarantined)
        model_summary = {"all": risk_total}
        for m_label, m_pattern in [("mimo", "%mimo%"), ("ollama", "%qwen%")]:
            model_summary[m_label] = conn.execute(
                f"SELECT COUNT(*) FROM metadata_extractions me "
                f"JOIN works w ON w.id = me.work_id "
                f"WHERE me.model_name LIKE ? {risk_status_filter} {quarantined_filter}",
                (m_pattern,),
            ).fetchone()[0]
        summary["model"] = model_summary

        # Build query
        where = []
        params = []
        if not include_quarantined:
            where.append("w.read_status != 'quarantined'")
        if status != "all":
            where.append("me.review_status = ?")
            params.append(status)
        if risk != "all":
            where.append("me.risk_level = ?")
            params.append(risk)
        if model == "mimo":
            where.append("me.model_name LIKE ?")
            params.append("%mimo%")
        elif model == "ollama":
            where.append("me.model_name LIKE ?")
            params.append("%qwen%")
        if search:
            where.append("(me.work_id LIKE ? OR w.title LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])

        where_clause = ("WHERE " + " AND ".join(where)) if where else ""

        total = conn.execute(
            f"SELECT COUNT(*) FROM metadata_extractions me "
            f"JOIN works w ON w.id = me.work_id {where_clause}",
            params,
        ).fetchone()[0]

        offset = (page - 1) * per_page
        rows = conn.execute(
            f"SELECT me.* FROM metadata_extractions me "
            f"JOIN works w ON w.id = me.work_id {where_clause} "
            f"ORDER BY me.risk_score DESC, me.created_at DESC LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()

        extractions = [_enrich_extraction(dict(r), conn) for r in rows]

        return {
            "extractions": extractions,
            "total": total,
            "page": page,
            "per_page": per_page,
            "summary": summary,
        }
    finally:
        conn.close()


@router.get("/metadata/{ext_id}")
def get_metadata(ext_id: str):
    conn = get_conn()
    try:
        ensure_metadata_review_columns(conn)
        row = conn.execute(
            "SELECT * FROM metadata_extractions WHERE id = ?", (ext_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Extraction not found")
        return _enrich_extraction(dict(row), conn)
    finally:
        conn.close()


@router.patch("/metadata/{ext_id}/review")
def review_metadata(ext_id: str, body: MetadataReviewAction):
    VALID_STATUSES = {"approved", "needs_fix", "rejected"}
    if body.review_status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {body.review_status}")

    conn = get_conn()
    try:
        ensure_metadata_review_columns(conn)
        row = conn.execute(
            "SELECT * FROM metadata_extractions WHERE id = ?", (ext_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Extraction not found")

        ext = dict(row)
        extracted = json.loads(ext["extracted_json"]) if ext["extracted_json"] else {}

        confidence = json.loads(ext["confidence_json"]) if ext["confidence_json"] else {}

        # Merge edited fields into extracted_json and promote them to human-confirmed.
        if body.edited_fields:
            extracted.update(body.edited_fields)
            for field in body.edited_fields:
                if field in HUMAN_CONFIRMED_FIELDS:
                    confidence[field] = "high"
            # Recompute risk after edits
            work = conn.execute("SELECT title FROM works WHERE id = ?", (ext["work_id"],)).fetchone()
            current_title = work["title"] if work else None
            risk = compute_risk(extracted, confidence, [], current_title)
            conn.execute(
                "UPDATE metadata_extractions SET extracted_json = ?, confidence_json = ?, risk_level = ?, risk_score = ?, risk_reasons = ? WHERE id = ?",
                (json.dumps(extracted, ensure_ascii=False),
                 json.dumps(confidence, ensure_ascii=False),
                 risk["risk_level"], risk["risk_score"],
                 json.dumps(risk["risk_reasons"], ensure_ascii=False), ext_id),
            )

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if body.edited_fields:
            conn.execute(
                "UPDATE metadata_extractions SET review_status = ?, review_note = ?, reviewed_at = ?, review_source = 'human', fix_action = 'edited' WHERE id = ?",
                (body.review_status, body.review_note, now, ext_id),
            )
        else:
            conn.execute(
                "UPDATE metadata_extractions SET review_status = ?, review_note = ?, reviewed_at = ?, review_source = 'human' WHERE id = ?",
                (body.review_status, body.review_note, now, ext_id),
            )

        # Auto-apply on approved (skip if work is quarantined)
        applied = 0
        if body.review_status == "approved" and not ext.get("applied"):
            work_row = conn.execute(
                "SELECT read_status FROM works WHERE id = ?", (ext["work_id"],)
            ).fetchone()
            if work_row and work_row["read_status"] != "quarantined":
                applied = _apply_single(conn, ext_id, ext["work_id"], extracted, confidence)

        # Supersede other pending/needs_fix/approved-not-applied extractions for the same work
        if body.review_status == "approved":
            conn.execute(
                "UPDATE metadata_extractions SET review_status = 'rejected', "
                "review_note = 'superseded by approved extraction', "
                "reviewed_at = ?, review_source = 'system', fix_action = 'superseded' "
                "WHERE work_id = ? AND id != ? AND "
                "(review_status IN ('pending', 'needs_fix') OR (review_status = 'approved' AND applied = 0))",
                (now, ext["work_id"], ext_id),
            )

        conn.commit()
        return {"ok": True, "applied": applied}
    finally:
        conn.close()


@router.post("/metadata/apply-approved")
def apply_approved():
    conn = get_conn()
    try:
        ensure_metadata_review_columns(conn)
        rows = conn.execute(
            "SELECT me.* FROM metadata_extractions me "
            "JOIN works w ON w.id = me.work_id "
            "WHERE me.review_status = 'approved' AND me.applied = 0 "
            "AND w.read_status != 'quarantined'"
        ).fetchall()

        total_applied = 0
        for row in rows:
            ext = dict(row)
            extracted = json.loads(ext["extracted_json"]) if ext["extracted_json"] else {}
            confidence = json.loads(ext["confidence_json"]) if ext["confidence_json"] else {}
            applied = _apply_single(conn, ext["id"], ext["work_id"], extracted, confidence)
            if applied:
                total_applied += 1

        conn.commit()
        return {"ok": True, "applied": total_applied, "total_reviewed": len(rows)}
    finally:
        conn.close()


@router.post("/metadata/batch-approve-low-risk")
def batch_approve_low_risk():
    """Approve all pending low-risk extractions and apply them.
    Per work: only the best extraction (mimo > ollama) is applied;
    other pending extractions for the same work are superseded.
    """
    conn = get_conn()
    try:
        ensure_metadata_review_columns(conn)
        # Order: mimo first per work, so it wins the overwrite
        rows = conn.execute(
            "SELECT me.* FROM metadata_extractions me "
            "JOIN works w ON w.id = me.work_id "
            "WHERE me.review_status = 'pending' AND me.risk_level = 'low' "
            "AND w.read_status != 'quarantined' "
            "ORDER BY me.work_id, "
            "  CASE WHEN me.model_name LIKE '%mimo%' THEN 0 ELSE 1 END, "
            "  me.risk_score ASC"
        ).fetchall()

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        approved_count = 0
        applied_count = 0
        applied_works = set()  # track which works already had an extraction applied

        for row in rows:
            ext = dict(row)
            # Mark as approved
            conn.execute(
                "UPDATE metadata_extractions SET review_status = 'approved', reviewed_at = ?, review_source = 'batch_low_risk' WHERE id = ?",
                (now, ext["id"]),
            )
            approved_count += 1

            # Apply only the first extraction per work (mimo wins)
            if ext["work_id"] not in applied_works:
                extracted = json.loads(ext["extracted_json"]) if ext["extracted_json"] else {}
                confidence = json.loads(ext["confidence_json"]) if ext["confidence_json"] else {}
                applied = _apply_single(conn, ext["id"], ext["work_id"], extracted, confidence)
                if applied:
                    applied_count += 1
                    applied_works.add(ext["work_id"])

        # Supersede remaining pending extractions for works that were applied
        if applied_works:
            placeholders = ",".join("?" * len(applied_works))
            conn.execute(
                f"UPDATE metadata_extractions SET review_status = 'rejected', "
                f"review_note = 'superseded by batch approve', "
                f"reviewed_at = ?, review_source = 'system', fix_action = 'superseded' "
                f"WHERE work_id IN ({placeholders}) AND review_status = 'pending'",
                [now] + list(applied_works),
            )

        conn.commit()
        return {"ok": True, "approved": approved_count, "applied": applied_count}
    finally:
        conn.close()


@router.get("/metadata/agent/queue")
def agent_queue(
    status: str = Query("needs_fix"),
    limit: int = Query(50, ge=1, le=200),
):
    """Agent-facing: list extractions needing re-processing, grouped by error pattern."""
    conn = get_conn()
    try:
        ensure_metadata_review_columns(conn)
        rows = conn.execute(
            "SELECT me.*, w.title AS work_title FROM metadata_extractions me "
            "JOIN works w ON w.id = me.work_id "
            "WHERE me.review_status = ? AND w.read_status != 'quarantined' "
            "ORDER BY me.risk_score DESC LIMIT ?",
            (status, limit),
        ).fetchall()

        items = []
        for row in rows:
            ext = dict(row)
            ext["extracted_json"] = json.loads(ext["extracted_json"]) if ext["extracted_json"] else {}
            ext["risk_reasons"] = json.loads(ext["risk_reasons"]) if ext.get("risk_reasons") else []
            items.append(ext)

        # Cluster by risk_reasons patterns
        clusters: dict[str, list] = {}
        for item in items:
            for reason in item["risk_reasons"]:
                # Extract pattern key (first part before ':')
                pattern = reason.split(":")[0].strip()
                clusters.setdefault(pattern, []).append(item["id"])

        return {"items": items, "total": len(items), "clusters": clusters}
    finally:
        conn.close()


@router.post("/metadata/{ext_id}/quarantine")
def quarantine_from_review(ext_id: str, body: QuarantineAction):
    """Quarantine a work from the metadata review page.

    Marks the current extraction as rejected with fix_action='quarantined',
    sets the work read_status to quarantined, writes a work_codes entry,
    and marks all pending extractions for that work as rejected+quarantined.
    Source file movement is handled by the existing works quarantine logic.
    """
    if not body.reason or body.reason not in QUARANTINE_REASONS:
        raise HTTPException(
            status_code=400,
            detail=f"reason is required and must be one of: {', '.join(sorted(QUARANTINE_REASONS))}",
        )

    conn = get_conn()
    try:
        ensure_metadata_review_columns(conn)
        row = conn.execute(
            "SELECT * FROM metadata_extractions WHERE id = ?", (ext_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Extraction not found")

        ext = dict(row)
        work_id = ext["work_id"]
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        # Mark current extraction as rejected + quarantined
        conn.execute(
            "UPDATE metadata_extractions SET review_status = 'rejected', "
            "review_source = 'human', fix_action = 'quarantined', "
            "review_note = ?, reviewed_at = ? WHERE id = ?",
            (body.reason, now, ext_id),
        )

        # Mark all other pending extractions for this work as rejected + quarantined
        # Don't overwrite existing review_note — only set if empty
        conn.execute(
            "UPDATE metadata_extractions SET review_status = 'rejected', "
            "review_source = 'human', fix_action = 'quarantined', "
            "review_note = CASE WHEN review_note IS NULL OR review_note = '' THEN ? ELSE review_note END, "
            "reviewed_at = ? "
            "WHERE work_id = ? AND review_status = 'pending' AND id != ?",
            (body.reason, now, work_id, ext_id),
        )

        # Also block approved-but-not-yet-applied extractions
        conn.execute(
            "UPDATE metadata_extractions SET review_status = 'rejected', "
            "review_source = 'human', fix_action = 'quarantined', "
            "review_note = CASE WHEN review_note IS NULL OR review_note = '' THEN ? ELSE review_note END, "
            "reviewed_at = ? "
            "WHERE work_id = ? AND review_status = 'approved' AND applied = 0 AND id != ?",
            (body.reason, now, work_id, ext_id),
        )

        # Update work status to quarantined
        conn.execute(
            "UPDATE works SET read_status = 'quarantined', updated_at = ? WHERE id = ?",
            (now, work_id),
        )

        # Write work_codes quarantine reason
        if table_exists(conn, "work_codes"):
            try:
                conn.execute(
                    "INSERT INTO work_codes (work_id, source_file_id, code, reason) "
                    "VALUES (?, '', 'quarantined', ?)",
                    (work_id, body.reason),
                )
            except Exception:
                pass  # Duplicate code entry is fine

        # Move source files to _quarantine/{work_id}/
        quarantine_dir = LIBRARY_ROOT / "_quarantine" / work_id
        sources = conn.execute(
            "SELECT id, source_path, original_name FROM source_files WHERE work_id = ?",
            (work_id,),
        ).fetchall()
        for s in sources:
            src = Path(s["source_path"])
            if src.exists():
                quarantine_dir.mkdir(parents=True, exist_ok=True)
                dest = quarantine_dir / (s["original_name"] or src.name)
                shutil.move(str(src), str(dest))
                conn.execute(
                    "UPDATE source_files SET source_path = ? WHERE id = ?",
                    (str(dest), s["id"]),
                )

        conn.commit()
        return {"ok": True, "work_id": work_id}
    finally:
        conn.close()


@router.post("/metadata/{ext_id}/supersede")
def supersede_extraction(ext_id: str, body: MetadataSupersedeAction):
    """Create a superseding extraction from explicit replacement fields.

    True model reruns are handled by scripts/literature_metadata_rerun.py --rerun,
    which calls Ollama and writes a new extraction with a fresh raw_response.
    This endpoint is for externally supplied corrections, not a model call.
    """
    if not body.edited_fields:
        raise HTTPException(
            status_code=400,
            detail="edited_fields is required; use literature_metadata_rerun.py --rerun for model reruns",
        )

    conn = get_conn()
    try:
        ensure_metadata_review_columns(conn)
        row = conn.execute(
            "SELECT * FROM metadata_extractions WHERE id = ?", (ext_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Extraction not found")

        ext = dict(row)
        extracted = json.loads(ext["extracted_json"]) if ext["extracted_json"] else {}
        confidence = json.loads(ext["confidence_json"]) if ext["confidence_json"] else {}

        extracted.update(body.edited_fields)
        for field in body.edited_fields:
            if field in HUMAN_CONFIRMED_FIELDS:
                confidence[field] = "high"

        # Compute risk for new extraction
        work = conn.execute("SELECT title FROM works WHERE id = ?", (ext["work_id"],)).fetchone()
        current_title = work["title"] if work else None
        risk = compute_risk(extracted, confidence, [], current_title)

        # Create new extraction record
        new_id = f"ME-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn.execute("""
            INSERT INTO metadata_extractions
            (id, work_id, model_name, content_md_path, input_chars, input_tokens_est,
             raw_response, extracted_json, confidence_json, applied,
             review_status, review_source, risk_level, risk_score, risk_reasons,
             review_note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'pending', 'agent', ?, ?, ?, ?, ?)
        """, (
            new_id, ext["work_id"], ext["model_name"], ext["content_md_path"],
            ext["input_chars"], ext["input_tokens_est"], ext["raw_response"],
            json.dumps(extracted, ensure_ascii=False),
            json.dumps(confidence, ensure_ascii=False),
            risk["risk_level"], risk["risk_score"],
            json.dumps(risk["risk_reasons"], ensure_ascii=False),
            body.review_note or f"superseded by agent from {ext_id}", now,
        ))

        # Mark old extraction as superseded
        conn.execute(
            "UPDATE metadata_extractions SET superseded_by = ?, fix_action = 'rerun_requested' WHERE id = ?",
            (new_id, ext_id),
        )

        conn.commit()
        return {"ok": True, "new_extraction_id": new_id}
    finally:
        conn.close()


def _apply_single(conn, ext_id: str, work_id: str, extracted: dict, confidence: dict) -> int:
    """Overwrite apply for one extraction. Returns 1 if work was updated."""
    current = conn.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
    if not current:
        return 0

    sets = []
    params = []
    for field, col in APPLY_FIELDS.items():
        conf = confidence.get(field) if isinstance(confidence, dict) else None
        if conf not in ("high", "medium"):
            continue
        value = extracted.get(field)
        if value is None or value == "":
            continue
        # Serialize complex fields
        if field == "authors" and isinstance(value, list):
            value = json.dumps(value, ensure_ascii=False)
        elif field == "contributors" and isinstance(value, list):
            value = json.dumps(value, ensure_ascii=False)
        elif field == "publication_date" and isinstance(value, dict):
            value = json.dumps(value, ensure_ascii=False)
        sets.append(f"{col} = ?")
        params.append(value)

    if sets:
        params.append(work_id)
        conn.execute(
            f"UPDATE works SET {', '.join(sets)}, updated_at = datetime('now') WHERE id = ?",
            params,
        )
        conn.execute(
            "UPDATE metadata_extractions SET applied = 1, applied_at = datetime('now') WHERE id = ?",
            (ext_id,),
        )
        return 1
    return 0
