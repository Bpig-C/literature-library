"""Only task-owned synthetic LocalObjectBackend snapshots. No formal/OSS path."""
import hashlib,json,os,sqlite3,uuid,shutil,subprocess
from pathlib import Path
from contextlib import ExitStack,contextmanager
from .core import StorageError,file_lock,hash_file,relative_key
from .runtime import configured_service,required_path
from .backends import LocalObjectBackend
from .producers import lock_path
from .service import member_digest

CODE=Path(__file__).resolve().parents[2]
WORKSPACE=CODE.parents[1] if CODE.parent.name=='.task_tmp' else CODE

def owned_task_path(path):
 p=Path(path).resolve()
 if not p.is_relative_to(WORKSPACE/'.task_tmp'):raise StorageError('configuration_error','synthetic snapshot requires task-owned workspace directory')
 return p

def synthetic_context():
 root=owned_task_path(required_path('LITLIB_SYNTHETIC_ROOT'))
 try:marker=json.loads((root/'.litlib-synthetic.json').read_text('utf-8'))
 except (OSError,ValueError):raise StorageError('configuration_error','synthetic marker required') from None
 if marker.get('synthetic') is not True or marker.get('root')!=str(root):raise StorageError('configuration_error','synthetic marker mismatch')
 expected={'LITLIB_LIBRARY_ROOT':root/'library','LITLIB_DB_PATH':root/'library/literature.sqlite','LITLIB_RESEARCH_ROOT':root/'research','LITLIB_RESEARCH_DB':root/'research/research.sqlite','LITLIB_STORAGE_CACHE':root/'cache','LITLIB_STORAGE_STAGING':root/'staging'}
 if any(required_path(k)!=v for k,v in expected.items()):raise StorageError('configuration_error','synthetic roots must match fixed isolated layout')
 service=configured_service()
 if not isinstance(service.backend,LocalObjectBackend) or '/test/' not in service.ns.root:raise StorageError('configuration_error','synthetic local test namespace only')
 backend=owned_task_path(service.backend.root)
 if backend.is_relative_to(root) or root.is_relative_to(backend):raise StorageError('configuration_error','simulated remote backend must be outside client root')
 marker=json.loads((backend/'.litlib-synthetic-backend.json').read_text('utf-8'))
 if marker!={'synthetic':True,'root':str(backend),'namespace':service.ns.root}:raise StorageError('configuration_error','synthetic backend ownership mismatch')
 return root,service

def guarded_connection(path):
 c=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,timeout=10);c.row_factory=sqlite3.Row;c.execute('BEGIN IMMEDIATE');return c

def copy_checked(src,dst):
 if src.is_symlink() or not src.is_file():raise StorageError('unsafe_package','snapshot input is not a plain file')
 digest=hash_file(src);dst.parent.mkdir(parents=True,exist_ok=True)
 with src.open('rb') as a,dst.open('xb') as b:shutil.copyfileobj(a,b,1024*1024);b.flush();os.fsync(b.fileno())
 if hash_file(src)!=digest or hash_file(dst)!=digest:raise StorageError('checksum_mismatch','snapshot input changed during copy')

def snapshot(destination,mutable_files=()):
 root,service=synthetic_context();dest=owned_task_path(destination)
 if dest.is_relative_to(root) or root.is_relative_to(dest):raise StorageError('configuration_error','snapshot must be separate from source')
 dest.mkdir(parents=True,exist_ok=False)
 with file_lock(lock_path(service)),file_lock(service._lock('staging','all')):
  with ExitStack() as stack:
   connections=[]
   for database in [service.registry.catalog,required_path('LITLIB_RESEARCH_DB')]:
    c=guarded_connection(database);stack.callback(c.close);connections.append(c)
   catalog,research=connections
   if catalog.execute("SELECT 1 FROM storage_operations WHERE state!='registered' LIMIT 1").fetchone() or catalog.execute("SELECT 1 FROM storage_producer_jobs WHERE state IN ('preparing','artifacts_ready') LIMIT 1").fetchone():raise StorageError('producer_incomplete','snapshot requires an explicitly quiet completed window')
   for connection,tables in [(catalog,{'source_files':['source_path','archive_path'],'literature_parse_runs':['source_path','output_dir','content_md_path','content_json_path','package_path']}),(research,{'research_sources':['source_path','snapshot_path']})]:
    for table,columns in tables.items():
     for column in columns:
      for (raw,) in connection.execute('SELECT '+column+' FROM '+table+' WHERE '+column+" IS NOT NULL AND "+column+"<>''"):
       if str(raw).startswith('litlib-asset://'):
        from .references import decode_reference
        identity,version=decode_reference(raw);service.registry.binding(identity,'pdf',version);continue
       if table=='research_sources':raise StorageError('configuration_error','legacy research source path requires explicit registered-reference migration')
       if not Path(raw).is_absolute() or not Path(raw).resolve().is_relative_to(root):raise StorageError('configuration_error','synthetic snapshot has unsupported external/relative material reference')
   bindings=[dict(r) for r in catalog.execute('SELECT * FROM storage_bindings ORDER BY identity,role,version')]
   closure={}
   for b in bindings:
    digest=b['parent_sha256'] or b['sha256'];size=b['parent_bytes'] if b['parent_sha256'] else b['bytes']
    if digest in closure and closure[digest]!=size:raise StorageError('checksum_mismatch','closure size conflict')
    closure[digest]=size
   for digest,size in closure.items():
    key=service.ns.key(digest);src=service.backend.path(key)
    if hash_file(src)!=(digest,size):raise StorageError('checksum_mismatch','registered closure object failed verification')
    copy_checked(src,dest/'backend/objects'/key)
   for b in bindings:
    if b['member'] and member_digest(dest/'backend/objects'/service.ns.key(b['parent_sha256']),b['member'])!=(b['sha256'],b['bytes']):raise StorageError('checksum_mismatch','closure member mismatch')
   # BEGIN IMMEDIATE on both databases excludes commits in the same quiet window.
   # Back up from separate read-only connections; backing up a write-lock owner hangs.
   for database,relative in [(service.registry.catalog,'library/literature.sqlite'),(required_path('LITLIB_RESEARCH_DB'),'research/research.sqlite')]:
    target=dest/'client'/relative;target.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(target) as out:src.backup(out)
   # Explicit whitelist only. Never recursively copy works/research_sources.
   for rel in mutable_files:
    relative_key(rel);p=root/rel
    if not rel.startswith('research/editing/') or p.suffix not in ('.md','.json','.txt') or not p.resolve().is_relative_to(root/'research/editing'):raise StorageError('invalid_request','mutable whitelist limited to required editing text files')
    if hash_file(p)[0] in {b['sha256'] for b in bindings}:raise StorageError('invalid_request','registered asset duplicate cannot be a mutable working file')
    copy_checked(p,dest/'client'/rel)
   snapshots=[dict(r) for r in research.execute('SELECT id,source_id,version,parse_run_id,content_sha256 FROM research_text_snapshots ORDER BY id')]
   drafts=list(mutable_files)
   code={p.relative_to(CODE).as_posix():hash_file(p)[0] for folder in ['api','scripts','web/src','contracts'] for p in (CODE/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.js','.vue','.json')}
   for name in ['pyproject.toml','uv.lock','web/package.json','web/package-lock.json','web/npm-shrinkwrap.json']:
    if (CODE/name).is_file():code[name]=hash_file(CODE/name)[0]
   revision=subprocess.run(['git','rev-parse','HEAD'],cwd=CODE,capture_output=True,text=True)
   status=subprocess.run(['git','status','--porcelain'],cwd=CODE,capture_output=True,text=True)
   (dest/'client/build-manifest.json').write_text(json.dumps({'source_code_root':str(CODE),'code_sha256':code,'code_commit':revision.stdout.strip() if revision.returncode==0 else None,'source_tree_clean':status.returncode==0 and not status.stdout.strip(),'dependency_locks':{name:code[name] for name in ['uv.lock','web/npm-shrinkwrap.json'] if name in code},'git_remote_fetchability':'not established by snapshot; local commit/package evidence separate','browser_build':'not included by DB snapshot; frontend package evidence separate'},indent=2),'utf-8')
   files={p.relative_to(dest).as_posix():{'sha256':hash_file(p)[0],'bytes':p.stat().st_size} for p in dest.rglob('*') if p.is_file()}
   manifest={'format':'litlib-synthetic-snapshot-v2','id':uuid.uuid4().hex,'status':'complete','synthetic':True,'original_root':str(root),'namespace':service.ns.root,'files':files,'client_files':sorted(k for k in files if k.startswith('client/')),'backend_files':sorted(k for k in files if k.startswith('backend/objects/')),'excluded':['library/works','library/_inbox','library/_archive','research/research_sources','producer outputs/packages','cache','staging','unlisted mutable files'],'bindings':bindings,'physical_closure':closure,'research_snapshots':snapshots,'drafts':drafts,'window':'both DB write locks plus cooperative producer/staging lock; explicitly stopped external writers; not a production concurrent snapshot guarantee'}
   (dest/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),'utf-8')
 return manifest

def verify_bundle(bundle):
 bundle=owned_task_path(bundle);m=json.loads((bundle/'manifest.json').read_text('utf-8'))
 if m.get('format')!='litlib-synthetic-snapshot-v2' or m.get('synthetic') is not True or m.get('status')!='complete':raise StorageError('configuration_error','complete v2 synthetic manifest required')
 allowed={'client/library/literature.sqlite','client/research/research.sqlite','client/build-manifest.json'}|{'client/'+p for p in m['drafts']}
 expected_backend={'backend/objects/'+m['namespace']+f'objects/sha256/{h[:2]}/{h}' for h in m['physical_closure']}
 if set(m['client_files'])!=allowed or set(m['backend_files'])!=expected_backend or set(m['files'])!=allowed|expected_backend:raise StorageError('configuration_error','snapshot payload violates explicit whitelist')
 for rel,entry in m['files'].items():
  relative_key(rel);p=bundle/rel
  if p.is_symlink() or not p.resolve().is_relative_to(bundle) or hash_file(p)!=(entry['sha256'],entry['bytes']):raise StorageError('checksum_mismatch','snapshot bundle failed verification')
 return m

def restore_backend(bundle,destination):
 bundle=owned_task_path(bundle);m=verify_bundle(bundle);dest=owned_task_path(destination)
 if dest.is_relative_to(bundle) or bundle.is_relative_to(dest) or dest==Path(m['original_root']).resolve():raise StorageError('configuration_error','backend restore requires a separate new root')
 dest.mkdir(parents=True,exist_ok=False)
 for rel in m['backend_files']:copy_checked(bundle/rel,dest/rel.removeprefix('backend/objects/'))
 (dest/'.litlib-synthetic-backend.json').write_text(json.dumps({'synthetic':True,'root':str(dest),'namespace':m['namespace']}),'utf-8')
 return {'backend':str(dest),'objects':len(m['physical_closure']),'client_payload_copied':False}

def restore(bundle,destination,object_backend):
 bundle=owned_task_path(bundle);m=verify_bundle(bundle);dest=owned_task_path(destination)
 if dest==Path(m['original_root']).resolve():raise StorageError('configuration_error','restore requires a new root, not original source')
 if dest==bundle or dest.is_relative_to(bundle) or bundle.is_relative_to(dest):raise StorageError('configuration_error','restore must use a new separate root')
 backend=owned_task_path(object_backend)
 if backend.is_relative_to(dest) or dest.is_relative_to(backend):raise StorageError('configuration_error','backend must be outside restored client')
 marker=json.loads((backend/'.litlib-synthetic-backend.json').read_text('utf-8'))
 if marker!={'synthetic':True,'root':str(backend),'namespace':m['namespace']}:raise StorageError('configuration_error','separate backend marker mismatch')
 for h,size in m['physical_closure'].items():
  if hash_file(backend/(m['namespace']+f'objects/sha256/{h[:2]}/{h}'))!=(h,size):raise StorageError('checksum_mismatch','separate backend closure invalid')
 dest.mkdir(parents=True,exist_ok=False)
 for rel in m['client_files']:copy_checked(bundle/rel,dest/rel.removeprefix('client/'))
 old=Path(m['original_root']);oldstr=str(old)
 def relocate(value):
  if isinstance(value,str) and (value==oldstr or value.startswith(oldstr+os.sep)):return str(dest)+value[len(oldstr):]
  if isinstance(value,list):return [relocate(v) for v in value]
  if isinstance(value,dict):return {k:relocate(v) for k,v in value.items()}
  return value
 specs={'library/literature.sqlite':{'source_files':['source_path','archive_path'],'literature_parse_runs':['source_path','output_dir','content_md_path','content_json_path','package_path'],'library_migration_files':['original_source_path','library_path'],'duplicate_candidates':['source_path'],'storage_paths':['path'],'storage_operations':['pending','request'],'storage_staging_files':['pending'],'storage_producer_jobs':['artifacts']},'research/research.sqlite':{'research_sources':['source_path','snapshot_path']}}
 for relative,tables in specs.items():
  with sqlite3.connect(dest/relative) as c:
   for table,requested in tables.items():
    available={r[1] for r in c.execute('PRAGMA table_info('+table+')')}
    for column in set(requested)&available:
     for rowid,value in c.execute('SELECT rowid,'+column+' FROM '+table).fetchall():
      if not value:continue
      updated=json.dumps(relocate(json.loads(value))) if column in ('request','artifacts') else relocate(value)
      if updated!=value:c.execute('UPDATE '+table+' SET '+column+'=? WHERE rowid=?',(updated,rowid))
   if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise StorageError('checksum_mismatch','restored database integrity failure')
 environment={'LITLIB_STORAGE_MODE':'immutable','LITLIB_SYNTHETIC_ROOT':str(dest),'LITLIB_LIBRARY_ROOT':str(dest/'library'),'LITLIB_DB_PATH':str(dest/'library/literature.sqlite'),'LITLIB_RESEARCH_ROOT':str(dest/'research'),'LITLIB_RESEARCH_DB':str(dest/'research/research.sqlite'),'LITLIB_STORAGE_BACKEND':'local','LITLIB_STORAGE_ROOT':m['namespace'],'LITLIB_STORAGE_LOCAL_OBJECTS':str(backend),'LITLIB_STORAGE_CACHE':str(dest/'cache'),'LITLIB_STORAGE_STAGING':str(dest/'staging')}
 (dest/'.litlib-synthetic.json').write_text(json.dumps({'synthetic':True,'root':str(dest),'restored_snapshot':m['id']}),'utf-8')
 (dest/'restore-environment.json').write_text(json.dumps(environment,indent=2),'utf-8')
 (dest/'restore-receipt.json').write_text(json.dumps({'snapshot':m['id'],'root':str(dest),'cache_copied':False,'fallback_configuration':'disabled by explicit immutable roots','consumption_validation':'not_run','client_copied_files':m['client_files'],'object_backend':str(backend),'relocation':'explicit path fields only; scientific payload/text unchanged','formal_restore':False},indent=2),'utf-8')
 return environment

def verify_restored_client(bundle,root):
 bundle=owned_task_path(bundle);m=verify_bundle(bundle);root=owned_task_path(root)
 environment=json.loads((root/'restore-environment.json').read_text('utf-8'));previous={k:os.environ.get(k) for k in environment}
 try:
  os.environ.update(environment);client,service=synthetic_context()
  if client!=root:raise StorageError('configuration_error','restore environment root mismatch')
  if Path(m['original_root']).exists():raise StorageError('configuration_error','client-only proof requires original root unavailable')
  service.cache.clear();reads=[]
  for b in m['bindings']:
   with service.read(b['identity'],b['role'],b['version']) as p:
    if hash_file(p)!=(b['sha256'],b['bytes']):raise StorageError('checksum_mismatch','restored consumption fingerprint failed')
   reads.append({'identity':b['identity'],'role':b['role'],'version':b['version'],'sha256':b['sha256']})
  with sqlite3.connect((root/'research/research.sqlite').as_uri()+'?mode=ro',uri=True) as c:
   for snap in m['research_snapshots']:
    row=c.execute('SELECT content_text,content_sha256 FROM research_text_snapshots WHERE id=?',(snap['id'],)).fetchone()
    if not row or hashlib.sha256(row[0].encode()).hexdigest()!=snap['content_sha256'] or row[1]!=snap['content_sha256']:raise StorageError('checksum_mismatch','fixed research text fingerprint failed')
  service.cache.clear()
  allowed={p.removeprefix('client/') for p in m['client_files']}|{'.litlib-synthetic.json','restore-environment.json','restore-receipt.json','consumption-verification.json'}
  files=sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file())
  for rel in files:
   if rel.startswith(('cache/','staging/')) or rel.endswith(('-wal','-shm','.lock')):continue
   if rel not in allowed:raise StorageError('configuration_error','unexpected durable client file: '+rel)
  if list(service.cache.root.glob('*.asset')):raise StorageError('configuration_error','cache payload not cleared')
  result={'snapshot':m['id'],'status':'passed','asset_fingerprints':reads,'fixed_research_snapshots':len(m['research_snapshots']),'client_files':files,'no_durable_local_asset_copies':True,'cache_payloads_after_clear':0,'fallback_configuration':'explicit roots; no filesystem fallback','old_root_exists_at_validation':Path(m['original_root']).exists(),'validation':'actual resolver reads plus SHA/size and fixed text hashes; no HTTP/browser'}
  (root/'consumption-verification.json').write_text(json.dumps(result,indent=2),'utf-8');return result
 finally:
  for k,v in previous.items():
   if v is None:os.environ.pop(k,None)
   else:os.environ[k]=v
