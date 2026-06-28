# tests/test_parse_api.py
"""Parse trigger/status API route tests. Temp DB copy; patches get_conn + LIBRARY_ROOT
in api.routes.parse. The nucleus delegation point _run_parse is stubbed so tests
never touch real clients / fitz / network."""
from __future__ import annotations
import shutil, sqlite3, tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.db import DB_PATH
from api.main import app

_tmp_dir = tempfile.mkdtemp(prefix="litlib_parse_")
_tmp_db = Path(_tmp_dir) / "literature.sqlite"
shutil.copy2(str(DB_PATH), str(_tmp_db))


def _test_get_conn():
    c = sqlite3.connect(str(_tmp_db)); c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL"); return c


@pytest.fixture(autouse=True, scope="function")
def _patch_get_conn():
    import api.routes.parse as parse
    with patch("api.routes.parse.get_conn", _test_get_conn), \
         patch("api.routes.parse.LIBRARY_ROOT", _tmp_dir):
        yield


@pytest.fixture(autouse=True, scope="function")
def _seed():
    """Function-scoped on purpose: trigger tests mutate rows (flip pending→succeeded/
    failed), and `test_trigger_failure_does_not_abort_batch` triggers BOTH seed rows
    (explicit work_ids) and needs them still pending to satisfy failed==1 AND succeeded==1.
    INSERT OR REPLACE re-inserts before each test, resetting any prior mutation.
    Session-scoped _cleanup still tears down last (session teardown follows function)."""
    conn = _test_get_conn()
    now = "2026-06-28T00:00:00"
    conn.executemany(
        "INSERT OR REPLACE INTO works(id,title,language,parse_status,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?)",
        [("W-parse-test-1", "T1", "english", "pending", now, now),
         ("W-parse-test-2", "T2", "chinese", "pending", now, now)],
    )
    out1 = str(Path(_tmp_dir) / "works" / "W-parse-test-1" / "parsed" / "mineru" / "SF-1")
    out2 = str(Path(_tmp_dir) / "works" / "W-parse-test-2" / "parsed" / "mineru" / "SF-2")
    conn.executemany(
        "INSERT OR REPLACE INTO literature_parse_runs"
        "(id,work_id,source_file_id,source_path,task_id,status,backend,parse_method,"
        " file_size,started_at,finished_at,output_dir,error,content_json_path,"
        " content_md_path,package_path) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [("LPR-SF-1", "W-parse-test-1", "SF-1", "/tmp/a.pdf", "", "pending", "",
          "auto", 0, now, None, out1, "", "", "", ""),
         ("LPR-SF-2", "W-parse-test-2", "SF-2", "/tmp/b.pdf", "", "pending", "",
          "auto", 0, now, None, out2, "", "", "", "")],
    )
    conn.commit(); conn.close()


@pytest.fixture(autouse=True, scope="session")
def _cleanup():
    yield
    shutil.rmtree(_tmp_dir, ignore_errors=True)


client = TestClient(app)


def test_status_aggregate_counts():
    r = client.get("/api/parse/status")
    assert r.status_code == 200
    s = r.json()
    assert s["total"] >= 2
    assert s["pending"] >= 2


def test_status_single_work():
    r = client.get("/api/parse/status", params={"work_id": "W-parse-test-1"})
    assert r.status_code == 200
    body = r.json()
    assert body["work"]["work_id"] == "W-parse-test-1"
    assert body["work"]["status"] == "pending"
    assert body["work"]["content_md_path"] in ("", None)


def test_list_pending_runs_returns_seeded_rows():
    """Reviewer note (Task 4): lock the SQL contract that trigger depends on."""
    import api.routes.parse as parse
    conn = _test_get_conn()
    try:
        rows = parse.list_pending_runs(conn)
        by_work = {r["work_id"]: r for r in rows}
        assert "W-parse-test-1" in by_work and "W-parse-test-2" in by_work
        r1 = by_work["W-parse-test-1"]
        assert r1["run_id"] == "LPR-SF-1"
        assert r1["source_file_id"] == "SF-1"
        assert r1["source_path"] == "/tmp/a.pdf"
        assert r1["language"] == "english"  # LEFT JOIN works.language
        assert r1["output_dir"].endswith("SF-1")
        assert by_work["W-parse-test-2"]["language"] == "chinese"
    finally:
        conn.close()


def test_trigger_success_updates_run_and_status(monkeypatch):
    import api.routes.parse as parse
    seen = {}
    def fake_run(source_path, output_dir, language):
        seen.update(source_path=source_path, language=language)
        out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
        (out / "content.md").write_text("# stub md", encoding="utf-8")
        return True, "ok", "pymupdf", "BATCH-stub"
    monkeypatch.setattr(parse, "_run_parse", fake_run)
    r = client.post("/api/parse/trigger", json={"work_ids": ["W-parse-test-1"]})
    assert r.status_code == 200
    body = r.json()
    assert body["triggered"] == 1 and body["succeeded"] == 1 and body["failed"] == 0
    res = body["results"][0]
    assert res["status"] == "succeeded" and res["backend"] == "pymupdf"
    assert res["content_md_path"].endswith("content.md")
    assert seen["source_path"] == "/tmp/a.pdf"
    assert seen["language"] == "english"  # 传给 nucleus 的是 works.language 原值
    # DB 真的写了
    conn = _test_get_conn()
    try:
        row = conn.execute(
            "SELECT status, content_md_path, backend, task_id FROM literature_parse_runs WHERE id='LPR-SF-1'"
        ).fetchone()
        assert row["status"] == "succeeded"
        assert (row["content_md_path"] or "").endswith("content.md")
        assert row["backend"] == "pymupdf"
        assert row["task_id"] == "BATCH-stub"  # cloud last_batch_id 溯源被保留（I1）
        # Flag 4：works.parse_status 被同步成 succeeded
        wrow = conn.execute(
            "SELECT parse_status FROM works WHERE id='W-parse-test-1'"
        ).fetchone()
        assert wrow["parse_status"] == "succeeded"
    finally:
        conn.close()


def test_trigger_failure_does_not_abort_batch(monkeypatch):
    import api.routes.parse as parse
    calls = {"n": 0}
    def fake_run(source_path, output_dir, language):
        calls["n"] += 1
        return (False, "boom", "vlm", "BATCH-fail") if calls["n"] == 1 else (True, "ok", "pymupdf", "BATCH-ok")
    monkeypatch.setattr(parse, "_run_parse", fake_run)
    # 用 work_ids 显式选定 2 行，避免 temp DB（live 副本）里其它 pending 行
    # （如 Phase A 留下的 W-arxiv-2506.19248）混入 all_pending 集合。
    r = client.post("/api/parse/trigger",
                    json={"work_ids": ["W-parse-test-1", "W-parse-test-2"]})
    assert r.status_code == 200
    body = r.json()
    assert body["triggered"] == 2
    assert body["failed"] == 1 and body["succeeded"] == 1  # 单条失败不中断


def test_trigger_no_pending_400():
    # 不存在的 work_id → 空集 → 400
    r = client.post("/api/parse/trigger", json={"work_ids": ["W-nope-not-exist"]})
    assert r.status_code == 400


def test_trigger_empty_body_400():
    r = client.post("/api/parse/trigger", json={})
    assert r.status_code == 400
