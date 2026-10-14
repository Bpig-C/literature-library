import importlib.util
import json
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from api import remote_access, remote_version


def cli():
    spec=importlib.util.spec_from_file_location('version_cli',Path(__file__).parents[1]/'scripts/litlib_remote.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


class Reply(BytesIO):
    def __enter__(self):return self
    def __exit__(self,*args):self.close()


class Opener:
    def __init__(self,result):self.result=result
    def open(self,request,timeout):
        if isinstance(self.result,Exception):raise self.result
        return Reply(json.dumps(self.result).encode())


def test_authenticated_version_has_capabilities_and_no_business_access(monkeypatch):
    monkeypatch.setenv('LITLIB_REMOTE_ENABLED','1');monkeypatch.setenv('LITLIB_REMOTE_TOKEN','synthetic-'+'x'*32)
    app=FastAPI();app.add_middleware(remote_access.RemoteAuthentication);app.include_router(remote_access.router,prefix='/api')
    client=TestClient(app)
    assert client.get('/api/remote/version').status_code==401
    response=client.get('/api/remote/version',headers={'Authorization':'Bearer synthetic-'+'x'*32})
    assert response.status_code==200
    data=response.json()
    assert data['capabilities']['ingest_purpose_v1']['required_fields']==['purpose']
    assert data['client']['sha256']
    assert response.headers['cache-control']=='no-store'


def test_cli_detects_commit_change_and_capability_mismatch():
    module=cli()
    server={'format':'litlib-client-capabilities-v1','protocol_version':1,'code_commit':'a'*40,'capabilities':{'ingest_purpose_v1':{}}}
    result,code=module.check_version(Opener(server),'https://example.com',{},1,expected_commit='a'*40,required=['ingest_purpose_v1'])
    assert code==0 and result['compatible']
    assert module.check_version(Opener(server),'https://example.com',{},1,expected_commit='b'*40)[1]==2
    assert module.check_version(Opener(server),'https://example.com',{},1,required=['future_protocol'])[1]==2
    server['protocol_version']=2
    assert module.check_version(Opener(server),'https://example.com',{},1)[1]==2


def test_legacy_server_is_explicitly_unknown_and_auth_failure_not_hidden():
    module=cli()
    missing=HTTPError('https://example.com',404,'missing',{},None)
    result,code=module.check_version(Opener(missing),'https://example.com',{},1)
    assert code==2 and not result['compatible']
    with pytest.raises(HTTPError):module.check_version(Opener(HTTPError('https://example.com',401,'auth',{},None)),'https://example.com',{},1)


def test_dirty_code_never_advertises_a_pinned_cli(monkeypatch):
    def output(command,**kwargs):return b'a'*40 if command[1]=='rev-parse' else b' M api/remote_version.py'
    monkeypatch.setattr(remote_version.subprocess,'check_output',output)
    result=remote_version.version_info()
    assert result['code_dirty'] and result['client']['download_url'] is None


def test_cli_command_reports_compatibility_without_downloading(monkeypatch,capsys):
    module=cli();monkeypatch.setenv('LITLIB_REMOTE_TOKEN','synthetic-'+'x'*32)
    monkeypatch.setattr(module,'build_opener',lambda *args:Opener({'format':'litlib-client-capabilities-v1','protocol_version':1,'capabilities':{'ingest_purpose_v1':{}}}))
    assert module.main(['--server','https://example.com','check-version','--require-capability','ingest_purpose_v1'])==0
    assert json.loads(capsys.readouterr().out)['compatible']


def test_private_ca_is_optional_but_invalid_explicit_path_rejected(tmp_path):
    module=cli()
    with pytest.raises(ValueError,match='CA certificate'):module.tls_context(tmp_path/'missing.crt')
