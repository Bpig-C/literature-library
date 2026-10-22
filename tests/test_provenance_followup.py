"""Recovery metadata history, export compatibility and read-only transport."""
import copy
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from api import db as catalog_db
from api import source_provenance as p
from test_issue_8_9_regression import db, gated  # shared synthetic HTTP fixtures


def test_history_patch_clear_zero_and_replay():
    with sqlite3.connect(':memory:') as conn:
        p.record(conn, 'W', source_file_id='A', direct_url='https://example.invalid/old', known_bytes=100)
        p.record(conn, 'W', source_file_id='A', direct_url='', known_bytes=0)
        p.record(conn, 'W', source_file_id='A', direct_url='', known_bytes=0)
        entry = p.query(conn, 'W')[0]
        assert entry['direct_url'] == '' and entry['known_bytes'] == 0
        assert len(entry['history']) == 2
        assert entry['history'][0]['record']['direct_url'] == 'https://example.invalid/old'
        assert not entry['legacy_review_required']
        assert entry['last_verified_at'] == ''  # editing metadata does not verify a URL


@pytest.mark.parametrize('payload', [{'known_sha256': 'z' * 64}, {'known_bytes': -1}, {'known_bytes': True}])
def test_invalid_values_leave_no_schema(payload):
    with sqlite3.connect(':memory:') as conn:
        with pytest.raises(ValueError):
            p.record(conn, 'W', **payload)
        assert conn.execute('SELECT COUNT(*) FROM sqlite_master').fetchone()[0] == 0


def test_export_stability_scope_and_truncation(monkeypatch):
    monkeypatch.setattr(p, '_now', lambda: '2026-10-22T00:00:00Z')
    digests = []
    for order in [('A', 'B'), ('B', 'A')]:
        with sqlite3.connect(':memory:') as conn:
            for source in order:
                p.record(conn, 'W', source_file_id=source, direct_url='https://example.invalid/' + source)
            catalog = p.export_catalog(conn)
            assert p.verify_catalog(catalog)
            digests.append(catalog['integrity_sha256'])
            catalog['generated_at'] = 'different time'
            assert p.verify_catalog(catalog)
            for field, value in [('direct_url', 'changed'), ('backup_url', 'changed'), ('known_bytes', 999)]:
                tampered = copy.deepcopy(catalog)
                tampered['entries'][0][field] = value
                assert not p.verify_catalog(tampered)
            partial = p.export_catalog(conn, limit=1)
            assert partial['truncated'] and partial['entry_count'] == 1 and partial['total_count'] == 2
            assert p.verify_catalog(partial)
            partial['truncated'] = False
            assert not p.verify_catalog(partial)
            catalog['format'] = 'litlib-source-provenance-v1'
            assert not p.verify_catalog(catalog)
    assert digests[0] == digests[1]


def test_legacy_preservation_idempotence_and_rollback():
    with sqlite3.connect(':memory:') as conn:
        p.record(conn, 'W', source_file_id='A', direct_url='https://example.invalid/legacy')
        conn.execute('DROP TABLE source_provenance_revisions')
        conn.commit()
        original = dict(conn.execute('SELECT * FROM source_provenance').fetchone())
        assert p.query(conn, 'W')[0]['legacy_review_required']
        assert p.preserve_legacy(conn) == 1
        assert p.preserve_legacy(conn) == 0
        conn.rollback()
        assert not p._exists(conn, 'source_provenance_revisions')
        assert dict(conn.execute('SELECT * FROM source_provenance').fetchone()) == original
        assert p.preserve_legacy(conn) == 1
        conn.commit()
        p.record(conn, 'W', source_file_id='A', direct_url='https://example.invalid/new')
        entry = p.query(conn, 'W')[0]
        assert entry['id'] == original['id']
        assert entry['history'][0]['record'] == original
        assert entry['history'][0]['origin'] == 'legacy_unverified'
        assert entry['legacy_review_required']


def test_parallel_same_source_serialized(tmp_path):
    database = tmp_path / 'history.sqlite'
    barrier = Barrier(2)
    def write(url):
        with sqlite3.connect(database, timeout=10) as conn:
            barrier.wait(timeout=5)
            p.record(conn, 'W', source_file_id='A', direct_url=url)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(write, 'https://example.invalid/' + n) for n in ['a', 'b']]
        for result in results:
            result.result(timeout=15)
    with sqlite3.connect(database) as conn:
        entries = p.query(conn, 'W')
        assert len(entries) == 1 and len(entries[0]['history']) == 2
        assert {r['record']['direct_url'] for r in entries[0]['history']} == {'https://example.invalid/a', 'https://example.invalid/b'}


def test_http_source_validation_no_writes(db):
    tmp, client, _ = db
    # W-2 exists but SF-a belongs to W-1.
    with sqlite3.connect(tmp / 'literature.sqlite') as conn:
        conn.execute("INSERT INTO works(id,title) VALUES('W-2','Other')")
    cases = [({'work_id': 'W-2', 'source_file_id': 'SF-a'}, 400),
             ({'work_id': 'W-1', 'source_file_id': 'absent'}, 404),
             ({'work_id': 'W-1', 'source_file_id': 'SF-a', 'known_sha256': 'f' * 64}, 400),
             ({'work_id': 'W-1', 'source_file_id': 'SF-a', 'known_bytes': 999}, 400)]
    for body, status in cases:
        assert client.post('/api/provenance', json=body).status_code == status
    with sqlite3.connect(tmp / 'literature.sqlite') as conn:
        assert not p._exists(conn, 'source_provenance')


def test_read_connection_no_creation_journal_or_writes(tmp_path, monkeypatch):
    monkeypatch.delenv('LITLIB_STORAGE_MODE', raising=False)
    database = tmp_path / 'read.sqlite'
    monkeypatch.setattr(catalog_db, 'DB_PATH', database)
    with pytest.raises(sqlite3.OperationalError):
        catalog_db.get_read_conn()
    assert not database.exists()
    with sqlite3.connect(database) as conn:
        conn.execute('CREATE TABLE sentinel(id INTEGER)')
    before = database.read_bytes()
    conn = catalog_db.get_read_conn()
    try:
        assert conn.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'
        with pytest.raises(sqlite3.OperationalError):
            conn.execute('INSERT INTO sentinel VALUES(1)')
        assert p.query(conn, 'W') == []
        assert p.export_catalog(conn)['entries'] == []
    finally:
        conn.close()
    assert database.read_bytes() == before


def test_immutable_registry_validation_uses_read_only_connections(tmp_path, monkeypatch):
    from api.storage import runtime
    from api.storage.core import Namespace, Registry
    database = tmp_path / 'catalog.sqlite'
    with sqlite3.connect(database):
        pass
    registry = Registry(database, Namespace('research/agent-loss-of-control/literature/test/provenance/'))
    registry.initialize()
    monkeypatch.setattr(catalog_db, 'DB_PATH', database)
    monkeypatch.setenv('LITLIB_STORAGE_MODE', 'immutable')
    monkeypatch.setattr(runtime, 'configured_registry', lambda: registry)
    real_connect = sqlite3.connect
    connections = []
    def connect(path, *args, **kwargs):
        connections.append(path)
        return real_connect(path, *args, **kwargs)
    monkeypatch.setattr(sqlite3, 'connect', connect)
    conn = catalog_db.get_read_conn()
    conn.close()
    assert len(connections) == 2
    assert all(str(path).endswith('?mode=ro') for path in connections)


def test_lookup_database_failure_is_not_no_match(gated, monkeypatch):
    tmp, client, _, _, headers = gated
    monkeypatch.setattr(catalog_db, 'DB_PATH', tmp / 'missing.sqlite')
    response = client.post('/api/duplicates/lookup', headers=headers, json={'doi': 'x'})
    assert response.status_code == 503
    assert not (tmp / 'missing.sqlite').exists()


def test_malformed_table_is_not_empty_catalog():
    with sqlite3.connect(':memory:') as conn:
        conn.execute('CREATE TABLE source_provenance(id TEXT)')
        with pytest.raises(sqlite3.OperationalError):
            p.query(conn, 'W')
        with pytest.raises(sqlite3.OperationalError):
            p.export_catalog(conn)


def test_explicit_preservation_backup_and_replay(tmp_path):
    from scripts.preserve_source_provenance import preserve
    database, backup = tmp_path / 'catalog.sqlite', tmp_path / 'before.sqlite'
    with sqlite3.connect(database) as conn:
        p.record(conn, 'W', direct_url='https://example.invalid/original')
        conn.execute('DROP TABLE source_provenance_revisions')
    assert preserve(database, backup) == 1
    with sqlite3.connect(backup) as conn:
        assert not p._exists(conn, 'source_provenance_revisions')
        assert p.query(conn, 'W')[0]['direct_url'] == 'https://example.invalid/original'
    assert preserve(database, tmp_path / 'replay.sqlite') == 0
    with pytest.raises(FileExistsError):
        preserve(database, backup)


def test_duplicate_legacy_identities_fail_without_merging(tmp_path):
    from scripts.preserve_source_provenance import preserve
    database, backup = tmp_path / 'catalog.sqlite', tmp_path / 'before.sqlite'
    with sqlite3.connect(database) as conn:
        p.record(conn, 'W')
        conn.execute('DROP INDEX idx_provenance_identity')
        conn.execute('DROP TABLE source_provenance_revisions')
        columns = ['id', *p.FIELDS]
        row = dict(conn.execute('SELECT * FROM source_provenance').fetchone())
        row['id'] = 'legacy-duplicate'
        conn.execute('INSERT INTO source_provenance (' + ','.join(columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')', [row[k] for k in columns])
    with pytest.raises(sqlite3.IntegrityError):
        preserve(database, backup)
    for path in [database, backup]:
        with sqlite3.connect(path) as conn:
            assert conn.execute('SELECT COUNT(*) FROM source_provenance').fetchone()[0] == 2
            assert not p._exists(conn, 'source_provenance_revisions')
