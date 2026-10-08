"""Small immutable discovery records survive loss of the authority's disk."""
import json,re,tempfile
from pathlib import Path
from .core import Namespace,StorageError,checked_sha,hash_file
from .release_control import write
from .unified_release import object_read

FIELDS=('id','state','verified_at','namespace','manifest_key','manifest_sha256','code_commit')
def validate(v,namespace):
    ns=Namespace(namespace)
    if set(v)!=set(FIELDS) or not re.fullmatch('[0-9a-f]{32}',v['id']) or v['state']!='verified' or v['namespace']!=namespace or v['manifest_key']!=ns.key(checked_sha(v['manifest_sha256'])):raise StorageError('invalid_request','Exact immutable verified discovery record required')
    return ns.root+'control/backups/versions/'+v['id']+'.json'

def publish_discovery(backend,version,scratch):
    v={k:version[k] for k in FIELDS};key=validate(v,v['namespace'])
    with tempfile.TemporaryDirectory(dir=scratch) as t:
        p=Path(t)/'version.json';write(p,v)
        try:backend.put_immutable(key,p)
        except StorageError as e:
            if e.code!='object_exists':raise
            q=Path(t)/'existing.json';backend.download(key,q,max_bytes=8192);prior=json.loads(q.read_text('utf-8'));validate(prior,v['namespace'])
            compare=dict(v);compare['verified_at']=prior['verified_at']
            if compare!=prior:raise StorageError('revision_conflict','Discovery version cannot change')
            v=prior
        return v

def discover_remote(backend,namespace,*,retain=3,limit=1000):
    ns=Namespace(namespace)
    if retain<1 or limit<retain:raise StorageError('invalid_request','Explicit positive discovery budgets required')
    versions=[]
    with tempfile.TemporaryDirectory() as t:
        for key in backend.list_keys(ns.root+'control/backups/versions/',limit):
            p=Path(t)/'descriptor.json';backend.download(key,p,max_bytes=8192);v=json.loads(p.read_text('utf-8'))
            if key!=validate(v,namespace):raise StorageError('checksum_mismatch','Discovery record identity differs from locator')
            versions.append(v)
        from .snapshot_policy import timestamp
        versions.sort(key=lambda v:(timestamp(v['verified_at']),v['id']),reverse=True)
        selected=versions[:retain]
        # Only the retained choices require manifest reads, bounded to 16 MiB.
        for v in selected:
            p=Path(t)/'manifest.json';backend.download(v['manifest_key'],p,max_bytes=16*1024**2)
            if hash_file(p)[0]!=v['manifest_sha256']:raise StorageError('checksum_mismatch','Discovered manifest SHA differs')
            m=json.loads(p.read_text('utf-8'))
            if m['release_id']!=v['id'] or m['namespace']!=namespace or m['code']['commit']!=v['code_commit']:raise StorageError('checksum_mismatch','Discovered release metadata differs')
    return selected
