from __future__ import annotations
import hashlib, os, re, sqlite3, time
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

CHUNK = 1024 * 1024

class StorageError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)

def hash_file(path: Path) -> tuple[str, int]:
    h = hashlib.sha256(); size = 0
    with open(path, 'rb') as stream:
        while chunk := stream.read(CHUNK): h.update(chunk); size += len(chunk)
    return h.hexdigest(), size

def copy_stream(source, target, limit: int | None = None):
    size = 0
    while chunk := source.read(CHUNK):
        size += len(chunk)
        if limit is not None and size > limit: raise StorageError('quota_exceeded', 'stream exceeds reservation')
        target.write(chunk)
    return size

def checked_sha(value: str):
    if not re.fullmatch(r'[0-9a-f]{64}', value): raise StorageError('invalid_request', 'full SHA256 required')
    return value

def relative_key(value: str):
    if not value or value.startswith('/') or '\\' in value or ':' in value or any(p in {'', '.', '..'} for p in value.split('/')):
        raise StorageError('invalid_request', 'unsafe relative key')
    return value

class Namespace:
    def __init__(self, root: str):
        if not re.fullmatch(r'research/agent-loss-of-control/literature/(prod/|test/[A-Za-z0-9][A-Za-z0-9_-]{0,79}/)', root):
            raise StorageError('configuration_error', 'explicit isolated storage root required')
        self.root = root
    def key(self, digest):
        checked_sha(digest)
        return self.root + f'objects/sha256/{digest[:2]}/{digest}'

@contextmanager
def file_lock(path: Path, timeout: float = 30):
    """Cooperative process lock. Never remove a lock inode while it is in use."""
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = open(path, 'a+b'); stream.seek(0, 2)
    if stream.tell() == 0: stream.write(b'0'); stream.flush()
    deadline = time.monotonic() + timeout
    while True:
        try:
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.monotonic() >= deadline:
                stream.close(); raise StorageError('busy', 'storage operation is busy; retry')
            time.sleep(0.02)
    try: yield
    finally:
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_UN)
        stream.close()

SCHEMA = '''
CREATE TABLE IF NOT EXISTS storage_settings (id INTEGER PRIMARY KEY CHECK(id=1), root TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS storage_objects (sha256 TEXT PRIMARY KEY, bytes INTEGER NOT NULL CHECK(bytes>=0), verified_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS storage_bindings (
 identity TEXT NOT NULL, role TEXT NOT NULL, version INTEGER NOT NULL CHECK(version>0),
 sha256 TEXT NOT NULL, bytes INTEGER NOT NULL, parent_sha256 TEXT, parent_bytes INTEGER, member TEXT,
 PRIMARY KEY(identity,role,version), FOREIGN KEY(sha256) REFERENCES storage_objects(sha256));
CREATE TABLE IF NOT EXISTS storage_operations (
 operation_id TEXT PRIMARY KEY, request TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('staged','uploaded_verified','registered')),
 pending TEXT NOT NULL, error_code TEXT, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS storage_paths (path TEXT PRIMARY KEY, identity TEXT NOT NULL, role TEXT NOT NULL, version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS storage_staging_files (
 sha256 TEXT PRIMARY KEY, bytes INTEGER NOT NULL, pending TEXT NOT NULL UNIQUE,
 state TEXT NOT NULL CHECK(state IN ('reserved','ready','releasing','released')));
CREATE TABLE IF NOT EXISTS storage_producer_jobs (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('pdf','parse')),
 source_file_id TEXT NOT NULL, parse_run_id TEXT, version INTEGER NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('preparing','artifacts_ready','registered','failed')),
 artifacts TEXT NOT NULL DEFAULT '[]', error_code TEXT, backend TEXT, task_id TEXT,
 UNIQUE(kind,source_file_id,version));
'''

class Registry:
    def __init__(self, catalog: Path, namespace: Namespace):
        self.catalog = Path(catalog).resolve(); self.ns = namespace
        if not self.catalog.is_file(): raise StorageError('configuration_error', 'explicit catalog must already exist')
    @contextmanager
    def conn(self, write=False):
        c = sqlite3.connect(self.catalog.as_uri() + '?mode=rw', uri=True, timeout=30)
        c.row_factory = sqlite3.Row; c.execute('PRAGMA foreign_keys=ON')
        try:
            if write: c.execute('BEGIN IMMEDIATE')
            yield c
            if write: c.commit()
        except BaseException:
            c.rollback(); raise
        finally: c.close()
    def initialize(self):
        # Explicit opt-in migration via CLI; no lazy DDL in a read endpoint.
        with self.conn() as c:
            c.executescript(SCHEMA); c.execute('INSERT OR IGNORE INTO storage_settings VALUES(1,?)', (self.ns.root,)); c.commit()
        self.validate()
    def validate(self):
        try:
            with self.conn() as c:
                row = c.execute('SELECT root FROM storage_settings WHERE id=1').fetchone()
                c.execute('SELECT sha256 FROM storage_staging_files LIMIT 0')
                c.execute('SELECT id FROM storage_producer_jobs LIMIT 0')
        except sqlite3.Error: raise StorageError('configuration_error', 'storage registry migration required') from None
        if not row or row['root'] != self.ns.root: raise StorageError('configuration_error', 'registry environment root mismatch')
    def binding(self, identity, role, version=None):
        with self.conn() as c:
            row = c.execute('SELECT * FROM storage_bindings WHERE identity=? AND role=?' + (' AND version=?' if version is not None else ' ORDER BY version DESC LIMIT 1'),
                            (identity,role,version) if version is not None else (identity,role)).fetchone()
        if not row: raise StorageError('not_found', 'registered asset unavailable')
        return dict(row)
    def path_registered(self, path):
        with self.conn() as c: return bool(c.execute('SELECT 1 FROM storage_paths WHERE path=?', (str(path),)).fetchone())
