"""Lightweight source provenance for offline recovery (issue #5).

Records where each Work/Source was originally obtained so that lost originals
can be re-acquired. Reads never create a database or migrate a schema.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MAX_URL_LENGTH = 2048
MAX_NOTES_LENGTH = 2000
MAX_EXPORT_WORKS = 5000


def initialize(conn: sqlite3.Connection) -> None:
    conn.execute('''CREATE TABLE IF NOT EXISTS source_provenance (
        id TEXT PRIMARY KEY,
        work_id TEXT NOT NULL,
        source_file_id TEXT,
        landing_url TEXT DEFAULT '',
        direct_url TEXT DEFAULT '',
        backup_url TEXT DEFAULT '',
        source_type TEXT DEFAULT '',
        doi TEXT DEFAULT '',
        arxiv_id TEXT DEFAULT '',
        known_sha256 TEXT DEFAULT '',
        known_bytes INTEGER,
        first_obtained_at TEXT DEFAULT '',
        last_verified_at TEXT DEFAULT '',
        access_notes TEXT DEFAULT '',
        created_at TEXT NOT NULL)''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_source_provenance_work ON source_provenance(work_id)')
    expected = {'id', 'work_id', 'source_file_id', 'landing_url', 'direct_url', 'backup_url',
                'source_type', 'doi', 'arxiv_id', 'known_sha256', 'known_bytes',
                'first_obtained_at', 'last_verified_at', 'access_notes', 'created_at'}
    actual = {r[1] for r in conn.execute('PRAGMA table_info(source_provenance)')}
    if not expected <= actual:
        raise ValueError('incompatible source_provenance schema; explicit migration required')


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _validate_url(url: str, field: str) -> str:
    url = url.strip()
    if len(url) > MAX_URL_LENGTH:
        raise ValueError(f'{field} exceeds {MAX_URL_LENGTH} characters')
    return url


def record(conn: sqlite3.Connection, work_id: str, **kwargs) -> dict:
    conn.row_factory = sqlite3.Row
    """Insert or update provenance for a Work. Caller manages transaction."""
    if not work_id or not work_id.strip():
        raise ValueError('work_id is required')
    work_id = work_id.strip()

    for url_field in ('landing_url', 'direct_url', 'backup_url'):
        if kwargs.get(url_field):
            kwargs[url_field] = _validate_url(kwargs[url_field], url_field)
    if kwargs.get('access_notes') and len(kwargs['access_notes']) > MAX_NOTES_LENGTH:
        raise ValueError(f'access_notes exceeds {MAX_NOTES_LENGTH} characters')
    if kwargs.get('known_sha256') and len(kwargs['known_sha256']) != 64:
        raise ValueError('known_sha256 must be a 64-character hex string')

    initialize(conn)
    existing = conn.execute(
        'SELECT id FROM source_provenance WHERE work_id = ? ORDER BY created_at DESC LIMIT 1',
        (work_id,)).fetchone()

    prov_id = existing['id'] if existing else 'SP-' + hashlib.sha256(work_id.encode()).hexdigest()[:16]
    now = _now()

    fields = {'work_id': work_id, 'source_file_id': kwargs.get('source_file_id') or '',
              'landing_url': kwargs.get('landing_url') or '',
              'direct_url': kwargs.get('direct_url') or '',
              'backup_url': kwargs.get('backup_url') or '',
              'source_type': kwargs.get('source_type') or '',
              'doi': kwargs.get('doi') or '',
              'arxiv_id': kwargs.get('arxiv_id') or '',
              'known_sha256': kwargs.get('known_sha256') or '',
              'known_bytes': kwargs.get('known_bytes'),
              'first_obtained_at': kwargs.get('first_obtained_at') or '',
              'last_verified_at': kwargs.get('last_verified_at') or now,
              'access_notes': kwargs.get('access_notes') or ''}

    if existing:
        # merge: update non-empty fields only
        current = dict(conn.execute(
            'SELECT * FROM source_provenance WHERE id = ?', (prov_id,)).fetchone())
        for k, v in fields.items():
            if v or k == 'last_verified_at':
                current[k] = v
        current['last_verified_at'] = now
        conn.execute('''UPDATE source_provenance SET
            source_file_id=?, landing_url=?, direct_url=?, backup_url=?, source_type=?,
            doi=?, arxiv_id=?, known_sha256=?, known_bytes=?,
            first_obtained_at=?, last_verified_at=?, access_notes=?
            WHERE id=?''',
            (current['source_file_id'], current['landing_url'], current['direct_url'],
             current['backup_url'], current['source_type'], current['doi'], current['arxiv_id'],
             current['known_sha256'], current['known_bytes'],
             current['first_obtained_at'], current['last_verified_at'],
             current['access_notes'], prov_id))
    else:
        conn.execute('''INSERT INTO source_provenance
            (id, work_id, source_file_id, landing_url, direct_url, backup_url, source_type,
             doi, arxiv_id, known_sha256, known_bytes, first_obtained_at, last_verified_at,
             access_notes, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (prov_id, work_id, fields['source_file_id'], fields['landing_url'],
             fields['direct_url'], fields['backup_url'], fields['source_type'],
             fields['doi'], fields['arxiv_id'], fields['known_sha256'],
             fields['known_bytes'], fields['first_obtained_at'],
             fields['last_verified_at'], fields['access_notes'], now))

    row = conn.execute('SELECT * FROM source_provenance WHERE id = ?', (prov_id,)).fetchone()
    return dict(row)


def query(conn: sqlite3.Connection, work_id: str) -> list[dict]:
    conn.row_factory = sqlite3.Row
    """Read provenance records for a Work. Read-only; no schema creation."""
    try:
        rows = conn.execute(
            'SELECT * FROM source_provenance WHERE work_id = ? ORDER BY created_at DESC',
            (work_id,)).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []  # table doesn't exist yet


def export_catalog(conn: sqlite3.Connection, *, limit: int = MAX_EXPORT_WORKS) -> dict:
    conn.row_factory = sqlite3.Row
    """Export the full provenance catalog as a versioned, integrity-checkable manifest."""
    try:
        rows = [dict(r) for r in conn.execute(
            'SELECT * FROM source_provenance ORDER BY work_id').fetchall()]
    except sqlite3.OperationalError:
        rows = []
    if len(rows) > limit:
        rows = rows[:limit]

    catalog = {
        'format': 'litlib-source-provenance-v1',
        'generated_at': _now(),
        'entry_count': len(rows),
        'entries': rows,
    }
    # integrity digest over sorted entry JSON
    manifest_text = json.dumps(
        [{'work_id': e['work_id'], 'known_sha256': e['known_sha256'],
          'landing_url': e['landing_url'], 'source_file_id': e['source_file_id']}
         for e in rows],
        ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    catalog['integrity_sha256'] = hashlib.sha256(manifest_text.encode('utf-8')).hexdigest()
    return catalog
