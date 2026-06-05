"""Works API routes."""

from __future__ import annotations

import json
import shutil
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from ..db import get_conn, LIBRARY_ROOT
from ..models import WorkUpdate, QuarantineAction

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
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    conn = get_conn()
    try:
        where = []
        params = []

        if status != "all":
            where.append("w.read_status = ?")
            params.append(status)
        if doc_type != "all":
            where.append("w.doc_type = ?")
            params.append(doc_type)
        if language != "all":
            where.append("w.language = ?")
            params.append(language)
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

        offset = (page - 1) * per_page
        rows = conn.execute(
            f"SELECT w.* FROM works w{where_clause} ORDER BY {sort_col} LIMIT ? OFFSET ?",
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

        work["source_files"] = sources
        work["archived_source_files"] = archived_sources
        work["relations"] = relations
        work["codes"] = codes
        work["duplicates"] = duplicates
        work["parse_runs"] = runs

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
        for field, value in body.model_dump(exclude_unset=True).items():
            if field == "authors":
                updates.append("authors = ?")
                params.append(json.dumps(value, ensure_ascii=False))
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

        # Move source files to _quarantine/{work_id}/
        sources = conn.execute(
            "SELECT id, source_path, original_name FROM source_files WHERE work_id = ?",
            (work_id,),
        ).fetchall()
        for s in sources:
            src = Path(s["source_path"])
            if src.exists():
                dest = quarantine_dir / s["original_name"] or src.name
                quarantine_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dest))
                moved_files.append(str(dest))

        # Update DB
        conn.execute(
            "UPDATE works SET read_status = 'quarantined', updated_at = datetime('now') WHERE id = ?",
            (work_id,),
        )
        # Update source_paths to point to quarantine
        for s in sources:
            src = Path(s["source_path"])
            if src.name:
                new_path = str(quarantine_dir / src.name)
                conn.execute(
                    "UPDATE source_files SET source_path = ? WHERE id = ?",
                    (new_path, s["id"]),
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

        # Move source files back from _quarantine/{work_id}/ to works/{work_id}/source/
        sources = conn.execute(
            "SELECT id, source_path, original_name FROM source_files WHERE work_id = ?",
            (work_id,),
        ).fetchall()
        for s in sources:
            src = Path(s["source_path"])
            if src.exists():
                work_dir.mkdir(parents=True, exist_ok=True)
                dest = work_dir / s["original_name"] or src.name
                shutil.move(str(src), str(dest))
                moved_files.append(str(dest))

        # Update DB
        conn.execute(
            "UPDATE works SET read_status = 'unread', updated_at = datetime('now') WHERE id = ?",
            (work_id,),
        )
        # Update source_paths back to works dir
        for s in sources:
            src = Path(s["source_path"])
            if src.name:
                new_path = str(work_dir / src.name)
                conn.execute(
                    "UPDATE source_files SET source_path = ? WHERE id = ?",
                    (new_path, s["id"]),
                )
        # Remove bad_source code
        conn.execute(
            "DELETE FROM work_codes WHERE work_id = ? AND code = 'bad_source'",
            (work_id,),
        )

        conn.commit()
        return {"ok": True, "work_id": work_id, "moved_files": moved_files}
    finally:
        conn.close()
