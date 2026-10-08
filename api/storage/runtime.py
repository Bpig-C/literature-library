from __future__ import annotations
import json,os,sqlite3,uuid
from pathlib import Path
from .core import Namespace,Registry,StorageError,file_lock
from .cache import DiskCache
from .backends import LocalObjectBackend,oss_from_environment
from .service import StorageService

def enabled(): return os.environ.get('LITLIB_STORAGE_MODE')=='immutable'

def required_path(name,*,file=False):
    raw=os.environ.get(name)
    if not raw or not Path(raw).is_absolute(): raise StorageError('configuration_error',name+' must be an explicit absolute path')
    p=Path(raw).resolve()
    if file and not p.is_file(): raise StorageError('configuration_error',name+' is absent; no fallback')
    return p

def configured_registry():
    root=required_path('LITLIB_LIBRARY_ROOT'); catalog=required_path('LITLIB_DB_PATH',file=True)
    if not catalog.is_relative_to(root): raise StorageError('configuration_error','catalog outside explicit data root')
    research=required_path('LITLIB_RESEARCH_ROOT'); research_db=required_path('LITLIB_RESEARCH_DB',file=True)
    if not research_db.is_relative_to(research): raise StorageError('configuration_error','research DB outside explicit research root')
    return Registry(catalog,Namespace(os.environ.get('LITLIB_STORAGE_ROOT','')))

def configured_service():
    registry=configured_registry(); registry.validate()
    cache=required_path('LITLIB_STORAGE_CACHE'); staging=required_path('LITLIB_STORAGE_STAGING')
    protected=protected_data_paths(registry)
    workdirs=[cache,staging]
    backend=os.environ.get('LITLIB_STORAGE_BACKEND')
    if backend=='local':
        if '/test/' not in registry.ns.root: raise StorageError('configuration_error','offline backend requires test namespace')
        objects=required_path('LITLIB_STORAGE_LOCAL_OBJECTS')
        workdirs.append(objects)
        store=None
    elif backend=='oss': store=None
    else: raise StorageError('configuration_error','explicit local or oss backend required')
    assert_safe_working_paths(workdirs,protected)
    claim_working_directory(cache,'cache',registry)
    claim_working_directory(staging,'staging',registry)
    if backend=='local':store=LocalObjectBackend(objects)
    else:store=oss_from_environment()
    return StorageService(registry,store,DiskCache(cache,int(os.environ.get('LITLIB_STORAGE_CACHE_BYTES',str(1024**3)))),staging,int(os.environ.get('LITLIB_STORAGE_STAGING_BYTES',str(2*1024**3))))

def overlaps(a,b):return a.is_relative_to(b) or b.is_relative_to(a)

def protected_data_paths(registry):
    library=required_path('LITLIB_LIBRARY_ROOT');research=required_path('LITLIB_RESEARCH_ROOT')
    protected={registry.catalog,required_path('LITLIB_RESEARCH_DB',file=True)}
    protected.update((library/name).resolve() for name in ['works','_inbox','_quarantine','_archive'])
    protected.update((research/name).resolve() for name in ['editing','research_sources','_research_backups'])
    # Include actual required local file/directory references outside default trees.
    specs=[(registry.catalog,library,{'source_files':['source_path'],'literature_parse_runs':['content_md_path','output_dir']}),
           (required_path('LITLIB_RESEARCH_DB',file=True),research,{'research_sources':['source_path','snapshot_path']})]
    for database,root,tables in specs:
        with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as c:
            c.execute('PRAGMA query_only=ON')
            for table,requested in tables.items():
                columns={r[1] for r in c.execute('PRAGMA table_info('+table+')')}
                for column in set(requested)&columns:
                    for (raw,) in c.execute('SELECT '+column+' FROM '+table+' WHERE '+column+" IS NOT NULL AND "+column+"<>''"):
                        if str(raw).startswith('litlib-asset://'):
                            from .references import decode_reference
                            decode_reference(raw);continue
                        path=Path(raw);protected.add((path if path.is_absolute() else root/path).resolve())
    return protected

def assert_safe_working_paths(workdirs,protected):
    for n,path in enumerate(workdirs):
        if any(overlaps(path,other) for other in workdirs[n+1:]):raise StorageError('configuration_error','working directories overlap')
        if any(overlaps(path,required) for required in protected):raise StorageError('configuration_error','working directory overlaps required data')

def claim_working_directory(path,kind,registry):
    """Empty directory or a matching ownership marker; no implicit adoption."""
    path.mkdir(parents=True,exist_ok=True)
    expected={'kind':kind,'namespace':registry.ns.root,'catalog':str(registry.catalog),'directory':str(path)}
    marker=path/'.litlib-storage-owner.json'
    with file_lock(path/'.ownership.lock'):
        if marker.exists():
            try:actual=json.loads(marker.read_text('utf-8'))
            except (ValueError,OSError):raise StorageError('configuration_error','working directory ownership marker invalid') from None
            if actual!=expected:raise StorageError('configuration_error','working directory belongs to another configuration')
            return
        if any(p.name!='.ownership.lock' for p in path.iterdir()):raise StorageError('configuration_error','working directory is not empty or explicitly owned')
        temp=path/('.owner-'+uuid.uuid4().hex+'.tmp')
        try:
            with temp.open('x',encoding='utf-8') as stream:json.dump(expected,stream);stream.flush();os.fsync(stream.fileno())
            os.replace(temp,marker)
        finally:temp.unlink(missing_ok=True)

def material_ready(path):
    if not enabled(): return Path(path).is_file()
    registry=configured_registry();registry.validate()
    return registry.path_registered(path)  # registered reference, not an OSS health probe

def validate_startup():
    service=configured_service()
    try:
        with sqlite3.connect(service.registry.catalog.as_uri()+'?mode=ro',uri=True) as c:
            c.execute('PRAGMA query_only=ON')
            for query in ['SELECT id FROM works LIMIT 0','SELECT id,work_id,source_path FROM source_files LIMIT 0','SELECT id,work_id,source_file_id,status,content_md_path FROM literature_parse_runs LIMIT 0']:
                c.execute(query)
            if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise StorageError('configuration_error','catalog integrity check failed')
        from ..research_context import ResearchContext
        from ..research_schema import verify_schema
        state=verify_schema(ResearchContext(required_path('LITLIB_RESEARCH_ROOT'),required_path('LITLIB_RESEARCH_DB',file=True),read_only=True))
        if not state['ok']:raise StorageError('configuration_error','research schema verification failed; explicit migration required')
    except sqlite3.Error:raise StorageError('configuration_error','required catalog schema unavailable') from None
    return service
