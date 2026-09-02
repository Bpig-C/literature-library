"""/parse/trigger 的 backend 覆盖与 force 重解析测试（UX-002 断点2）。

用 sample_db + 桩 _run_parse（永不触达 fitz/网络）验证：
- force=True 可重解析已 succeeded 的 run（原先只能 pending）；
- backend 参数透传到 _run_parse 并落库 parse_runs.backend；
- 非法 backend / force 无 work_ids / 无命中 run 返回 400；
- 非 force 无 pending 的旧行为不变（400）。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def _make_conn_factory(db_path):
    def _conn():
        c = sqlite3.connect(str(db_path))
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        return c
    return _conn


@pytest.fixture()
def parse_api(sample_db, tmp_path, monkeypatch):
    """patch parse 路由的 get_conn 指向 sample_db，_run_parse 指向可控桩。

    PR-001 种子的 output_dir 为 NULL，会按契约回算到**真实**仓库 works 树；
    这里显式改写到 tmp_path，保证测试不污染真实 works/。
    """
    import api.routes.parse as parse_mod

    out_dir = tmp_path / "out" / "PR-001"
    conn = sqlite3.connect(str(sample_db))
    conn.execute(
        "UPDATE literature_parse_runs SET output_dir=? WHERE id='PR-001'", (str(out_dir),)
    )
    conn.commit()
    conn.close()

    factory = _make_conn_factory(sample_db)
    with patch("api.routes.parse.get_conn", factory):
        recorded = {}

        def fake_run_parse(source_path, output_dir, language, backend=None):
            recorded["backend"] = backend
            recorded["source_path"] = source_path
            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)
            (out / "content.md").write_text("# reparsed", encoding="utf-8")
            return True, "stub ok", backend or "pymupdf", "TASK-1"

        monkeypatch.setattr(parse_mod, "_run_parse", fake_run_parse)
        yield {"recorded": recorded, "db": sample_db}


def _run_row(db_path, work_id="W-sample-001"):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM literature_parse_runs WHERE work_id=? ORDER BY id LIMIT 1",
            (work_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def test_force_reparse_succeeded_run(parse_api):
    db = parse_api["db"]
    before = _run_row(db)
    assert before["status"] == "succeeded"  # sample_db 种子即 succeeded

    r = client.post("/api/parse/trigger", json={
        "work_ids": ["W-sample-001"], "force": True, "backend": "pymupdf",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["triggered"] == 1 and body["succeeded"] == 1
    assert body["results"][0]["backend"] == "pymupdf"

    row = _run_row(db)
    assert row["status"] == "succeeded"
    assert row["backend"] == "pymupdf"
    assert row["content_md_path"].endswith("content.md")


def test_backend_passthrough_to_run_parse(parse_api):
    r = client.post("/api/parse/trigger", json={
        "work_ids": ["W-sample-001"], "force": True, "backend": "vlm",
    })
    assert r.status_code == 200
    assert parse_api["recorded"]["backend"] == "vlm"


def test_backend_auto_passes_through(parse_api):
    r = client.post("/api/parse/trigger", json={
        "work_ids": ["W-sample-001"], "force": True, "backend": "auto",
    })
    assert r.status_code == 200
    assert parse_api["recorded"]["backend"] == "auto"


def test_invalid_backend_400(parse_api):
    r = client.post("/api/parse/trigger", json={
        "work_ids": ["W-sample-001"], "force": True, "backend": "pipeline",
    })
    assert r.status_code == 400


def test_force_without_work_ids_400(parse_api):
    r = client.post("/api/parse/trigger", json={"all_pending": True, "force": True})
    assert r.status_code == 400


def test_force_unknown_work_400(parse_api):
    r = client.post("/api/parse/trigger", json={
        "work_ids": ["W-nonexistent"], "force": True,
    })
    assert r.status_code == 400


def test_non_force_no_pending_keeps_old_400(parse_api):
    """回归：PR-001 已 succeeded 且非 force → 维持旧的 400 行为。"""
    r = client.post("/api/parse/trigger", json={"work_ids": ["W-sample-001"]})
    assert r.status_code == 400
    assert parse_api["recorded"] == {}  # 未触发解析
