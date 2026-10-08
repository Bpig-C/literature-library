from api.storage.snapshot_policy import plan
from api.storage.core import Namespace

def test_weekly_success_retention_protects_active_and_retained_assets():
    ns=Namespace('research/agent-loss-of-control/literature/test/policy/')
    def key(i):return ns.key(str(i)*64)
    versions=[{'id':str(i),'state':'verified','verified_at':f'2026-10-0{i}T00:00:00Z','namespace':ns.root,'manifest_sha256':str(i)*64,'manifest_key':key(i),'asset_keys':[key(9),key(5+i)]} for i in range(1,5)]
    versions.append({'id':'failed-new','state':'failed'})
    p=plan(versions,[key(6)],now='2026-10-08T00:00:00Z')
    assert p['keep']==['4','3','2'] and p['retire_snapshot_records']==['1']
    assert key(9) in p['protected_keys'] and key(6) not in p['unreferenced_candidates']
    assert key(1) in p['unreferenced_candidates'] and p['backup_due'] is False
    assert p['failed_versions_count']==1 and p['deletion_performed'] is False
    assert plan(versions,[],now='2026-10-11T00:00:00Z')['backup_due'] is True

def test_failed_initial_backup_does_not_create_a_successful_version():
    p=plan([{'id':'failed','state':'failed'}],[],now='2026-10-08T00:00:00+08:00')
    assert p['backup_due'] and not p['keep'] and not p['retire_snapshot_records']
