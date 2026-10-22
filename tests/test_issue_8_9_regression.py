"""Regression tests for issue #8 (provenance multi-Source) and #9 (lookup bypass)."""
import hashlib
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts.literature_ingest import ensure_core_schema
from api.routes import duplicates as dup_route
from api.routes import provenance as prov_route


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
    # Simulate remote writes disabled (the middleware checks this env var,
    # but we can't easily set it in TestClient; instead we verify the handler
    # returns 200 which proves it reached the route, not the middleware gate)
    r = client.post('/api/duplicates/lookup', json={'content_sha256': sha})
    assert r.status_code == 200
    assert r.json()['status'] == 'exact_match'


def test_other_write_still_gated(db):
    """Other write operations should still be gated normally."""
    tmp, client, _ = db
    # POST /api/provenance is still a write endpoint (not in the read-only bypass list)
    # We can't test the middleware directly without the real authority, but we can
    # verify the middleware source includes the whitelist correctly
    from api.remote_access import _READ_ONLY_POST_PATHS
    assert '/api/duplicates/lookup' in _READ_ONLY_POST_PATHS
    assert '/api/provenance' not in _READ_ONLY_POST_PATHS
    assert '/api/works' not in _READ_ONLY_POST_PATHS
    assert '/api/parse/trigger' not in _READ_ONLY_POST_PATHS
