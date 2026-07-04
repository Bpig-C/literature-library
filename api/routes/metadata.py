"""Metadata review API routes."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..db import get_conn, ensure_metadata_review_columns, table_exists, LIBRARY_ROOT
from ..metadata_template import (
    build_metadata_system_prompt,
    build_metadata_user_prompt,
    get_metadata_template,
    normalize_metadata_fields,
    valid_rerun_fields,
)
from ..models import MetadataReviewAction, MetadataSupersedeAction, QuarantineAction
from ..risk import compute_risk
from ..security import build_status_filter, validate_status

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
    sort: str = Query("created_at"),
    order: str = Query("desc"),
):
    conn = get_conn()
    try:
        ensure_metadata_review_columns(conn)
        validate_status(status)

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
        risk_status_sql, risk_status_params = build_status_filter(status, "me.review_status")
        risk_summary = {}
        risk_total = conn.execute(
            f"SELECT COUNT(*) FROM metadata_extractions me "
            f"JOIN works w ON w.id = me.work_id "
            f"WHERE 1=1 {risk_status_sql} {quarantined_filter}",
            risk_status_params,
        ).fetchone()[0]
        risk_summary["all"] = risk_total
        for r in ("low", "medium", "high"):
            risk_summary[r] = conn.execute(
                f"SELECT COUNT(*) FROM metadata_extractions me "
                f"JOIN works w ON w.id = me.work_id "
                f"WHERE me.risk_level = ? {risk_status_sql} {quarantined_filter}",
                [r] + risk_status_params,
            ).fetchone()[0]
        summary["risk"] = risk_summary

        # Model summary (follows status filter, excluding quarantined)
        model_summary = {"all": risk_total}
        for m_label, m_pattern in [("mimo", "%mimo%"), ("ollama", "%qwen%")]:
            model_summary[m_label] = conn.execute(
                f"SELECT COUNT(*) FROM metadata_extractions me "
                f"JOIN works w ON w.id = me.work_id "
                f"WHERE me.model_name LIKE ? {risk_status_sql} {quarantined_filter}",
                [m_pattern] + risk_status_params,
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

        sort_col = {
            "created_at": "me.created_at",
            "risk_score": "me.risk_score",
            "work_title": "w.title",
        }.get(sort, "me.created_at")
        sort_dir = "DESC" if order.lower() == "desc" else "ASC"

        rows = conn.execute(
            f"SELECT me.* FROM metadata_extractions me "
            f"JOIN works w ON w.id = me.work_id {where_clause} "
            f"ORDER BY {sort_col} {sort_dir} LIMIT ? OFFSET ?",
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

        # Move sources + sync works/source_files status via the shared nucleus.
        # Strict: a missing source file 409s before any change (no half-isolation).
        from ..quarantine import quarantine_work_sources
        quarantine_work_sources(
            conn, LIBRARY_ROOT, work_id, reason=body.reason, code="quarantined"
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
    """Fill-empty apply for one extraction. Returns 1 if work was updated.

    Only writes fields where works table is empty/null, matching classification
    apply semantics. This preserves human-edited values in works table.
    """
    current = conn.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
    if not current:
        return 0

    sets = []
    params = []
    for field, col in APPLY_FIELDS.items():
        conf = confidence.get(field) if isinstance(confidence, dict) else None
        # title_zh: apply even when confidence is None (historical data has None)
        if conf not in ("high", "medium") and field != "title_zh":
            continue
        value = extracted.get(field)
        if value is None or value == "":
            continue
        # Fill-empty: skip if works already has this value
        existing = current[col] if col in current.keys() else None
        if existing:
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

    # Sync year from publication_date_json if year is not already set
    pdj = extracted.get("publication_date")
    if isinstance(pdj, dict) and pdj.get("year") and not current["year"]:
        sets.append("year = ?")
        params.append(pdj["year"])

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


# ---------------------------------------------------------------------------
# Extraction trigger endpoint
# ---------------------------------------------------------------------------

class ExtractRequest(BaseModel):
    work_ids: list[str] | None = None
    force: bool = False
    limit: int = 5


@router.post("/metadata/extract")
def trigger_metadata_extraction(body: ExtractRequest):
    """Thin adapter: trigger metadata extraction for specific works or a small batch.

    Reuses scripts.literature_metadata_extract nucleus logic.
    """
    import sys
    from pathlib import Path as P

    # Ensure scripts package is importable
    scripts_dir = str(LIBRARY_ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    from scripts.literature_metadata_extract import (
        get_works_to_process,
        connect_db,
        llm_judge,
        validate_extraction,
        compute_risk,
        rough_token_count,
        INPUT_CHAR_BUDGET,
        parse_llm_json,
    )
    import uuid as _uuid

    conn = connect_db()
    try:
        # Determine which works to process
        if body.work_ids:
            works = []
            for wid in body.work_ids:
                w = get_works_to_process(conn, limit=None, work_id=wid, force=body.force)
                works.extend(w)
        else:
            works = get_works_to_process(conn, limit=body.limit, work_id=None, force=body.force)

        if not works:
            return {
                "ok": True,
                "created": 0,
                "skipped": 0,
                "failed": [],
                "message": "没有需要处理的文献（可能已有 recent extraction，尝试 force=true）",
            }

        created = 0
        skipped = 0
        failed = []
        metadata_template = get_metadata_template()
        system_prompt = build_metadata_system_prompt(metadata_template)

        for w in works:
            work_id = w["id"]
            content_path = P(w["content_md_path"])

            if not content_path.exists():
                skipped += 1
                failed.append({"work_id": work_id, "error": f"content.md 不存在: {content_path}"})
                continue

            try:
                raw_text = content_path.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                skipped += 1
                failed.append({"work_id": work_id, "error": f"读取失败: {e}"})
                continue

            text = raw_text[:INPUT_CHAR_BUDGET]
            input_tokens = rough_token_count(text)

            user_msg = build_metadata_user_prompt(text, metadata_template)
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ]

            try:
                resp = llm_judge.chat(messages, timeout=120)
                raw_response = resp.get("message", {}).get("content", "")
            except Exception as e:
                skipped += 1
                failed.append({"work_id": work_id, "error": f"LLM 调用失败: {e}"})
                continue

            extracted = parse_llm_json(raw_response)
            if not extracted:
                skipped += 1
                failed.append({"work_id": work_id, "error": "无法解析 LLM JSON 响应"})
                continue

            try:
                extracted, validation_warnings = validate_extraction(extracted)
            except Exception as e:
                skipped += 1
                failed.append({"work_id": work_id, "error": f"验证失败: {e}"})
                continue

            confidence = extracted.get("confidence", {})
            risk = compute_risk(extracted, confidence, validation_warnings, w.get("title"))

            ext_id = f"ME-{_uuid.uuid4().hex[:12]}"
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")

            conn.execute("""
                INSERT INTO metadata_extractions
                (id, work_id, model_name, content_md_path, input_chars, input_tokens_est,
                 raw_response, extracted_json, confidence_json, applied,
                 risk_level, risk_score, risk_reasons, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
            """, (
                ext_id, work_id, "mimo-v2.5-pro", str(content_path),
                len(text), input_tokens,
                raw_response, json.dumps(extracted, ensure_ascii=False),
                json.dumps(confidence, ensure_ascii=False),
                risk["risk_level"], risk["risk_score"],
                json.dumps(risk["risk_reasons"], ensure_ascii=False), now,
            ))
            conn.commit()
            created += 1

        return {
            "ok": True,
            "created": created,
            "skipped": skipped,
            "failed": failed,
            "next": {
                "metadata_review": "/metadata?status=pending",
            },
        }
    finally:
        conn.close()


# ============================================================
# UX-004: 字段级重抽 API 端点
# ============================================================

class RerunPreviewRequest(BaseModel):
    """重抽预览请求体"""
    fields: list[str]  # 要重抽的字段列表
    review_note: str = ""  # 可选的审核备注


class RerunApplyRequest(BaseModel):
    """确认应用重抽结果"""
    preview_id: str  # preview 返回的临时 ID
    new_extraction: dict  # preview 返回的完整新记录


@router.post("/metadata/{ext_id}/rerun-preview")
async def rerun_metadata_fields_preview(ext_id: str, body: RerunPreviewRequest):
    """
    预览重抽结果（不写入数据库）。

    流程: 查询原记录 → 调 LLM 重抽指定字段 → 返回新旧值对比
    用户确认后调用 /{ext_id}/rerun-apply 写入。
    """
    from scripts.literature_metadata_rerun import (
        build_new_extraction,
        extraction_by_id,
    )

    # 校验字段合法性
    allowed_fields = valid_rerun_fields()
    invalid = [f for f in body.fields if f not in allowed_fields]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Invalid fields: {', '.join(invalid)}")

    if not body.fields:
        raise HTTPException(status_code=400, detail="fields must be non-empty")
    fields = normalize_metadata_fields(body.fields)

    conn = get_conn()
    try:
        ensure_metadata_review_columns(conn)
        ext = extraction_by_id(conn, ext_id)
        if not ext:
            raise HTTPException(status_code=404, detail=f"Extraction not found: {ext_id}")

        # 执行重抽（不写入DB）
        rerun_ext = dict(ext)
        if body.review_note.strip():
            rerun_ext["review_note"] = body.review_note.strip()
        try:
            new_ext = build_new_extraction(
                rerun_ext,
                fields=fields,
                model="mimo-2.5-pro",
                url="",
                timeout=300,
            )
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

        # 构建对比数据
        old_data = ext.get("extracted_json", {})
        new_data = new_ext["extracted_json"]

        diff = {}
        for field in fields:
            diff[field] = {
                "old": old_data.get(field),
                "new": new_data.get(field),
                "changed": old_data.get(field) != new_data.get(field),
            }

        return {
            "preview_id": new_ext["id"],
            "fields": fields,
            "diff": diff,
            "new_extraction": new_ext,
            "risk": new_ext["risk"],
        }
    finally:
        conn.close()


@router.post("/metadata/{ext_id}/rerun-apply")
async def apply_rerun_result(ext_id: str, body: RerunApplyRequest):
    """用户确认后，将预览结果写入数据库（supersede 旧记录）。"""
    from scripts.literature_metadata_rerun import (
        write_superseding_extraction,
        extraction_by_id,
    )

    if body.preview_id != body.new_extraction.get("id"):
        raise HTTPException(status_code=400, detail="preview_id does not match new_extraction.id")

    conn = get_conn()
    try:
        ensure_metadata_review_columns(conn)
        # 验证原记录存在
        ext = extraction_by_id(conn, ext_id)
        if not ext:
            raise HTTPException(status_code=404, detail=f"Extraction not found: {ext_id}")
        if body.new_extraction.get("old_id") != ext_id:
            raise HTTPException(status_code=400, detail="new_extraction.old_id does not match ext_id")
        if body.new_extraction.get("work_id") != ext["work_id"]:
            raise HTTPException(status_code=400, detail="new_extraction.work_id does not match original extraction")
        existing = conn.execute(
            "SELECT 1 FROM metadata_extractions WHERE id = ?", (body.new_extraction["id"],)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="rerun preview has already been applied")

        # 写入新记录（自动 supersede 旧记录）
        write_superseding_extraction(conn, body.new_extraction)

        # 返回最终写入的记录（直接从 DB 查询原始行，再 enrich）
        final_row = conn.execute(
            "SELECT * FROM metadata_extractions WHERE id = ?", (body.new_extraction["id"],)
        ).fetchone()
        if not final_row:
            raise HTTPException(status_code=500, detail="Failed to retrieve written record")
        return _enrich_extraction(dict(final_row), conn)
    finally:
        conn.close()


@router.get("/metadata/{ext_id}/rerun-prompt")
async def get_rerun_prompt(
    ext_id: str,
    fields: str = Query(...),
    review_note: str = Query(""),
):
    """
    生成指定字段的 Prompt（降级方案：复制到手动工具处理）。

    用法: GET /api/metadata/{ext_id}/rerun-prompt?fields=title,abstract
    返回: { prompt: "...", fields: [...], content_chars: int, content_preview: "..." }
    """
    from scripts.literature_metadata_rerun import (
        field_focus_instruction,
        extraction_by_id,
    )
    from scripts.literature_metadata_extract import INPUT_CHAR_BUDGET
    from pathlib import Path

    field_list = [f.strip() for f in fields.split(",") if f.strip()]
    allowed_fields = valid_rerun_fields()
    invalid = [f for f in field_list if f not in allowed_fields]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Invalid fields: {', '.join(invalid)}")

    if not field_list:
        raise HTTPException(status_code=400, detail="fields must be non-empty")
    field_list = normalize_metadata_fields(field_list)

    conn = get_conn()
    try:
        ensure_metadata_review_columns(conn)
        ext = extraction_by_id(conn, ext_id)
        if not ext:
            raise HTTPException(status_code=404, detail=f"Extraction not found: {ext_id}")

        # 读取 content.md
        content_path = Path(ext["content_md_path"])
        if not content_path.exists():
            raise HTTPException(status_code=404, detail="content.md not found")

        raw_text = content_path.read_text(encoding="utf-8", errors="replace")
        text = raw_text[:INPUT_CHAR_BUDGET]

        # 构建 prompt
        base_prompt = build_metadata_user_prompt(text, get_metadata_template())
        focus_instr = field_focus_instruction(field_list, review_note.strip() or ext.get("review_note") or "")
        full_prompt = base_prompt + focus_instr

        return {
            "prompt": full_prompt,
            "fields": field_list,
            "content_chars": len(text),
            "content_preview": text[:500],
        }
    finally:
        conn.close()
