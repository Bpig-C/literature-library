"""阶段一：导出 API 端点测试（/api/export/bibtex|ris|matrix.csv）。

复用 conftest.py 的 sample_db：
- W-sample-001：metadata pending（不应被导出）
- W-sample-002：metadata approved（应被导出）
- W-sample-003：无 metadata 记录（不应被导出）
额外 fixture 行使用唯一 ID 前缀，避免跨测试污染。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(sample_db, monkeypatch):
    import api.db as db
    import api.routes.export as export_route

    monkeypatch.setattr(db, "DB_PATH", sample_db)

    def _get_conn():
        conn = sqlite3.connect(str(sample_db))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    monkeypatch.setattr(export_route, "get_conn", _get_conn)

    from api.main import app
    return TestClient(app)


def _conn(sample_db):
    conn = sqlite3.connect(str(sample_db))
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture
def rich_work(sample_db):
    """插入一篇带标签 + approved digest + approved 元数据的完整 work（测试后清理，避免污染 session 级 sample_db）。"""
    uid = uuid.uuid4().hex[:6]
    wid = f"W-export-{uid}"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = _conn(sample_db)
    try:
        conn.execute(
            "INSERT INTO works (id, title, authors, year, doi, arxiv_id, doc_type, language, "
            "metadata_status, parse_status, read_status, created_at, updated_at, venue, primary_doc_type, priority, is_core_literature) "
            "VALUES (?, ?, ?, ?, ?, ?, 'paper', 'en', 'done', 'parsed', 'unread', ?, ?, 'TestConf', 'research_article', 'high', 1)",
            (wid, "Rich Export Paper", '["Doe, John", "Smith, Anna"]', 2025, "10.9999/rich", None, now, now),
        )
        conn.execute(
            "INSERT INTO metadata_extractions (id, work_id, model_name, content_md_path, input_chars, input_tokens_est, "
            "raw_response, extracted_json, confidence_json, applied, created_at, review_status, risk_level, risk_score, "
            "risk_reasons, review_source, fix_action, superseded_by) "
            "VALUES (?, ?, 'test', '', 0, 0, '{}', '{}', '{}', 1, ?, 'approved', 'low', 0, '[]', 'human', '', '')",
            (f"ME-{uid}", wid, now),
        )
        for grp, val in [("method_tags", "red_teaming"), ("method_tags", "benchmark_construction"), ("risk_domain", "deception")]:
            conn.execute(
                "INSERT INTO work_classification_tags (id, work_id, tag_group, tag_value, review_status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'approved', ?, ?)",
                (f"CT-{uid}-{val}", wid, grp, val, now, now),
            )
        digest = {"fields": {"one_sentence_positioning": {"value": "这是一篇测试定位句。"}}}
        conn.execute(
            "INSERT INTO analysis_runs (id, kind, angle, work_id, extracted_json, review_status, created_at, updated_at) "
            "VALUES (?, 'digest', 'digest', ?, ?, 'approved', ?, ?)",
            (f"AR-{uid}", wid, json.dumps(digest, ensure_ascii=False), now, now),
        )
        conn.commit()
    finally:
        conn.close()
    yield wid
    conn = _conn(sample_db)
    try:
        for table in ("works", "metadata_extractions", "work_classification_tags", "analysis_runs"):
            conn.execute(f"DELETE FROM {table} WHERE work_id = ?" if table != "works" else f"DELETE FROM {table} WHERE id = ?", (wid,))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def quarantined_work(sample_db):
    """插入一篇 approved 但已隔离的 work（不应被导出；测试后清理）。"""
    uid = uuid.uuid4().hex[:6]
    wid = f"W-quar-{uid}"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = _conn(sample_db)
    try:
        conn.execute(
            "INSERT INTO works (id, title, authors, year, doc_type, language, metadata_status, parse_status, "
            "read_status, created_at, updated_at) VALUES (?, 'Quarantined Paper', '[]', 2024, 'paper', 'en', 'done', 'parsed', 'quarantined', ?, ?)",
            (wid, now, now),
        )
        conn.execute(
            "INSERT INTO metadata_extractions (id, work_id, model_name, content_md_path, input_chars, input_tokens_est, "
            "raw_response, extracted_json, confidence_json, applied, created_at, review_status, risk_level, risk_score, "
            "risk_reasons, review_source, fix_action, superseded_by) "
            "VALUES (?, ?, 'test', '', 0, 0, '{}', '{}', '{}', 1, ?, 'approved', 'low', 0, '[]', 'human', '', '')",
            (f"ME-quar-{uid}", wid, now),
        )
        conn.commit()
    finally:
        conn.close()
    yield wid
    conn = _conn(sample_db)
    try:
        conn.execute("DELETE FROM metadata_extractions WHERE work_id = ?", (wid,))
        conn.execute("DELETE FROM works WHERE id = ?", (wid,))
        conn.commit()
    finally:
        conn.close()


# ---------- 过滤规则 ----------

def test_only_approved_metadata_exported(client):
    body = client.get("/api/export/bibtex").text
    assert "W-sample-002" in body
    assert "W-sample-001" not in body  # pending
    assert "W-sample-003" not in body  # 无 metadata


def test_quarantined_excluded(client, quarantined_work):
    body = client.get("/api/export/bibtex").text
    assert quarantined_work not in body


def test_work_ids_explicit_selection(client):
    body = client.get("/api/export/bibtex", params={"work_ids": "W-sample-002"}).text
    assert "W-sample-002" in body
    body2 = client.get("/api/export/bibtex", params={"work_ids": "W-sample-001"}).text
    assert "W-sample-001" not in body2  # 显式指定也不能突破 approved 门禁


def test_search_and_doctype_filter(client, rich_work):
    body = client.get("/api/export/bibtex", params={"search": "Rich Export"}).text
    assert rich_work in body
    assert "W-sample-002" not in body
    body2 = client.get("/api/export/bibtex", params={"doc_type": "research_article"}).text
    assert rich_work in body2
    assert "W-sample-003" not in body2  # 无 approved 元数据，任何筛选都不应出现


def test_tag_filter(client, rich_work):
    body = client.get("/api/export/bibtex", params={"tag": "red_teaming"}).text
    assert rich_work in body
    assert "W-sample-002" not in body
    body2 = client.get("/api/export/bibtex", params={"tag": "nonexistent_tag"}).text
    assert "@" not in body2


# ---------- 内容正确性 ----------

@pytest.fixture
def superseded_digest_work(sample_db):
    """approved 元数据 + 一条已被取代的 approved digest（不应导出旧定位句）。"""
    uid = uuid.uuid4().hex[:6]
    wid = f"W-supdig-{uid}"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = _conn(sample_db)
    try:
        conn.execute(
            "INSERT INTO works (id, title, authors, year, doc_type, language, metadata_status, parse_status, "
            "read_status, created_at, updated_at) VALUES (?, 'Superseded Digest Paper', '[]', 2024, 'paper', 'en', 'done', 'parsed', 'unread', ?, ?)",
            (wid, now, now),
        )
        conn.execute(
            "INSERT INTO metadata_extractions (id, work_id, model_name, content_md_path, input_chars, input_tokens_est, "
            "raw_response, extracted_json, confidence_json, applied, created_at, review_status, risk_level, risk_score, "
            "risk_reasons, review_source, fix_action, superseded_by) "
            "VALUES (?, ?, 'test', '', 0, 0, '{}', '{}', '{}', 1, ?, 'approved', 'low', 0, '[]', 'human', '', '')",
            (f"ME-supdig-{uid}", wid, now),
        )
        old_digest = {"fields": {"one_sentence_positioning": {"value": "旧定位句不应导出"}}}
        conn.execute(
            "INSERT INTO analysis_runs (id, kind, angle, work_id, extracted_json, review_status, superseded_by, created_at, updated_at) "
            "VALUES (?, 'digest', 'digest', ?, ?, 'approved', 'AR-newer', ?, ?)",
            (f"AR-old-{uid}", wid, json.dumps(old_digest, ensure_ascii=False), now, now),
        )
        conn.commit()
    finally:
        conn.close()
    yield wid
    conn = _conn(sample_db)
    try:
        conn.execute("DELETE FROM metadata_extractions WHERE work_id = ?", (wid,))
        conn.execute("DELETE FROM analysis_runs WHERE work_id = ?", (wid,))
        conn.execute("DELETE FROM works WHERE id = ?", (wid,))
        conn.commit()
    finally:
        conn.close()


def test_superseded_digest_not_exported(client, superseded_digest_work):
    resp = client.get("/api/export/matrix.csv", params={"work_ids": superseded_digest_work})
    body = resp.content.decode("utf-8-sig")
    assert "旧定位句不应导出" not in body
    assert body.splitlines()[1].endswith(",")  # 一句话定位留空


def test_bibtex_content(client, rich_work):
    body = client.get("/api/export/bibtex", params={"work_ids": rich_work}).text
    assert body.startswith(f"@article{{{rich_work},")
    assert "Doe, John and Smith, Anna" in body
    assert "journal = {TestConf}" in body


def test_ris_keywords_and_end(client, rich_work):
    body = client.get("/api/export/ris", params={"work_ids": rich_work}).text
    assert "TY  - JOUR" in body
    assert "KW  - red_teaming" in body
    assert "KW  - benchmark_construction" in body
    assert body.rstrip("\n").endswith("ER  - ")


def test_matrix_csv(client, rich_work):
    resp = client.get("/api/export/matrix.csv", params={"work_ids": rich_work})
    assert resp.headers["content-type"].startswith("text/csv")
    body = resp.content.decode("utf-8-sig")
    lines = body.splitlines()
    assert lines[0].startswith("work_id,")
    assert "benchmark_construction; red_teaming" in lines[1]
    assert "deception" in lines[1]
    assert "这是一篇测试定位句。" in lines[1]
    assert "attachment" in resp.headers["content-disposition"]


def test_matrix_digest_empty_when_missing(client):
    resp = client.get("/api/export/matrix.csv", params={"work_ids": "W-sample-002"})
    body = resp.content.decode("utf-8-sig")
    assert "W-sample-002" in body
    assert body.splitlines()[1].endswith(",")  # 一句话定位留空


def test_download_headers(client):
    resp = client.get("/api/export/bibtex")
    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]
    assert ".bib" in resp.headers["content-disposition"]
