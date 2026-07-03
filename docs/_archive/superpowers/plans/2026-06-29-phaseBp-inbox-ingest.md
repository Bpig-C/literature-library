# Phase B' inbox 手动摄入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 仿 IntakeReview 做 inbox 手动摄入：`GET /api/ingest/plan`（dry-run 扫 `_inbox/`）→ `POST /api/ingest/execute` → `InboxReview.vue`。

**Architecture:** ingest nucleus（`scripts/literature_ingest.py` 的 `scan_inbox`/`build_ingest_plan`/`execute_plan`）已是纯逻辑、无 CLI/打印混入，API 路由做薄包装：plan 端点调 `build_ingest_plan(dry_run=True)` 预览、execute 端点调 `execute_plan`。不碰 nucleus 逻辑（§2 单核：API 是薄适配器）。ingest 直写 works（源可信，无候选闸门），dry-run 预览即人工关；与 collector 两路摄入经不同入口物理隔离。

**Tech Stack:** FastAPI / sqlite3 / Vue3 / pytest（function-scoped temp DB，仿 tests/test_intake_api.py；ingest nucleus 走 `connect_db` 非 `get_conn`，patch 目标不同）。

**硬约束（每任务必守）：**
1. §2 单核：API 路由零业务逻辑——只解析 body + 委托 `build_ingest_plan`/`execute_plan` + 整形返回。**不复制 nucleus 逻辑**。
2. 解析输出契约不变：ingest 建 `works/{work_id}/source/` + `literature_parse_runs` pending 行（Phase B 解析接力点），路径语义不动。
3. 测试纪律：每端点配测试；temp DB + 不触真网络（ingest 本就不触网络，只读本地 PDF 元数据 via pypdf）；不触达真 `_inbox/`（用 temp library_root）。
4. 向后兼容：既有路由/页面只新增不改语义。`scripts/literature_ingest.py` 的 nucleus 函数**不改签名/行为**（除非加可选参数且默认行为不变）。
5. 边界：ingest 直接写 works（不经 intake_candidates/ingest_bridge）；与 collector 互不混用。

**接力点实锤（来自调研）：**
- nucleus：`scripts/literature_ingest.py:473 scan_inbox(inbox_dir)->list[Path]`、`:479 build_ingest_plan(library_root,*,inbox_dir=None,limit=None,dry_run=True)->IngestPlan`、`:875 execute_plan(plan,*,no_backup=False,leave_inbox=False)->Path|None`。
- 数据结构：`IngestPlan`(`:83`) `.summary()`/`.as_dict()`；`IngestAction`(`:68`)；`DuplicateAction`(`:57`)。
- 范本：后端 `api/routes/intake.py`（薄适配器）；前端 `web/src/views/IntakeReview.vue`；API 测试 `tests/test_intake_api.py:32-52`（function-scoped patch）；ingest 单测 `tests/test_literature_ingest.py:18-42`（temp library 夹具）。
- 挂载点：`api/main.py:11` import + `:23-30` include_router；前端 `web/src/router.js`、`web/src/components/AppLayout.vue:29-31`（侧边栏）、`web/src/api.js`。
- **隔离坑**：nucleus 硬开 `library_root/"literature.sqlite"`（`build_ingest_plan:488`、`insert_db_rows:684`），不走 `api.db.get_conn`。API 端点传 `LIBRARY_ROOT`（真实生产路径）；测试用 temp library_root + monkeypatch `api.routes.ingest.LIBRARY_ROOT` 指向 temp 目录（nucleus 自然读 temp/literature.sqlite，无需 patch get_conn）。

---

## Task 1: 后端 `api/routes/ingest.py`（TDD）

**Files:**
- Create: `api/routes/ingest.py`
- Modify: `api/main.py`（import + include_router）
- Test: `tests/test_ingest_api.py`

- [ ] **Step 1: 写失败测试 —— plan 端点 dry-run 预览**

Create `tests/test_ingest_api.py`：
```python
"""inbox 摄入 API 测试。temp library_root（含 _inbox + literature.sqlite），
不触真网络。nucleus 走 connect_db，故 patch LIBRARY_ROOT 指向 temp 目录。"""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


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
    _make_pdf(tmp_path / "_inbox" / "sample.pdf")
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
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run python -m pytest tests/test_ingest_api.py -q`
Expected: FAIL（无 `/api/ingest/plan` 路由 → 404）。

- [ ] **Step 3: 实现 ingest 路由 + 挂载**

Create `api/routes/ingest.py`：
```python
"""Inbox 手动摄入 API。薄适配器——零业务逻辑，全委托 scripts.literature_ingest nucleus。

边界：ingest 直接写 works（源可信，不经候选闸门）；dry-run 预览即人工关。
与 collector 摄入（经 ingest_bridge/候选闸门）入口不同、互不混用。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import LIBRARY_ROOT

from scripts.literature_ingest import build_ingest_plan, execute_plan

router = APIRouter()


@router.get("/ingest/plan")
def ingest_plan(limit: int | None = None):
    """dry-run：扫 _inbox/ 预览摄入计划，不写盘。"""
    plan = build_ingest_plan(LIBRARY_ROOT, limit=limit, dry_run=True)
    d = plan.as_dict()
    return {"dry_run": True, "summary": d["summary"], "ingests": d["ingests"],
            "exact_duplicates": d["exact_duplicates"], "skipped": d["skipped"],
            "warnings": d["warnings"]}


class ExecuteBody(BaseModel):
    leave_inbox: bool = False  # True=保留 inbox 原文件；默认移走到 _archive/ingested_inbox/


@router.post("/ingest/execute")
def ingest_execute(body: ExecuteBody):
    """执行摄入：_inbox/ → works/{id}/source/，直写 works + 建 parse_runs pending 行。
    执行前先 dry-run 取计划（无新文件则 400）。"""
    plan = build_ingest_plan(LIBRARY_ROOT, dry_run=True)
    if plan.summary()["ingests"] == 0:
        raise HTTPException(400, "no new files in _inbox/ to ingest")
    backup_dir = execute_plan(plan, no_backup=True, leave_inbox=body.leave_inbox)
    s = plan.summary()
    return {"ok": True, "summary": s, "backup_dir": str(backup_dir) if backup_dir else None}
```

In `api/main.py`：加 `from .routes import ingest`（import 列表，与现有 routes 同处）+ `app.include_router(ingest.router, prefix="/api")`（与 `:23-30` 现有 include_router 同处）。

- [ ] **Step 4: 运行 plan 测试通过**

Run: `uv run python -m pytest tests/test_ingest_api.py -q`
Expected: 2 passed。

- [ ] **Step 5: 写失败测试 —— execute 端点写 works + 建 parse_runs pending**

Append to `tests/test_ingest_api.py`：
```python
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
```

- [ ] **Step 6: 运行全 ingest API 测试通过**

Run: `uv run python -m pytest tests/test_ingest_api.py -q`
Expected: 4 passed。

- [ ] **Step 7: 全量回归 + 挂载确认**

Run:
```bash
uv run python -m pytest tests/ -q 2>&1 | tail -3
uv run python -c "from api.main import app; print([r.path for r in app.routes if '/ingest' in r.path])"
```
Expected: 全 passed / 0 failed（+4 新测试）；打印含 `/api/ingest/plan`、`/api/ingest/execute`。

- [ ] **Step 8: Commit**

```bash
git add api/routes/ingest.py api/main.py tests/test_ingest_api.py
git commit -m "feat(P3.5/B'): /api/ingest/plan(dry-run) + /execute inbox 手动摄入端点

薄适配器委托 scripts.literature_ingest nucleus(build_ingest_plan/execute_plan)，
零业务逻辑(§2 单核)。ingest 直写 works + 建 parse_runs pending 行(Phase B 接力)。
tests/test_ingest_api.py: temp library_root + patch LIBRARY_ROOT, 不触网络。"
```

---

## Task 2: 前端 client + InboxReview.vue + 路由/侧边栏

**Files:**
- Modify: `web/src/api.js`（加 `getIngestPlan`/`executeIngest`）
- Create: `web/src/views/InboxReview.vue`
- Modify: `web/src/router.js`（加路由）
- Modify: `web/src/components/AppLayout.vue`（加侧边栏入口）

- [ ] **Step 1: 加 api.js client 函数**

In `web/src/api.js`，仿现有 `getIntakeCandidates` 模式加：
```javascript
export async function getIngestPlan(params = {}) {
  const qs = new URLSearchParams(params).toString()
  return fetchJSON(`/api/ingest/plan${qs ? '?' + qs : ''}`)
}

export async function executeIngest(body = {}) {
  return fetchJSON('/api/ingest/execute', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}
```
（用文件里既有的 `fetchJSON` helper 与 base URL 约定；若签名不同，对齐现有 `promoteCandidates` 的写法。）

- [ ] **Step 2: 创建 InboxReview.vue（仿 IntakeReview.vue 结构）**

Create `web/src/views/InboxReview.vue`，双栏：左=待摄入列表（从 `getIngestPlan` 的 `ingests`，显示 original_name/work_id/file_size + exact_duplicates/skipped 计数 badge）+ 右=详情（metadata kv + warnings）+ 顶部「重新扫描」「确认摄入」按钮（`executeIngest`，带 busy 锁 + confirm + alert 结果，摄入后 reload）。用 `<AppLayout>` 包裹。UI 风格对齐 IntakeReview.vue（list-panel/detail-panel grid）。组件需 `import { getIngestPlan, executeIngest } from '../api'`。

- [ ] **Step 3: 注册路由 + 侧边栏**

In `web/src/router.js`：`import InboxReview from './views/InboxReview.vue'` + 路由项 `{ path: '/inbox', component: InboxReview }`（仿 IntakeReview 行）。
In `web/src/components/AppLayout.vue`：侧边栏 nav-item 加 `📥 收件箱摄入 → /inbox`（仿 `:29-31` 的采集审核项）。

- [ ] **Step 4: 前端构建验证**

Run（前端目录）：
```bash
cd web && npm run build 2>&1 | tail -10
```
（若无 build 脚本，用 `npm run lint` 或 dev server 启动确认无编译错。）
Expected: 构建无错。

- [ ] **Step 5: Commit**

```bash
git add web/src/api.js web/src/views/InboxReview.vue web/src/router.js web/src/components/AppLayout.vue
git commit -m "feat(P3.5/B'): InboxReview.vue + /inbox 路由 + 侧边栏入口

仿 IntakeReview：左栏待摄入列表(ingests/exact_duplicates/skipped) + 右栏详情
+ 确认摄入按钮(executeIngest)。api.js 加 getIngestPlan/executeIngest。"
```

---

## Task 3: 端到端串联确认 + 收尾

**Files:**
- Update: `docs/superpowers/specs/2026-06-28-three-chain-completeness-plan.md`（Phase B' → ✅）
- Update: `FUTURE_WORK_PLAN.md`

- [ ] **Step 1: §2 单核核验**

Run:
```bash
grep -rn "def route_and_parse" --include=*.py . | grep -v "_archive\|/docs/"
grep -n "INSERT INTO works" api/routes/ingest.py
```
Expected: route_and_parse 仅 router.py；ingest 路由零 `INSERT INTO works`（全委托 nucleus）。

- [ ] **Step 2: 全量绿 + 裸 pytest**

Run:
```bash
uv run python -m pytest tests/ -q 2>&1 | tail -3
uv run python -m pytest --collect-only -q 2>&1 | tail -3
```
Expected: 全 passed / 0 failed；干净收集。

- [ ] **Step 3: 更新矩阵 + FUTURE_WORK**

Phase B' 行 → ✅（API `/api/ingest/plan`+`/execute` + UI InboxReview.vue）。

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "docs(P3.5/B'): Phase B' inbox 手动摄入完成标记"
```

---

## Self-Review
- plan/execute 端点 → Task 1 ✅；UI → Task 2 ✅；串联/矩阵 → Task 3 ✅。
- §2：路由零 `INSERT INTO works`、零业务逻辑（Task 3 Step 1 grep 守卫）✅。
- 契约：parse_runs pending 行由 nucleus 建（test_execute_writes_works_and_parse_run 断言）✅。
- 测试隔离：patch LIBRARY_ROOT → temp，nucleus 读 temp/literature.sqlite，不触真库/网络 ✅。
