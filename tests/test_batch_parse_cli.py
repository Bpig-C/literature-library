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
    # hermetic：run_pending(execute=True) 在调用 stub 的 route_and_parse 之前有
    # token 闸门。设一个 dummy key 让闸门通过（key 永不真用——CloudClient/
    # route_and_parse 均被各测试 stub）。避免依赖真实 .env（CI/干净检出无 .env）。
    monkeypatch.setenv("MinerU_API_KEY", "test-dummy-not-used")
    return mod


def _ensure_pending_row(conn, tmp_path, sf_id="SF-cli1", work_id="W-cli1"):
    source_path = str(tmp_path / "x.pdf")
    output_dir = str(tmp_path / "out")
    content_json_path = str(tmp_path / "out" / "content.json")
    content_md_path = str(tmp_path / "out" / "content.md")
    conn.execute(
        "INSERT OR REPLACE INTO source_files "
        "(id, work_id, content_sha256, original_name, source_path, "
        "relative_source_path, file_size, file_ext, status) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (sf_id, work_id, f"sha_{sf_id}", "x.pdf", source_path,
         f"works/{work_id}/source/x.pdf", 1000, ".pdf", "active"),
    )
    conn.execute(
        "INSERT OR REPLACE INTO literature_parse_runs "
        "(id, work_id, source_file_id, source_path, task_id, status, backend, "
        " parse_method, file_size, started_at, finished_at, output_dir, error, "
        " content_json_path, content_md_path, package_path) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (f"LPR-{sf_id}", work_id, sf_id, source_path, "", "pending",
         "vlm", "auto", 1000, "2026-06-28T00:00:00+00:00", "", output_dir,
         "", content_json_path, content_md_path, ""),
    )
    conn.execute(
        "INSERT OR REPLACE INTO works (id, title, parse_status, read_status, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?)",
        (work_id, "t", "pending", "unread", "2026-06-28", "2026-06-28"),
    )
    conn.commit()


def test_get_pending_db_reads_parse_runs(cli_module, tmp_path):
    conn = sqlite3.connect(str(cli_module.DB_PATH))
    try:
        _ensure_pending_row(conn, tmp_path)
    finally:
        conn.close()
    pending = cli_module.get_pending_db()
    sf_ids = [p["source_file_id"] for p in pending]
    assert "SF-cli1" in sf_ids
    # 字段集齐备
    row = next(p for p in pending if p["source_file_id"] == "SF-cli1")
    assert row["work_id"] == "W-cli1"
    assert row["source_path"] == str(tmp_path / "x.pdf")
    assert row["output_dir"]


def test_get_pending_db_excludes_non_pending(cli_module, tmp_path):
    conn = sqlite3.connect(str(cli_module.DB_PATH))
    try:
        _ensure_pending_row(conn, tmp_path)
        conn.execute(
            "UPDATE literature_parse_runs SET status='succeeded' WHERE id='LPR-SF-cli1'"
        )
        conn.commit()
    finally:
        conn.close()
    assert all(p["source_file_id"] != "SF-cli1" for p in cli_module.get_pending_db())


def test_run_one_writes_db_and_syncs_work_status(cli_module, monkeypatch, tmp_path):
    """成功解析后：parse_runs.status=succeeded 且 works.parse_status=succeeded。"""
    conn = sqlite3.connect(str(cli_module.DB_PATH))
    try:
        _ensure_pending_row(conn, tmp_path)
    finally:
        conn.close()

    # 桩 route_and_parse：写一个假 content.md，返回成功
    def fake_route_and_parse(client, pymupdf_client, source_path, output_dir, language, backend="auto"):
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


def test_run_one_dry_run_does_not_write(cli_module, monkeypatch, tmp_path):
    conn = sqlite3.connect(str(cli_module.DB_PATH))
    try:
        _ensure_pending_row(conn, tmp_path)
    finally:
        conn.close()
    called = {"n": 0}

    def fake_route_and_parse(*a, **k):
        called["n"] += 1
        return True, "", "pymupdf"

    monkeypatch.setattr(cli_module, "route_and_parse", fake_route_and_parse)
    cli_module.run_pending(execute=False)
    assert called["n"] == 0  # dry-run 不解析


def test_sync_failure_does_not_rollback_parse_runs(cli_module, monkeypatch, tmp_path):
    """sync_work_parse_status 抛异常时，parse_runs 的 succeeded 仍应被提交（不回滚）。

    回归 MINOR-1：sync 在内层 except 之外、commit 之前；若它的异常未吞掉，
    会回滚 parse_runs 的 succeeded UPDATE，但磁盘 content.md 已写 → 静默不一致。
    """
    conn = sqlite3.connect(str(cli_module.DB_PATH))
    try:
        _ensure_pending_row(conn, tmp_path)
    finally:
        conn.close()

    # 桩 route_and_parse：写一个假 content.md，返回成功
    def fake_route_and_parse(client, pymupdf_client, source_path, output_dir, language, backend="auto"):
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "content.md").write_text("# ok", encoding="utf-8")
        return True, "", "pymupdf"

    monkeypatch.setattr(cli_module, "route_and_parse", fake_route_and_parse)
    monkeypatch.setattr(cli_module, "CloudClient", lambda: object(), raising=False)
    monkeypatch.setattr(cli_module, "PyMuPDFClient", lambda: object(), raising=False)

    # 让 sync_work_parse_status 抛异常
    def boom(conn, work_id):
        raise RuntimeError("sync boom")

    monkeypatch.setattr(cli_module, "sync_work_parse_status", boom)

    rc = cli_module.run_pending(execute=True)
    assert rc == 0  # sync 异常被吞，整体 rc 仍为 0（解析成功）

    conn = sqlite3.connect(str(cli_module.DB_PATH))
    try:
        pr = conn.execute(
            "SELECT status FROM literature_parse_runs WHERE id='LPR-SF-cli1'"
        ).fetchone()
        # 关键断言：succeeded 未被回滚
        assert pr[0] == "succeeded", (
            f"sync 异常不应回滚 parse_runs；实际 status={pr[0]!r}"
        )
    finally:
        conn.close()


def test_cli_direct_invocation_imports_clean():
    """回归：直接 `python scripts/literature_batch_parse.py` 运行时，顶层 import 链不报 ModuleNotFoundError。

    本 CLI 顶部 `from scripts.migrate_sync_parse_status import ...` 与
    `from core.mineru.router import ...` 要求 repo root 和 parser 子项目都在
    sys.path 上。经包路径 import（pytest/-m）总成立，但直接当脚本跑时
    sys.path[0] 是 scripts/ 目录，必须由脚本自身显式补 path。
    用 --help：argparse 在任何 DB 访问前 exit，但模块顶层 import 已先执行——
    若 import 链坏，这里会非 0 退出并带 ModuleNotFoundError。hermetic，不触 DB/网络/fitz。
    """
    import subprocess
    import sys

    repo_root = Path(__file__).resolve().parents[1]
    r = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "literature_batch_parse.py"), "--help"],
        capture_output=True, text=True, cwd=str(repo_root), timeout=30,
    )
    assert r.returncode == 0, (
        f"CLI 直接运行失败（returncode={r.returncode}）:\nSTDOUT:{r.stdout}\nSTDERR:{r.stderr}"
    )
    assert "ModuleNotFoundError" not in r.stderr
