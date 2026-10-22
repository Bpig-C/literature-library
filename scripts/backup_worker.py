"""Independent host backup worker. Configuration is trusted, never remote input."""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from api.backup_jobs import run_one, resolve
from api.storage.manual_backup import execute


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--loop',action='store_true')
    parser.add_argument('--preview',action='store_true')
    parser.add_argument('--resolve-job')
    parser.add_argument('--service-verified',action='store_true')
    args=parser.parse_args(argv)
    config=json.loads(args.config.read_text('utf-8-sig'))
    if args.resolve_job:
        print(json.dumps(resolve(args.resolve_job,verified_service=args.service_verified))); return
    if args.preview:
        print(json.dumps(execute(config,'preview',preview=True))); return
    while True:
        result=run_one(lambda jid:execute(config,jid))
        print(json.dumps(result),flush=True)
        if not args.loop or result['state']=='needs_attention': return
        time.sleep(10)


if __name__=='__main__':
    try: main()
    except Exception as error:
        print(json.dumps({'code':getattr(error,'code','backup_worker_failed'),'type':type(error).__name__}),file=sys.stderr)
        raise SystemExit(1)
