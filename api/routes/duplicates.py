"""Duplicates API routes."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db import get_conn, get_read_conn, LIBRARY_ROOT
from ..models import DuplicateReview
from ..path_safety import _safe_dest_name, _unique_dest

router = APIRouter()

RELATION_TYPES = {
    "same_work", "not_duplicate", "version_of",
    "translation_of", "supersedes", "part_of",
}


class DuplicateLookupBody(BaseModel):
    """Pure lookup: no side effects, no PDF upload, no Work/Source creation."""
    content_sha256: str | None = Field(default=None, description="SHA256 hex of the local PDF")
    doi: str | None = None
    arxiv_id: str | None = None
    title: str | None = Field(default=None, description="Exact or fuzzy title for candidate-level matches")
    limit: int = Field(default=10, ge=1, le=50)


@router.post("/duplicates/lookup")
def duplicates_lookup(body: DuplicateLookupBody):
    """Check if a local PDF is already in the library without uploading it.

    Returns tiered results:
    - exact_sha: same file (SHA256 match on source_files)
    - same_work: same paper, different version (DOI/arXiv match on works)
    - title_candidates: similar titles (NOT auto-confirmed)
    - unmatched: nothing found (or incomplete query)

    Read-only: creates no Work/Source/Parse/A/R, no purpose notes, no locks,
    no producer jobs, no OSS operations.
    """
    if not body.content_sha256 and not body.doi and not body.arxiv_id and not body.title:
        raise HTTPException(400, "at least one of content_sha256, doi, arxiv_id, or title is required")

    results = {"exact_sha": [], "same_work": [], "title_candidates": [], "status": "unmatched"}
    try:
        conn = get_read_conn()
    except sqlite3.DatabaseError as error:
        raise HTTPException(503, 'lookup catalog unavailable') from error
    try:
        # Tier 1: exact SHA match
        if body.content_sha256:
            sha = body.content_sha256.strip().lower()
            if len(sha) != 64 or not all(c in "0123456789abcdef" for c in sha):
                raise HTTPException(400, "content_sha256 must be a 64-character hex string")
            rows = conn.execute(
                """SELECT sf.id AS source_file_id, sf.work_id, sf.original_name, sf.status,
                          w.title, w.read_status, w.parse_status, w.arxiv_id, w.doi
                   FROM source_files sf LEFT JOIN works w ON w.id = sf.work_id
                   WHERE sf.content_sha256 = ?""",
                (sha,),
            ).fetchall()
            for r in rows:
                results["exact_sha"].append(dict(r))

        # Tier 2: same work via DOI or arXiv (different file = different version)
        if body.doi or body.arxiv_id:
            where, params = [], []
            if body.doi:
                where.append("w.doi = ?")
                params.append(body.doi.strip())
            if body.arxiv_id:
                where.append("w.arxiv_id = ?")
                params.append(body.arxiv_id.strip())
            query = f"""
                SELECT w.id AS work_id, w.title, w.arxiv_id, w.doi, w.read_status, w.parse_status,
                       (SELECT COUNT(*) FROM source_files sf WHERE sf.work_id = w.id) AS source_count
                FROM works w WHERE {' OR '.join(where)} LIMIT ?
            """
            rows = conn.execute(query, [*params, body.limit]).fetchall()
            for r in rows:
                results["same_work"].append(dict(r))

        # Tier 3: title candidates (fuzzy, NOT confirmed)
        if body.title:
            title = body.title.strip()
            if len(title) >= 3:
                rows = conn.execute(
                    """SELECT w.id AS work_id, w.title, w.arxiv_id, w.doi, w.read_status
                       FROM works w
                       WHERE w.title LIKE ? COLLATE NOCASE
                       LIMIT ?""",
                    (f"%{title}%", body.limit),
                ).fetchall()
                for r in rows:
                    # Don't duplicate entries already in same_work
                    if not any(sw["work_id"] == r["work_id"] for sw in results["same_work"]):
                        results["title_candidates"].append(dict(r))

        # Determine overall status
        if results["exact_sha"]:
            results["status"] = "exact_match"
        elif results["same_work"]:
            results["status"] = "same_work_different_version"
        elif results["title_candidates"]:
            results["status"] = "title_candidates_only"
        else:
            results["status"] = "not_found"

        # Add quarantined/archived visibility note
        all_works = {r["work_id"] for r in results["exact_sha"] if r.get("work_id")}
        all_works |= {r["work_id"] for r in results["same_work"]}
        all_works |= {r["work_id"] for r in results["title_candidates"]}
        if all_works:
            qmarks = ",".join("?" * len(all_works))
            archived = {
                r["id"]: r["read_status"]
                for r in conn.execute(
                    f"SELECT id, read_status FROM works WHERE id IN ({qmarks})",
                    list(all_works),
                ).fetchall()
            }
            results["work_statuses"] = {
                wid: {"read_status": status, "available": status not in ("quarantined", "archived")}
                for wid, status in archived.items()
            }

        return results
    except sqlite3.DatabaseError as error:
        raise HTTPException(503, 'lookup catalog query failed') from error
    finally:
        conn.close()


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
                "SELECT title, authors, year, doc_type, language, parse_status, read_status, "
                "arxiv_id, doi FROM works WHERE id = ?",
                (c["work_id"],),
            ).fetchone()
            if work:
                c["work_title"] = work["title"] or c["work_id"]
                c["work_year"] = work["year"]
                c["work_doc_type"] = work["doc_type"] or ""
                c["work_language"] = work["language"] or ""
                c["work_parse_status"] = work["parse_status"] or ""
                c["work_read_status"] = work["read_status"] or ""
                c["work_arxiv_id"] = work["arxiv_id"] or ""
                c["work_doi"] = work["doi"] or ""
            # Source file info
            src = conn.execute(
                "SELECT original_name, relative_source_path, file_size, content_sha256 FROM source_files WHERE id = ?",
                (c.get("source_file_id") or "",),
            ).fetchone()
            if src:
                c["source_original_name"] = src["original_name"] or ""
                c["source_file_size"] = src["file_size"] or 0
                c["content_sha256"] = src["content_sha256"] or ""
            # Fallback: if no sha yet, use the work's first active source_file sha
            if not c.get("content_sha256") and c.get("work_id"):
                fb = conn.execute(
                    "SELECT content_sha256 FROM source_files WHERE work_id = ? AND status = 'active' AND content_sha256 IS NOT NULL AND content_sha256 != '' ORDER BY id LIMIT 1",
                    (c["work_id"],),
                ).fetchone()
                if fb:
                    c["content_sha256"] = fb["content_sha256"] or ""

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


def _work_score(conn, work_id: str) -> int:
    """Score a work for dedup priority. Higher = better to keep.

    Criteria (from user discussion):
    - Has arxiv_id: +100
    - Has doi: +100
    - File size: +log2(size_kb)
    - Has an active bibliographic projection (vetted current value): +50

    LL-DECOUPLE-20260920: the legacy approved-tag count is no longer part of
    the score — retired classification data must not influence merge quality.
    """
    score = 0
    w = conn.execute("SELECT arxiv_id, doi FROM works WHERE id=?", (work_id,)).fetchone()
    if w:
        if w["arxiv_id"]:
            score += 100
        if w["doi"]:
            score += 100

    sf = conn.execute("SELECT file_size FROM source_files WHERE work_id=? AND status='active'", (work_id,)).fetchall()
    for s in sf:
        size_kb = max(1, (s["file_size"] or 0) / 1024)
        import math
        score += int(math.log2(size_kb))

    from .. import bibliographic_projection as projection
    if projection.get_active_projection(conn, work_id):
        score += 50

    return score


def _research_references(conn_unused, work_ids: list[str]):
    """Count research-store source rows still bound to each work (read-only).

    A merge never rewrites research identities; the counts are reported so the
    reviewer sees which merged secondaries still carry research references.
    Returns ``{"counts": {...} | None, "error": str | None}`` — when the
    research store cannot be read the counts are ``None`` (unknown), never a
    misleading zero (R1 L6).
    """
    out = {wid: 0 for wid in work_ids}
    result: dict = {"counts": out, "error": None}
    try:
        from contextlib import closing

        from ..research_context import get_research_context
        ctx = get_research_context()
        if not ctx.db_path.is_file():
            result["counts"] = None
            result["error"] = "research store not configured"
            return result
        with closing(ctx.connect(read_only=True)) as rconn:
            placeholders = ",".join("?" * len(work_ids))
            for row in rconn.execute(
                f"SELECT work_id, COUNT(*) AS n FROM research_sources "
                f"WHERE work_id IN ({placeholders}) GROUP BY work_id", work_ids):
                out[row["work_id"]] = row["n"]
    except Exception as error:  # noqa: BLE001 — surfaced, never faked as 0
        result["counts"] = None
        result["error"] = str(error)
    return result


def _merge_same_work(conn, work_ids: list[str], note: str, primary_work_id: str | None = None) -> dict:
    """Merge multiple works into one. Keeps the best, archives others.

    If ``primary_work_id`` is provided and is one of ``work_ids``, it is kept as
    the primary (human override); otherwise the primary is chosen by auto-score.
    Returns actions dict.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    actions = {"primary": "", "archived_sources": 0, "projection_transferred": 0,
               "quarantined": [], "research_references": {}}

    if len(work_ids) < 2:
        return actions

    # Choose primary: human override if valid, else auto-score
    if primary_work_id and primary_work_id in work_ids:
        primary = primary_work_id
        secondaries = [w for w in work_ids if w != primary_work_id]
    else:
        scored = [(wid, _work_score(conn, wid)) for wid in work_ids]
        scored.sort(key=lambda x: -x[1])
        primary = scored[0][0]
        secondaries = [s[0] for s in scored[1:]]
    actions["primary"] = primary

    # Research references are preserved as-is (identities are not rewritten);
    # report them so the reviewer knows merged secondaries stay traceable.
    actions["research_references"] = _research_references(conn, work_ids)

    from .. import bibliographic_projection as projection
    primary_has_projection = bool(projection.get_active_projection(conn, primary))

    for sec_id in secondaries:
        # Preserve the current bibliographic projection (R1 H1): if the
        # primary has no active projection but the secondary does, rebuild it
        # on the primary (origin source_kind/source_ref kept verbatim, note
        # records the merge) and supersede the secondary's original — the
        # merged work must not silently drop out of the exportable catalog.
        # When both have projections the primary keeps its own; the
        # secondary's stays in place (quarantined work, history intact).
        if not primary_has_projection:
            sec_projection = projection.get_active_projection(conn, sec_id)
            if sec_projection is not None:
                projection.upsert_projection(
                    conn, primary,
                    source_kind=sec_projection["source_kind"],
                    source_ref=sec_projection["source_ref"],
                    payload=sec_projection["payload"],
                    exportable=bool(sec_projection["exportable"]),
                    note=(f"transferred from merged work {sec_id} "
                          f"({sec_projection['source_kind']} "
                          f"{sec_projection['source_ref']}); dedup merge"))
                projection.supersede_active_projection(
                    conn, sec_id, superseded_by=f"dedup-merge-into-{primary}")
                actions["projection_transferred"] += 1
                primary_has_projection = True

        # Archive secondary's source files
        sec_sources = conn.execute(
            "SELECT id, source_path, original_name FROM source_files WHERE work_id=? AND status='active'",
            (sec_id,)
        ).fetchall()
        for s in sec_sources:
            src_path = Path(s["source_path"])
            archive_path = None
            if src_path.exists():
                archive_dir = LIBRARY_ROOT / "_archive" / "dedup" / sec_id
                archive_dir.mkdir(parents=True, exist_ok=True)
                dest_name = _safe_dest_name(dict(s), str(src_path))
                dest = _unique_dest(archive_dir / dest_name)
                shutil.move(str(src_path), str(dest))
                archive_path = str(dest)
            conn.execute(
                "UPDATE source_files SET status='archived', archived_at=?, archive_path=?, archive_reason=? WHERE id=?",
                (now, archive_path, f"merged into {primary}", s["id"])
            )
            actions["archived_sources"] += 1

        # Create same_work relation
        _create_relation(conn, primary, sec_id, "same_work", note or f"dedup merge")

        # Quarantine secondary
        conn.execute("UPDATE works SET read_status='quarantined', updated_at=? WHERE id=?", (now, sec_id))
        conn.execute(
            "INSERT OR IGNORE INTO work_codes (work_id, source_file_id, code, reason) VALUES (?, '', 'quarantined', ?)",
            (sec_id, f"merged into {primary}")
        )
        actions["quarantined"].append(sec_id)

    return actions


def _move_to_quarantine(conn, work_id: str, reason: str) -> list[str]:
    """Move source_files to _quarantine/{work_id}/, sync status='quarantined',
    and update DB. Returns moved paths. (Batch-friendly: skips missing files.)"""
    quarantine_dir = LIBRARY_ROOT / "_quarantine" / work_id
    moved = []
    sources = conn.execute(
        "SELECT id, source_path, original_name FROM source_files WHERE work_id = ?",
        (work_id,),
    ).fetchall()
    for s in sources:
        src = Path(s["source_path"])
        dest_name = _safe_dest_name(dict(s), str(src))
        if src.exists():
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            dest = _unique_dest(quarantine_dir / dest_name)
            shutil.move(str(src), str(dest))
            moved.append(str(dest))
            new_path = str(dest)
        else:
            # File absent on disk: still record the sanitized intended location.
            new_path = str(quarantine_dir / dest_name)
        # Update source_path + sync status to quarantined (P1-01: avoid drift)
        conn.execute(
            "UPDATE source_files SET source_path = ?, status = 'quarantined' WHERE id = ?",
            (new_path, s["id"]),
        )
    return moved


@router.get("/duplicates/{group_id}/merge-preview")
def merge_preview(group_id: str):
    """Preview a same_work merge for a title_candidate group.

    Returns each candidate work's auto-score and the machine-recommended primary,
    so the UI can show the recommendation and let a human override it.
    """
    conn = get_conn()
    try:
        group = conn.execute(
            "SELECT * FROM duplicate_groups WHERE id = ?", (group_id,)
        ).fetchone()
        if not group:
            raise HTTPException(status_code=404, detail="Duplicate group not found")

        rows = conn.execute(
            "SELECT DISTINCT work_id FROM duplicate_candidates WHERE group_id = ?",
            (group_id,),
        ).fetchall()
        work_ids = [r["work_id"] for r in rows if r["work_id"]]

        scored = [{"work_id": w, "score": _work_score(conn, w)} for w in work_ids]
        scored.sort(key=lambda x: -x["score"])
        recommended = scored[0]["work_id"] if scored else ""

        # Enrich with title for display
        for item in scored:
            w = conn.execute("SELECT title FROM works WHERE id = ?", (item["work_id"],)).fetchone()
            item["title"] = w["title"] if w else item["work_id"]

        return {"group_id": group_id, "candidates": scored, "recommended_primary": recommended}
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

        actions = {"relations_created": 0, "sources_removed": 0, "files_moved": [], "merged": None}

        # 2. Handle same_work on title_candidate: auto-merge
        if body.decision == "same_work" and group["duplicate_type"] == "title_candidate":
            cands = conn.execute(
                "SELECT DISTINCT work_id FROM duplicate_candidates WHERE group_id = ?",
                (group_id,),
            ).fetchall()
            work_ids = [c["work_id"] for c in cands]
            merge_result = _merge_same_work(conn, work_ids, body.note or f"dedup review {group_id}", body.primary_work_id)
            actions["merged"] = merge_result

        # 3. Create work_relations for other relation-type decisions
        elif body.decision in RELATION_TYPES:
            cands = conn.execute(
                "SELECT DISTINCT work_id FROM duplicate_candidates WHERE group_id = ?",
                (group_id,),
            ).fetchall()
            work_ids = [c["work_id"] for c in cands]

            # For same_work on exact_sha256: all candidates share the same work_id
            if body.decision == "same_work" and group["duplicate_type"] == "exact_sha256":
                pass
            else:
                for i in range(len(work_ids)):
                    for j in range(i + 1, len(work_ids)):
                        created = _create_relation(
                            conn, work_ids[i], work_ids[j],
                            body.decision,
                            body.note or f"dedup review {group_id}",
                        )
                        if created:
                            actions["relations_created"] += 1

        # 4. Clean up duplicate source_files for same_work on exact_sha256
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
