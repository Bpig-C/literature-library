"""Durable, single-authority-host parse scheduler (#7/#14).

An independent worker advances ONE phase per lease. API requests never wait
for cloud work. All writes, including producer/storage bookkeeping, are fenced
by both authority epoch and a transactionally checked lease generation.
"""
from contextlib import contextmanager,ExitStack
from dataclasses import asdict, dataclass
import copy
import hashlib
import json
import os
import shutil
from pathlib import Path
import threading
import time
import uuid

from . import parse_plans
from .storage.core import StorageError, file_lock
from .storage.fenced import FencedRegistry,short_guard


def enabled():return os.environ.get('LITLIB_ASYNC_PARSE_ENABLED')=='1'


@dataclass(frozen=True)
class Limits:
    prepare: int = 1
    submit: int = 1
    upload: int = 1
    poll: int = 2
    download: int = 1
    publish: int = 1
    local: int = 1
    upstream: int = 10  # in-flight files, not local threads or promised provider concurrency
    submit_per_minute: int = 30
    poll_per_minute: int = 60
    poll_seconds: int = 10
    lease_seconds: int = 120
    max_input_bytes: int = 128*1024*1024
    max_download_bytes: int = 256*1024*1024
    max_attempts: int = 3
    min_free_bytes: int = 64*1024*1024
    batch_size: int = 10
    batch_input_bytes: int = 256*1024*1024
    max_pages_per_file: int = 200

    def __post_init__(self):
        if any(type(v) is not int or v<1 for v in asdict(self).values()):raise ValueError('positive integer limits required')
        if self.lease_seconds<15:raise ValueError('lease must allow heartbeat')
        if any(getattr(self,k)>32 for k in ('prepare','submit','upload','poll','download','publish','local')):
            raise ValueError('at most 32 phase slots')
        if self.batch_size>50 or self.upstream>1000:raise ValueError('batch_size at most 50; bounded upstream files required')


SCHEMA='''CREATE TABLE IF NOT EXISTS parse_queue_control(
 id INTEGER PRIMARY KEY CHECK(id=1), limits_json TEXT NOT NULL,
 maintenance TEXT NOT NULL DEFAULT '', maintenance_owner TEXT,
 submit_after REAL NOT NULL DEFAULT 0, poll_after REAL NOT NULL DEFAULT 0,
 submit_paused INTEGER NOT NULL DEFAULT 0);
 CREATE TABLE IF NOT EXISTS parse_queue_jobs(
 id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, position INTEGER NOT NULL,
 source_file_id TEXT NOT NULL, backend TEXT NOT NULL, language TEXT NOT NULL DEFAULT '',
 phase TEXT NOT NULL, state TEXT NOT NULL, producer_id TEXT, current_batch TEXT,
 epoch INTEGER, worker TEXT, lease_token TEXT, lease_until REAL NOT NULL DEFAULT 0,
 generation INTEGER NOT NULL DEFAULT 0, next_at REAL NOT NULL DEFAULT 0,
 created_at REAL NOT NULL, updated_at REAL NOT NULL,
 submissions INTEGER NOT NULL DEFAULT 0, upstream_state TEXT,
 error_code TEXT, attempts INTEGER NOT NULL DEFAULT 0,
 cancel_requested INTEGER NOT NULL DEFAULT 0, UNIQUE(plan_id,position));
 CREATE TABLE IF NOT EXISTS parse_queue_events(
 id INTEGER PRIMARY KEY, task_id TEXT NOT NULL, event TEXT NOT NULL,
 at REAL NOT NULL, detail TEXT NOT NULL);
 CREATE INDEX IF NOT EXISTS idx_parse_queue_due ON parse_queue_jobs(state,next_at,created_at);'''


def exists(conn):return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name='parse_queue_jobs'").fetchone())


def initialize(conn,limits=Limits()):
    for statement in SCHEMA.split(';'):
        if statement.strip():conn.execute(statement)
    conn.execute('INSERT OR IGNORE INTO parse_queue_control(id,limits_json) VALUES(1,?)',(parse_plans.canonical(asdict(limits)),))
    from .parse_batches import initialize as batches
    batches(conn)


def submission_usage(conn,pid):
    if not exists(conn):return conn.execute('SELECT COALESCE(sum(reserved),0) FROM parse_plan_items WHERE plan_id=?',(pid,)).fetchone()[0]
    return conn.execute('''SELECT COALESCE(sum(CASE WHEN q.id IS NULL THEN i.reserved ELSE q.submissions END),0)
        FROM parse_plan_items i LEFT JOIN parse_queue_jobs q ON q.plan_id=i.plan_id AND q.position=i.position WHERE i.plan_id=?''',(pid,)).fetchone()[0]


def snapshot_barrier(conn,owner):
    control=conn.execute('SELECT maintenance,maintenance_owner FROM parse_queue_control').fetchone()
    if control[0]!='drain' or control[1]!=owner:raise StorageError('busy','drain must be owned before snapshot')
    if conn.execute("SELECT 1 FROM parse_queue_jobs WHERE lease_token IS NOT NULL OR (producer_id IS NOT NULL AND state NOT IN ('succeeded','failed','cancelled','paused','tracking','inspection_required','blocked_budget')) LIMIT 1").fetchone():
        raise StorageError('busy','parse tasks have not drained')
    conn.execute("UPDATE parse_queue_control SET maintenance='snapshot'")


class Queue:
    def __init__(self,service,authority,*,clock=time.time,limits=None):
        self.service=service;self.registry=service.registry;self.authority=authority
        self.clock=clock;self.initial_limits=limits or Limits();self.worker=uuid.uuid4().hex

    @contextmanager
    def tx(self):
        with short_guard(self.authority),self.registry.conn(write=True) as conn:yield conn

    def event(self,conn,qid,event,**detail):
        conn.execute('INSERT INTO parse_queue_events(task_id,event,at,detail) VALUES(?,?,?,?)',
                     (qid,event,self.clock(),parse_plans.canonical(detail)))

    def enqueue(self,pid,max_tasks=None):
        with self.tx() as conn:
            parse_plans.require_open(conn,pid)
            initialize(conn,self.initial_limits)
            if conn.execute('SELECT maintenance FROM parse_queue_control').fetchone()[0]:
                raise StorageError('busy','parse maintenance is draining; retry after maintenance')
            plan=conn.execute('SELECT * FROM parse_plans WHERE id=?',(pid,)).fetchone()
            if not plan:raise StorageError('not_found','plan not found')
            payload=json.loads(plan['payload']);stamp=self.clock();admitted=0
            maximum=max_tasks if max_tasks is not None else plan['max_items']
            if type(maximum) is not int or not 1<=maximum<=1000:raise StorageError('invalid_request','max_tasks must be 1..1000')
            for item in conn.execute('SELECT * FROM parse_plan_items WHERE plan_id=? ORDER BY position',(pid,)).fetchall():
                if admitted>=maximum:break
                qid='PQ-'+hashlib.sha256(f'{pid}:{item["position"]}'.encode()).hexdigest()[:32]
                existing=conn.execute('SELECT state FROM parse_queue_jobs WHERE id=?',(qid,)).fetchone()
                if existing:
                    if existing[0]!='succeeded':admitted+=1
                    continue
                if item['state']!='queued':continue
                active=conn.execute("SELECT id FROM parse_queue_jobs WHERE source_file_id=? AND state NOT IN ('succeeded','failed','cancelled','blocked_budget')",(item['source_file_id'],)).fetchone()
                if active:raise StorageError('revision_conflict','source already queued: '+active[0])
                language=conn.execute('SELECT w.language FROM works w JOIN source_files sf ON sf.work_id=w.id WHERE sf.id=?',(item['source_file_id'],)).fetchone()
                conn.execute('''INSERT INTO parse_queue_jobs(id,plan_id,position,source_file_id,backend,language,phase,state,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,'prepare','queued',?,?)''',(qid,pid,item['position'],item['source_file_id'],payload['selection']['backend'],language[0] or '',stamp,stamp))
                self.event(conn,qid,'enqueued')
                admitted+=1
        return self.plan_status(pid)

    def plan_status(self,pid):
        result=parse_plans.status(self.registry,pid)
        with self.registry.conn(read_only=True) as conn:
            result['tasks']=[self.public(dict(r)) for r in conn.execute('SELECT * FROM parse_queue_jobs WHERE plan_id=? ORDER BY position',(pid,))] if exists(conn) else []
            if exists(conn):
                result['native_batch_intents']=conn.execute('SELECT count(DISTINCT m.batch_id) FROM parse_cloud_members m JOIN parse_queue_jobs q ON q.id=m.task_id WHERE q.plan_id=?',(pid,)).fetchone()[0]
                result['accepted_native_batches']=conn.execute('SELECT count(DISTINCT m.batch_id) FROM parse_cloud_members m JOIN parse_queue_jobs q ON q.id=m.task_id JOIN parse_cloud_batches b ON b.id=m.batch_id WHERE q.plan_id=? AND b.provider_id IS NOT NULL',(pid,)).fetchone()[0]
                result['submission_accounting']='file-attempt reservations; native batch POST intents are counted separately; not provider balance'
        states={t['state'] for t in result['tasks']}
        action=('queued' if states & {'queued','runnable','active','waiting'} else
                'inspect_or_resume' if states & {'paused','failed','inspection_required'} else
                'budget_exhausted' if 'blocked_budget' in states else
                'complete_with_abandoned' if 'cancelled' in states else
                'complete' if result['tasks'] and not result['remaining'] else 'no_queued_items')
        result.update(execution='background',action=action)
        return result

    def public(self,row):
        row={k:v for k,v in row.items() if k not in ('lease_token','worker')}
        row['tracking_upstream']=row['state']=='tracking'
        if row['state']=='tracking':row['state']='cancelled' if row['cancel_requested']==2 else 'paused'
        row['recovery_action']=('inspect_provider' if row['state']=='inspection_required' else
            'resume_existing' if row['state'] in ('paused','failed','cancelled') else
            'new_budget_plan' if row['state']=='blocked_budget' else 'query_status')
        return row

    def status(self,qid):
        with self.registry.conn(read_only=True) as conn:
            row=conn.execute('SELECT * FROM parse_queue_jobs WHERE id=?',(qid,)).fetchone() if exists(conn) else None
            if not row:raise StorageError('not_found','async task not found')
            result=self.public(dict(row))
            result['events']=[dict(r) for r in conn.execute('SELECT event,at,detail FROM parse_queue_events WHERE task_id=? ORDER BY id DESC LIMIT 30',(qid,))]
            for event in result['events']:event['detail']=json.loads(event['detail'])
            if row['producer_id']:
                producer=conn.execute('SELECT id,state,backend,task_id,version,error_code FROM storage_producer_jobs WHERE id=?',(row['producer_id'],)).fetchone()
                result['producer']=dict(producer) if producer else None
            result['cloud_history']=[dict(r) for r in conn.execute('''SELECT b.provider_id batch_id,m.data_id,m.file_name,m.source_file_id,m.sha256,m.version,m.upload_state,m.upstream_state
                FROM parse_cloud_members m JOIN parse_cloud_batches b ON b.id=m.batch_id WHERE m.task_id=? ORDER BY b.created_at''',(qid,))]
            return result

    def configure(self,limits):
        with self.tx() as conn:
            initialize(conn,limits)
            self.control_mutable(conn)
            if conn.execute('SELECT 1 FROM parse_queue_jobs WHERE lease_token IS NOT NULL LIMIT 1').fetchone():
                raise StorageError('busy','drain active leases before changing limits')
            conn.execute('UPDATE parse_queue_control SET limits_json=?',(parse_plans.canonical(asdict(limits)),))

    def batch_status(self,batch_id):
        with self.registry.conn(read_only=True) as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='parse_cloud_batches'").fetchone():raise StorageError('not_found','native batch not found')
            batch=conn.execute('SELECT id,provider_id,state,language,created_at FROM parse_cloud_batches WHERE id=?',(batch_id,)).fetchone()
            if not batch:raise StorageError('not_found','native batch not found')
            return {**dict(batch),'files':[dict(r) for r in conn.execute('''SELECT task_id,data_id,file_name,source_file_id,producer_id,sha256,bytes,version,upload_state,upstream_state
                FROM parse_cloud_members WHERE batch_id=? ORDER BY data_id''',(batch_id,))]}

    def control_mutable(self,conn):
        if conn.execute('SELECT maintenance FROM parse_queue_control').fetchone()[0]=='snapshot':
            raise StorageError('busy','snapshot barrier blocks task/configuration changes; restore maintenance first')

    def maintenance(self,action,owner):
        with self.tx() as conn:
            initialize(conn,self.initial_limits)
            control=conn.execute('SELECT * FROM parse_queue_control').fetchone()
            if control['maintenance'] and control['maintenance_owner']!=owner:
                raise StorageError('busy','maintenance belongs to another operator')
            if action=='snapshot':
                snapshot_barrier(conn,owner)
            if action not in ('drain','snapshot','resume'):raise StorageError('invalid_request','unknown maintenance action')
            conn.execute('UPDATE parse_queue_control SET maintenance=?,maintenance_owner=?',('' if action=='resume' else action,None if action=='resume' else owner))
        return self.overview()

    def overview(self):
        with self.registry.conn(read_only=True) as conn:
            if not exists(conn):return {'configured':False,'states':{},'maintenance':''}
            c=dict(conn.execute('SELECT * FROM parse_queue_control').fetchone())
            return {'configured':True,'limits':json.loads(c['limits_json']),'maintenance':c['maintenance'],'maintenance_owner':c['maintenance_owner'],
                'submission_paused':bool(c['submit_paused']),
                'states':{r[0]:r[1] for r in conn.execute('SELECT state,count(*) FROM parse_queue_jobs GROUP BY state')},
                'phases':{r[0]:r[1] for r in conn.execute('SELECT phase,count(*) FROM parse_queue_jobs GROUP BY phase')},
                'active_leases':conn.execute('SELECT count(*) FROM parse_queue_jobs WHERE lease_token IS NOT NULL AND lease_until>?',(self.clock(),)).fetchone()[0]}

    def _assert_current(self,conn,row):
        parse_plans.require_open(conn,row['plan_id'])
        other=conn.execute("SELECT id FROM parse_queue_jobs WHERE source_file_id=? AND id!=? AND state NOT IN ('succeeded','failed','cancelled','blocked_budget') LIMIT 1",(row['source_file_id'],row['id'])).fetchone()
        if other:raise StorageError('revision_conflict','source belongs to another active task '+other[0])
        if row['producer_id']:
            latest=conn.execute("SELECT id FROM storage_producer_jobs WHERE kind='parse' AND source_file_id=? ORDER BY version DESC LIMIT 1",(row['source_file_id'],)).fetchone()
            if not latest or latest[0]!=row['producer_id']:raise StorageError('revision_conflict','later parse exists; historical task cannot resume')
        source=conn.execute('SELECT sf.status,w.read_status FROM source_files sf JOIN works w ON w.id=sf.work_id WHERE sf.id=?',(row['source_file_id'],)).fetchone()
        if (not source or source[0]!='active' or source[1] in ('quarantined','archived')) and not (row['phase']=='poll' and row['cancel_requested']):raise StorageError('revision_conflict','source no longer active')
        if row['producer_id']:
            identity=conn.execute('''SELECT sf.content_sha256,sf.work_id,r.sha256,pr.work_id FROM source_files sf
                JOIN producer_recovery r ON r.source_file_id=sf.id JOIN literature_parse_runs pr ON pr.id=r.parse_run_id
                WHERE r.job_id=?''',(row['producer_id'],)).fetchone()
            if not identity or identity[0]!=identity[2] or identity[1]!=identity[3]:raise StorageError('revision_conflict','source identity changed since producer preparation')

    def validate(self,conn,row,*,source=True):
        actual=conn.execute('SELECT * FROM parse_queue_jobs WHERE id=?',(row['id'],)).fetchone()
        if not actual or actual['lease_token']!=row['lease_token'] or actual['generation']!=row['generation'] or actual['epoch']!=self.authority.epoch or actual['lease_until']<=self.clock():
            raise StorageError('revision_conflict','parse lease expired or superseded; stale worker fenced')
        if source:self._assert_current(conn,dict(actual))

    def renew(self,row):
        with self.tx() as conn:
            self.validate(conn,row,source=False)  # finish recording an in-flight upstream response even if source was archived
            seconds=Limits(**json.loads(conn.execute('SELECT limits_json FROM parse_queue_control').fetchone()[0])).lease_seconds
            conn.execute('UPDATE parse_queue_jobs SET lease_until=? WHERE id=?',(self.clock()+seconds,row['id']))

    def _recover_expired(self,conn,row):
        from .producer_recovery import read
        job=conn.execute('SELECT * FROM storage_producer_jobs WHERE id=?',(row['producer_id'],)).fetchone() if row['producer_id'] else None
        receipt=read(conn,row['producer_id']) if job else None
        phase=row['phase'];state='runnable';upstream=row['upstream_state']
        if job and job['state']=='registered':phase='publish'
        elif job and job['state']=='artifacts_ready':phase='publish'
        elif job and job['task_id']:phase='poll'
        elif receipt and receipt['submission'] in ('unknown','known'):state='inspection_required'
        elif job and receipt and receipt['submission'] in ('not_started','rejected','verified_not_submitted'):
            phase='submit' if row['backend']=='vlm' else 'local';upstream='not_started'
            if row['current_batch'] and not conn.execute('SELECT provider_id FROM parse_cloud_batches WHERE id=?',(row['current_batch'],)).fetchone()[0]:
                conn.execute('UPDATE parse_queue_jobs SET current_batch=NULL WHERE id=?',(row['id'],))
        elif phase not in ('prepare','submit'):state='inspection_required'
        conn.execute('UPDATE parse_queue_jobs SET phase=?,state=?,upstream_state=?,lease_token=NULL,lease_until=0,updated_at=? WHERE id=?',(phase,state,upstream,self.clock(),row['id']))
        self.event(conn,row['id'],'interrupted',outcome=state,phase=phase)

    def claim(self,*,native=False):
        stamp=self.clock()
        with self.registry.conn(read_only=True) as peek:
            if exists(peek) and peek.execute('SELECT maintenance FROM parse_queue_control').fetchone()[0]=='snapshot':return None
        with self.tx() as conn:
            initialize(conn,self.initial_limits)
            control=conn.execute('SELECT * FROM parse_queue_control').fetchone();limits=Limits(**json.loads(control['limits_json']))
            if control['maintenance']=='snapshot':return None
            for r in conn.execute('SELECT * FROM parse_queue_jobs WHERE lease_token IS NOT NULL AND lease_until<=?',(stamp,)).fetchall():self._recover_expired(conn,dict(r))
            candidates=conn.execute("SELECT * FROM parse_queue_jobs WHERE state IN ('queued','runnable','waiting','tracking') AND lease_token IS NULL AND next_at<=? ORDER BY next_at,updated_at,created_at,id",(stamp,)).fetchall()
            for candidate in candidates:
                row=dict(candidate);phase=row['phase']
                if control['maintenance'] and phase=='prepare':continue
                try:self._assert_current(conn,row)
                except StorageError as error:
                    self._park(conn,row,'inspection_required',error.code)
                    self.event(conn,row['id'],'ownership_conflict',error_code=error.code);continue
                slots=conn.execute('SELECT count(DISTINCT COALESCE(current_batch,id)) FROM parse_queue_jobs WHERE phase=? AND lease_token IS NOT NULL AND lease_until>?',(phase,stamp)).fetchone()[0] if phase in ('submit','poll') else conn.execute('SELECT count(*) FROM parse_queue_jobs WHERE phase=? AND lease_token IS NOT NULL AND lease_until>?',(phase,stamp)).fetchone()[0]
                if slots>=getattr(limits,phase):continue
                if native and (phase=='submit' or (phase=='poll' and row['current_batch'])):
                    from .parse_batches import claim as claim_batch
                    group=claim_batch(self,conn,row,candidates,control,limits,stamp)
                    if group:return group
                    continue
                if phase=='submit':
                    if control['submit_paused'] or control['submit_after']>stamp:continue
                    active=conn.execute('''SELECT count(*) FROM parse_queue_jobs q
                        LEFT JOIN producer_recovery r ON r.job_id=q.producer_id
                        LEFT JOIN storage_producer_jobs p ON p.id=q.producer_id
                        WHERE q.backend='vlm' AND (
                        (q.phase='submit' AND q.lease_token IS NOT NULL AND q.lease_until>?) OR
                        ((r.submission IN ('unknown','known') OR COALESCE(p.task_id,'')!='')
                         AND COALESCE(q.upstream_state,'unknown') NOT IN ('done','failed','rejected')))''',(stamp,)).fetchone()[0]
                    if active>=limits.upstream:continue
                    budget=conn.execute('SELECT max_submissions FROM parse_plans WHERE id=?',(row['plan_id'],)).fetchone()[0]
                    if submission_usage(conn,row['plan_id'])>=budget:
                        self._park(conn,row,'blocked_budget','budget_exhausted');continue
                    conn.execute("UPDATE parse_queue_jobs SET submissions=submissions+1,upstream_state='unknown' WHERE id=?",(row['id'],))
                    conn.execute('UPDATE parse_queue_control SET submit_after=?',(stamp+60/limits.submit_per_minute,))
                if phase in ('poll','download','upload'):
                    if control['poll_after']>stamp:continue
                    conn.execute('UPDATE parse_queue_control SET poll_after=?',(stamp+60/limits.poll_per_minute,))
                token=uuid.uuid4().hex
                conn.execute('''UPDATE parse_queue_jobs SET state='active',epoch=?,worker=?,lease_token=?,lease_until=?,generation=generation+1,updated_at=? WHERE id=?''',
                    (self.authority.epoch,self.worker,token,stamp+limits.lease_seconds,stamp,row['id']))
                self.event(conn,row['id'],'claimed',phase=phase,epoch=self.authority.epoch)
                return dict(conn.execute('SELECT * FROM parse_queue_jobs WHERE id=?',(row['id'],)).fetchone())
        return None

    def finish(self,row,*,phase=None,state='runnable',delay=0,error=None,upstream=None):
        with self.tx() as conn:
            self.validate(conn,row,source=state not in ('failed','inspection_required','blocked_budget','paused','cancelled'))
            if state in ('failed','inspection_required','blocked_budget','paused'):self._park(conn,row,state,error)
            conn.execute('''UPDATE parse_queue_jobs SET phase=?,state=?,next_at=?,error_code=?,upstream_state=COALESCE(?,upstream_state),
                lease_token=NULL,lease_until=0,updated_at=? WHERE id=?''',
                (phase or row['phase'],state,self.clock()+delay,error,upstream,self.clock(),row['id']))
            if error is None:conn.execute('UPDATE parse_queue_jobs SET attempts=0 WHERE id=?',(row['id'],))
            self.event(conn,row['id'],'phase_finished',phase=phase or row['phase'],state=state,error_code=error)

    def _park(self,conn,row,state,error):
        actual=conn.execute('SELECT producer_id FROM parse_queue_jobs WHERE id=?',(row['id'],)).fetchone()
        conn.execute('UPDATE parse_queue_jobs SET state=?,error_code=? WHERE id=?',(state,error,row['id']))
        if actual and actual[0]:
            conn.execute("UPDATE storage_producer_jobs SET state='failed',error_code=? WHERE id=? AND state='preparing'",(error,actual[0]))
            conn.execute("UPDATE literature_parse_runs SET status='failed',error=? WHERE id=(SELECT parse_run_id FROM storage_producer_jobs WHERE id=?) AND status='running'",(error,actual[0]))
            conn.execute("UPDATE parse_plan_items SET state='failed',error_code=? WHERE plan_id=? AND position=?",(error,row['plan_id'],row['position']))

    def action(self,qid,action,reason):
        if not reason.strip() or len(reason)>500:raise StorageError('invalid_request','inspection reason required')
        with self.tx() as conn:
            initialize(conn,self.initial_limits)
            self.control_mutable(conn)
            row=conn.execute('SELECT * FROM parse_queue_jobs WHERE id=?',(qid,)).fetchone()
            if not row:raise StorageError('not_found','async task not found')
            parse_plans.require_open(conn,row['plan_id'])
            if row['state']=='succeeded':raise StorageError('revision_conflict','completed task cannot be paused, cancelled or restarted')
            if action=='resume':
                if row['lease_token']:raise StorageError('busy','task still has an execution lease')
                self._assert_current(conn,dict(row))
                job=conn.execute('SELECT * FROM storage_producer_jobs WHERE id=?',(row['producer_id'],)).fetchone() if row['producer_id'] else None
                if job and job['state'] in ('registered','artifacts_ready'):phase='publish'
                elif job and row['current_batch'] and row['upstream_state']=='failed':
                    budget=conn.execute('SELECT max_submissions FROM parse_plans WHERE id=?',(row['plan_id'],)).fetchone()[0]
                    if submission_usage(conn,row['plan_id'])>=budget:raise StorageError('budget_exhausted','new file attempt requires remaining submission budget or a new plan')
                    phase='submit'
                    conn.execute('UPDATE storage_producer_jobs SET task_id=NULL WHERE id=?',(job['id'],))
                    conn.execute("UPDATE producer_recovery SET submission='not_started' WHERE job_id=?",(job['id'],))
                    conn.execute('UPDATE parse_queue_jobs SET current_batch=NULL WHERE id=?',(qid,))
                    self.event(conn,qid,'retry_failed_file',previous_batch=row['current_batch'])
                elif job and job['task_id']:phase='poll'
                elif row['producer_id']:
                    from .producer_recovery import read
                    receipt=read(conn,row['producer_id'])
                    if row['backend']=='pymupdf':phase='local'
                    elif receipt and receipt['submission'] in ('not_started','rejected','verified_not_submitted'):phase='submit'
                    else:raise StorageError('producer_incomplete','inspect submitting task; never blindly resubmit')
                else:phase='prepare'
                conn.execute("UPDATE parse_queue_jobs SET state='runnable',phase=?,cancel_requested=0,next_at=0,error_code=NULL,attempts=0 WHERE id=?",(phase,qid))
                if phase=='submit':
                    conn.execute("UPDATE parse_queue_jobs SET upstream_state='not_started' WHERE id=?",(qid,))
                    if row['current_batch'] and not conn.execute('SELECT provider_id FROM parse_cloud_batches WHERE id=?',(row['current_batch'],)).fetchone()[0]:conn.execute('UPDATE parse_queue_jobs SET current_batch=NULL WHERE id=?',(qid,))
                conn.execute("UPDATE parse_plan_items SET state=CASE WHEN reserved=1 THEN 'running' ELSE 'queued' END WHERE plan_id=? AND position=?",(row['plan_id'],row['position']))
            elif action in ('pause','cancel'):
                conn.execute('UPDATE parse_queue_jobs SET cancel_requested=? WHERE id=?',(2 if action=='cancel' else 1,qid))
                if not row['lease_token']:self._stop(conn,dict(row),action)
            else:raise StorageError('invalid_request','unknown task action')
            self.event(conn,qid,action,reason=reason.strip())
        return self.status(qid)

    def resolve(self,qid,outcome,reason,task_id=None):
        import re
        if not reason.strip() or len(reason)>500:raise StorageError('invalid_request','provider verification reason required')
        if outcome not in ('not_submitted','task_found'):raise StorageError('invalid_request','explicit verified outcome required')
        if outcome=='task_found' and not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}',task_id or ''):raise StorageError('invalid_request','exact provider task ID required')
        with self.tx() as conn:
            initialize(conn,self.initial_limits);self.control_mutable(conn)
            row=conn.execute('SELECT * FROM parse_queue_jobs WHERE id=?',(qid,)).fetchone()
            if not row:raise StorageError('not_found','task not found')
            if row['lease_token'] or row['state'] not in ('inspection_required','cancelled','paused'):
                raise StorageError('revision_conflict','stop and inspect task before resolving')
            self._assert_current(conn,dict(row))
            job=conn.execute('SELECT * FROM storage_producer_jobs WHERE id=?',(row['producer_id'],)).fetchone()
            from .producer_recovery import read
            receipt=read(conn,row['producer_id'])
            if not job or job['task_id'] or not receipt or receipt['submission']!='unknown':
                raise StorageError('revision_conflict','only unknown submissions without task IDs may be resolved')
            known=outcome=='task_found'
            conn.execute('UPDATE producer_recovery SET submission=? WHERE job_id=?',('known' if known else 'verified_not_submitted',job['id']))
            conn.execute("UPDATE storage_producer_jobs SET task_id=?,backend='vlm' WHERE id=?",(task_id if known else None,job['id']))
            if row['current_batch']:
                if known:
                    prior=conn.execute('SELECT provider_id FROM parse_cloud_batches WHERE id=?',(row['current_batch'],)).fetchone()[0]
                    if prior and prior!=task_id:raise StorageError('revision_conflict','provider batch differs from persisted mapping')
                    conn.execute('UPDATE parse_cloud_batches SET provider_id=? WHERE id=?',(task_id,row['current_batch']))
                else:conn.execute('UPDATE parse_queue_jobs SET current_batch=NULL WHERE id=?',(qid,))
            conn.execute('UPDATE parse_queue_jobs SET state=?,phase=?,upstream_state=?,next_at=0,cancel_requested=0,error_code=NULL WHERE id=?',
                         ('waiting' if known else 'paused','poll' if known else 'submit','pending' if known else 'rejected',qid))
            if known:conn.execute("UPDATE parse_plan_items SET state='running' WHERE plan_id=? AND position=?",(row['plan_id'],row['position']))
            self.event(conn,qid,'provider_verified',outcome=outcome,reason=reason.strip(),task_id=task_id if known else None)
        return self.status(qid)

    def _stop(self,conn,row,action):
        state='cancelled' if action=='cancel' else 'paused'
        job=conn.execute('SELECT task_id,state FROM storage_producer_jobs WHERE id=?',(row['producer_id'],)).fetchone() if row['producer_id'] else None
        track=bool(job and job['task_id'] and job['state'] not in ('registered','artifacts_ready') and row['upstream_state'] not in ('done','failed'))
        conn.execute('UPDATE parse_queue_jobs SET state=?,phase=?,next_at=?,lease_token=NULL,lease_until=0 WHERE id=?',
                     ('tracking' if track else state,'poll' if track else row['phase'],self.clock(),row['id']))
        self._stop_records(conn,row,action)

    def _stop_records(self,conn,row,action):
        if row['producer_id']:
            conn.execute("UPDATE storage_producer_jobs SET state=CASE WHEN state='preparing' THEN 'failed' ELSE state END,error_code='async_paused' WHERE id=?",(row['producer_id'],))
            conn.execute("UPDATE literature_parse_runs SET status=CASE WHEN status='running' THEN 'failed' ELSE status END,error='async_paused' WHERE id=(SELECT parse_run_id FROM storage_producer_jobs WHERE id=?)",(row['producer_id'],))
        conn.execute('UPDATE parse_plan_items SET state=? WHERE plan_id=? AND position=?',('abandoned' if action=='cancel' else 'failed',row['plan_id'],row['position']))

    def run_one(self,driver):
        row=self.claim(native=hasattr(driver,'create_batch'))
        if not row:return {'state':'idle'}
        rows=row.get('_members',[row])
        from .storage.producers import _source_lock_path
        source_lock=_source_lock_path(self.service,row['source_file_id'])
        stop=threading.Event()
        def heartbeat():
            while not stop.wait(max(1,self._limits().lease_seconds/3)):
                renewed=0
                for current in rows:
                    try:self.renew(current);renewed+=1
                    except StorageError:pass  # next mutation rejects stale lease
                if not renewed:return
        thread=threading.Thread(target=heartbeat,daemon=True)
        try:
            with ExitStack() as locks:
                for current in sorted(rows,key=lambda r:r['source_file_id']):locks.enter_context(file_lock(_source_lock_path(self.service,current['source_file_id']),timeout=0))
                thread.start()
                with self.registry.conn(read_only=True) as conn:cancel=conn.execute('SELECT cancel_requested FROM parse_queue_jobs WHERE id=?',(row['id'],)).fetchone()[0]
                if '_members' in row:
                    from .parse_batches import submit,poll
                    (submit if row['phase']=='submit' else poll)(self,rows,driver)
                elif cancel and row['phase']=='poll':
                    with self.tx() as conn:
                        self.validate(conn,row);self._stop_records(conn,row,'cancel' if cancel==2 else 'pause')
                    self._advance(row,driver,tracking=cancel)
                elif cancel:
                    with self.tx() as conn:self.validate(conn,row);self._stop(conn,row,'cancel' if cancel==2 else 'pause')
                else:self._advance(row,driver)
        except Exception as error:
            first_error=None
            for current in rows:
                with self.registry.conn(read_only=True) as conn:actual=conn.execute('SELECT lease_token FROM parse_queue_jobs WHERE id=?',(current['id'],)).fetchone()
                if actual and actual[0]==current['lease_token']:
                    try:self._failure(current,error)
                    except StorageError as failure:first_error=first_error or failure
            if first_error:raise first_error
        finally:stop.set();thread.join(2) if thread.ident else None
        return self.status(row['id'])

    def _limits(self):
        with self.registry.conn(read_only=True) as conn:return Limits(**json.loads(conn.execute('SELECT limits_json FROM parse_queue_control').fetchone()[0]))

    def _failure(self,row,error):
        code=getattr(error,'code','phase_failed')
        # Record only bounded codes; never provider message/URL/path/credentials.
        import re
        if not re.fullmatch('[A-Za-z0-9_.:-]{1,100}',str(code)):code='phase_failed'
        if code=='busy' and row['phase']!='submit':
            return self.finish(row,state='waiting',delay=1,error='busy')
        detail={'phase':row['phase'],'error_code':code}
        for field in ('http_status','provider_code'):
            value=getattr(error,field,None)
            if value is not None and re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}',str(value)):detail[field]=value
        with self.tx() as conn:self.validate(conn,row,source=False);self.event(conn,row['id'],'phase_error',**detail)
        with self.registry.conn(read_only=True) as conn:
            actual=conn.execute('SELECT producer_id FROM parse_queue_jobs WHERE id=?',(row['id'],)).fetchone()
            job=conn.execute('SELECT * FROM storage_producer_jobs WHERE id=?',(actual[0],)).fetchone() if actual and actual[0] else None
            from .producer_recovery import read as recovery
            receipt=recovery(conn,job['id']) if job else None
            from .producer_events import read as diagnostics
            events=diagnostics(conn,job['id']) if job else []
            latest=next((e for e in reversed(events) if e['stage'] in ('submission_rejected','submission_unknown')), {})
        if row['phase']=='submit' and not (job and job['task_id']) and (latest.get('stage')=='submission_rejected' or (receipt and receipt['submission']=='rejected')):
            provider=getattr(error,'provider_code',latest.get('provider_code'));http=getattr(error,'http_status',latest.get('http_status'))
            with self.tx() as conn:
                self.validate(conn,row)
                if row['current_batch']:conn.execute('UPDATE parse_queue_jobs SET current_batch=NULL WHERE id=?',(row['id'],))
            if str(provider)=='-60018':
                with self.tx() as conn:
                    self.validate(conn,row);conn.execute('UPDATE parse_queue_control SET submit_paused=1')
                return self.finish(row,state='paused',error='provider_daily_quota',upstream='rejected')
            if str(provider)=='-60009' or str(http)=='429':
                attempts=self.status(row['id'])['submissions'];delay=min(60,2**attempts)
                with self.tx() as conn:
                    self.validate(conn,row);conn.execute('UPDATE parse_queue_control SET submit_after=max(submit_after,?)',(self.clock()+delay,))
                return self.finish(row,state='runnable' if attempts<self._limits().max_attempts else 'paused',
                                   delay=delay,error='provider_queue_full',upstream='rejected')
            return self.finish(row,state='paused',error='provider_submission_rejected',upstream='rejected')
        if row['phase']=='poll' and code!='revision_conflict':
            with self.tx() as conn:
                self.validate(conn,row)
                failure=conn.execute('SELECT attempts,cancel_requested FROM parse_queue_jobs WHERE id=?',(row['id'],)).fetchone()
                attempts=failure[0]+1
                conn.execute('UPDATE parse_queue_jobs SET attempts=? WHERE id=?',(attempts,row['id']))
            terminal=getattr(error,'http_status',None) in (401,403,404,422) or code=='provider_identity_mismatch' or attempts>=self._limits().max_attempts
            return self.finish(row,phase='poll',state='inspection_required' if terminal else ('tracking' if failure[1] else 'waiting'),
                delay=min(60,self._limits().poll_seconds*2**min(attempts,6)),error=code)
        if row['phase']=='download' and code=='result_not_ready':return self.finish(row,phase='poll',state='waiting',delay=self._limits().poll_seconds,error=code)
        state='blocked_budget' if code=='budget_exhausted' else 'inspection_required'
        if row['phase']=='prepare':state='failed' if code!='budget_exhausted' else 'blocked_budget'
        self.finish(row,state=state,error=code)

    def _advance(self,row,driver,tracking=False):
        from .storage import producers
        from .producer_events import capture
        fenced=copy.copy(self.service)
        fenced.registry=FencedRegistry(self.registry,self.authority,lambda c:self.validate(c,row))
        limits=self._limits();phase=row['phase']
        if phase=='upload':
            from .parse_batches import upload
            upload(self,row,driver);return
        if phase=='prepare':
            current=parse_plans.status(self.registry,row['plan_id']);item=current['items'][row['position']];expected=item['source']
            binding=self.registry.binding(row['source_file_id'],'pdf',1)
            if (binding['sha256'],binding['bytes'])!=(expected['sha256'],expected['bytes']):raise StorageError('checksum_mismatch','planned PDF differs')
            if binding['bytes']>limits.max_input_bytes:raise StorageError('input_budget_exceeded','input exceeds scheduler limit')
            with fenced.read(row['source_file_id'],'pdf',1) as pdf:pages=driver.pages(pdf)
            if type(pages) is not int or pages<1:raise StorageError('invalid_request','page count unavailable')
            if row['backend']=='vlm' and pages>limits.max_pages_per_file:raise StorageError('provider_file_page_limit','file exceeds configured provider page limit')
            def link(conn,jid):
                budget=conn.execute('SELECT * FROM parse_plans WHERE id=?',(row['plan_id'],)).fetchone()
                used=conn.execute('SELECT COALESCE(sum(reserved),0),COALESCE(sum(pages*reserved),0) FROM parse_plan_items WHERE plan_id=?',(row['plan_id'],)).fetchone()
                if used[0]>=budget['max_items'] or (budget['max_pages'] is not None and used[1]+pages>budget['max_pages']):raise StorageError('budget_exhausted','plan budget exhausted')
                source=conn.execute('SELECT sf.work_id,sf.content_sha256,sf.status,w.read_status FROM source_files sf JOIN works w ON w.id=sf.work_id WHERE sf.id=?',(row['source_file_id'],)).fetchone()
                prior=conn.execute("SELECT id,state FROM storage_producer_jobs WHERE kind='parse' AND source_file_id=? AND id!=? ORDER BY version DESC LIMIT 1",(row['source_file_id'],jid)).fetchone()
                if not source or source[0]!=expected['work_id'] or source[1]!=expected['sha256'] or source[2]!='active' or source[3] in ('quarantined','archived') or (prior[0] if prior else None)!=expected['baseline_job'] or (prior[1] if prior else None)!=expected['baseline_state']:
                    raise StorageError('revision_conflict','frozen source baseline changed')
                conn.execute("UPDATE parse_plan_items SET state='running',reserved=1,pages=?,job_id=? WHERE plan_id=? AND position=?",(pages,jid,row['plan_id'],row['position']))
                conn.execute('UPDATE parse_queue_jobs SET producer_id=? WHERE id=?',(jid,row['id']))
            source,rid,out,jid=producers.prepare_parse(fenced,row['source_file_id'],force=True,backend=row['backend'],on_registered=link)
            out.mkdir(parents=True,exist_ok=False)
            (out/'.litlib-producer-owned.json').write_text(json.dumps({'job_id':jid,'catalog':str(self.registry.catalog),'output':str(out),'files':None,'release_state':'producing'}),'utf-8')
            self.finish(row,phase='submit' if row['backend']=='vlm' else 'local');return
        with self.registry.conn(read_only=True) as conn:
            current=conn.execute('SELECT producer_id FROM parse_queue_jobs WHERE id=?',(row['id'],)).fetchone()
            job=dict(conn.execute('SELECT * FROM storage_producer_jobs WHERE id=?',(current[0],)).fetchone())
            run=dict(conn.execute('SELECT * FROM literature_parse_runs WHERE id=?',(job['parse_run_id'],)).fetchone())
        if phase=='publish':
            job=producers._finish(fenced,job['id'])
            with self.tx() as conn:
                self.validate(conn,row)
                conn.execute("UPDATE parse_plan_items SET state='succeeded',error_code=NULL WHERE plan_id=? AND position=?",(row['plan_id'],row['position']))
            self.finish(row,state='succeeded',upstream='done');return
        out=Path(run['output_dir'])
        if phase in ('submit','download','local'):out,owner=producers.owned_output(fenced,job,run)
        if phase in ('download','local') and shutil.disk_usage(out).free<3*limits.max_download_bytes+limits.min_free_bytes:
            raise StorageError('working_disk_full','preserve work; free space before resuming')
        # Reuse the cold-restore ownership checks, without submitting a task.
        with capture(fenced.registry,job['id']) as event:
            event('async_'+phase,backend=row['backend'])
            with fenced.read(row['source_file_id'],'pdf',1) as pdf:
                if phase=='submit':
                    task=driver.submit(pdf,out,event,language=row['language'])
                    if not task:raise StorageError('submission_unknown','upstream ID unavailable')
                    event('upstream_submitted',task_id=task,backend='vlm')
                    self.finish(row,phase='poll',state='waiting',delay=limits.poll_seconds,upstream='pending');return
                if phase=='poll':
                    result=driver.poll(pdf,job['task_id'],event)
                    state=result.get('state','pending')
                    if tracking:
                        self.finish(row,phase='poll',state=('cancelled' if tracking==2 else 'paused') if state in ('done','failed') else 'tracking',delay=limits.poll_seconds,upstream=state);return
                    if state=='done':self.finish(row,phase='download',upstream='done');return
                    if state=='failed':
                        with fenced.registry.conn(write=True) as conn:
                            conn.execute("UPDATE producer_recovery SET submission='terminal_failed' WHERE job_id=?",(job['id'],))
                            conn.execute("UPDATE storage_producer_jobs SET state='failed',error_code='upstream_failed' WHERE id=?",(job['id'],))
                            conn.execute("UPDATE literature_parse_runs SET status='failed',error='upstream_failed' WHERE id=?",(job['parse_run_id'],))
                            conn.execute("UPDATE parse_plan_items SET state='failed',error_code='upstream_failed' WHERE plan_id=? AND position=?",(row['plan_id'],row['position']))
                        self.finish(row,state='failed',error='upstream_failed',upstream='failed');return
                    self.finish(row,phase='poll',state='waiting',delay=limits.poll_seconds,upstream=state);return
                if phase=='download':
                    if row['current_batch']:
                        from .parse_batches import download
                        download(self,row,driver,pdf,out,event,limits.max_download_bytes)
                    else:driver.download(pdf,out,job['task_id'],event,limits.max_download_bytes)
                elif phase=='local':driver.local(pdf,out,event,language=row['language'])
            if sum(p.stat().st_size for p in out.rglob('*') if p.is_file())>3*limits.max_download_bytes:
                raise StorageError('output_budget_exceeded','owned output exceeds materialization budget')
            owner=json.loads((out/'.litlib-producer-owned.json').read_text('utf-8'))
            producers._stage_parse_assets(fenced,job['id'],out,row['backend'],job['task_id'] or '',owner)
        self.finish(row,phase='publish')
