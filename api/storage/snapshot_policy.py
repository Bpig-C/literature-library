"""Successful-version retention planning, separate from daily asset publication.

This module never deletes objects. It produces a reviewable plan only.
"""
from datetime import datetime,timezone,timedelta
from .core import StorageError,Namespace,checked_sha

def timestamp(value):
    t=datetime.fromisoformat(value.replace('Z','+00:00'))
    if t.tzinfo is None:raise StorageError('invalid_request','Snapshot times require explicit timezone')
    return t.astimezone(timezone.utc)

def plan(versions,active_keys,*,now,interval_days=7,retain=3):
    if not isinstance(retain,int) or retain<1 or not isinstance(interval_days,int) or interval_days<1:
        raise StorageError('invalid_request','Positive retention and interval required')
    current=timestamp(now);success=[];seen=set();all_keys=set()
    for v in versions:
        if v['id'] in seen:raise StorageError('revision_conflict','Duplicate snapshot identity')
        seen.add(v['id'])
        if v['state'] not in {'verified','retired'}:continue
        ns=Namespace(v['namespace']);checked_sha(v['manifest_sha256'])
        if v['manifest_key']!=ns.key(v['manifest_sha256']):raise StorageError('checksum_mismatch','Snapshot manifest locator differs')
        keys=set(v['asset_keys'])|{v['manifest_key']}
        for key in keys:
            if not key.startswith(ns.root+'objects/sha256/') or ns.key(key.rsplit('/',1)[-1])!=key:
                raise StorageError('invalid_request','Snapshot asset outside exact namespace')
        if v['state']=='verified':success.append((timestamp(v['verified_at']),v,keys))
        all_keys|=keys
    success.sort(key=lambda x:(x[0],x[1]['id']),reverse=True)
    keep=success[:retain];protected=set(active_keys)
    for _,v,keys in keep:protected|=keys
    latest=success[0][0] if success else None
    return {'policy':{'interval_days':interval_days,'retain_successful':retain},
        'backup_due':latest is None or current>=latest+timedelta(days=interval_days),
        'keep':[v['id'] for _,v,_ in keep],'retire_snapshot_records':[v['id'] for _,v,_ in success[retain:]],
        'protected_keys':sorted(protected),'unreferenced_candidates':sorted(all_keys-protected),
        'failed_versions_count':sum(v['state'] not in {'verified','retired'} for v in versions),
        'deletion_performed':False,'requires_exact_review_before_deletion':True}
