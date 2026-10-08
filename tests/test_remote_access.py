import importlib.util,os,sqlite3
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from api import remote_access
from api.storage.core import Registry,Namespace,StorageError
from api.storage.cache import DiskCache
from api.storage.backends import LocalObjectBackend
from api.storage.service import StorageService

def fixture(tmp_path):
    db=tmp_path/'catalog.sqlite';sqlite3.connect(db).close()
    reg=Registry(db,Namespace('research/agent-loss-of-control/literature/test/remote-continuous/'));reg.initialize()
    return StorageService(reg,LocalObjectBackend(tmp_path/'objects'),DiskCache(tmp_path/'cache',1024**2),tmp_path/'staging',1024**2,spare_bytes=0)

def test_authenticated_fixed_asset_and_no_version_fallback(tmp_path,monkeypatch):
    svc=fixture(tmp_path);source=tmp_path/'source.md';source.write_text('synthetic incremental document','utf-8')
    svc.publish(source,identity='parse-synthetic',role='md',version=2,operation_id='synthetic-2')
    monkeypatch.setattr(remote_access,'configured_service',lambda:svc)
    monkeypatch.setenv('LITLIB_REMOTE_ENABLED','1');monkeypatch.setenv('LITLIB_REMOTE_TOKEN','synthetic-token-'+'x'*32)
    app=FastAPI();app.add_middleware(remote_access.RemoteAuthentication);app.include_router(remote_access.router,prefix='/api')
    @app.exception_handler(StorageError)
    async def error(request,e):
        from fastapi.responses import JSONResponse
        return JSONResponse({'code':e.code},status_code=404)
    c=TestClient(app);url='/api/remote/assets/parse-synthetic?role=md&version=2'
    assert c.get(url).status_code==401
    headers={'Authorization':'Bearer '+os.environ['LITLIB_REMOTE_TOKEN']}
    assert c.get(url,headers=headers).content==source.read_bytes()
    assert c.get(url+'&metadata=true',headers=headers).json()['version']==2
    assert c.get(url.replace('version=2','version=1'),headers=headers).status_code==404
    # Exercise the actual CLI over a loopback socket, with no local client DB.
    import socket,threading,time,uvicorn
    spec=importlib.util.spec_from_file_location('real_cli',Path(__file__).parents[1]/'scripts/litlib_remote.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',lifespan='off'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    try:
        for _ in range(100):
            if server.started:break
            time.sleep(.02)
        assert server.started
        output=tmp_path/'remote-client-document.md'
        assert cli.main(['--server',f'http://127.0.0.1:{port}','asset','parse-synthetic','--role','md','--version','2','--max-bytes','4096','--output',str(output)])==0
        assert output.read_bytes()==source.read_bytes()
        with pytest.raises(ValueError):cli.main(['--server',f'http://127.0.0.1:{port}','asset','parse-synthetic','--role','md','--version','2','--max-bytes','1'])
    finally:
        server.should_exit=True;thread.join(5);sock.close()
    assert not thread.is_alive()
    monkeypatch.delenv('LITLIB_REMOTE_TOKEN');assert c.get(url,headers=headers).status_code==503

def test_daily_publish_failure_retains_pending_then_resume(tmp_path):
    svc=fixture(tmp_path);source=tmp_path/'new.md';source.write_text('new synthetic data','utf-8')
    backend=svc.backend
    class Offline:
        def size(self,key):raise StorageError('network_unavailable','synthetic offline')
    svc.backend=Offline()
    with pytest.raises(StorageError):svc.publish(source,identity='new-parse',role='md',version=1,operation_id='new-operation')
    with svc.registry.conn() as c:
        row=c.execute('SELECT * FROM storage_operations').fetchone();assert row['state']=='staged' and row['error_code']=='network_unavailable'
        assert Path(row['pending']).is_file()
    assert source.exists()
    svc.backend=backend;result=svc.resume('new-operation');assert result['version']==1
    assert svc.resume('new-operation')==result
    with svc.read('new-parse','md',1) as p:assert p.read_bytes()==source.read_bytes()
    assert source.exists() and not list((tmp_path/'staging').glob('*.pending'))

def test_remote_client_refuses_non_tls_and_redirect():
    spec=importlib.util.spec_from_file_location('client',Path(__file__).parents[1]/'scripts/litlib_remote.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    assert m.base_url('https://example.com')=='https://example.com'
    with pytest.raises(ValueError):m.base_url('http://example.com')
    with pytest.raises(ValueError):m.base_url('https://user:secret@example.com')
    with pytest.raises(ValueError):m.NoRedirect().redirect_request(None,None,None,None,None,None)
