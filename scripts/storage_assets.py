"""Explicit catalog asset operations. Never auto-migrates or selects a default DB."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from api.storage.runtime import configured_registry,configured_service,validate_startup

def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('initialize')
    sub.add_parser('check')
    sub.add_parser('release-completed-staging')
    r=sub.add_parser('release-ingested-pdf');r.add_argument('--job-id',required=True)
    r=sub.add_parser('migration-dry-run');r.add_argument('--manifest',required=True)
    r=sub.add_parser('migration-apply-synthetic');r.add_argument('--manifest',required=True)
    r=sub.add_parser('migration-prepare-controlled');r.add_argument('--manifest',required=True);r.add_argument('--payloads',required=True)
    r=sub.add_parser('migration-apply-controlled');r.add_argument('--ticket',required=True);r.add_argument('--approved-ticket-sha256',required=True)
    r=sub.add_parser('release-producer-output');r.add_argument('--job-id',required=True)
    r=sub.add_parser('resume-producer');r.add_argument('--job-id',required=True)
    r=sub.add_parser('reconcile-ingest');r.add_argument('--source-file-id',required=True)
    r=sub.add_parser('import-research');r.add_argument('--work-id',required=True);r.add_argument('--source-file-id',required=True);r.add_argument('--parse-run-id',required=True);r.add_argument('--version',required=True,type=int)
    q=sub.add_parser('register');q.add_argument('--source',required=True);q.add_argument('--identity',required=True);q.add_argument('--role',required=True);q.add_argument('--version',required=True,type=int);q.add_argument('--operation-id',required=True);q.add_argument('--member');q.add_argument('--virtual-path')
    r=sub.add_parser('resume');r.add_argument('--operation-id',required=True)
    args=p.parse_args()
    if args.command=='initialize': configured_registry().initialize();print(json.dumps({'initialized':True}));return
    if args.command=='check':validate_startup();print(json.dumps({'startup_checked':True}));return
    if args.command=='migration-prepare-controlled':
        from api.storage.controlled_migration import prepare,ticket_digest
        ticket=prepare(json.loads(Path(args.manifest).read_text('utf-8')),json.loads(Path(args.payloads).read_text('utf-8')))
        print(json.dumps({'ticket':ticket,'ticket_sha256':ticket_digest(ticket)},ensure_ascii=False));return
    if args.command=='migration-apply-controlled':
        from api.storage.controlled_migration import execute
        print(json.dumps(execute(json.loads(Path(args.ticket).read_text('utf-8')),args.approved_ticket_sha256)));return
    service=configured_service()
    if args.command.startswith('migration-'):
        from api.storage.migration import dry_run,apply
        manifest=json.loads(Path(args.manifest).read_text('utf-8'))
        print(json.dumps((dry_run if args.command=='migration-dry-run' else apply)(manifest,service)));return
    if args.command=='release-ingested-pdf':
        from api.storage.ingest_lifecycle import release_ingested_pdf
        print(json.dumps(release_ingested_pdf(args.job_id,service)));return
    if args.command=='release-producer-output':
        from api.storage.producers import release_producer_output
        print(json.dumps(release_producer_output(args.job_id,service)));return
    if args.command=='import-research':
        from api.research_context import ResearchContext
        from api.research_service import ResearchService
        result=ResearchService(ResearchContext.from_env()).import_registered_source(work_id=args.work_id,source_file_id=args.source_file_id,parse_run_id=args.parse_run_id,version=args.version)
        print(json.dumps(result));return
    if args.command=='resume-producer':
        from api.storage.producers import resume_producer
        print(json.dumps(resume_producer(args.job_id,service)));return
    if args.command=='reconcile-ingest':
        from api.storage.producers import register_ingested_sources
        print(json.dumps(register_ingested_sources([args.source_file_id],service)));return
    if args.command=='release-completed-staging':print(json.dumps({'released_sha256':service.release_completed_staging()}));return
    if args.command=='resume': result=service.resume(args.operation_id)
    else: result=service.publish(Path(args.source),identity=args.identity,role=args.role,version=args.version,operation_id=args.operation_id,member=args.member,virtual_path=args.virtual_path)
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__': main()
