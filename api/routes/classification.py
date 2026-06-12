"""Classification API routes: tags CRUD, batch operations, vocab endpoint."""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..db import LIBRARY_ROOT, get_conn, table_exists
from ..models import QuarantineAction
from ..classification_vocab import get_vocab, validate_tag_value
from ..classification_ambiguity import compute_ambiguity

router = APIRouter()

QUARANTINE_REASONS = {"bad_source", "out_of_scope", "not_literature", "duplicate_residual", "user_removed", "needs_rerun"}


class TagCreate(BaseModel):
    tag_group: str
    tag_value: str
    source: str = "human"
    confidence: str | None = None
    evidence: str | None = None
    notes: str | None = None


class TagBatchCreate(BaseModel):
    tags: list[TagCreate]


class TagReview(BaseModel):
    review_status: str  # approved / rejected
    review_note: str = ""


def _make_tag_id() -> str:
    return f"CT-{uuid.uuid4().hex[:12]}"


@router.get("/classification/tags/{work_id}")
def get_tags(work_id: str):
    conn = get_conn()
    try:
        row = conn.execute("SELECT 1 FROM works WHERE id = ?", (work_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Work not found")
        tags = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM work_classification_tags WHERE work_id = ? ORDER BY tag_group, tag_value",
                (work_id,),
            ).fetchall()
        ]
        return {"tags": tags, "total": len(tags)}
    finally:
        conn.close()


@router.post("/classification/tags/{work_id}")
def create_tag(work_id: str, body: TagCreate):
    if not validate_tag_value(body.tag_group, body.tag_value):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid tag_value '{body.tag_value}' for tag_group '{body.tag_group}'",
        )
    conn = get_conn()
    try:
        row = conn.execute("SELECT 1 FROM works WHERE id = ?", (work_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Work not found")

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        tag_id = _make_tag_id()
        conn.execute(
            "INSERT INTO work_classification_tags "
            "(id, work_id, tag_group, tag_value, source, confidence, evidence, notes, "
            "review_status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'approved', ?, ?)",
            (tag_id, work_id, body.tag_group, body.tag_value,
             body.source, body.confidence, body.evidence, body.notes, now, now),
        )
        conn.commit()
        return {"ok": True, "tag_id": tag_id}
    finally:
        conn.close()


@router.post("/classification/tags/{work_id}/batch")
def create_tags_batch(work_id: str, body: TagBatchCreate):
    conn = get_conn()
    try:
        row = conn.execute("SELECT 1 FROM works WHERE id = ?", (work_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Work not found")

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        created = []
        for tag in body.tags:
            if not validate_tag_value(tag.tag_group, tag.tag_value):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid tag_value '{tag.tag_value}' for tag_group '{tag.tag_group}'",
                )
            tag_id = _make_tag_id()
            conn.execute(
                "INSERT INTO work_classification_tags "
                "(id, work_id, tag_group, tag_value, source, confidence, evidence, notes, "
                "review_status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'approved', ?, ?)",
                (tag_id, work_id, tag.tag_group, tag.tag_value,
                 tag.source, tag.confidence, tag.evidence, tag.notes, now, now),
            )
            created.append(tag_id)
        conn.commit()
        return {"ok": True, "created": len(created), "tag_ids": created}
    finally:
        conn.close()


@router.delete("/classification/tags/{tag_id}")
def delete_tag(tag_id: str):
    conn = get_conn()
    try:
        row = conn.execute("SELECT 1 FROM work_classification_tags WHERE id = ?", (tag_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Tag not found")
        conn.execute("DELETE FROM work_classification_tags WHERE id = ?", (tag_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@router.patch("/classification/tags/{tag_id}/review")
def review_tag(tag_id: str, body: TagReview):
    if body.review_status not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="review_status must be 'approved' or 'rejected'")
    conn = get_conn()
    try:
        row = conn.execute("SELECT 1 FROM work_classification_tags WHERE id = ?", (tag_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Tag not found")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn.execute(
            "UPDATE work_classification_tags SET review_status = ?, reviewed_at = ?, notes = COALESCE(?, notes) WHERE id = ?",
            (body.review_status, now, body.review_note or None, tag_id),
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@router.get("/classification/vocab")
def vocab():
    return get_vocab()


# ---------------------------------------------------------------------------
# Classification extractions CRUD + review
# ---------------------------------------------------------------------------

class ExtractionReview(BaseModel):
    review_status: str  # approved / needs_fix / rejected
    review_note: str = ""
    edited_fields: dict | None = None


class ExtractionDraft(BaseModel):
    review_note: str = ""
    edited_fields: dict | None = None


def _enrich_extraction(row: dict, conn) -> dict:
    """Parse JSON fields and add work info."""
    ext = dict(row)
    ext["extracted_json"] = json.loads(ext["extracted_json"]) if ext["extracted_json"] else {}
    ext["confidence_json"] = json.loads(ext["confidence_json"]) if ext["confidence_json"] else {}
    ext["ambiguity_reasons"] = json.loads(ext["ambiguity_reasons"]) if ext.get("ambiguity_reasons") else []

    work = conn.execute(
        "SELECT title, year, doc_type, primary_doc_type, secondary_doc_type, read_status, "
        "authors, venue, arxiv_id, doi, url, abstract, "
        "title_zh, language, contributors, publication_status, ingestion_state, priority, "
        "publication_date_json "
        "FROM works WHERE id = ?",
        (ext["work_id"],)
    ).fetchone()
    if work:
        ext["work_title"] = work["title"] or ext["work_id"]
        ext["work_year"] = work["year"]
        ext["work_publication_date_json"] = work["publication_date_json"]
        ext["work_doc_type"] = work["doc_type"]
        ext["work_primary_doc_type"] = work["primary_doc_type"]
        ext["work_secondary_doc_type"] = work["secondary_doc_type"]
        ext["work_read_status"] = work["read_status"]
        ext["work_authors"] = work["authors"]
        ext["work_venue"] = work["venue"]
        ext["work_arxiv_id"] = work["arxiv_id"]
        ext["work_doi"] = work["doi"]
        ext["work_url"] = work["url"]
        ext["work_abstract"] = work["abstract"]
        ext["work_title_zh"] = work["title_zh"]
        ext["work_language"] = work["language"]
        ext["work_publication_status"] = work["publication_status"]
        ext["work_ingestion_state"] = work["ingestion_state"]
        ext["work_priority"] = work["priority"]

        # --- Display helpers ---
        # Parse authors JSON to readable string
        authors_raw = work["authors"]
        if authors_raw:
            try:
                authors_list = json.loads(authors_raw) if isinstance(authors_raw, str) else authors_raw
                if isinstance(authors_list, list):
                    # Handle both ["name"] and [{"name":"...","affiliations":[...]}]
                    names = []
                    for a in authors_list:
                        if isinstance(a, str):
                            names.append(a)
                        elif isinstance(a, dict):
                            names.append(a.get("name", str(a)))
                    ext["work_authors_display"] = "; ".join(names)
                else:
                    ext["work_authors_display"] = str(authors_list)
            except (json.JSONDecodeError, TypeError):
                ext["work_authors_display"] = str(authors_raw)
        else:
            ext["work_authors_display"] = None

        # Parse publication_date_json to display string
        pdj_str = work["publication_date_json"]
        if pdj_str:
            try:
                pdj = json.loads(pdj_str) if isinstance(pdj_str, str) else pdj_str
                if isinstance(pdj, dict):
                    parts = []
                    if pdj.get("year"):
                        parts.append(f"{pdj['year']}年")
                    if pdj.get("month"):
                        parts.append(f"{pdj['month']}月")
                    if pdj.get("day"):
                        parts.append(f"{pdj['day']}日")
                    ext["work_date_display"] = "".join(parts) if parts else None
                else:
                    ext["work_date_display"] = None
            except (json.JSONDecodeError, TypeError):
                ext["work_date_display"] = None
        else:
            ext["work_date_display"] = None

        # Institutions from metadata_extractions (approved/latest only)
        inst_row = conn.execute("""
            SELECT json_extract(me.extracted_json, '$.institutions') as institutions
            FROM metadata_extractions me
            WHERE me.work_id = ?
            AND me.review_status = 'approved'
            AND json_extract(me.extracted_json, '$.institutions') IS NOT NULL
            ORDER BY me.created_at DESC LIMIT 1
        """, (ext["work_id"],)).fetchone()
        if inst_row and inst_row[0]:
            try:
                ext["work_institutions"] = json.loads(inst_row[0])
            except (json.JSONDecodeError, TypeError):
                ext["work_institutions"] = None
        else:
            ext["work_institutions"] = None
        ext["work_language"] = work["language"]
        ext["work_publication_status"] = work["publication_status"]
        ext["work_ingestion_state"] = work["ingestion_state"]
        ext["work_priority"] = work["priority"]

        # Parse contributors JSON
        contribs_raw = work["contributors"]
        if contribs_raw:
            try:
                ext["work_contributors"] = json.loads(contribs_raw) if isinstance(contribs_raw, str) else contribs_raw
            except (json.JSONDecodeError, TypeError):
                ext["work_contributors"] = None
        else:
            ext["work_contributors"] = None
    return ext


@router.get("/classification/extractions")
def list_extractions(
    status: str = Query("pending"),
    priority: str = Query(""),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: str = Query(""),
    include_quarantined: bool = Query(False),
    sort: str = Query("created_at"),
    order: str = Query("desc"),
):
    conn = get_conn()
    try:
        where_parts = []
        params: list = []

        if not include_quarantined:
            where_parts.append("w.read_status != 'quarantined'")

        if status != "all":
            where_parts.append("ce.review_status = ?")
            params.append(status)

        if search:
            where_parts.append("(ce.work_id LIKE ? OR w.title LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])

        if priority:
            where_parts.append("w.priority = ?")
            params.append(priority)

        where_sql = " AND ".join(where_parts) if where_parts else "1=1"

        # Count
        count_row = conn.execute(f"""
            SELECT COUNT(*) as cnt
            FROM classification_extractions ce
            JOIN works w ON w.id = ce.work_id
            WHERE {where_sql}
        """, params).fetchone()
        total = count_row["cnt"]

        # Summary counts
        summary = {}
        quarantined_filter = "" if include_quarantined else "AND w.read_status != 'quarantined'"
        for s in ("pending", "approved", "needs_fix", "rejected"):
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM classification_extractions ce "
                "JOIN works w ON w.id = ce.work_id "
                f"WHERE ce.review_status = ? {quarantined_filter}",
                (s,)
            ).fetchone()
            summary[s] = row["cnt"]
        summary["all"] = sum(summary.values())
        summary["quarantined"] = conn.execute(
            "SELECT COUNT(*) as cnt FROM classification_extractions ce "
            "JOIN works w ON w.id = ce.work_id "
            "WHERE w.read_status = 'quarantined'"
        ).fetchone()["cnt"]

        # Ambiguity summary (follows status filter, non-overlapping ranges)
        ambiguity_status_filter = "" if status == "all" else f"AND ce.review_status = '{status}'"
        for level, (lo, hi) in [("high", (50, 10000)), ("medium", (20, 50)), ("low", (0, 20))]:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM classification_extractions ce "
                "JOIN works w ON w.id = ce.work_id "
                f"WHERE ce.ambiguity_score >= ? AND ce.ambiguity_score < ? {ambiguity_status_filter} {quarantined_filter}",
                (lo, hi)
            ).fetchone()
            summary.setdefault("ambiguity", {})[level] = row["cnt"]

        # Priority summary (follows status filter)
        priority_status_filter = "" if status == "all" else f"AND ce.review_status = '{status}'"
        for p in ("P0", "P1", "P2", "P3", "archive"):
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM classification_extractions ce "
                "JOIN works w ON w.id = ce.work_id "
                f"WHERE w.priority = ? {priority_status_filter} {quarantined_filter}",
                (p,)
            ).fetchone()
            summary.setdefault("priority", {})[p] = row["cnt"]

        # Sort
        sort_col = {
            "created_at": "ce.created_at",
            "ambiguity_score": "ce.ambiguity_score",
            "work_title": "w.title",
        }.get(sort, "ce.created_at")
        sort_dir = "DESC" if order.lower() == "desc" else "ASC"

        # Fetch page
        rows = conn.execute(f"""
            SELECT ce.*
            FROM classification_extractions ce
            JOIN works w ON w.id = ce.work_id
            WHERE {where_sql}
            ORDER BY {sort_col} {sort_dir}
            LIMIT ? OFFSET ?
        """, params + [limit, offset]).fetchall()

        extractions = [_enrich_extraction(dict(r), conn) for r in rows]

        return {
            "extractions": extractions,
            "total": total,
            "summary": summary,
        }
    finally:
        conn.close()


@router.get("/classification/extractions/{ext_id}")
def get_extraction(ext_id: str):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM classification_extractions WHERE id = ?", (ext_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Extraction not found")
        return _enrich_extraction(dict(row), conn)
    finally:
        conn.close()


@router.patch("/classification/extractions/{ext_id}/save-draft")
def save_extraction_draft(ext_id: str, body: ExtractionDraft):
    """Save edited fields without changing review status."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM classification_extractions WHERE id = ?", (ext_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Extraction not found")

        ext = dict(row)
        extracted = json.loads(ext["extracted_json"]) if ext["extracted_json"] else {}
        confidence = json.loads(ext["confidence_json"]) if ext["confidence_json"] else {}

        # Merge edited fields with diff-based confidence promotion (D2 fix)
        if body.edited_fields:
            for k, v in body.edited_fields.items():
                if k in ("extracted_json", "confidence_json"):
                    continue
                old_value = extracted.get(k)
                if old_value != v:
                    extracted[k] = v
                    confidence[k] = "high"

        # Merge dual-source confidence before recomputing (D1 read-side fix)
        embedded_confidence = extracted.get("confidence", {})
        merged_confidence = {**embedded_confidence, **confidence}

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        # Recompute ambiguity with merged confidence
        new_amb = compute_ambiguity(extracted, merged_confidence)

        # Sync confidence_json back
        conn.execute(
            "UPDATE classification_extractions SET extracted_json = ?, "
            "confidence_json = ?, ambiguity_score = ?, ambiguity_reasons = ?, updated_at = ? WHERE id = ?",
            (json.dumps(extracted, ensure_ascii=False),
             json.dumps(confidence, ensure_ascii=False),
             new_amb["score"],
             json.dumps(new_amb["reasons"], ensure_ascii=False),
             now, ext_id),
        )
        conn.commit()
        return {"ok": True, "ambiguity_score": new_amb["score"], "reasons": new_amb["reasons"]}
    finally:
        conn.close()


@router.patch("/classification/extractions/{ext_id}/review")
def review_extraction(ext_id: str, body: ExtractionReview):
    VALID_STATUSES = {"approved", "needs_fix", "rejected"}
    if body.review_status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"review_status must be one of {VALID_STATUSES}",
        )

    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM classification_extractions WHERE id = ?", (ext_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Extraction not found")

        ext = dict(row)
        work_row = conn.execute(
            "SELECT read_status FROM works WHERE id = ?", (ext["work_id"],)
        ).fetchone()
        is_quarantined = bool(work_row and work_row["read_status"] == "quarantined")

        # Short-circuit: if already approved and applied, skip re-processing
        if ext["review_status"] == "approved" and ext.get("applied"):
            return {"ok": True, "note": "already approved and applied"}

        extracted = json.loads(ext["extracted_json"]) if ext["extracted_json"] else {}
        confidence = json.loads(ext["confidence_json"]) if ext["confidence_json"] else {}

        # Merge edited fields with diff-based confidence promotion (D2 fix)
        if body.edited_fields:
            for k, v in body.edited_fields.items():
                if k in ("extracted_json", "confidence_json"):
                    continue
                old_value = extracted.get(k)
                if old_value != v:
                    extracted[k] = v
                    confidence[k] = "high"

        # Merge dual-source confidence BEFORE apply block (D1 read-side fix)
        # Must happen before tag writing so embedded high-confidence groups propagate
        embedded_confidence = extracted.get("confidence", {})
        merged_confidence = {**embedded_confidence, **confidence}

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        if body.review_status == "approved" and not is_quarantined:
            # Write classification to works table (fill-empty only)
            work_id = ext["work_id"]
            CLASSIFICATION_FIELDS = {
                "primary_doc_type": "primary_doc_type",
                "secondary_doc_type": "secondary_doc_type",
                "publication_status": "publication_status",
                "ingestion_state": "ingestion_state",
                "priority": "priority",
                "primary_source_actor_type": "primary_source_actor_type",
                "region": "region",
            }
            sets = []
            params = []
            for field, col in CLASSIFICATION_FIELDS.items():
                value = extracted.get(field)
                if value is None:
                    continue
                current = conn.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
                if current and col in current.keys() and current[col]:
                    continue
                sets.append(f"{col} = ?")
                params.append(value)

            if sets:
                params.append(work_id)
                conn.execute(
                    f"UPDATE works SET {', '.join(sets)} WHERE id = ?",
                    params,
                )

            # Write multi-value tags
            TAG_GROUPS = ["reading_lane", "artifact_focus", "risk_domain", "method_tags"]
            for group in TAG_GROUPS:
                values = extracted.get(group) or []
                for v in values:
                    existing = conn.execute(
                        "SELECT 1 FROM work_classification_tags WHERE work_id = ? AND tag_group = ? AND tag_value = ?",
                        (work_id, group, v),
                    ).fetchone()
                    if not existing:
                        tag_id = f"CT-{uuid.uuid4().hex[:12]}"
                        conn.execute(
                            "INSERT INTO work_classification_tags "
                            "(id, work_id, tag_group, tag_value, source, confidence, evidence, "
                            "review_status, created_at, updated_at) "
                            "VALUES (?, ?, ?, ?, 'model', ?, ?, 'approved', ?, ?)",
                            (tag_id, work_id, group, v,
                             merged_confidence.get(group, "low"),
                             (extracted.get("evidence") or {}).get(group, ""),
                             now, now),
                        )

            # Mark extraction as applied
            conn.execute(
                "UPDATE classification_extractions SET applied = 1, applied_at = ? WHERE id = ?",
                (now, ext_id),
            )

            # Supersede other pending extractions for the same work
            conn.execute(
                "UPDATE classification_extractions SET review_status = 'rejected', "
                "review_note = 'superseded by approved extraction', "
                "reviewed_at = ?, fix_action = 'superseded' "
                "WHERE work_id = ? AND id != ? AND "
                "(review_status IN ('pending', 'needs_fix') OR (review_status = 'approved' AND applied = 0))",
                (now, ext["work_id"], ext_id),
            )

        # Update extraction review status
        # Recompute ambiguity score after edits (merged_confidence already built above)
        new_amb = compute_ambiguity(extracted, merged_confidence)
        conn.execute(
            "UPDATE classification_extractions SET review_status = ?, review_note = ?, "
            "reviewed_at = ?, extracted_json = ?, confidence_json = ?, ambiguity_score = ?, "
            "ambiguity_reasons = ?, updated_at = ? WHERE id = ?",
            (body.review_status, body.review_note, now,
             json.dumps(extracted, ensure_ascii=False),
             json.dumps(confidence, ensure_ascii=False),
             new_amb["score"],
             json.dumps(new_amb["reasons"], ensure_ascii=False),
             now, ext_id),
        )
        conn.commit()
        return {"ok": True, "applied": 0 if is_quarantined else int(body.review_status == "approved")}
    finally:
        conn.close()


@router.post("/classification/extractions/batch-approve-low-risk")
def batch_approve_low_ambiguity():
    """Batch approve low-ambiguity extractions.

    Per work: only the best extraction (mimo > ollama, then lower ambiguity) is applied;
    other pending extractions for the same work are superseded.
    """
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT ce.* FROM classification_extractions ce "
            "JOIN works w ON w.id = ce.work_id "
            "WHERE ce.review_status = 'pending' AND ce.ambiguity_score < 20 "
            "AND w.read_status != 'quarantined' "
            "ORDER BY ce.work_id, "
            "  CASE "
            "    WHEN ce.model_name LIKE '%mimo2.5pro%' THEN 0 "
            "    WHEN ce.model_name LIKE '%mimo-claude%' THEN 1 "
            "    ELSE 2 "
            "  END, "
            "  ce.ambiguity_score ASC"
        ).fetchall()
        if not rows:
            return {"ok": True, "approved": 0}

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        approved_count = 0
        applied_works = set()
        applied_ids = []

        for row in rows:
            ext = dict(row)
            extracted = json.loads(ext["extracted_json"]) if ext["extracted_json"] else {}
            evidence = extracted.get("evidence") or {}
            work_id = ext["work_id"]

            # Gate on primary_doc_type evidence
            if not evidence.get("primary_doc_type"):
                continue

            # Only apply the first extraction per work (mimo wins, lower amb wins)
            if work_id not in applied_works:
                confidence = json.loads(ext["confidence_json"]) if ext["confidence_json"] else {}

                # Merge dual-source confidence (D1 read-side fix)
                embedded_confidence = extracted.get("confidence", {})
                merged_confidence = {**embedded_confidence, **confidence}

                # Write scalar classification fields (fill-empty only)
                CLASSIFICATION_FIELDS = {
                    "primary_doc_type": "primary_doc_type",
                    "publication_status": "publication_status",
                    "ingestion_state": "ingestion_state",
                    "priority": "priority",
                    "primary_source_actor_type": "primary_source_actor_type",
                    "region": "region",
                }
                current = conn.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
                if current:
                    sets = []
                    params = []
                    for field, col in CLASSIFICATION_FIELDS.items():
                        value = extracted.get(field)
                        if value is None:
                            continue
                        if col in current.keys() and current[col]:
                            continue
                        sets.append(f"{col} = ?")
                        params.append(value)
                    if sets:
                        params.append(work_id)
                        conn.execute(f"UPDATE works SET {', '.join(sets)} WHERE id = ?", params)

                # Write multi-value tags
                TAG_GROUPS = ["reading_lane", "artifact_focus", "risk_domain", "method_tags"]
                for group in TAG_GROUPS:
                    values = extracted.get(group) or []
                    for v in values:
                        existing = conn.execute(
                            "SELECT 1 FROM work_classification_tags WHERE work_id = ? AND tag_group = ? AND tag_value = ?",
                            (work_id, group, v),
                        ).fetchone()
                        if not existing:
                            tag_id = f"CT-{uuid.uuid4().hex[:12]}"
                            conn.execute(
                                "INSERT INTO work_classification_tags "
                                "(id, work_id, tag_group, tag_value, source, confidence, evidence, "
                                "review_status, created_at, updated_at) "
                                "VALUES (?, ?, ?, ?, 'model', ?, ?, 'approved', ?, ?)",
                                (tag_id, work_id, group, v,
                                 merged_confidence.get(group, "low"),
                                 evidence.get(group, ""),
                                 now, now),
                            )

                # Mark extraction as applied
                conn.execute(
                    "UPDATE classification_extractions SET applied = 1, applied_at = ? WHERE id = ?",
                    (now, ext["id"]),
                )
                applied_ids.append(ext["id"])
                applied_works.add(work_id)
                approved_count += 1

        # Mark applied extractions as approved
        if applied_ids:
            placeholders = ",".join("?" * len(applied_ids))
            conn.execute(
                f"UPDATE classification_extractions SET review_status = 'approved', reviewed_at = ?, "
                f"review_note = 'batch auto-approve (ambiguity < 20)' WHERE id IN ({placeholders})",
                [now] + applied_ids,
            )

        # Supersede ALL other extractions for approved works (including previously approved)
        if applied_works:
            work_placeholders = ",".join("?" * len(applied_works))
            id_placeholders = ",".join("?" * len(applied_ids))
            conn.execute(
                f"UPDATE classification_extractions SET review_status = 'rejected', "
                f"fix_action = 'superseded', review_note = 'superseded by batch-approved extraction', "
                f"reviewed_at = ? "
                f"WHERE work_id IN ({work_placeholders}) AND id NOT IN ({id_placeholders})",
                [now] + list(applied_works) + applied_ids,
            )

        conn.commit()
        return {"ok": True, "approved": approved_count}
    finally:
        conn.close()


class BatchApproveWithTag(BaseModel):
    threshold: int = 100
    tag: str


@router.post("/classification/extractions/batch-approve-with-tag")
def batch_approve_with_tag(body: BatchApproveWithTag):
    """Batch approve pending extractions up to a given ambiguity threshold.

    Unlike batch-approve-low-risk (fixed <20), this endpoint accepts a custom
    threshold and writes a uniform review_note tag for traceability.

    Per work: only the best extraction (mimo > ollama, then lower ambiguity) is applied;
    other pending extractions for the same work are superseded.
    """
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT ce.* FROM classification_extractions ce "
            "JOIN works w ON w.id = ce.work_id "
            "WHERE ce.review_status = 'pending' AND ce.ambiguity_score <= ? "
            "AND w.read_status != 'quarantined' "
            "ORDER BY ce.work_id, "
            "  CASE "
            "    WHEN ce.model_name LIKE '%mimo2.5pro%' THEN 0 "
            "    WHEN ce.model_name LIKE '%mimo-claude%' THEN 1 "
            "    ELSE 2 "
            "  END, "
            "  ce.ambiguity_score ASC",
            (body.threshold,),
        ).fetchall()
        if not rows:
            return {"ok": True, "approved": 0, "tag": body.tag}

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        approved_count = 0
        applied_works = set()
        applied_ids = []

        for row in rows:
            ext = dict(row)
            extracted = json.loads(ext["extracted_json"]) if ext["extracted_json"] else {}
            evidence = extracted.get("evidence") or {}
            work_id = ext["work_id"]

            # Gate on primary_doc_type evidence
            if not evidence.get("primary_doc_type"):
                continue

            # Only apply the first extraction per work (mimo wins, lower amb wins)
            if work_id not in applied_works:
                confidence = json.loads(ext["confidence_json"]) if ext["confidence_json"] else {}

                # Merge dual-source confidence (D1 read-side fix)
                embedded_confidence = extracted.get("confidence", {})
                merged_confidence = {**embedded_confidence, **confidence}

                # Write scalar classification fields (fill-empty only)
                CLASSIFICATION_FIELDS = {
                    "primary_doc_type": "primary_doc_type",
                    "publication_status": "publication_status",
                    "ingestion_state": "ingestion_state",
                    "priority": "priority",
                    "primary_source_actor_type": "primary_source_actor_type",
                    "region": "region",
                }
                current = conn.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
                if current:
                    sets = []
                    params = []
                    for field, col in CLASSIFICATION_FIELDS.items():
                        value = extracted.get(field)
                        if value is None:
                            continue
                        if col in current.keys() and current[col]:
                            continue
                        sets.append(f"{col} = ?")
                        params.append(value)
                    if sets:
                        params.append(work_id)
                        conn.execute(f"UPDATE works SET {', '.join(sets)} WHERE id = ?", params)

                # Write multi-value tags
                TAG_GROUPS = ["reading_lane", "artifact_focus", "risk_domain", "method_tags"]
                for group in TAG_GROUPS:
                    values = extracted.get(group) or []
                    for v in values:
                        existing = conn.execute(
                            "SELECT 1 FROM work_classification_tags WHERE work_id = ? AND tag_group = ? AND tag_value = ?",
                            (work_id, group, v),
                        ).fetchone()
                        if not existing:
                            tag_id = f"CT-{uuid.uuid4().hex[:12]}"
                            conn.execute(
                                "INSERT INTO work_classification_tags "
                                "(id, work_id, tag_group, tag_value, source, confidence, evidence, "
                                "review_status, created_at, updated_at) "
                                "VALUES (?, ?, ?, ?, 'model', ?, ?, 'approved', ?, ?)",
                                (tag_id, work_id, group, v,
                                 merged_confidence.get(group, "low"),
                                 evidence.get(group, ""),
                                 now, now),
                            )

                # Mark extraction as applied
                conn.execute(
                    "UPDATE classification_extractions SET applied = 1, applied_at = ? WHERE id = ?",
                    (now, ext["id"]),
                )
                applied_ids.append(ext["id"])
                applied_works.add(work_id)
                approved_count += 1

        # Mark applied extractions as approved with tag
        if applied_ids:
            placeholders = ",".join("?" * len(applied_ids))
            conn.execute(
                f"UPDATE classification_extractions SET review_status = 'approved', reviewed_at = ?, "
                f"review_note = ? WHERE id IN ({placeholders})",
                [now, body.tag] + applied_ids,
            )

        # Supersede ALL other extractions for approved works (including previously approved)
        if applied_works:
            work_placeholders = ",".join("?" * len(applied_works))
            id_placeholders = ",".join("?" * len(applied_ids))
            conn.execute(
                f"UPDATE classification_extractions SET review_status = 'rejected', "
                f"fix_action = 'superseded', review_note = 'superseded by batch-approved extraction', "
                f"reviewed_at = ? "
                f"WHERE work_id IN ({work_placeholders}) AND id NOT IN ({id_placeholders})",
                [now] + list(applied_works) + applied_ids,
            )

        conn.commit()
        return {"ok": True, "approved": approved_count, "tag": body.tag, "total_candidates": len(rows)}
    finally:
        conn.close()


@router.post("/classification/extractions/{ext_id}/quarantine")
def quarantine_from_classification_review(ext_id: str, body: QuarantineAction):
    """Quarantine a work from the classification review page.

    The global quarantine state lives on works.read_status. This endpoint mirrors
    metadata quarantine behavior so every review surface and management view sees
    the same isolation boundary.
    """
    if not body.reason or body.reason not in QUARANTINE_REASONS:
        raise HTTPException(
            status_code=400,
            detail=f"reason is required and must be one of: {', '.join(sorted(QUARANTINE_REASONS))}",
        )

    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM classification_extractions WHERE id = ?", (ext_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Extraction not found")

        ext = dict(row)
        work_id = ext["work_id"]
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        conn.execute(
            "UPDATE classification_extractions SET review_status = 'rejected', "
            "fix_action = 'quarantined', review_note = ?, reviewed_at = ?, updated_at = ? "
            "WHERE id = ?",
            (body.reason, now, now, ext_id),
        )
        conn.execute(
            "UPDATE classification_extractions SET review_status = 'rejected', "
            "fix_action = 'quarantined', "
            "review_note = CASE WHEN review_note IS NULL OR review_note = '' THEN ? ELSE review_note END, "
            "reviewed_at = ?, updated_at = ? "
            "WHERE work_id = ? AND review_status = 'pending' AND id != ?",
            (body.reason, now, now, work_id, ext_id),
        )
        conn.execute(
            "UPDATE classification_extractions SET review_status = 'rejected', "
            "fix_action = 'quarantined', "
            "review_note = CASE WHEN review_note IS NULL OR review_note = '' THEN ? ELSE review_note END, "
            "reviewed_at = ?, updated_at = ? "
            "WHERE work_id = ? AND review_status = 'approved' AND applied = 0 AND id != ?",
            (body.reason, now, now, work_id, ext_id),
        )

        conn.execute(
            "UPDATE works SET read_status = 'quarantined', updated_at = ? WHERE id = ?",
            (now, work_id),
        )

        if table_exists(conn, "work_codes"):
            try:
                conn.execute(
                    "INSERT INTO work_codes (work_id, source_file_id, code, reason) "
                    "VALUES (?, '', 'quarantined', ?)",
                    (work_id, body.reason),
                )
            except Exception:
                pass

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
