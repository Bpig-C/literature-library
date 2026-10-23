import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from api import parse_plans,remote_access
from api.parse_queue import Queue,Limits,snapshot_barrier
from api.routes import async_parse,foundation
from api.storage import authority,producers
from api.storage.authority import Authority
from api.storage.core import StorageError
from api.storage.fenced import FencedRegistry
from test_foundation_plans import service,preview,sqlite_read


class Clock:
    def __init__(self):self.now=1000000.
    def __call__(self):return self.now
    def tick(self,seconds=2):self.now+=seconds


class Driver:
    def __init__(self,states=None):self.submits=[];self.polls=[];self.downloads=[];self.states=states or ['done']
    def pages(self,pdf):return 2
    def submit(self,pdf,out,event,*,language=''):
        event('submitting',backend='vlm')
        task='cloud-'+Path(pdf).stem
        self.submits.append(task);event('upstream_submitted',task_id=task)
        return task
    def poll(self,pdf,task,event):
        self.polls.append(task);event('poll',task_id=task)
        return {'state':self.states.pop(0) if len(self.states)>1 else self.states[0]}
    def download(self,pdf,out,task,event,maximum):
        self.downloads.append(task);event('download',task_id=task)
        (out/'content.md').write_text('fixed result '+task,'utf-8')
        (out/'content.json').write_text('{}')
    def local(self,pdf,out,event,*,language=''):(out/'content.md').write_text('local result','utf-8')


@pytest.fixture
def queue(service,tmp_path):
    a=Authority(service.backend,service.ns.root,'synthetic-owner-'+'x'*32,0,tmp_path/'authority')
    a.initialize()
    return Queue(service,a,clock=Clock(),limits=Limits(upstream=1,poll_seconds=1,submit_per_minute=600,poll_per_minute=600,lease_seconds=15))


def accept(q,*,backend='vlm',items=2,submissions=2,pages=100,request='async',source_ids=None):
    with q.registry.conn(read_only=True) as conn:
        plan=parse_plans.preview(conn,parse_plans.Selection(backend=backend,purpose='deception',source_file_ids=source_ids or []))
    return parse_plans.accept(q.registry,plan,request,items,submissions,pages)['plan_id']


def run_all(q,driver,pid):
    for _ in range(80):
        q.run_one(driver);q.clock.tick()
        state=q.plan_status(pid)
        if state['tasks'] and all(t['state'] in ('succeeded','failed','inspection_required','blocked_budget','paused','cancelled') for t in state['tasks']):return state
    pytest.fail('scheduler did not converge')


def test_pipeline_pending_is_not_failure_and_replay_keeps_budget(queue):
    pid=accept(queue);first=queue.enqueue(pid);driver=Driver(['pending','running','done'])
    assert len(first['tasks'])==2
    queue.run_one(driver);queue.clock.tick();queue.run_one(driver);queue.clock.tick()
    waiting=queue.run_one(driver)
    assert waiting['state']=='waiting' and waiting['phase']=='poll' and waiting['upstream_state']=='pending'
    with queue.registry.conn(read_only=True) as conn:
        assert conn.execute("SELECT count(*) FROM literature_parse_runs WHERE status='failed'").fetchone()[0]==0
    queue.clock.tick()
    completed=run_all(queue,driver,pid)
    assert completed['action']=='complete' and len(driver.submits)==len(set(driver.submits))==2
    assert completed['budget']['reserved_items']==completed['budget']['reserved_submissions']==2
    assert completed['budget']['reserved_pages']==4
    assert [t['id'] for t in queue.enqueue(pid)['tasks']]==[t['id'] for t in first['tasks']]


def test_slow_cloud_does_not_block_other_work_and_api_returns_202(queue,monkeypatch):
    pid=accept(queue);token='t'*40
    monkeypatch.setenv('LITLIB_ASYNC_PARSE_ENABLED','1');monkeypatch.setenv('LITLIB_STORAGE_MODE','immutable')
    monkeypatch.setenv('LITLIB_REMOTE_ENABLED','1');monkeypatch.setenv('LITLIB_REMOTE_WRITE_ENABLED','1');monkeypatch.setenv('LITLIB_REMOTE_TOKEN',token)
    monkeypatch.setattr(authority,'configured_authority',lambda:queue.authority)
    monkeypatch.setattr(async_parse,'queue',lambda:queue)
    app=FastAPI();app.add_middleware(remote_access.RemoteAuthentication);app.include_router(async_parse.router,prefix='/api')
    @app.post('/api/works/W2/purpose-probe')
    def other_write():
        with queue.registry.conn(write=True) as conn:conn.execute("UPDATE works SET updated_at='other write committed' WHERE id='W2'")
        return {'ok':True}
    @app.exception_handler(StorageError)
    async def error(request,exc):return JSONResponse({'code':exc.code},status_code=409)
    started=threading.Event();finish=threading.Event()
    class Slow(Driver):
        def submit(self,*args,**kwargs):started.set();assert finish.wait(5);return super().submit(*args,**kwargs)
    driver=Slow();headers={'Authorization':'Bearer '+token}
    with TestClient(app) as client,ThreadPoolExecutor(max_workers=1) as pool:
        assert client.post(f'/api/async/parse/plans/{pid}/enqueue',json={'max_tasks':1},headers=headers).status_code==202
        assert client.post(f'/api/async/parse/plans/{pid}/enqueue',json={}).status_code==401
        queue.run_one(driver);queue.clock.tick()
        pending=pool.submit(queue.run_one,driver)
        try:
            assert started.wait(3)
            assert client.post('/api/works/W2/purpose-probe',headers=headers).status_code==200
            assert client.get('/api/async/parse/scheduler',headers=headers).status_code==200
            response=client.post('/api/parse/trigger',json={},headers=headers)
            assert response.status_code==409 and response.json()['code']=='async_required'
        finally:finish.set()
        assert pending.result(5)['phase']=='poll'
    with queue.registry.conn(read_only=True) as conn:assert conn.execute("SELECT updated_at FROM works WHERE id='W2'").fetchone()[0]=='other write committed'


def test_same_source_competing_plans_conflict_before_submission(queue):
    first=accept(queue,request='one',source_ids=['SF1']);second=accept(queue,request='two',source_ids=['SF1'])
    task=queue.enqueue(first)['tasks'][0]
    with pytest.raises(StorageError,match=task['id']):queue.enqueue(second)
    assert queue.enqueue(first)['tasks'][0]['id']==task['id']


def test_capacity_and_rates_are_shared_between_queue_instances(queue):
    pid=accept(queue);queue.enqueue(pid)
    second=Queue(queue.service,queue.authority,clock=queue.clock)
    row=queue.claim();assert row['phase']=='prepare'
    assert second.claim() is None
    queue.finish(row,state='queued')
    driver=Driver()
    for _ in range(6):
        queue.run_one(driver)
        if driver.submits:break
        queue.clock.tick()
    # One upstream task fills the shared capacity, but preparing another source
    # is allowed. Its submission cannot create a second cloud task yet.
    queue.clock.tick(.2)
    assert second.claim() is None
    assert len(driver.submits)==1
    assert second.overview()['limits']['upstream']==1
    with queue.registry.conn(read_only=True) as conn:
        assert conn.execute('SELECT sum(submissions) FROM parse_queue_jobs').fetchone()[0]==1


def test_two_local_sources_actually_overlap_with_configured_capacity(queue):
    queue.initial_limits=replace(queue.initial_limits,prepare=2,local=2)
    pid=accept(queue,backend='pymupdf',submissions=0);queue.enqueue(pid)
    queue.run_one(Driver());queue.clock.tick();queue.run_one(Driver());queue.clock.tick()
    lock=threading.Lock();both=threading.Event();finish=threading.Event();counts={'active':0,'peak':0}
    class SlowLocal(Driver):
        def local(self,*args,**kwargs):
            with lock:
                counts['active']+=1;counts['peak']=max(counts['peak'],counts['active'])
                if counts['active']==2:both.set()
            try:assert finish.wait(5);return super().local(*args,**kwargs)
            finally:
                with lock:counts['active']-=1
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(queue.run_one,SlowLocal()) for _ in range(2)]
        try:assert both.wait(3)
        finally:finish.set()
        for f in futures:assert f.result(5)['phase']=='publish'
    assert counts['peak']==2
    assert run_all(queue,Driver(),pid)['action']=='complete'


def test_expired_submit_response_lost_never_posts_again(queue):
    pid=accept(queue,source_ids=['SF1']);queue.enqueue(pid);driver=Driver()
    queue.run_one(driver);queue.clock.tick()
    class Die(Driver):
        def submit(self,pdf,out,event,**kwargs):event('submitting',backend='vlm');raise KeyboardInterrupt('process died after intent')
    with pytest.raises(KeyboardInterrupt):queue.run_one(Die())
    queue.clock.tick(20)
    assert queue.run_one(driver)['state']=='idle'
    task=queue.plan_status(pid)['tasks'][0]
    assert task['state']=='inspection_required' and task['submissions']==1 and not driver.submits
    with pytest.raises(StorageError,match='never blindly'):queue.action(task['id'],'resume','Inspected but outcome still unknown')
    cancelled=queue.action(task['id'],'cancel','Preserve unknown consumption and stop')
    assert cancelled['state']=='cancelled'
    assert queue.plan_status(pid)['budget']['reserved_submissions']==1


def test_known_task_survives_death_before_worker_saves_phase(queue):
    pid=accept(queue,source_ids=['SF1']);queue.enqueue(pid);driver=Driver()
    queue.run_one(driver);queue.clock.tick()
    class Die(Driver):
        def submit(self,pdf,out,event,**kwargs):
            event('submitting',backend='vlm');event('upstream_submitted',task_id='existing-cloud')
            raise KeyboardInterrupt('process died after upstream ID persisted')
    with pytest.raises(KeyboardInterrupt):queue.run_one(Die())
    queue.clock.tick(20)
    complete=run_all(queue,driver,pid)
    assert complete['action']=='complete' and driver.submits==[] and driver.downloads==['existing-cloud']
    assert complete['budget']['reserved_submissions']==1


def test_death_before_post_releases_upstream_slot_but_preserves_attempt_budget(queue):
    pid=accept(queue,source_ids=['SF1']);queue.enqueue(pid);driver=Driver()
    queue.run_one(driver);queue.clock.tick()
    row=queue.claim();assert row['phase']=='submit'  # crash before submitting intent/POST
    queue.clock.tick(20)
    completed=run_all(queue,driver,pid)
    assert completed['action']=='complete' and len(driver.submits)==1
    assert completed['budget']['reserved_submissions']==2


def test_stale_epoch_and_generation_cannot_write_or_register(queue):
    pid=accept(queue,source_ids=['SF1']);queue.enqueue(pid);row=queue.claim()
    fenced=FencedRegistry(queue.registry,queue.authority,lambda conn:queue.validate(conn,row))
    with queue.tx() as conn:conn.execute('UPDATE parse_queue_jobs SET generation=generation+1 WHERE id=?',(row['id'],))
    with pytest.raises(StorageError,match='lease'):
        with fenced.conn(write=True) as conn:conn.execute("UPDATE works SET updated_at='stale'")
    release={'manifest_sha256':'e'*64,'manifest_key':queue.service.ns.key('e'*64)}
    queue.authority.handover(hashlib.sha256(('new-owner-'+'z'*32).encode()).hexdigest(),release)
    with pytest.raises(StorageError):queue.finish(row,state='succeeded')
    with pytest.raises(StorageError):
        with fenced.conn(write=True):pytest.fail('old epoch entered catalog transaction')
    with queue.registry.conn(read_only=True) as conn:assert not conn.execute("SELECT 1 FROM works WHERE updated_at='stale'").fetchone()


def test_prepare_crash_rolls_back_identity_budget_and_link(queue,monkeypatch):
    pid=accept(queue);queue.enqueue(pid);original=producers.prepare_parse
    def crash(*args,**kwargs):
        callback=kwargs['on_registered']
        def link(conn,jid):callback(conn,jid);raise KeyboardInterrupt('atomic prepare interrupted')
        kwargs['on_registered']=link;return original(*args,**kwargs)
    monkeypatch.setattr(producers,'prepare_parse',crash)
    with pytest.raises(KeyboardInterrupt):queue.run_one(Driver())
    assert queue.plan_status(pid)['budget']['reserved_items']==0
    with queue.registry.conn(read_only=True) as conn:assert conn.execute("SELECT count(*) FROM storage_producer_jobs WHERE kind='parse'").fetchone()[0]==0
    monkeypatch.setattr(producers,'prepare_parse',original);queue.clock.tick(20)
    assert run_all(queue,Driver(),pid)['action']=='complete'


def test_page_budget_and_submission_retry_budget_are_enforced(queue):
    pid=accept(queue,pages=1);queue.enqueue(pid)
    assert run_all(queue,Driver(),pid)['action']=='budget_exhausted'
    assert queue.plan_status(pid)['budget']['reserved_items']==0
    second=accept(queue,request='retry-budget',source_ids=['SF1'],submissions=1)
    queue.enqueue(second)
    class QueueFull(Driver):
        def submit(self,pdf,out,event,**kwargs):
            event('submitting',backend='vlm');event('submission_rejected',http_status=200,provider_code=-60009)
            raise RuntimeError('private provider details')
    driver=QueueFull();queue.run_one(driver);queue.clock.tick();queue.run_one(driver);queue.clock.tick(20)
    assert run_all(queue,driver,second)['action']=='budget_exhausted'
    status=queue.plan_status(second)
    assert status['budget']['reserved_submissions']==1
    assert 'private' not in json.dumps(status)


def test_daily_quota_stops_submission_but_keeps_other_phases_available(queue):
    pid=accept(queue);queue.enqueue(pid,max_tasks=1);queue.run_one(Driver());queue.clock.tick()
    class Daily(Driver):
        def submit(self,pdf,out,event,**kwargs):
            event('submitting',backend='vlm');event('submission_rejected',http_status=200,provider_code=-60018)
            raise RuntimeError('daily limit')
    result=queue.run_one(Daily())
    assert result['state']=='paused' and result['error_code']=='provider_daily_quota'
    assert queue.overview()['submission_paused'] is True


def test_maintenance_drains_existing_jobs_blocks_new_work_and_snapshot_claims(queue):
    pid=accept(queue);queue.enqueue(pid);queue.run_one(Driver());queue.clock.tick()
    queue.maintenance('drain','backup-owner')
    with pytest.raises(StorageError):queue.enqueue(pid)
    with pytest.raises(StorageError):queue.maintenance('snapshot','backup-owner')
    # A pre-existing prepared job finishes; the other queued Source is not started.
    driver=Driver()
    for _ in range(10):queue.run_one(driver);queue.clock.tick()
    assert len(driver.submits)==1
    tasks=queue.plan_status(pid)['tasks'];assert {t['state'] for t in tasks}=={'succeeded','queued'}
    queue.maintenance('snapshot','backup-owner')
    assert queue.claim() is None
    with pytest.raises(StorageError):queue.maintenance('resume','wrong-owner')
    queue.maintenance('resume','backup-owner')
    assert run_all(queue,driver,pid)['action']=='complete'


def test_empty_queue_reads_do_not_initialize_catalog(queue):
    from api.storage.core import hash_file
    before=hash_file(queue.registry.catalog)
    assert queue.overview()['configured'] is False
    with pytest.raises(StorageError,match='async task not found'):queue.status('missing')
    with pytest.raises(StorageError,match='native batch not found'):queue.batch_status('missing')
    assert hash_file(queue.registry.catalog)==before
    with queue.registry.conn(read_only=True) as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name LIKE 'parse_queue_%' OR name LIKE 'parse_cloud_%'").fetchone()


def test_snapshot_barrier_blocks_control_changes_until_owner_resumes(queue,monkeypatch):
    pid=accept(queue);task=queue.enqueue(pid)['tasks'][0]
    queue.maintenance('drain','backup-owner');queue.maintenance('snapshot','backup-owner')
    before=queue.overview();task_before=queue.status(task['id'])
    with pytest.raises(StorageError,match='snapshot barrier'):queue.configure(replace(queue.initial_limits,upstream=2))
    with pytest.raises(StorageError,match='snapshot barrier'):queue.action(task['id'],'cancel','operator cancellation')
    with pytest.raises(StorageError,match='snapshot barrier'):queue.resolve(task['id'],'not_submitted','verified by operator')
    monkeypatch.setattr(async_parse,'queue',lambda:queue)
    from api import backup_jobs
    monkeypatch.setattr(backup_jobs,'authorize',lambda token:None)
    with pytest.raises(StorageError,match='snapshot barrier'):
        async_parse.maintain('resume-submissions',async_parse.Maintenance(owner='backup-owner',reason='resume submissions',force=True),None)
    assert queue.overview()==before and queue.status(task['id'])==task_before
    queue.maintenance('resume','backup-owner')
    assert queue.action(task['id'],'cancel','operator cancellation')['state']=='cancelled'


def test_cancel_pause_resume_are_explicit_and_preserve_existing_task(queue):
    pid=accept(queue,source_ids=['SF1']);task=queue.enqueue(pid)['tasks'][0];driver=Driver()
    queue.run_one(driver);queue.clock.tick();queue.run_one(driver);queue.clock.tick()
    assert queue.action(task['id'],'pause','Pause waiting for cloud')['state']=='paused'
    assert queue.action(task['id'],'resume','Continue original task')['phase']=='poll'
    assert run_all(queue,driver,pid)['action']=='complete'
    assert len(driver.submits)==1


def test_reclamation_and_sync_resume_cannot_take_async_source(queue):
    pid=accept(queue,source_ids=['SF1']);queue.enqueue(pid);queue.run_one(Driver())
    task=queue.plan_status(pid)['tasks'][0]
    with pytest.raises(StorageError):producers.resume_producer(task['producer_id'],queue.service)
    with pytest.raises(StorageError):producers.release_producer_output(task['producer_id'],queue.service)


@pytest.mark.parametrize('outcome',['not_submitted','task_found'])
def test_operator_resolution_is_audited_and_does_not_refund_or_blindly_post(queue,outcome):
    pid=accept(queue,source_ids=['SF1']);task=queue.enqueue(pid)['tasks'][0]
    driver=Driver();queue.run_one(driver);queue.clock.tick()
    class Lost(Driver):
        def submit(self,pdf,out,event,**kwargs):event('submitting',backend='vlm');raise TimeoutError('response lost')
    assert queue.run_one(Lost())['state']=='inspection_required'
    resolved=queue.resolve(task['id'],outcome,'Provider account records verified',task_id='found-original' if outcome=='task_found' else None)
    assert any(e['event']=='provider_verified' for e in resolved['events'])
    assert queue.plan_status(pid)['budget']['reserved_submissions']==1
    if outcome=='task_found':
        assert run_all(queue,driver,pid)['action']=='complete' and driver.submits==[]
    else:
        assert resolved['state']=='paused'
        assert preview(queue.service,source_file_ids=['SF1'])['items']
        queue.action(task['id'],'resume','Explicit retry with remaining submission budget')
        assert run_all(queue,driver,pid)['action']=='complete'
        assert queue.plan_status(pid)['budget']['reserved_submissions']==2


def test_completed_task_cannot_be_cancelled_or_restarted(queue):
    pid=accept(queue,source_ids=['SF1']);task=queue.enqueue(pid)['tasks'][0]
    assert run_all(queue,Driver(),pid)['action']=='complete'
    for action in ('pause','cancel','resume'):
        with pytest.raises(StorageError,match='completed'):queue.action(task['id'],action,'Must preserve completed result')
    assert queue.plan_status(pid)['items'][0]['state']=='succeeded'


def test_historical_resume_cannot_bypass_a_newer_source_task(queue):
    pid=accept(queue,source_ids=['SF1']);old=queue.enqueue(pid)['tasks'][0];driver=Driver()
    queue.run_one(driver);queue.clock.tick()
    queue.action(old['id'],'cancel','Stop before POST')
    newer=accept(queue,source_ids=['SF1'],request='newer-source-intent')
    queue.enqueue(newer);queue.run_one(driver);queue.clock.tick()
    with pytest.raises(StorageError,match='another active|later parse'):queue.action(old['id'],'resume','Old task must stay historical')
    assert run_all(queue,driver,newer)['action']=='complete' and len(driver.submits)==1
    with pytest.raises(StorageError,match='later parse'):queue.action(old['id'],'resume','Still must not resurrect v1')


@pytest.mark.parametrize('status,expected',[ (403,1),(503,3) ])
def test_poll_errors_are_bounded_and_preserve_task_identity(queue,status,expected):
    pid=accept(queue,source_ids=['SF1']);task=queue.enqueue(pid)['tasks'][0];driver=Driver()
    queue.run_one(driver);queue.clock.tick();queue.run_one(driver);queue.clock.tick()
    class FailedQueries(Driver):
        def poll(self,*args):
            self.polls.append('query')
            error=StorageError('provider_query_failed','not returned to client');error.http_status=status
            raise error
    failing=FailedQueries();state=run_all(queue,failing,pid)
    assert state['tasks'][0]['state']=='inspection_required' and len(failing.polls)==expected
    assert state['tasks'][0]['attempts']==expected and len(driver.submits)==1
    assert queue.status(task['id'])['producer']['task_id']==driver.submits[0]
    assert any(e['event']=='phase_error' and e['detail'].get('http_status')==status for e in queue.status(task['id'])['events'])


def test_cancelled_cloud_task_is_tracked_to_terminal_and_releases_capacity(queue):
    pid=accept(queue);queue.enqueue(pid,max_tasks=1);driver=Driver(['pending','done'])
    queue.run_one(driver);queue.clock.tick();queue.run_one(driver);queue.clock.tick()
    first=queue.plan_status(pid)['tasks'][0]
    cancelled=queue.action(first['id'],'cancel','Stop local download; still track provider')
    assert cancelled['state']=='cancelled' and cancelled['tracking_upstream']
    queue.enqueue(pid,max_tasks=2)
    for _ in range(30):queue.run_one(driver);queue.clock.tick()
    status=queue.plan_status(pid)
    assert [t['state'] for t in status['tasks']]==['cancelled','succeeded']
    assert not queue.status(first['id'])['tracking_upstream']
    assert len(driver.submits)==2 and len(driver.downloads)==1


@pytest.mark.parametrize('first_state',['pending','done'])
def test_cancel_during_poll_lease_settles_business_rows_and_allows_snapshot(queue,first_state):
    pid=accept(queue,source_ids=['SF1']);task=queue.enqueue(pid)['tasks'][0]
    start=threading.Event();release=threading.Event()
    class SlowPoll(Driver):
        def poll(self,*args):start.set();assert release.wait(5);return {'state':first_state}
    driver=SlowPoll();queue.run_one(driver);queue.clock.tick();queue.run_one(driver);queue.clock.tick()
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(queue.run_one,driver)
        try:
            assert start.wait(3)
            assert queue.action(task['id'],'cancel','Cancel while provider GET is in progress')['cancel_requested']==2
        finally:release.set()
        pending.result(5)
    reader=Driver()
    for _ in range(10):
        queue.clock.tick();queue.run_one(reader)
        status=queue.status(task['id'])
        if status['state']=='cancelled' and not status['tracking_upstream']:break
    else:pytest.fail('cancel did not settle')
    with queue.registry.conn(read_only=True) as conn:
        assert conn.execute("SELECT count(*) FROM literature_parse_runs WHERE status='running'").fetchone()[0]==0
        assert conn.execute("SELECT count(*) FROM storage_producer_jobs WHERE kind='parse' AND state='preparing'").fetchone()[0]==0
        assert conn.execute('SELECT state FROM parse_plan_items WHERE plan_id=?',(pid,)).fetchone()[0]=='abandoned'
    queue.maintenance('drain','cancel-snapshot');queue.maintenance('snapshot','cancel-snapshot')
    assert len(driver.submits)==1 and reader.submits==reader.downloads==[]


def test_late_upload_cannot_register_after_handover_and_new_epoch_resumes(queue,tmp_path,monkeypatch):
    pid=accept(queue,source_ids=['SF1']);queue.enqueue(pid);driver=Driver()
    for _ in range(10):
        state=queue.run_one(driver);queue.clock.tick()
        if state.get('phase')=='publish':break
    else:pytest.fail('publish phase missing')
    task=queue.plan_status(pid)['tasks'][0];jid=task['producer_id']
    original=queue.service.backend.put_immutable;switched=[]
    token='new-owner-'+'z'*32
    release={'manifest_sha256':'e'*64,'manifest_key':queue.service.ns.key('e'*64)}
    def upload_then_handover(key,path):
        result=original(key,path)
        if not switched and '/control/authority/' not in key:
            switched.append(True)
            queue.authority.handover(hashlib.sha256(token.encode()).hexdigest(),release)
        return result
    monkeypatch.setattr(queue.service.backend,'put_immutable',upload_then_handover)
    with pytest.raises(StorageError):queue.run_one(driver)
    with queue.registry.conn(read_only=True) as conn:
        rid=conn.execute('SELECT parse_run_id FROM storage_producer_jobs WHERE id=?',(jid,)).fetchone()[0]
        assert not conn.execute("SELECT 1 FROM storage_bindings WHERE identity=? AND role='md'",(rid,)).fetchone()
    new_authority=Authority(queue.service.backend,queue.service.ns.root,token,1,tmp_path/'new-authority',release['manifest_sha256'])
    current=Queue(queue.service,new_authority,clock=queue.clock)
    queue.clock.tick(20)
    assert run_all(current,driver,pid)['action']=='complete'
    assert len(driver.submits)==1


def test_actual_cli_uses_background_acceptance_and_task_controls(queue,tmp_path,monkeypatch,capsys):
    import socket,uvicorn
    from api import remote_version
    from test_remote_version import cli
    token='t'*40
    for name,value in {'LITLIB_ASYNC_PARSE_ENABLED':'1','LITLIB_STORAGE_MODE':'immutable','LITLIB_REMOTE_ENABLED':'1','LITLIB_REMOTE_WRITE_ENABLED':'1','LITLIB_REMOTE_TOKEN':token}.items():monkeypatch.setenv(name,value)
    monkeypatch.setattr(authority,'configured_authority',lambda:queue.authority)
    monkeypatch.setattr(async_parse,'queue',lambda:queue)
    monkeypatch.setattr(foundation,'configured_registry',lambda:queue.registry)
    monkeypatch.setattr(foundation,'get_read_conn',lambda:sqlite_read(queue.registry.catalog))
    monkeypatch.setattr(foundation,'enabled',lambda:True)
    monkeypatch.setattr(remote_version,'version_info',lambda:dict(format='litlib-client-capabilities-v1',protocol_version=1,
        capabilities={'parse_plans_v1':{},'async_parse_v1':{'enabled':True}}))
    app=FastAPI();app.add_middleware(remote_access.RemoteAuthentication)
    for router in (remote_access.router,foundation.router,async_parse.router):app.include_router(router,prefix='/api')
    sock=socket.socket();sock.bind(('127.0.0.1',0))
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',lifespan='off'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    try:
        for _ in range(100):
            if server.started:break
            time.sleep(.02)
        assert server.started
        module=cli();base=['--server',f'http://127.0.0.1:{sock.getsockname()[1]}'];path=tmp_path/'async-plan.json'
        assert module.main(base+['parse','plan','--backend','vlm','--source-file-id','SF1','--output',str(path)])==0
        assert module.main(base+['parse','run','--plan',str(path),'--request-id','async-cli','--max-items','1','--max-submissions','1','--execute'])==0
        with queue.registry.conn(read_only=True) as conn:
            row=conn.execute('SELECT id,plan_id,producer_id FROM parse_queue_jobs').fetchone()
        assert row['producer_id'] is None  # HTTP/CLI did not run the parser
        assert module.main(base+['parse','status','--task-id',row['id']])==0
        assert module.main(base+['parse','pause','--task-id',row['id'],'--reason','Pause before work','--execute'])==0
        assert module.main(base+['parse','retry','--task-id',row['id'],'--reason','Resume frozen input','--execute'])==0
        assert run_all(queue,Driver(),row['plan_id'])['action']=='complete'
        assert module.main(base+['parse','status','--plan-id',row['plan_id']])==0
        assert module.main(base+['parse','scheduler'])==0
        with queue.tx() as conn:conn.execute('UPDATE parse_queue_control SET submit_paused=1')
        monkeypatch.setenv('LITLIB_BACKUP_ADMIN_TOKEN','b'*40)
        assert module.main(base+['parse','scheduler','--resume-submissions','--reason','Account limit verified available','--execute'])==0
        assert queue.overview()['submission_paused'] is False
        assert 'background' in capsys.readouterr().out
    finally:server.should_exit=True;thread.join(10);sock.close()
