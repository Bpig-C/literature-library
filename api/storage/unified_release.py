"""One manifest restores essential local state and attaches lazy cloud assets.

Code comes from an exact Git revision. Runtime snapshots/config come from
content-addressed objects. Ordinary credentials are never snapshot payloads.
"""
import hashlib,json,os,re,shutil,sqlite3,subprocess,tempfile,uuid,zipfile
from contextlib import ExitStack,closing
from pathlib import Path
from .core import StorageError,Namespace,hash_file,relative_key,copy_stream,file_lock
from .backends import LocalObjectBackend,oss_from_environment

CONFIG_KEYS={'storage_namespace','oss_bucket','oss_region','cache_bytes','staging_bytes','schema_version','contract_version','research_editing_enabled'}

def validate_versions(config,research):
    from ..research_context import ResearchContext
    from ..research_schema import CONTRACT,verify_schema
    result=verify_schema(ResearchContext(Path(research).parent,Path(research),read_only=True))
    if not result['ok'] or config.get('schema_version')!=result['schema_version'] or config.get('contract_version')!=int(CONTRACT['version']):
        raise StorageError('revision_conflict','research snapshot schema/contract differs from the release')
    with closing(sqlite3.connect(Path(research).as_uri()+'?mode=ro',uri=True)) as c:
        row=c.execute('SELECT contract_version FROM research_schema_migrations ORDER BY version DESC LIMIT 1').fetchone()
        if not row or row[0]!=config['contract_version']:raise StorageError('revision_conflict','snapshot migration contract differs')

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)

def descriptor(path,namespace):
    sha,size=hash_file(Path(path));return {'sha256':sha,'bytes':size,'key':namespace.key(sha)}

def object_read(backend,entry,target,limit):
    if entry['bytes']>limit:raise StorageError('quota_exceeded','release object exceeds configured restore budget')
    backend.download(entry['key'],target,max_bytes=entry['bytes'])
    if hash_file(target)!=(entry['sha256'],entry['bytes']):raise StorageError('checksum_mismatch','release object SHA/size mismatch')

def publish_snapshot(destination,*,catalog,research,files,config,code,frontend,namespace,backend,asset_index):
    """Explicit publisher. Caller supplies exact reviewed inputs, no directory crawl.

    User authorization to back up is separate from invoking this function; formal
    inputs are not selected by default. A quiet maintenance window is required.
    """
    ns=Namespace(namespace);dest=Path(destination).resolve()
    if dest.exists():raise StorageError('revision_conflict','new release staging directory required')
    if set(config)-CONFIG_KEYS or config.get('storage_namespace')!=namespace:raise StorageError('invalid_request','only non-sensitive whitelisted configuration can be backed up')
    if not re.fullmatch('[0-9a-f]{40}',code['commit']):raise StorageError('invalid_request','exact Git commit required')
    for name,path in files.items():
        relative_key(name)
        if not name.startswith(('research/assets/','research/editing/','library/templates/','library/docs/')) or Path(path).suffix.lower() not in {'.json','.md','.txt','.js'}:raise StorageError('invalid_request','working file must be explicitly selected in supported runtime paths')
        if Path(path).is_symlink():raise StorageError('invalid_request','linked working file refused')
        if Path(path).suffix.lower()=='.json':
            def no_credentials(value):
                if isinstance(value,dict):
                    for key,item in value.items():
                        normalized=key.lower().replace('_','').replace('-','')
                        if normalized in {'ossaccesskeyid','ossaccesskeysecret','osssessiontoken','accesskeysecret','accesskeyid','sessiontoken','apikey'} and item not in (None,''):
                            raise StorageError('permission_denied','credential values must not be backed up as ordinary configuration')
                        no_credentials(item)
                elif isinstance(value,list):
                    for item in value:no_credentials(item)
            no_credentials(json.loads(Path(path).read_text('utf-8')))
    dest.mkdir(parents=True)
    inputs={'library/literature.sqlite':Path(catalog).resolve(),'research/research.sqlite':Path(research).resolve()}
    # Both DB writer locks protect a consistent pair, not two independently
    # timed main-file copies. Backups use separate read connections.
    with file_lock(Path(catalog).with_suffix('.producer.lock')),ExitStack() as stack:
        for name,path in inputs.items():
            c=stack.enter_context(closing(sqlite3.connect(path.as_uri()+'?mode=rw',uri=True)));c.execute('BEGIN IMMEDIATE')
        for name,path in inputs.items():
            target=dest/name;target.parent.mkdir(parents=True,exist_ok=True)
            with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as source,closing(sqlite3.connect(target)) as out:source.backup(out)
    for name,path in files.items():
        target=dest/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
        if hash_file(Path(path))!=hash_file(target):raise StorageError('revision_conflict','working file changed during snapshot; keep writers stopped')
    validate_versions(config,dest/'research/research.sqlite')
    essentials={name:descriptor(dest/name,ns) for name in inputs}
    essentials.update({name:descriptor(dest/name,ns) for name in files})
    front=descriptor(frontend,ns)
    manifest={'format':'litlib-unified-release-v1','release_id':uuid.uuid4().hex,'code':code,'frontend':front,'essentials':essentials,'configuration':config,
              'credential_environment_names':['OSS_ACCESS_KEY_ID','OSS_ACCESS_KEY_SECRET','OSS_SESSION_TOKEN','MINERU_API_TOKEN','LITLIB_PARSE_UPLOAD_KEY'],'namespace':namespace,
              'original_roots':{'library':str(Path(catalog).resolve().parent),'research':str(Path(research).resolve().parent)},'asset_index':asset_index,
              'default_fetch':'code/frontend/DBs/required working files only; asset_index attaches remote objects for bounded on-demand cache',
              'snapshot_window':'both SQLite write locks; caller must stop external file/business writers'}
    data=canonical(manifest).encode();manifest_path=dest/'release.json';manifest_path.write_bytes(data)
    entry=descriptor(manifest_path,ns)
    uploads={str(dest/name):entry for name,entry in essentials.items()};uploads[str(frontend)]=front
    if backend is None:
        return {'manifest':manifest,'manifest_object':descriptor(manifest_path,ns),'snapshot_upload_objects':len({v['sha256'] for v in uploads.values()}),'long_term_asset_objects_reuploaded':0}
    with tempfile.TemporaryDirectory(prefix='litlib-release-readback-') as tmp:
        for path,entry in uploads.items():
            try:backend.size(entry['key'])
            except StorageError as error:
                if error.code!='not_found':raise
                try:backend.put_immutable(entry['key'],Path(path))
                except StorageError as put_error:
                    if put_error.code!='object_exists':raise
            object_read(backend,entry,Path(tmp)/'verified',max(entry['bytes'],1))
    data=canonical(manifest).encode();manifest_path=dest/'release.json';manifest_path.write_bytes(data)
    entry=descriptor(manifest_path,ns)
    try:backend.put_immutable(entry['key'],manifest_path)
    except StorageError as error:
        if error.code!='object_exists':raise
    return {'manifest':manifest,'manifest_object':entry,'snapshot_upload_objects':len({v['sha256'] for v in uploads.values()}),'long_term_asset_objects_reuploaded':0}

def restore_release(backend,*,manifest_key,manifest_sha256,destination,namespace,expected_git_url=None,quota_bytes=512*1024**2):
    ns=Namespace(namespace);target=Path(destination)
    if not target.is_absolute() or target.exists():raise StorageError('revision_conflict','restore requires a new absolute destination; existing state preserved')
    if manifest_key!=ns.key(manifest_sha256):raise StorageError('invalid_request','manifest key must match exact reviewed SHA/namespace')
    if not shutil.which('git'):raise StorageError('configuration_error','Git executable required before restore')
    target.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.litlib-unified-restore-',dir=target.parent) as temporary:
        temp=Path(temporary);raw=temp/'release.json'
        if not temp.resolve().is_relative_to(target.parent.resolve()):raise StorageError('configuration_error','restore staging outside explicit destination parent')
        backend.download(manifest_key,raw,max_bytes=16*1024**2)
        if hash_file(raw)[0]!=manifest_sha256:raise StorageError('checksum_mismatch','release manifest SHA mismatch')
        m=json.loads(raw.read_text('utf-8'))
        if m.get('format')!='litlib-unified-release-v1' or m['namespace']!=namespace or m['configuration'].get('storage_namespace')!=namespace or set(m['configuration'])-CONFIG_KEYS:raise StorageError('invalid_request','supported exact non-sensitive unified release required')
        code=m['code']
        if not re.fullmatch('[0-9a-f]{40}',code['commit']) or (expected_git_url and code['url']!=expected_git_url):raise StorageError('revision_conflict','Git source/revision does not match expected release')
        url=code['url']
        if not (url.startswith('https://github.com/') or (namespace.find('/test/')>=0 and Path(url).is_absolute())):raise StorageError('invalid_request','supported GitHub code source required; local Git only for isolated tests')
        required={'library/literature.sqlite','research/research.sqlite'}
        presentation_required={'research/assets/'+name for name in ['research-display.json','ontology-display.json','ontology-display-source.js','autonomy-risk-v1.json','ontology-proposal.json','review-cards-v5.json','assets-manifest.json']}
        if not presentation_required<=set(m['essentials']):raise StorageError('invalid_request','complete runtime research assets required')
        if not required<=set(m['essentials']):raise StorageError('invalid_request','both DB snapshots required')
        for name,e in m['essentials'].items():
            relative_key(name)
            if name not in required and not name.startswith(('research/assets/','research/editing/','library/templates/','library/docs/')):raise StorageError('invalid_request','essential path outside runtime whitelist')
            if e['key']!=ns.key(e['sha256']):raise StorageError('invalid_request','essential locator namespace mismatch')
        if m['frontend']['key']!=ns.key(m['frontend']['sha256']):raise StorageError('invalid_request','frontend namespace mismatch')
        entries=list(m['essentials'].values())+[m['frontend']]
        if sum(e['bytes'] for e in entries)>quota_bytes:raise StorageError('quota_exceeded','essential payload exceeds restore budget')
        restored=temp/'new';restored.mkdir();app=restored/'app';data=restored/'data';data.mkdir()
        subprocess.run(['git','init','--quiet',str(app)],check=True)
        subprocess.run(['git','-C',str(app),'fetch','--quiet','--depth=1','--no-tags',url,code['commit']],check=True)
        subprocess.run(['git','-C',str(app),'-c','core.autocrlf=false','checkout','--quiet','--detach',code['commit']],check=True)
        tracked=set(subprocess.check_output(['git','-C',str(app),'ls-tree','-r','--name-only','-z','HEAD']).decode().rstrip('\0').split('\0'))
        if tracked!=set(code['files']):raise StorageError('revision_conflict','Git tree exceeds reviewed release whitelist')
        for name,sha in code['files'].items():
            relative_key(name)
            p=app/name
            if p.is_symlink() or not p.resolve().is_relative_to(app.resolve()) or hash_file(p)[0]!=sha:raise StorageError('checksum_mismatch','restored code fingerprint mismatch')
        for name in ('uv.lock','web/npm-shrinkwrap.json'):
            if code.get('locks',{}).get(name)!=code['files'].get(name):raise StorageError('revision_conflict','release lock differs from code tree')
        for name,e in m['essentials'].items():
            p=data/name;p.parent.mkdir(parents=True,exist_ok=True);object_read(backend,e,p,quota_bytes)
        frontend=temp/'frontend.zip';object_read(backend,m['frontend'],frontend,quota_bytes)
        with zipfile.ZipFile(frontend) as z:
            if sum(i.file_size for i in z.infolist())>quota_bytes:raise StorageError('quota_exceeded','frontend extraction budget exceeded')
            for info in z.infolist():
                relative_key(info.filename)
                if info.is_dir() or ((info.external_attr>>16)&0o170000)==0o120000:raise StorageError('unsafe_package','frontend package must contain plain whitelisted files')
                p=app/'web/dist'/info.filename;p.parent.mkdir(parents=True,exist_ok=True)
                with z.open(info) as src,p.open('xb') as out:copy_stream(src,out,limit=info.file_size)
        frontend_files={p.relative_to(app/'web/dist').as_posix():hash_file(p)[0] for p in (app/'web/dist').rglob('*') if p.is_file()}
        (restored/'frontend-integrity.json').write_text(canonical(frontend_files),'utf-8')
        # Relocate explicit transport fields only, preserving scientific payloads
        # and text offsets. Alias identities/version and object SHA remain fixed.
        final_data=target/'data'
        mapping=sorted([(v,str(final_data/k)) for k,v in m['original_roots'].items()],key=lambda p:len(p[0]),reverse=True)
        def relocate(v):
            if isinstance(v,str):
                for old,new in mapping:
                    if v==old or v.startswith(old+os.sep):return new+v[len(old):]
            if isinstance(v,list):return [relocate(x) for x in v]
            if isinstance(v,dict):return {k:relocate(x) for k,x in v.items()}
            return v
        specs={'library/literature.sqlite':{'source_files':['source_path','archive_path'],'duplicate_candidates':['source_path'],'literature_parse_runs':['source_path','output_dir','content_md_path','content_json_path','package_path'],'library_migration_files':['original_source_path','library_path'],'storage_paths':['path'],'storage_operations':['pending','request'],'storage_staging_files':['pending'],'storage_producer_jobs':['artifacts']},'research/research.sqlite':{'research_sources':['source_path','snapshot_path']}}
        for db,tables in specs.items():
            with closing(sqlite3.connect(data/db)) as c:
                for table,columns in tables.items():
                    available={r[1] for r in c.execute('PRAGMA table_info('+table+')')}
                    for column in set(columns)&available:
                        for rowid,value in c.execute('SELECT rowid,'+column+' FROM '+table).fetchall():
                            if not value:continue
                            new=json.dumps(relocate(json.loads(value))) if column in ('request','artifacts') else relocate(value)
                            if new!=value:c.execute('UPDATE '+table+' SET '+column+'=? WHERE rowid=?',(new,rowid))
                c.commit()
                if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise StorageError('checksum_mismatch','restored SQLite integrity failed')
        validate_versions(m['configuration'],data/'research/research.sqlite')
        with closing(sqlite3.connect(data/'library/literature.sqlite')) as c:
            setting=c.execute('SELECT root FROM storage_settings WHERE id=1').fetchone()
            if not setting or setting[0]!=namespace:raise StorageError('configuration_error','restored registry namespace differs')
            bindings=[dict(zip(['identity','role','version','sha256','bytes','parent_sha256','parent_bytes','member'],r)) for r in c.execute('SELECT identity,role,version,sha256,bytes,parent_sha256,parent_bytes,member FROM storage_bindings ORDER BY identity,role,version')]
            if bindings!=m['asset_index']['bindings']:raise StorageError('revision_conflict','snapshot registry differs from immutable asset index')
        assets=data/'research/assets';index=json.loads((assets/'assets-manifest.json').read_text('utf-8'))
        for name,entry in index.items():
            relative_key(name)
            if hash_file(assets/name)!=(entry['sha256'],entry['bytes']):raise StorageError('checksum_mismatch','runtime presentation integrity mismatch')
        cfg=m['configuration'];environment={'LITLIB_STORAGE_MODE':'immutable','LITLIB_LIBRARY_ROOT':str(final_data/'library'),'LITLIB_DB_PATH':str(final_data/'library/literature.sqlite'),'LITLIB_RESEARCH_ROOT':str(final_data/'research'),'LITLIB_RESEARCH_DB':str(final_data/'research/research.sqlite'),'LITLIB_RESEARCH_ASSETS_ROOT':str(final_data/'research/assets'),'LITLIB_STORAGE_ROOT':namespace,'LITLIB_STORAGE_BACKEND':'local' if isinstance(backend,LocalObjectBackend) else 'oss','LITLIB_STORAGE_CACHE':str(target/'cache'),'LITLIB_STORAGE_STAGING':str(target/'staging'),'LITLIB_STORAGE_CACHE_BYTES':str(cfg.get('cache_bytes',1024**3)),'LITLIB_STORAGE_STAGING_BYTES':str(cfg.get('staging_bytes',2*1024**3)),'LITLIB_RESEARCH_EDITING_ENABLED':'1' if cfg.get('research_editing_enabled') else '0'}
        if isinstance(backend,LocalObjectBackend):environment['LITLIB_STORAGE_LOCAL_OBJECTS']=str(backend.root)
        else:environment.update(LITLIB_OSS_BUCKET=cfg['oss_bucket'],LITLIB_OSS_REGION=cfg['oss_region'])
        environment['LITLIB_RUNTIME_MATERIALS_ROOT']=str(final_data/'library/docs')
        materials=data/'library/docs/contracts';materials.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(app/'contracts/research-workflow-v1.json',materials/'research-workflow-v1.json')
        (restored/'environment.json').write_text(json.dumps(environment,indent=2),'utf-8')
        (restored/'release-manifest.json').write_text(canonical(m),'utf-8')
        receipt={'release_id':m['release_id'],'code_commit':code['commit'],'manifest_sha256':manifest_sha256,'credentials_copied':False,'default_full_asset_download':False,'asset_index_attached':True,'essential_local_files':sorted(m['essentials']),'cache_initially_absent':True,'scientific_payload_rewritten':False,'initial_dependency_install':'uv sync --frozen --extra storage in app if runtime dependencies not already installed; no npm build needed'}
        (restored/'restore-receipt.json').write_text(json.dumps(receipt,indent=2),'utf-8')
        # Publish only after integrity checks. Never replace an existing target.
        if target.exists():raise StorageError('revision_conflict','destination appeared during restore; preserve it')
        target.parent.mkdir(parents=True,exist_ok=True)
        # Both paths are in the explicitly checked same destination parent.
        # Windows directory rename refuses an already-existing destination.
        restored.rename(target)
        return receipt
