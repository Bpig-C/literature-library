"""Portable producer identity, persisted before any filesystem/network work.

No credentials or absolute paths: the catalog snapshot can authorize a fresh
output directory after cold restore, but never adopt an unowned existing one.
"""
from datetime import datetime, timezone


def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS producer_recovery(
        job_id TEXT PRIMARY KEY, source_file_id TEXT NOT NULL, parse_run_id TEXT NOT NULL,
        version INTEGER NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL,
        submission TEXT NOT NULL, created_at TEXT NOT NULL)''')


def create(conn, jid, sid, rid, version, sha, size):
    initialize(conn)
    conn.execute('INSERT INTO producer_recovery VALUES(?,?,?,?,?,?,?,?)',
                 (jid,sid,rid,version,sha,size,'not_started',datetime.now(timezone.utc).isoformat()))


def read(conn, jid):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='producer_recovery'").fetchone():
        return None
    row=conn.execute('SELECT * FROM producer_recovery WHERE job_id=?',(jid,)).fetchone()
    return dict(row) if row else None


def record_stage(conn, jid, stage):
    # A submitting intent is durable BEFORE POST. Only explicit evidence can
    # refine unknown; later errors/polling must never erase that evidence.
    state={'submitting':'unknown','submission_unknown':'unknown',
           'upstream_submitted':'known','submission_rejected':'rejected'}.get(stage)
    if state and read(conn,jid):
        conn.execute('UPDATE producer_recovery SET submission=? WHERE job_id=?',(state,jid))
