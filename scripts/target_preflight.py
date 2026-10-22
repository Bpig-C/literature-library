"""Offline target configuration validation. Never install, stop or upload."""
import argparse,json,re,sys
from pathlib import Path
from urllib.parse import urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from api.storage.core import Namespace,hash_file
FIELDS={'format','server_url','restored_root','code_url','code_commit','manifest_key','manifest_sha256','namespace','oss_bucket','oss_region','backup_catalog','backup_inputs','stage_parent','max_snapshot_bytes','interval_days','retain_successful','weekly_day','weekly_time','time_zone','maintenance_adapter','maintenance_adapter_sha256'}
def validate(value,*,check_files=False):
    errors=[]
    if set(value)!=FIELDS:errors.append('Configuration fields differ from exact non-sensitive schema')
    if value.get('format')!='litlib-target-config-v1':errors.append('Configuration format differs')
    u=urlsplit(str(value.get('server_url','')))
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment or u.path not in ('','/') or u.hostname.endswith('.invalid'):errors.append('Real HTTPS origin without embedded credentials required')
    if value.get('code_url')!='https://github.com/Bpig-C/literature-library':errors.append('Reviewed repository required')
    for k,size in [('code_commit',40),('manifest_sha256',64),('maintenance_adapter_sha256',64)]:
        if not re.fullmatch('[0-9a-f]{'+str(size)+'}',str(value.get(k,''))):errors.append('Exact SHA required: '+k)
    try:
        ns=Namespace(value.get('namespace',''))
        if '/prod/' not in ns.root or value.get('manifest_key')!=ns.key(value.get('manifest_sha256','')):errors.append('Exact production manifest locator required')
    except Exception:errors.append('Namespace/manifest locator invalid')
    if not value.get('oss_bucket') or not value.get('oss_region'):errors.append('Explicit bucket and region required')
    paths={}
    for k in ('restored_root','backup_catalog','backup_inputs','stage_parent','maintenance_adapter'):
        p=Path(str(value.get(k,'')))
        if not p.is_absolute():errors.append('Absolute path required: '+k)
        else:paths[k]=p.resolve()
    if len(set(paths.values()))!=len(paths):errors.append('Runtime and control paths must be distinct')
    root=paths.get('restored_root')
    if root:
        for k in ('backup_catalog','backup_inputs','stage_parent','maintenance_adapter'):
            if k in paths and (paths[k]==root or root in paths[k].parents):errors.append('Durable control/staging path must be outside replaceable release: '+k)
    if type(value.get('max_snapshot_bytes')) is not int or value['max_snapshot_bytes']<=0:errors.append('Positive snapshot byte ceiling required')
    if type(value.get('interval_days')) is not int or value['interval_days']<1:errors.append('Positive interval required')
    if type(value.get('retain_successful')) is not int or value['retain_successful']<1:errors.append('Positive retention required')
    if value.get('weekly_day') not in ('Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'):errors.append('Exact weekly day required')
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',str(value.get('weekly_time',''))):errors.append('HH:MM schedule required')
    # This template uses Windows China Standard Time, corresponding to UTC+8.
    if value.get('time_zone')!='Asia/Shanghai':errors.append('Template currently supports Asia/Shanghai only')
    if check_files:
        for k in ('backup_inputs','maintenance_adapter'):
            p=paths.get(k)
            if not p or not p.is_file() or p.is_symlink():errors.append('Existing regular file required: '+k)
        adapter=paths.get('maintenance_adapter')
        inputs_path=paths.get('backup_inputs')
        if inputs_path and inputs_path.is_file() and root:
            try:
                from api.storage.release_control import validate_source
                inputs=json.loads(inputs_path.read_text('utf-8'))
                if Path(inputs.get('source_root','')).resolve()!=root:errors.append('Backup source_root differs from restored runtime')
                validate_source(inputs)
            except Exception as exc:errors.append('Backup source validation failed: '+str(exc))
        if adapter and adapter.is_file() and hash_file(adapter)[0]!=value.get('maintenance_adapter_sha256'):errors.append('Reviewed maintenance adapter hash differs')
        if root and not (root/'release-manifest.json').is_file():errors.append('Restored manifest missing')
        elif root:
            manifest=root/'release-manifest.json'
            if hash_file(manifest)[0]!=value.get('manifest_sha256'):errors.append('Restored manifest SHA differs')
            else:
                try:
                    m=json.loads(manifest.read_text('utf-8'))
                    if m['namespace']!=value['namespace'] or m['code']['commit']!=value['code_commit']:errors.append('Restored manifest namespace/code differs from configuration')
                except (ValueError,KeyError,TypeError):errors.append('Restored manifest structure invalid')
    return {'ok':not errors,'errors':errors,'offline':True,'service_started':False,'timer_installed':False,'network_requests':0,'credential_values_read':False,'scope':'Configuration and optional named files only; runtime/TLS/authority and actual writer stoppage require deployment acceptance'}
def main():
    p=argparse.ArgumentParser();p.add_argument('--configuration',required=True);p.add_argument('--check-files',action='store_true');a=p.parse_args()
    result=validate(json.loads(Path(a.configuration).read_text('utf-8')),check_files=a.check_files);print(json.dumps(result,ensure_ascii=False));return 0 if result['ok'] else 1
if __name__=='__main__':raise SystemExit(main())
