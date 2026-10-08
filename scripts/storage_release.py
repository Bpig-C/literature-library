"""Unified cold restore from an exact GitHub+OSS release manifest."""
import argparse,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from api.storage.backends import LocalObjectBackend,oss_from_environment
from api.storage.release_control import prepare,stage,publish,digest,read,write,staged
from api.storage.core import StorageError
from api.storage.unified_release import restore_release

def backend(args,namespace):
    if args.local_objects:
        if '/test/' not in namespace or not Path(args.local_objects).is_absolute():raise StorageError('permission_denied','explicit absolute local object root only allowed for test namespace')
        return LocalObjectBackend(Path(args.local_objects))
    if not os.environ.get('LITLIB_OSS_BUCKET') or not os.environ.get('LITLIB_OSS_REGION'):raise StorageError('configuration_error','explicit OSS bucket/region required')
    return oss_from_environment()

def main():
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='command',required=True)
    q=s.add_parser('snapshot-prepare');q.add_argument('--inputs',required=True);q.add_argument('--ticket',required=True);q.add_argument('--max-snapshot-bytes',type=int,required=True)
    q=s.add_parser('snapshot-stage');q.add_argument('--ticket',required=True);q.add_argument('--approved-ticket-sha256',required=True);q.add_argument('--destination',required=True);q.add_argument('--writers-stopped',action='store_true')
    q=s.add_parser('snapshot-publish');q.add_argument('--stage',required=True);q.add_argument('--approved-manifest-sha256',required=True);q.add_argument('--max-upload-bytes',type=int,required=True);q.add_argument('--local-objects')
    q=s.add_parser('backup');q.add_argument('--inputs',required=True);q.add_argument('--approved-input-sha256',required=True);q.add_argument('--destination',required=True);q.add_argument('--writers-stopped',action='store_true');q.add_argument('--max-upload-bytes',type=int,required=True);q.add_argument('--local-objects')
    q=s.add_parser('restore');q.add_argument('--manifest-key',required=True);q.add_argument('--manifest-sha256',required=True);q.add_argument('--namespace',required=True);q.add_argument('--destination',required=True);q.add_argument('--expected-git-url',required=True);q.add_argument('--quota-bytes',type=int,default=512*1024**2);q.add_argument('--local-objects')
    a=p.parse_args()
    try:
        if a.command=='snapshot-prepare':
            ticket=prepare(read(a.inputs),a.max_snapshot_bytes);path=Path(a.ticket)
            if path.exists():raise StorageError('revision_conflict','new ticket path required')
            write(path,ticket);result={'ticket_sha256':digest(ticket),'ticket':str(path),'payload_bytes_estimate':ticket['payload_bytes_estimate'],'manifest_bytes':'exact at staging; included in budget','source_writes':False,'network_requests':0}
        elif a.command=='snapshot-stage':result=stage(read(a.ticket),a.approved_ticket_sha256,a.destination,a.writers_stopped)
        elif a.command=='backup':
            inputs=read(a.inputs)
            if digest(inputs)!=a.approved_input_sha256 or not a.writers_stopped:raise StorageError('permission_denied','exact reviewed input scope and stopped writers required')
            destination=Path(a.destination)
            if destination.exists():
                _,receipt,m=staged(destination)
                if read(destination/'backup-approval.json')['input_sha256']!=a.approved_input_sha256:raise StorageError('revision_conflict','existing frozen backup belongs to another approved input')
            else:
                ticket=prepare(inputs,a.max_upload_bytes)
                receipt=stage(ticket,digest(ticket),destination,True)
                write(destination/'snapshot-ticket.json',ticket)
                write(destination/'backup-approval.json',{'input_sha256':a.approved_input_sha256,'max_upload_bytes':a.max_upload_bytes,'scope':'one-command backup of exact approved named inputs, current coherent DB snapshots in operator-confirmed stopped-writer window; digest alone is not human authorization'})
            result=publish(destination,receipt['manifest_sha256'],backend(a,inputs['namespace']),a.max_upload_bytes)
        elif a.command=='snapshot-publish':
            m=read(Path(a.stage)/'release.json');result=publish(a.stage,a.approved_manifest_sha256,backend(a,m['namespace']),a.max_upload_bytes)
        else:result=restore_release(backend(a,a.namespace),manifest_key=a.manifest_key,manifest_sha256=a.manifest_sha256,destination=Path(a.destination),namespace=a.namespace,expected_git_url=a.expected_git_url,quota_bytes=a.quota_bytes)
        print(json.dumps(result,ensure_ascii=False))
    except StorageError as error:
        print(json.dumps({'error_code':error.code,'detail':str(error),'existing_state_preserved':True}),file=sys.stderr);return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
