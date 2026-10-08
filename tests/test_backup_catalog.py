import pytest
from api.storage.backup_catalog import run_due,read_catalog,select
from api.storage.core import StorageError

def test_rotation_keeps_three_and_purges_only_unreferenced_test_objects(tmp_path):
    from api.storage.backup_catalog import rotate_catalog,discover,purge_isolated_objects
    from api.storage.release_control import write
    from api.storage.backends import LocalObjectBackend
    from api.storage.core import Namespace,hash_file
    backend=LocalObjectBackend(tmp_path/'objects');ns=Namespace('research/agent-loss-of-control/literature/test/rotation/')
    shared=tmp_path/'shared';shared.write_text('synthetic active parse');active=ns.key(hash_file(shared)[0]);backend.put_immutable(active,shared)
    versions=[]
    for i in range(1,5):
        p=tmp_path/f'manifest-{i}';p.write_text(f'synthetic snapshot {i}');sha=hash_file(p)[0];key=ns.key(sha);backend.put_immutable(key,p)
        versions.append({'id':str(i),'state':'verified','verified_at':f'2026-10-0{i}T00:00:00Z','namespace':ns.root,'manifest_sha256':sha,'manifest_key':key,'asset_keys':[active]})
    catalog=tmp_path/'versions.json';write(catalog,{'format':'litlib-backup-catalog-v1','versions':versions,'attempts':[]})
    decision=rotate_catalog(catalog,[active],now='2026-10-08T00:00:00Z')
    assert [v['id'] for v in discover(catalog)]==['4','3','2']
    result=purge_isolated_objects(backend,decision)
    assert result['deleted']==[versions[0]['manifest_key']]
    assert backend.size(active)>0
    for v in versions[1:]:assert backend.size(v['manifest_key'])>0

def test_failed_backup_preserves_successful_catalog(tmp_path):
    catalog=tmp_path/'backups.json'
    def fail():raise StorageError('network_unavailable','synthetic upload failure')
    with pytest.raises(StorageError):run_due(catalog,[],fail,now='2026-10-08T00:00:00Z')
    c=read_catalog(catalog);assert not c['versions'] and c['attempts'][0]['state']=='failed'
    with pytest.raises(StorageError):select(catalog,'unknown')
