"""inbox 摄入 API 测试。temp library_root（含 _inbox + literature.sqlite），
不触真网络。nucleus 走 connect_db，故 patch LIBRARY_ROOT 指向 temp 目录。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture()
def client():
    return TestClient(app)


def _make_pdf(path: Path, content: bytes = b"%PDF-1.4 fake") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


@pytest.fixture()
def temp_library(tmp_path, monkeypatch):
    """temp library：空 literature.sqlite（ensure_core_schema）+ _inbox/ 放 PDF。"""
    from scripts.literature_ingest import ensure_core_schema
    db = tmp_path / "literature.sqlite"
    conn = sqlite3.connect(str(db))
    ensure_core_schema(conn)
    conn.commit()
    conn.close()
    (tmp_path / "_inbox").mkdir(exist_ok=True)
    _make_pdf(tmp_path / "_inbox" / "arXiv-2501.12345-Test Paper 2025.pdf")
    # patch 路由的 LIBRARY_ROOT → temp
    import api.routes.ingest as ingest_route
    monkeypatch.setattr(ingest_route, "LIBRARY_ROOT", tmp_path)
    return tmp_path


def test_plan_returns_dry_run_preview(temp_library, client):
    resp = client.get("/api/ingest/plan")
    assert resp.status_code == 200
    data = resp.json()
    assert data["dry_run"] is True
    assert data["summary"]["ingests"] >= 1
    # dry-run 不写盘：works 表仍空
    conn = sqlite3.connect(str(temp_library / "literature.sqlite"))
    try:
        n = conn.execute("SELECT COUNT(*) FROM works").fetchone()[0]
    finally:
        conn.close()
    assert n == 0


def test_plan_empty_inbox(temp_library, client):
    # 清空 _inbox
    for p in (temp_library / "_inbox").glob("*.pdf"):
        p.unlink()
    resp = client.get("/api/ingest/plan")
    assert resp.status_code == 200
    assert resp.json()["summary"]["ingests"] == 0


def test_execute_writes_works_and_parse_run(temp_library, client):
    resp = client.post("/api/ingest/execute", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["summary"]["ingests"] >= 1
    conn = sqlite3.connect(str(temp_library / "literature.sqlite"))
    try:
        nworks = conn.execute("SELECT COUNT(*) FROM works").fetchone()[0]
        nruns = conn.execute(
            "SELECT COUNT(*) FROM literature_parse_runs WHERE status='pending'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert nworks >= 1
    assert nruns >= 1  # Phase B 解析接力点


def test_execute_empty_inbox_returns_400(temp_library, client):
    for p in (temp_library / "_inbox").glob("*.pdf"):
        p.unlink()
    resp = client.post("/api/ingest/execute", json={})
    assert resp.status_code == 400
