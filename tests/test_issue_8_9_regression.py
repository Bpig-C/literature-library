"""Regression tests for issue #8 (provenance multi-Source) and #9 (lookup bypass)."""
import hashlib
import sqlite3
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts.literature_ingest import ensure_core_schema
from api.routes import duplicates as dup_route
from api.routes import provenance as prov_route
from api import db as catalog_db
from api.remote_access import RemoteAuthentication


@pytest.fixture()
def db(tmp_path, monkeypatch):
    conn = sqlite3.connect(tmp_path / "literature.sqlite")
    conn.row_factory = sqlite3.Row
    ensure_core_schema(conn)
    conn.execute(
        "INSERT INTO works (id, title, arxiv_id, parse_status, read_status, created_at, updated_at) "
        "VALUES ('W-1', 'Paper', '2609.17226', 'succeeded', 'active', '2026-01-01', '2026-01-01')")
    test_sha = hashlib.sha256(b"pdf").hexdigest()
    conn.execute(
        "INSERT INTO source_files (id, work_id, content_sha256, original_name, source_path, "
        "relative_source_path, file_size, file_ext, import_time) "
        "VALUES ('SF-a', 'W-1', ?, 'a.pdf', '/tmp/a.pdf', 'a.pdf', 100, '.pdf', '2026-01-01')",
        (test_sha,))
    conn.execute(
        "INSERT INTO source_files (id, work_id, content_sha256, original_name, source_path, "
        "relative_source_path, file_size, file_ext, import_time) "
        "VALUES ('SF-b', 'W-1', ?, 'b.pdf', '/tmp/b.pdf', 'b.pdf', 200, '.pdf', '2026-01-01')",
        (hashlib.sha256(b"pdf2").hexdigest(),))
    conn.commit()
    conn.close()

    def _connect():
        c = sqlite3.connect(tmp_path / "literature.sqlite", check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(dup_route, 'get_conn', _connect)
    monkeypatch.setattr(prov_route, 'get_conn', _connect)
    monkeypatch.setattr(catalog_db, 'DB_PATH', tmp_path / 'literature.sqlite')
    monkeypatch.delenv('LITLIB_STORAGE_MODE', raising=False)

    app = FastAPI()
    app.include_router(dup_route.router, prefix='/api')
    app.include_router(prov_route.router, prefix='/api')
    return tmp_path, TestClient(app), test_sha


# === Issue #8: multi-Source provenance must not overwrite ===

def test_multi_source_provenance_preserved(db):
    """Different Sources of the same Work get separate provenance records."""
    tmp, client, _ = db
    client.post('/api/provenance', json={
        'work_id': 'W-1', 'source_file_id': 'SF-a',
        'landing_url': 'https://arxiv.org/abs/v1', 'source_type': 'arxiv'})
    client.post('/api/provenance', json={
        'work_id': 'W-1', 'source_file_id': 'SF-b',
        'landing_url': 'https://doi.org/10.1000/final', 'source_type': 'publisher'})
    r = client.get('/api/provenance/W-1')
    records = r.json()['records']
    assert len(records) == 2
    by_sf = {r['source_file_id']: r for r in records}
    assert by_sf['SF-a']['landing_url'] == 'https://arxiv.org/abs/v1'
    assert by_sf['SF-b']['landing_url'] == 'https://doi.org/10.1000/final'


def test_provenance_same_source_merges(db):
    """Same Work + same Source_file_id merges (not duplicates)."""
    tmp, client, _ = db
    client.post('/api/provenance', json={
        'work_id': 'W-1', 'source_file_id': 'SF-a', 'landing_url': 'https://first.com'})
    client.post('/api/provenance', json={
        'work_id': 'W-1', 'source_file_id': 'SF-a', 'backup_url': 'https://backup.com'})
    r = client.get('/api/provenance/W-1')
    records = r.json()['records']
    assert len(records) == 1
    assert records[0]['landing_url'] == 'https://first.com'
    assert records[0]['backup_url'] == 'https://backup.com'


def test_provenance_export_integrity_covers_all_fields(db):
    """Export integrity_sha256 must change when ANY field changes."""
    tmp, client, _ = db
    client.post('/api/provenance', json={
        'work_id': 'W-1', 'source_file_id': 'SF-a', 'landing_url': 'https://a.com',
        'direct_url': 'https://direct.com', 'known_bytes': 100})
    export1 = client.get('/api/provenance-export').json()
    sha1 = export1['integrity_sha256']

    # change a field that was previously NOT covered by the old digest
    client.post('/api/provenance', json={
        'work_id': 'W-1', 'source_file_id': 'SF-a', 'direct_url': 'https://CHANGED.com'})
    export2 = client.get('/api/provenance-export').json()
    sha2 = export2['integrity_sha256']

    assert sha1 != sha2, "digest must detect changes to direct_url"


# === Issue #9: lookup POST bypasses write gate ===

def test_lookup_bypasses_write_gate(db):
    """POST /api/duplicates/lookup must work even when remote writes are disabled."""
    tmp, client, sha = db
    r = client.post('/api/duplicates/lookup', json={'content_sha256': sha})
    assert r.status_code == 200
    assert r.json()['status'] == 'exact_match'


@pytest.fixture()
def gated(db, monkeypatch):
    from types import SimpleNamespace
    from api.storage import authority, runtime
    from api.storage.core import StorageError
    tmp, _, sha = db
    monkeypatch.setenv('LITLIB_REMOTE_ENABLED', '1')
    monkeypatch.setenv('LITLIB_REMOTE_TOKEN', 't' * 32)
    monkeypatch.setenv('LITLIB_REMOTE_WRITE_ENABLED', '0')
    monkeypatch.setenv('LITLIB_STORAGE_MODE', 'immutable')
    monkeypatch.setattr(runtime, 'configured_registry', lambda: SimpleNamespace(validate=lambda **kw: None))
    calls = []
    @contextmanager
    def guard():
        calls.append('guard')
        raise StorageError('revision_conflict', 'synthetic old epoch')
        yield
    monkeypatch.setattr(authority, 'configured_authority', lambda: SimpleNamespace(write_guard=guard))
    app = FastAPI()
    app.add_middleware(RemoteAuthentication)
    app.include_router(dup_route.router, prefix='/api')
    app.include_router(prov_route.router, prefix='/api')
    # Deliberately install a future mutating method on the lookup path.
    @app.put('/api/duplicates/lookup')
    def mutation():
        pytest.fail('non-POST route bypassed gate')
    with TestClient(app) as client:
        yield tmp, client, sha, calls, {'Authorization': 'Bearer ' + 't' * 32}


def test_lookup_real_middleware_auth_and_guard(gated):
    tmp, client, sha, calls, headers = gated
    before = (tmp / 'literature.sqlite').read_bytes()
    for path in ['/api/duplicates/lookup', '/api/duplicates/lookup/', '/api/duplicates/lookup?x=1']:
        response = client.post(path, headers=headers, json={'content_sha256': sha})
        assert response.status_code == 200
        assert response.json()['status'] == 'exact_match'
    assert calls == []
    assert (tmp / 'literature.sqlite').read_bytes() == before
    assert client.post('/api/duplicates/lookup', json={'doi': 'x'}).status_code == 401
    assert client.post('/api/duplicates/lookup', headers={'Authorization': 'Bearer wrong'}, json={'doi': 'x'}).status_code == 401


def test_other_write_still_gated(gated, monkeypatch):
    _, client, _, calls, headers = gated
    assert client.post('/api/provenance', headers=headers, json={'work_id': 'W-1'}).status_code == 403
    assert client.put('/api/duplicates/lookup', headers=headers).status_code == 403
    assert client.post('/api/duplicates/lookup-extra', headers=headers).status_code == 403
    assert calls == []
    monkeypatch.setenv('LITLIB_REMOTE_WRITE_ENABLED', '1')
    response = client.post('/api/provenance', headers=headers, json={'work_id': 'W-1'})
    assert response.status_code == 409
    assert response.json()['code'] == 'revision_conflict'
    assert calls == ['guard']
    calls.clear()
    assert client.post('/api/duplicates/lookup', headers=headers, json={'doi': 'x'}).status_code == 200
    assert calls == []
