"""Host-owned backup queue, separate from the API process and release slots."""
import hashlib
import hmac
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from .storage.core import StorageError, file_lock
from .storage.release_control import write
from .storage.backup_catalog import read_catalog


def now(): return datetime.now(timezone.utc).isoformat()


def root():
    value = os.environ.get('LITLIB_BACKUP_CONTROL')
    if not value or not Path(value).is_absolute():
        raise StorageError('configuration_error', 'backup controller not configured')
    return Path(value).resolve()


def authorize(token):
    expected = os.environ.get('LITLIB_BACKUP_ADMIN_TOKEN', '')
    if len(expected) < 32 or not token or not hmac.compare_digest(expected, token):
        raise StorageError('permission_denied', 'dedicated backup permission required')


def job_path(job_id):
    if not re.fullmatch(r'BK-[a-f0-9]{32}', job_id): raise StorageError('invalid_request', 'invalid backup job ID')
    return root() / 'jobs' / (job_id + '.json')


def get_job(job_id):
    path = job_path(job_id)
    if not path.is_file(): raise StorageError('not_found', 'backup job not found')
    return json.loads(path.read_text('utf-8'))


def enqueue(request_id):
    if not request_id or len(request_id) > 200: raise StorageError('invalid_request', 'request_id required')
    directory = root(); directory.mkdir(parents=True, exist_ok=True)
    jid = 'BK-' + hashlib.sha256(request_id.encode()).hexdigest()[:32]
    path = job_path(jid)
    with file_lock(directory/'queue.lock', timeout=0):
        if path.exists(): return get_job(jid)
        path.parent.mkdir(parents=True, exist_ok=True)
        job = dict(job_id=jid, request_id=request_id, state='queued', requested_at=now(),
                   message='host worker must be configured and running; no backup exists yet')
        write(path, job)
    return job


def describe():
    if not os.environ.get('LITLIB_BACKUP_CONTROL'):
        return {'configured':False, 'scheduler_state':'unknown', 'worker_last_seen':None}
    directory = root()
    catalog = read_catalog(directory/'backup-catalog.json')
    verified = sorted((v for v in catalog['versions'] if v['state']=='verified'), key=lambda v:v['verified_at'])
    heartbeat = directory/'worker.json'
    worker = json.loads(heartbeat.read_text('utf-8')) if heartbeat.is_file() else {}
    attempts=list(catalog['attempts'])
    if verified: attempts.append({'at':verified[-1]['verified_at'],'state':'verified','version_id':verified[-1]['id']})
    return {'configured':True, 'scheduler_state':'not_managed',
            'worker_last_seen':worker.get('at'), 'worker_state':worker.get('state','unknown'),
            'latest_verified':{k:verified[-1].get(k) for k in ('id','verified_at','code_commit','manifest_sha256')} if verified else None,
            'last_attempt':max(attempts,key=lambda a:a['at']) if attempts else None,
            'restore_test':'not_inferred_from_publish',
            'guide':'docs/foundation-client.md'}


def run_one(execute):
    """Run outside uvicorn. Never automatically replay an interrupted backup."""
    directory = root(); directory.mkdir(parents=True, exist_ok=True)
    with file_lock(directory/'worker.lock', timeout=0):
        write(directory/'worker.json', {'at':now(),'state':'checking'})
        jobs = [json.loads(p.read_text('utf-8')) for p in (directory/'jobs').glob('BK-*.json')]
        interrupted = [j for j in jobs if j['state'] in ('running','needs_attention')]
        if interrupted:
            for job in interrupted:
                job.update(state='needs_attention', message='inspect maintenance and receipt; automatic replay refused')
                write(job_path(job['job_id']), job)
            write(directory/'worker.json', {'at':now(),'state':'needs_attention'})
            return {'state':'needs_attention','job_ids':[j['job_id'] for j in interrupted]}
        pending = sorted((j for j in jobs if j['state']=='queued'),key=lambda j:(j['requested_at'],j['job_id']))
        if not pending:
            write(directory/'worker.json', {'at':now(),'state':'idle'})
            return {'state':'idle'}
        job = pending[0]; job.update(state='running',started_at=now())
        write(job_path(job['job_id']),job)
        try:
            version = execute(job['job_id'])
            catalog = read_catalog(directory/'backup-catalog.json')
            stored = next((v for v in catalog['versions'] if v['id']==version.get('id') and v['state']=='verified'),None)
            if stored != version or version['verified_at'] < job['started_at']:
                raise StorageError('checksum_mismatch','executor did not register a fresh verified backup')
            job.update(state='succeeded',finished_at=now(),message='verified snapshot published; restore testing is separate',
                       version={k:version[k] for k in ('id','verified_at','code_commit','manifest_sha256')})
        except Exception as error:
            # The executor may have entered maintenance: stop subsequent jobs
            # until its recovery receipt has been inspected by the host operator.
            job.update(state='needs_attention',finished_at=now(),error_code=getattr(error,'code','backup_failed'),
                       message='inspect host maintenance and receipt before resolving this job')
        write(job_path(job['job_id']),job)
        write(directory/'worker.json',{'at':now(),'state':job['state']})
        return job


def resolve(job_id, *, verified_service):
    """Host-only acknowledgment, never a retry or assertion of backup success."""
    if not verified_service: raise StorageError('permission_denied','verify maintenance closed and service restored first')
    with file_lock(root()/'worker.lock', timeout=0):
        job=get_job(job_id)
        if job['state']!='needs_attention': raise StorageError('revision_conflict','job does not need resolution')
        job.update(state='failed',resolved_at=now(),message='host acknowledged recovery; use a new request for another backup')
        write(job_path(job_id),job)
        return job
