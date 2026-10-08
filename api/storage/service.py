from __future__ import annotations
import hashlib,json,os,re,shutil,sqlite3,stat,time,unicodedata,uuid,zipfile
from contextlib import ExitStack,contextmanager
from pathlib import Path
from .core import CHUNK,StorageError,checked_sha,copy_stream,file_lock,hash_file,relative_key

def member_info(z,name):
    """Validate the complete directory; stream exactly one member, no extraction."""
    names=set(); total=0; selected=None
    for info in z.infolist():
        path=info.filename.rstrip('/'); normalized=unicodedata.normalize('NFC',path).casefold()
        relative_key(path)
        if normalized in names or stat.S_ISLNK(info.external_attr>>16) or info.flag_bits&1:
            raise StorageError('unsafe_package','ambiguous, symbolic or encrypted ZIP member')
        names.add(normalized); total+=info.file_size
        if info.file_size>64*1024*1024 or total>256*1024*1024 or info.file_size/max(1,info.compress_size)>1000:
            raise StorageError('unsafe_package','ZIP expansion budget exceeded')
        if info.filename==name and not info.is_dir(): selected=info
    if selected is None: raise StorageError('not_found','ZIP member absent')
    return selected

def extract_member(parent,name,destination):
    try:
        with zipfile.ZipFile(parent) as z:
            info=member_info(z,name)
            with z.open(info) as src,open(destination,'wb') as dst: copy_stream(src,dst,info.file_size)
    except (zipfile.BadZipFile,RuntimeError): raise StorageError('checksum_mismatch','ZIP CRC or format failed') from None

def member_digest(parent,name):
    try:
        with zipfile.ZipFile(parent) as z:
            info=member_info(z,name);h=hashlib.sha256();size=0
            with z.open(info) as stream:
                while chunk:=stream.read(CHUNK):h.update(chunk);size+=len(chunk)
            return h.hexdigest(),size
    except (zipfile.BadZipFile,RuntimeError):raise StorageError('checksum_mismatch','ZIP CRC or format failed') from None

class StorageService:
    def __init__(self,registry,backend,cache,staging,staging_capacity=256*1024*1024,spare_bytes=8*1024*1024):
        self.registry=registry; self.ns=registry.ns; self.backend=backend; self.cache=cache
        self.staging=Path(staging).resolve(); self.staging.mkdir(parents=True,exist_ok=True)
        self.capacity=int(staging_capacity); self.spare=int(spare_bytes)
        self.registry.validate()
    def _lock(self,kind,value): return self.staging/'locks'/(kind+'-'+hashlib.sha256(value.encode()).hexdigest()+'.lock')
    def _stage(self,source,digest,size):
        pending=self.staging/(digest+'.pending')
        self.release_completed_staging()  # nonblocking pins; current publisher's digest is pinned
        with file_lock(self._lock('staging','all')):
            if pending.exists():
                if pending.is_symlink() or not pending.is_file():raise StorageError('configuration_error','pending is not an owned regular file')
                if hash_file(pending)!=(digest,size): raise StorageError('checksum_mismatch','pending bytes corrupt')
                # Preexisting untracked bytes remain unowned and are never GC'd.
                with self.registry.conn(write=True) as c:
                    c.execute("UPDATE storage_staging_files SET state='ready' WHERE sha256=? AND pending=? AND state IN ('reserved','releasing')",(digest,str(pending)))
                return pending
            used=sum(p.stat().st_size for p in self.staging.glob('*.pending'))+sum(p.stat().st_size for p in self.staging.glob('*.part'))
            if used+size>self.capacity or shutil.disk_usage(self.staging).free<size+self.spare:
                raise StorageError('staging_full','staging capacity exhausted; preserve existing pending')
            temp=self.staging/(digest+'-'+uuid.uuid4().hex+'.part')
            # Durable ownership intent exists before creating any tool-owned file.
            with self.registry.conn(write=True) as c:
                c.execute('INSERT INTO storage_staging_files VALUES(?,?,?,?) ON CONFLICT(sha256) DO UPDATE SET bytes=excluded.bytes,pending=excluded.pending,state=excluded.state',(digest,size,str(pending),'reserved'))
            try:
                with open(source,'rb') as src,temp.open('xb') as dst: copy_stream(src,dst,size);dst.flush();os.fsync(dst.fileno())
                if hash_file(temp)!=(digest,size): raise StorageError('checksum_mismatch','source changed during staging')
                os.replace(temp,pending)
                with self.registry.conn(write=True) as c:c.execute("UPDATE storage_staging_files SET state='ready' WHERE sha256=?",(digest,))
            finally: temp.unlink(missing_ok=True)
            return pending
    def publish(self,source,*,identity,role,version,operation_id,member=None,virtual_path=None,fail_after_upload=False):
        if not isinstance(version,int) or isinstance(version,bool) or version<1: raise StorageError('invalid_request','positive fixed version required')
        if not identity or not role or len(identity)>200 or len(role)>200: raise StorageError('invalid_request','bounded binding identity required')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',operation_id): raise StorageError('invalid_request','invalid operation id')
        source=Path(source); parent_sha,parent_size=hash_file(source)
        # First lock by operation, then binding. All publishers use the same order.
        with file_lock(self._lock('operation',operation_id)),file_lock(self._lock('binding',json.dumps([identity,role,version]))),file_lock(self._lock('pending',parent_sha)):
            pending=self.staging/(parent_sha+'.pending')
            asset_sha,asset_size=parent_sha,parent_size
            if member is not None:
                relative_key(member)
                # Inspect before allocating staging; _stage verifies the parent again.
                asset_sha,asset_size=member_digest(source,member)
            request={'identity':identity,'role':role,'version':version,'sha256':asset_sha,'bytes':asset_size,'parent_sha256':parent_sha if member else None,'parent_bytes':parent_size if member else None,'member':member,'virtual_path':virtual_path}
            serialized=json.dumps(request,sort_keys=True,separators=(',',':'))
            with self.registry.conn(write=True) as c:
                previous=c.execute('SELECT request,state FROM storage_operations WHERE operation_id=?',(operation_id,)).fetchone()
                if previous and previous['request']!=serialized: raise StorageError('revision_conflict','operation id cannot change payload or binding')
                existing=c.execute('SELECT * FROM storage_bindings WHERE identity=? AND role=? AND version=?',(identity,role,version)).fetchone()
                if existing and any(existing[k]!=request[k] for k in ['sha256','bytes','parent_sha256','parent_bytes','member']):
                    raise StorageError('revision_conflict','fixed binding already contains different content/locator')
                if previous and previous['state']=='registered': return self.registry.binding(identity,role,version)
                if virtual_path:
                    alias=c.execute('SELECT identity,role,version FROM storage_paths WHERE path=?',(virtual_path,)).fetchone()
                    if alias and tuple(alias)!=(identity,role,version):raise StorageError('revision_conflict','fixed virtual path cannot be rebound')
                c.execute('INSERT OR IGNORE INTO storage_operations VALUES(?,?,?,?,?,?)',(operation_id,serialized,'staged',str(pending),None,time.time()))
            key=self.ns.key(parent_sha)
            try:
                pending=self._stage(source,parent_sha,parent_size)
                if member is not None and member_digest(pending,member)!=(asset_sha,asset_size):
                    raise StorageError('checksum_mismatch','ZIP member changed before immutable staging')
                try:
                    self.backend.size(key)
                except StorageError as e:
                    if e.code!='not_found': raise
                    try: self.backend.put_immutable(key,pending)
                    except StorageError as e:
                        if e.code!='object_exists': raise
                # Always streamed download and full parent verification, including existing object reuse.
                with self.cache.acquire(parent_sha,parent_size,lambda target:self.backend.download(key,target,max_bytes=parent_size),refresh=True): pass
                with self.registry.conn(write=True) as c:
                    c.execute('UPDATE storage_operations SET state=?,error_code=NULL,updated_at=? WHERE operation_id=?',('uploaded_verified',time.time(),operation_id))
                if fail_after_upload: raise StorageError('registration_pending','injected registration interruption')
                with self.registry.conn(write=True) as c:
                    # Unique binding + operation completion atomically in catalog.
                    for digest,size in {(parent_sha,parent_size),(asset_sha,asset_size)}:
                        row=c.execute('SELECT bytes FROM storage_objects WHERE sha256=?',(digest,)).fetchone()
                        if row and row['bytes']!=size: raise StorageError('checksum_mismatch','registered SHA size conflict')
                        c.execute('INSERT OR IGNORE INTO storage_objects VALUES(?,?,?)',(digest,size,time.time()))
                    c.execute('INSERT OR IGNORE INTO storage_bindings VALUES(?,?,?,?,?,?,?,?)',tuple(request[k] for k in ['identity','role','version','sha256','bytes','parent_sha256','parent_bytes','member']))
                    if virtual_path:
                        alias=c.execute('SELECT identity,role,version FROM storage_paths WHERE path=?',(virtual_path,)).fetchone()
                        if alias and tuple(alias)!=(identity,role,version): raise StorageError('revision_conflict','fixed virtual path cannot be rebound')
                        c.execute('INSERT OR IGNORE INTO storage_paths VALUES(?,?,?,?)',(virtual_path,identity,role,version))
                    c.execute('UPDATE storage_operations SET state=?,error_code=NULL,updated_at=? WHERE operation_id=?',('registered',time.time(),operation_id))
                result=self.registry.binding(identity,role,version)
            except StorageError as e:
                with self.registry.conn(write=True) as c:c.execute('UPDATE storage_operations SET error_code=?,updated_at=? WHERE operation_id=?',(e.code,time.time(),operation_id))
                raise
            except sqlite3.Error:
                # Uploaded_verified was committed before the binding transaction.
                # A failing/full catalog may reject even an error update; preserve
                # the prior durable phase and pending for an explicit resume.
                raise StorageError('registration_pending','catalog registration failed; verified pending preserved') from None
        # Outside publisher/cache pins. Failures/unfinished shared references remain.
        self.release_completed_staging()
        return result

    def release_completed_staging(self,*,fail_after_mark=False):
        """Only tool-created pending with every reference durably registered.

        Never scans/deletes arbitrary files, original sources, .part leftovers or
        unknown/legacy pending. Nonblocking pins avoid cleanup/publisher deadlocks.
        Releasing is durable so an interrupted unlink is safe to retry.
        """
        released=[]
        with file_lock(self._lock('staging','all')):
            with self.registry.conn() as c:rows=c.execute("SELECT * FROM storage_staging_files WHERE state IN ('ready','releasing')").fetchall()
            for row in rows:
                h=row['sha256'];p=self.staging/(checked_sha(h)+'.pending')
                if row['pending']!=str(p) or p.is_symlink():continue
                try:
                    with file_lock(self._lock('pending',h),timeout=0),file_lock(self.cache.pin_path(h),timeout=0):
                        if p.exists() and (not p.is_file() or hash_file(p)!=(h,row['bytes'])):continue
                        with self.registry.conn(write=True) as c:
                            refs=c.execute('SELECT state FROM storage_operations WHERE pending=?',(str(p),)).fetchall()
                            if not refs or any(r['state']!='registered' for r in refs):continue
                            c.execute("UPDATE storage_staging_files SET state='releasing' WHERE sha256=?",(h,))
                        if fail_after_mark:raise StorageError('cleanup_pending','injected cleanup interruption')
                        try:p.unlink(missing_ok=True)
                        except OSError:continue  # external open handle; retry, never invalidate registration
                        with self.registry.conn(write=True) as c:c.execute("UPDATE storage_staging_files SET state='released' WHERE sha256=?",(h,))
                        released.append(h)
                except StorageError as e:
                    if e.code!='busy':raise
        return released
    def resume(self,operation_id):
        with self.registry.conn() as c: row=c.execute('SELECT * FROM storage_operations WHERE operation_id=?',(operation_id,)).fetchone()
        if not row: raise StorageError('not_found','operation unavailable')
        request=json.loads(row['request'])
        if row['state']=='registered': return self.registry.binding(request['identity'],request['role'],request['version'])
        try:return self.publish(Path(row['pending']),identity=request['identity'],role=request['role'],version=request['version'],operation_id=operation_id,member=request['member'],virtual_path=request['virtual_path'])
        except FileNotFoundError:
            # Another resume may have completed and released the shared pending.
            with self.registry.conn() as c:current=c.execute('SELECT state FROM storage_operations WHERE operation_id=?',(operation_id,)).fetchone()
            if current and current['state']=='registered':return self.registry.binding(request['identity'],request['role'],request['version'])
            raise StorageError('staging_missing','unfinished staging unavailable; retry with original source and identical operation') from None
    @contextmanager
    def read(self,identity,role,version=None):
        asset=self.registry.binding(identity,role,version)
        if asset['member'] is None:
            with self.cache.acquire(asset['sha256'],asset['bytes'],lambda target:self.backend.download(self.ns.key(asset['sha256']),target,max_bytes=asset['bytes'])) as path: yield path
        else:
            # Parent pin remains held while the child is streamed/CRC checked.
            with self.cache.acquire(asset['parent_sha256'],asset['parent_bytes'],lambda target:self.backend.download(self.ns.key(asset['parent_sha256']),target,max_bytes=asset['parent_bytes'])) as parent:
                with self.cache.acquire(asset['sha256'],asset['bytes'],lambda target:extract_member(parent,asset['member'],target)) as child: yield child
