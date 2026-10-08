"""Explicit authority control. All commands run on the current authority host."""
import argparse,sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from api.storage.authority import configured_authority
from api.storage.backup_catalog import select
from api.storage.core import StorageError

def main():
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='command',required=True)
    for name in ('initialize','status','freeze'):s.add_parser(name)
    q=s.add_parser('handover');q.add_argument('--target-owner-sha256',required=True);q.add_argument('--catalog',required=True);q.add_argument('--version-id',required=True);q.add_argument('--writers-stopped',action='store_true')
    a=p.parse_args();authority=configured_authority()
    if a.command=='initialize':value=authority.initialize()
    elif a.command=='status':value=authority.check_remote()
    elif a.command=='freeze':value=authority.freeze()
    else:
        if not a.writers_stopped or not authority.marker.exists():raise StorageError('permission_denied','Freeze source before final backup; actual writers must be stopped')
        v=select(a.catalog,a.version_id)
        value=authority.handover(a.target_owner_sha256,{'manifest_sha256':v['manifest_sha256'],'manifest_key':v['manifest_key']})
    print(json.dumps(value))
if __name__=='__main__':
    try:main()
    except StorageError as e:print(json.dumps({'ok':False,'code':e.code,'detail':str(e)}),file=sys.stderr);raise SystemExit(1)
