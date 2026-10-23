from scripts.restored_runtime import read_only_cli


def test_restored_environment_preserves_host_controls_but_replaces_data_roots(tmp_path,monkeypatch):
    import json
    import os
    from scripts import restored_runtime as runtime
    slot=tmp_path/'slot';code=slot/'app';code.mkdir(parents=True)
    monkeypatch.setattr(runtime,'CODE',code)
    expected={'LITLIB_LIBRARY_ROOT':slot/'data/library','LITLIB_DB_PATH':slot/'data/library/literature.sqlite',
              'LITLIB_RESEARCH_ROOT':slot/'data/research','LITLIB_RESEARCH_DB':slot/'data/research/research.sqlite',
              'LITLIB_RESEARCH_ASSETS_ROOT':slot/'data/research/assets','LITLIB_RUNTIME_MATERIALS_ROOT':slot/'data/library/docs',
              'LITLIB_STORAGE_CACHE':slot/'cache','LITLIB_STORAGE_STAGING':slot/'staging'}
    env={k:str(v) for k,v in expected.items()}
    env.update(LITLIB_STORAGE_MODE='immutable',LITLIB_STORAGE_ROOT='research/agent-loss-of-control/literature/test/host-controls/',
               LITLIB_STORAGE_BACKEND='local',LITLIB_STORAGE_LOCAL_OBJECTS=str(tmp_path/'objects'))
    (slot/'environment.json').write_text(json.dumps(env),'utf-8')
    (slot/'release-manifest.json').write_text(json.dumps({'namespace':env['LITLIB_STORAGE_ROOT']}),'utf-8')
    controls={'LITLIB_ASYNC_PARSE_ENABLED':'1','LITLIB_PARSE_UPLOAD_KEY':'synthetic-key',
              'LITLIB_BACKUP_CONTROL':str(tmp_path/'control'),'LITLIB_BACKUP_ADMIN_TOKEN':'synthetic-admin',
              'LITLIB_AUTHORITY_EPOCH':'7','LITLIB_AUTHORITY_TOKEN':'synthetic-owner'}
    for name,value in controls.items():monkeypatch.setenv(name,value)
    for name in env:monkeypatch.setenv(name,'inherited-value')
    monkeypatch.setenv('LITLIB_UNREVIEWED_CONTROL','discard')
    monkeypatch.setenv('LITLIB_RESEARCH_READ_ONLY','0')
    runtime.environment(slot)
    assert all(os.environ[name]==value for name,value in controls.items())
    assert all(os.environ[name]==value for name,value in env.items())
    assert 'LITLIB_UNREVIEWED_CONTROL' not in os.environ
    assert os.environ['LITLIB_RESEARCH_READ_ONLY']=='1'

def test_read_argument_cannot_disguise_a_mutating_subcommand():
    assert read_only_cli('litlib.py',['--library-root','/explicit','read','RS-synthetic'])
    assert not read_only_cli('litlib.py',['--library-root','/explicit','feedback-open','--detail','read'])
    assert not read_only_cli('storage_assets.py',['register','--source','read'])
    assert not read_only_cli('literature_ingest.py',['--library-root','/explicit'])
    assert read_only_cli('storage_assets.py',['check'])
    assert read_only_cli('storage_backup.py',['--catalog','/explicit/backup.json','versions'])
    assert not read_only_cli('storage_backup.py',['--catalog','/explicit/backup.json','tick','--inputs','versions'])
    assert read_only_cli('storage_authority.py',['status'])
    assert not read_only_cli('storage_authority.py',['freeze'])
    assert read_only_cli('storage_reclamation.py',['--catalog','/explicit/backups.json','--roots','/explicit/roots.json','--max-verify-bytes','1024','plan'])
    assert not read_only_cli('storage_reclamation.py',['--catalog','/explicit/backups.json','delete'])
