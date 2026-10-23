"""Apply a recovered environment, verify its roots, and run only that runtime."""
import argparse,importlib.metadata,json,os,socket,sqlite3,subprocess,sys
from contextlib import closing
from pathlib import Path
CODE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(CODE))
from api.storage.core import StorageError,hash_file,Namespace
from api.storage.unified_release import validate_versions

def read_only_cli(script,arguments):
    if arguments in (['--help'],['-h']):return True
    if script=='storage_assets.py':return bool(arguments) and arguments[0] in {'check','migration-dry-run','migration-prepare-controlled'}
    if script=='healthcheck_library.py':return '--apply' not in arguments
    if script=='storage_authority.py':return arguments==['status']
    if script=='storage_reclamation.py':
        p=argparse.ArgumentParser(add_help=False);p.add_argument('--catalog');p.add_argument('--roots');p.add_argument('--max-verify-bytes')
        _,remaining=p.parse_known_args(arguments)
        return bool(remaining) and remaining[0] in {'plan','validate'}
    if script=='storage_backup.py':
        p=argparse.ArgumentParser(add_help=False);p.add_argument('--catalog')
        _,remaining=p.parse_known_args(arguments)
        return bool(remaining) and remaining[0] in {'versions','select','plan','discover-remote'}
    if script!='litlib.py':return False
    p=argparse.ArgumentParser(add_help=False);p.add_argument('--library-root');p.add_argument('--db-path');p.add_argument('--read-only',action='store_true')
    _,remaining=p.parse_known_args(arguments)
    return bool(remaining) and remaining[0] in {'lookup','read','search','query','evidence','units','feedback-list','citations-view','citations-export','output-history','matrix','comparison','composition','ontology-impact','usable-basis','verify-environment'}

def environment(root):
    root=Path(root)
    if not root.is_absolute() or not root.is_dir():raise StorageError('configuration_error','explicit existing absolute restored root required')
    root=root.resolve()
    if CODE.resolve()!=(root/'app').resolve():raise StorageError('configuration_error','invoke restored app/scripts/restored_runtime.py, never a source-machine checkout')
    env=json.loads((root/'environment.json').read_text('utf-8'));m=json.loads((root/'release-manifest.json').read_text('utf-8'))
    exact={'LITLIB_LIBRARY_ROOT':root/'data/library','LITLIB_DB_PATH':root/'data/library/literature.sqlite','LITLIB_RESEARCH_ROOT':root/'data/research','LITLIB_RESEARCH_DB':root/'data/research/research.sqlite','LITLIB_RESEARCH_ASSETS_ROOT':root/'data/research/assets','LITLIB_RUNTIME_MATERIALS_ROOT':root/'data/library/docs','LITLIB_STORAGE_CACHE':root/'cache','LITLIB_STORAGE_STAGING':root/'staging'}
    allowed=set(exact)|{'LITLIB_STORAGE_MODE','LITLIB_STORAGE_ROOT','LITLIB_STORAGE_BACKEND','LITLIB_STORAGE_LOCAL_OBJECTS','LITLIB_STORAGE_CACHE_BYTES','LITLIB_STORAGE_STAGING_BYTES','LITLIB_RESEARCH_EDITING_ENABLED','LITLIB_OSS_BUCKET','LITLIB_OSS_REGION'}
    if set(env)-allowed:raise StorageError('configuration_error','unexpected environment key; refuse credentials and inherited root overrides')
    for name,path in exact.items():
        if name not in env or not Path(env[name]).is_absolute() or Path(env[name]).resolve()!=path.resolve():raise StorageError('configuration_error','restored root mismatch: '+name)
    ns=Namespace(env.get('LITLIB_STORAGE_ROOT',''))
    if env.get('LITLIB_STORAGE_MODE')!='immutable' or ns.root!=m['namespace']:raise StorageError('configuration_error','exact immutable release environment required')
    if env.get('LITLIB_STORAGE_BACKEND')=='local':
        if '/test/' not in ns.root or not Path(env.get('LITLIB_STORAGE_LOCAL_OBJECTS','')).is_absolute():raise StorageError('configuration_error','local backend allowed only in explicit test namespace')
    elif env.get('LITLIB_STORAGE_BACKEND')!='oss' or env.get('LITLIB_OSS_BUCKET')!=m['configuration'].get('oss_bucket') or env.get('LITLIB_OSS_REGION')!=m['configuration'].get('oss_region'):raise StorageError('configuration_error','release OSS backend configuration mismatch')
    host_controls={'LITLIB_REMOTE_ENABLED','LITLIB_REMOTE_TOKEN','LITLIB_REMOTE_WRITE_ENABLED',
                   'LITLIB_AUTHORITY_TOKEN','LITLIB_AUTHORITY_EPOCH','LITLIB_ASYNC_PARSE_ENABLED',
                   'LITLIB_PARSE_UPLOAD_KEY','LITLIB_BACKUP_CONTROL','LITLIB_BACKUP_ADMIN_TOKEN'}
    for k in list(os.environ):
        if k.startswith('LITLIB_') and k not in host_controls:os.environ.pop(k)
    os.environ.update(env);os.environ.update(LITLIB_RESEARCH_READ_ONLY='1',LITLIB_LEGACY_CLASSIFICATION_WRITES='block',PYTHONUTF8='1')
    return root,m

def check(root,development=False):
    root,m=environment(root);head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=CODE).decode().strip()
    if development:
        from scripts.check_release import check as check_code
        if not check_code()['ok'] or subprocess.check_output(['git','status','--porcelain'],cwd=CODE).strip():raise StorageError('revision_conflict','development requires committed clean generic code history')
        if subprocess.run(['git','merge-base','--is-ancestor',m['code']['commit'],head],cwd=CODE).returncode!=0:raise StorageError('revision_conflict','development code must descend from restored release')
    else:
        if head!=m['code']['commit']:raise StorageError('revision_conflict','runtime Git revision differs')
        for name,sha in m['code']['files'].items():
            if hash_file(CODE/name)[0]!=sha:raise StorageError('checksum_mismatch','runtime code changed: '+name)
    for name,sha in json.loads((root/'frontend-integrity.json').read_text('utf-8')).items():
        if hash_file(CODE/'web/dist'/name)[0]!=sha:raise StorageError('checksum_mismatch','runtime frontend changed: '+name)
    validate_versions(m['configuration'],root/'data/research/research.sqlite')
    from api.research_runtime_assets import presentation_assets
    assets=presentation_assets()
    with closing(sqlite3.connect((root/'data/library/literature.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
        if db.execute('PRAGMA quick_check').fetchone()[0]!='ok' or db.execute('SELECT root FROM storage_settings WHERE id=1').fetchone()[0]!=m['namespace']:raise StorageError('checksum_mismatch','catalog integrity/namespace differs')
    if importlib.metadata.version('alibabacloud-oss-v2')!='1.4.0':raise StorageError('configuration_error','locked OSS SDK 1.4.0 required')
    for module in ('fastapi','uvicorn','pymupdf','python_multipart'):__import__(module)
    # S5: non-sensitive parser runtime configuration preflight. conf.json is a
    # per-machine file (intentionally not in the sealed manifest); its absence
    # makes _run_parse raise FileNotFoundError at CloudClient construction.
    parser_conf=CODE/'parser/conf.json'
    if not parser_conf.is_file():
        import warnings;warnings.warn('parser/conf.json absent; parse operations will fail until the {}-byte non-sensitive configuration is placed (see library/docs/docs/manuals/parser-conf-restore.md in the runtime materials closure)',RuntimeWarning)
    else:
        import json as _json;_json.loads(parser_conf.read_text('utf-8-sig'))
    parser_constructors_ok=True
    try:
        sys.path.insert(0,str(CODE/'parser'));sys.path.insert(0,str(CODE))
        from core.mineru.cloud_client import CloudClient as _CC
        from core.mineru.pymupdf_client import PyMuPDFClient as _PMC
        _CC();_PMC()
    except Exception:parser_constructors_ok=False
    return {'ok':True,'development':development,'restored_root':str(root),'code_commit':head,'schema_version':6,'contract_version':5,'reading_records':len(assets['reading']['records']),'concepts':len(assets['ontology']['concepts']),'environment_applied_in_this_process':True,'fallback_to_source_machine':False,'service_started':False,'cache_downloads':0,'sdk_version':'1.4.0','parser_config_present':parser_conf.is_file(),'parser_constructors_ok':parser_constructors_ok}

def main():
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='command',required=True)
    q=s.add_parser('check');q.add_argument('--root',required=True)
    q=s.add_parser('serve');q.add_argument('--root',required=True);q.add_argument('--port',required=True,type=int);q.add_argument('--read-only',action='store_true');q.add_argument('--allow-writes',action='store_true')
    q=s.add_parser('run-cli');q.add_argument('--root',required=True);q.add_argument('--allow-writes',action='store_true');q.add_argument('--authority-control',action='store_true');q.add_argument('script',choices=['litlib.py','storage_assets.py','healthcheck_library.py','literature_ingest.py','storage_authority.py','storage_backup.py','storage_reclamation.py']);q.add_argument('arguments',nargs=argparse.REMAINDER)
    for command_parser in s.choices.values():command_parser.add_argument('--development',action='store_true',help='explicit isolated development from a clean descendant code commit; normal release checks remain strict')
    a=p.parse_args()
    try:
        result=check(a.root,a.development);print(json.dumps(result),flush=True)
        if a.command=='run-cli':
            if a.authority_control:
                if a.allow_writes or a.script not in {'storage_authority.py','storage_backup.py','storage_reclamation.py'}:raise StorageError('permission_denied','Authority control is exclusively for explicit backup/handover/reclamation administrative commands')
                return subprocess.call([sys.executable,str(CODE/'scripts'/a.script),*a.arguments],cwd=CODE)
            if not a.allow_writes and not read_only_cli(a.script,a.arguments):raise StorageError('permission_denied','Mutating CLI requires --allow-writes and an active authority; read-only is the default')
            os.environ['LITLIB_RESEARCH_READ_ONLY']='0' if a.allow_writes else '1'
            if a.allow_writes:
                from api.storage.authority import configured_authority
                with configured_authority().write_guard():return subprocess.call([sys.executable,str(CODE/'scripts'/a.script),*a.arguments],cwd=CODE)
            return subprocess.call([sys.executable,str(CODE/'scripts'/a.script),*a.arguments],cwd=CODE)
        if a.command=='serve':
            if not 1024<=a.port<=65535:raise StorageError('invalid_request','explicit nonprivileged port required')
            with socket.socket() as sock:sock.bind(('127.0.0.1',a.port))
            if a.allow_writes and a.read_only:raise StorageError('invalid_request','Choose read-only or explicit authority writes')
            os.environ['LITLIB_RESEARCH_READ_ONLY']='0' if a.allow_writes else '1'
            if a.allow_writes:
                from api.storage.authority import configured_authority
                configured_authority().check_remote()
            import uvicorn
            uvicorn.run('api.main:app',host='127.0.0.1',port=a.port)
    except (StorageError,OSError,KeyError,ValueError) as error:
        print(json.dumps({'ok':False,'detail':str(error),'service_started':False,'no_fallback':True}),file=sys.stderr);return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
