from __future__ import annotations
import os, shutil, sqlite3, time
from contextlib import contextmanager
from pathlib import Path
from .core import StorageError, checked_sha, file_lock, hash_file

class DiskCache:
    """Rebuildable index; cross-process pins held through response streaming."""
    def __init__(self,root,capacity,spare_bytes=8*1024*1024):
        self.root=Path(root).resolve(); self.root.mkdir(parents=True,exist_ok=True)
        self.capacity=int(capacity); self.spare=int(spare_bytes)
        if self.capacity<1 or self.spare<0: raise StorageError('configuration_error','invalid cache budget')
        self.index=self.root/'cache.sqlite'; self.guard=self.root/'index.lock'
        with file_lock(self.guard),self.conn() as c:
            c.execute('CREATE TABLE IF NOT EXISTS entries (sha TEXT PRIMARY KEY, bytes INTEGER NOT NULL, touched REAL NOT NULL, state TEXT NOT NULL)')
    @contextmanager
    def conn(self):
        c=sqlite3.connect(self.index,timeout=30)
        try:
            with c:yield c
        finally:c.close()
    def path(self,h): return self.root/(checked_sha(h)+'.asset')
    def pin_path(self,h): return self.root/'pins'/(checked_sha(h)+'.lock')
    def _reserve(self,h,size,additional=None):
        if size<0 or size>self.capacity: raise StorageError('cache_full','asset exceeds disk cache budget')
        with file_lock(self.guard),self.conn() as c:
            # A warming entry can be reclaimed only when its process pin is free.
            rows=c.execute('SELECT sha,bytes,state FROM entries WHERE sha<>? ORDER BY touched',(h,)).fetchall()
            used=c.execute('SELECT COALESCE(SUM(bytes),0) FROM entries WHERE sha<>?',(h,)).fetchone()[0]
            needed=max(0,used+size-self.capacity)
            for other,n,state in rows:
                if needed<=0: break
                try:
                    with file_lock(self.pin_path(other),timeout=0):
                        self.path(other).unlink(missing_ok=True)
                        (self.root/(other+'.part')).unlink(missing_ok=True)
                        c.execute('DELETE FROM entries WHERE sha=?',(other,)); needed-=n
                except StorageError as e:
                    if e.code!='busy': raise
            if needed>0: raise StorageError('cache_full','cache entries are pinned; retry after reads finish')
            if shutil.disk_usage(self.root).free < (size if additional is None else additional)+self.spare:
                raise StorageError('cache_full','insufficient free disk for verified download')
            c.execute('INSERT OR REPLACE INTO entries VALUES(?,?,?,?)',(h,size,time.time(),'warming'))
    @contextmanager
    def acquire(self,h,size,loader,refresh=False):
        p=self.path(h)
        with file_lock(self.pin_path(h)):
            if not refresh and p.is_file() and hash_file(p)==(h,size):
                self._reserve(h,size,additional=0)
                with file_lock(self.guard),self.conn() as c:
                    c.execute('INSERT OR REPLACE INTO entries VALUES(?,?,?,?)',(h,size,time.time(),'ready'))
                yield p; return
            p.unlink(missing_ok=True)
            self._reserve(h,size); temp=self.root/(h+'.part'); temp.unlink(missing_ok=True)
            try:
                loader(temp)
                if hash_file(temp)!=(h,size): raise StorageError('checksum_mismatch','download or member SHA/size mismatch')
                with temp.open('r+b') as stream: os.fsync(stream.fileno())
                os.replace(temp,p)
                with file_lock(self.guard),self.conn() as c:
                    c.execute('UPDATE entries SET state=?,touched=? WHERE sha=?',('ready',time.time(),h))
                yield p
            except BaseException:
                if not p.is_file():
                    with file_lock(self.guard),self.conn() as c: c.execute('DELETE FROM entries WHERE sha=?',(h,))
                raise
            finally: temp.unlink(missing_ok=True)
    def clear(self):
        """Only unpinned cache, never publisher staging or authoritative objects."""
        with file_lock(self.guard),self.conn() as c:
            for (h,) in c.execute('SELECT sha FROM entries').fetchall():
                try:
                    with file_lock(self.pin_path(h),timeout=0):
                        self.path(h).unlink(missing_ok=True); (self.root/(h+'.part')).unlink(missing_ok=True)
                        c.execute('DELETE FROM entries WHERE sha=?',(h,))
                except StorageError as e:
                    if e.code!='busy': raise
