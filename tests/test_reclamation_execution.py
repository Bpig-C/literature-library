import copy,json
import pytest
from test_reclamation import scenario,NOW
from api.storage.core import StorageError,hash_file
from api.storage.release_control import read,write,REQUIRED_ASSETS
from api.storage.reclamation_execution import ReclamationExecution
from api.storage.backup_catalog import rotate_catalog,discover

def approval(plan):return {'format':'litlib-gc-authorization-v1','execute':True,'target':plan['target'],'plan_sha256':plan['plan_sha256'],'max_objects':len(plan['candidates']),'max_bytes':plan['total_unique_bytes'],'approved_by':'synthetic test authorization','approved_at':NOW,'expires_at':'2026-10-08T00:30:00Z'}

def test_two_physical_rotations_intent_recovery_and_catalog_retry(tmp_path):
    planner,svc,catalog,roots,releases,shared=scenario(tmp_path);execution=ReclamationExecution(planner)
    plan=planner.plan(now=NOW);auth=approval(plan);journal=tmp_path/'round1-journal.json';receipt=tmp_path/'round1-receipt.json'
    def interrupted(point,entry):raise StorageError('network_unavailable','synthetic after unlink')
    with pytest.raises(StorageError):execution.execute(plan,auth,journal,receipt,now=NOW,simulate_local=True,fault=interrupted)
    result=execution.execute(plan,auth,journal,receipt,now=NOW,simulate_local=True)
    assert result['reclaimed_versions']==['1'];assert any(e['phase']=='recovered_absent' for e in result['journal']['events'])
    def catalog_failure(*args):raise StorageError('network_unavailable','synthetic before catalog commit')
    with pytest.raises(StorageError):execution.reconcile(receipt,fault=catalog_failure)
    assert read(catalog)['versions'][0]['state']=='retired'
    execution.reconcile(receipt);assert execution.reconcile(receipt)['idempotent']
    assert read(catalog)['versions'][0]['state']=='reclaimed'
    assert not planner.plan(now=NOW)['candidates']
    # New weekly version genuinely adds a fifth manifest, then retires version 2.
    m=read(tmp_path/'manifest-4.json');m['release_id']='5'
    for name in ('library/literature.sqlite','research/research.sqlite'):
        source=tmp_path/('next-'+name.split('/')[0]);source.write_text('synthetic next '+name)
        sha,size=hash_file(source);entry={'key':svc.ns.key(sha),'sha256':sha,'bytes':size};svc.backend.put_immutable(entry['key'],source);m['essentials'][name]=entry
    p=tmp_path/'manifest-5.json';write(p,m);sha,size=hash_file(p);new={'key':svc.ns.key(sha),'sha256':sha,'bytes':size};svc.backend.put_immutable(new['key'],p)
    c=read(catalog);c['versions'].append({'id':'5','state':'verified','verified_at':'2026-10-05T00:00:00Z','namespace':svc.ns.root,'manifest_key':new['key'],'manifest_sha256':sha,'code_commit':'a'*40,'asset_keys':sorted({e['key'] for e in m['essentials'].values()}|{m['frontend']['key']})});write(catalog,c)
    r=read(roots);r['runtime_release']=new;write(roots,r);rotate_catalog(catalog,[],now=NOW)
    next_plan=planner.plan(now=NOW);assert next_plan['keep_successful']==['3','4','5'];assert len(next_plan['candidates'])==3
    next_receipt=tmp_path/'round2-receipt.json';execution.execute(next_plan,approval(next_plan),tmp_path/'round2-journal.json',next_receipt,now=NOW,simulate_local=True);execution.reconcile(next_receipt)
    assert len(read(catalog)['reclamations'])==2
    assert [v['id'] for v in discover(catalog)]==['5','4','3']
    assert not planner.plan(now=NOW)['candidates']
    for e in [releases[2],releases[3],new]:assert svc.backend.size(e['key'])==e['bytes']
    assert svc.backend.size(shared['key'])==shared['bytes']

def test_explicit_approval_receipt_integrity_and_production_gate(tmp_path):
    planner,svc,catalog,roots,releases,shared=scenario(tmp_path);execution=ReclamationExecution(planner);plan=planner.plan(now=NOW);auth=approval(plan);journal=tmp_path/'journal.json';receipt=tmp_path/'receipt.json'
    bad=copy.deepcopy(auth);bad['max_bytes']+=1
    with pytest.raises(StorageError,match='summary differs'):execution.execute(plan,bad,journal,receipt,now=NOW,simulate_local=True)
    with pytest.raises(StorageError,match='production deletion disabled'):execution.execute(plan,auth,journal,receipt,now=NOW)
    assert not journal.exists()
    r=read(roots);r['pins']=[{'id':'new','reason':'new pin','release':releases[0]}];write(roots,r)
    with pytest.raises(StorageError,match='roots changed'):execution.execute(plan,auth,journal,receipt,now=NOW,simulate_local=True)
    assert all(svc.backend.size(e['key'])==e['bytes'] for e in plan['candidates'])
    r['pins']=[];write(roots,r);execution.execute(plan,auth,journal,receipt,now=NOW,simulate_local=True);execution.reconcile(receipt)
    receipt.write_text(receipt.read_text()+' ')
    with pytest.raises(StorageError,match='receipt changed'):planner.plan(now=NOW)
