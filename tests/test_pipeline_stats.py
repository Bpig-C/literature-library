"""阶段二：/api/pipeline/stats 扩展指标测试。

复用 conftest.py 的 sample_db：
- W-sample-001：parse succeeded + metadata pending + classification pending
  → 计入 backlog.metadata_unapproved 与 backlog.classification_unapproved
- W-sample-002：metadata approved 但无 parse run → 不计入 backlog
- W-sample-003：无 parse run → 不计入 backlog
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(sample_db, monkeypatch):
    import api.db as db
    import api.routes.ingest as ingest_route

    monkeypatch.setattr(db, "DB_PATH", sample_db)

    def _get_conn():
        conn = sqlite3.connect(str(sample_db))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    monkeypatch.setattr(ingest_route, "get_conn", _get_conn)

    from api.main import app
    return TestClient(app)


def test_backlog_metrics_baseline(client):
    stats = client.get("/api/pipeline/stats").json()
    assert stats["backlog"]["metadata_unapproved"] == 1       # 仅 W-sample-001
    assert stats["backlog"]["classification_unapproved"] == 1  # 仅 W-sample-001
    assert stats["intake"]["pending"] == 0


def test_existing_fields_not_regressed(client):
    stats = client.get("/api/pipeline/stats").json()
    # 既有字段语义不变（依据 sample_db 种子）
    assert stats["metadata"]["pending_review"] == 1   # ME-sample-pending (W-sample-001)
    assert stats["metadata"]["pending_extract"] == 0  # 无"已解析但无 metadata 记录"的 work
    assert stats["parse"]["pending"] == 0  # sample_db 无 pending parse run


@pytest.fixture
def intake_candidate(sample_db):
    """插入一条 pending intake 候选（yield fixture，断言失败也能清理）。"""
    uid = uuid.uuid4().hex[:6]
    cid = f"IC-stats-{uid}"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = sqlite3.connect(str(sample_db))
    try:
        conn.execute(
            "INSERT INTO intake_candidates (id, source_type, title, review_status, status, collected_at) "
            "VALUES (?, 'manual', 'Stats Test', 'pending', 'pending', ?)",
            (cid, now),
        )
        conn.commit()
    finally:
        conn.close()
    yield cid
    conn = sqlite3.connect(str(sample_db))
    try:
        conn.execute("DELETE FROM intake_candidates WHERE id = ?", (cid,))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def quarantined_parsed_work(sample_db):
    """插入一篇已隔离且有 succeeded parse run 的 work（yield fixture，保证清理）。"""
    uid = uuid.uuid4().hex[:6]
    wid = f"W-qback-{uid}"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = sqlite3.connect(str(sample_db))
    try:
        conn.execute(
            "INSERT INTO works (id, title, authors, year, doc_type, language, metadata_status, parse_status, "
            "read_status, created_at, updated_at) VALUES (?, 'Quar Backlog', '[]', 2024, 'paper', 'en', 'done', 'parsed', 'quarantined', ?, ?)",
            (wid, now, now),
        )
        conn.execute(
            "INSERT INTO literature_parse_runs (id, work_id, source_file_id, status, content_md_path, started_at, finished_at) "
            "VALUES (?, ?, 'SF-x', 'succeeded', 'x.md', ?, ?)",
            (f"PR-qback-{uid}", wid, now, now),
        )
        conn.commit()
    finally:
        conn.close()
    yield wid
    conn = sqlite3.connect(str(sample_db))
    try:
        conn.execute("DELETE FROM literature_parse_runs WHERE work_id = ?", (wid,))
        conn.execute("DELETE FROM works WHERE id = ?", (wid,))
        conn.commit()
    finally:
        conn.close()


def test_intake_pending_counts_and_cleans_up(client, intake_candidate):
    stats = client.get("/api/pipeline/stats").json()
    assert stats["intake"]["pending"] == 1


def test_quarantined_work_not_in_backlog(client, quarantined_parsed_work):
    stats = client.get("/api/pipeline/stats").json()
    assert stats["backlog"]["metadata_unapproved"] == 1  # 仍是 1，隔离 work 不计入
    assert stats["backlog"]["classification_unapproved"] == 1
