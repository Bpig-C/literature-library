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
