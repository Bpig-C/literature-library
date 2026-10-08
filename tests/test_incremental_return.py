"""A -> B -> new code/new parse/new draft -> A2, synthetic objects only."""
import json,subprocess
from pathlib import Path
import pytest
from test_unified_release import release
from api.storage.unified_release import restore_release
from api.storage import release_control as control
from api.storage.backup_catalog import record_verified,discover,select,run_due
from api.storage.core import hash_file,StorageError
from api.storage.runtime import configured_service
from api.storage.producers import parse_source
from api.research_context import ResearchContext
from api.research_service import ResearchService

def test_incremental_roundtrip_preserves_new_code_parse_and_draft(release,tmp_path,monkeypatch):
    root,backend,ns,first,action,old_job,old_snap,config,code,files,frontend=release
    b=tmp_path/'B';e=first['manifest_object']
    restore_release(backend,manifest_key=e['key'],manifest_sha256=e['sha256'],destination=b,namespace=ns,expected_git_url=code['url'])
    subprocess.run(['git','-C',str(b/'app'),'fetch','--quiet','--unshallow','--no-tags',code['url']],check=True)
    for k,v in json.loads((b/'environment.json').read_text()).items():monkeypatch.setenv(k,v)
    service=configured_service()
    def parser(pdf,out,*args,**kwargs):
        (out/'content.md').write_text('# synthetic increment produced on B','utf-8');(out/'content.json').write_text('{"synthetic_increment":2}','utf-8')
        return True,'','synthetic','increment-task'
    job=parse_source(action.source_file_id,parser,force=True,service=service)
    assert job['version']==2
    svc=ResearchService(ResearchContext(b/'data/research',b/'data/research/research.sqlite'))
    snap=svc.import_registered_source(work_id=action.work_id,source_file_id=action.source_file_id,parse_run_id=job['parse_run_id'],version=2)
    assert snap['snapshot_id']!=old_snap['snapshot_id']
    draft=b/'data/research/editing/working.md';draft.write_text('synthetic draft updated on B','utf-8')
    marker=b/'app/docs/synthetic-iteration.md';marker.write_text('Synthetic code iteration on B','utf-8')
    subprocess.run(['git','-C',str(b/'app'),'add','docs/synthetic-iteration.md'],check=True)
    subprocess.run(['git','-C',str(b/'app'),'-c','user.name=Synthetic Test','-c','user.email=synthetic@example.invalid','commit','--quiet','-m','Synthetic iteration'],check=True)
    new_commit=subprocess.check_output(['git','-C',str(b/'app'),'rev-parse','HEAD']).decode().strip();assert new_commit!=code['commit']
    selected={name:{'source':str(b/'data'/name),'sha256':hash_file(b/'data'/name)[0],'bytes':hash_file(b/'data'/name)[1]} for name in files}
    inputs={'format':'litlib-snapshot-input-v1','namespace':ns,'catalog':str(b/'data/library/literature.sqlite'),'research':str(b/'data/research/research.sqlite'),'files':selected,'configuration':config,'code_url':str(b/'app'),'frontend':{'source':str(frontend),'sha256':hash_file(frontend)[0],'bytes':hash_file(frontend)[1]}}
    monkeypatch.setattr(control,'CODE',b/'app');ticket=control.prepare(inputs,10*1024**2)
    stage=tmp_path/'B-new-snapshot';staged=control.stage(ticket,control.digest(ticket),stage,True)
    published=control.publish(stage,staged['manifest_sha256'],backend,staged['maximum_upload_bytes'])
    catalog=tmp_path/'backup-catalog.json';v=record_verified(catalog,stage,published,backend,'2026-10-08T00:00:00Z')
    assert select(catalog,v['id'])['code_commit']==new_commit
    assert run_due(catalog,[],lambda:pytest.fail('Not due'),now='2026-10-09T00:00:00Z')['state']=='not_due'
    def fail():raise StorageError('network_unavailable','synthetic backup failure')
    with pytest.raises(StorageError):run_due(catalog,[],fail,now='2026-10-15T00:00:00Z')
    assert discover(catalog)==[v]
    a2=tmp_path/'A-returned';restore_release(backend,manifest_key=v['manifest_key'],manifest_sha256=v['manifest_sha256'],destination=a2,namespace=ns,expected_git_url=str(b/'app'))
    assert subprocess.check_output(['git','-C',str(a2/'app'),'rev-parse','HEAD']).decode().strip()==new_commit
    assert (a2/'app/docs/synthetic-iteration.md').read_text()=='Synthetic code iteration on B'
    assert (a2/'data/research/editing/working.md').read_text()=='synthetic draft updated on B'
    for k,val in json.loads((a2/'environment.json').read_text()).items():monkeypatch.setenv(k,val)
    returned=configured_service()
    with returned.read(job['parse_run_id'],'md',2) as path:assert path.read_text()=='# synthetic increment produced on B'
    result=ResearchService(ResearchContext(a2/'data/research',a2/'data/research/research.sqlite')).read_text(snap['source_id'],snapshot_id=snap['snapshot_id'])
    assert result['content_text']=='# synthetic increment produced on B'
    assert not list((a2/'data').rglob('*.pdf'))
