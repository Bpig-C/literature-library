# Phase B — 解析触发与状态（API+UI）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给已合并但仅 CLI 可用的 parser（P3.5）补齐 API + UI 两条链，让人能在浏览器走完：晋升后的 work（pending）→ UI 触发解析 → `content.md` 落地 → `literature_parse_runs.content_md_path` 更新、`parse_status` 翻 succeeded。

**Architecture:** 单核三适配器。把现在埋在 `scripts/literature_batch_parse.py` 里的 D13 路由 `route_and_parse` 提升为唯一权威核 `parser/core/mineru/router.py`；CLI 脚本与新建的 `api/routes/parse.py` 都薄委托它。API 路由基于 `api.db.get_conn`（可打桩），状态读写键控 `literature_parse_runs`（DB，非 ledger 文件）。触发用同步串行（与 CLI nucleus 一致）。前端在 `WorkDetail.vue` 加触发按钮 + 调新端点。

**Tech Stack:** FastAPI + SQLite + Vue3（naive-ui）+ uv；pytest（`uv run python -m pytest tests/`，**不可**裸 pytest）；parser 核心 `parser/core/mineru/*`（`parse_pdf(req)->(bool,str)` 契约）。

---

## 前置：4 个 Flag 的处置（写代码前先读）

这 4 个 flag 已在 brainstorm 阶段核实并入本 plan，实施时按此处置：

**Flag 1（language 不在 parse_runs）。** `literature_parse_runs` 无 `language` 列。`list_pending_runs` 用 `LEFT JOIN works` 取 `works.language` **原值**；ch/en 映射逻辑随 `route_and_parse` 进 `router.py`（消费者侧，映射属 nucleus），不在两处重复。

**Flag 2（同名两文件 + 单核范围）。** nucleus 来源 = **仓库根** `scripts/literature_batch_parse.py`（`route_and_parse`/`PyMuPDFClient_quality_ok`/`work_language` 的真正出处）。
- **更正（与最初假设冲突，以 git 为准）：** 该根脚本 `git ls-files` 确认**已被跟踪**（commit `e479801`），**不是未跟踪**。故提升 router 到 core 时，唯一需要 `git add` 的是**新建**的 `parser/core/mineru/router.py`；根脚本本身已在 VCS。
- `parser/scripts/literature_batch_parse.py`（已跟踪，较老的批量队列/Agent-API 版）= 遗留，**本次 out of scope**，记入 Phase D 清理/归档候选（见 Task 11）。本次不改它。

**Flag 3（先导脚本，别重复造）。** `scripts/_phase_b_trial.py`（`scripts/_*.py` 被 gitignore，故 `git status` 不可见）已是本 phase 原型。已从中抢救契约：(1) run 行 `id` 格式 = `LPR-{source_file_id}`，sf_id 用 `id.replace("LPR-","")` 恢复；(2) per-work 取行 `ORDER BY id LIMIT 1`；(3) `content_md_path` 对部分行已填充。**不复制**它的隔离目录 `_cloud_trial/` 与 `backend="pipeline"`（已弃用）。按治理移入 `scripts/_archive/`（Task 10）。

**Flag 4（works.parse_status 同步别造第三套）。** `scripts/migrate_sync_parse_status.py` 已实现 `works.parse_status ↔ parse_runs.status` 同步（单向保守：只 pending/其他→succeeded，永不回退）。本 plan 抽出可复用 helper `sync_work_parse_status(conn, work_id)`，路由**委托**它，不写第三套同步。

---

## File Structure

**Create:**
- `parser/core/mineru/router.py` — 唯一 D13 路由核：`route_and_parse(...)` + `_quality_ok(...)` + `map_mineru_language(raw)`。**parser-core import 全部惰性（函数内）**，确保 `from core.mineru.router import route_and_parse` 不触发 fitz。
- `api/routes/parse.py` — 薄适配器：`POST /parse/trigger`、`GET /parse/status` + `get_conn` 版 DB 辅助 + 单点委托 `_run_parse`。
- `tests/test_parse_api.py` — 临时 DB 副本 + patch `get_conn`/`LIBRARY_ROOT`/`_run_parse`；不碰真网络/fitz。

**Modify:**
- `scripts/literature_batch_parse.py` — 删本地 `route_and_parse`/`PyMuPDFClient_quality_ok`，改 `from core.mineru.router import route_and_parse, map_mineru_language`；`work_language` 降为只读 DB 原值（映射交 router）。CLI 行为不变。
- `scripts/migrate_sync_parse_status.py` — 新增 `sync_work_parse_status(conn, work_id)` helper，`main()` 经它落地（行为不变）。
- `api/main.py` — import `parse` + `app.include_router(parse.router, prefix="/api")`。
- `web/src/api.js` — 加 `parseTrigger()`、`parseStatus()`。
- `web/src/views/WorkDetail.vue` — 「解析状态」行加「触发解析」按钮 + 调用/刷新。
- `web/src/router.js` + `web/src/views/Parse.vue`（可选，Task 9）。

**Move (governance):**
- `scripts/_phase_b_trial.py` → `scripts/_archive/_phase_b_trial.py`（仍 gitignored）。

---

## Task 1: 提升 D13 路由到 `parser/core/mineru/router.py`（单核）

**Files:**
- Create: `parser/core/mineru/router.py`
- Reference: `scripts/literature_batch_parse.py:104-152`（搬移源）

- [ ] **Step 1: 创建 `parser/core/mineru/router.py`**

```python
"""D13 二元路由核（唯一权威）。从 scripts/literature_batch_parse.py 提升。

路由策略（pipeline 弃用）：
- 文本层 PDF（born-digital）→ PyMuPDF 本地直抽；质检不合格 → 回退 cloud vlm。
- 扫描型 PDF（无文本层）→ cloud vlm。

单核约束：CLI/API/UI 都调本模块的 route_and_parse，不再各自实现路由。
import 安全：parser-core 子模块全部惰性导入（函数内），保证
`from core.mineru.router import route_and_parse` 不触发 fitz/网络。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def map_mineru_language(raw: str) -> str:
    """works.language 原值 → MinerU language 取值（ch/en/...）。

    消费者侧映射属 nucleus：CLI/API 只传 works.language 原值，统一在此映射。
    幂等：对自身输出再映射结果不变。缺失/未知 → en。
    """
    lang = (raw or "").strip().lower()
    if lang in ("", "unknown"):
        return "en"
    if lang.startswith("zh") or lang in ("chinese", "中文"):
        return "ch"
    if lang.startswith("en") or lang in ("english",):
        return "en"
    return lang[:2]


def _quality_ok(pymupdf_client: Any) -> bool:
    """薄封装，避免顶层 import 循环。"""
    from core.mineru.pymupdf_client import PyMuPDFClient  # noqa: PLC0415（惰性）
    return PyMuPDFClient.quality_ok(getattr(pymupdf_client, "last_metrics", {}))


def route_and_parse(
    cloud_client: Any,
    pymupdf_client: Any,
    source_path: str,
    output_dir: Path,
    language: str,
) -> tuple[bool, str, str]:
    """二元路由（D13）。language 取 works.language 原值，内部经 map_mineru_language 映射。

    返回 (ok, msg, backend_used ∈ {"pymupdf","vlm"})。pipeline 不再使用。
    """
    from core.mineru.base_client import ParseRequest  # noqa: PLC0415（惰性）
    from core.mineru.pymupdf_client import has_text_layer  # noqa: PLC0415（惰性）

    pdf_path = Path(source_path)
    lang = map_mineru_language(language)

    def _cloud_vlm() -> tuple[bool, str]:
        req = ParseRequest(
            pdf_path=pdf_path,
            output_dir=Path(output_dir),
            backend="vlm",
            lang_list=lang,
            formula_enable=True,
            table_enable=True,
        )
        return cloud_client.parse_pdf(req)

    # 1) 文本层 → PyMuPDF
    if has_text_layer(pdf_path):
        ok, msg = pymupdf_client.parse_pdf(
            ParseRequest(pdf_path=pdf_path, output_dir=Path(output_dir))
        )
        if ok and _quality_ok(pymupdf_client):
            return True, msg, "pymupdf"
        print(f"  PyMuPDF 质检不合格({pymupdf_client.last_metrics})，回退 cloud vlm")
        ok2, msg2 = _cloud_vlm()
        return ok2, msg2, "vlm"

    # 2) 扫描型 → cloud vlm
    ok, msg = _cloud_vlm()
    return ok, msg, "vlm"
```

- [ ] **Step 2: 验证 import 安全（不触发 fitz）**

Run:
```bash
cd D:\02_academic\doctoral\literature_library
uv run python -c "import sys; sys.path.insert(0,'parser'); from core.mineru.router import route_and_parse, map_mineru_language; print('import OK', map_mineru_language('chinese'), map_mineru_language(''), map_mineru_language('Japanese'))"
```
Expected: `import OK ch en ja`（不报 `ModuleNotFoundError: fitz`）。

- [ ] **Step 3: Commit**

```bash
git add parser/core/mineru/router.py
git commit -m "feat(P3.5/B): 提升 D13 路由 route_and_parse 到 parser/core/mineru/router.py 为唯一核

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: 薄化 CLI 脚本（委托新核）

**Files:**
- Modify: `scripts/literature_batch_parse.py`（删 `route_and_parse`、`PyMuPDFClient_quality_ok`；改 `work_language` 为只读原值；`main()` 内调用适配）

- [ ] **Step 1: 用 import 替换本地定义**

在 `scripts/literature_batch_parse.py` 中，删除整段 `def route_and_parse(...)`（约 104-146 行）与 `def PyMuPDFClient_quality_ok(...)`（约 149-152 行）。在文件顶部 import 区（`PARSER_ROOT` sys.path 注入之后）加：

```python
from core.mineru.router import route_and_parse, map_mineru_language  # noqa: E402
```

- [ ] **Step 2: 把 `work_language` 改为只读原值**

将 `work_language` 函数体替换为只从 DB 读 `works.language` 原值（删去 ch/en 映射分支，映射已交 router）：

```python
def work_language(work_id: str) -> str:
    """从 works 表取 literature 语言原值（映射由 router.map_mineru_language 负责）。"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        try:
            row = conn.execute("SELECT language FROM works WHERE id=?", (work_id,)).fetchone()
            return (row[0] if row else "") or ""
        finally:
            conn.close()
    except Exception:
        return ""
```

`main()` 中 `language = work_language(run.get("work_id", ""))` 一行**保持不变**——`route_and_parse` 现在内部会映射。无需其它改动。

- [ ] **Step 3: CLI 冒烟（dry-run，不耗额度）**

Run:
```bash
uv run python scripts/literature_batch_parse.py
```
Expected: 打印 pending 列表（来自 `parse_ledger.json`）或 `No pending parse tasks.`，**无** `NameError: route_and_parse` / `import error`。

- [ ] **Step 4: Commit**

```bash
git add scripts/literature_batch_parse.py
git commit -m "refactor(P3.5/B): CLI 脚本薄化——route_and_parse 改委托 core.mineru.router

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: 抽出 `sync_work_parse_status` 可复用 helper（Flag 4）

**Files:**
- Modify: `scripts/migrate_sync_parse_status.py`

- [ ] **Step 1: 加 helper 并让 main() 复用**

在 `find_desynced` 之后、`main` 之前插入：

```python
def sync_work_parse_status(conn: sqlite3.Connection, work_id: str) -> str:
    """按 literature_parse_runs 重算单个 work 的 works.parse_status。

    保守：succeeded 是粘性的（曾有 succeeded 且 content_md_path 非空的 run → 保持 succeeded）；
    全部 failed → failed；否则 pending。返回写入的状态值。
    """
    runs = conn.execute(
        "SELECT status, content_md_path FROM literature_parse_runs WHERE work_id=?",
        (work_id,),
    ).fetchall()
    has_succeeded = any(
        r[0] == "succeeded" and (r[1] or "") for r in runs
    )
    all_failed = bool(runs) and all(r[0] == "failed" for r in runs)
    new = "succeeded" if has_succeeded else ("failed" if all_failed else "pending")
    conn.execute(
        "UPDATE works SET parse_status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (new, work_id),
    )
    return new
```

把 `main()` 中 `--apply` 分支的逐条 UPDATE（`conn.execute("UPDATE works SET parse_status='succeeded'...")`）替换为调用 helper：

```python
        for wid, _ in rows:
            sync_work_parse_status(conn, wid)
            changed += 1
```
（`find_desynced` 仍只筛「应升 succeeded」的 work，故 helper 对这些 work 必算出 `succeeded`，行为与旧版一致。）

- [ ] **Step 2: migrate 冒烟（dry-run，幂等）**

Run:
```bash
uv run python scripts/migrate_sync_parse_status.py
```
Expected: 打印 `需同步的 work 数：N（DRY-RUN）`，无异常。

- [ ] **Step 3: Commit**

```bash
git add scripts/migrate_sync_parse_status.py
git commit -m "refactor(P3.5/B): 抽 sync_work_parse_status helper 供 API 路由复用（Flag 4）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: TDD — `api/routes/parse.py` 读路径（list_pending_runs + status）

**Files:**
- Create: `tests/test_parse_api.py`
- Create: `api/routes/parse.py`

- [ ] **Step 1: 写失败测试（test_parse_api.py 骨架 + status 用例）**

```python
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


@pytest.fixture(autouse=True, scope="session")
def _seed():
    conn = _test_get_conn()
    now = "2026-06-28T00:00:00"
    # 两个合成 work，避开真实 work_id
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
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run python -m pytest tests/test_parse_api.py -v`
Expected: FAIL（`api.routes.parse` 不存在 / 路由 404）。

- [ ] **Step 3: 写 `api/routes/parse.py`（读路径 + 骨架）**

```python
"""Parse trigger/status API routes. Thin adapter over the parser nucleus.

单核：本模块不写解析路由逻辑——触发委托 core.mineru.router.route_and_parse（经
_run_parse 单点）；works.parse_status 同步委托 scripts.migrate_sync_parse_status。
状态读写键控 literature_parse_runs（DB，非 ledger 文件）。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import get_conn, LIBRARY_ROOT

# 让 parser 子项目（core.mineru.*）可导入。与 scripts/ 约定一致。
_PARSER_ROOT = LIBRARY_ROOT / "parser"
if str(_PARSER_ROOT) not in sys.path:
    sys.path.insert(0, str(_PARSER_ROOT))

from core.mineru.router import route_and_parse  # noqa: E402（惰性 import，不触发 fitz）

# works.parse_status 同步 helper（Flag 4：复用既有同步逻辑，不造第三套）
from scripts.migrate_sync_parse_status import sync_work_parse_status  # noqa: E402

router = APIRouter()


def _run_output_dir(run_work_id: str, source_file_id: str) -> Path:
    """契约输出目录（绝对）：{LIBRARY_ROOT}/works/{work_id}/parsed/mineru/{sfid}。"""
    return Path(LIBRARY_ROOT) / "works" / run_work_id / "parsed" / "mineru" / source_file_id


def _row_to_pending(d: dict) -> dict:
    """规整一行 parse_run → 触发所需的字段集；output_dir 缺失则按契约重算。"""
    sf_id = (d.get("id") or "").replace("LPR-", "") or d.get("source_file_id", "")
    out_dir = d.get("output_dir") or str(_run_output_dir(d["work_id"], sf_id))
    return {
        "run_id": d.get("id"),
        "source_file_id": sf_id,
        "work_id": d["work_id"],
        "source_path": d["source_path"],
        "output_dir": out_dir,
        "language": d.get("language") or "",  # works.language 原值（LEFT JOIN 带出）
    }


def list_pending_runs(conn, work_ids: list[str] | None = None) -> list[dict]:
    where = ["pr.status = 'pending'"]
    params: list = []
    if work_ids:
        where.append(f"pr.work_id IN ({','.join('?' * len(work_ids))})")
        params.extend(work_ids)
    rows = conn.execute(
        f"""SELECT pr.id, pr.work_id, pr.source_file_id, pr.source_path, pr.output_dir,
                  w.language AS language
           FROM literature_parse_runs pr
           LEFT JOIN works w ON w.id = pr.work_id
           WHERE {' AND '.join(where)}
           ORDER BY pr.id""",
        params,
    ).fetchall()
    return [_row_to_pending(dict(r)) for r in rows]


@router.get("/parse/status")
def parse_status(work_id: str | None = None):
    conn = get_conn()
    try:
        if work_id:
            row = conn.execute(
                """SELECT pr.work_id, pr.status, pr.content_md_path, pr.backend,
                          pr.error, pr.finished_at
                   FROM literature_parse_runs pr
                   WHERE pr.work_id=? ORDER BY pr.id LIMIT 1""",
                (work_id,),
            ).fetchone()
            if not row:
                raise HTTPException(404, f"no parse_run for work {work_id}")
            d = dict(row)
            return {"work": d}
        # 汇总
        counts = {"pending": 0, "succeeded": 0, "failed": 0}
        total = 0
        for r in conn.execute(
            "SELECT status, COUNT(*) n FROM literature_parse_runs GROUP BY status"
        ).fetchall():
            counts[r["status"]] = counts.get(r["status"], 0) + r["n"]
            total += r["n"]
        return {"total": total, **counts}
    finally:
        conn.close()
```

- [ ] **Step 4: 挂载路由（否则 404）**

修改 `api/main.py`：import 行加 `parse`（`from .routes import duplicates, files, intake, metadata, parse, relations, works, classification`），include 区加 `app.include_router(parse.router, prefix="/api")`。

- [ ] **Step 5: 运行，确认两条用例通过**

Run: `uv run python -m pytest tests/test_parse_api.py -v`
Expected: `test_status_aggregate_counts`、`test_status_single_work` PASS。

- [ ] **Step 6: Commit**

```bash
git add api/routes/parse.py api/main.py tests/test_parse_api.py
git commit -m "feat(P3.5/B): GET /api/parse/status + parse 路由挂载（读路径，TDD）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: TDD — `POST /api/parse/trigger`（写路径，委托 nucleus）

**Files:**
- Modify: `api/routes/parse.py`
- Modify: `tests/test_parse_api.py`（追加用例）

- [ ] **Step 1: 追加失败测试（trigger 用例）**

追加到 `tests/test_parse_api.py`：

```python
def test_trigger_success_updates_run_and_status(monkeypatch):
    import api.routes.parse as parse
    seen = {}
    def fake_run(source_path, output_dir, language):
        seen.update(source_path=source_path, language=language)
        out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
        (out / "content.md").write_text("# stub md", encoding="utf-8")
        return True, "ok", "pymupdf"
    monkeypatch.setattr(parse, "_run_parse", fake_run)
    r = client.post("/api/parse/trigger", json={"work_ids": ["W-parse-test-1"]})
    assert r.status_code == 200
    body = r.json()
    assert body["triggered"] == 1 and body["succeeded"] == 1 and body["failed"] == 0
    res = body["results"][0]
    assert res["status"] == "succeeded" and res["backend"] == "pymupdf"
    assert res["content_md_path"].endswith("content.md")
    # DB 真的写了
    conn = _test_get_conn()
    row = conn.execute(
        "SELECT status, content_md_path, backend FROM literature_parse_runs WHERE id='LPR-SF-1'"
    ).fetchone(); conn.close()
    assert row["status"] == "succeeded"
    assert (row["content_md_path"] or "").endswith("content.md")
    assert row["backend"] == "pymupdf"


def test_trigger_failure_does_not_abort_batch(monkeypatch):
    import api.routes.parse as parse
    calls = {"n": 0}
    def fake_run(source_path, output_dir, language):
        calls["n"] += 1
        return (False, "boom", "vlm") if calls["n"] == 1 else (True, "ok", "pymupdf")
    monkeypatch.setattr(parse, "_run_parse", fake_run)
    r = client.post("/api/parse/trigger", json={"all_pending": True})
    assert r.status_code == 200
    body = r.json()
    assert body["failed"] >= 1 and body["succeeded"] >= 1  # 单条失败不中断


def test_trigger_no_pending_400():
    # 两行已被前两个用例改成 succeeded/failed？用显式不存在的 work_id 触发空集
    r = client.post("/api/parse/trigger", json={"work_ids": ["W-nope-not-exist"]})
    assert r.status_code == 400


def test_trigger_empty_body_400():
    r = client.post("/api/parse/trigger", json={})
    assert r.status_code == 400
```

> 注：`test_trigger_failure_does_not_abort_batch` 依赖 `W-parse-test-2` 仍 pending。若测试顺序导致 test-1 已被成功用例消费，`all_pending` 仍会拿到 test-2；用例只断言 `failed>=1 and succeeded>=1`，对集合大小不敏感。若 pytest 顺序问题导致不稳定，把两个 work 的 seed 放到 function-scoped fixture（每个用例重建）。先按 session seed 跑；脆则改 function-scoped。

- [ ] **Step 2: 运行，确认失败**

Run: `uv run python -m pytest tests/test_parse_api.py -v`
Expected: 新 trigger 用例 FAIL（`_run_parse` 不存在 / 路由未实现）。

- [ ] **Step 3: 实现 trigger + `_run_parse`**

在 `api/routes/parse.py` 追加：

```python
class TriggerBody(BaseModel):
    work_ids: list[str] | None = None
    all_pending: bool = False
    backend: str | None = None  # 可选覆盖；默认 D13 自动


def _load_env_file() -> None:
    env = Path(LIBRARY_ROOT) / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def _run_parse(source_path: str, output_dir, language: str) -> tuple[bool, str, str]:
    """单点委托 nucleus：惰性构造 client + 调 route_and_parse。

    生产路径：.env 已载入 → CloudClient/PyMuPDFClient 真构造。测试通过 patch
    api.routes.parse._run_parse 替换整段，永不触达 fitz/网络。
    """
    _load_env_file()
    from core.mineru.cloud_client import CloudClient  # noqa: PLC0415（惰性）
    from core.mineru.pymupdf_client import PyMuPDFClient  # noqa: PLC0415（惰性）
    cloud = CloudClient()
    pymupdf = PyMuPDFClient()
    return route_and_parse(cloud, pymupdf, source_path, Path(output_dir), language)


def _update_run(conn, run: dict, status: str, *, content_md_path: str = "",
                backend: str = "", task_id: str = "", error: str = "") -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """UPDATE literature_parse_runs
           SET status=?, task_id=?, finished_at=?, error=?,
               content_md_path=?, backend=? WHERE id=?""",
        (status, task_id, now, error, content_md_path, backend, run["run_id"]),
    )
    sync_work_parse_status(conn, run["work_id"])  # Flag 4：委托既有同步


@router.post("/parse/trigger")
def parse_trigger(body: TriggerBody):
    if not body.work_ids and not body.all_pending:
        raise HTTPException(400, "provide work_ids or set all_pending=true")
    conn = get_conn()
    try:
        pending = list_pending_runs(conn, body.work_ids if body.work_ids else None)
        if not pending:
            raise HTTPException(400, "no pending parse runs for the given selector")
        results, succ, fail = [], 0, 0
        for run in pending:  # 同步串行（与 CLI nucleus 一致）
            try:
                ok, msg, backend_used = _run_parse(
                    run["source_path"], run["output_dir"], run["language"]
                )
                content_md = str(Path(run["output_dir"]) / "content.md")
                if ok:
                    _update_run(conn, run, "succeeded",
                                content_md_path=content_md, backend=backend_used,
                                task_id="")
                    results.append({"work_id": run["work_id"], "source_file_id": run["source_file_id"],
                                    "status": "succeeded", "backend": backend_used,
                                    "content_md_path": content_md, "error": ""})
                    succ += 1
                else:
                    _update_run(conn, run, "failed", backend=backend_used, error=msg)
                    results.append({"work_id": run["work_id"], "source_file_id": run["source_file_id"],
                                    "status": "failed", "backend": backend_used,
                                    "content_md_path": "", "error": msg})
                    fail += 1
            except Exception as e:  # noqa: BLE001 — 批次不中断
                _update_run(conn, run, "failed", error=str(e))
                results.append({"work_id": run["work_id"], "source_file_id": run["source_file_id"],
                                "status": "failed", "backend": "", "content_md_path": "",
                                "error": str(e)})
                fail += 1
        conn.commit()
        return {"triggered": len(results), "succeeded": succ, "failed": fail, "results": results}
    finally:
        conn.close()
```

> `body.backend` 覆盖暂不在 v1 路由里强制注入（`route_and_parse` 走 D13 自动）。保留字段以向前兼容；若需硬覆盖，后续在 `_run_parse` 增加 backend 参数。这是有意 YAGNI，不扩边界。

- [ ] **Step 4: 运行，确认全绿**

Run: `uv run python -m pytest tests/test_parse_api.py -v`
Expected: 6 用例全 PASS。若 `test_trigger_failure_does_not_abort_batch` 因测试顺序脆，把 `_seed` 改 function-scoped（每用例重建两 pending 行）。

- [ ] **Step 5: 全量回归**

Run: `uv run python -m pytest tests/ -q`
Expected: 全绿（≥ 既有基线 + 新 6 条），**无** fitz/import 报错。

- [ ] **Step 6: Commit**

```bash
git add api/routes/parse.py tests/test_parse_api.py
git commit -m "feat(P3.5/B): POST /api/parse/trigger 同步串行委托 nucleus + 单点 _run_parse（TDD）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: 前端 — api.js 封装 + WorkDetail 触发按钮

**Files:**
- Modify: `web/src/api.js`
- Modify: `web/src/views/WorkDetail.vue`（「解析状态」行，约 115 行）

- [ ] **Step 1: api.js 加封装**

在 `web/src/api.js` 末尾追加：

```javascript
export function parseTrigger(payload) {
  return request('/parse/trigger', { method: 'POST', body: JSON.stringify(payload) })
}

export function parseStatus(workId) {
  return request(`/parse/status${workId ? '?work_id=' + encodeURIComponent(workId) : ''}`)
}
```

- [ ] **Step 2: WorkDetail.vue 加触发按钮 + 处理函数**

`WorkDetail.vue` 现有行（约 115 行）：
```html
<div>解析状态</div><div :class="'status-' + work.parse_status">{{ label(PARSE_STATUS_LABELS, work.parse_status) }}</div>
```
在该 `<div>` 之后追加一个触发按钮（同一网格语境内，用 `<n-button>`，与文件已有 naive-ui 用法一致）：

```html
<n-button size="small" quaternary :loading="parseLoading"
          :disabled="work.parse_status === 'succeeded'"
          @click="triggerParse">触发解析</n-button>
```

`<script setup>` 中：
- import 行追加 `parseTrigger`：
```javascript
import { getWorks, getWork, updateWork, createRelation, deleteRelation, quarantineWork, restoreWork, contentUrl, pdfUrl, getTags, createTag, deleteTag, parseTrigger } from '../api'
```
- 在其它 `ref` 声明附近加：
```javascript
const parseLoading = ref(false)
async function triggerParse() {
  parseLoading.value = true
  try {
    const res = await parseTrigger({ work_ids: [props.id] })
    const r = (res.results || [])[0] || {}
    message.success(`解析：${r.status || '?'}${r.backend ? ' (' + r.backend + ')' : ''}`)
    work.value = await getWork(props.id)  // 刷新 parse_status
  } catch (e) {
    message.error('触发解析失败：' + e.message)
  } finally {
    parseLoading.value = false
  }
}
```

- [ ] **Step 3: 前端构建冒烟**

Run: `cd web && npx vite build`
Expected: 构建通过，无 `parseTrigger` undefined / 模板编译错误。

- [ ] **Step 4: Commit**

```bash
git add web/src/api.js web/src/views/WorkDetail.vue
git commit -m "feat(P3.5/B): WorkDetail 加「触发解析」按钮 + api.js parseTrigger/parseStatus

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7（可选）: Parse 概览页（仿 IntakeReview）

> 优先级低于后端契约。时间允许再做；否则延后到 Phase D，不阻塞交付。

**Files:**
- Create: `web/src/views/Parse.vue`
- Modify: `web/src/router.js`、`web/src/App.vue`（侧边栏入口，如有）

- [ ] **Step 1:** 仿 `IntakeReview.vue` 结构：顶部用 `parseStatus()` 显示 pending/succeeded/failed 计数 + 「全部触发」按钮调 `parseTrigger({all_pending:true})`；列表展示 pending works（需后端补一个 list 端点或复用 `getWorks` 按 parse_status=pending 过滤）。
- [ ] **Step 2:** `router.js` 加 `{ path: '/parse', component: Parse }` + import。
- [ ] **Step 3:** 侧边栏加入口（参照现有 AppLayout 链接写法）。
- [ ] **Step 4:** `npx vite build` 通过；commit。

> 若不做，在交付说明里显式记「Parse 概览页延后」。

---

## Task 8: 三链 smoke + 真解析 smoke（诚实记录）

**Files:** 无代码改动；产出 smoke 记录。

- [ ] **Step 1: 真 API 契约 smoke（桩）已由测试覆盖** —— Task 4/5 的 `test_parse_api.py` 即 trigger→content.md 落地→content_md_path 更新的桩验证。

- [ ] **Step 2: 三链一致 smoke（同一动作：触发 W-arxiv-2506.19248 解析）**

前置确认：`literature_parse_runs` 里该 work 有一行 `status='pending'`（Phase A 接力点）。
- **CLI 链**：`uv run python scripts/literature_batch_parse.py --execute --limit 1`
  - ⚠️ **已知状态来源不一致（Flag）：** CLI 读 `parse_ledger.json`，API 读 `literature_parse_runs`。若 ledger 无该 work 条目，CLI 链 smoke 需先确认 ledger 同步，或显式声明「CLI 链以 ledger 为准、本次仅验 API+UI 两链」。把不一致记入交付说明 + Phase D 跟踪项，**不在本次修**。
- **curl 链**：启动 API（`uv run uvicorn api.main:app`）后：
  ```bash
  curl -X POST http://127.0.0.1:8000/api/parse/trigger -H 'Content-Type: application/json' -d '{"work_ids":["W-arxiv-2506.19248"]}'
  curl 'http://127.0.0.1:8000/api/parse/status?work_id=W-arxiv-2506.19248'
  ```
- **UI 链**：`cd web && npx vite`（或已起 dev server）→ WorkDetail 页点「触发解析」→ 看徽标翻 succeeded。
- 一致判据：三链任一执行后，`literature_parse_runs.content_md_path` 指向真实存在的 `content.md`，`status='succeeded'`，`works.parse_status='succeeded'`。

- [ ] **Step 3: 真 MinerU smoke 的诚实记录**

真解析需：(a) 联网；(b) `.env` 的 `MinerU_API_KEY`；(c) born-digital 走 PyMuPDF → **需运行环境装 fitz**（`uv add pymupdf` 或确认 parser venv 已装）；若该样本为扫描型则走 cloud vlm（不需 fitz，但耗额度+联网）。

- 若环境允许：跑 Step 2 curl 链，确认 content.md 真实落地（非桩）。把 `content.md` 字符数、backend、batch_id 记入交付说明。
- 若环境不允许（无网/无 token/无 fitz）：**显式记录「真解析 smoke 未跑；契约经 Task 4/5 桩验证」**，不得谎报成功。

- [ ] **Step 4: 把 smoke 结论写进交付说明**（见 Task 11 的合并说明）。

---

## Task 9: 自审 —— 全量测试 + 构建 + 单核未破

- [ ] **Step 1: 后端全绿**

Run: `uv run python -m pytest tests/ -q`
Expected: 全绿，无回归，无 fitz 收集错误。

- [ ] **Step 2: 前端构建**

Run: `cd web && npx vite build`
Expected: 通过。

- [ ] **Step 3: 单核未破自检**

确认全仓只有**一条** D13 路由实现：
```bash
grep -rn "def route_and_parse" --include=*.py .
```
Expected: 唯一命中 `parser/core/mineru/router.py`。`scripts/literature_batch_parse.py` 不再有该定义（只剩 import）。

- [ ] **Step 4: import 安全自检**

```bash
uv run python -c "import api.main; print('api.main OK — no fitz pulled at import')"
```
Expected: 打印 OK，无 fitz ModuleNotFoundError。

---

## Task 10: 治理 —— 归档先导脚本

**Files:**
- Move: `scripts/_phase_b_trial.py` → `scripts/_archive/_phase_b_trial.py`

- [ ] **Step 1:** 确认 `scripts/_archive/` 存在（不存在则建）。移动文件（两者均 `scripts/_*.py` → gitignored，不涉及 VCS）。
- [ ] **Step 2:** 同理评估 `scripts/_phase_c_validate.py`（Phase C 用，本次**不动**，留给 Phase C）。
- [ ] **Step 3:** 不需 commit（gitignored）；若 `git status` 仍显示，确认 `.gitignore` 覆盖 `scripts/_*/`。

---

## Task 11: 合并说明 + 更新规划矩阵

**Files:**
- Modify: `docs/FUTURE_WORK_PLAN.md`（P3.5 状态：parser CLI-only → API+UI 已补齐 Phase B）
- Modify: `docs/superpowers/specs/2026-06-28-three-chain-completeness-plan.md`（矩阵 parser-E/F 行打 ✅；§6 端态验收对应项）
- Reference: `MEMORY.md`（新增 Phase B 完成条目，仿 `phaseA-intake-review-done.md` 格式）

- [ ] **Step 1:** 写 Phase B 合并说明（含：交付的端点、单核提升、Flag 处置、smoke 结论含真解析是否跑了、已知遗留：CLI ledger vs DB 不一致 → Phase D、parser/scripts/ 旧版归档候选 → Phase D）。
- [ ] **Step 2:** 更新 `FUTURE_WORK_PLAN.md` P3.5 行 + 总体规划矩阵 parser-E（API trigger）/parser-F（UI）→ ✅。
- [ ] **Step 3:** 新增 memory 文件 `phaseB-parse-trigger-done.md` 并在 `MEMORY.md` 加一行指针。
- [ ] **Step 4:** 最终 commit + push（用户确认后）。

---

## 验收对照（总体规划 §4 Phase B + §6）

- [x] `POST /api/parse/trigger`（委托 nucleus，D13 路由，同步串行）— Task 5
- [x] `GET /api/parse/status`（汇总 + per-work + content_md_path）— Task 4
- [x] MinerU_API_KEY 从 .env 读（不打印/提交）— Task 5 `_load_env_file`
- [x] 每端点配测试（temp DB + patch get_conn + 桩 nucleus）— Task 4/5
- [x] 单核三适配器（router 提升为唯一核；CLI/API 薄委托）— Task 1/2/5
- [x] 输出契约不变（`works/{id}/parsed/mineru/{sfid}/content.md` + `content_md_path`）— Task 5
- [x] 向后兼容（既有路由/页面语义不动，只新增 + include_router）— Task 4
- [x] WorkDetail 触发按钮 — Task 6
- [ ] promote 后 UI 触发解析 → content.md 落地 → content_md_path 更新（真解析 smoke）— Task 8（环境允许时）

## 边界（不做）

- Phase B'（inbox-ingest）、C（topics/collect UI）、D（pytest testpaths / 端到端验收 / CLI ledger↔DB 统一）— 仅记跟踪项。
- 不改既有解析契约、不改 collector 链路、不改 `parser/scripts/literature_batch_parse.py`（遗留）。
