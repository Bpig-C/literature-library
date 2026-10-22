"""Pure duplicate lookup (#3) and source provenance (#5) tests."""
import hashlib
import json
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
    ensure_core_schema(conn)
    conn.execute(
        "INSERT INTO works (id, title, arxiv_id, doi, parse_status, read_status, created_at, updated_at) "
        "VALUES ('W-1', 'Risk Assessment Paper', '2609.17226', '10.1000/test', "
        "'succeeded', 'active', '2026-01-01', '2026-01-01')")
    conn.execute(
        "INSERT INTO works (id, title, arxiv_id, parse_status, read_status, created_at, updated_at) "
        "VALUES ('W-2', 'Another Paper', '2501.99999', 'pending', 'unread', '2026-01-01', '2026-01-01')")
    test_sha = hashlib.sha256(b"test-pdf-bytes").hexdigest()
    conn.execute(
        "INSERT INTO source_files (id, work_id, content_sha256, original_name, source_path, "
        "relative_source_path, file_size, file_ext, import_time) "
        "VALUES ('SF-1', 'W-1', ?, 'paper.pdf', '/tmp/paper.pdf', 'paper.pdf', 100, '.pdf', '2026-01-01')",
        (test_sha,))
    conn.commit()
    conn.close()

    import api.routes.duplicates as dr
    import api.routes.provenance as pr
    def _connect():
        c = sqlite3.connect(tmp_path / "literature.sqlite", check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr(dr, 'get_conn', _connect)
    monkeypatch.setattr(dr, 'get_read_conn', _connect)
    monkeypatch.setattr(pr, 'get_conn', _connect)
    monkeypatch.setattr(pr, 'get_read_conn', _connect)

    app = FastAPI()
    app.include_router(dr.router, prefix='/api')
    app.include_router(pr.router, prefix='/api')
    return tmp_path, TestClient(app), test_sha


# === #3: pure duplicate lookup ===

def test_exact_sha_match(db):
    _, client, sha = db
    r = client.post('/api/duplicates/lookup', json={'content_sha256': sha})
    assert r.status_code == 200
    d = r.json()
    assert d['status'] == 'exact_match'
    assert len(d['exact_sha']) == 1
    assert d['exact_sha'][0]['work_id'] == 'W-1'
    assert d['exact_sha'][0]['source_file_id'] == 'SF-1'


def test_doi_match(db):
    _, client, _ = db
    r = client.post('/api/duplicates/lookup', json={'doi': '10.1000/test'})
    assert r.status_code == 200
    d = r.json()
    assert d['status'] == 'same_work_different_version'
    assert len(d['same_work']) == 1
    assert d['same_work'][0]['work_id'] == 'W-1'


def test_arxiv_match(db):
    _, client, _ = db
    r = client.post('/api/duplicates/lookup', json={'arxiv_id': '2501.99999'})
    assert r.status_code == 200
    d = r.json()
    assert d['status'] == 'same_work_different_version'
    assert d['same_work'][0]['work_id'] == 'W-2'


def test_title_fuzzy(db):
    _, client, _ = db
    r = client.post('/api/duplicates/lookup', json={'title': 'Risk Assessment'})
    assert r.status_code == 200
    d = r.json()
    assert d['status'] == 'title_candidates_only'
    assert any(c['work_id'] == 'W-1' for c in d['title_candidates'])


def test_not_found(db):
    _, client, _ = db
    new_sha = hashlib.sha256(b"different-bytes").hexdigest()
    r = client.post('/api/duplicates/lookup', json={'content_sha256': new_sha})
    assert r.status_code == 200
    assert r.json()['status'] == 'not_found'


def test_empty_body_rejected(db):
    _, client, _ = db
    r = client.post('/api/duplicates/lookup', json={})
    assert r.status_code == 400


def test_invalid_sha_rejected(db):
    _, client, _ = db
    r = client.post('/api/duplicates/lookup', json={'content_sha256': 'not-hex'})
    assert r.status_code == 400


def test_no_side_effects(db):
    """Verify lookup doesn't create any rows."""
    tmp, client, sha = db
    before = sqlite3.connect(tmp / "literature.sqlite")
    works_before = before.execute("SELECT COUNT(*) FROM works").fetchone()[0]
    sf_before = before.execute("SELECT COUNT(*) FROM source_files").fetchone()[0]
    before.close()

    client.post('/api/duplicates/lookup', json={'content_sha256': sha, 'doi': '10.1000/x'})

    after = sqlite3.connect(tmp / "literature.sqlite")
    assert after.execute("SELECT COUNT(*) FROM works").fetchone()[0] == works_before
    assert after.execute("SELECT COUNT(*) FROM source_files").fetchone()[0] == sf_before
    after.close()


def test_quarantined_visible(db):
    """Quarantined works should appear but be marked unavailable."""
    tmp, client, sha = db
    conn = sqlite3.connect(tmp / "literature.sqlite")
    conn.execute("UPDATE works SET read_status='quarantined' WHERE id='W-1'")
    conn.commit()
    conn.close()
    r = client.post('/api/duplicates/lookup', json={'content_sha256': sha})
    d = r.json()
    assert d['status'] == 'exact_match'
    assert d.get('work_statuses', {}).get('W-1', {}).get('available') is False


# === #5: source provenance ===

def test_provenance_record_and_query(db):
    tmp, client, _ = db
    r = client.post('/api/provenance', json={
        'work_id': 'W-1', 'landing_url': 'https://arxiv.org/abs/2609.17226',
        'doi': '10.1000/test', 'source_type': 'arxiv',
        'known_sha256': hashlib.sha256(b"test").hexdigest(), 'known_bytes': 100,
    })
    assert r.status_code == 200
    assert r.json()['ok'] is True

    r2 = client.get('/api/provenance/W-1')
    assert r2.status_code == 200
    records = r2.json()['records']
    assert len(records) >= 1
    assert records[0]['landing_url'] == 'https://arxiv.org/abs/2609.17226'
    assert records[0]['source_type'] == 'arxiv'


def test_provenance_nonexistent_work(db):
    _, client, _ = db
    r = client.post('/api/provenance', json={'work_id': 'W-nothere'})
    assert r.status_code == 404


def test_provenance_update_merges(db):
    tmp, client, _ = db
    client.post('/api/provenance', json={
        'work_id': 'W-1', 'landing_url': 'https://example.com', 'source_type': 'publisher'})
    client.post('/api/provenance', json={
        'work_id': 'W-1', 'backup_url': 'https://backup.com'})
    r = client.get('/api/provenance/W-1')
    records = r.json()['records']
    assert len(records) == 1  # single record, merged
    assert records[0]['landing_url'] == 'https://example.com'
    assert records[0]['backup_url'] == 'https://backup.com'


def test_provenance_export(db):
    _, client, _ = db
    client.post('/api/provenance', json={
        'work_id': 'W-1', 'landing_url': 'https://example.com', 'source_type': 'test'})
    r = client.get('/api/provenance-export')
    assert r.status_code == 200
    catalog = r.json()
    assert catalog['format'] == 'litlib-source-provenance-v2'
    assert catalog['entry_count'] == 1
    assert len(catalog['integrity_sha256']) == 64


def test_provenance_query_empty(db):
    _, client, _ = db
    r = client.get('/api/provenance/W-2')
    assert r.status_code == 200
    assert r.json()['records'] == []
