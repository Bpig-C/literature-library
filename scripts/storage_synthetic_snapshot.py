"""Explicit offline synthetic snapshot/restore CLI; no formal DB defaults."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from api.storage.synthetic_snapshot import snapshot,restore,restore_backend,verify_restored_client
def main():
 p=argparse.ArgumentParser();s=p.add_subparsers(dest='command',required=True)
 q=s.add_parser('snapshot');q.add_argument('--destination',required=True);q.add_argument('--mutable-file',action='append',default=[])
 q=s.add_parser('restore');q.add_argument('--bundle',required=True);q.add_argument('--destination',required=True);q.add_argument('--object-backend',required=True)
 q=s.add_parser('restore-backend');q.add_argument('--bundle',required=True);q.add_argument('--destination',required=True)
 q=s.add_parser('verify-restore');q.add_argument('--bundle',required=True);q.add_argument('--client-root',required=True)
 a=p.parse_args()
 if a.command=='snapshot':result=snapshot(a.destination,a.mutable_file)
 elif a.command=='restore':result=restore(a.bundle,a.destination,a.object_backend)
 elif a.command=='restore-backend':result=restore_backend(a.bundle,a.destination)
 else:result=verify_restored_client(a.bundle,a.client_root)
 print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
