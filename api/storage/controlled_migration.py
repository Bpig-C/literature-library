"""Reviewable preflight and explicitly approved transport execution.

No environment flag silently enables production. Preparing a ticket is read-only;
the exact ticket digest must be supplied to execute after human authorization.
"""
import hashlib,json,os,sqlite3
from contextlib import closing,ExitStack
from pathlib import Path
from types import SimpleNamespace
from .core import StorageError,hash_file,Registry,file_lock
from .runtime import configured_registry,configured_service,required_path,protected_data_paths,assert_safe_working_paths
from .migration import checked_plan,canonical,connect,paths,FIELDS,_apply_transport,write_journal
from .producers import lock_path

CODE=Path(__file__).resolve().parents[2]

class ReadOnlyRegistry(Registry):
    def binding(self,identity,role,version=None):
        with closing(connect(self.catalog)) as c:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE name='storage_bindings'").fetchone():raise StorageError('not_found','registry not initialized')
            row=c.execute('SELECT * FROM storage_bindings WHERE identity=? AND role=? AND version=?',(identity,role,version)).fetchone()
            if not row:raise StorageError('not_found','fixed binding absent')
            return dict(row)

def context():
    registry=configured_registry()
    backend=os.environ.get('LITLIB_STORAGE_BACKEND')
    production=registry.ns.root=='research/agent-loss-of-control/literature/prod/'
    if production and (backend!='oss' or not os.environ.get('LITLIB_OSS_BUCKET') or not os.environ.get('LITLIB_OSS_REGION')):
        raise StorageError('configuration_error','production requires explicit OSS bucket/region')
    if backend not in ('local','oss'):raise StorageError('configuration_error','explicit backend required')
    if backend=='local' and '/test/' not in registry.ns.root:raise StorageError('configuration_error','local execution only in test namespace')
    return SimpleNamespace(registry=ReadOnlyRegistry(registry.catalog,registry.ns),ns=registry.ns),{
        'databases':{k:str(v) for k,v in paths(SimpleNamespace(registry=registry)).items()},
        'namespace':registry.ns.root,'backend':backend,'bucket':os.environ.get('LITLIB_OSS_BUCKET'),
        'region':os.environ.get('LITLIB_OSS_REGION'),'local_objects':os.environ.get('LITLIB_STORAGE_LOCAL_OBJECTS') if backend=='local' else None,
        'cache':str(required_path('LITLIB_STORAGE_CACHE')),'staging':str(required_path('LITLIB_STORAGE_STAGING')),
        'ledger':str(required_path('LITLIB_STORAGE_LEDGER'))}

def code_fingerprint():
    return {p.relative_to(CODE).as_posix():hash_file(p)[0] for folder in ['api','scripts','contracts'] for p in (CODE/folder).rglob('*') if p.is_file() and p.suffix in ('.py','.json') and '__pycache__' not in p.parts}

def business_fingerprint(connections):
    result={}
    for db,c in connections.items():
        h=hashlib.sha256()
        for (table,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'storage_%' ORDER BY name"):
            columns=[row[1] for row in c.execute('PRAGMA table_info("'+table.replace('"','""')+'")') if row[1] not in FIELDS.get(db,{}).get(table,set())]
            query='SELECT '+','.join('"'+name.replace('"','""')+'"' for name in columns)+' FROM "'+table.replace('"','""')+'"'
            # Canonical sorted rows avoid dependence on storage order.
            values=sorted(canonical([v.hex() if isinstance(v,bytes) else v for v in row]) for row in c.execute(query))
            h.update(canonical([table,columns,values]).encode())
        result[db]=h.hexdigest()
    return result

def prepare(plan,payloads):
    service,ctx=context()
    digest=checked_plan(plan,service)
    sources={};sizes={}
    for p in payloads:
        path=Path(p['source']);key=(p['sha256'],p['bytes'])
        if not path.is_absolute() or path.is_symlink() or hash_file(path)!=key:raise StorageError('checksum_mismatch','explicit payload SHA/size mismatch')
        if str(path) in sources:raise StorageError('invalid_request','duplicate physical payload source')
        sources[str(path)]=key;sizes[p['sha256']]=p['bytes']
    if any(a['source'] not in sources for a in plan['assets']):raise StorageError('invalid_request','asset source missing from physical closure')
    if max(sizes.values(),default=0)>int(os.environ.get('LITLIB_STORAGE_CACHE_BYTES',str(1024**3))):raise StorageError('cache_full','largest payload exceeds configured cache')
    with ExitStack() as stack:
        dbs={k:stack.enter_context(closing(connect(Path(p)))) for k,p in ctx['databases'].items()}
        fingerprints=business_fingerprint(dbs)
    protected=protected_data_paths(service.registry)
    assert_safe_working_paths([Path(ctx[k]) for k in ['cache','staging','ledger']],protected)
    ticket={'format':'litlib-controlled-migration-v1','context':ctx,'manifest_sha256':digest,'plan':plan,'payloads':payloads,
            'database_endpoint_sha256':{k:hash_file(Path(p))[0] for k,p in ctx['databases'].items()},'business_fingerprints':fingerprints,
            'code_sha256':code_fingerprint(),'approval_required':True,'writers_must_be_stopped':True,'production':ctx['namespace'].endswith('/prod/')}
    return ticket

def ticket_digest(ticket):return hashlib.sha256(canonical(ticket).encode()).hexdigest()

def execute(ticket,approved_digest,*,fault=None):
    if ticket.get('format')!='litlib-controlled-migration-v1' or approved_digest!=ticket_digest(ticket):
        raise StorageError('permission_denied','exact reviewed ticket digest required after explicit authorization')
    reader,ctx=context()
    if ctx!=ticket['context'] or code_fingerprint()!=ticket['code_sha256']:raise StorageError('revision_conflict','reviewed environment/code changed')
    if checked_plan(ticket['plan'],reader)!=ticket['manifest_sha256']:raise StorageError('revision_conflict','manifest changed')
    ledger=Path(ctx['ledger'])/approved_digest
    start=ledger/'controlled.json'
    with file_lock(lock_path(reader)):
        prior=json.loads(start.read_text('utf-8')) if start.exists() else None
        if prior and prior['ticket_digest']!=approved_digest:raise StorageError('revision_conflict','controlled ledger differs')
        # Endpoint hashes apply only before the first execution; resumptions use
        # exact business fingerprints/old-or-new transport cells and frozen backups.
        if not prior and any(hash_file(Path(p))[0]!=ticket['database_endpoint_sha256'][k] for k,p in ctx['databases'].items()):
            raise StorageError('revision_conflict','DB changed since reviewed preparation')
        with ExitStack() as stack:
            dbs={k:stack.enter_context(closing(connect(Path(p),True))) for k,p in ctx['databases'].items()}
            if business_fingerprint(dbs)!=ticket['business_fingerprints']:raise StorageError('revision_conflict','business rows changed; new preparation required')
            ledger.mkdir(parents=True,exist_ok=True)
            if not prior:
                backups={}
                for k,p in ctx['databases'].items():
                    target=ledger/(k+'-before.sqlite')
                    with closing(connect(Path(p))) as src,closing(sqlite3.connect(target)) as out:src.backup(out)
                    backups[k]={'path':str(target),'sha256':hash_file(target)[0]}
                prior={'ticket_digest':approved_digest,'state':'prepared','backups':backups,'verified_objects':[]}
                write_journal(start,prior)
            for backup in prior['backups'].values():
                if hash_file(Path(backup['path']))[0]!=backup['sha256']:raise StorageError('checksum_mismatch','backup changed; execution refused')
        for p in ticket['payloads']:
            if hash_file(Path(p['source']))!=(p['sha256'],p['bytes']):raise StorageError('checksum_mismatch','source changed before upload')
        # Initialization is an explicit part of approved execution, never prepare.
        configured_registry().initialize()
    service=configured_service()
    with file_lock(Path(ctx['ledger'])/'controlled-execution.lock'):
        for p in ticket['payloads']:
            key=service.ns.key(p['sha256'])
            try:service.backend.size(key)
            except StorageError as error:
                if error.code!='not_found':raise
                try:service.backend.put_immutable(key,Path(p['source']))
                except StorageError as put_error:
                    if put_error.code!='object_exists':raise
            with service.cache.acquire(p['sha256'],p['bytes'],lambda target:service.backend.download(key,target,max_bytes=p['bytes']),refresh=True):pass
            if p['sha256'] not in prior['verified_objects']:prior['verified_objects'].append(p['sha256']);write_journal(start,prior)
        def guard(dbs):
            if business_fingerprint(dbs)!=ticket['business_fingerprints']:raise StorageError('revision_conflict','business changed during upload window')
        result=_apply_transport(ticket['plan'],service,ledger,fault,business_guard=guard)
        prior['state']=result['state'];write_journal(start,prior)
        return {**result,'controlled_ticket_sha256':approved_digest,'preupload_backups':prior['backups'],'verified_physical_objects':len(prior['verified_objects']),'production':ticket['production']}
