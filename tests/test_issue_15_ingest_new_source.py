"""Regression tests for issue #15 (2026-10-23 batch).

已有 Work 摄入同一文献另一版本 PDF（不同 SHA）时，计划内新 Source 在插入前
被用途归属校验误拒（upload/execute 返回 400 "source_file_id does not belong
to this work"）。修复：前置检查区分"计划新 Work"与"计划向已有 Work 精确配对
插入的新 Source (work_id, source_file_id)"；后者延后到 write_notes 在同一事
务内插入后复验。跨 Work 引用已有 Source、隔离 Work 仍被拒绝。

All stores are synthetic, isolated SQLite files; no production data.
"""
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from api.routes import ingest as route
from scripts import literature_ingest as core


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    with sqlite3.connect(tmp_path / 'literature.sqlite') as conn:
        core.ensure_core_schema(conn)
    monkeypatch.setattr(route, 'LIBRARY_ROOT', tmp_path)
    app = FastAPI()
    app.include_router(route.router, prefix='/api')
    return tmp_path, TestClient(app)


def upload(client, *, filename='arxiv-2401.00001 paper.pdf', data=b'%PDF first version',
           purpose='review', rid='upload-1'):
    return client.post('/api/ingest/upload',
                       data={'purpose': purpose, 'request_id': rid},
                       files={'files': (filename, data)})


def _db(root):
    conn = sqlite3.connect(root / 'literature.sqlite')
    conn.row_factory = sqlite3.Row
    return conn


def _first_source(root):
    with _db(root) as conn:
        return conn.execute('SELECT id, work_id FROM source_files').fetchone()


def test_issue15_upload_existing_work_new_source_succeeds(isolated):
    root, client = isolated
    first = upload(client, rid='req-1')
    assert first.status_code == 200, first.text
    source = _first_source(root)
    wid = source['work_id']

    # 同一文献另一版本（同 arXiv 身份、不同 SHA）：此前在只读前置检查被
    # "source_file_id does not belong to this work" 误拒（issue #15）。
    second = upload(client, filename='arxiv-2401.00001 v2.pdf',
                    data=b'%PDF second version with different bytes',
                    purpose='second version of the same paper', rid='req-2')
    assert second.status_code == 200, second.text
    body = second.json()
    assert body['ingested'] == 1

    with _db(root) as conn:
        assert conn.execute('SELECT COUNT(*) FROM works').fetchone()[0] == 1
        sources = conn.execute(
            'SELECT id FROM source_files WHERE work_id=? ORDER BY import_time',
            (wid,)).fetchall()
        assert len(sources) == 2
        # 旧 Source 保留（v1 未被替换），新 Source 是另一 SHA 的 v2。
        assert sources[0]['id'] == source['id']
        assert sources[1]['id'] != source['id']
        assert conn.execute('SELECT COUNT(*) FROM literature_parse_runs').fetchone()[0] == 2
        notes = conn.execute(
            'SELECT request_id FROM ingest_notes WHERE work_id=? ORDER BY created_at',
            (wid,)).fetchall()
        assert [n['request_id'] for n in notes] == ['req-1', 'req-2']


def test_issue15_execute_entry_same_chain_succeeds(isolated):
    root, client = isolated
    assert upload(client, rid='req-1').status_code == 200
    wid = _first_source(root)['work_id']

    inbox = root / '_inbox'
    (inbox / 'arxiv-2401.00001 v2.pdf').write_bytes(b'%PDF v2 bytes differ')
    plan = client.get('/api/ingest/plan').json()
    assert plan['ingests'], plan
    response = client.post('/api/ingest/execute', json={
        'purpose': 'v2 of the same paper', 'request_id': 'exec-2',
        'file_ids': [plan['ingests'][0]['content_sha256']],
    })
    assert response.status_code == 200, response.text
    with _db(root) as conn:
        assert conn.execute('SELECT COUNT(*) FROM source_files WHERE work_id=?',
                            (wid,)).fetchone()[0] == 2


def test_issue15_quarantined_work_still_rejected(isolated):
    root, client = isolated
    assert upload(client, rid='req-1').status_code == 200
    wid = _first_source(root)['work_id']
    with _db(root) as conn:
        conn.execute("UPDATE works SET read_status='quarantined' WHERE id=?", (wid,))
        conn.commit()

    second = upload(client, filename='arxiv-2401.00001 v2.pdf',
                    data=b'%PDF different bytes', purpose='v2', rid='req-2')
    assert second.status_code == 400
    assert 'quarantined' in second.text
    # 生命周期检查未被 pending 豁免跳过：没有插入任何新 Source。
    with _db(root) as conn:
        assert conn.execute('SELECT COUNT(*) FROM source_files').fetchone()[0] == 1


def test_issue15_cross_work_source_reference_still_rejected(isolated):
    from api.ingest_notes import validate_targets

    root, client = isolated
    assert upload(client, rid='req-1').status_code == 200
    source = _first_source(root)
    with _db(root) as conn:
        conn.execute(
            "INSERT INTO works(id,title,read_status) VALUES ('W-other','Other','unread')")
        conn.commit()
        # 其他 Work 直接引用既有 Source：仍拒绝。
        try:
            validate_targets(conn, {'W-other': source['id']})
            raise AssertionError('cross-work reference must be rejected')
        except ValueError as error:
            assert 'does not belong' in str(error)
        # pending 豁免只覆盖精确 (work_id, source_file_id) 配对：把别人的
        # Source id 申报为待插入对仍拒绝，不能借道挪用。
        try:
            validate_targets(conn, {'W-other': source['id']},
                             pending_sources={('W-other', source['id'])})
            raise AssertionError('pending pair must not reuse a foreign source id')
        except ValueError as error:
            assert 'another work' in str(error)
        # 合法精确配对（本计划将插入的新 id）：只延后归属核验，work 存在性
        # 与隔离检查照常执行。
        validate_targets(conn, {source['work_id']: 'SF-brand-new'},
                         pending_sources={(source['work_id'], 'SF-brand-new')})


def test_issue15_purpose_write_revalidates_after_insert(isolated):
    """write_notes 在同一事务内插入后复验归属：伪造 pending 混入他人 Source
    时，插入路径自身仍会拒绝（不因预检豁免放松）。"""
    from api.ingest_notes import write_notes

    root, client = isolated
    assert upload(client, rid='req-1').status_code == 200
    source = _first_source(root)
    with _db(root) as conn:
        conn.execute(
            "INSERT INTO works(id,title,read_status) VALUES ('W-other','Other','unread')")
        conn.commit()
        try:
            write_notes(conn, {'W-other': source['id']}, 'p', 'rid-x')
            raise AssertionError('write_notes must revalidate ownership')
        except ValueError as error:
            assert 'does not belong' in str(error)
