import json
import hashlib
from pathlib import Path
from scripts.target_preflight import validate

def test_target_config_rejects_placeholders_credentials_and_unsafe_controls(tmp_path):
    config=json.loads((Path(__file__).parents[1]/'deploy/target-config.example.json').read_text('utf-8'))
    assert not validate(config)['ok']
    config.update(server_url='https://library.example.com',code_commit='a'*40,manifest_sha256='b'*64,manifest_key=config['namespace']+'objects/sha256/bb/'+'b'*64,maintenance_adapter_sha256='c'*64)
    for key in ('restored_root','backup_catalog','backup_inputs','stage_parent','maintenance_adapter'):config[key]=str(tmp_path/key)
    assert validate(config)['ok']
    config['access_key_secret']='synthetic';assert not validate(config)['ok'];del config['access_key_secret']
    config['backup_catalog']=str(tmp_path/'restored_root/catalog.json');assert not validate(config)['ok']
    config['backup_catalog']=str(tmp_path/'backup_catalog')
    root=Path(config['restored_root']);root.mkdir()
    manifest=root/'release-manifest.json';manifest.write_text(json.dumps({'namespace':config['namespace'],'code':{'commit':config['code_commit']}}),encoding='utf-8')
    config['manifest_sha256']=hashlib.sha256(manifest.read_bytes()).hexdigest()
    config['manifest_key']=config['namespace']+'objects/sha256/'+config['manifest_sha256'][:2]+'/'+config['manifest_sha256']
    for key in ('backup_inputs','maintenance_adapter'):Path(config[key]).write_text('{}',encoding='utf-8')
    config['maintenance_adapter_sha256']=hashlib.sha256(Path(config['maintenance_adapter']).read_bytes()).hexdigest()
    assert not validate(config,check_files=True)['ok']  # Empty/stale inputs fail before maintenance.
    env={'LITLIB_STORAGE_ROOT':config['namespace'],'LITLIB_DB_PATH':str(root/'data/library/literature.sqlite'),'LITLIB_RESEARCH_DB':str(root/'data/research/research.sqlite')}
    (root/'environment.json').write_text(json.dumps(env),encoding='utf-8')
    Path(config['backup_inputs']).write_text(json.dumps({'source_root':str(root),'namespace':config['namespace'],'catalog':env['LITLIB_DB_PATH'],'research':env['LITLIB_RESEARCH_DB'],'files':{}}),encoding='utf-8')
    assert validate(config,check_files=True)['ok']
    config['code_commit']='d'*40;assert not validate(config,check_files=True)['ok']
