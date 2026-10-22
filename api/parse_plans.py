"""Frozen, budgeted parse plans. Serial steps retain the existing authority guard.

Reads never migrate. Acceptance/steps are authorized writes. A disconnected
caller queries the same plan; a crashed submitting item is never resubmitted.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .storage.core import StorageError, checked_sha, file_lock


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def instant(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, AttributeError, TypeError):
        return None


class Selection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    work_ids: list[str] = Field(default_factory=list, max_length=1000)
    source_file_ids: list[str] = Field(default_factory=list, max_length=1000)
    request_ids: list[str] = Field(default_factory=list, max_length=1000)
    purpose: str | None = Field(default=None, min_length=1, max_length=2000)
    time_field: Literal['work_created', 'source_imported', 'purpose_created'] = 'source_imported'
    from_time: str | None = None
    to_time: str | None = None
    source_policy: Literal['single', 'all'] = 'single'
    backend: Literal['vlm', 'pymupdf']
    reparse_completed: bool = False

    @model_validator(mode='after')
    def validate_scope(self):
        if not any((self.work_ids, self.source_file_ids, self.request_ids, self.purpose,
                    self.from_time, self.to_time)):
            raise ValueError('explicit IDs, purpose or time range required')
        for value in (self.from_time, self.to_time):
            if value is not None and instant(value) is None:
                raise ValueError('time requires ISO8601 with explicit timezone')
        if self.from_time and self.to_time and instant(self.from_time) >= instant(self.to_time):
            raise ValueError('from_time must precede to_time; interval is [from,to)')
        return self


def within(value, selection):
    if not selection.from_time and not selection.to_time:
        return True
    stamp = instant(value)
    return stamp is not None and (not selection.from_time or stamp >= instant(selection.from_time)) and (
        not selection.to_time or stamp < instant(selection.to_time))


def preview(conn, selection: Selection):
    """One read transaction; no PDF downloads, writes or implicit latest batch."""
    conn.execute('BEGIN')
    clauses, args = [], []
    for values, column in ((selection.work_ids, 'w.id'), (selection.source_file_ids, 'sf.id')):
        if values:
            clauses.append(column + ' IN (' + ','.join('?' for _ in values) + ')')
            args.extend(values)
    note_filter = bool(selection.request_ids or selection.purpose or selection.time_field == 'purpose_created')
    notes_exist = conn.execute("SELECT 1 FROM sqlite_master WHERE name='ingest_notes'").fetchone()
    if note_filter and not notes_exist:
        raise StorageError('configuration_error', 'purpose history unavailable; cannot infer matches')
    if note_filter:
        conditions = ['n.work_id=w.id', '(n.source_file_id IS NULL OR n.source_file_id=sf.id)']
        if selection.request_ids:
            conditions.append('n.request_id IN (' + ','.join('?' for _ in selection.request_ids) + ')')
            args.extend(selection.request_ids)
        if selection.purpose:
            conditions.append('instr(n.purpose,?)>0'); args.append(selection.purpose)
        clauses.append('EXISTS(SELECT 1 FROM ingest_notes n WHERE ' + ' AND '.join(conditions) + ')')
    rows = conn.execute('''SELECT sf.id source_file_id,sf.work_id,sf.content_sha256,
        sf.file_size,sf.status source_status,sf.import_time,w.created_at,w.read_status,
        (SELECT count(*) FROM source_files s WHERE s.work_id=w.id AND s.status='active') source_count
        FROM source_files sf JOIN works w ON w.id=sf.work_id WHERE ''' +
        (' AND '.join(clauses) or '1=1') + ' ORDER BY sf.id LIMIT 5001', args).fetchall()
    if len(rows) > 5000:
        raise StorageError('invalid_request', 'selection exceeds 5000 sources; narrow scope')
    items, excluded = [], []
    for row in rows:
        row = dict(row)
        sid, wid = row['source_file_id'], row['work_id']
        matches = []
        if note_filter:
            for note in conn.execute('SELECT request_id,purpose,created_at,source_file_id FROM ingest_notes WHERE work_id=?', (wid,)):
                note = dict(note)
                if note['source_file_id'] and note['source_file_id'] != sid: continue
                if selection.request_ids and note['request_id'] not in selection.request_ids: continue
                if selection.purpose and selection.purpose not in note['purpose']: continue
                if selection.time_field == 'purpose_created' and not within(note['created_at'], selection): continue
                matches.append(note)
            if not matches:
                excluded.append(dict(work_id=wid, source_file_id=sid, reason='purpose_time_not_matched')); continue
        field = {'work_created': 'created_at', 'source_imported': 'import_time'}.get(selection.time_field)
        if field and not within(row[field], selection):
            excluded.append(dict(work_id=wid, source_file_id=sid, reason='time_not_matched_or_unknown')); continue
        jobs = [dict(r) for r in conn.execute("SELECT id,state,version,backend,task_id FROM storage_producer_jobs WHERE kind='parse' AND source_file_id=? ORDER BY version DESC", (sid,))]
        runs = [dict(r) for r in conn.execute('SELECT id,status,backend FROM literature_parse_runs WHERE source_file_id=? ORDER BY id', (sid,))]
        successful = [r for r in runs if r['status'] == 'succeeded' and r['backend'] == selection.backend and conn.execute("SELECT 1 FROM storage_bindings WHERE identity=? AND role='md'", (r['id'],)).fetchone()]
        reason = None
        from .producer_events import read as diagnostics
        events = diagnostics(conn,jobs[0]['id']) if jobs else []
        stages = {e['stage'] for e in events}
        uncertain = bool(jobs and jobs[0]['state']=='failed' and
                         (jobs[0]['task_id'] or 'submission_unknown' in stages or
                          ('submitting' in stages and 'submission_rejected' not in stages) or
                          (jobs[0]['backend']=='vlm' and not events)))
        if row['source_status'] != 'active' or row['read_status'] in ('quarantined', 'archived'): reason = 'inactive'
        elif any(j['state'] in ('preparing', 'artifacts_ready') for j in jobs): reason = 'unfinished_job'
        elif uncertain: reason = 'upstream_inspection_required'
        elif not selection.source_file_ids and selection.source_policy == 'single' and row['source_count'] > 1: reason = 'select_exact_source'
        elif successful and not selection.reparse_completed: reason = 'target_backend_exists'
        elif not row['content_sha256']: reason = 'missing_sha'
        item = dict(work_id=wid, source_file_id=sid, sha256=row['content_sha256'],
                    bytes=row['file_size'], baseline_job=jobs[0]['id'] if jobs else None,
                    baseline_state=jobs[0]['state'] if jobs else None,
                    matched_request_ids=sorted({n['request_id'] for n in matches}))
        if reason: excluded.append({**item, 'reason': reason})
        else:
            checked_sha(item['sha256']); items.append(item)
    payload = dict(format='litlib-parse-plan-v1', selection=selection.model_dump(), items=items)
    return {**payload, 'sha256': digest(payload), 'created_at': now(), 'excluded': excluded,
            'counts': {'eligible_sources': len(items), 'eligible_works': len({i['work_id'] for i in items}),
                       'excluded_sources': len(excluded)}, 'page_estimate': None,
            'budget_note': 'pages counted from pinned PDF before execution; local caps are not provider balance'}


SCHEMA = '''CREATE TABLE IF NOT EXISTS parse_plans(
 id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, request_sha256 TEXT NOT NULL,
 payload TEXT NOT NULL, max_items INTEGER NOT NULL, max_submissions INTEGER NOT NULL,
 max_pages INTEGER, created_at TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS parse_plan_items(
 plan_id TEXT NOT NULL, position INTEGER NOT NULL, source_file_id TEXT NOT NULL,
 state TEXT NOT NULL, job_id TEXT, pages INTEGER NOT NULL DEFAULT 0,
 reserved INTEGER NOT NULL DEFAULT 0, error_code TEXT,
 PRIMARY KEY(plan_id,position), UNIQUE(plan_id,source_file_id));'''


def initialize(conn):
    # Single authorized transaction; executescript would implicitly commit.
    for statement in SCHEMA.split(';'):
        if statement.strip(): conn.execute(statement)


def accept(registry, plan, request_id, max_items, max_submissions, max_pages=None):
    if not request_id or len(request_id) > 200: raise StorageError('invalid_request', 'request_id required, at most 200 characters')
    if not 1 <= max_items <= 1000 or not 0 <= max_submissions <= 1000 or (max_pages is not None and max_pages < 1):
        raise StorageError('invalid_request', 'explicit valid budget required')
    try:
        selection = Selection.model_validate(plan.get('selection'))
        payload = {k: plan[k] for k in ('format', 'selection', 'items')}
        if not isinstance(payload['items'], list) or not all(isinstance(i,dict) and isinstance(i.get('source_file_id'),str) for i in payload['items']):
            raise ValueError('invalid items')
    except (ValueError, KeyError, TypeError):
        raise StorageError('invalid_request','invalid frozen plan') from None
    if payload['format'] != 'litlib-parse-plan-v1' or digest(payload) != plan.get('sha256'):
        raise StorageError('checksum_mismatch', 'plan digest differs')
    if not 1 <= len(payload['items']) <= 1000: raise StorageError('invalid_request', 'plan must contain 1..1000 eligible sources')
    if selection.backend == 'vlm' and max_submissions < 1: raise StorageError('invalid_request', 'VLM submission budget required')
    # Replaying an accepted plan is allowed after its own baseline has changed.
    request = dict(plan=payload, max_items=max_items, max_submissions=max_submissions, max_pages=max_pages)
    request_sha = digest(request); pid = 'PP-' + digest(request_id)[:32]
    with registry.conn(write=True) as conn:
        initialize(conn)
        prior = conn.execute('SELECT request_sha256 FROM parse_plans WHERE request_id=?', (request_id,)).fetchone()
        if prior:
            if prior[0] != request_sha: raise StorageError('revision_conflict', 'request_id already binds different plan/budget')
        else:
            # A digest is integrity, not authorization. Recompute the preview and
            # compare selected entries so a caller cannot inject unsafe sources.
            with registry.conn(read_only=True) as read:
                current = preview(read, selection)
            available = {i['source_file_id']: i for i in current['items']}
            seen = set()
            for item in payload['items']:
                sid = item['source_file_id']
                if sid in seen or available.get(sid) != item: raise StorageError('revision_conflict', 'selection changed; preview again')
                seen.add(sid)
            conn.execute('INSERT INTO parse_plans VALUES(?,?,?,?,?,?,?,?)',
                         (pid, request_id, request_sha, canonical(payload), max_items, max_submissions, max_pages, now()))
            conn.executemany("INSERT INTO parse_plan_items(plan_id,position,source_file_id,state) VALUES(?,?,?,'queued')",
                             [(pid, n, i['source_file_id']) for n, i in enumerate(payload['items'])])
    return status(registry, pid)


def status(registry, pid):
    with registry.conn(read_only=True) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='parse_plans'").fetchone():
            raise StorageError('not_found', 'plan not found')
        plan = conn.execute('SELECT * FROM parse_plans WHERE id=?', (pid,)).fetchone()
        if not plan: raise StorageError('not_found', 'plan not found')
        items = [dict(r) for r in conn.execute('SELECT * FROM parse_plan_items WHERE plan_id=? ORDER BY position', (pid,))]
        payload = json.loads(plan['payload'])
        for item in items:
            item['source'] = payload['items'][item['position']]
            if item['job_id']:
                job = conn.execute('SELECT state,parse_run_id,version,backend,task_id,error_code FROM storage_producer_jobs WHERE id=?', (item['job_id'],)).fetchone()
                item['producer'] = dict(job) if job else None
        used = sum(i['reserved'] for i in items)
        return dict(plan_id=pid, request_id=plan['request_id'], selection=payload['selection'],
                    budget=dict(max_items=plan['max_items'], max_submissions=plan['max_submissions'], max_pages=plan['max_pages'],
                                reserved_items=used, reserved_submissions=used if payload['selection']['backend']=='vlm' else 0,
                                reserved_pages=sum(i['pages'] for i in items if i['reserved'])), items=items,
                    remaining=[i['source_file_id'] for i in items if i['state']=='queued'])


def step(service, pid, runner, *, count_pages=None):
    """At most one new parse per call. Caller holds authority guard throughout.

    A per-catalog plan lock also prevents two direct callers reserving together.
    Interrupted items require inspection/resume; never automatically re-run.
    """
    from .storage import producers
    if count_pages is None:
        def count_pages(path):
            import fitz
            with fitz.open(str(path)) as pdf: return pdf.page_count
    registry = service.registry
    with file_lock(registry.catalog.with_suffix('.parse-plans.lock'), timeout=0):
        current = status(registry, pid)
        # Reconcile producer completion after loss of an HTTP response/process.
        for item in current['items']:
            if item['state'] not in ('running','failed'): continue
            producer = item.get('producer') or {}
            if producer.get('state') == 'registered':
                with registry.conn(write=True) as conn:
                    conn.execute("UPDATE parse_plan_items SET state='succeeded' WHERE plan_id=? AND position=?", (pid,item['position']))
            else:
                return {**current, 'action': 'inspect_or_resume', 'blocked_item': item['position']}
        current = status(registry, pid)
        item = next((i for i in current['items'] if i['state']=='queued'), None)
        if not item: return {**current, 'action': 'complete'}
        budget = current['budget']; backend = current['selection']['backend']
        if budget['reserved_items'] >= budget['max_items'] or (backend=='vlm' and budget['reserved_submissions'] >= budget['max_submissions']):
            return {**current, 'action': 'budget_exhausted'}
        sid = item['source_file_id']; expected = item['source']
        with registry.conn(read_only=True) as conn:
            row = conn.execute('SELECT sf.content_sha256,sf.status,w.read_status FROM source_files sf JOIN works w ON w.id=sf.work_id WHERE sf.id=?', (sid,)).fetchone()
            previous = conn.execute("SELECT id,state FROM storage_producer_jobs WHERE kind='parse' AND source_file_id=? ORDER BY version DESC LIMIT 1", (sid,)).fetchone()
        if not row or row[0] != expected['sha256'] or row[1] != 'active' or row[2] in ('quarantined','archived') or (previous[0] if previous else None) != expected['baseline_job'] or (previous[1] if previous else None) != expected['baseline_state']:
            raise StorageError('revision_conflict', 'source/baseline changed; do not expand frozen plan')
        binding = registry.binding(sid, 'pdf', 1)
        if binding['sha256'] != expected['sha256'] or binding['bytes'] != expected['bytes']:
            raise StorageError('checksum_mismatch', 'PDF binding differs from planned source')
        with service.read(sid, 'pdf', 1) as pdf:
            pages = count_pages(pdf)
        if not isinstance(pages,int) or pages < 1: raise StorageError('invalid_request', 'PDF page count unavailable; no submission made')
        if budget['max_pages'] is not None and budget['reserved_pages'] + pages > budget['max_pages']:
            return {**current, 'action': 'budget_exhausted', 'next_pages': pages}
        with registry.conn(write=True) as conn:
            conn.execute("UPDATE parse_plan_items SET state='running',reserved=1,pages=? WHERE plan_id=? AND position=?", (pages,pid,item['position']))
        def registered(jid):
            with registry.conn(write=True) as conn:
                conn.execute('UPDATE parse_plan_items SET job_id=? WHERE plan_id=? AND position=?', (jid,pid,item['position']))
        try:
            job = producers.parse_source(sid, runner, force=True, backend=backend, service=service, on_registered=registered)
            with registry.conn(write=True) as conn:
                conn.execute("UPDATE parse_plan_items SET state='succeeded',job_id=? WHERE plan_id=? AND position=?", (job['id'],pid,item['position']))
        except Exception as error:
            with registry.conn(write=True) as conn:
                # Conservative reservation remains even if the provider outcome is unknown.
                conn.execute("UPDATE parse_plan_items SET state='failed',error_code=? WHERE plan_id=? AND position=?", (getattr(error,'code','producer_failed'),pid,item['position']))
            return {**status(registry,pid), 'action': 'inspect_failure'}
        return {**status(registry,pid), 'action': 'progress'}
