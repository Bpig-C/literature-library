"""新 CLI DB-only 行为测试：pending 从 parse_runs 读；结果写 parse_runs + 同步 works.parse_status。
不触达真 fitz/网络——route_and_parse 用桩。"""
from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture()
def cli_module(tmp_path, monkeypatch):
    """加载新 CLI 模块，DB_PATH 指向 temp 副本。"""
    import shutil
    src = Path(__file__).resolve().parents[1] / "literature.sqlite"
    db = tmp_path / "literature.sqlite"
    if src.exists():
        shutil.copy(src, db)
    mod = importlib.import_module("scripts.literature_batch_parse")
    monkeypatch.setattr(mod, "DB_PATH", db)
    return mod


def _ensure_pending_row(conn, sf_id="SF-cli1", work_id="W-cli1"):
    conn.execute(
        "INSERT OR REPLACE INTO literature_parse_runs "
        "(id, work_id, source_file_id, source_path, task_id, status, backend, "
        " parse_method, file_size, started_at, finished_at, output_dir, error, "
        " content_json_path, content_md_path, package_path) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (f"LPR-{sf_id}", work_id, sf_id, "/tmp/x.pdf", "", "pending",
         "vlm", "auto", 1000, "2026-06-28T00:00:00+00:00", "", "/tmp/out",
         "", "/tmp/out/content.json", "/tmp/out/content.md", ""),
    )
    conn.execute(
        "INSERT OR REPLACE INTO works (id, title, parse_status, read_status, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?)",
        (work_id, "t", "pending", "unread", "2026-06-28", "2026-06-28"),
    )
    conn.commit()


def test_get_pending_db_reads_parse_runs(cli_module):
    conn = sqlite3.connect(str(cli_module.DB_PATH))
    try:
        _ensure_pending_row(conn)
    finally:
        conn.close()
    pending = cli_module.get_pending_db()
    sf_ids = [p["source_file_id"] for p in pending]
    assert "SF-cli1" in sf_ids
    # 字段集齐备
    row = next(p for p in pending if p["source_file_id"] == "SF-cli1")
    assert row["work_id"] == "W-cli1"
    assert row["source_path"] == "/tmp/x.pdf"
    assert row["output_dir"]


def test_get_pending_db_excludes_non_pending(cli_module):
    conn = sqlite3.connect(str(cli_module.DB_PATH))
    try:
        _ensure_pending_row(conn)
        conn.execute(
            "UPDATE literature_parse_runs SET status='succeeded' WHERE id='LPR-SF-cli1'"
        )
        conn.commit()
    finally:
        conn.close()
    assert all(p["source_file_id"] != "SF-cli1" for p in cli_module.get_pending_db())


def test_run_one_writes_db_and_syncs_work_status(cli_module, monkeypatch):
    """成功解析后：parse_runs.status=succeeded 且 works.parse_status=succeeded。"""
    conn = sqlite3.connect(str(cli_module.DB_PATH))
    try:
        _ensure_pending_row(conn)
    finally:
        conn.close()

    # 桩 route_and_parse：写一个假 content.md，返回成功
    def fake_route_and_parse(client, pymupdf_client, source_path, output_dir, language):
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "content.md").write_text("# ok", encoding="utf-8")
        return True, "", "pymupdf"

    monkeypatch.setattr(cli_module, "route_and_parse", fake_route_and_parse)
    monkeypatch.setattr(cli_module, "CloudClient", lambda: object(), raising=False)
    monkeypatch.setattr(cli_module, "PyMuPDFClient", lambda: object(), raising=False)

    rc = cli_module.run_pending(execute=True)
    assert rc == 0

    conn = sqlite3.connect(str(cli_module.DB_PATH))
    try:
        pr = conn.execute(
            "SELECT status, content_md_path, backend FROM literature_parse_runs WHERE id='LPR-SF-cli1'"
        ).fetchone()
        assert pr[0] == "succeeded"
        assert pr[1] and pr[1].endswith("content.md")
        assert pr[2] == "pymupdf"
        w = conn.execute("SELECT parse_status FROM works WHERE id='W-cli1'").fetchone()
        assert w[0] == "succeeded"  # 经 sync_work_parse_status 同步
    finally:
        conn.close()


def test_run_one_dry_run_does_not_write(cli_module, monkeypatch):
    conn = sqlite3.connect(str(cli_module.DB_PATH))
    try:
        _ensure_pending_row(conn)
    finally:
        conn.close()
    called = {"n": 0}

    def fake_route_and_parse(*a, **k):
        called["n"] += 1
        return True, "", "pymupdf"

    monkeypatch.setattr(cli_module, "route_and_parse", fake_route_and_parse)
    cli_module.run_pending(execute=False)
    assert called["n"] == 0  # dry-run 不解析
