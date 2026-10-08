"""Run on the authority host scheduler; never defer daily asset uploads here."""
import argparse,json,sys,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from api.storage.backup_catalog import discover,select,run_due,read_catalog,record_verified
from api.storage.snapshot_policy import plan
from api.storage.release_control import bindings,prepare,stage,publish,digest
from api.storage.core import Namespace,StorageError
from api.storage.backends import LocalObjectBackend,oss_from_environment

def main():
    p=argparse.ArgumentParser();p.add_argument('--catalog',required=True)
    s=p.add_subparsers(dest='command',required=True);s.add_parser('versions')
    q=s.add_parser('select');q.add_argument('--version-id',required=True)
    for name in ('plan','tick'):
        q=s.add_parser(name);q.add_argument('--inputs',required=True);q.add_argument('--now',required=True);q.add_argument('--interval-days',type=int,default=7);q.add_argument('--retain',type=int,default=3)
        if name=='tick':
            q.add_argument('--stage-parent',required=True);q.add_argument('--max-snapshot-bytes',type=int,required=True);q.add_argument('--writers-stopped',action='store_true');q.add_argument('--local-objects')
    a=p.parse_args();catalog=Path(a.catalog)
    if not catalog.is_absolute():raise StorageError('invalid_request','Explicit absolute authority backup catalog required')
    if a.command=='versions':result=discover(catalog)
    elif a.command=='select':result=select(catalog,a.version_id)
    else:
        inputs=json.loads(Path(a.inputs).read_text('utf-8'));ns=Namespace(inputs['namespace'])
        active={ns.key(b['parent_sha256'] or b['sha256']) for b in bindings(inputs['catalog'])}
        if a.command=='plan':result=plan(read_catalog(catalog)['versions'],active,now=a.now,interval_days=a.interval_days,retain=a.retain)
        else:
            if not a.writers_stopped:raise StorageError('permission_denied','Actual authority writer maintenance window required')
            parent=Path(a.stage_parent)
            if not parent.is_absolute():raise StorageError('invalid_request','Explicit absolute stage parent required')
            if a.local_objects and '/test/' not in ns.root:raise StorageError('permission_denied','Local backend only allowed in test namespace')
            backend=LocalObjectBackend(a.local_objects) if a.local_objects else oss_from_environment()
            def backup():
                ticket=prepare(inputs,a.max_snapshot_bytes);dest=parent/uuid.uuid4().hex
                receipt=stage(ticket,digest(ticket),dest,True)
                published=publish(dest,receipt['manifest_sha256'],backend,receipt['maximum_upload_bytes'])
                return record_verified(catalog,dest,published,backend,a.now)
            result=run_due(catalog,active,backup,now=a.now,interval_days=a.interval_days,retain=a.retain)
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':
    try:main()
    except StorageError as e:print(json.dumps({'ok':False,'code':e.code,'detail':str(e)}),file=sys.stderr);raise SystemExit(1)
