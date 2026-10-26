"""Work purpose history. Reads never create a database or migrate a schema."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

PURPOSE_MAX_LENGTH = 2000


class PurposeConflict(ValueError):
    pass


def validate_purpose(purpose: str) -> str:
    if not isinstance(purpose, str) or not purpose.strip():
        raise ValueError('ingest purpose is required; blank or whitespace-only is not accepted')
    purpose = purpose.strip()
    if len(purpose) > PURPOSE_MAX_LENGTH:
        raise ValueError(f'ingest purpose exceeds {PURPOSE_MAX_LENGTH} characters')
    return purpose


def request_id(value: str = '') -> str:
    import uuid
    value = value.strip() or str(uuid.uuid4())
    if len(value) > 200:
        raise ValueError('request_id exceeds 200 characters')
    return value


def initialize(conn):
    # execute(), not executescript(): retain the caller's transaction.
    conn.execute('''CREATE TABLE IF NOT EXISTS ingest_notes (
        id TEXT PRIMARY KEY, work_id TEXT NOT NULL, source_file_id TEXT,
        purpose TEXT NOT NULL, actor TEXT DEFAULT '', created_at TEXT NOT NULL,
        request_id TEXT NOT NULL, UNIQUE(request_id, work_id))''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_ingest_notes_work ON ingest_notes(work_id, created_at)')
    conn.execute('''CREATE TABLE IF NOT EXISTS ingest_purpose_requests (
        request_id TEXT PRIMARY KEY, purpose TEXT NOT NULL,
        target_signature TEXT NOT NULL, created_at TEXT NOT NULL)''')
    expected = {'id','work_id','source_file_id','purpose','actor','created_at','request_id'}
    if not expected <= {r[1] for r in conn.execute('PRAGMA table_info(ingest_notes)')}:
        raise ValueError('incompatible ingest_notes schema; explicit migration required')
    unique_indexes = [r[1] for r in conn.execute('PRAGMA index_list(ingest_notes)') if r[2]]
    if not any([r[2] for r in conn.execute('PRAGMA index_info("'+name.replace('"','""')+'")')] == ['request_id','work_id'] for name in unique_indexes):
        raise ValueError('ingest_notes requires a unique request_id/work_id constraint')


def signature(targets):
    return json.dumps(sorted(set(targets)), ensure_ascii=False, separators=(',', ':'))


def check_request(conn, rid, purpose, targets=None):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='ingest_purpose_requests'").fetchone():
        return False
    row = conn.execute('SELECT purpose,target_signature FROM ingest_purpose_requests WHERE request_id=?', (rid,)).fetchone()
    if row and (row[0] != purpose or (targets is not None and row[1] != signature(targets))):
        raise PurposeConflict('request_id already belongs to a different purpose or set of files/works')
    return bool(row)


def validate_targets(conn, targets, *, planned=(), pending_sources=()):
    """Validate purpose targets before any write.

    ``planned`` lists work ids the caller will CREATE, so nothing can be
    checked against them yet.  ``pending_sources`` lists exact
    ``(work_id, source_file_id)`` pairs the caller will INSERT into already
    existing works inside this same operation (issue #15): their ownership
    check defers to :func:`write_notes`, which re-runs this validation after
    the insert within the same transaction.  The work lifecycle checks still
    apply, and a source id that already exists under a different work is
    rejected here instead of failing the insert later.
    """
    planned = set(planned)
    pending = {(wid, sfid) for wid, sfid in pending_sources if sfid}
    for wid, sfid in targets.items():
        if wid in planned:
            continue
        row = conn.execute('SELECT read_status FROM works WHERE id=?', (wid,)).fetchone()
        if row is None:
            raise ValueError(f'work {wid} not found')
        if row[0] == 'quarantined':
            raise ValueError(f'work {wid} is quarantined; review its lifecycle before adding a purpose')
        if not sfid:
            continue
        if (wid, sfid) in pending:
            owner = conn.execute('SELECT work_id FROM source_files WHERE id=?', (sfid,)).fetchone()
            if owner is not None and owner[0] != wid:
                raise ValueError('source_file_id already belongs to another work')
            continue
        if not conn.execute('SELECT 1 FROM source_files WHERE id=? AND work_id=?', (sfid, wid)).fetchone():
            raise ValueError('source_file_id does not belong to this work')


def write_notes(conn, targets, purpose, rid, actor='', *, request_targets=None):
    purpose = validate_purpose(purpose)
    rid = request_id(rid)
    validate_targets(conn, targets)
    scope = request_targets if request_targets is not None else [('work', wid) for wid in targets]
    check_request(conn, rid, purpose, scope)
    now = datetime.now(timezone.utc).isoformat(timespec='microseconds')
    conn.execute('INSERT OR IGNORE INTO ingest_purpose_requests VALUES (?,?,?,?)', (rid,purpose,signature(scope),now))
    inserted = 0
    for wid, sfid in sorted(targets.items()):
        existing = conn.execute('SELECT purpose FROM ingest_notes WHERE request_id=? AND work_id=?', (rid,wid)).fetchone()
        if existing:
            if existing[0] != purpose:
                raise PurposeConflict('request_id already belongs to a different purpose')
            continue
        nid = 'IN-' + hashlib.sha256(json.dumps([rid,wid]).encode()).hexdigest()[:24]
        conn.execute('INSERT INTO ingest_notes VALUES (?,?,?,?,?,?,?)', (nid,wid,sfid or None,purpose,actor,now,rid))
        inserted += 1
    return {'purposes_saved': inserted, 'purposes_already_existed': len(targets)-inserted,
            'works_annotated': len(targets), 'purpose': purpose,
            'items': [{'work_id':wid,'source_file_id':sfid or None} for wid,sfid in sorted(targets.items())]}


def query(library_root: Path, work_id: str, limit=50, offset=0):
    path = Path(library_root)/'literature.sqlite'
    if not path.is_file():
        return []
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='ingest_notes'").fetchone():
            return []
        return [dict(r) for r in conn.execute('SELECT * FROM ingest_notes WHERE work_id=? ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?', (work_id,max(1,min(limit,200)),max(0,offset)))]


def append(library_root, work_id, purpose, rid, source_file_id=None):
    purpose = validate_purpose(purpose)
    rid = request_id(rid)
    with sqlite3.connect(Path(library_root)/'literature.sqlite') as conn:
        conn.execute('BEGIN IMMEDIATE')
        validate_targets(conn, {work_id:source_file_id})
        initialize(conn)
        return write_notes(conn,{work_id:source_file_id},purpose,rid,
                           request_targets=[('work',work_id,source_file_id or '')])


def replay(library_root, rid, purpose):
    """Replay a completed inbox operation after its inputs were archived."""
    path = Path(library_root)/'literature.sqlite'
    if not path.is_file():
        return None
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as conn:
        if not check_request(conn,rid,purpose):
            return None
        rows = conn.execute('SELECT work_id,source_file_id FROM ingest_notes WHERE request_id=?',(rid,)).fetchall()
        return {'purposes_saved':0,'purposes_already_existed':len(rows),'works_annotated':len(rows),
                'purpose':purpose,'items':[{'work_id':w,'source_file_id':s} for w,s in rows]}
