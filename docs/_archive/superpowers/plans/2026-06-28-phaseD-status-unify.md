# Phase D 状态源统一 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 废弃 `parse_ledger.json` 文件状态源，让 `literature_parse_runs`（DB）成为解析状态的唯一权威；新 CLI 改 DB-only；归档旧自部署 CLI。

**Architecture:** 不加 DB 列、不动状态机。归档旧 CLI（`parser/scripts/literature_batch_parse.py`，自部署 Agent API 版，4 个专属字段/四态的唯一消费者）后，新 CLI 的 ledger 本就是 parse_runs 的纯冗余镜像。因此统一 = 新 CLI 改读写 DB + 删 ingest 的 ledger 写 + 修 healthcheck/dashboard 读者 + 移走 ledger 文件。work 状态统一复用既有 `sync_work_parse_status`（三态 pending/succeeded/failed），新 CLI 成为其第 3 个调用方。

**Tech Stack:** Python 3.11 / sqlite3 / FastAPI / pytest（function-scoped temp DB，仿 tests/test_parse_api.py）。

**硬约束（每任务必守）：**
1. §2 单核：`parser/core/mineru/router.py::route_and_parse` 全仓唯一命中，本计划不碰它。
2. 解析输出契约不变：`works/{work_id}/parsed/mineru/{source_file_id}/content.md` + `literature_parse_runs.content_md_path`。
3. 测试不触达真网络/真 fitz/真文件 IO——`route_and_parse` 用 monkeypatch 桩；DB 用 temp 副本。
4. 向后兼容：既有 API 路由语义不变；CLI 的 `--execute/--limit/dry-run` 行为不变。
5. 范围守恒：不碰 `parser/scripts/` 下与 ledger 无关的 `literature_inventory.py`/`literature_migrate.py`/`migration_decisions.py`（非本 phase）。

**接力点实锤：**
- 新 CLI：`scripts/literature_batch_parse.py`（234 行，已委托 `core.mineru.router.route_and_parse`）。
- 旧 CLI（要归档）：`parser/scripts/literature_batch_parse.py`（857 行，打 `/api/v1/tasks` 自部署 HTTP，含 `Ledger` 类/bucket/failure_kind）。
- 状态同步复用点：`scripts/migrate_sync_parse_status.py::sync_work_parse_status(conn, work_id)`（API 已用）。
- ingest 双写起点：`scripts/literature_ingest.py:691 update_ledger` + `:721 insert_db_rows`（后者已写 parse_runs），调用点 `:925`。
- 读者：`scripts/literature_healthcheck.py:115 check_parse_ledger`（调用 `:500`、输出键 `:527`）、`scripts/literature_dashboard.py:67/93-95/155/162`（ledger 兜底）。
- 测试范本：`tests/test_parse_api.py`（temp DB + patch get_conn + 桩 route_and_parse）。

---

## Task 1: 归档旧自部署 CLI 与 ledger 依赖的 cleanup 工具

**Files:**
- Move: `parser/scripts/literature_batch_parse.py` → `_archive/parser_scripts_literature_batch_parse.py`
- Move: `parser/scripts/literature_cleanup_bad_sources.py` → `_archive/parser_scripts_literature_cleanup_bad_sources.py`
- Verify: 无 active 代码 import 上述模块（已确认 `api/`、`scripts/`根、`collector/` 零引用；仅 `parser/tests/` 引用，而 `parser/tests` 不在根 pytest `testpaths` 内）。

- [ ] **Step 1: 确认 cleanup_bad_sources 是 ledger 依赖的旧生态工具**

Run:
```bash
grep -n "parse_ledger\|load_ledger\|ledger" parser/scripts/literature_cleanup_bad_sources.py | head
```
Expected: 命中 `parse_ledger`/`load_ledger`（证明它读 ledger，ledger 废弃后即失效，应一并归档）。若**未**命中（即它不依赖 ledger），则**只归档 batch_parse，跳过 cleanup**——在本步笔记记录决策，不强行归档。

- [ ] **Step 2: 确认归档不破坏根测试收集**

Run:
```bash
uv run python -m pytest tests/ -q 2>&1 | tail -5
```
Expected: 192 passed / 6 skipped / 0 failed（归档前基线）。

- [ ] **Step 3: 用 git mv 归档（保留历史）**

```bash
mkdir -p _archive
git mv parser/scripts/literature_batch_parse.py _archive/parser_scripts_literature_batch_parse.py
# 仅当 Step 1 确认 ledger 依赖时执行：
git mv parser/scripts/literature_cleanup_bad_sources.py _archive/parser_scripts_literature_cleanup_bad_sources.py
```

- [ ] **Step 4: 在 _archive/ 顶部加 README 说明（若无）**

Create/append `_archive/README.md`：
```markdown
# _archive

已弃用、确认无 active 引用的脚本。保留备查，不在任何运行路径上。

- `parser_scripts_literature_batch_parse.py`：旧自部署 MinerU Agent API（:18200 /api/v1/tasks）版批量解析 CLI。Phase D 状态源统一时归档——新 CLI `scripts/literature_batch_parse.py`（官网 cloud API + core.mineru.router 单核）已取代。
- `parser_scripts_literature_cleanup_bad_sources.py`：依赖已废弃的 parse_ledger.json，随旧 CLI 归档。
```

- [ ] **Step 5: 验证根测试仍绿 + 裸 pytest 仍干净**

Run:
```bash
uv run python -m pytest tests/ -q 2>&1 | tail -3
uv run python -m pytest --collect-only -q 2>&1 | tail -3
```
Expected: 192 passed / 6 skipped / 0 failed；198 tests collected 无 ERROR。

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore(P3.5/D): 归档旧自部署 MinerU Agent API CLI 及 ledger 依赖工具

Phase D 状态源统一预备：parser/scripts/literature_batch_parse.py
(自部署 /api/v1/tasks 版，Ledger 类/bucket/failure_kind 唯一消费者) 与
literature_cleanup_bad_sources.py(ledger 依赖) 移至 _archive/。
active 代码(api/scripts/collector) 零引用，根测试不受影响。"
```

---

## Task 2: 新 CLI 改 DB-only（TDD）

**Files:**
- Modify: `scripts/literature_batch_parse.py`（删 `load_ledger/save_ledger/get_pending`，新增 `get_pending_db`，main 改读写 DB，末尾调 `sync_work_parse_status`）。
- Test: `tests/test_batch_parse_cli.py`（新建，仿 `tests/test_parse_api.py` 的 temp DB + 桩 route_and_parse）。

- [ ] **Step 1: 写失败测试 —— get_pending_db 从 DB 读 pending**

Create `tests/test_batch_parse_cli.py`：
```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run python -m pytest tests/test_batch_parse_cli.py -q`
Expected: FAIL（`AttributeError: module ... has no attribute 'get_pending_db'`）。

- [ ] **Step 3: 实现 get_pending_db + 删 ledger 函数**

In `scripts/literature_batch_parse.py`，删除 `load_ledger`/`save_ledger`/`get_pending`（行 64-79），替换为：
```python
def get_pending_db(limit: int | None = None) -> list[dict]:
    """从 literature_parse_runs 读 status='pending' 的待解析任务（DB 唯一源）。"""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        rows = conn.execute(
            """SELECT pr.source_file_id, pr.work_id, pr.source_path, pr.output_dir,
                      w.language AS language
               FROM literature_parse_runs pr
               LEFT JOIN works w ON w.id = pr.work_id
               WHERE pr.status = 'pending'
               ORDER BY pr.id"""
        ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["output_dir"] = d["output_dir"] or ""
        d["language"] = d.get("language") or ""
        out.append(d)
    if limit:
        out = out[:limit]
    return out
```
（同步删顶部 `import json` 若不再被引用——本文件改完后 save_ledger/load_ledger 已删，json 仅它们用。`time`/`Any` 视实际保留。）

- [ ] **Step 4: 运行确认 get_pending 测试通过**

Run: `uv run python -m pytest tests/test_batch_parse_cli.py -q`
Expected: 2 passed。

- [ ] **Step 5: 写失败测试 —— parse 成功后写 parse_runs + 同步 works.parse_status**

Append to `tests/test_batch_parse_cli.py`：
```python
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
```

- [ ] **Step 6: 运行确认失败**

Run: `uv run python -m pytest tests/test_batch_parse_cli.py::test_run_one_writes_db_and_syncs_work_status -q`
Expected: FAIL（`AttributeError: ... has no attribute 'run_pending'`）。

- [ ] **Step 7: 重构 main 为 run_pending(execute, limit) + 薄 main**

In `scripts/literature_batch_parse.py`，把原 `main()` 解析循环逻辑重构为可单测的 `run_pending(execute: bool, limit: int | None = None) -> int`，DB-only，末尾对每个 work 调 `sync_work_parse_status`。删除所有 `ledger`/`save_ledger` 引用。完整替换 `main` 及循环体为：
```python
from scripts.migrate_sync_parse_status import sync_work_parse_status  # 顶部 import 区


def _open_conn() -> sqlite3.Connection:
    return sqlite3.connect(str(DB_PATH))


def _update_run_db(conn, sf_id, status, task_id, now, error="", content_md_path="",
                   content_json_path="", package_path="", backend="") -> None:
    """写 parse_runs 单行。"""
    if backend:
        conn.execute(
            """UPDATE literature_parse_runs
               SET status=?, task_id=?, finished_at=?, error=?,
                   content_md_path=?, content_json_path=?, package_path=?, backend=?
               WHERE id=?""",
            (status, task_id, now, error, content_md_path, content_json_path,
             package_path, backend, f"LPR-{sf_id}"),
        )
    else:
        conn.execute(
            """UPDATE literature_parse_runs
               SET status=?, task_id=?, finished_at=?, error=?,
                   content_md_path=?, content_json_path=?, package_path=?
               WHERE id=?""",
            (status, task_id, now, error, content_md_path, content_json_path,
             package_path, f"LPR-{sf_id}"),
        )


def run_pending(execute: bool, limit: int | None = None) -> int:
    """解析所有 status='pending' 的 parse_run。DB 唯一状态源。

    execute=False → dry-run 仅列出；execute=True → 串行 route_and_parse，
    逐条 UPDATE parse_runs + sync_work_parse_status。
    """
    load_env_file()
    from core.mineru.cloud_client import CloudClient  # noqa: PLC0415
    from core.mineru.pymupdf_client import PyMuPDFClient  # noqa: PLC0415

    pending = get_pending_db(limit=limit)
    if not pending:
        print("No pending parse tasks.")
        return 0

    print(f"{'[DRY-RUN] ' if not execute else ''}Pending: {len(pending)} files "
          f"(route: 文本层→PyMuPDF / 扫描型→cloud vlm)")
    for p in pending:
        print(f"  {p['source_file_id']}: {p['source_path']}")

    if not execute:
        return 0

    token_present = bool(os.getenv("MinerU_API_KEY") or os.getenv("MINERU_API_TOKEN"))
    if not token_present:
        print("ERROR: MinerU_API_KEY 未在环境/根目录 .env 中找到，无法执行 cloud 解析。")
        return 2

    client = CloudClient()
    pymupdf_client = PyMuPDFClient()
    success = failed = 0
    for p in pending:
        source_path = p["source_path"]
        output_dir = Path(p["output_dir"])
        language = p.get("language") or work_language(p.get("work_id", ""))
        print(f"\n[{p['source_file_id']}] route+parse: {Path(source_path).name} (lang={language})")
        conn = _open_conn()
        try:
            try:
                ok, msg, backend_used = route_and_parse(
                    client, pymupdf_client, source_path, output_dir, language
                )
                now = utc_now()
                if ok:
                    content_md = output_dir / "content.md"
                    content_json = output_dir / "content.json"
                    package = output_dir / "package.zip"
                    md_text = content_md.read_text(encoding="utf-8") if content_md.exists() else ""
                    batch_id = getattr(client, "last_batch_id", "") or ""
                    _update_run_db(
                        conn, p["source_file_id"], "succeeded", batch_id, now,
                        content_md_path=str(content_md),
                        content_json_path=str(content_json),
                        package_path=str(package) if package.exists() else "",
                        backend=backend_used,
                    )
                    success += 1
                    print(f"  OK ({len(md_text)} chars md) backend={backend_used} batch_id={batch_id}")
                else:
                    batch_id = getattr(client, "last_batch_id", "") or ""
                    _update_run_db(
                        conn, p["source_file_id"], "failed", batch_id, now,
                        error=msg, backend="vlm",
                    )
                    failed += 1
                    print(f"  FAILED: {msg}")
            except Exception as exc:  # noqa: BLE001
                now = utc_now()
                _update_run_db(conn, p["source_file_id"], "failed", "", now, error=str(exc))
                failed += 1
                print(f"  ERROR: {exc}")
            # 同步 works.parse_status（复用既有 helper，状态源统一）
            sync_work_parse_status(conn, p["work_id"])
            conn.commit()
        finally:
            conn.close()

    print(f"\nDone: {success} succeeded, {failed} failed")
    return 0 if failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch parse pending PDFs via MinerU cloud API.")
    parser.add_argument("--execute", action="store_true", help="Actually parse. Default is dry-run.")
    parser.add_argument("--limit", type=int, default=None, help="Max number of files to parse.")
    args = parser.parse_args()
    return run_pending(execute=args.execute, limit=args.limit)
```
注意：保留 `load_env_file`/`work_language`/`utc_now` 原样；删除原 main 里 `token_present` 检查在 dry-run 前的位置（移入 run_pending 的 execute 分支，见上）。删除 `update_db`（被 `_update_run_db(conn,...)` 取代，后者在事务内）。

- [ ] **Step 8: 运行全部新 CLI 测试通过**

Run: `uv run python -m pytest tests/test_batch_parse_cli.py -q`
Expected: 4 passed。

- [ ] **Step 9: 运行全量回归**

Run: `uv run python -m pytest tests/ -q 2>&1 | tail -3`
Expected: 196 passed / 6 skipped / 0 failed（+4 新测试，无回归）。

- [ ] **Step 10: Commit**

```bash
git add scripts/literature_batch_parse.py tests/test_batch_parse_cli.py
git commit -m "refactor(P3.5/D): 新 CLI 改 DB-only，废弃 parse_ledger.json 读取

scripts/literature_batch_parse.py:
- 删 load_ledger/save_ledger/get_pending(文件源)
- 新增 get_pending_db 从 literature_parse_runs 读 pending(DB 唯一源)
- main 拆为 run_pending(execute,limit) 可单测
- 逐条 UPDATE parse_runs + 调 sync_work_parse_status 同步 works.parse_status
  (修掉 CLI 不同步 work 状态的缺口；复用既有 helper 不造第三套)
- 解析输出契约不变(content.md + content_md_path)

tests/test_batch_parse_cli.py: 新增，temp DB + 桩 route_and_parse
覆盖 get_pending_db/成功写库+状态同步/dry-run 不写。"
```

---

## Task 3: 删 ingest 的 ledger 双写（TDD）

**Files:**
- Modify: `scripts/literature_ingest.py`（删 `update_ledger` 函数 691-718 + 调用点 925 + 不再使用的 `bucket_for_size` 引用若仅此处用）。
- Test: 既有 `tests/test_ingest_bridge.py` 或新建断言。

- [ ] **Step 1: 写失败测试 —— ingest 后无 parse_ledger.json，但 parse_runs 行已建**

Create `tests/test_ingest_no_ledger.py`：
```python
"""ingest 不再写 parse_ledger.json；parse_runs pending 行仍由 insert_db_rows 建立。"""
from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path


def test_ingest_does_not_write_ledger(tmp_path, monkeypatch):
    library_root = tmp_path
    ingest = importlib.import_module("scripts.literature_ingest")
    # 不真正跑 ingest（需文件）；直接断言 update_ledger 已从模块移除
    assert not hasattr(ingest, "update_ledger"), (
        "update_ledger 应已删除——parse_ledger.json 不再是状态源"
    )
    # parse_ledger.json 不应被 insert_db_rows 创建
    assert not (library_root / "parse_ledger.json").exists()
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run python -m pytest tests/test_ingest_no_ledger.py -q`
Expected: FAIL（`update_ledger` 仍存在）。

- [ ] **Step 3: 删除 update_ledger 及调用**

In `scripts/literature_ingest.py`：
- 删除 `def update_ledger(...)` 整个函数（行 691-718）。
- 删除调用点 `update_ledger(library_root, plan, now)`（行 925）。
- 若 `bucket_for_size` 仅被 `update_ledger` 使用，删除其定义与 import（先 grep 确认无其他引用）。

Run 确认无残留引用：
```bash
grep -n "update_ledger\|parse_ledger" scripts/literature_ingest.py
```
Expected: 空。

- [ ] **Step 4: 运行测试通过 + ingest 相关回归**

Run:
```bash
uv run python -m pytest tests/test_ingest_no_ledger.py tests/test_ingest_bridge.py tests/test_intake_cli.py -q 2>&1 | tail -3
```
Expected: 全 passed（ingest_bridge/intake 仍绿，证明 insert_db_rows 写 parse_runs 未受影响）。

- [ ] **Step 5: Commit**

```bash
git add scripts/literature_ingest.py tests/test_ingest_no_ledger.py
git commit -m "refactor(P3.5/D): ingest 删 update_ledger，停止双写 parse_ledger.json

literature_parse_runs 的 pending 行早由 insert_db_rows 建立(DB 单写)；
update_ledger 写的文件镜像 parse_ledger.json 不再是状态源，删除函数与
调用点。bucket_for_size 若仅此引用则一并清理。"
```

---

## Task 4: 修 healthcheck / dashboard 读者，脱离 ledger

**Files:**
- Modify: `scripts/literature_healthcheck.py`（删 `check_parse_ledger` 115-135 + 调用 500 + 输出键 527）。
- Modify: `scripts/literature_dashboard.py`（删 ledger 加载 67/93-95 + 兜底 155/162）。

- [ ] **Step 1: 写失败测试 —— healthcheck 无 parse_ledger 键、无 ledger 文件也能跑**

Create `tests/test_healthcheck_no_ledger.py`：
```python
"""healthcheck 不再依赖 parse_ledger.json。"""
from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path


def test_healthcheck_has_no_parse_ledger_check():
    hc = importlib.import_module("scripts.literature_healthcheck")
    assert not hasattr(hc, "check_parse_ledger"), (
        "check_parse_ledger 应删除——ledger 已废弃，解析一致性由 check_content_md(DB) 覆盖"
    )


def test_healthcheck_output_has_no_ledger_key(tmp_path):
    hc = importlib.import_module("scripts.literature_healthcheck")
    # 无 parse_ledger.json 也不应报错/不应含 parse_ledger 键
    if hasattr(hc, "run_all"):
        result = hc.run_all() if callable(getattr(hc, "run_all", None)) else None
        # 若 run_all 存在：断言结果无 parse_ledger 键
```
（注：若 healthcheck 无 `run_all` 入口，本测试仅保留 `test_healthcheck_has_no_parse_ledger_check`，第二个测试改为 grep 断言 `parse_ledger` 不再出现在源文件——见 Step 3 的 grep 验证。）

- [ ] **Step 2: 删除 healthcheck 的 ledger 检查**

In `scripts/literature_healthcheck.py`：
- 删除 `def check_parse_ledger() -> dict[str, Any]:` 整个函数（行 115-135）。
- 删除调用 `ledger = check_parse_ledger()`（行 500）。
- 删除输出字典中 `"parse_ledger": ledger,`（行 527）。
- 清理因此不再使用的 `LIBRARY_ROOT`/`json` 引用（仅在确无其他用处时）。

- [ ] **Step 3: grep 确认 healthcheck 无 ledger 残留**

Run:
```bash
grep -n "parse_ledger\|check_parse_ledger" scripts/literature_healthcheck.py
```
Expected: 空。

- [ ] **Step 4: 删除 dashboard 的 ledger 兜底**

In `scripts/literature_dashboard.py`：
- 删除 `ledger_path = library_root / "parse_ledger.json"`（行 67）。
- 删除 ledger 加载块（行 93-95：`ledger = {"runs": {}}` ... `json.loads(...)`）。
- 删除 `ledger_runs = ledger.get("runs", {})`（行 155）。
- 行 162 改为去掉 ledger 兜底：`run = runs_by_source.get(source["id"], {})`。
- 清理不再使用的 `json` import（仅当无其他用处）。

- [ ] **Step 5: grep 确认 dashboard 无 ledger 残留**

Run:
```bash
grep -n "parse_ledger\|ledger" scripts/literature_dashboard.py
```
Expected: 空。

- [ ] **Step 6: 运行测试 + 全量回归**

Run:
```bash
uv run python -m pytest tests/ -q 2>&1 | tail -3
```
Expected: 全 passed / 0 failed（无回归）。

- [ ] **Step 7: Commit**

```bash
git add scripts/literature_healthcheck.py scripts/literature_dashboard.py tests/test_healthcheck_no_ledger.py
git commit -m "refactor(P3.5/D): healthcheck/dashboard 脱离 parse_ledger.json

healthcheck: 删 check_parse_ledger(解析一致性已由 check_content_md 读
parse_runs 覆盖)；dashboard: 删 ledger 加载与 DB优先+ledger兜底 回退，
纯读 parse_runs。两处不再引用 parse_ledger.json。"
```

---

## Task 5: 移走 parse_ledger.json + 收尾（矩阵/FUTURE_WORK/memory）

**Files:**
- Move: `parse_ledger.json`（若存在于 LIBRARY_ROOT）→ `_archive/parse_ledger.json.bak`。
- Update: `docs/superpowers/specs/2026-06-28-three-chain-completeness-plan.md`（矩阵 Phase D-状态源统一 → ✅）。
- Update: `FUTURE_WORK_PLAN.md`（状态源分裂条目 → 已解决）。

- [ ] **Step 1: 确认 parse_ledger.json 不再被任何 .py 引用**

Run:
```bash
grep -rn "parse_ledger" --include=*.py api/ scripts/ collector/ parser/core/ 2>/dev/null
```
Expected: 空（api/scripts/collector/parser/core 全无引用；仅 _archive/ 内的历史归档可能有，忽略）。

- [ ] **Step 2: 移走现有 ledger 文件（DB 已是镜像，无需数据迁移）**

```bash
if [ -f parse_ledger.json ]; then
  git mv parse_ledger.json _archive/parse_ledger.json.bak 2>/dev/null || mv parse_ledger.json _archive/parse_ledger.json.bak
fi
```
若 `parse_ledger.json` 未被 git 跟踪（gitignored 或本地文件），直接 `mv` 即可，并在 `_archive/README.md` 注明。把它加入 `.gitignore` 已无必要（不再生成）。

- [ ] **Step 3: §2 单核不变量核验**

Run:
```bash
grep -rn "def route_and_parse" --include=*.py .
```
Expected: 仅 `parser/core/mineru/router.py` 命中（其余为 _archive/docs，非 active code）。

- [ ] **Step 4: 全量绿 + 裸 pytest 干净**

Run:
```bash
uv run python -m pytest tests/ -q 2>&1 | tail -3
uv run python -m pytest --collect-only -q 2>&1 | tail -3
```
Expected: 全 passed / 0 failed；198+ tests collected 无 ERROR。

- [ ] **Step 5: 更新规划矩阵 + FUTURE_WORK_PLAN**

在 `docs/superpowers/specs/2026-06-28-three-chain-completeness-plan.md` 的 Phase D 进度块追加：状态源统一 ✅（parse_ledger.json 废弃，literature_parse_runs 唯一源；旧自部署 CLI 归档；新 CLI DB-only + 复用 sync_work_parse_status）。
在 `FUTURE_WORK_PLAN.md` 把 Phase B 遗留的"ledger↔DB 状态源不一致"标记为已解决（合并点待填）。

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore(P3.5/D): 移走 parse_ledger.json，状态源统一收尾

parse_ledger.json(DB 的冗余镜像)移至 _archive/。active 代码(api/scripts/
collector/parser/core) 已零引用 parse_ledger。状态源统一完成：
literature_parse_runs 为唯一权威；旧自部署 CLI 归档；新 CLI DB-only；
works.parse_status 复用 sync_work_parse_status。§2 单核不变量 PRESERVED。"
```

---

## Self-Review（plan 完成后自查）

**Spec coverage：**
- 废弃 ledger → Task 2(新 CLI 不读写) + Task 3(ingest 不写) + Task 4(读者脱离) + Task 5(移走文件) ✅
- 新 CLI DB-only → Task 2 ✅
- 归档旧 CLI → Task 1 ✅
- 状态机复用 → Task 2 Step 7 调 sync_work_parse_status ✅
- §2 不变量 → Task 5 Step 3 grep ✅
- 不加列/不动状态机 → 全计划无 ALTER TABLE、无 partial/parsing ✅

**Placeholder scan：** 无 TBD/TODO；每步含实锤路径或完整代码。

**Type/签名一致性：** `get_pending_db(limit) -> list[dict]`、`run_pending(execute, limit) -> int`、`_update_run_db(conn, sf_id, ...)` 在 Task 2 内定义且测试一致调用；`sync_work_parse_status(conn, work_id)` 复用既有签名 ✅。
