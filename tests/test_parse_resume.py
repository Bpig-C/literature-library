"""HTTP regression for issue #2: resume existing output under the producer lock."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import parse as route
from api.storage import producers, runtime
from api.storage.core import StorageError
from test_remote_access import fixture


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    service = fixture(tmp_path)
    with service.registry.conn(write=True) as conn:
        conn.executescript("""
            CREATE TABLE works(id TEXT PRIMARY KEY, parse_status TEXT, updated_at TEXT);
            CREATE TABLE source_files(id TEXT PRIMARY KEY, work_id TEXT, status TEXT);
            CREATE TABLE literature_parse_runs(id TEXT PRIMARY KEY, work_id TEXT,
                source_file_id TEXT, status TEXT, content_md_path TEXT, backend TEXT,
                task_id TEXT, finished_at TEXT, error TEXT);
            INSERT INTO works VALUES('work-1','pending','');
            INSERT INTO source_files VALUES('source-1','work-1','active');
            INSERT INTO literature_parse_runs VALUES('run-1','work-1','source-1',
                'running','','','','','');
        """)
    monkeypatch.setattr(producers, 'configured_service', lambda: service)
    monkeypatch.setattr(runtime, 'enabled', lambda: True)
    monkeypatch.setattr(route, '_run_parse', lambda *a, **k: pytest.fail('resume ran parser'))
    app = FastAPI()
    app.include_router(route.router, prefix='/api')
    return service, TestClient(app)


def test_artifacts_ready_resume_is_idempotent_and_keeps_ids(isolated, tmp_path, monkeypatch):
    service, client = isolated
    output = tmp_path / 'content.md'
    output.write_text('durable parser output', encoding='utf-8')
    artifact = dict(identity='run-1', role='md', version=3, source=str(output),
                    member=None, virtual_path=str(output))
    with service.registry.conn(write=True) as conn:
        conn.execute("""INSERT INTO storage_producer_jobs
            (id,kind,source_file_id,parse_run_id,version,state,artifacts,backend,task_id)
            VALUES('job-1','parse','source-1','run-1',3,'artifacts_ready',?,'test','task-1')""",
                     (json.dumps([artifact]),))
    # Start with a durable pending operation, as after a transport interruption.
    backend = service.backend
    class Offline:
        def size(self, key):
            raise StorageError('network_unavailable', 'isolated interruption')
    service.backend = Offline()
    op = producers.job_id('asset', 'job-1\nmd')
    with pytest.raises(StorageError):
        service.publish(output, identity='run-1', role='md', version=3, operation_id=op,
                        member=None, virtual_path=str(output))
    service.backend = backend
    original_lock = producers.file_lock
    body = {'job_id': 'job-1', 'force': True}
    monkeypatch.setattr(producers, 'file_lock', lambda path: original_lock(path, timeout=0))
    with original_lock(producers._source_lock_path(service, 'source-1')):
        blocked = client.post('/api/parse/resume', json=body)
        assert blocked.status_code == 422 and 'busy' in blocked.json()['detail']
    monkeypatch.setattr(producers, 'file_lock', original_lock)
    first = client.post('/api/parse/resume', json=body)
    assert first.status_code == 200, first.text
    assert first.json() == dict(job_id='job-1', state='registered', parse_run_id='run-1',
                                version=3, backend='test')
    assert client.post('/api/parse/resume', json=body).json() == first.json()
    with service.registry.conn() as conn:
        for table in ('storage_producer_jobs', 'literature_parse_runs',
                      'storage_operations', 'storage_bindings'):
            assert conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] == 1
        assert conn.execute('SELECT operation_id,state FROM storage_operations').fetchone()[:] == (op, 'registered')
        assert conn.execute('SELECT status FROM literature_parse_runs').fetchone()[0] == 'succeeded'
    with service.read('run-1', 'md', 3) as path:
        assert path.read_text('utf-8') == 'durable parser output'


def test_resume_errors_and_intent_gates(isolated, monkeypatch):
    service, client = isolated
    with service.registry.conn(write=True) as conn:
        conn.execute("INSERT INTO storage_producer_jobs(id,kind,source_file_id,version,state) VALUES('incomplete','parse','source-1',1,'preparing')")
    def post(body):
        return client.post('/api/parse/resume', json=body)
    assert post({'job_id': 'missing'}).status_code == 400
    missing = post({'job_id': 'missing', 'force': True})
    assert missing.status_code == 422 and 'not_found' in missing.json()['detail']
    incomplete = post({'job_id': 'incomplete', 'force': True})
    assert incomplete.status_code == 409 and 'producer_incomplete' in incomplete.json()['detail']
    monkeypatch.setattr(runtime, 'enabled', lambda: False)
    assert post({'job_id': 'missing', 'force': True}).status_code == 400
