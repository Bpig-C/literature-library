"""Cooperative immutable epoch handover; freeze source before publishing successor.

Owner secrets are process-only and never part of a release. No expiry permits
automatic failover: loss of the current owner requires deliberate recovery.
"""
import hashlib,json,tempfile
from datetime import datetime,timezone
from pathlib import Path
from contextlib import contextmanager
from .core import StorageError,file_lock,Namespace,checked_sha
from .release_control import write

class Authority:
    def __init__(self,backend,namespace,owner_token,epoch,local_root,release_sha256=None):
        if len(owner_token)<32 or not isinstance(epoch,int) or epoch<0:raise StorageError('configuration_error','Explicit authority token and nonnegative epoch required')
        self.backend=backend;self.ns=Namespace(namespace);self.owner=hashlib.sha256(owner_token.encode()).hexdigest();self.epoch=epoch
        self.release_sha256=checked_sha(release_sha256) if release_sha256 is not None else None
        self.root=Path(local_root).resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.marker=self.root/f'{self.owner}-{epoch}.frozen.json';self.lock=self.root/f'{self.owner}-{epoch}.lock'
    def key(self,epoch):return self.ns.root+f'control/authority/epochs/{epoch:010d}.json'
    def read(self,epoch):
        with tempfile.TemporaryDirectory(dir=self.root) as t:
            p=Path(t)/'epoch.json';self.backend.download(self.key(epoch),p,max_bytes=8192);v=json.loads(p.read_text('utf-8'))
        if v.get('format')!='litlib-authority-epoch-v1' or v.get('namespace')!=self.ns.root or v.get('epoch')!=epoch:raise StorageError('checksum_mismatch','Authority record differs')
        return v
    def put(self,value):
        with tempfile.TemporaryDirectory(dir=self.root) as t:
            p=Path(t)/'epoch.json';write(p,value)
            try:self.backend.put_immutable(self.key(value['epoch']),p)
            except StorageError as e:
                if e.code!='object_exists':raise
                if self.read(value['epoch'])!=value:raise StorageError('revision_conflict','Authority epoch already belongs to another owner/release')
        return value
    def initialize(self):
        if self.epoch!=0:raise StorageError('permission_denied','Only initial epoch can be initialized')
        return self.put({'format':'litlib-authority-epoch-v1','namespace':self.ns.root,'epoch':0,'owner_sha256':self.owner,'predecessor':None,'release':None})
    def check_remote(self):
        v=self.read(self.epoch)
        if v['owner_sha256']!=self.owner:raise StorageError('permission_denied','This process is not the current authority owner')
        if self.epoch>0 and (self.release_sha256 is None or (v.get('release') or {}).get('manifest_sha256')!=self.release_sha256):raise StorageError('revision_conflict','Writer must use the exact handover release')
        try:self.backend.size(self.key(self.epoch+1))
        except StorageError as e:
            if e.code!='not_found':raise
        else:raise StorageError('revision_conflict','Authority has been handed over; old writer fenced')
        return v
    @contextmanager
    def write_guard(self):
        with file_lock(self.lock,timeout=0):
            if self.marker.exists():raise StorageError('permission_denied','Source authority is frozen')
            self.check_remote();yield
    def handover(self,target_owner_sha256,release):
        checked_sha(target_owner_sha256);sha=checked_sha(release['manifest_sha256'])
        if release['manifest_key']!=self.ns.key(sha):raise StorageError('invalid_request','Exact published release descriptor required')
        with file_lock(self.lock,timeout=0):
            value={'format':'litlib-authority-epoch-v1','namespace':self.ns.root,'epoch':self.epoch+1,'owner_sha256':target_owner_sha256,'predecessor':self.owner,'release':release}
            if self.marker.exists():
                prior=json.loads(self.marker.read_text('utf-8'))
                if prior.get('phase')=='frozen':write(self.marker,value)
                elif prior!=value:raise StorageError('revision_conflict','Frozen handover cannot change target/release')
            else:
                self.check_remote();write(self.marker,value) # durable freeze precedes network request
            return self.put(value)
    def freeze(self):
        """Invoke before the final migration snapshot; source cannot resume writes."""
        with file_lock(self.lock,timeout=0):
            if self.marker.exists():return json.loads(self.marker.read_text('utf-8'))
            self.check_remote()
            value={'format':'litlib-authority-freeze-v1','phase':'frozen','namespace':self.ns.root,'epoch':self.epoch,'owner_sha256':self.owner,'frozen_at':datetime.now(timezone.utc).isoformat()}
            write(self.marker,value);return value

def configured_authority():
    import os
    from .runtime import configured_service,required_path
    service=configured_service()
    try:epoch=int(os.environ['LITLIB_AUTHORITY_EPOCH']);token=os.environ['LITLIB_AUTHORITY_TOKEN']
    except (KeyError,ValueError):raise StorageError('configuration_error','Writer requires explicit authority epoch/token') from None
    from .core import hash_file
    library=required_path('LITLIB_LIBRARY_ROOT')
    manifest=library.parent.parent/'release-manifest.json'
    if not manifest.is_file():raise StorageError('configuration_error','Writer requires its restored release manifest')
    return Authority(service.backend,service.ns.root,token,epoch,library.parent/'.authority',hash_file(manifest)[0])
