import json
import socket
import threading
import time
from contextlib import contextmanager

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from api import remote_access, remote_version, parse_plans
from api.routes import foundation, parse
from api.storage import authority, producers
from api.storage.core import StorageError
from test_foundation_plans import service, runner
from test_remote_version import cli


def test_real_http_cli_plan_execute_status_guide_and_backup(service, tmp_path, monkeypatch, capsys):
    token='test-'+'t'*40
    monkeypatch.setenv('LITLIB_REMOTE_TOKEN',token);monkeypatch.setenv('LITLIB_REMOTE_ENABLED','1')
    monkeypatch.setenv('LITLIB_REMOTE_WRITE_ENABLED','1')
    monkeypatch.setenv('LITLIB_BACKUP_CONTROL',str(tmp_path/'backup-control'))
    monkeypatch.setenv('LITLIB_BACKUP_ADMIN_TOKEN','b'*40)
    monkeypatch.setattr(foundation,'configured_registry',lambda:service.registry)
    monkeypatch.setattr(foundation,'configured_service',lambda:service)
    monkeypatch.setattr(foundation,'enabled',lambda:True)
    original=parse_plans.step
    monkeypatch.setattr(parse_plans,'step',lambda svc,pid,parse:original(svc,pid,parse,count_pages=lambda p:1))
    calls=[];monkeypatch.setattr(parse,'_run_parse',runner(calls))
    monkeypatch.setattr(remote_version,'version_info',lambda:dict(format='litlib-client-capabilities-v1',protocol_version=1,
        capabilities={k:{} for k in ['parse_plans_v1','parse_resolution_v1','backup_jobs_v1','intake_reconcile_v1','foundation_guide_v1']}))
    app=FastAPI();app.add_middleware(remote_access.RemoteAuthentication)
    app.include_router(remote_access.router,prefix='/api');app.include_router(foundation.router,prefix='/api')
    @app.exception_handler(StorageError)
    async def error(request,exc):return JSONResponse({'code':exc.code},status_code=409)
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',lifespan='off'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    try:
        for _ in range(100):
            if server.started:break
            time.sleep(.02)
        assert server.started
        module=cli();base=['--server',f'http://127.0.0.1:{port}'];path=tmp_path/'plan.json'
        assert module.main(base+['parse','plan','--backend','vlm','--purpose','deception','--output',str(path)])==0
        assert path.is_file()
        args=base+['parse','run','--plan',str(path),'--request-id','remote-run','--max-items','1','--max-submissions','1','--execute']
        assert module.main(args)==0
        assert len(calls)==1
        assert module.main(args)==3  # same plan: budget pause, no second submission
        assert len(calls)==1
        assert module.main(base+['backup','request','--request-id','after-intake','--execute'])==0
        assert module.main(base+['backup','status'])==0
        assert module.main(base+['guide'])==0
        failed_path=tmp_path/'failed-plan.json'
        assert module.main(base+['parse','plan','--backend','vlm','--source-file-id','SF2','--output',str(failed_path)])==0
        def interrupted(*args,**kwargs):raise TimeoutError('isolated failure')
        monkeypatch.setattr(parse,'_run_parse',interrupted)
        assert module.main(base+['parse','run','--plan',str(failed_path),'--request-id','remote-failed','--max-items','1','--max-submissions','1','--execute'])==3
        with service.registry.conn(read_only=True) as conn:
            pid=conn.execute("SELECT id FROM parse_plans WHERE request_id='remote-failed'").fetchone()[0]
        abandon=base+['parse','abandon','--plan-id',pid,'--position','0','--reason','Inspected failed runner']
        with pytest.raises(ValueError,match='--execute'):module.main(abandon)
        assert module.main(abandon+['--execute'])==0
        assert parse_plans.status(service.registry,pid)['budget']['reserved_submissions']==1
        assert module.main(base+['parse','continue','--plan-id',pid,'--execute'])==3
        assert 'private-token' not in capsys.readouterr().out
    finally:
        server.should_exit=True;thread.join(10);sock.close()


def test_old_epoch_blocks_plan_writes_before_execution(service,monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv('LITLIB_REMOTE_ENABLED','1');monkeypatch.setenv('LITLIB_REMOTE_TOKEN','t'*40)
    monkeypatch.setenv('LITLIB_REMOTE_WRITE_ENABLED','1');monkeypatch.setenv('LITLIB_STORAGE_MODE','immutable')
    class Frozen:
        @contextmanager
        def write_guard(self):
            raise StorageError('revision_conflict','old epoch');yield
    monkeypatch.setattr(authority,'configured_authority',lambda:Frozen())
    monkeypatch.setattr(foundation,'plan_step',lambda *a:pytest.fail('executed old epoch'))
    app=FastAPI();app.add_middleware(remote_access.RemoteAuthentication);app.include_router(foundation.router,prefix='/api')
    response=TestClient(app).post('/api/parse/plans/PP-old/step',json={},headers={'Authorization':'Bearer '+'t'*40})
    assert response.status_code==409 and response.json()['code']=='revision_conflict'
    response=TestClient(app).post('/api/parse/plans/PP-old/abandon',json={'position':0,'reason':'Inspected','force':True},headers={'Authorization':'Bearer '+'t'*40})
    assert response.status_code==409 and response.json()['code']=='revision_conflict'
