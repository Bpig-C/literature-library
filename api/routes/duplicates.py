"""Duplicates API routes."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..db import get_conn, LIBRARY_ROOT
from ..models import DuplicateReview

router = APIRouter()

RELATION_TYPES = {
    "same_work", "not_duplicate", "version_of",
    "translation_of", "supersedes", "part_of",
}


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


def _cleanup_same_work_sources(conn, group_id: str) -> int:
    """For exact_sha256 same_work: archive duplicate source_files, keep one active per SHA256 per work.

    Returns the number of source_files archived.
    """
    # Get all source_files referenced by this group's candidates
    cands = conn.execute(
        "SELECT DISTINCT source_file_id, work_id FROM duplicate_candidates WHERE group_id = ?",
        (group_id,),
    ).fetchall()

    # Group by work_id, then by SHA256
    work_sha_files: dict[str, dict[str, list]] = {}
    for c in cands:
        if not c["source_file_id"]:
            continue
        src = conn.execute(
            "SELECT id, work_id, content_sha256, source_path, original_name FROM source_files WHERE id = ?",
            (c["source_file_id"],),
        ).fetchone()
        if not src:
            continue
        wid = src["work_id"]
        sha = src["content_sha256"]
        work_sha_files.setdefault(wid, {}).setdefault(sha, []).append(dict(src))

    from datetime import datetime, timezone
    archived = 0
    archive_dir = LIBRARY_ROOT / "_archive" / "dedup"
    for wid, sha_map in work_sha_files.items():
        for sha, files in sha_map.items():
            if len(files) <= 1:
                continue
            # Keep the first file (prefer the one with the more descriptive name), archive the rest
            files.sort(key=lambda f: len(f.get("original_name") or ""), reverse=True)
            keep = files[0]
            for f in files[1:]:
                src_path = Path(f["source_path"])
                archive_path = None
                if src_path.exists():
                    rel = src_path.name
                    dest = archive_dir / f["work_id"] / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src_path), str(dest))
                    archive_path = str(dest)
                # Mark as archived instead of deleting
                conn.execute(
                    "UPDATE source_files SET status = 'archived', archived_at = ?, archive_path = ?, archive_reason = ? WHERE id = ?",
                    (
                        datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        archive_path,
                        f"dedup cleanup: same SHA256 as {keep['id']}",
                        f["id"],
                    ),
                )
                archived += 1

    return archived


def _create_relation(conn, work_id_a: str, work_id_b: str, relation_type: str, note: str) -> bool:
    """Insert a work_relation, avoiding duplicates. Returns True if a new row was inserted."""
    if work_id_a == work_id_b:
        return False
    if relation_type in ("same_work", "not_duplicate", "version_of", "translation_of"):
        a, b = sorted([work_id_a, work_id_b])
    else:
        a, b = work_id_a, work_id_b
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO work_relations (work_id_a, work_id_b, relation_type, confirmed, note) VALUES (?, ?, ?, 1, ?)",
            (a, b, relation_type, note),
        )
        return cur.rowcount > 0
    except Exception:
        return False


def _move_to_quarantine(conn, work_id: str, reason: str) -> list[str]:
    """Move source_files to _quarantine/{work_id}/ and update DB. Returns moved paths."""
    quarantine_dir = LIBRARY_ROOT / "_quarantine" / work_id
    moved = []
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
            moved.append(str(dest))
        # Update source_path to new location
        new_path = str(quarantine_dir / (s["original_name"] or Path(s["source_path"]).name))
        conn.execute(
            "UPDATE source_files SET source_path = ? WHERE id = ?",
            (new_path, s["id"]),
        )
    return moved


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
        # Check group exists
        group = conn.execute(
            "SELECT * FROM duplicate_groups WHERE id = ?", (group_id,)
        ).fetchone()
        if not group:
            raise HTTPException(status_code=404, detail="Duplicate group not found")

        # 1. Mark candidates as reviewed
        conn.execute(
            "UPDATE duplicate_candidates SET reviewed = 1 WHERE group_id = ?",
            (group_id,),
        )

        actions = {"relations_created": 0, "sources_removed": 0, "files_moved": []}

        # 2. Create work_relations for relation-type decisions
        if body.decision in RELATION_TYPES:
            cands = conn.execute(
                "SELECT DISTINCT work_id FROM duplicate_candidates WHERE group_id = ?",
                (group_id,),
            ).fetchall()
            work_ids = [c["work_id"] for c in cands]

            # For same_work on exact_sha256: all candidates share the same work_id,
            # so no inter-work relation is needed. The relation is implicit.
            if body.decision == "same_work" and group["duplicate_type"] == "exact_sha256":
                pass  # Same work, no relation to create
            else:
                # Create pairwise relations between all work_ids in the group
                for i in range(len(work_ids)):
                    for j in range(i + 1, len(work_ids)):
                        created = _create_relation(
                            conn, work_ids[i], work_ids[j],
                            body.decision,
                            body.note or f"dedup review {group_id}",
                        )
                        if created:
                            actions["relations_created"] += 1

        # 3. Clean up duplicate source_files for same_work on exact_sha256
        if body.decision == "same_work" and group["duplicate_type"] == "exact_sha256":
            actions["sources_removed"] = _cleanup_same_work_sources(conn, group_id)

        # 4. Handle quarantine: move files to _quarantine/
        if body.decision == "quarantine":
            cands = conn.execute(
                "SELECT DISTINCT work_id FROM duplicate_candidates WHERE group_id = ?",
                (group_id,),
            ).fetchall()
            for c in cands:
                wid = c["work_id"]
                conn.execute(
                    "UPDATE works SET read_status = 'quarantined', updated_at = datetime('now') WHERE id = ?",
                    (wid,),
                )
                try:
                    conn.execute(
                        "INSERT INTO work_codes (work_id, source_file_id, code, reason) VALUES (?, '', 'bad_source', ?)",
                        (wid, body.note or f"quarantine: {group_id}"),
                    )
                except Exception:
                    pass
                moved = _move_to_quarantine(conn, wid, body.note or f"quarantine: {group_id}")
                actions["files_moved"].extend(moved)

        conn.commit()
        return {"ok": True, "actions": actions}
    finally:
        conn.close()
