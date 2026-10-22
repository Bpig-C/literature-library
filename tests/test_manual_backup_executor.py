import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest

from api.storage import manual_backup as backup
from api.storage.core import StorageError, hash_file


@pytest.fixture
def host(tmp_path,monkeypatch):
    from scripts import snapshot_inputs
    slot=tmp_path/'slots'/'runtime';(slot/'code').mkdir(parents=True)
    library=slot/'data/library';research=slot/'data/research';library.mkdir(parents=True);research.mkdir()
    with sqlite3.connect(library/'literature.sqlite') as conn:
        conn.executescript('CREATE TABLE literature_parse_runs(status); CREATE TABLE storage_operations(state); CREATE TABLE storage_producer_jobs(state);')
    sqlite3.connect(research/'research.sqlite').close()
    env={'LITLIB_DB_PATH':str(library/'literature.sqlite'),'LITLIB_RESEARCH_DB':str(research/'research.sqlite'),
         'LITLIB_STORAGE_ROOT':'research/agent-loss-of-control/literature/test/backup-worker/'}
    (slot/'environment.json').write_text(json.dumps(env))
    manifest={'namespace':env['LITLIB_STORAGE_ROOT'],'configuration':{},'code':{'url':'https://github.com/example/test'},'essentials':{},'frontend':{}}
    (slot/'release-manifest.json').write_text(json.dumps(manifest))
    live={'code_root':str(slot/'code'),'code_commit':'a'*40,'manifest_sha256':hash_file(slot/'release-manifest.json')[0],
          'verify':{'ok':True},'read_only':False,'remote_writes_enabled':True,'plan':{'db_path':env['LITLIB_RESEARCH_DB']}}
    control=tmp_path/'control';control.mkdir();monkeypatch.setenv('LITLIB_BACKUP_CONTROL',str(control))
    monkeypatch.setenv('LITLIB_REMOTE_TOKEN','t'*40);monkeypatch.setenv('LITLIB_AUTHORITY_TOKEN','o'*40)
    from io import BytesIO
    class Response(BytesIO):
        def __enter__(self):return self
        def __exit__(self,*a):self.close()
    class Opener:
        def open(self,*a,**kw):return Response(json.dumps(live).encode())
    monkeypatch.setattr(backup,'build_opener',lambda *a:Opener())
    monkeypatch.setattr(backup.subprocess,'check_output',lambda *a,**k:('a'*40).encode())
    events=[]
    class Authority:
        marker=tmp_path/'absent-marker'
        def __init__(self,*a):pass
        def check_remote(self):events.append('authority')
        @contextmanager
        def write_guard(self):events.append('guard_enter');yield;events.append('guard_exit')
    monkeypatch.setattr(backup,'Authority',Authority);monkeypatch.setattr(backup,'oss_from_environment',lambda:object())
    monkeypatch.setattr(snapshot_inputs,'refresh',lambda *a:dict(namespace=env['LITLIB_STORAGE_ROOT'],catalog=env['LITLIB_DB_PATH']))
    monkeypatch.setattr(backup,'prepare',lambda *a:{'payload_bytes_estimate':1})
    monkeypatch.setattr(backup,'stage',lambda *a:{'manifest_sha256':'d'*64,'maximum_upload_bytes':1})
    monkeypatch.setattr(backup,'publish',lambda *a:{'state':'published'})
    version={'id':'new','state':'verified','verified_at':'2026-10-22T00:00:00Z','code_commit':'a'*40,'manifest_sha256':'d'*64}
    monkeypatch.setattr(backup,'record_verified',lambda *a:version)
    monkeypatch.setattr(backup,'run_due',lambda catalog,active,fn,**kw:{'state':'backed_up','version':fn()})
    monkeypatch.setattr(backup,'bindings',lambda *a:[])
    monkeypatch.setattr(backup.subprocess,'run',lambda argv,**kw:events.append(argv[0]))
    cfg={'server':'http://127.0.0.1:1','releases_root':str(slot.parent),'epoch':6,'max_snapshot_bytes':1000,
         'frontend_zip':str(tmp_path/'frontend.zip'),'maintenance_enter':['enter'],'maintenance_verify_stopped':['stopped'],'maintenance_exit':['exit']}
    return cfg,events,control,live


def test_executor_orders_maintenance_and_restores_same_writer(host):
    cfg,events,control,live=host
    result=backup.execute(cfg,'BK-test')
    assert result['id']=='new'
    assert events.index('enter')<events.index('guard_exit')<events.index('stopped')<events.index('exit')
    assert (control/'receipts/BK-test/service-restored.json').is_file()


def test_stop_verification_failure_still_restores_service(host,monkeypatch):
    cfg,events,control,live=host
    def command(argv,**kw):
        events.append(argv[0])
        if argv[0]=='stopped':raise RuntimeError('stop verification failed')
    monkeypatch.setattr(backup.subprocess,'run',command)
    with pytest.raises(RuntimeError):backup.execute(cfg,'BK-stop-failed')
    assert 'exit' in events


def test_preview_never_enters_maintenance(host):
    cfg,events,control,live=host
    assert backup.execute(cfg,'preview',preview=True)['executed'] is False
    assert 'enter' not in events and not (control/'receipts').exists()
