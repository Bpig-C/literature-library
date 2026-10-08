"""Dry-run default; exact execution/reconciliation only in local test namespace."""
import argparse,json,sys
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from api.storage.reclamation import ReclamationPlanner
from api.storage.runtime import configured_service
from api.storage.authority import configured_authority
from api.storage.release_control import read,write
from api.storage.core import StorageError

def main():
    p=argparse.ArgumentParser();p.add_argument('--catalog',required=True);p.add_argument('--roots',required=True);p.add_argument('--max-verify-bytes',required=True,type=int)
    s=p.add_subparsers(dest='command',required=True)
    q=s.add_parser('plan');q.add_argument('--output',required=True)
    q=s.add_parser('validate');q.add_argument('--plan',required=True)
    q=s.add_parser('execute');q.add_argument('--plan',required=True);q.add_argument('--authorization',required=True);q.add_argument('--journal',required=True);q.add_argument('--receipt',required=True);q.add_argument('--simulate-local',action='store_true')
    q=s.add_parser('reconcile');q.add_argument('--receipt',required=True);q.add_argument('--simulate-local',action='store_true')
    a=p.parse_args();svc=configured_service();planner=ReclamationPlanner(svc,a.catalog,a.roots,configured_authority(),max_verify_bytes=a.max_verify_bytes)
    now=datetime.now(timezone.utc).isoformat()
    if a.command=='plan':
        output=Path(a.output)
        if not output.is_absolute() or output.exists():raise StorageError('revision_conflict','New absolute frozen plan file required')
        value=planner.plan(now=now)
        # Exclusive creation prevents overwriting evidence even under a race.
        with output.open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2)
        result={k:value[k] for k in ('plan_sha256','keep_successful','rotation_pending','physical_limit_blockers','total_unique_bytes','deletion_performed','production_delete_supported')};result['plan']=str(output)
    elif a.command=='validate':
        with planner.guard():result=planner.validate(read(a.plan),now=now)
    else:
        from api.storage.reclamation_execution import ReclamationExecution,LocalExactDeletion
        if not a.simulate_local:raise StorageError('permission_denied','Production execution/reconciliation disabled')
        LocalExactDeletion(planner)
        execution=ReclamationExecution(planner)
        if a.command=='execute':result=execution.execute(read(a.plan),read(a.authorization),a.journal,a.receipt,now=now,simulate_local=True)
        else:result=execution.reconcile(a.receipt)
    print(json.dumps(result,ensure_ascii=False));return 0
if __name__=='__main__':
    try:raise SystemExit(main())
    except (StorageError,ValueError,KeyError,TypeError,OSError) as e:print(json.dumps({'ok':False,'code':getattr(e,'code','invalid_request'),'detail':str(e),'deletion_performed':False}),file=sys.stderr);raise SystemExit(1)
