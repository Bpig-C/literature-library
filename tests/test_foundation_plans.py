import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from api import parse_plans as plans, db, remote_access
from api.routes import foundation
from api.storage import producers, authority
from api.storage.core import StorageError, hash_file
from test_remote_access import fixture


@pytest.fixture
def service(tmp_path, monkeypatch):
    svc=fixture(tmp_path)
    with svc.registry.conn(write=True) as conn:
        conn.executescript('''CREATE TABLE works(id TEXT PRIMARY KEY,language TEXT,created_at TEXT,read_status TEXT,parse_status TEXT,updated_at TEXT);
            CREATE TABLE source_files(id TEXT PRIMARY KEY,work_id TEXT,source_path TEXT,content_sha256 TEXT,file_size INTEGER,status TEXT,import_time TEXT);
            CREATE TABLE literature_parse_runs(id TEXT PRIMARY KEY,work_id TEXT,source_file_id TEXT,source_path TEXT,status TEXT,output_dir TEXT,started_at TEXT,error TEXT,
                content_md_path TEXT,content_json_path TEXT,package_path TEXT,backend TEXT,task_id TEXT,finished_at TEXT);
            CREATE TABLE ingest_notes(request_id TEXT,work_id TEXT,source_file_id TEXT,purpose TEXT,created_at TEXT);''')
    research=tmp_path/'research.sqlite'
    with sqlite3.connect(research) as conn:conn.execute('CREATE TABLE research_text_snapshots(parse_run_id TEXT)')
    monkeypatch.setenv('LITLIB_RESEARCH_DB',str(research))
    monkeypatch.setenv('LITLIB_LIBRARY_ROOT',str(tmp_path))
    monkeypatch.setattr(db,'DB_PATH',svc.registry.catalog)
    monkeypatch.delenv('LITLIB_STORAGE_MODE',raising=False)
    for n in (1,2):
        pdf=tmp_path/f'{n}.pdf';pdf.write_bytes(b'%PDF synthetic '+str(n).encode())
        sha,size=hash_file(pdf)
        with svc.registry.conn(write=True) as conn:
            conn.execute('INSERT INTO works VALUES(?,?,?,?,?,?)',(f'W{n}','en','2026-10-22T00:00:00Z','unread','pending',''))
            conn.execute('INSERT INTO source_files VALUES(?,?,?,?,?,?,?)',(f'SF{n}',f'W{n}',str(pdf),sha,size,'active','2026-10-22T00:00:00Z'))
            conn.execute('INSERT INTO ingest_notes VALUES(?,?,?,?,?)',(f'R{n}',f'W{n}',f'SF{n}','deception','2026-10-22T00:00:00Z'))
        svc.publish(pdf,identity=f'SF{n}',role='pdf',version=1,operation_id=f'pdf{n}')
    return svc


def preview(svc, **kwargs):
    with svc.registry.conn(read_only=True) as conn:
        return plans.preview(conn,plans.Selection(backend='vlm',purpose='deception',**kwargs))


def runner(calls):
    def parse(path,out,language,backend=None):
        calls.append(path);(out/'content.md').write_text('verified output','utf-8')
        return True,'ok',backend,'task-1'
    return parse


def test_plan_is_read_only_time_same_note_and_frozen(service):
    with service.registry.conn(write=True) as conn:
        conn.execute("UPDATE ingest_notes SET created_at='2026-09-01T00:00:00Z' WHERE work_id='W1'")
        conn.execute("INSERT INTO ingest_notes VALUES('later','W1','SF1','unrelated','2026-10-22T00:00:00Z')")
    before=hash_file(service.registry.catalog)
    plan=preview(service,time_field='purpose_created',from_time='2026-10-22T08:00:00+08:00')
    assert [i['source_file_id'] for i in plan['items']]==['SF2']
    assert hash_file(service.registry.catalog)==before
    with service.registry.conn(read_only=True) as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='parse_plans'").fetchone()
    with pytest.raises(ValueError):plans.Selection(backend='vlm',from_time='2026-10-22')


def test_budget_idempotence_and_new_source_does_not_expand(service):
    plan=preview(service)
    accepted=plans.accept(service.registry,plan,'run1',1,1,10);pid=accepted['plan_id'];calls=[]
    first=plans.step(service,pid,runner(calls),count_pages=lambda p:3)
    assert first['items'][0]['state']=='succeeded'
    assert first['budget']['reserved_pages']==3
    replay=plans.accept(service.registry,plan,'run1',1,1,10)
    assert replay['plan_id']==pid
    assert plans.step(service,pid,runner(calls),count_pages=lambda p:3)['action']=='budget_exhausted'
    assert len(calls)==1 and replay['remaining']==['SF2']
    with pytest.raises(StorageError,match='different plan/budget'):plans.accept(service.registry,plan,'run1',2,2,10)


def test_page_budget_and_source_change_prevent_submission(service):
    plan=preview(service);pid=plans.accept(service.registry,plan,'run2',2,2,2)['plan_id']
    calls=[]
    assert plans.step(service,pid,runner(calls),count_pages=lambda p:3)['action']=='budget_exhausted'
    assert plans.status(service.registry,pid)['budget']['reserved_items']==0
    with service.registry.conn(write=True) as conn:conn.execute("UPDATE source_files SET status='quarantined' WHERE id='SF1'")
    with pytest.raises(StorageError,match='baseline changed'):plans.step(service,pid,runner(calls),count_pages=lambda p:1)
    assert not calls


def test_unknown_submission_blocks_replay_and_preserves_diagnostics(service):
    from api.producer_events import emit
    plan=preview(service);pid=plans.accept(service.registry,plan,'unknown',2,2)['plan_id'];calls=[]
    def fail(*args,**kwargs):
        calls.append(1);emit('upstream_submitted',task_id='known-task',ignored='secret',error_code='https://signed.invalid/?secret')
        raise TimeoutError('credential that must not reach diagnostic API')
    first=plans.step(service,pid,fail,count_pages=lambda p:1)
    assert first['action']=='inspect_failure' and first['budget']['reserved_submissions']==1
    assert plans.step(service,pid,fail,count_pages=lambda p:1)['action']=='inspect_or_resume'
    assert len(calls)==1
    with service.registry.conn(read_only=True) as conn:
        raw=conn.execute('SELECT detail FROM producer_diagnostics').fetchone()[0]
        assert 'secret' not in raw and 'credential' not in raw and 'known-task' in raw
        assert conn.execute('SELECT task_id FROM storage_producer_jobs').fetchone()[0]=='known-task'


def test_artifacts_resume_reconciles_same_plan_without_parser(service,monkeypatch):
    plan=preview(service);pid=plans.accept(service.registry,plan,'resume',1,1)['plan_id'];calls=[]
    original=producers._finish
    monkeypatch.setattr(producers,'_finish',lambda *a:(_ for _ in ()).throw(StorageError('network_unavailable','test')))
    result=plans.step(service,pid,runner(calls),count_pages=lambda p:1)
    jid=result['items'][0]['job_id'];assert result['items'][0]['producer']['state']=='artifacts_ready'
    monkeypatch.setattr(producers,'_finish',original)
    producers.resume_producer(jid,service)
    result=plans.step(service,pid,runner(calls),count_pages=lambda p:1)
    assert result['items'][0]['state']=='succeeded' and len(calls)==1


def test_crash_running_without_job_never_submits_again(service):
    plan=preview(service);pid=plans.accept(service.registry,plan,'crash',1,1)['plan_id']
    with service.registry.conn(write=True) as conn:conn.execute("UPDATE parse_plan_items SET state='running',reserved=1 WHERE plan_id=? AND position=0",(pid,))
    result=plans.step(service,pid,lambda *a,**k:pytest.fail('resubmitted'))
    assert result['action']=='inspect_or_resume'


def test_known_cloud_recovery_keeps_job_version_and_budget(service):
    from api.producer_events import emit
    plan=preview(service);pid=plans.accept(service.registry,plan,'recover-cloud',1,1)['plan_id']
    def interrupted(*args,**kwargs):
        emit('upstream_submitted',task_id='existing-task',backend='vlm')
        raise TimeoutError('poll interrupted')
    first=plans.step(service,pid,interrupted,count_pages=lambda p:2)
    jid=first['items'][0]['job_id']
    assert preview(service)['excluded'][0]['reason']=='upstream_inspection_required'
    def recover(path,out,task):
        assert task=='existing-task'
        (out/'content.md').write_text('downloaded existing result')
        return True,'ok','vlm',task
    result=producers.recover_cloud_producer(jid,recover,service)
    assert result['id']==jid and result['version']==1
    current=plans.step(service,pid,lambda *a,**k:pytest.fail('resubmitted'))
    assert current['items'][0]['state']=='succeeded' and current['budget']['reserved_submissions']==1


def test_http_read_routes_bypass_write_guard_but_not_auth(service,monkeypatch):
    token='t'*40
    monkeypatch.setenv('LITLIB_REMOTE_ENABLED','1');monkeypatch.setenv('LITLIB_REMOTE_TOKEN',token)
    monkeypatch.setenv('LITLIB_REMOTE_WRITE_ENABLED','0');monkeypatch.setenv('LITLIB_STORAGE_MODE','immutable')
    monkeypatch.setattr(foundation,'get_read_conn',lambda:sqlite_read(service.registry.catalog))
    monkeypatch.setattr(authority,'configured_authority',lambda:pytest.fail('read-only route used authority'))
    app=FastAPI();app.add_middleware(remote_access.RemoteAuthentication);app.include_router(foundation.router,prefix='/api')
    client=TestClient(app);headers={'Authorization':'Bearer '+token}
    assert client.post('/api/parse/plan',json={'backend':'vlm','purpose':'deception'}).status_code==401
    assert client.post('/api/parse/plan',json={'backend':'vlm','purpose':'deception'},headers=headers).status_code==200
    item=preview(service)['items'][0]
    result=client.post('/api/intake/reconcile',json={'items':[{'client_id':'a','sha256':item['sha256'],'request_id':'R1','purpose':'deception'}]},headers=headers)
    assert result.status_code==200 and result.json()['items'][0]['purpose_state']=='confirmed'
    assert client.post('/api/parse/plans/anything/step',json={},headers=headers).status_code==403


def sqlite_read(path):
    conn=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,check_same_thread=False);conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA query_only=ON');return conn


def test_tampered_plan_and_unknown_fields_rejected(service):
    plan=preview(service);plan['items'][0]['sha256']='b'*64
    with pytest.raises(StorageError,match='digest'):plans.accept(service.registry,plan,'tampered',1,1)
    plan['sha256']=plans.digest({k:plan[k] for k in ('format','selection','items')})
    with pytest.raises(StorageError,match='selection changed'):plans.accept(service.registry,plan,'tampered',1,1)
    with pytest.raises(ValueError):plans.Selection(backend='vlm',purpose='x',ignore_unknown=True)


def test_reconcile_receipts_match_exact_source_or_work_scope(service,monkeypatch):
    monkeypatch.setattr(foundation,'get_read_conn',lambda:sqlite_read(service.registry.catalog))
    with service.registry.conn(write=True) as conn:
        conn.execute("INSERT INTO source_files VALUES('SF1b','W1','unused',?,10,'active','2026-10-22T00:00:00Z')",('b'*64,))
    body=foundation.Reconcile(items=[foundation.IntakeItem(client_id='b',sha256='b'*64,work_id='W1',request_id='R1',purpose='deception')])
    assert foundation.reconcile(body)['items'][0]['purpose_state']=='missing'
    assert preview(service,source_file_ids=['SF1b'],request_ids=['R1'])['items']==[]
    with service.registry.conn(write=True) as conn:
        conn.execute("UPDATE ingest_notes SET source_file_id=NULL WHERE request_id='R1'")
    assert foundation.reconcile(body)['items'][0]['purpose_state']=='confirmed'
    assert len(preview(service,source_file_ids=['SF1b'],request_ids=['R1'])['items'])==1


def test_crash_during_registration_rolls_back_job_and_plan_link(service,monkeypatch):
    plan=preview(service);pid=plans.accept(service.registry,plan,'atomic-link',2,2)['plan_id']
    original=producers.parse_source
    def crash(*args,**kwargs):
        callback=kwargs['on_registered']
        def link(conn,jid):
            callback(conn,jid)
            raise KeyboardInterrupt('simulated process death before commit')
        kwargs['on_registered']=link
        return original(*args,**kwargs)
    monkeypatch.setattr(producers,'parse_source',crash)
    with pytest.raises(KeyboardInterrupt):plans.step(service,pid,runner([]),count_pages=lambda p:1)
    state=plans.status(service.registry,pid)
    assert state['items'][0]['state']=='running' and state['items'][0]['job_id'] is None
    with service.registry.conn(read_only=True) as conn:
        assert conn.execute("SELECT count(*) FROM storage_producer_jobs WHERE kind='parse'").fetchone()[0]==0
    resolved=plans.abandon(service,pid,0,'Inspected before submission')
    assert resolved['items'][0]['state']=='abandoned' and resolved['budget']['reserved_submissions']==1
    assert resolved['resolutions'][0]['reason']=='Inspected before submission'
    monkeypatch.setattr(producers,'parse_source',original)
    completed=plans.step(service,pid,runner([]),count_pages=lambda p:1)
    assert completed['items'][1]['state']=='succeeded' and completed['action']=='complete_with_abandoned'


def test_committed_crash_and_legacy_orphan_have_audited_exit(service,monkeypatch):
    from api import producer_events
    plan=preview(service);pid=plans.accept(service.registry,plan,'committed-crash',2,2)['plan_id']
    @contextmanager
    def crash(*args):raise KeyboardInterrupt('death after commit');yield
    monkeypatch.setattr(producer_events,'capture',crash)
    with pytest.raises(KeyboardInterrupt):plans.step(service,pid,runner([]),count_pages=lambda p:1)
    state=plans.status(service.registry,pid);jid=state['items'][0]['job_id']
    assert jid and state['items'][0]['producer']['state']=='preparing'
    # A legacy pre-fix orphan is deliberately identified by the operator.
    with service.registry.conn(write=True) as conn:
        conn.execute('UPDATE parse_plan_items SET job_id=NULL WHERE plan_id=? AND position=0',(pid,))
    with pytest.raises(StorageError,match='exact orphan'):plans.abandon(service,pid,0,'Inspected')
    with pytest.raises(StorageError):plans.abandon(service,pid,0,'Inspected','unrelated-job')
    resolved=plans.abandon(service,pid,0,'Confirmed interrupted before runner',jid)
    assert resolved['items'][0]['producer']['state']=='failed'
    with service.registry.conn(read_only=True) as conn:
        assert conn.execute("SELECT count(*) FROM literature_parse_runs WHERE status='running'").fetchone()[0]==0
        assert conn.execute("SELECT count(*) FROM parse_plan_items WHERE state='running'").fetchone()[0]==0
    assert len(plans.abandon(service,pid,0,'Retry same request',jid)['resolutions'])==1


def test_abandon_unknown_keeps_budget_and_prevents_fresh_submission(service):
    from api.producer_events import emit
    plan=preview(service);pid=plans.accept(service.registry,plan,'abandon-unknown',2,2)['plan_id']
    def unknown(*args,**kwargs):
        emit('submitting',backend='vlm');emit('submission_unknown')
        raise TimeoutError()
    result=plans.step(service,pid,unknown,count_pages=lambda p:2)
    resolved=plans.abandon(service,pid,0,'Provider outcome still unknown; stop this item')
    assert resolved['budget']==result['budget']
    assert preview(service,source_file_ids=['SF1'])['excluded'][0]['reason']=='upstream_inspection_required'
    assert plans.step(service,pid,runner([]),count_pages=lambda p:1)['items'][1]['state']=='succeeded'


@pytest.mark.parametrize('unsafe',['foreign_file','bad_receipt','missing_receipt'])
def test_portable_recovery_never_adopts_unowned_or_mismatched_output(service,unsafe):
    from api.producer_events import emit
    def interrupted(*args,**kwargs):
        emit('upstream_submitted',task_id='known-task',backend='vlm')
        raise TimeoutError()
    with pytest.raises(TimeoutError):producers.parse_source('SF1',interrupted,backend='vlm',service=service)
    with service.registry.conn(write=True) as conn:
        job=conn.execute("SELECT * FROM storage_producer_jobs WHERE kind='parse'").fetchone()
        out=Path(conn.execute('SELECT output_dir FROM literature_parse_runs WHERE id=?',(job['parse_run_id'],)).fetchone()[0])
        if unsafe=='bad_receipt':conn.execute("UPDATE producer_recovery SET sha256=?",('f'*64,))
        if unsafe=='missing_receipt':conn.execute('DELETE FROM producer_recovery')
    assert out.resolve().is_relative_to(service.registry.catalog.parent.resolve())
    (out/'.litlib-producer-owned.json').unlink()
    if unsafe=='foreign_file':(out/'foreign.txt').write_text('preserve this')
    with pytest.raises(StorageError):producers.recover_cloud_producer(job['id'],lambda *a:pytest.fail('unsafe cloud call'),service)
    if unsafe=='foreign_file':assert (out/'foreign.txt').read_text()=='preserve this'
