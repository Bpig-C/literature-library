"""Explicit historical transport migration; apply is limited to synthetic DBs.

Scientific rows, text snapshots, review and adoption are never reconstructed.
The two independent SQLite commits are journaled and compensated by exact CAS.
"""
import hashlib
import json
import sqlite3
from contextlib import ExitStack
from pathlib import Path
from .core import StorageError, file_lock, hash_file
from .runtime import configured_service, required_path
from .references import asset_reference
from .producers import lock_path

FIELDS = {
    'catalog': {'source_files': {'source_path'},
                'literature_parse_runs': {'source_path', 'content_md_path', 'content_json_path', 'package_path'}},
    'research': {'research_sources': {'source_path', 'snapshot_path'}},
}

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)

def connect(path, write=False):
    c = sqlite3.connect(path.as_uri() + ('?mode=rw' if write else '?mode=ro'), uri=True, timeout=15)
    c.row_factory = sqlite3.Row
    if write:
        c.execute('BEGIN IMMEDIATE')
    return c

def paths(service):
    return {'catalog': service.registry.catalog, 'research': required_path('LITLIB_RESEARCH_DB', file=True)}

def checked_plan(plan, service):
    if set(plan) != {'format', 'assets', 'patches'} or plan['format'] != 'litlib-transport-migration-v1':
        raise StorageError('invalid_request', 'explicit v1 transport manifest required')
    seen = set()
    with ExitStack() as stack:
        dbs = {k: connect(p) for k, p in paths(service).items()}
        for c in dbs.values(): stack.callback(c.close)
        for a in plan['assets']:
            key = (a['identity'], a['role'], a['version'])
            if key in seen or type(a['version']) is not int or a['version'] < 1:
                raise StorageError('invalid_request', 'duplicate or invalid fixed asset binding')
            seen.add(key)
            if a['role'] == 'pdf':
                row = dbs['catalog'].execute('SELECT work_id,content_sha256,file_size FROM source_files WHERE id=?', (a['identity'],)).fetchone()
                if not row or row['work_id'] != a['work_id'] or (row['content_sha256'], row['file_size']) != (a['sha256'], a['bytes']):
                    raise StorageError('checksum_mismatch', 'PDF catalog identity/fingerprint mismatch')
            else:
                row = dbs['catalog'].execute('SELECT work_id,source_file_id,status FROM literature_parse_runs WHERE id=?', (a['identity'],)).fetchone()
                if not row or row['work_id'] != a['work_id'] or row['source_file_id'] != a['source_file_id'] or row['status'] != 'succeeded':
                    raise StorageError('invalid_request', 'fixed parse ownership/status mismatch')
            try: binding = service.registry.binding(*key)
            except StorageError as error:
                if error.code != 'not_found': raise
                binding = None
            if binding:
                if (binding['sha256'], binding['bytes'], binding['member']) != (a['sha256'], a['bytes'], a.get('member')):
                    raise StorageError('revision_conflict', 'immutable binding differs from manifest')
            elif a.get('member'):
                from .service import member_digest
                if member_digest(Path(a['source']), a['member']) != (a['sha256'], a['bytes']):
                    raise StorageError('checksum_mismatch', 'ZIP member changed')
            elif hash_file(Path(a['source'])) != (a['sha256'], a['bytes']):
                raise StorageError('checksum_mismatch', 'migration asset changed')
        cells = set()
        for p in plan['patches']:
            if p['database'] not in FIELDS or p['table'] not in FIELDS[p['database']] or p['column'] not in FIELDS[p['database']][p['table']]:
                raise StorageError('invalid_request', 'only whitelisted transport fields can migrate')
            cell = (p['database'], p['table'], p['id'], p['column'])
            if cell in cells: raise StorageError('invalid_request', 'duplicate transport cell')
            cells.add(cell)
            key = (p['identity'], p['role'], p['version'])
            if key not in seen: raise StorageError('invalid_request', 'patch requires an explicit asset')
            asset = next(a for a in plan['assets'] if (a['identity'], a['role'], a['version']) == key)
            expected = asset_reference(p['identity'], p['version']) if p['role'] == 'pdf' else asset.get('virtual_path')
            if not expected or p['new'] != expected or p['old'] == p['new']:
                raise StorageError('invalid_request', 'patch must use fixed PDF reference or registered parse path')
            c = dbs[p['database']]
            row = c.execute('SELECT * FROM ' + p['table'] + ' WHERE id=?', (p['id'],)).fetchone()
            if not row or row[p['column']] not in (p['old'], p['new']):
                raise StorageError('revision_conflict', 'transport cell changed outside this migration')
            if p['table'] == 'source_files' and (p['id'] != p['identity'] or p['role'] != 'pdf'):
                raise StorageError('invalid_request', 'source PDF identity mismatch')
            if p['table'] == 'literature_parse_runs':
                identity = row['source_file_id'] if p['column'] == 'source_path' else row['id']
                roles = {'source_path':'pdf', 'content_md_path':'md', 'content_json_path':'json', 'package_path':'package'}
                if identity != p['identity'] or roles[p['column']] != p['role']:
                    raise StorageError('invalid_request', 'parse field/asset mismatch')
            if p['table'] == 'research_sources':
                if p['role'] != 'pdf' or row['source_file_id'] != p['identity'] or row['work_id'] != asset['work_id'] or row['source_sha256'] != asset['sha256']:
                    raise StorageError('invalid_request', 'research fixed source fingerprint mismatch')
        return hashlib.sha256(canonical(plan).encode()).hexdigest()

def dry_run(plan, service=None):
    service = service or configured_service()
    digest = checked_plan(plan, service)
    return {'manifest_sha256':digest, 'assets':len(plan['assets']), 'transport_cells':len(plan['patches']), 'writes':False}

def write_journal(path, journal):
    import os
    temp = path.with_suffix('.part')
    with temp.open('w', encoding='utf-8') as stream:
        stream.write(canonical(journal)); stream.flush(); os.fsync(stream.fileno())
    temp.replace(path)

def cas(c, p, before, after):
    row = c.execute('SELECT ' + p['column'] + ' FROM ' + p['table'] + ' WHERE id=?', (p['id'],)).fetchone()
    if row and row[0] == after: return
    if not row or row[0] != before: raise StorageError('revision_conflict', 'compensation/migration conflicts with another writer; preserve journal')
    c.execute('UPDATE ' + p['table'] + ' SET ' + p['column'] + '=? WHERE id=? AND ' + p['column'] + ' IS ?', (after, p['id'], before))

def apply(plan, service=None, fault=None):
    # Never infer production authorization from a dry-run or a supplied DB path.
    from .synthetic_snapshot import synthetic_context
    root, guarded = synthetic_context()
    service = service or guarded
    if service.registry.catalog != guarded.registry.catalog or service.ns.root != guarded.ns.root:
        raise StorageError('configuration_error', 'synthetic migration context mismatch')
    return _apply_transport(plan, service, root, fault, synthetic=True)

def _apply_transport(plan, service, root, fault=None, *, synthetic=False, business_guard=None):
    with file_lock(lock_path(service)):
        digest = checked_plan(plan, service)
        ledger = root/'migration-ledger'/digest
        ledger.mkdir(parents=True, exist_ok=True)
        journal_path = ledger/'journal.json'
        journal = json.loads(journal_path.read_text('utf-8')) if journal_path.exists() else {'manifest_sha256':digest, 'state':'publishing', 'databases':{k:str(v) for k,v in paths(service).items()}, 'plan':plan}
        if journal['manifest_sha256'] != digest or journal['databases'] != {k:str(v) for k,v in paths(service).items()} or journal['plan'] != plan:
            raise StorageError('revision_conflict', 'migration ledger context changed')
        write_journal(journal_path, journal)
        for index, a in enumerate(plan['assets']):
            args = {k:a.get(k) for k in ['identity','role','version','member','virtual_path']}
            op = 'migration-'+digest[:48]+'-'+str(index)
            with service.registry.conn() as c:
                prior = c.execute('SELECT state FROM storage_operations WHERE operation_id=?', (op,)).fetchone()
            if prior: service.resume(op)
            else: service.publish(Path(a['source']), operation_id=op, **args)
            with service.read(a['identity'], a['role'], a['version']) as p:
                if hash_file(p) != (a['sha256'], a['bytes']): raise StorageError('checksum_mismatch', 'registered migration asset unreadable')
        if fault: fault('after_assets')
        connections = {}
        committed = False
        research_committed = False
        try:
            for k,p in paths(service).items(): connections[k] = connect(p, True)
            if business_guard: business_guard(connections)
            # Both writer locks protect a coherent pair of committed pre-images.
            if not journal.get('snapshot'):
                snapshots = {}
                for k,p in paths(service).items():
                    destination = ledger/(k+'.sqlite')
                    from contextlib import closing
                    with closing(sqlite3.connect(p.as_uri()+'?mode=ro', uri=True)) as src, closing(sqlite3.connect(destination)) as dst: src.backup(dst)
                    snapshots[k] = {'path':str(destination), 'sha256':hash_file(destination)[0]}
                journal['snapshot'] = snapshots
            for p in plan['patches']: cas(connections[p['database']], p, p['old'], p['new'])
            journal['state'] = 'prepared'; write_journal(journal_path, journal)
            if fault: fault('before_catalog_commit')
            connections['catalog'].commit(); committed = True
            journal['state'] = 'catalog_committed'; write_journal(journal_path, journal)
            if fault: fault('after_catalog_commit')
            connections['research'].commit()
            research_committed = True
            journal['state'] = 'applied'; write_journal(journal_path, journal)
        except Exception:
            for c in connections.values(): c.rollback()
            if committed and not research_committed:
                # Exact field compensation; never restore an entire DB over others.
                c = connect(paths(service)['catalog'], True)
                try:
                    for p in plan['patches']:
                        if p['database'] == 'catalog': cas(c, p, p['new'], p['old'])
                    c.commit()
                finally: c.close()
            journal['state'] = 'applied' if research_committed else 'compensated'
            write_journal(journal_path, journal)
            raise
        finally:
            for c in connections.values(): c.close()
        return {'manifest_sha256':digest, 'state':journal['state'], 'snapshot':journal['snapshot'], 'synthetic_only':synthetic}
