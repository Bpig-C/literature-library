import json,zipfile
from pathlib import Path
import pytest
from api.storage.core import StorageError,hash_file,file_lock
from api.storage.release_control import write,REQUIRED_ASSETS
from api.storage.reclamation import ReclamationPlanner
from api.storage.authority import Authority
from api.storage.backup_catalog import rotate_catalog,run_due,discover
from test_remote_access import fixture

NOW='2026-10-08T00:00:00Z'

def scenario(tmp_path):
    svc=fixture(tmp_path);ns=svc.ns
    def put(label):
        p=tmp_path/(label+'.blob');p.write_text('synthetic '+label,encoding='utf-8');sha,size=hash_file(p);e={'key':ns.key(sha),'sha256':sha,'bytes':size};svc.backend.put_immutable(e['key'],p);return e
    shared=put('shared');versions=[];descriptors=[]
    for i in range(1,5):
        essential={name:shared for name in REQUIRED_ASSETS}
        essential.update({'library/literature.sqlite':put('catalog-'+str(i)),'research/research.sqlite':put('research-'+str(i))})
        m={'format':'litlib-unified-release-v1','namespace':ns.root,'release_id':str(i),'configuration':{'storage_namespace':ns.root},'code':{'commit':'a'*40},'essentials':essential,'frontend':shared,'asset_index':{'bindings':[]}}
        p=tmp_path/f'manifest-{i}.json';write(p,m);sha,size=hash_file(p);e={'key':ns.key(sha),'sha256':sha,'bytes':size};svc.backend.put_immutable(e['key'],p);descriptors.append(e)
        versions.append({'id':str(i),'state':'verified','verified_at':f'2026-10-0{i}T00:00:00Z','namespace':ns.root,'manifest_key':e['key'],'manifest_sha256':sha,'code_commit':'a'*40,'asset_keys':sorted({v['key'] for v in essential.values()}|{shared['key']})})
    catalog=tmp_path/'backups.json';write(catalog,{'format':'litlib-backup-catalog-v1','versions':versions,'attempts':[]});rotate_catalog(catalog,[],now=NOW)
    stages=tmp_path/'snapshot-stages';stages.mkdir()
    roots=tmp_path/'roots.json';write(roots,{'format':'litlib-gc-roots-v1','namespace':ns.root,'runtime_release':descriptors[-1],'handover_releases':[],'pins':[],'stage_parent':str(stages),'snapshot_stages':[],'writers_quiescent':True})
    authority=Authority(svc.backend,ns.root,'synthetic-gc-owner-'+'x'*32,0,tmp_path/'authority');authority.initialize()
    planner=ReclamationPlanner(svc,catalog,roots,authority,max_verify_bytes=1024**2)
    return planner,svc,catalog,roots,descriptors,shared

def test_exact_three_shared_parent_pending_and_pins(tmp_path):
    planner,svc,catalog,roots,releases,shared=scenario(tmp_path)
    p=tmp_path/'member.zip'
    with zipfile.ZipFile(p,'w') as z:z.writestr('content.md','synthetic current member')
    svc.publish(p,identity='active',role='md',version=1,operation_id='active-member',member='content.md')
    plan=planner.plan(now=NOW);assert plan['keep_successful']==['2','3','4'];assert len(plan['candidates'])==3
    assert shared['key'] in plan['protected']
    assert svc.ns.key(hash_file(p)[0]) in plan['protected']
    # A not-yet-registered object protects even a retired manifest's DB blob.
    old=json.loads((tmp_path/'manifest-1.json').read_text('utf-8'))['essentials']['library/literature.sqlite']
    old_source=next(q for q in tmp_path.glob('*.blob') if hash_file(q)[0]==old['sha256'])
    with pytest.raises(StorageError):svc.publish(old_source,identity='pending',role='pdf',version=1,operation_id='pending-upload',fail_after_upload=True)
    second=planner.plan(now=NOW);assert old['key'] in second['protected'];assert len(second['candidates'])==2
    r=json.loads(roots.read_text('utf-8'));r['pins']=[{'id':'restore-hold','reason':'requested restore','release':releases[0]}];write(roots,r)
    held=planner.plan(now=NOW);assert not held['candidates'];assert held['physical_limit_blockers'][0]['version']=='1'
    assert 'pin:restore-hold:requested restore' in held['physical_limit_blockers'][0]['reasons']
    r['pins']=[];r['runtime_release']=releases[0];write(roots,r)
    runtime=planner.plan(now=NOW);assert not runtime['candidates'];assert 'current_runtime' in runtime['physical_limit_blockers'][0]['reasons']
    r['runtime_release']=releases[-1]
    r['pins']=[];r['handover_releases']=[releases[0]];write(roots,r)
    assert not planner.plan(now=NOW)['candidates']
    r['handover_releases']=[]
    stage=Path(r['stage_parent'])/'pending-snapshot';stage.mkdir()
    m=json.loads((tmp_path/'manifest-1.json').read_text('utf-8'))
    for name,e in m['essentials'].items():
        f=stage/name;f.parent.mkdir(parents=True,exist_ok=True);svc.backend.download(e['key'],f,max_bytes=e['bytes'])
    svc.backend.download(shared['key'],stage/'frontend.zip',max_bytes=shared['bytes'])
    (stage/'release.json').write_bytes((tmp_path/'manifest-1.json').read_bytes())
    write(stage/'stage-receipt.json',{'manifest_sha256':releases[0]['sha256']})
    write(stage/'upload-journal.json',{'manifest_sha256':releases[0]['sha256'],'state':'publishing','verified':[]})
    r['snapshot_stages']=[{'id':'1','state':'publishing','path':str(stage)}];write(roots,r)
    pending=planner.plan(now=NOW);assert not pending['candidates'];assert 'snapshot_retry:1' in pending['protected'][releases[0]['key']]
    svc.backend.size(shared['key'])

def test_root_drift_concurrency_and_unknown_inventory_abort(tmp_path):
    planner,svc,catalog,roots,releases,shared=scenario(tmp_path);plan=planner.plan(now=NOW)
    with planner.authority.write_guard():
        with pytest.raises(StorageError,match='busy'):planner.plan(now=NOW)
    with file_lock(catalog.with_suffix('.scheduler.lock'),timeout=0):
        with pytest.raises(StorageError,match='busy'):planner.plan(now=NOW)
    r=json.loads(roots.read_text('utf-8'));r['pins']=[{'id':'new-pin','reason':'new reader','release':releases[0]}];write(roots,r)
    with planner.guard(),pytest.raises(StorageError,match='roots changed'):planner.validate(plan,now=NOW)
    r['pins']=[];write(roots,r)
    old=json.loads((tmp_path/'manifest-1.json').read_text())['essentials']['library/literature.sqlite']
    source=next(q for q in tmp_path.glob('*.blob') if hash_file(q)[0]==old['sha256'])
    svc.publish(source,identity='new-active-root',role='pdf',version=1,operation_id='new-active-root')
    with planner.guard(),pytest.raises(StorageError,match='roots changed'):planner.validate(plan,now=NOW)
    (Path(r['stage_parent'])/'unknown').mkdir()
    with pytest.raises(StorageError,match='inventory incomplete'):planner.plan(now=NOW)
    assert all(svc.backend.size(e['key'])==e['bytes'] for e in plan['candidates'])
    (Path(r['stage_parent'])/'unknown').rmdir()
    with svc.registry.conn(write=True) as c:c.execute("INSERT INTO storage_producer_jobs(id,kind,source_file_id,version,state) VALUES('synthetic-incomplete','parse','synthetic',1,'preparing')")
    with pytest.raises(StorageError,match='unknown reference closure'):planner.plan(now=NOW)

def test_failure_intent_resume_and_changed_object_preserved(tmp_path):
    planner,svc,catalog,roots,releases,shared=scenario(tmp_path);plan=planner.plan(now=NOW);journal=tmp_path/'gc-journal.json'
    candidate=next(e for e in plan['candidates'] if e['key'] not in plan['manifest_cache']);target=svc.backend.path(candidate['key']);original=target.read_bytes()
    target.write_bytes(b'x'*len(original))
    with planner.guard(),pytest.raises(StorageError,match='SHA/size changed'):planner.validate(plan,now=NOW)
    assert target.is_file();target.write_bytes(original)
    with pytest.raises(StorageError,match='Synthetic interruption'):planner.execute_local(plan,journal,now=NOW,fail_after_delete=True)
    j=json.loads(journal.read_text());assert j['pending'] and not j['deleted']
    result=planner.execute_local(plan,journal,now=NOW);assert result['state']=='completed';assert len(result['deleted'])==3
    assert planner.execute_local(plan,journal,now=NOW)==result
    for e in releases[1:]:assert svc.backend.size(e['key'])==e['bytes']
    assert svc.backend.size(shared['key'])==shared['bytes']
    from api.storage.backends import OSSBackend
    planner.backend=OSSBackend(None,'synthetic-not-real')
    with pytest.raises(StorageError,match='No production/OSS deletion'):planner.execute_local(plan,journal,now=NOW)

def test_failed_backup_no_retirement_and_mid_validation_drift(tmp_path):
    planner,svc,catalog,roots,releases,shared=scenario(tmp_path)
    before=[v['id'] for v in discover(catalog)]
    def fail():raise StorageError('network_unavailable','synthetic backup failure')
    with pytest.raises(StorageError):run_due(catalog,[],fail,now='2026-10-15T00:00:00Z')
    assert [v['id'] for v in discover(catalog)]==before
    plan=planner.plan(now=NOW);download=svc.backend.download;changed=False
    def drift(key,destination,max_bytes=None):
        nonlocal changed
        download(key,destination,max_bytes)
        if key in {e['key'] for e in plan['candidates']} and not changed:
            r=json.loads(roots.read_text());r['pins']=[{'id':'concurrent-pin','reason':'restore in progress','release':releases[0]}];write(roots,r);changed=True
    svc.backend.download=drift
    with pytest.raises(StorageError,match='Roots changed during planning'):planner.plan(now=NOW)
    svc.backend.download=download;r=json.loads(roots.read_text());r['pins']=[];write(roots,r);changed=False;svc.backend.download=drift
    with planner.guard(),pytest.raises(StorageError,match='[Rr]oots changed'):planner.validate(plan,now=NOW)
    assert all(svc.backend.size(e['key'])==e['bytes'] for e in plan['candidates'])
