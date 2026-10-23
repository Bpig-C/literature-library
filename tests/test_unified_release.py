import gc,hashlib,json,os,sqlite3,subprocess,zipfile
from pathlib import Path
import pytest
from api.storage.core import Namespace,Registry,StorageError,hash_file
from api.storage.backends import LocalObjectBackend
from api.storage.runtime import configured_service
from api.storage.producers import parse_source
from api.storage.ingest_lifecycle import release_ingested_pdf
from api.storage.producers import job_id
from api.storage.unified_release import publish_snapshot,restore_release
from api.research_context import ResearchContext
from api.research_schema import apply_schema
from api.research_service import ResearchService
from api.research_runtime_assets import presentation_assets
from scripts.literature_ingest import ensure_core_schema,build_ingest_plan,execute_plan

CODE=Path(__file__).resolve().parents[1]
def assets(root):
    root.mkdir(parents=True)
    for name,value in [('research-display.json',{'records':{},'artifact_version':'synthetic'}),('ontology-display.json',{'concepts':[{'id':'synthetic','zh':'合成概念','nature':'risk'}],'natureLabels':{'risk':'合成标签'}}),('autonomy-risk-v1.json',{'version':'autonomy-risk-v1','concepts':[{'id':'synthetic','definition':'Synthetic fixture only'}]}),('ontology-proposal.json',{'changed_keys':[]}),('review-cards-v5.json',{'cards':[]})]:
        (root/name).write_text(json.dumps(value),'utf-8')
    (root/'ontology-display-source.js').write_text('// synthetic provenance, not executed','utf-8')
    index={p.name:{'sha256':hash_file(p)[0],'bytes':p.stat().st_size} for p in root.iterdir()}
    (root/'assets-manifest.json').write_text(json.dumps(index),'utf-8')
    return {p.name:p for p in root.iterdir()}

@pytest.fixture
def release(tmp_path,monkeypatch):
    root=tmp_path/'source';library=root/'library';(library/'_inbox').mkdir(parents=True)
    with sqlite3.connect(library/'literature.sqlite') as c:
        ensure_core_schema(c);c.execute('CREATE TABLE work_codes(work_id TEXT,source_file_id TEXT,code TEXT,reason TEXT,UNIQUE(work_id,code))')
    c.close();asset_files=assets(root/'research/assets');monkeypatch.setenv('LITLIB_RESEARCH_ASSETS_ROOT',str(root/'research/assets'))
    ctx=ResearchContext(root/'research',root/'research/research.sqlite');assert apply_schema(ctx,backup=False)['ok']
    ns='research/agent-loss-of-control/literature/test/unified-'+tmp_path.name+'/'
    Registry(library/'literature.sqlite',Namespace(ns)).initialize()
    remote=tmp_path/'remote';backend=LocalObjectBackend(remote)
    env={'LITLIB_STORAGE_MODE':'immutable','LITLIB_LIBRARY_ROOT':str(library),'LITLIB_DB_PATH':str(library/'literature.sqlite'),'LITLIB_RESEARCH_ROOT':str(root/'research'),'LITLIB_RESEARCH_DB':str(ctx.db_path),'LITLIB_STORAGE_BACKEND':'local','LITLIB_STORAGE_ROOT':ns,'LITLIB_STORAGE_LOCAL_OBJECTS':str(remote),'LITLIB_STORAGE_CACHE':str(root/'cache'),'LITLIB_STORAGE_STAGING':str(root/'staging')}
    for k,v in env.items():monkeypatch.setenv(k,v)
    import pymupdf
    doc=pymupdf.open();p=doc.new_page();p.insert_text((40,40),'Synthetic unified recovery');doc.save(library/'_inbox/synthetic.pdf');doc.close()
    plan=build_ingest_plan(library);execute_plan(plan,purpose='Synthetic storage lifecycle verification',no_backup=True);action=plan.ingests[0];service=configured_service()
    release_ingested_pdf(job_id('pdf',action.source_file_id),service)
    def parser(pdf,out,*args,**kwargs):
        (out/'content.md').write_text('# synthetic immutable text','utf-8');(out/'content.json').write_text('{"synthetic":true}','utf-8')
        return True,'','synthetic','synthetic-task'
    job=parse_source(action.source_file_id,parser,service=service)
    # Frozen selections/remaining budgets are part of catalog recovery too.
    from api.parse_plans import Selection,preview,accept
    with service.registry.conn(read_only=True) as read:
        frozen_plan=preview(read,Selection(source_file_ids=[action.source_file_id],backend='vlm'))
    accept(service.registry,frozen_plan,'synthetic-queued-recovery-plan',1,1,100)
    snap=ResearchService(ctx).import_registered_source(work_id=action.work_id,source_file_id=action.source_file_id,parse_run_id=job['parse_run_id'],version=1)
    editing=root/'research/editing/working.md';editing.parent.mkdir();editing.write_text('synthetic unaccepted draft','utf-8')
    files={'research/assets/'+name:path for name,path in asset_files.items()};files['research/editing/working.md']=editing
    frontend=tmp_path/'frontend.zip'
    with zipfile.ZipFile(frontend,'x') as z:z.writestr('index.html','<html>Synthetic frontend fixture</html>')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=CODE).decode().strip()
    tracked=subprocess.check_output(['git','ls-tree','-r','--name-only','-z','HEAD'],cwd=CODE).decode().rstrip('\0').split('\0')
    code={'url':str(CODE),'commit':commit,'files':{p:hash_file(CODE/p)[0] for p in tracked},'locks':{p:hash_file(CODE/p)[0] for p in ['uv.lock','web/npm-shrinkwrap.json']}}
    with service.registry.conn() as c:bindings=[dict(r) for r in c.execute('SELECT * FROM storage_bindings ORDER BY identity,role,version')]
    config={'storage_namespace':ns,'cache_bytes':64*1024**2,'schema_version':6,'contract_version':5}
    published=publish_snapshot(tmp_path/'snapshot',catalog=service.registry.catalog,research=ctx.db_path,files=files,config=config,code=code,frontend=frontend,namespace=ns,backend=backend,asset_index={'bindings':bindings})
    return root,backend,ns,published,action,job,snap,config,code,files,frontend

def test_unified_cold_restore_essential_only_and_fixed_consumption(release,tmp_path,monkeypatch):
    root,backend,ns,published,action,job,snap,*_=release;entry=published['manifest_object'];target=tmp_path/'new-client'
    downloads=[];original=backend.download
    def count(*args,**kwargs):downloads.append(args[0]);return original(*args,**kwargs)
    backend.download=count
    gc.collect();root.rename(tmp_path/'old-root-unavailable')
    receipt=restore_release(backend,manifest_key=entry['key'],manifest_sha256=entry['sha256'],destination=target,namespace=ns,expected_git_url=str(CODE))
    assert not (target/'cache').exists() and not list(target.rglob('*.pdf')) and not list(target.rglob('*.zip'))
    assert not any(p['sha256']==action.content_sha256 for p in published['manifest']['essentials'].values())
    assert Namespace(ns).key(action.content_sha256) not in downloads
    assert receipt['credentials_copied'] is False and published['long_term_asset_objects_reuploaded']==0
    with sqlite3.connect(target/'data/library/literature.sqlite') as restored_catalog:
        assert restored_catalog.execute('SELECT purpose FROM ingest_notes WHERE work_id=?',(action.work_id,)).fetchone()[0]=='Synthetic storage lifecycle verification'
        assert restored_catalog.execute('SELECT max_submissions FROM parse_plans WHERE request_id=?',('synthetic-queued-recovery-plan',)).fetchone()[0]==1
        assert restored_catalog.execute('SELECT state,reserved FROM parse_plan_items').fetchone()==('queued',0)
        assert restored_catalog.execute('SELECT count(*) FROM producer_diagnostics').fetchone()[0]==1
    for k,v in json.loads((target/'environment.json').read_text('utf-8')).items():monkeypatch.setenv(k,v)
    assert presentation_assets()['ontology']['concepts'][0]['zh']=='合成概念'
    service=configured_service()
    with service.read(action.source_file_id,'pdf',1) as pdf:assert hash_file(pdf)[0]==action.content_sha256
    with service.read(job['parse_run_id'],'md',1) as md:assert md.read_text()=='# synthetic immutable text'
    research=ResearchService(ResearchContext(target/'data/research',target/'data/research/research.sqlite'))
    assert research.read_text(snap['source_id'],snapshot_id=snap['snapshot_id'])['content_text']=='# synthetic immutable text'
    assert (target/'data/research/editing/working.md').read_text()=='synthetic unaccepted draft'
    service.cache.clear();assert not list((target/'cache').glob('*.asset'))

def test_restore_failure_and_existing_destination_preserved(release,tmp_path):
    root,backend,ns,published,*_=release;entry=published['manifest_object'];existing=tmp_path/'existing';existing.mkdir();(existing/'keep').write_text('keep')
    with pytest.raises(StorageError):restore_release(backend,manifest_key=entry['key'],manifest_sha256=entry['sha256'],destination=existing,namespace=ns)
    assert (existing/'keep').read_text()=='keep'
    victim=next(iter(published['manifest']['essentials'].values()));backend.path(victim['key']).write_bytes(b'corrupt')
    with pytest.raises(StorageError):restore_release(backend,manifest_key=entry['key'],manifest_sha256=entry['sha256'],destination=tmp_path/'failed',namespace=ns)
    assert not (tmp_path/'failed').exists()

def test_snapshot_reuses_objects_and_rejects_secret_configuration(release,tmp_path):
    root,backend,ns,published,action,job,snap,config,code,files,frontend=release
    puts=[];original=backend.put_immutable
    def count(*args,**kwargs):puts.append(args[0]);return original(*args,**kwargs)
    backend.put_immutable=count
    repeat=publish_snapshot(tmp_path/'repeat',catalog=root/'library/literature.sqlite',research=root/'research/research.sqlite',files=files,config=config,code=code,frontend=frontend,namespace=ns,backend=backend,asset_index=published['manifest']['asset_index'])
    assert puts==[repeat['manifest_object']['key']]
    with pytest.raises(StorageError):publish_snapshot(tmp_path/'secret',catalog=root/'library/literature.sqlite',research=root/'research/research.sqlite',files=files,config={**config,'OSS_ACCESS_KEY_SECRET':'never-save'},code=code,frontend=frontend,namespace=ns,backend=backend,asset_index={})
    assert not (tmp_path/'secret').exists()

def test_restore_rejects_schema_contract_mismatch(release,tmp_path):
    root,backend,ns,published,*_=release
    manifest=json.loads(json.dumps(published['manifest']))
    manifest['configuration']['schema_version']=999
    path=tmp_path/'wrong-version.json';path.write_text(json.dumps(manifest),'utf-8')
    sha,size=hash_file(path);key=Namespace(ns).key(sha);backend.put_immutable(key,path)
    with pytest.raises(StorageError,match='schema/contract'):
        restore_release(backend,manifest_key=key,manifest_sha256=sha,destination=tmp_path/'wrong-version',namespace=ns)
    assert not (tmp_path/'wrong-version').exists()


def test_failed_cloud_task_recovers_after_full_cold_restore(release,tmp_path,monkeypatch):
    from api import parse_plans
    from api.producer_events import emit
    from api.storage.producers import recover_cloud_producer
    root,backend,ns,published,action,old_job,snap,config,code,files,frontend=release
    service=configured_service()
    with service.registry.conn(read_only=True) as conn:
        pid=conn.execute('SELECT id FROM parse_plans').fetchone()[0]
    def interrupted(*args,**kwargs):
        emit('submitting',backend='vlm')
        emit('upstream_submitted',task_id='existing-cloud-task')
        raise TimeoutError('download interrupted')
    failed=parse_plans.step(service,pid,interrupted,count_pages=lambda p:1)
    jid=failed['items'][0]['job_id']
    assert failed['items'][0]['producer']['state']=='failed'
    receipt=publish_snapshot(tmp_path/'failed-cloud-snapshot',catalog=service.registry.catalog,
        research=root/'research/research.sqlite',files=files,config=config,code=code,frontend=frontend,
        namespace=ns,backend=backend,asset_index=published['manifest']['asset_index'])
    entry=receipt['manifest_object'];target=tmp_path/'cold-cloud-client'
    gc.collect();assert root.resolve().is_relative_to(tmp_path.resolve())
    root.rename(tmp_path/'old-cloud-root-unavailable')
    restore_release(backend,manifest_key=entry['key'],manifest_sha256=entry['sha256'],
        destination=target,namespace=ns,expected_git_url=str(CODE))
    assert not list(target.rglob('.litlib-producer-owned.json'))
    for k,v in json.loads((target/'environment.json').read_text('utf-8')).items():monkeypatch.setenv(k,v)
    restored=configured_service();calls=[]
    def recover(pdf,out,task):
        assert task=='existing-cloud-task';calls.append(task)
        (out/'content.md').write_text('Recovered existing cloud output','utf-8')
        return True,'ok','vlm',task
    recovered=recover_cloud_producer(jid,recover,restored)
    assert recovered['id']==jid and recovered['version']==2 and calls==['existing-cloud-task']
    complete=parse_plans.step(restored,pid,lambda *a,**k:pytest.fail('must not submit again'))
    assert complete['action']=='complete' and complete['budget']==failed['budget']
    with restored.read(recovered['parse_run_id'],'md',2) as md:
        assert md.read_text()=='Recovered existing cloud output'


def test_async_queue_paused_cloud_task_resumes_after_cold_restore(release,tmp_path,monkeypatch):
    from api.parse_queue import Queue,Limits
    from api.storage.authority import Authority
    from test_async_parse import Driver,Clock,run_all
    root,backend,ns,published,action,old_job,snap,config,code,files,frontend=release
    service=configured_service();owner='synthetic-async-owner-'+'x'*32
    a=Authority(backend,ns,owner,0,tmp_path/'authority');a.initialize()
    clock=Clock();q=Queue(service,a,clock=clock,limits=Limits(poll_seconds=1,submit_per_minute=600,poll_per_minute=600))
    with service.registry.conn(read_only=True) as conn:pid=conn.execute('SELECT id FROM parse_plans').fetchone()[0]
    task=q.enqueue(pid)['tasks'][0];driver=Driver()
    q.run_one(driver);clock.tick();q.run_one(driver);clock.tick()
    paused=q.action(task['id'],'pause','Prepare recoverable snapshot')
    assert paused['producer']['task_id'] and len(driver.submits)==1
    snapshot=publish_snapshot(tmp_path/'async-snapshot',catalog=service.registry.catalog,research=root/'research/research.sqlite',
        files=files,config=config,code=code,frontend=frontend,namespace=ns,backend=backend,asset_index=published['manifest']['asset_index'])
    entry=snapshot['manifest_object'];target=tmp_path/'async-cold'
    gc.collect();assert root.resolve().is_relative_to(tmp_path.resolve());root.rename(tmp_path/'old-async-unavailable')
    restore_release(backend,manifest_key=entry['key'],manifest_sha256=entry['sha256'],destination=target,namespace=ns,expected_git_url=str(CODE))
    assert not list(target.rglob('.litlib-producer-owned.json'))
    for k,v in json.loads((target/'environment.json').read_text('utf-8')).items():monkeypatch.setenv(k,v)
    restored=configured_service();new_authority=Authority(backend,ns,owner,0,target/'data/.authority')
    current=Queue(restored,new_authority,clock=clock)
    assert current.status(task['id'])['state']=='paused'
    current.action(task['id'],'resume','Continue same provider task after restore')
    class ExistingOnly(Driver):
        def submit(self,*args,**kwargs):pytest.fail('cold restore must not create cloud task')
    reader=ExistingOnly();completed=run_all(current,reader,pid)
    assert completed['action']=='complete' and completed['budget']['reserved_submissions']==1
    assert reader.downloads==driver.submits


def test_native_batch_upload_links_and_mappings_survive_cold_restore(release,tmp_path,monkeypatch):
    import base64
    from api import parse_plans
    from api.parse_queue import Queue,Limits
    from api.storage.authority import Authority
    from test_async_parse import Clock,run_all
    from test_native_batches import Native,until
    root,backend,ns,published,action,old_job,snap,config,code,files,frontend=release
    library=root/'library'
    import pymupdf
    doc=pymupdf.open();page=doc.new_page();page.insert_text((40,40),'Second synthetic native batch paper')
    doc.save(library/'_inbox/second.pdf');doc.close()
    intake=build_ingest_plan(library);execute_plan(intake,purpose='native batch cold restore verification',no_backup=True)
    service=configured_service();owner='native-owner-'+'x'*32
    monkeypatch.setenv('LITLIB_PARSE_UPLOAD_KEY',base64.urlsafe_b64encode(b'n'*32).decode())
    auth=Authority(backend,ns,owner,0,tmp_path/'native-authority');auth.initialize()
    clock=Clock();q=Queue(service,auth,clock=clock,limits=Limits(upstream=2,batch_size=2,poll_seconds=1,submit_per_minute=600,poll_per_minute=600))
    with service.registry.conn(read_only=True) as conn:
        plan=parse_plans.preview(conn,parse_plans.Selection(backend='vlm',work_ids=[action.work_id,intake.ingests[0].work_id]))
    pid=parse_plans.accept(service.registry,plan,'native-cold-plan',2,2,100)['plan_id']
    tasks=q.enqueue(pid)['tasks'];driver=Native();until(q,driver,lambda:bool(driver.posts))
    assert len(driver.posts)==1 and len(driver.posts[0])==2 and not driver.puts
    for task in tasks:q.action(task['id'],'pause','Checkpoint before uploading files')
    q.maintenance('drain','native-cold-snapshot');q.maintenance('snapshot','native-cold-snapshot')
    with service.registry.conn(read_only=True) as conn:bindings=[dict(r) for r in conn.execute('SELECT * FROM storage_bindings ORDER BY identity,role,version')]
    snapshot=publish_snapshot(tmp_path/'native-snapshot',catalog=service.registry.catalog,research=root/'research/research.sqlite',
        files=files,config=config,code=code,frontend=frontend,namespace=ns,backend=backend,asset_index={'bindings':bindings})
    entry=snapshot['manifest_object'];target=tmp_path/'native-cold'
    gc.collect();assert root.resolve().is_relative_to(tmp_path.resolve());root.rename(tmp_path/'native-old-unavailable')
    restore_release(backend,manifest_key=entry['key'],manifest_sha256=entry['sha256'],destination=target,namespace=ns,expected_git_url=str(CODE))
    for k,v in json.loads((target/'environment.json').read_text('utf-8')).items():monkeypatch.setenv(k,v)
    restored=configured_service();current=Queue(restored,Authority(backend,ns,owner,0,target/'data/.authority'),clock=clock)
    assert current.overview()['maintenance_owner']=='native-cold-snapshot'
    assert current.claim(native=True) is None
    current.maintenance('resume','native-cold-snapshot')
    for task in tasks:current.action(task['id'],'resume','Restore original native batch upload checkpoint')
    assert run_all(current,driver,pid)['action']=='complete'
    assert len(driver.posts)==1 and len(driver.puts)==2 and len(driver.downloads)==2
    assert current.plan_status(pid)['budget']['reserved_submissions']==2
