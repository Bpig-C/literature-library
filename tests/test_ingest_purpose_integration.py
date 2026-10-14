"""Exercise actual upload/execute transactions and request retries."""
import sqlite3
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from api.routes import ingest as route
from api.ingest_notes import query
from scripts import literature_ingest as core


@pytest.fixture
def isolated(tmp_path,monkeypatch):
    with sqlite3.connect(tmp_path/'literature.sqlite') as conn:
        core.ensure_core_schema(conn)
    monkeypatch.setattr(route,'LIBRARY_ROOT',tmp_path)
    app=FastAPI();app.include_router(route.router,prefix='/api')
    return tmp_path,TestClient(app)


def upload(client,purpose='review',rid='upload-1',data=b'%PDF synthetic work'):
    return client.post('/api/ingest/upload',data={'purpose':purpose,'request_id':rid},files={'files':('work.pdf',data)})


def test_missing_and_whitespace_have_no_files_or_notes(isolated):
    root,client=isolated
    assert client.post('/api/ingest/upload',files={'files':('work.pdf',b'x')}).status_code==422
    assert upload(client,'   ').status_code==400
    assert not (root/'_inbox').exists()
    assert client.post('/api/ingest/execute',json={}).status_code==422
    with sqlite3.connect(root/'literature.sqlite') as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='ingest_notes'").fetchone()


def test_upload_repeat_conflicts_and_distinct_purposes(isolated):
    root,client=isolated
    first=upload(client);assert first.status_code==200,first.text
    wid=first.json()['purpose_notes']['items'][0]['work_id']
    assert upload(client).json()['purpose_notes']['purposes_already_existed']==1
    assert upload(client,'case study','upload-2').json()['purpose_notes']['purposes_saved']==1
    assert upload(client,'changed').status_code==409
    assert upload(client,data=b'%PDF different').status_code==409
    with sqlite3.connect(root/'literature.sqlite') as conn:
        assert [conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ('works','source_files','literature_parse_runs','ingest_notes')]==[1,1,1,2]
    assert len(query(root,wid))==2


def test_query_never_migrates_and_append_checks_source(isolated):
    root,client=isolated
    assert client.get('/api/works/unknown/ingest-notes').json()['notes']==[]
    with sqlite3.connect(root/'literature.sqlite') as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='ingest_notes'").fetchone()
    wid=upload(client).json()['purpose_notes']['items'][0]['work_id']
    url=f'/api/works/{wid}/ingest-notes'
    assert client.post(url,json={'purpose':'text','source_file_id':'SF-wrong'}).status_code==400
    response=client.post(url,json={'purpose':'text','request_id':'direct-1'})
    assert response.status_code==200,response.text
    assert client.post(url,json={'purpose':'changed','request_id':'direct-1'}).status_code==409
    assert client.get(url+'?limit=0').status_code==422


def test_purpose_failure_rolls_back_catalog_rows(isolated,monkeypatch):
    root,client=isolated
    def fail(*args,**kwargs):raise RuntimeError('synthetic purpose failure')
    monkeypatch.setattr(core,'write_notes',fail)
    response=upload(client);assert response.status_code==500
    with sqlite3.connect(root/'literature.sqlite') as conn:
        assert conn.execute('SELECT COUNT(*) FROM works').fetchone()[0]==0
        assert conn.execute('SELECT COUNT(*) FROM source_files').fetchone()[0]==0
    assert (root/'_inbox/work.pdf').exists()


def test_execute_retry_after_inputs_archived_and_selection(isolated):
    root,client=isolated
    inbox=root/'_inbox';inbox.mkdir()
    (inbox/'one.pdf').write_bytes(b'%PDF first')
    (inbox/'two.pdf').write_bytes(b'%PDF second')
    plan=client.get('/api/ingest/plan').json()
    body={'purpose':'batch','request_id':'execute-1','file_ids':[plan['ingests'][0]['content_sha256']]}
    response=client.post('/api/ingest/execute',json=body);assert response.status_code==200,response.text
    assert response.json()['summary']['ingests']==1
    retry=client.post('/api/ingest/execute',json=body)
    assert retry.status_code==200,retry.text
    assert retry.json()['replayed']
    # Finish the second file separately, leaving an empty inbox for replay.
    assert client.post('/api/ingest/execute',json={'purpose':'second','request_id':'execute-2'}).status_code==200
    response=client.post('/api/ingest/execute',json={'purpose':'batch','request_id':'execute-1'})
    assert response.status_code==200,response.text
    assert response.json()['replayed']


def test_cli_missing_purpose_before_plan_or_write(tmp_path):
    absent=tmp_path/'absent'
    assert core.main(['--library-root',str(absent),'--execute'])==1
    assert not absent.exists()
    import subprocess,sys
    result=subprocess.run([sys.executable,core.__file__, '--library-root',str(absent),'--execute'],capture_output=True,text=True)
    assert result.returncode==1
    assert 'purpose is required' in result.stderr
    assert not absent.exists()
    assert core.main(['--library-root',str(absent)])==0
    assert not absent.exists()


def test_remote_readonly_blocks_note_writes(isolated,monkeypatch):
    from api.remote_access import RemoteAuthentication
    root,client=isolated
    monkeypatch.setenv('LITLIB_REMOTE_ENABLED','1');monkeypatch.setenv('LITLIB_REMOTE_TOKEN','synthetic-token-'+'x'*32)
    monkeypatch.delenv('LITLIB_REMOTE_WRITE_ENABLED',raising=False)
    client.app.add_middleware(RemoteAuthentication)
    headers={'Authorization':'Bearer '+'synthetic-token-'+'x'*32}
    assert client.post('/api/works/W-test/ingest-notes',json={'purpose':'text'},headers=headers).status_code==403
    assert client.get('/api/works/W-test/ingest-notes',headers=headers).status_code==200


def test_core_and_collector_reject_blank_before_work(isolated):
    from collector.ingest_bridge import promote
    root,client=isolated
    plan=core.build_ingest_plan(root)
    with pytest.raises(ValueError,match='purpose is required'):
        core.execute_plan(plan,purpose=' ')
    with pytest.raises(ValueError,match='purpose is required'):
        promote('IC-absent',library_root=root,purpose=' ')
    assert not (root/'_inbox').exists()


def test_collect_promotion_requires_purpose_before_candidate_db(isolated):
    from api.routes import intake
    root,client=isolated
    client.app.include_router(intake.router,prefix='/api')
    assert client.post('/api/intake/promote',json={'ids':['IC-absent']}).status_code==422
    assert client.post('/api/intake/promote',json={'ids':['IC-absent'],'purpose':' '}).status_code==400


def test_already_promoted_candidate_purpose_conflict_is_per_item(isolated,monkeypatch):
    from api.routes import intake
    from api.ingest_notes import append
    root,client=isolated
    wid=upload(client).json()['purpose_notes']['items'][0]['work_id']
    append(root,wid,'original purpose','batch:IC-test')
    with sqlite3.connect(root/'literature.sqlite') as conn:
        conn.execute('CREATE TABLE intake_candidates(id TEXT,status TEXT,review_status TEXT,resolution TEXT,matched_work_id TEXT,ingested_work_id TEXT,local_pdf_path TEXT)')
        conn.execute("INSERT INTO intake_candidates VALUES ('IC-test','ingested','approved','new',NULL,?,NULL)",(wid,))
    def connect():
        conn=sqlite3.connect(root/'literature.sqlite');conn.row_factory=sqlite3.Row;return conn
    monkeypatch.setattr(intake,'get_conn',connect)
    monkeypatch.setattr(intake,'LIBRARY_ROOT',root)
    result=intake.promote_candidates(intake.PromoteBody(ids=['IC-test'],purpose='changed',request_id='batch'))
    assert not result['promoted']
    assert result['failed'][0]['id']=='IC-test'
    assert 'different purpose' in result['failed'][0]['error']
