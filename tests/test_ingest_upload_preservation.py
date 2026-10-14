"""Upload preservation regressions. Synthetic bytes and isolated catalogs only."""
import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.datastructures import UploadFile
from fastapi.testclient import TestClient
from io import BytesIO

import api.routes.ingest as route
from scripts.literature_ingest import ensure_core_schema


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    conn = sqlite3.connect(tmp_path / 'literature.sqlite')
    ensure_core_schema(conn)
    conn.commit()
    conn.close()
    (tmp_path / '_inbox').mkdir()
    monkeypatch.setattr(route, 'LIBRARY_ROOT', tmp_path)
    app = FastAPI()
    app.include_router(route.router, prefix='/api')
    return tmp_path, TestClient(app)


def contents(root):
    return {p.read_bytes() for p in root.rglob('*.pdf')}


def test_preexisting_same_name_preserved(isolated):
    root, client = isolated
    old, new = b'%PDF old synthetic', b'%PDF new synthetic'
    (root / '_inbox/same.pdf').write_bytes(old)
    response = client.post('/api/ingest/upload', files={'files': ('same.pdf', new)})
    assert response.status_code == 200, response.text
    assert {old, new} <= contents(root)
    assert response.json()['ingested'] == 1
    assert (root / '_inbox/same.pdf').read_bytes() == old


def test_same_request_same_name_preserved(isolated):
    root, client = isolated
    first, second = b'%PDF first synthetic', b'%PDF second synthetic'
    response = client.post('/api/ingest/upload', files=[('files', ('same.pdf', first)), ('files', ('same.pdf', second))])
    assert response.status_code == 200, response.text
    assert {first, second} <= contents(root)
    assert response.json()['uploaded'] == response.json()['ingested'] == 2


def test_exact_repeat_still_deduplicated(isolated):
    root, client = isolated
    data = b'%PDF repeat synthetic'
    for expected in (1, 0):
        response = client.post('/api/ingest/upload', files={'files': ('same.pdf', data)})
        assert response.status_code == 200, response.text
        assert response.json()['ingested'] == expected
    conn = sqlite3.connect(root / 'literature.sqlite')
    assert conn.execute('select count(*) from source_files').fetchone()[0] == 1
    conn.close()


def test_read_failure_preserves_existing_and_other_upload(isolated, monkeypatch):
    root, client = isolated
    old, good = b'%PDF old synthetic', b'%PDF good synthetic'
    (root / '_inbox/same.pdf').write_bytes(old)
    original = UploadFile.read
    async def fail_read(self, size=-1):
        if self.filename == 'same.pdf':
            raise OSError('synthetic read failure')
        return await original(self, size)
    monkeypatch.setattr(UploadFile, 'read', fail_read)
    response = client.post('/api/ingest/upload', files=[('files', ('same.pdf', b'bad')), ('files', ('good.pdf', good))])
    assert response.status_code == 200, response.text
    assert {old, good} <= contents(root)
    assert len(response.json()['skipped']) == 1
    assert response.json()['ingested'] == 1
    assert (root / '_inbox/same.pdf').read_bytes() == old
    assert not list((root / '_inbox').glob('*.part'))


def test_unselected_inbox_is_untouched_and_explicit_execute_still_scans_all(isolated):
    root, client = isolated
    old = b'%PDF unselected synthetic'
    (root / '_inbox/unselected.pdf').write_bytes(old)
    response = client.post('/api/ingest/upload', files={'files': ('selected.pdf', b'%PDF selected synthetic')})
    assert response.status_code == 200
    assert response.json()['ingested'] == 1
    assert (root / '_inbox/unselected.pdf').read_bytes() == old
    preview = client.get('/api/ingest/plan').json()
    assert preview['summary']['ingests'] == 1
    response = client.post('/api/ingest/execute', json={})
    assert response.status_code == 200
    assert response.json()['summary']['ingests'] == 1
    assert old in contents(root)


def test_publication_failure_never_removes_original(isolated, monkeypatch):
    root, client = isolated
    old = b'%PDF old synthetic'
    (root / '_inbox/same.pdf').write_bytes(old)
    def fail_link(*args):
        raise OSError('synthetic publication failure')
    monkeypatch.setattr(route.os, 'link', fail_link)
    response = client.post('/api/ingest/upload', files={'files': ('same.pdf', b'new')})
    assert response.status_code == 400
    assert (root / '_inbox/same.pdf').read_bytes() == old
    assert not list((root / '_inbox').glob('*.part'))


def test_concurrent_publication_preserves_every_content(isolated):
    root, _ = isolated
    payloads = [f'%PDF synthetic {i}'.encode() for i in range(12)]
    def publish(data):
        return asyncio.run(route._save_upload(UploadFile(BytesIO(data), filename='same.pdf'), str(root / '_inbox')))
    with ThreadPoolExecutor(max_workers=6) as pool:
        paths = list(pool.map(publish, payloads))
    assert len(set(paths)) == len(payloads)
    assert contents(root) == set(payloads)
    assert not list((root / '_inbox').glob('*.part'))


def test_partial_staging_is_not_scanned(isolated):
    root, _ = isolated
    class PartialUpload:
        filename = 'same.pdf'
        calls = 0
        async def read(self, size):
            self.calls += 1
            if self.calls == 1:
                return b'%PDF partial'
            assert list((root / '_inbox').glob('*.part'))
            assert route.build_ingest_plan(root, dry_run=True).summary()['ingests'] == 0
            raise OSError('synthetic interrupted read')
    with pytest.raises(OSError):
        asyncio.run(route._save_upload(PartialUpload(), str(root / '_inbox')))
    assert not list((root / '_inbox').iterdir())


def test_upload_filename_cannot_escape_inbox(isolated):
    root, client = isolated
    data = b'%PDF synthetic boundary'
    response = client.post('/api/ingest/upload', files={'files': ('../../escape.pdf', data)})
    assert response.status_code == 200, response.text
    assert data in contents(root)
    assert not (root.parent / 'escape.pdf').exists()
    conn = sqlite3.connect(root / 'literature.sqlite')
    for path, in conn.execute('select source_path from source_files'):
        assert Path(path).resolve().is_relative_to(root)
    conn.close()


def test_selected_plan_rejects_paths_outside_inbox(isolated):
    root, _ = isolated
    outside = root / 'outside.pdf'
    outside.write_bytes(b'%PDF synthetic')
    with pytest.raises(ValueError):
        route.build_ingest_plan(root, selected_paths=[outside])
