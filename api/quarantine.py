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
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from .path_safety import _safe_dest_name, _unique_dest

RESTORE_STATE_CODE = 'quarantine_restore_state'


def get_restore_read_state(conn, work_id):
    work = conn.execute('SELECT read_status FROM works WHERE id=?', (work_id,)).fetchone()
    if not work:
        raise HTTPException(404, 'Work not found')
    if work['read_status'] != 'quarantined':
        return work['read_status'], 'already_active'
    saved = conn.execute('SELECT reason FROM work_codes WHERE work_id=? AND code=?', (work_id, RESTORE_STATE_CODE)).fetchone()
    if not saved:
        # Compatibility only: the historical state is unknown, not inferred.
        return 'unread', 'legacy_default_unread'
    try:
        value = json.loads(saved['reason'])
        status = value['read_status']
        if value['version'] != 1 or not isinstance(status, str) or not status or status == 'quarantined':
            raise ValueError('Invalid saved state')
    except (ValueError, TypeError, KeyError):
        raise HTTPException(409, 'Invalid saved quarantine reading state')
    return status, 'recorded_before_quarantine'


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
    work = conn.execute("SELECT id, read_status FROM works WHERE id = ?", (work_id,)).fetchone()
    if not work:
        raise HTTPException(status_code=404, detail="Work not found")
    if work['read_status'] == 'quarantined':
        return []  # Retrying must not overwrite the original reading state.
    if not isinstance(work['read_status'], str) or not work['read_status']:
        raise HTTPException(409, 'Reading state is missing; cannot record quarantine restore state')
    from .storage.runtime import enabled
    if enabled():
        from .storage.runtime import configured_registry
        registry=configured_registry();registry.validate()
        sources=conn.execute('SELECT id FROM source_files WHERE work_id=?',(work_id,)).fetchall()
        for source in sources:registry.binding(source['id'],'pdf',1)
        conn.execute("INSERT INTO work_codes(work_id,source_file_id,code,reason) VALUES(?,'',?,?) ON CONFLICT(work_id,code) DO UPDATE SET reason=excluded.reason",(work_id,RESTORE_STATE_CODE,json.dumps({'version':1,'read_status':work['read_status']})))
        conn.execute("UPDATE source_files SET status='quarantined',archived_at=?,archive_reason=? WHERE work_id=?",(_now(),reason or 'quarantined',work_id))
        conn.execute("UPDATE works SET read_status='quarantined',updated_at=? WHERE id=?",(_now(),work_id))
        return []  # Logical state only; shared immutable objects and local originals remain.

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
    conn.execute(
        'INSERT INTO work_codes (work_id,source_file_id,code,reason) VALUES (?,\'\',?,?) '
        'ON CONFLICT(work_id,code) DO UPDATE SET reason=excluded.reason',
        (work_id, RESTORE_STATE_CODE, json.dumps({'version': 1, 'read_status': work['read_status']})),
    )
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
    restore the recorded reading state and source_files.status='active'.
    Historical quarantines without a saved state use the explicit legacy default.

    Returns list of moved dest paths.
    """
    work = conn.execute("SELECT id, read_status FROM works WHERE id = ?", (work_id,)).fetchone()
    if not work:
        raise HTTPException(status_code=404, detail="Work not found")
    if work['read_status'] != 'quarantined':
        return []  # Repeated restore must not reset or move an active work.
    read_status, _ = get_restore_read_state(conn, work_id)
    from .storage.runtime import enabled
    if enabled():
        conn.execute("UPDATE source_files SET status='active',archived_at=NULL,archive_path=NULL,archive_reason=NULL WHERE work_id=?",(work_id,))
        conn.execute('UPDATE works SET read_status=?,updated_at=? WHERE id=?',(read_status,_now(),work_id))
        conn.execute('DELETE FROM work_codes WHERE work_id=? AND code IN (?,?,?)',(work_id,RESTORE_STATE_CODE,'bad_source','quarantined'))
        return []

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
        "UPDATE works SET read_status = ?, updated_at = ? WHERE id = ?",
        (read_status, now, work_id),
    )
    conn.execute(
        "DELETE FROM work_codes WHERE work_id = ? AND code IN ('bad_source', 'quarantined')",
        (work_id,),
    )
    conn.execute('DELETE FROM work_codes WHERE work_id=? AND code=?', (work_id, RESTORE_STATE_CODE))

    quarantine_dir = Path(library_root) / "_quarantine" / work_id
    if quarantine_dir.exists():
        try:
            quarantine_dir.rmdir()  # only removes if empty
        except OSError:
            pass
    return moved
