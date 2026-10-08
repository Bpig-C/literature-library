"""Ownership of newly planned ingest copies, never inferred from legacy paths."""
import json
import sqlite3
import uuid
from pathlib import Path
from .core import StorageError, file_lock, hash_file
from .runtime import configured_service, required_path
from .producers import job_id, lock_path
from .references import asset_reference

def prepare_ingest(plan, service=None):
    service = service or configured_service()
    library = required_path('LITLIB_LIBRARY_ROOT')
    if Path(plan.library_root).resolve() != library:
        raise StorageError('configuration_error', 'ingest ownership root mismatch')
    with file_lock(lock_path(service)):
        for action in plan.ingests:
            target = Path(action.library_path)
            if not target.is_absolute() or not target.resolve().is_relative_to(library/'works') or target.exists():
                raise StorageError('revision_conflict', 'new owned ingest destination must be absent within works')
            if hash_file(Path(action.inbox_path)) != (action.content_sha256, action.file_size):
                raise StorageError('checksum_mismatch', 'planned inbox changed')
            jid = job_id('pdf', action.source_file_id)
            owner = {'job_id':jid, 'path':str(target), 'catalog':str(service.registry.catalog), 'library':str(library),
                     'sha256':action.content_sha256, 'bytes':action.file_size, 'nonce':uuid.uuid4().hex, 'release_state':'owned'}
            asset = {'identity':action.source_file_id, 'role':'pdf', 'version':1, 'source':str(target), 'member':None, 'virtual_path':None, 'owned_copy':owner}
            with service.registry.conn(write=True) as c:
                if c.execute('SELECT 1 FROM source_files WHERE id=?', (action.source_file_id,)).fetchone():
                    raise StorageError('revision_conflict', 'existing source cannot acquire new-copy ownership')
                c.execute("INSERT INTO storage_producer_jobs(id,kind,source_file_id,version,state,artifacts) VALUES(?,'pdf',?,1,'preparing',?)", (jid,action.source_file_id,json.dumps([asset])))
            target.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive marker precedes exclusive copy. Failures retain evidence.
            with marker_path(target, action.source_file_id).open('x', encoding='utf-8') as stream: json.dump(owner, stream)

def marker_path(target, source_id):
    return target.parent/('.litlib-ingest-owned-'+source_id+'.json')

def release_ingested_pdf(jid, service=None):
    service = service or configured_service()
    with file_lock(lock_path(service)):
        with service.registry.conn() as c:
            row = c.execute('SELECT * FROM storage_producer_jobs WHERE id=?', (jid,)).fetchone()
            if not row or row['kind'] != 'pdf' or row['state'] != 'registered':
                raise StorageError('producer_incomplete', 'only registered PDF job can release its new copy')
            job = dict(row)
        assets = json.loads(job['artifacts']); owner = assets[0].get('owned_copy') if assets else None
        if not owner: raise StorageError('configuration_error', 'legacy/unowned PDF preserved')
        if owner['release_state'] == 'released': return {'job_id':jid, 'released':False, 'reason':'already released'}
        target = Path(owner['path']); library = required_path('LITLIB_LIBRARY_ROOT')
        if owner['job_id'] != jid or owner['catalog'] != str(service.registry.catalog) or owner['library'] != str(library) or str(target) != assets[0]['source'] or not target.is_absolute() or not target.resolve().is_relative_to(library/'works'):
            raise StorageError('configuration_error', 'owned PDF outside recorded task destination')
        for p in [target, *target.parents]:
            if p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()): raise StorageError('configuration_error', 'linked source preserved')
        marker = marker_path(target, job['source_file_id'])
        try: recorded = json.loads(marker.read_text('utf-8'))
        except (OSError, ValueError): raise StorageError('configuration_error', 'new-copy ownership marker missing') from None
        if {k:v for k,v in owner.items() if k!='release_state'} != {k:v for k,v in recorded.items() if k!='release_state'}:
            raise StorageError('configuration_error', 'ownership marker differs from durable job')
        if target.exists() and hash_file(target) != (owner['sha256'], owner['bytes']):
            raise StorageError('checksum_mismatch', 'modified owned PDF preserved')
        if not target.exists() and owner['release_state'] != 'releasing':
            raise StorageError('revision_conflict', 'unexpected missing PDF; preserve ownership evidence')
        binding = service.registry.binding(job['source_file_id'], 'pdf', 1)
        if (binding['sha256'],binding['bytes']) != (owner['sha256'],owner['bytes']): raise StorageError('checksum_mismatch', 'registered PDF fingerprint changed')
        # Forced cold download, bounded by the normal cache reservation and pins.
        with service.cache.acquire(binding['sha256'],binding['bytes'],lambda p:service.backend.download(service.ns.key(binding['sha256']),p,max_bytes=binding['bytes']),refresh=True): pass
        reference = asset_reference(job['source_file_id'], 1)
        with sqlite3.connect(required_path('LITLIB_RESEARCH_DB', file=True).as_uri()+'?mode=ro', uri=True) as research:
            if research.execute('SELECT 1 FROM research_sources WHERE source_path=? OR snapshot_path=? LIMIT 1', (str(target),str(target))).fetchone():
                raise StorageError('revision_conflict', 'legacy research reference still needs migration')
        with service.registry.conn(write=True) as c:
            source = c.execute('SELECT source_path,content_sha256,file_size FROM source_files WHERE id=?', (job['source_file_id'],)).fetchone()
            if not source or source['source_path'] not in (str(target), reference) or (source['content_sha256'],source['file_size']) != (owner['sha256'],owner['bytes']):
                raise StorageError('revision_conflict', 'source changed; local copy preserved')
            if c.execute('SELECT 1 FROM source_files WHERE id<>? AND (source_path=? OR archive_path=?) LIMIT 1', (job['source_file_id'],str(target),str(target))).fetchone() or c.execute('SELECT 1 FROM literature_parse_runs WHERE source_file_id<>? AND source_path=? LIMIT 1', (job['source_file_id'],str(target))).fetchone():
                raise StorageError('revision_conflict', 'shared legacy source copy preserved')
            owner['release_state']='releasing'
            c.execute('UPDATE source_files SET source_path=? WHERE id=?', (reference,job['source_file_id']))
            c.execute('UPDATE literature_parse_runs SET source_path=? WHERE source_file_id=? AND source_path=?', (reference,job['source_file_id'],str(target)))
            c.execute('UPDATE library_migration_files SET library_path=? WHERE source_file_id=? AND library_path=?', (reference,job['source_file_id'],str(target)))
            c.execute('UPDATE storage_producer_jobs SET artifacts=? WHERE id=?', (json.dumps(assets),jid))
        # A crash after pointer commit retries using the durable releasing state.
        if target.exists():
            if hash_file(target) != (owner['sha256'],owner['bytes']): raise StorageError('checksum_mismatch', 'source changed during release; preserve it')
            target.unlink()
        owner['release_state']='released'
        with service.registry.conn(write=True) as c: c.execute('UPDATE storage_producer_jobs SET artifacts=? WHERE id=?', (json.dumps(assets),jid))
        marker.unlink()
        return {'job_id':jid, 'released':True, 'reference':reference, 'bytes':owner['bytes'], 'originals_preserved':True}
