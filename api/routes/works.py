"""Works API routes."""

from __future__ import annotations

import json
import shutil
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from ..db import get_conn, LIBRARY_ROOT
from ..models import WorkUpdate, QuarantineAction
from ..path_safety import _sanitize_filename, _safe_dest_name, _unique_dest

router = APIRouter()


def _safe_json(value: str | None, default=None):
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


@router.get("/works")
def list_works(
    status: str = "all",
    doc_type: str = "all",
    language: str = "all",
    search: str = "",
    sort: str = "id",
    order: str = "asc",
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    include_quarantined: bool = Query(False),
    # Classification v0.2 filters
    primary_doc_type: str | None = Query(None),
    publication_status: str | None = Query(None),
    ingestion_state: str | None = Query(None),
    priority: str | None = Query(None),
    # Multi-value tag filters (OR within dimension)
    reading_lane: list[str] | None = Query(default=None),
    artifact_focus: list[str] | None = Query(default=None),
    risk_domain: list[str] | None = Query(default=None),
    # Classified-only filter
    classified_only: bool = Query(False),
):
    conn = get_conn()
    try:
        where = []
        params = []

        # Exclude quarantined by default
        if not include_quarantined and status == "all":
            where.append("w.read_status != 'quarantined'")

        if status != "all":
            where.append("w.read_status = ?")
            params.append(status)
        if doc_type != "all":
            where.append("w.doc_type = ?")
            params.append(doc_type)
        if language != "all":
            where.append("w.language = ?")
            params.append(language)
        if primary_doc_type is not None:
            where.append("w.primary_doc_type = ?")
            params.append(primary_doc_type)
        if publication_status is not None:
            where.append("w.publication_status = ?")
            params.append(publication_status)
        if ingestion_state is not None:
            where.append("w.ingestion_state = ?")
            params.append(ingestion_state)
        if priority is not None:
            where.append("w.priority = ?")
            params.append(priority)

        # Classified-only filter
        if classified_only:
            where.append("w.primary_doc_type IS NOT NULL AND w.primary_doc_type != ''")

        # Multi-value tag filters: OR within dimension (match any selected value)
        for tag_group, tag_values in [
            ("reading_lane", reading_lane),
            ("artifact_focus", artifact_focus),
            ("risk_domain", risk_domain),
        ]:
            if tag_values:
                placeholders = ",".join("?" * len(tag_values))
                where.append(
                    f"w.id IN (SELECT work_id FROM work_classification_tags "
                    f"WHERE tag_group = ? AND tag_value IN ({placeholders}) AND review_status = 'approved')"
                )
                params.extend([tag_group, *tag_values])
        if search:
            where.append(
                "(w.title LIKE ? OR w.id LIKE ? OR w.arxiv_id LIKE ? OR w.doi LIKE ?)"
            )
            like = f"%{search}%"
            params.extend([like, like, like, like])

        where_clause = (" WHERE " + " AND ".join(where)) if where else ""

        # Summary stats
        stats = {}
        for row in conn.execute(
            "SELECT read_status, COUNT(*) as cnt FROM works GROUP BY read_status"
        ):
            stats[row["read_status"]] = row["cnt"]
        total = sum(stats.values())

        doc_type_counts = {}
        for row in conn.execute(
            "SELECT doc_type, COUNT(*) as cnt FROM works GROUP BY doc_type"
        ):
            doc_type_counts[row["doc_type"] or "unknown"] = row["cnt"]

        lang_counts = {}
        for row in conn.execute(
            "SELECT language, COUNT(*) as cnt FROM works GROUP BY language"
        ):
            lang_counts[row["language"] or "unknown"] = row["cnt"]

        relation_count = conn.execute("SELECT COUNT(*) FROM work_relations").fetchone()[
            0
        ]

        # Total matching (for pagination)
        count_row = conn.execute(
            f"SELECT COUNT(*) FROM works w{where_clause}", params
        ).fetchone()
        total_matching = count_row[0]

        # Valid sort columns
        sort_col = {
            "id": "w.id",
            "title": "w.title",
            "year": "w.year",
            "created_at": "w.created_at",
            "read_status": "w.read_status",
        }.get(sort, "w.id")
        sort_dir = "DESC" if order.lower() == "desc" else "ASC"

        offset = (page - 1) * per_page
        rows = conn.execute(
            f"SELECT w.* FROM works w{where_clause} ORDER BY {sort_col} {sort_dir} LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()

        works = []
        for row in rows:
            d = dict(row)
            d["authors"] = _safe_json(d.get("authors"), [])
            # Source count (active only)
            sc = conn.execute(
                "SELECT COUNT(*) FROM source_files WHERE work_id = ? AND status = 'active'", (d["id"],)
            ).fetchone()
            d["source_count"] = sc[0]
            # Unique source count (distinct SHA256 among active)
            uc = conn.execute(
                "SELECT COUNT(DISTINCT content_sha256) FROM source_files WHERE work_id = ? AND status = 'active'",
                (d["id"],),
            ).fetchone()
            d["unique_source_count"] = uc[0]
            # Total source count (including archived)
            tc = conn.execute(
                "SELECT COUNT(*) FROM source_files WHERE work_id = ?", (d["id"],)
            ).fetchone()
            d["total_source_count"] = tc[0]
            works.append(d)

        return {
            "works": works,
            "total": total,
            "total_matching": total_matching,
            "page": page,
            "per_page": per_page,
            "summary": {
                "total": total,
                "statuses": stats,
                "doc_types": doc_type_counts,
                "languages": lang_counts,
                "relations": relation_count,
            },
        }
    finally:
        conn.close()


@router.get("/works/{work_id}")
def get_work(work_id: str):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Work not found")

        work = dict(row)
        work["authors"] = _safe_json(work.get("authors"), [])
        work["contributors"] = _safe_json(work.get("contributors"), [])

        # Source files (active and archived separately)
        sources = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM source_files WHERE work_id = ? AND status = 'active'", (work_id,)
            ).fetchall()
        ]
        archived_sources = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM source_files WHERE work_id = ? AND status = 'archived'", (work_id,)
            ).fetchall()
        ]

        # Relations
        relations = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM work_relations WHERE work_id_a = ? OR work_id_b = ?",
                (work_id, work_id),
            ).fetchall()
        ]
        # Enrich relations with partner titles
        for rel in relations:
            partner_id = (
                rel["work_id_b"] if rel["work_id_a"] == work_id else rel["work_id_a"]
            )
            partner = conn.execute(
                "SELECT title FROM works WHERE id = ?", (partner_id,)
            ).fetchone()
            rel["partner_title"] = partner["title"] if partner else partner_id

        # Work codes
        codes = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM work_codes WHERE work_id = ?", (work_id,)
            ).fetchall()
        ]

        # Duplicate candidates
        duplicates = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM duplicate_candidates WHERE work_id = ?", (work_id,)
            ).fetchall()
        ]

        # Parse runs
        runs = []
        if work.get("parse_status") != "unknown":
            runs = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM literature_parse_runs WHERE work_id = ?",
                    (work_id,),
                ).fetchall()
            ]

        # Classification tags (approved only, grouped by tag_group)
        tag_rows = conn.execute(
            "SELECT tag_group, tag_value, confidence, evidence FROM work_classification_tags "
            "WHERE work_id = ? AND review_status = 'approved'",
            (work_id,),
        ).fetchall()
        classification_tags = {}
        tag_confidence = {}
        tag_evidence = {}
        for tr in tag_rows:
            group = tr["tag_group"]
            classification_tags.setdefault(group, []).append(tr["tag_value"])
            if tr["confidence"]:
                tag_confidence[f"{group}:{tr['tag_value']}"] = tr["confidence"]
            if tr["evidence"]:
                tag_evidence[f"{group}:{tr['tag_value']}"] = tr["evidence"]

        work["source_files"] = sources
        work["archived_source_files"] = archived_sources
        work["relations"] = relations
        work["codes"] = codes
        work["duplicates"] = duplicates
        work["parse_runs"] = runs
        work["classification_tags"] = classification_tags
        work["tag_confidence"] = tag_confidence
        work["tag_evidence"] = tag_evidence

        return work
    finally:
        conn.close()


@router.patch("/works/{work_id}")
def update_work(work_id: str, body: WorkUpdate):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Work not found")

        updates = []
        params = []
        # Handle month -> publication_date_json sync
        body_data = body.model_dump(exclude_unset=True)
        month_val = body_data.pop("month", None)
        if month_val is not None:
            # Update publication_date_json with month
            date_json = json.loads(row["publication_date_json"] or "{}") if row["publication_date_json"] else {}
            date_json["month"] = month_val
            if "year" not in date_json and row["year"]:
                date_json["year"] = row["year"]
            updates.append("publication_date_json = ?")
            params.append(json.dumps(date_json, ensure_ascii=False))
        for field, value in body_data.items():
            if field == "authors":
                updates.append("authors = ?")
                params.append(json.dumps(value, ensure_ascii=False))
            elif field == "is_core_literature" and value is not None:
                updates.append("is_core_literature = ?")
                params.append(1 if value else 0)
            elif field == "publication_date_json" and value is not None:
                # Direct update of publication_date_json
                updates.append("publication_date_json = ?")
                params.append(value)
            elif value is not None:
                updates.append(f"{field} = ?")
                params.append(value)

        if updates:
            from datetime import datetime, timezone

            updates.append("updated_at = ?")
            params.append(datetime.now(timezone.utc).isoformat(timespec="seconds"))
            params.append(work_id)
            conn.execute(
                f"UPDATE works SET {', '.join(updates)} WHERE id = ?", params
            )
            conn.commit()

        return {"ok": True, "work_id": work_id}
    finally:
        conn.close()


@router.post("/works/{work_id}/quarantine")
def quarantine_work(work_id: str, body: QuarantineAction = QuarantineAction()):
    """Quarantine a work: update status, add bad_source code, move files to _quarantine/."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Work not found")

        quarantine_dir = LIBRARY_ROOT / "_quarantine" / work_id
        moved_files = []
        missing_files = []

        sources = conn.execute(
            "SELECT id, source_path, original_name FROM source_files WHERE work_id = ?",
            (work_id,),
        ).fetchall()

        # Pre-check: collect all dest paths and verify sources exist
        planned_moves: list[tuple[Path, Path, dict]] = []
        for s in sources:
            src = Path(s["source_path"])
            if not src.exists():
                missing_files.append(str(src))
                continue
            dest_name = _safe_dest_name(dict(s), s["source_path"])
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            dest = _unique_dest(quarantine_dir / dest_name)
            planned_moves.append((src, dest, dict(s)))

        if missing_files:
            raise HTTPException(
                status_code=409,
                detail={"error": "missing_source_files", "missing": missing_files},
            )

        # Move files
        for src, dest, _ in planned_moves:
            shutil.move(str(src), str(dest))
            moved_files.append(str(dest))

        # Update DB: work status
        conn.execute(
            "UPDATE works SET read_status = 'quarantined', updated_at = datetime('now') WHERE id = ?",
            (work_id,),
        )
        # Update source_paths to point to quarantine (use same dest name as file move)
        for _, dest, s in planned_moves:
            conn.execute(
                "UPDATE source_files SET source_path = ? WHERE id = ?",
                (str(dest), s["id"]),
            )
        # Add bad_source code
        try:
            conn.execute(
                "INSERT INTO work_codes (work_id, source_file_id, code, reason) VALUES (?, '', 'bad_source', ?)",
                (work_id, body.reason or "quarantined via API"),
            )
        except Exception:
            pass  # Already has this code

        conn.commit()
        return {"ok": True, "work_id": work_id, "moved_files": moved_files}
    finally:
        conn.close()


@router.post("/works/{work_id}/restore")
def restore_work(work_id: str):
    """Restore a quarantined work: update status, remove bad_source code, move files back."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Work not found")

        work_dir = LIBRARY_ROOT / "works" / work_id / "source"
        moved_files = []
        missing_files = []

        sources = conn.execute(
            "SELECT id, source_path, original_name FROM source_files WHERE work_id = ?",
            (work_id,),
        ).fetchall()

        # Pre-check: collect all dest paths and verify sources exist
        planned_moves: list[tuple[Path, Path, dict]] = []
        for s in sources:
            src = Path(s["source_path"])
            if not src.exists():
                missing_files.append(str(src))
                continue
            dest_name = _safe_dest_name(dict(s), s["source_path"])
            work_dir.mkdir(parents=True, exist_ok=True)
            dest = _unique_dest(work_dir / dest_name)
            planned_moves.append((src, dest, dict(s)))

        if missing_files:
            raise HTTPException(
                status_code=409,
                detail={"error": "missing_source_files", "missing": missing_files},
            )

        # Move files
        for src, dest, _ in planned_moves:
            shutil.move(str(src), str(dest))
            moved_files.append(str(dest))

        # Update DB: work status
        conn.execute(
            "UPDATE works SET read_status = 'unread', updated_at = datetime('now') WHERE id = ?",
            (work_id,),
        )
        # Update source_paths back to works dir (use same dest name as file move)
        for _, dest, s in planned_moves:
            conn.execute(
                "UPDATE source_files SET source_path = ? WHERE id = ?",
                (str(dest), s["id"]),
            )
        # Remove quarantine-related codes
        conn.execute(
            "DELETE FROM work_codes WHERE work_id = ? AND code IN ('bad_source', 'quarantined')",
            (work_id,),
        )

        conn.commit()

        # Clean up empty quarantine directory
        quarantine_dir = LIBRARY_ROOT / "_quarantine" / work_id
        if quarantine_dir.exists():
            try:
                quarantine_dir.rmdir()  # only removes if empty
            except OSError:
                pass  # directory not empty, leave it

        return {"ok": True, "work_id": work_id, "moved_files": moved_files}
    finally:
        conn.close()
