"""Source-scoped recovery metadata; reads never initialize or migrate a schema."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone

MAX_URL_LENGTH = 2048
MAX_NOTES_LENGTH = 2000
MAX_EXPORT_WORKS = 5000
FORMAT = 'litlib-source-provenance-v2'
DIGEST_SCOPE = 'format,digest_scope,entry_count,total_count,truncated,entries; canonical UTF-8 JSON'
FIELDS = ('work_id', 'source_file_id', 'landing_url', 'direct_url', 'backup_url',
          'source_type', 'doi', 'arxiv_id', 'known_sha256', 'known_bytes',
          'first_obtained_at', 'last_verified_at', 'access_notes', 'created_at')


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def _exists(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def initialize(conn: sqlite3.Connection) -> None:
    """Write-only additive schema setup. Caller owns transaction/rollback."""
    conn.execute('''CREATE TABLE IF NOT EXISTS source_provenance (
        id TEXT PRIMARY KEY, work_id TEXT NOT NULL, source_file_id TEXT,
        landing_url TEXT DEFAULT '', direct_url TEXT DEFAULT '', backup_url TEXT DEFAULT '',
        source_type TEXT DEFAULT '', doi TEXT DEFAULT '', arxiv_id TEXT DEFAULT '',
        known_sha256 TEXT DEFAULT '', known_bytes INTEGER, first_obtained_at TEXT DEFAULT '',
        last_verified_at TEXT DEFAULT '', access_notes TEXT DEFAULT '', created_at TEXT NOT NULL)''')
    actual = {r[1] for r in conn.execute('PRAGMA table_info(source_provenance)')}
    if not (set(FIELDS) | {'id'}) <= actual:
        raise ValueError('incompatible source_provenance schema; explicit migration required')
    # NULL and empty Source both mean the separate Work-level identity.
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_provenance_identity ON source_provenance(work_id, COALESCE(source_file_id,''))")
    conn.execute('''CREATE TABLE IF NOT EXISTS source_provenance_revisions (
        provenance_id TEXT NOT NULL, revision INTEGER NOT NULL,
        recorded_at TEXT NOT NULL, origin TEXT NOT NULL, payload TEXT NOT NULL,
        PRIMARY KEY(provenance_id, revision))''')


def _append(conn, row, origin):
    revision = conn.execute('SELECT COALESCE(MAX(revision),0)+1 FROM source_provenance_revisions WHERE provenance_id=?',
                            (row['id'],)).fetchone()[0]
    conn.execute('INSERT INTO source_provenance_revisions VALUES(?,?,?,?,?)',
                 (row['id'], revision, _now(), origin, _json(row)))


def preserve_legacy(conn: sqlite3.Connection) -> int:
    """Explicit idempotent backfill preserving old values without certifying them.

    Does not commit. Duplicate legacy identities fail rather than merging history.
    """
    if not conn.in_transaction:
        conn.execute('BEGIN IMMEDIATE')
    conn.row_factory = sqlite3.Row
    initialize(conn)
    count = 0
    for row in conn.execute('SELECT * FROM source_provenance ORDER BY id').fetchall():
        if not conn.execute('SELECT 1 FROM source_provenance_revisions WHERE provenance_id=?', (row['id'],)).fetchone():
            _append(conn, dict(row), 'legacy_unverified')
            count += 1
    return count


def record(conn: sqlite3.Connection, work_id: str, **kwargs) -> dict:
    """Patch one identity, appending immutable snapshots of every effective change.

    Missing fields keep their value; explicit empty strings clear text fields.
    Source identity is a selector, never a field patched onto another identity.
    """
    if not work_id or not work_id.strip():
        raise ValueError('work_id is required')
    work_id = work_id.strip()
    unknown = set(kwargs) - (set(FIELDS) - {'work_id', 'created_at'})
    if unknown:
        raise ValueError('unknown provenance fields: ' + ', '.join(sorted(unknown)))
    source_id = kwargs.pop('source_file_id', None) or ''
    if not isinstance(source_id, str):
        raise ValueError('source_file_id must be a string')
    for key, value in kwargs.items():
        if key == 'known_bytes':
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError('known_bytes must be a nonnegative integer')
        elif not isinstance(value, str):
            raise ValueError(key + ' must be a string')
        if key.endswith('_url'):
            kwargs[key] = value.strip()
            if len(kwargs[key]) > MAX_URL_LENGTH:
                raise ValueError(key + ' exceeds URL length budget')
    if len(kwargs.get('access_notes', '')) > MAX_NOTES_LENGTH:
        raise ValueError('access_notes exceeds notes length budget')
    sha = kwargs.get('known_sha256', '').lower()
    if sha and (len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha)):
        raise ValueError('known_sha256 must be a 64-character hex string')
    if 'known_sha256' in kwargs:
        kwargs['known_sha256'] = sha
    if not conn.in_transaction:
        conn.execute('BEGIN IMMEDIATE')
    conn.row_factory = sqlite3.Row
    initialize(conn)
    existing = conn.execute("SELECT * FROM source_provenance WHERE work_id=? AND COALESCE(source_file_id,'')=?",
                            (work_id, source_id)).fetchone()
    if existing:
        current = dict(existing)
        # Preserve the exact original row, including ID and NULLs, before first change.
        if not conn.execute('SELECT 1 FROM source_provenance_revisions WHERE provenance_id=?', (current['id'],)).fetchone():
            _append(conn, current, 'legacy_unverified')
        updated = {**current, **kwargs}
        if updated != current:
            conn.execute('UPDATE source_provenance SET ' + ','.join(k + '=?' for k in kwargs) + ' WHERE id=?',
                         [*kwargs.values(), current['id']])
            _append(conn, updated, 'recorded')
        return updated
    now = _now()
    identity = _json([work_id, source_id])
    row = {k: '' for k in FIELDS}
    row.update(id='SP-' + hashlib.sha256(identity.encode()).hexdigest(),
               work_id=work_id, source_file_id=source_id, known_bytes=None, created_at=now)
    row.update(kwargs)
    columns = ['id', *FIELDS]
    conn.execute('INSERT INTO source_provenance (' + ','.join(columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')',
                 [row[k] for k in columns])
    _append(conn, row, 'recorded')
    return row


def _with_history(conn, rows):
    has_history = _exists(conn, 'source_provenance_revisions')
    entries = []
    for row in rows:
        entry = dict(row)
        history = []
        if has_history:
            for revision in conn.execute('SELECT revision,recorded_at,origin,payload FROM source_provenance_revisions WHERE provenance_id=? ORDER BY revision', (entry['id'],)):
                history.append({'revision': revision['revision'], 'recorded_at': revision['recorded_at'],
                                'origin': revision['origin'], 'record': json.loads(revision['payload'])})
        entry['history'] = history
        # A subsequent edit cannot prove that a pre-fix URL/fingerprint was sound.
        entry['legacy_review_required'] = not history or any(r['origin'] == 'legacy_unverified' for r in history)
        entries.append(entry)
    return entries


def query(conn: sqlite3.Connection, work_id: str) -> list[dict]:
    conn.row_factory = sqlite3.Row
    own_transaction = not conn.in_transaction
    if own_transaction:
        conn.execute('BEGIN')
    try:
        if not _exists(conn, 'source_provenance'):
            return []
        return _with_history(conn, conn.execute('SELECT * FROM source_provenance WHERE work_id=? ORDER BY created_at DESC,id', (work_id,)).fetchall())
    finally:
        if own_transaction:
            conn.rollback()


def _digest(catalog):
    payload = {k: catalog[k] for k in ('format', 'digest_scope', 'entry_count', 'total_count', 'truncated', 'entries')}
    return hashlib.sha256(_json(payload).encode('utf-8')).hexdigest()


def verify_catalog(catalog: dict) -> bool:
    """v2 only: historical v1 used two incompatible digest algorithms."""
    try:
        return (catalog['format'] == FORMAT and catalog['digest_scope'] == DIGEST_SCOPE
                and catalog['entry_count'] == len(catalog['entries'])
                and catalog['integrity_sha256'] == _digest(catalog))
    except (KeyError, TypeError, ValueError):
        return False


def export_catalog(conn: sqlite3.Connection, *, limit: int = MAX_EXPORT_WORKS) -> dict:
    if type(limit) is not int or not 1 <= limit <= MAX_EXPORT_WORKS:
        raise ValueError('invalid export limit')
    conn.row_factory = sqlite3.Row
    # One read snapshot covers both current rows and their history/counts.
    own_transaction = not conn.in_transaction
    if own_transaction:
        conn.execute('BEGIN')
    try:
        rows, total = [], 0
        if _exists(conn, 'source_provenance'):
            total = conn.execute('SELECT COUNT(*) FROM source_provenance').fetchone()[0]
            rows = conn.execute("SELECT * FROM source_provenance ORDER BY work_id,COALESCE(source_file_id,''),id LIMIT ?", (limit,)).fetchall()
        catalog = {'format': FORMAT, 'generated_at': _now(), 'digest_scope': DIGEST_SCOPE,
                   'entry_count': len(rows), 'total_count': total, 'truncated': total > len(rows),
                   'entries': _with_history(conn, rows)}
        catalog['integrity_sha256'] = _digest(catalog)
        return catalog
    finally:
        if own_transaction:
            conn.rollback()  # release read snapshot; never commit a caller's writes
