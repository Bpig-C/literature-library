"""Shared quarantine / restore nucleus — one policy for every review surface.

V1 invariant: moving a work's source files into ``_quarantine/`` MUST be
accompanied by setting ``source_files.status='quarantined'`` (and
``works.read_status='quarantined'``); restore MUST reverse both. Without this,
``scripts/healthcheck_library.py`` reports status inconsistency
("quarantined work + active source", "source in _quarantine but status !=
quarantined") — i.e. a supported UI action could make a clean library unhealthy.

Policy: strict by default. If any source file is missing on disk, raise 409
BEFORE moving anything. The pre-check runs before any file move and the caller
has not committed, so a 409 leaves DB and filesystem unchanged (no
half-isolation). Callers that need best-effort batch semantics pass strict=False.

These functions do NOT commit and do NOT touch extraction review state; callers
handle their own domain cascade and the final commit.
"""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from .path_safety import _safe_dest_name, _unique_dest


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def quarantine_work_sources(
    conn, library_root, work_id, *, reason="", code="bad_source", strict=True
):
    """Move all of work_id's source_files into ``_quarantine/{work_id}/`` and mark
    the work + its sources quarantined. Returns list of moved dest paths.

    ``code`` is the work_codes.code value written (works/duplicates use
    'bad_source', metadata/classification pass 'quarantined').
    """
    work = conn.execute("SELECT id FROM works WHERE id = ?", (work_id,)).fetchone()
    if not work:
        raise HTTPException(status_code=404, detail="Work not found")

    quarantine_dir = Path(library_root) / "_quarantine" / work_id
    sources = conn.execute(
        "SELECT id, source_path, original_name FROM source_files WHERE work_id = ?",
        (work_id,),
    ).fetchall()

    # Pre-check: plan every move before touching the filesystem.
    planned: list[tuple[Path, Path, str]] = []  # (src, dest, source_file_id)
    missing: list[str] = []
    for s in sources:
        src = Path(s["source_path"])
        if not src.exists():
            missing.append(str(src))
            continue
        dest_name = _safe_dest_name(dict(s), s["source_path"])
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        planned.append((src, _unique_dest(quarantine_dir / dest_name), s["id"]))

    if strict and missing:
        raise HTTPException(
            status_code=409,
            detail={"error": "missing_source_files", "missing": missing},
        )

    now = _now()
    archive_reason = reason or "quarantined"
    moved: list[str] = []
    for src, dest, sf_id in planned:
        shutil.move(str(src), str(dest))
        moved.append(str(dest))
        conn.execute(
            "UPDATE source_files SET source_path = ?, status = 'quarantined', "
            "archived_at = ?, archive_path = ?, archive_reason = ? WHERE id = ?",
            (str(dest), now, str(dest), archive_reason, sf_id),
        )

    # Any source row not physically moved (missing under non-strict) still reflects
    # quarantine so DB state matches works.read_status.
    conn.execute(
        "UPDATE source_files SET status = 'quarantined' "
        "WHERE work_id = ? AND status != 'quarantined'",
        (work_id,),
    )
    conn.execute(
        "UPDATE works SET read_status = 'quarantined', updated_at = ? WHERE id = ?",
        (now, work_id),
    )
    try:
        conn.execute(
            "INSERT INTO work_codes (work_id, source_file_id, code, reason) "
            "VALUES (?, '', ?, ?)",
            (work_id, code, archive_reason),
        )
    except Exception:
        pass  # duplicate code entry is fine (UNIQUE(work_id, code))
    return moved


def restore_work_sources(conn, library_root, work_id, *, strict=True):
    """Reverse quarantine: move source_files back to ``works/{work_id}/source/``,
    set works.read_status='unread' and source_files.status='active'.

    Returns list of moved dest paths.
    """
    work = conn.execute("SELECT id FROM works WHERE id = ?", (work_id,)).fetchone()
    if not work:
        raise HTTPException(status_code=404, detail="Work not found")

    work_dir = Path(library_root) / "works" / work_id / "source"
    sources = conn.execute(
        "SELECT id, source_path, original_name FROM source_files WHERE work_id = ?",
        (work_id,),
    ).fetchall()

    planned: list[tuple[Path, Path, str]] = []
    missing: list[str] = []
    for s in sources:
        src = Path(s["source_path"])
        if not src.exists():
            missing.append(str(src))
            continue
        dest_name = _safe_dest_name(dict(s), s["source_path"])
        work_dir.mkdir(parents=True, exist_ok=True)
        planned.append((src, _unique_dest(work_dir / dest_name), s["id"]))

    if strict and missing:
        raise HTTPException(
            status_code=409,
            detail={"error": "missing_source_files", "missing": missing},
        )

    now = _now()
    moved: list[str] = []
    for src, dest, sf_id in planned:
        shutil.move(str(src), str(dest))
        moved.append(str(dest))
        conn.execute(
            "UPDATE source_files SET source_path = ?, status = 'active', "
            "archived_at = NULL, archive_path = NULL, archive_reason = NULL WHERE id = ?",
            (str(dest), sf_id),
        )
    conn.execute(
        "UPDATE source_files SET status = 'active' "
        "WHERE work_id = ? AND status != 'active'",
        (work_id,),
    )
    conn.execute(
        "UPDATE works SET read_status = 'unread', updated_at = ? WHERE id = ?",
        (now, work_id),
    )
    conn.execute(
        "DELETE FROM work_codes WHERE work_id = ? AND code IN ('bad_source', 'quarantined')",
        (work_id,),
    )

    quarantine_dir = Path(library_root) / "_quarantine" / work_id
    if quarantine_dir.exists():
        try:
            quarantine_dir.rmdir()  # only removes if empty
        except OSError:
            pass
    return moved
