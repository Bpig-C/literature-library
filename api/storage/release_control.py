"""Reviewed snapshot prepare/stage/publish, with immutable resumable uploads."""
import json,sqlite3,subprocess,tempfile,hashlib,os
from contextlib import closing
from pathlib import Path
from .core import Namespace,StorageError,hash_file,relative_key
from .unified_release import CONFIG_KEYS,canonical,descriptor,object_read,publish_snapshot,validate_versions

CODE=Path(__file__).resolve().parents[2]
REQUIRED_ASSETS={'research/assets/'+n for n in ('research-display.json','ontology-display.json','ontology-display-source.js','autonomy-risk-v1.json','ontology-proposal.json','review-cards-v5.json','assets-manifest.json')}

def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def read(path):return json.loads(Path(path).read_text('utf-8'))
def write(path,value):
    p=Path(path);temporary=p.with_name(p.name+'.next');temporary.write_text(canonical(value),'utf-8');temporary.replace(p)

def code_tree(url,namespace):
    if not (url.startswith('https://github.com/') or ('/test/' in namespace and Path(url).is_absolute())):raise StorageError('invalid_request','explicit supported GitHub source required; local Git only in test namespace')
    if subprocess.check_output(['git','status','--porcelain'],cwd=CODE).strip():raise StorageError('revision_conflict','snapshot tool code must be committed and clean')
    from scripts.check_release import check as check_code
    if not check_code(CODE)['ok']:raise StorageError('permission_denied','generic complete code history audit required before snapshot publication')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=CODE).decode().strip()
    paths=subprocess.check_output(['git','ls-tree','-r','--name-only','-z','HEAD'],cwd=CODE).decode().rstrip('\0').split('\0')
    files={p:hash_file(CODE/p)[0] for p in paths}
    return {'url':url,'commit':commit,'files':files,'locks':{p:files[p] for p in ('uv.lock','web/npm-shrinkwrap.json')}}

def no_secrets(value):
    if isinstance(value,dict):
        for key,v in value.items():
            if key.lower().replace('_','').replace('-','') in {'ossaccesskeyid','ossaccesskeysecret','osssessiontoken','accesskeyid','accesskeysecret','sessiontoken','apikey'} and v not in ('',None):raise StorageError('permission_denied','credential values refused in snapshot input')
            no_secrets(v)
    elif isinstance(value,list):
        for v in value:no_secrets(v)

def bindings(path):
    with closing(sqlite3.connect(Path(path).as_uri()+'?mode=ro',uri=True)) as c:
        c.row_factory=sqlite3.Row
        return [dict(r) for r in c.execute('SELECT * FROM storage_bindings ORDER BY identity,role,version')]

def database_digest(path):
    # Logical SQLite content is stable across harmless WAL checkpoints. Raw
    # endpoint hashes remain evidence, not the sole drift discriminator.
    h=hashlib.sha256()
    with closing(sqlite3.connect(Path(path).as_uri()+'?mode=ro',uri=True)) as c:
        c.execute('BEGIN')
        for table,sql in c.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
            quoted='"'+table.replace('"','""')+'"'
            values=sorted(canonical([v.hex() if isinstance(v,bytes) else v for v in row]) for row in c.execute('SELECT * FROM '+quoted))
            h.update(canonical([table,sql,values]).encode())
    return h.hexdigest()

def validate_source(inputs):
    """Bind all runtime inputs to one reviewed slot; reject inherited stale DBs.

    This is an offline identity check, not proof the slot is the live authority.
    The maintenance adapter must verify that identity before stopping writers.
    """
    root_value=inputs.get('source_root')
    if not root_value:
        if '/prod/' in inputs['namespace']:
            raise StorageError('configuration_error','Production snapshots require explicit source_root; regenerate legacy inputs from the current writer slot')
        return
    root=Path(root_value)
    if not root.is_absolute() or not root.is_dir():raise StorageError('configuration_error','Existing absolute source slot required')
    root=root.resolve();env=read(root/'environment.json')
    if env.get('LITLIB_STORAGE_ROOT')!=inputs['namespace']:raise StorageError('revision_conflict','Source slot namespace differs')
    for name,key,relative in [('catalog','LITLIB_DB_PATH','library/literature.sqlite'),('research','LITLIB_RESEARCH_DB','research/research.sqlite')]:
        expected=root/'data'/relative
        if Path(inputs[name]).resolve()!=expected or Path(env[key]).resolve()!=expected:
            raise StorageError('revision_conflict','Snapshot database differs from source slot: '+name)
        if os.environ.get(key) and Path(os.environ[key]).resolve()!=expected:
            raise StorageError('revision_conflict','Snapshot source differs from the applied runtime: '+name)
    for name,entry in inputs['files'].items():
        relative_key(name)
        expected=(root/'data'/name).resolve()
        if not expected.is_relative_to(root/'data') or Path(entry['source']).resolve()!=expected:
            raise StorageError('revision_conflict','Snapshot working file differs from source slot: '+name)


def prepare(inputs,max_bytes):
    """No source mutation, registry/cache initialization or network requests."""
    if inputs.get('format')!='litlib-snapshot-input-v1':raise StorageError('invalid_request','exact snapshot input format required')
    no_secrets(inputs);ns=Namespace(inputs['namespace']);cfg=inputs['configuration']
    validate_source(inputs)
    if set(cfg)-CONFIG_KEYS or cfg.get('storage_namespace')!=ns.root:raise StorageError('invalid_request','whitelisted configuration and namespace required')
    if '/prod/' in ns.root and not (cfg.get('oss_bucket') and cfg.get('oss_region')):raise StorageError('invalid_request','explicit production OSS bucket/region required')
    if max_bytes<=0:raise StorageError('invalid_request','positive explicit snapshot budget required')
    selected={}
    for name,entry in inputs['files'].items():
        relative_key(name)
        if not name.startswith(('research/assets/','research/editing/','library/templates/','library/docs/')):raise StorageError('invalid_request','runtime path outside snapshot whitelist')
        path=Path(entry['source'])
        if not path.is_absolute() or path.is_symlink() or path.suffix.lower() not in {'.json','.md','.txt','.js'}:raise StorageError('invalid_request','explicit plain working file required')
        sha,size=hash_file(path)
        if (sha,size)!=(entry['sha256'],entry['bytes']):raise StorageError('revision_conflict','selected working file differs from exact input')
        if path.suffix.lower()=='.json':no_secrets(read(path))
        selected[name]={'source':str(path),'sha256':sha,'bytes':size}
    if not REQUIRED_ASSETS<=set(selected):raise StorageError('invalid_request','complete runtime research assets required')
    endpoints={};db_sizes={};logical={}
    for name in ('catalog','research'):
        p=Path(inputs[name])
        if not p.is_absolute() or not p.is_file() or p.is_symlink():raise StorageError('invalid_request','explicit existing database required')
        for f in [p,Path(str(p)+'-wal')]:
            if f.is_file():endpoints[str(f)]=hash_file(f)[0]
        with closing(sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)) as c:
            if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise StorageError('checksum_mismatch','database integrity failed')
            db_sizes[name]=c.execute('PRAGMA page_count').fetchone()[0]*c.execute('PRAGMA page_size').fetchone()[0]
        logical[name]=database_digest(p)
    validate_versions(cfg,Path(inputs['research']))
    index={'bindings':bindings(inputs['catalog'])}
    with closing(sqlite3.connect(Path(inputs['catalog']).as_uri()+'?mode=ro',uri=True)) as c:
        setting=c.execute('SELECT root FROM storage_settings WHERE id=1').fetchone()
        if not setting or setting[0]!=ns.root:raise StorageError('revision_conflict','source registry namespace differs')
    frontend=dict(inputs['frontend']);p=Path(frontend['source'])
    if not p.is_absolute() or p.is_symlink() or hash_file(p)!=(frontend['sha256'],frontend['bytes']):raise StorageError('revision_conflict','frontend input differs')
    code=code_tree(inputs['code_url'],ns.root)
    total=sum(db_sizes.values())+sum(e['bytes'] for e in selected.values())+frontend['bytes']
    if total>max_bytes:raise StorageError('quota_exceeded','snapshot payload estimate exceeds explicit budget')
    return {'format':'litlib-snapshot-ticket-v1','inputs':inputs,'input_sha256':digest(inputs),'code':code,'asset_index':index,'source_endpoints':endpoints,'database_logical_sha256':logical,'database_image_bytes':db_sizes,'payload_bytes_estimate':total,'max_snapshot_bytes':max_bytes,'writers_must_be_stopped':True,'prepare_source_writes':False,'prepare_network_requests':0}

def staged(stage):
    root=Path(stage).resolve();receipt=read(root/'stage-receipt.json');m=read(root/'release.json');ns=Namespace(m['namespace'])
    if receipt['manifest_sha256']!=hash_file(root/'release.json')[0]:raise StorageError('checksum_mismatch','frozen manifest changed')
    for name,e in m['essentials'].items():
        relative_key(name)
        p=root/name
        if p.is_symlink() or not p.resolve().is_relative_to(root) or hash_file(p)!=(e['sha256'],e['bytes']) or e['key']!=ns.key(e['sha256']):raise StorageError('checksum_mismatch','frozen snapshot object changed')
    if hash_file(root/'frontend.zip')!=(m['frontend']['sha256'],m['frontend']['bytes']):raise StorageError('checksum_mismatch','frozen frontend changed')
    return root,receipt,m

def stage(ticket,approved,destination,writers_stopped):
    if digest(ticket)!=approved or not writers_stopped:raise StorageError('permission_denied','exact reviewed ticket and operator-confirmed stopped writers required')
    dest=Path(destination)
    if not dest.is_absolute():raise StorageError('invalid_request','new absolute staging directory required')
    if dest.exists():
        root,receipt,m=staged(dest)
        if receipt['ticket_sha256']!=approved:raise StorageError('revision_conflict','existing stage belongs to another ticket')
        return receipt
    inputs=ticket['inputs'];current=prepare(inputs,ticket['max_snapshot_bytes'])
    expected=dict(ticket);observed=dict(current)
    expected.pop('source_endpoints');observed.pop('source_endpoints')
    if expected!=observed:raise StorageError('revision_conflict','source DB/files/code drifted since preparation; prepare a new ticket')
    result=publish_snapshot(dest,catalog=inputs['catalog'],research=inputs['research'],files={name:e['source'] for name,e in inputs['files'].items()},config=inputs['configuration'],code=ticket['code'],frontend=inputs['frontend']['source'],namespace=inputs['namespace'],backend=None,asset_index=ticket['asset_index'])
    # Freeze the frontend as well; retries never read live sources again.
    import shutil
    shutil.copyfile(inputs['frontend']['source'],dest/'frontend.zip')
    for name,path in [('catalog',dest/'library/literature.sqlite'),('research',dest/'research/research.sqlite')]:
        if database_digest(path)!=ticket['database_logical_sha256'][name]:raise StorageError('revision_conflict','database business/schema content changed before coherent freeze; preserve incomplete stage')
    if bindings(dest/'library/literature.sqlite')!=ticket['asset_index']['bindings']:raise StorageError('revision_conflict','registry changed during staging; retain incomplete stage and use a new ticket/directory')
    rows=list(result['manifest']['essentials'].values())+[result['manifest']['frontend'],result['manifest_object']]
    unique={e['key']:e for e in rows};exact=sum(e['bytes'] for e in unique.values())
    if exact>ticket['max_snapshot_bytes']:raise StorageError('quota_exceeded','exact staged upload bytes including manifest exceed budget; retain stage, no upload')
    receipt={'ticket_sha256':approved,'manifest_sha256':result['manifest_object']['sha256'],'manifest_key':result['manifest_object']['key'],'unique_snapshot_objects':len(unique),'maximum_upload_bytes':exact,'actual_upload_bytes_before_HEAD_unknown':True,'long_term_objects_reuploaded':0,'state':'staged','authorization':'ticket SHA binds operator approval; flag does not independently prove maintenance window'}
    write(dest/'stage-receipt.json',receipt);write(dest/'upload-journal.json',{'manifest_sha256':receipt['manifest_sha256'],'state':'staged','verified':[]})
    staged(dest)
    return receipt

def publish(stage,approved,backend,max_upload_bytes,fault=None):
    root,receipt,m=staged(stage)
    if receipt['manifest_sha256']!=approved:raise StorageError('permission_denied','exact staged manifest approval required')
    if receipt['maximum_upload_bytes']>max_upload_bytes:raise StorageError('quota_exceeded','exact maximum upload bytes exceed approval budget')
    ns=Namespace(m['namespace'])
    # Require the existing immutable corpus closure, never silently re-upload it.
    corpus={}
    for b in m['asset_index']['bindings']:
        sha=b['parent_sha256'] or b['sha256'];size=b['parent_bytes'] if b['parent_sha256'] else b['bytes'];corpus[ns.key(sha)]=size
    for key,size in corpus.items():
        if backend.size(key)!=size:raise StorageError('revision_conflict','referenced corpus object absent/size differs; preserve stage')
    journal=read(root/'upload-journal.json')
    if journal['manifest_sha256']!=approved:raise StorageError('revision_conflict','upload journal belongs to another manifest')
    journal['state']='publishing';write(root/'upload-journal.json',journal)
    objects={e['key']:(root/name,e) for name,e in m['essentials'].items()}
    objects[m['frontend']['key']]=(root/'frontend.zip',m['frontend'])
    manifest_entry=descriptor(root/'release.json',ns);objects[manifest_entry['key']]=(root/'release.json',manifest_entry)
    with tempfile.TemporaryDirectory(prefix='litlib-snapshot-verify-') as temporary:
        for key,(path,e) in objects.items():
            try:backend.size(key)
            except StorageError as error:
                if error.code!='not_found':raise
                try:backend.put_immutable(key,path)
                except StorageError as error:
                    if error.code!='object_exists':raise
            object_read(backend,e,Path(temporary)/'object',max(e['bytes'],1))
            if key not in journal['verified']:journal['verified'].append(key)
            write(root/'upload-journal.json',journal)
            if fault:fault(key)
    journal['state']='published';write(root/'upload-journal.json',journal)
    return {**receipt,'state':'published','verified_snapshot_objects':len(objects),'manifest_published_last':True,'failure_resume':'rerun this exact frozen stage/manifest/budget; existing objects verified, never overwritten or deleted; incomplete stage requires a new ticket/directory'}
