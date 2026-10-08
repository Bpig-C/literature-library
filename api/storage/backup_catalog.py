"""Authority-side successful backup discovery and configurable due execution.

The caller owns the writer maintenance window. Retention is a plan, not GC.
"""
import json
from pathlib import Path
from datetime import datetime,timezone
from .core import StorageError,Namespace,file_lock,hash_file
from .release_control import write,staged
from .unified_release import object_read
from .snapshot_policy import plan

def read_catalog(path):
    p=Path(path)
    if not p.exists():return {'format':'litlib-backup-catalog-v1','versions':[],'attempts':[]}
    value=json.loads(p.read_text('utf-8'))
    if value.get('format')!='litlib-backup-catalog-v1':raise StorageError('configuration_error','Backup catalog format differs')
    return value

def discover(path):
    return sorted((v for v in read_catalog(path)['versions'] if v['state']=='verified'),key=lambda v:(v['verified_at'],v['id']),reverse=True)

def select(path,version_id):
    values=[v for v in discover(path) if v['id']==version_id]
    if len(values)!=1:raise StorageError('not_found','Explicit verified snapshot version unavailable')
    return values[0]

def record_verified(catalog,stage,receipt,backend,verified_at):
    root,stage_receipt,m=staged(stage);ns=Namespace(m['namespace']);sha=hash_file(root/'release.json')[0]
    if receipt.get('state')!='published' or receipt.get('manifest_sha256')!=sha or receipt.get('manifest_key')!=ns.key(sha):
        raise StorageError('checksum_mismatch','Published receipt does not bind staged manifest')
    target=root/'manifest-verified.readback'
    try:object_read(backend,{'key':ns.key(sha),'sha256':sha,'bytes':(root/'release.json').stat().st_size},target,16*1024**2)
    finally:target.unlink(missing_ok=True)
    keys={e['key'] for e in m['essentials'].values()}|{m['frontend']['key']}
    for b in m['asset_index']['bindings']:keys.add(ns.key(b.get('parent_sha256') or b['sha256']))
    v={'id':m['release_id'],'state':'verified','verified_at':verified_at,'namespace':ns.root,'manifest_key':ns.key(sha),'manifest_sha256':sha,'code_commit':m['code']['commit'],'asset_keys':sorted(keys)}
    with file_lock(Path(catalog).with_suffix('.lock')):
        c=read_catalog(catalog);prior=[p for p in c['versions'] if p['id']==v['id']]
        if prior:
            if prior[0]!=v:raise StorageError('revision_conflict','Snapshot identity cannot change')
            return v
        c['versions'].append(v);write(catalog,c)
    return v

def run_due(catalog,active_keys,backup,*,now=None,interval_days=7,retain=3):
    """backup() must return only after publish and record_verified complete."""
    now=now or datetime.now(timezone.utc).isoformat()
    with file_lock(Path(catalog).with_suffix('.scheduler.lock'),timeout=0):
        c=read_catalog(catalog);decision=plan(c['versions'],active_keys,now=now,interval_days=interval_days,retain=retain)
        if not decision['backup_due']:return {'state':'not_due','retention':decision}
        try:
            version=backup()
            if select(catalog,version['id'])!=version:raise StorageError('checksum_mismatch','Backup did not register verified version')
        except Exception as e:
            with file_lock(Path(catalog).with_suffix('.lock')):
                c=read_catalog(catalog);c['attempts'].append({'at':now,'state':'failed','code':e.code if isinstance(e,StorageError) else 'backup_failed'});write(catalog,c)
            raise
        c=read_catalog(catalog)
        return {'state':'backed_up','version':version,'retention':plan(c['versions'],active_keys,now=now,interval_days=interval_days,retain=retain)}
