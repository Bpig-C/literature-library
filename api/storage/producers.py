"""Opt-in producer adapter. Business identities remain catalog-owned.

Durable job precedes filesystem work; registrations use deterministic operation
IDs. Explicit resume completes artifacts_ready without running the parser again.
Foundation execution is globally serial across parse/resume/release.
"""
import hashlib,json,os,re,sqlite3,zipfile
from pathlib import Path
from datetime import datetime,timezone
from .core import StorageError,file_lock,hash_file
from .runtime import configured_service,required_path

def now():return datetime.now(timezone.utc).isoformat()
def job_id(kind,identity):return kind+'-'+hashlib.sha256(identity.encode()).hexdigest()
def lock_path(service):return service.registry.catalog.with_suffix('.producer.lock')

def _source_lock_path(service,source_id):
 """Canonical safe lock key; the global ownership guard remains authoritative."""
 key=source_id if re.fullmatch(r'[A-Za-z0-9_.-]{1,160}',source_id) else hashlib.sha256(source_id.encode()).hexdigest()
 return service.registry.catalog.with_suffix(f'.producer-{key}.lock')

def _parse_concurrency():
 """Legacy setting reader; foundation producer execution remains serial."""
 try:return max(1,int(os.environ.get('LITLIB_PARSE_CONCURRENCY','1')))
 except (ValueError,TypeError):return 1

def register_ingested_sources(source_ids,service=None):
 service=service or configured_service();results=[]
 with file_lock(lock_path(service)):
  for source_id in source_ids:
   jid=job_id('pdf',source_id)
   with service.registry.conn(write=True) as c:
    prior=c.execute('SELECT * FROM storage_producer_jobs WHERE id=?',(jid,)).fetchone()
    if prior and prior['state']=='registered':
     results.append(dict(prior));continue
    row=c.execute('SELECT source_path,content_sha256,file_size FROM source_files WHERE id=?',(source_id,)).fetchone()
    if not row:raise StorageError('not_found','producer source absent')
    artifacts=[{'identity':source_id,'role':'pdf','version':1,'source':row['source_path'],'member':None,'virtual_path':None}]
    if prior:
     artifacts=json.loads(prior['artifacts'])
     if not artifacts or artifacts[0]['source']!=row['source_path']:raise StorageError('revision_conflict','ingest ownership path changed')
    if hash_file(Path(row['source_path']))!=(row['content_sha256'],row['file_size']):raise StorageError('checksum_mismatch','source changed after ingest')
    c.execute("INSERT OR IGNORE INTO storage_producer_jobs(id,kind,source_file_id,version,state,artifacts) VALUES(?,'pdf',?,1,'artifacts_ready',?)",(jid,source_id,json.dumps(artifacts)))
    if prior and prior['state']=='preparing':c.execute("UPDATE storage_producer_jobs SET state='artifacts_ready' WHERE id=?",(jid,))
   results.append(_finish(service,jid))
 return results

def _finish(service,jid):
 with service.registry.conn() as c:job=dict(c.execute('SELECT * FROM storage_producer_jobs WHERE id=?',(jid,)).fetchone() or {})
 if not job:raise StorageError('not_found','producer job unavailable')
 if job['state']=='registered':return job
 if job['state']!='artifacts_ready':raise StorageError('producer_incomplete','complete artifacts unavailable; explicit new parse required')
 try:
  for asset in json.loads(job['artifacts']):
   op=job_id('asset',jid+'\n'+asset['role'])
   with service.registry.conn() as c:prior=c.execute('SELECT state,pending FROM storage_operations WHERE operation_id=?',(op,)).fetchone()
   if prior and (prior['state']=='registered' or Path(prior['pending']).is_file()):service.resume(op)
   else:
    args={k:asset[k] for k in ['identity','role','version','member','virtual_path']}
    service.publish(Path(asset['source']),operation_id=op,**args)
  with service.registry.conn(write=True) as c:
   if job['kind']=='parse':
    md=next(a['virtual_path'] for a in json.loads(job['artifacts']) if a['role']=='md')
    c.execute("UPDATE literature_parse_runs SET status='succeeded',content_md_path=?,backend=?,task_id=?,finished_at=?,error='' WHERE id=?",(md,job['backend'],job['task_id'],now(),job['parse_run_id']))
    from scripts.migrate_sync_parse_status import sync_work_parse_status
    work=c.execute('SELECT work_id FROM literature_parse_runs WHERE id=?',(job['parse_run_id'],)).fetchone()[0]
    sync_work_parse_status(c,work)
   c.execute("UPDATE storage_producer_jobs SET state='registered',error_code=NULL WHERE id=?",(jid,))
 except Exception as error:
  with service.registry.conn(write=True) as c:c.execute('UPDATE storage_producer_jobs SET error_code=? WHERE id=?',(getattr(error,'code','producer_failed'),jid))
  raise
 with service.registry.conn() as c:return dict(c.execute('SELECT * FROM storage_producer_jobs WHERE id=?',(jid,)).fetchone())

def resume_producer(jid,service=None):
 service=service or configured_service()
 with file_lock(lock_path(service)):return _finish(service,jid)

def parse_source(source_id,runner,*,force=False,backend=None,service=None,on_registered=None):
 service=service or configured_service()
 # Foundation release retains global serialization across parse/resume/release.
 # A request-local thread pool must not bypass shared ownership or maintenance.
 with file_lock(lock_path(service)),file_lock(_source_lock_path(service,source_id)):
  with service.registry.conn(write=True) as c:
   source=c.execute('SELECT sf.*,w.language FROM source_files sf JOIN works w ON w.id=sf.work_id WHERE sf.id=?',(source_id,)).fetchone()
   if not source or source['status']=='quarantined':raise StorageError('invalid_request','active source required')
   previous=c.execute("SELECT * FROM storage_producer_jobs WHERE kind='parse' AND source_file_id=? ORDER BY version DESC LIMIT 1",(source_id,)).fetchone()
   if previous and previous['state'] in ('preparing','artifacts_ready'):raise StorageError('producer_incomplete','resume or inspect unfinished producer before new parse')
   if previous and previous['state']=='registered' and not force:return dict(previous)
   version=previous['version']+1 if previous else 1
   # Never reuse a historical local parse row/output, even on first opt-in run.
   rid='LPR-immutable-'+hashlib.sha256((source_id+':'+str(version)).encode()).hexdigest()[:32]
   initial='LPR-'+source_id
   pending=c.execute("SELECT id FROM literature_parse_runs WHERE id=? AND status='pending'",(initial,)).fetchone() if not previous else None
   with sqlite3.connect(required_path('LITLIB_RESEARCH_DB').as_uri()+'?mode=ro',uri=True) as research:
    referenced=research.execute('SELECT 1 FROM research_text_snapshots WHERE parse_run_id=? LIMIT 1',(initial,)).fetchone()
   if pending and not referenced and not c.execute('SELECT 1 FROM storage_bindings WHERE identity=? LIMIT 1',(initial,)).fetchone():rid=initial
   out=required_path('LITLIB_LIBRARY_ROOT')/'works'/source['work_id']/'parsed'/'immutable'/source_id/('v'+str(version))
   if out.exists():raise StorageError('revision_conflict','new parse directory already exists; inspect before retry')
   jid=job_id('parse',rid)
   if rid==initial:
    c.execute("UPDATE literature_parse_runs SET status='running',output_dir=?,started_at=?,content_md_path='',content_json_path='',package_path='',error='' WHERE id=?",(str(out),now(),rid))
   else:c.execute("INSERT INTO literature_parse_runs(id,work_id,source_file_id,source_path,status,output_dir,started_at,error) VALUES(?,?,?,?,'running',?,?,'')",(rid,source['work_id'],source_id,source['source_path'],str(out),now()))
   c.execute("INSERT INTO storage_producer_jobs(id,kind,source_file_id,parse_run_id,version,state) VALUES(?,'parse',?,?,?,'preparing')",(jid,source_id,rid,version))
  if on_registered:on_registered(jid)
  try:
   out.mkdir(parents=True,exist_ok=False)
   owner={'job_id':jid,'catalog':str(service.registry.catalog),'output':str(out),'files':None,'release_state':'producing'}
   (out/'.litlib-producer-owned.json').write_text(json.dumps(owner),'utf-8')
   # Pin verified PDF for parser input; never fallback to original machine path.
   from ..producer_events import capture
   with capture(service.registry,jid) as event:
    event('parser_start',backend=backend or 'auto')
    try:
     with service.read(source_id,'pdf',1) as pdf:ok,msg,used,task=runner(str(pdf),out,source['language'] or '',backend=backend)
     event('parser_returned',backend=used,task_id=task)
     if not ok:raise StorageError('producer_failed','parser failed; inspect job diagnostics')
    except Exception as error:
     event('failed',error_code=getattr(error,'code','producer_failed'))
     raise
   _stage_parse_assets(service,jid,out,used,task,owner)
  except Exception as error:
   with service.registry.conn(write=True) as c:
    c.execute("UPDATE storage_producer_jobs SET state='failed',error_code=? WHERE id=?",(getattr(error,'code','producer_failed'),jid))
    c.execute("UPDATE literature_parse_runs SET status='failed',error=?,finished_at=? WHERE id=?",(getattr(error,'code','producer_failed'),now(),rid))
   raise
  return _finish(service,jid)

def _stage_parse_assets(service,jid,out,used,task,owner):
 with service.registry.conn() as c:job=c.execute('SELECT parse_run_id,version FROM storage_producer_jobs WHERE id=?',(jid,)).fetchone()
 rid,version=job['parse_run_id'],job['version']
 files=sorted(p for p in out.rglob('*') if p.is_file() and p.name!='.litlib-producer-owned.json')
 if not (out/'content.md').is_file():raise StorageError('producer_incomplete','parser produced no content.md')
 package=out/'immutable-assets.zip'
 if package.exists() or any(p.is_symlink() for p in out.rglob('*')):raise StorageError('unsafe_package','unexpected parser package or symlink')
 with zipfile.ZipFile(package,'x',zipfile.ZIP_DEFLATED) as z:
  for p in files:z.write(p,p.relative_to(out).as_posix())
 owner['files']={p.relative_to(out).as_posix():list(hash_file(p)) for p in files+[package]}
 owner['release_state']='ready'
 (out/'.litlib-producer-owned.json').write_text(json.dumps(owner),'utf-8')
 assets=[]
 for p in files:
  rel=p.relative_to(out).as_posix()
  role={'content.md':'md','content.merged.md':'merged','content.json':'json','detail.json':'detail'}.get(rel)
  if rel.startswith('images/') and len(Path(rel).parts)==2:role='image:'+p.name
  if role:assets.append({'identity':rid,'role':role,'version':version,'source':str(package),'member':rel,'virtual_path':str(p)})
 assets[0]['owned_files']=owner['files']
 with service.registry.conn(write=True) as c:c.execute("UPDATE storage_producer_jobs SET state='artifacts_ready',artifacts=?,backend=?,task_id=? WHERE id=?",(json.dumps(assets),used,task,jid))

def recover_cloud_producer(jid,runner,service=None):
 """Query/download an existing cloud task; never submit another task/version."""
 service=service or configured_service()
 with file_lock(lock_path(service)):
  with service.registry.conn() as c:
   job=dict(c.execute('SELECT * FROM storage_producer_jobs WHERE id=?',(jid,)).fetchone() or {})
   if not job:raise StorageError('not_found','producer not found')
   if job['state'] in ('registered','artifacts_ready'):return _finish(service,jid)
   if job['kind']!='parse' or job['backend']!='vlm' or not job['task_id']:raise StorageError('producer_incomplete','known VLM task required; never resubmit unknown tasks')
   latest=c.execute("SELECT id FROM storage_producer_jobs WHERE kind='parse' AND source_file_id=? ORDER BY version DESC LIMIT 1",(job['source_file_id'],)).fetchone()
   if latest[0]!=jid:raise StorageError('revision_conflict','later parse exists; inspect historical job before recovery')
   run=c.execute('SELECT work_id,output_dir FROM literature_parse_runs WHERE id=?',(job['parse_run_id'],)).fetchone()
   source=c.execute('SELECT sf.status,w.read_status FROM source_files sf JOIN works w ON w.id=sf.work_id WHERE sf.id=?',(job['source_file_id'],)).fetchone()
   if not source or source[0]!='active' or source[1] in ('quarantined','archived'):raise StorageError('revision_conflict','source is not active')
  out=Path(run['output_dir']);library=required_path('LITLIB_LIBRARY_ROOT')
  expected=library/'works'/run['work_id']/'parsed'/'immutable'/job['source_file_id']/('v'+str(job['version']))
  if out.resolve()!=expected.resolve() or not out.resolve().is_relative_to(library) or out.is_symlink() or (hasattr(out,'is_junction') and out.is_junction()):raise StorageError('configuration_error','recovery output outside owned path')
  if any(p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()) for p in out.rglob('*')):raise StorageError('configuration_error','linked recovery output refused')
  marker=out/'.litlib-producer-owned.json'
  if not marker.is_file():raise StorageError('producer_incomplete','owned output marker unavailable')
  owner=json.loads(marker.read_text('utf-8'))
  if owner.get('job_id')!=jid or owner.get('catalog')!=str(service.registry.catalog) or owner.get('output')!=str(out) or owner.get('release_state')!='producing' or (out/'immutable-assets.zip').exists():raise StorageError('producer_incomplete','partial package requires inspection; do not overwrite')
  from ..producer_events import capture
  try:
   with capture(service.registry,jid) as event:
    event('recover_existing_task',task_id=job['task_id'],backend='vlm')
    with service.read(job['source_file_id'],'pdf',1) as pdf:ok,msg,used,task=runner(str(pdf),out,job['task_id'])
    if not ok:raise StorageError('producer_incomplete','existing cloud result not ready; inspect diagnostics')
    if task!=job['task_id'] or used!='vlm':raise StorageError('revision_conflict','recovery changed task or backend')
   _stage_parse_assets(service,jid,out,used,task,owner)
  except Exception as error:
   with service.registry.conn(write=True) as c:c.execute("UPDATE storage_producer_jobs SET state='failed',error_code=? WHERE id=?",(getattr(error,'code','producer_failed'),jid))
   raise
  return _finish(service,jid)

def release_producer_output(jid,service=None):
 """Explicit, conservative release of owned successful parse output only."""
 service=service or configured_service()
 with file_lock(lock_path(service)):
  with service.registry.conn() as c:
   job=c.execute('SELECT * FROM storage_producer_jobs WHERE id=?',(jid,)).fetchone()
   if not job or job['kind']!='parse' or job['state']!='registered':raise StorageError('producer_incomplete','registered parse job required; failed/unregistered material preserved')
   run=c.execute('SELECT work_id,output_dir FROM literature_parse_runs WHERE id=?',(job['parse_run_id'],)).fetchone()
  library=required_path('LITLIB_LIBRARY_ROOT');out=Path(run['output_dir'])
  expected=library/'works'/run['work_id']/'parsed'/'immutable'/job['source_file_id']/('v'+str(job['version']))
  # Resolve/check the final absolute target before any removal; reject links.
  if out.absolute()!=expected.absolute() or not out.resolve().is_relative_to(library.resolve()):raise StorageError('configuration_error','owned output outside expected library path')
  if not out.exists():return {'job_id':jid,'released':False,'reason':'already absent; no ownership inferred'}
  if out.is_symlink() or any(p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()) for p in [out,*out.rglob('*')]):raise StorageError('configuration_error','linked output preserved')
  marker=out/'.litlib-producer-owned.json'
  if not marker.is_file():raise StorageError('configuration_error','unmarked legacy output preserved')
  owner=json.loads(marker.read_text('utf-8'))
  if owner.get('job_id')!=jid or owner.get('catalog')!=str(service.registry.catalog) or owner.get('output')!=str(out) or not isinstance(owner.get('files'),dict):raise StorageError('configuration_error','output ownership incomplete')
  owned=owner['files'];present={p.relative_to(out).as_posix() for p in out.rglob('*') if p.is_file() and p!=marker}
  artifacts=json.loads(job['artifacts'])
  if not artifacts or owned!=artifacts[0].get('owned_files'):raise StorageError('configuration_error','ownership differs from durable producer journal')
  if present-set(owned) or (owner.get('release_state')!='releasing' and present!=set(owned)):raise StorageError('revision_conflict','unknown/missing output files preserved')
  for name in present:
   if list(hash_file(out/name))!=owned[name]:raise StorageError('checksum_mismatch','changed output preserved')
  # Actual fixed asset consumption must succeed before local destruction.
  for asset in artifacts:
   binding=service.registry.binding(asset['identity'],asset['role'],asset['version'])
   with service.read(asset['identity'],asset['role'],asset['version']) as path:
    if hash_file(path)!=(binding['sha256'],binding['bytes']):raise StorageError('checksum_mismatch','registered asset not consumable')
  owner['release_state']='releasing';temporary=marker.with_suffix('.part')
  temporary.write_text(json.dumps(owner),'utf-8');temporary.replace(marker)
  for name in sorted(present):
   p=out/name
   if list(hash_file(p))!=owned[name]:raise StorageError('checksum_mismatch','output changed during release; remaining files preserved')
   p.unlink()
  for directory in sorted((p for p in out.rglob('*') if p.is_dir()),key=lambda p:len(p.parts),reverse=True):directory.rmdir()
  marker.unlink();out.rmdir()
  return {'job_id':jid,'released':True,'files':len(present),'scope':'owned registered parse output; originals/failed/unmarked output preserved'}

def trigger_production(body,runner,service=None):
 service=service or configured_service()
 with service.registry.conn() as c:
  where="sf.status!='quarantined'";args=[]
  # S2: source_file_ids takes precedence for exact source selection; work_ids
  # selects all sources of those works; both may be combined (OR semantics
  # at the SQL level is confusing, so source_file_ids filters within the
  # work selection when both are present).
  if getattr(body,'source_file_ids',None):
   where+=' AND sf.id IN ('+','.join('?' for _ in body.source_file_ids)+')';args=list(body.source_file_ids)
   if body.work_ids:where+=' AND sf.work_id IN ('+','.join('?' for _ in body.work_ids)+')';args.extend(body.work_ids)
  elif body.work_ids:where+=' AND sf.work_id IN ('+','.join('?' for _ in body.work_ids)+')';args=list(body.work_ids)
  elif not body.all_pending:raise StorageError('invalid_request','explicit selector required (work_ids, source_file_ids, or all_pending)')
  if not body.force:where+=" AND NOT EXISTS(SELECT 1 FROM storage_producer_jobs j WHERE j.source_file_id=sf.id AND j.kind='parse' AND j.state='registered')"
  sources=list(c.execute('SELECT sf.id,sf.work_id FROM source_files sf WHERE '+where+' ORDER BY sf.id',args))
 results=[]
 for source in sources:
  try:
   job=parse_source(source['id'],runner,force=body.force,backend=body.backend,service=service)
   results.append({'work_id':source['work_id'],'source_file_id':source['id'],'parse_run_id':job['parse_run_id'],'version':job['version'],'status':'succeeded','job_id':job['id']})
  except Exception as error:results.append({'work_id':source['work_id'],'source_file_id':source['id'],'status':'failed','error':getattr(error,'code','producer_failed')})
 return {'triggered':len(results),'succeeded':sum(r['status']=='succeeded' for r in results),'failed':sum(r['status']=='failed' for r in results),'results':results}
