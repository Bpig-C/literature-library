"""Per-execution, allowlisted diagnostics; no provider messages or signed URLs."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import re
from datetime import datetime, timezone

_sink = ContextVar('producer_event_sink', default=None)


def emit(stage, **fields):
    sink = _sink.get()
    if sink: sink(stage, **fields)


@contextmanager
def capture(registry, job_id):
    def save(stage, **fields):
        event = {'stage': stage, 'at': datetime.now(timezone.utc).isoformat()}
        for key in ('task_id', 'error_code', 'http_status', 'provider_code', 'backend'):
            value = fields.get(key)
            if value is not None and re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', str(value)):
                event[key] = value
        with registry.conn(write=True) as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS producer_diagnostics(job_id TEXT PRIMARY KEY, detail TEXT NOT NULL)')
            prior = conn.execute('SELECT detail FROM producer_diagnostics WHERE job_id=?', (job_id,)).fetchone()
            history = json.loads(prior[0]) if prior else []
            history.append(event)
            conn.execute('INSERT OR REPLACE INTO producer_diagnostics VALUES(?,?)', (job_id,json.dumps(history[-24:])))
            if event.get('task_id'):
                conn.execute('UPDATE storage_producer_jobs SET task_id=? WHERE id=?', (event['task_id'],job_id))
            if event.get('backend'):
                conn.execute('UPDATE storage_producer_jobs SET backend=? WHERE id=?', (event['backend'],job_id))
    token = _sink.set(save)
    try:
        yield save
    finally:
        _sink.reset(token)


def read(conn, job_id):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='producer_diagnostics'").fetchone(): return []
    row = conn.execute('SELECT detail FROM producer_diagnostics WHERE job_id=?', (job_id,)).fetchone()
    return json.loads(row[0]) if row else []
