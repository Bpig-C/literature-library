# Phase A — collector 审核闭环（API + UI）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 collector 唯一必须人介入的环节（A2 审核 + 晋升）搬进浏览器：人能在 UI 走完「候选 → 审核 → 晋升为 work」，晋升后的 work 进入既有 metadata/分类审核流。

**Architecture:** 单核三适配器——业务逻辑只在 `collector/` core 写一次。新增 `api/routes/intake.py` 作薄包装，委托 `collector.candidate_store` / `collector.gate` / `collector.ingest_bridge` / `collector.topics`；新增 `IntakeReview.vue` 仿 `MetadataReview.vue`。CLI 与 API 共享同一 core 函数（为此把 CLI 里两段内联编排——review_status 写入、resolve 调度——抽进 core，CLI 改为调用）。向后兼容：既有 6 路由 + 7 页面语义不动，只新增。

**Tech Stack:** FastAPI + SQLite + Vue3 (script setup) + pytest (TestClient) + Vite。前端用既有 `request()` fetch 封装与 naive-ui（按 MetadataReview.vue 既有用法）。

**上位依据（不可改）：** `docs/superpowers/specs/2026-06-28-three-chain-completeness-plan.md` §4 Phase A、§2 单核三适配器、§5 跨切关注点。

**本 Phase 范围（严守，不外溢）：**
- 后端：`GET /api/intake/candidates`、`GET /api/intake/stats`、`POST /api/intake/resolve`、`PATCH /api/intake/candidates/{id}/review`、`POST /api/intake/promote`、`GET /api/intake/topics`、`POST /api/intake/topics`（成熟度流转）。
- 前端：`IntakeReview.vue`（候选列表 + 四态判别展示 + 逐条 approve/reject + 批量 promote + needs_better_copy 高亮）+ 侧边栏入口。
- 不做（留给 Phase C）：collect/resolve/topics 的 UI 触发页、主题创建 UI。`topics` 端点本 Phase 建好（委托 core），UI 留 Phase C。

**跨 phase 依赖 flag（记给人，不在本 phase 默写）：**
- Phase A 的端到端 smoke 需要候选数据，而候选由 `literature_intake.py collect`（已合并的 CLI，属 Phase B/C 的 collect 链）产生。本 Phase 用既有 CLI 灌一条候选来 smoke，**不**在本 Phase 实现 collect UI。
- `POST /api/intake/resolve` 委托的 `gate.resolve_pending` 当前只跑 `heavy_gate`（读 `local_pdf_path` 做 SHA256），不主动下载。下载目前发生在 collect 的适配器里。若 resolve 时候选尚无 `local_pdf_path`，heavy_gate 返回 `fetch_failed`——这是既有行为，本 Phase 保留，不在 Phase A 修。

---

## File Structure

**Core（nucleus，单一真相源）：**
- `collector/candidate_store.py` — **Modify**：新增 `set_review_status(cid, status, note=None)`（从 CLI 抽出）。
- `collector/gate.py` — **Modify**：新增 `resolve_pending(ids=None, limit=None)`（从 CLI 抽出）。

**CLI（薄包装，改用 core）：**
- `scripts/literature_intake.py` — **Modify**：`promote_review` 改调 `candidate_store.set_review_status`；`resolve` 改调 `gate.resolve_pending`。行为不变（既有测试守护）。

**API（薄包装）：**
- `api/routes/intake.py` — **Create**：全部端点，委托 core。
- `api/main.py` — **Modify**：`include_router(intake.router, prefix="/api")`。

**前端（薄包装）：**
- `web/src/api.js` — **Modify**：新增 intake 系列函数。
- `web/src/views/IntakeReview.vue` — **Create**：审核页。
- `web/src/router.js` — **Modify**：加 `/intake` 路由。
- `web/src/components/AppLayout.vue` — **Modify**：侧边栏加「采集审核」入口。

**测试：**
- `tests/test_intake_api.py` — **Create**：独立 temp DB 副本 + 跨模块 patch get_conn + 灌候选/主题夹具，覆盖每个端点。

**部署：**
- 在真实库跑 `python scripts/migrate_add_collection_topics.py`（live DB 当前缺 `collection_topics`；`intake_candidates` 已存在）。

---

## Task 1: 部署前置——迁移 collection_topics 到真实库

**Files:**
- Run: `python scripts/migrate_add_collection_topics.py`（脚本已存在，幂等）

- [ ] **Step 1: 迁移前确认现状（真实库缺表）**

Run:
```bash
python -c "import sqlite3; c=sqlite3.connect('literature.sqlite'); print([r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name IN ('intake_candidates','collection_topics')\")])"
```
Expected: `['intake_candidates']`（无 `collection_topics`）。

- [ ] **Step 2: dry-run**

Run: `python scripts/migrate_add_collection_topics.py --dry-run`
Expected: `DRY-RUN: would create collection_topics + 2 indexes (and topic_id column if missing)`

- [ ] **Step 3: 执行迁移**

Run: `python scripts/migrate_add_collection_topics.py`
Expected: `OK: collection_topics migration applied`

- [ ] **Step 4: 迁移后确认**

Run:
```bash
python -c "import sqlite3; c=sqlite3.connect('literature.sqlite'); print([r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name='collection_topics'\")]); print([r[0] for r in c.execute('PRAGMA table_info(collection_topics)')])"
```
Expected: 表存在，列含 `id,name,description,query_def,map_status,lifecycle,mapped_tags,proposed_note,axis_hint,created_at,updated_at`。

- [ ] **Step 5: 不单独 commit（部署变更不入版本；它是运行时动作）**

注：此步骤改的是 `literature.sqlite`（运行时数据，不入 git）。继续 Task 2。

---

## Task 2: Core — candidate_store.set_review_status（从 CLI 抽出 nucleus）

**Files:**
- Modify: `collector/candidate_store.py`（末尾追加）
- Modify: `scripts/literature_intake.py:28-38`（`promote_review` 改调 core）
- Test: `tests/test_intake_api.py` 的 review 测试会用到；本任务先用一个直测 core 的小测试

- [ ] **Step 1: 写失败测试（core 直测）**

Create `tests/test_candidate_store_review.py`:
```python
# tests/test_candidate_store_review.py
import sqlite3
from collector import candidate_store as cs


def _db(tmp_path):
    db = tmp_path / "literature.sqlite"
    c = sqlite3.connect(db)
    c.execute("""CREATE TABLE intake_candidates (
        id TEXT PRIMARY KEY, review_status TEXT, review_note TEXT, status TEXT)""")
    c.execute("INSERT INTO intake_candidates (id, review_status, status) VALUES ('IC-1','pending','resolved')")
    c.commit(); c.close()
    return db


def test_set_review_status_approves_with_note(tmp_path, monkeypatch):
    db = _db(tmp_path)
    def _get_conn():
        cc = sqlite3.connect(db); cc.row_factory = sqlite3.Row; return cc
    monkeypatch.setattr(cs, "get_conn", _get_conn)
    cs.set_review_status("IC-1", "approved", note="ok")
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT review_status, review_note FROM intake_candidates WHERE id='IC-1'").fetchone()
    conn.close()
    assert row[0] == "approved" and row[1] == "ok"


def test_set_review_status_rejects_bad_status(tmp_path, monkeypatch):
    db = _db(tmp_path)
    def _get_conn():
        cc = sqlite3.connect(db); cc.row_factory = sqlite3.Row; return cc
    monkeypatch.setattr(cs, "get_conn", _get_conn)
    import pytest
    with pytest.raises(ValueError):
        cs.set_review_status("IC-1", "bogus")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run python -m pytest tests/test_candidate_store_review.py -v`
Expected: FAIL（`AttributeError: module 'collector.candidate_store' has no attribute 'set_review_status'`）。

- [ ] **Step 3: 实现 core 函数**

在 `collector/candidate_store.py` 末尾追加：
```python
VALID_REVIEW = {"pending", "approved", "rejected"}


def set_review_status(candidate_id, status, note=None):
    """Set a candidate's A2 review_status (pending|approved|rejected). Optional note.

    This is the single nucleus for review-status writes; both the CLI and the
    intake API delegate here (no duplicate UPDATE logic).
    """
    if status not in VALID_REVIEW:
        raise ValueError(f"bad review_status {status}")
    conn = get_conn()
    try:
        cur = conn.execute("SELECT 1 FROM intake_candidates WHERE id=?", (candidate_id,)).fetchone()
        if not cur:
            raise KeyError(candidate_id)
        if note is not None:
            conn.execute("UPDATE intake_candidates SET review_status=?, review_note=? WHERE id=?",
                         (status, note, candidate_id))
        else:
            conn.execute("UPDATE intake_candidates SET review_status=? WHERE id=?",
                         (status, candidate_id))
        conn.commit()
    finally:
        conn.close()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run python -m pytest tests/test_candidate_store_review.py -v`
Expected: 2 passed。

- [ ] **Step 5: CLI 改调 core（行为不变）**

`scripts/literature_intake.py` 顶部 import 区已有 `from collector import topics`，新增：
```python
from collector import candidate_store
```
把 `promote_review`（第 28-38 行）整体替换为：
```python
def promote_review(*, approve=None, reject=None):
    """A2 审核：批量 approve/reject 候选（委托 candidate_store 单一 nucleus）。"""
    for cid in (approve or []):
        candidate_store.set_review_status(cid, "approved")
    for cid in (reject or []):
        candidate_store.set_review_status(cid, "rejected")
```

- [ ] **Step 6: CLI 既有测试不回归**

Run: `uv run python -m pytest tests/test_intake_cli.py -v`
Expected: 5 passed（含 `test_promote_marks_approved`）。

- [ ] **Step 7: Commit**

```bash
git add collector/candidate_store.py scripts/literature_intake.py tests/test_candidate_store_review.py
git commit -m "refactor(collector): 抽 set_review_status 为 core nucleus，CLI 改调"
```

---

## Task 3: Core — gate.resolve_pending（从 CLI 抽出 nucleus）

**Files:**
- Modify: `collector/gate.py`（末尾追加 `resolve_pending`）
- Modify: `scripts/literature_intake.py:86-98`（`resolve` 改调 core）
- Test: `tests/test_gate_resolve_pending.py`（新建）

- [ ] **Step 1: 写失败测试**

Create `tests/test_gate_resolve_pending.py`:
```python
# tests/test_gate_resolve_pending.py
import sqlite3
from collector import gate


def _db(tmp_path, rows):
    db = tmp_path / "literature.sqlite"
    c = sqlite3.connect(db)
    c.execute("""CREATE TABLE intake_candidates (
        id TEXT PRIMARY KEY, resolution TEXT, local_pdf_path TEXT, fetched_sha256 TEXT)""")
    c.execute("""CREATE TABLE source_files (id TEXT PRIMARY KEY, content_sha256 TEXT)""")
    for r in rows:
        c.execute("INSERT INTO intake_candidates (id, resolution, local_pdf_path) VALUES (?,?,?)",
                  (r["id"], r["resolution"], r.get("local_pdf_path")))
    c.commit(); c.close()
    return db


def test_resolve_pending_only_new_and_better_copy(tmp_path, monkeypatch):
    db = _db(tmp_path, [
        {"id": "IC-1", "resolution": "new"},
        {"id": "IC-2", "resolution": "exact_hit"},
        {"id": "IC-3", "resolution": "needs_better_copy"},
    ])
    calls = []
    def _get_conn():
        return sqlite3.connect(db)
    monkeypatch.setattr(gate, "get_conn", _get_conn)
    monkeypatch.setattr(gate, "heavy_gate", lambda cid: (calls.append(cid), "fetch_failed")[1])
    results = gate.resolve_pending()
    assert {cid for cid, _ in results} == {"IC-1", "IC-3"}   # exact_hit 不处理


def test_resolve_pending_explicit_ids(tmp_path, monkeypatch):
    db = _db(tmp_path, [{"id": "IC-1", "resolution": "new"}, {"id": "IC-2", "resolution": "new"}])
    monkeypatch.setattr(gate, "get_conn", lambda: sqlite3.connect(db))
    monkeypatch.setattr(gate, "heavy_gate", lambda cid: "new")
    results = gate.resolve_pending(ids=["IC-1"])
    assert [cid for cid, _ in results] == ["IC-1"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run python -m pytest tests/test_gate_resolve_pending.py -v`
Expected: FAIL（`AttributeError: module 'collector.gate' has no attribute 'resolve_pending'`）。

- [ ] **Step 3: 实现 core 函数**

在 `collector/gate.py` 末尾追加：
```python
def resolve_pending(ids=None, limit=None):
    """Run the heavy (SHA256) gate on candidates. Returns list of (candidate_id, resolution).

    Selection (when ids is None): only candidates whose resolution is
    'new' or 'needs_better_copy' — the ones worth downloading. exact_hit /
    sha256_duplicate need no download.

    This is the single nucleus for resolve scheduling; CLI and API both
    delegate here. heavy_gate manages its own connection and commit.
    """
    conn = get_conn()
    try:
        if ids:
            placeholders = ",".join("?" * len(ids))
            rows = conn.execute(
                f"SELECT id FROM intake_candidates WHERE id IN ({placeholders})", list(ids)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id FROM intake_candidates WHERE resolution IN ('new','needs_better_copy')"
            ).fetchall()
        if limit:
            rows = rows[:limit]
        ids_to_run = [r["id"] for r in rows]
    finally:
        conn.close()
    results = []
    for cid in ids_to_run:
        results.append((cid, heavy_gate(cid)))
    return results
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run python -m pytest tests/test_gate_resolve_pending.py -v`
Expected: 2 passed。

- [ ] **Step 5: CLI 改调 core（行为不变）**

`scripts/literature_intake.py` import 区新增：
```python
from collector.gate import light_gate, heavy_gate, resolve_pending
```
（替换原 `from collector.gate import light_gate, heavy_gate`。）
把 `resolve`（第 86-98 行）整体替换为：
```python
def resolve(args=None):
    """默认只对 resolution in {new, needs_better_copy} 的候选下载+SHA256（委托 gate.resolve_pending）。"""
    results = resolve_pending()
    print(f"resolved {len(results)} candidates")
```
保留 `resolve_one` 不动（heavy_gate 的薄别名，既有签名契约）。

- [ ] **Step 6: CLI 既有测试不回归**

Run: `uv run python -m pytest tests/test_intake_cli.py -v`
Expected: 5 passed（注意 `test_resolve_default_only_handles_new_and_better_copy` 仍绿——它 monkeypatch `cli.resolve_one`；但新 `resolve()` 改调 `resolve_pending`，后者内部调 `heavy_gate` 而非 `resolve_one`）。

⚠️ **若 Step 6 该测试红**：因为它 patch 的是 `cli.resolve_one` 而新流程走 `gate.heavy_gate`。修法：把该测试改为 `monkeypatch.setattr(gate, "heavy_gate", fake)`（在测试文件顶部 `from collector import gate`）。改测试断言不变。这是把测试对齐到新 nucleus，属允许的测试夹具修正（不改行为契约）。

- [ ] **Step 7: Commit**

```bash
git add collector/gate.py scripts/literature_intake.py tests/test_gate_resolve_pending.py tests/test_intake_cli.py
git commit -m "refactor(collector): 抽 resolve_pending 为 core nucleus，CLI 改调"
```

---

## Task 4: 后端路由骨架 + GET /candidates + GET /stats + 挂载 + 测试夹具

**Files:**
- Create: `api/routes/intake.py`
- Modify: `api/main.py`（include_router）
- Test: `tests/test_intake_api.py`（新建，含共享夹具）

- [ ] **Step 1: 写失败测试（夹具 + candidates/stats）**

Create `tests/test_intake_api.py`:
```python
# tests/test_intake_api.py
"""Intake (collector A2 review) API route tests. Temp DB copy; patches get_conn
in the route AND in every collector core module it delegates to (those modules
bind get_conn via `from api.db import get_conn`, so each must be rebound)."""
from __future__ import annotations
import json as _json
import shutil, sqlite3, tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.db import DB_PATH
from api.main import app

# --- temp DB (copy of live) ---
_tmp_dir = tempfile.mkdtemp(prefix="litlib_intake_")
_tmp_db = Path(_tmp_dir) / "literature.sqlite"
shutil.copy2(str(DB_PATH), str(_tmp_db))


def _test_get_conn():
    c = sqlite3.connect(str(_tmp_db)); c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL"); return c


def _conn():
    return _test_get_conn()


@pytest.fixture(autouse=True, scope="function")
def _patch_get_conn():
    """Patch get_conn in the route + all collector core modules it delegates to.

    NOTE scope='function' (not 'session'): a session-scoped patch.object on shared
    module symbols (collector.*.get_conn) would stay armed across the whole pytest
    run and silently rebind OTHER test files' get_conn to this file's temp DB
    (e.g. it broke tests/test_intake_cli.py::test_collect_topic_runs_gate_and_persists).
    Function scope arms/disarms per test, so no cross-file contamination. The
    _migrate_and_seed fixture below uses _conn() directly (not the patched symbol),
    so it is independent of this patch's scope/ordering.
    """
    import collector.candidate_store as cs
    import collector.gate as gate
    import collector.ingest_bridge as br
    import collector.topics as topics
    import api.routes.intake as intake
    with patch("api.routes.intake.get_conn", _test_get_conn), \
         patch.object(cs, "get_conn", _test_get_conn), \
         patch.object(gate, "get_conn", _test_get_conn), \
         patch.object(br, "get_conn", _test_get_conn), \
         patch.object(topics, "get_conn", _test_get_conn), \
         patch("api.routes.intake.LIBRARY_ROOT", _tmp_dir):
        yield


@pytest.fixture(autouse=True, scope="session")
def _migrate_and_seed():
    """collection_topics is absent from live DB; create it on the temp copy + seed."""
    import scripts.migrate_add_collection_topics as mct
    mct.run(_tmp_db)
    conn = _conn()
    now = "2026-06-28T00:00:00"
    conn.execute("DELETE FROM intake_candidates")
    conn.execute("DELETE FROM collection_topics")
    conn.execute("""INSERT INTO collection_topics
        (id,name,description,query_def,map_status,lifecycle,mapped_tags,proposed_note,
         axis_hint,created_at,updated_at)
        VALUES ('CT-1','测试主题','d','{\"explicit_ids\":[],\"seed_paper_ids\":[]}',
                'seedling','active',NULL,NULL,NULL,?,?)""", (now, now))
    seeds = [
        ("IC-aaaa", "arxiv", "https://arxiv.org/abs/2501.00001", "Paper One", "2501.00001",
         None, "new", "pending", None, "CT-1"),
        ("IC-bbbb", "arxiv", "https://arxiv.org/abs/2501.00002", "Paper Two", "2501.00002",
         None, "exact_hit", "pending", "W-existing", None),
        ("IC-cccc", "github", "https://github.com/x/y", "Repo Paper", None,
         None, "needs_better_copy", "approved", "W-quar", None),
        ("IC-dddd", "arxiv", "https://arxiv.org/abs/2501.00003", "Paper Three", "2501.00003",
         None, "new", "rejected", None, "CT-1"),
    ]
    conn.executemany("""INSERT INTO intake_candidates
        (id,source_type,url_canonical,title,arxiv_id,doi,resolution,review_status,
         matched_work_id,collection_topic_id,status,raw_meta,collected_at)
        VALUES (?,?,?,?,?,?,?, ?, ?,?,'pending',NULL,?)""", seeds)
    conn.commit(); conn.close()


@pytest.fixture(autouse=True, scope="session")
def _cleanup():
    yield
    shutil.rmtree(_tmp_dir, ignore_errors=True)


client = TestClient(app)


def test_list_candidates_default_pending():
    # 默认 review_status=pending（IC-aaaa, IC-bbbb 都是 pending）；resolution 默认不过滤
    r = client.get("/api/intake/candidates")
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()["candidates"]]
    assert set(ids) == {"IC-aaaa", "IC-bbbb"}


def test_list_candidates_filter_resolution():
    r = client.get("/api/intake/candidates", params={"resolution": "needs_better_copy"})
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()["candidates"]]
    assert ids == ["IC-cccc"]


def test_list_candidates_filter_topic():
    r = client.get("/api/intake/candidates", params={"topic": "CT-1"})
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()["candidates"]]
    assert set(ids) == {"IC-aaaa", "IC-dddd"}


def test_list_candidates_pagination():
    r = client.get("/api/intake/candidates", params={"per_page": 1, "page": 1})
    body = r.json()
    assert body["per_page"] == 1 and len(body["candidates"]) == 1
    assert body["total"] >= 2


def test_candidate_row_shape():
    r = client.get("/api/intake/candidates", params={"resolution": "new"})
    c = r.json()["candidates"][0]
    for k in ("id", "source_type", "title", "arxiv_id", "resolution", "review_status",
              "matched_work_id", "collection_topic_id", "raw_meta", "topic_name"):
        assert k in c
    assert c["topic_name"] == "测试主题"


def test_stats_counts():
    r = client.get("/api/intake/stats")
    assert r.status_code == 200
    s = r.json()
    assert s["resolution"]["new"] == 2          # IC-aaaa, IC-dddd
    assert s["resolution"]["exact_hit"] == 1
    assert s["resolution"]["needs_better_copy"] == 1
    assert s["review"]["pending"] == 2
    assert s["review"]["approved"] == 1
    assert s["review"]["rejected"] == 1
```

- [ ] **Step 2: 跑测试确认失败（路由不存在）**

Run: `uv run python -m pytest tests/test_intake_api.py -v`
Expected: FAIL（import `api.routes.intake` 失败 / 404）。

- [ ] **Step 3: 创建路由（candidates + stats）**

Create `api/routes/intake.py`:
```python
"""Intake (collector A2 review) API routes. Thin adapters over collector core.

Single-nucleus: this module writes no business logic. Candidate reads are inline
SQL (matching the metadata.py read pattern); every state change delegates to
collector.candidate_store / collector.gate / collector.ingest_bridge / collector.topics.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..db import get_conn, LIBRARY_ROOT
from collector import candidate_store, gate, ingest_bridge, topics

router = APIRouter()

RESOLUTIONS = (
    "pending", "new", "exact_hit", "title_candidate",
    "needs_better_copy", "sha256_duplicate", "fetch_failed",
)


@router.get("/intake/candidates")
def list_candidates(
    resolution: str | None = Query(None),
    review_status: str | None = Query("pending"),
    topic: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: str = Query(""),
):
    conn = get_conn()
    try:
        where, params = [], []
        if resolution:
            where.append("ic.resolution = ?"); params.append(resolution)
        if review_status:
            where.append("ic.review_status = ?"); params.append(review_status)
        if topic:
            where.append("ic.collection_topic_id = ?"); params.append(topic)
        if search:
            where.append("(ic.title LIKE ? OR ic.arxiv_id LIKE ? OR ic.id LIKE ?)")
            s = f"%{search}%"
            params.extend([s, s, s])
        where_clause = ("WHERE " + " AND ".join(where)) if where else ""

        total = conn.execute(
            f"SELECT COUNT(*) FROM intake_candidates ic {where_clause}", params
        ).fetchone()[0]

        offset = (page - 1) * per_page
        rows = conn.execute(
            f"""SELECT ic.*, ct.name AS topic_name
                FROM intake_candidates ic
                LEFT JOIN collection_topics ct ON ct.id = ic.collection_topic_id
                {where_clause}
                ORDER BY ic.collected_at DESC NULLS LAST
                LIMIT ? OFFSET ?""",
            params + [per_page, offset],
        ).fetchall()

        candidates = []
        for r in rows:
            d = dict(r)
            if d.get("raw_meta"):
                try:
                    d["raw_meta"] = json.loads(d["raw_meta"])
                except (json.JSONDecodeError, TypeError):
                    pass
            candidates.append(d)
        return {"candidates": candidates, "total": total, "page": page, "per_page": per_page}
    finally:
        conn.close()


@router.get("/intake/stats")
def intake_stats():
    conn = get_conn()
    try:
        resolution = {r: 0 for r in RESOLUTIONS}
        for row in conn.execute(
            "SELECT resolution, COUNT(*) n FROM intake_candidates GROUP BY resolution"
        ).fetchall():
            resolution[row["resolution"]] = row["n"]
        review = {"pending": 0, "approved": 0, "rejected": 0}
        for row in conn.execute(
            "SELECT review_status, COUNT(*) n FROM intake_candidates GROUP BY review_status"
        ).fetchall():
            review[row["review_status"]] = row["n"]
        return {
            "resolution": resolution,
            "review": review,
            "total": conn.execute("SELECT COUNT(*) FROM intake_candidates").fetchone()[0],
        }
    finally:
        conn.close()
```

- [ ] **Step 4: 挂载路由**

`api/main.py`：import 行改为：
```python
from .routes import duplicates, files, intake, metadata, relations, works, classification
```
在 `app.include_router(classification.router, prefix="/api")` 之后加：
```python
app.include_router(intake.router, prefix="/api")
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run python -m pytest tests/test_intake_api.py -v`
Expected: candidates/stats 相关用例 PASS。

- [ ] **Step 6: 全量不回归**

Run: `uv run python -m pytest tests/ -q`
Expected: 全绿（含既有 collector / api 测试）。

- [ ] **Step 7: Commit**

```bash
git add api/routes/intake.py api/main.py tests/test_intake_api.py
git commit -m "feat(api): intake 路由骨架 + GET /candidates + GET /stats"
```

---

## Task 5: POST /intake/resolve（委托 gate.resolve_pending）

**Files:**
- Modify: `api/routes/intake.py`（追加端点）
- Test: `tests/test_intake_api.py`（追加）

- [ ] **Step 1: 写失败测试**

在 `tests/test_intake_api.py` 末尾追加：
```python
def test_resolve_delegates_to_core(monkeypatch):
    import collector.gate as gate
    called = []
    def fake_resolve_pending(ids=None, limit=None):
        called.append((ids, limit))
        return [("IC-aaaa", "new")]
    monkeypatch.setattr(gate, "resolve_pending", fake_resolve_pending)
    r = client.post("/api/intake/resolve", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["resolved"] == 1
    assert body["results"] == [{"id": "IC-aaaa", "resolution": "new"}]
    assert called[0] == (None, None)


def test_resolve_with_ids_and_limit(monkeypatch):
    import collector.gate as gate
    seen = {}
    def fake_resolve_pending(ids=None, limit=None):
        seen["ids"], seen["limit"] = ids, limit
        return []
    monkeypatch.setattr(gate, "resolve_pending", fake_resolve_pending)
    r = client.post("/api/intake/resolve", json={"ids": ["IC-aaaa"], "limit": 5})
    assert r.status_code == 200
    assert seen == {"ids": ["IC-aaaa"], "limit": 5}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run python -m pytest tests/test_intake_api.py -k resolve -v`
Expected: FAIL（404 / 端点不存在）。

- [ ] **Step 3: 实现端点**

在 `api/routes/intake.py` 追加：
```python
class ResolveBody(BaseModel):
    ids: list[str] | None = None
    limit: int | None = None


@router.post("/intake/resolve")
def intake_resolve(body: ResolveBody):
    """Trigger the heavy (SHA256) gate. Delegates entirely to gate.resolve_pending."""
    results = gate.resolve_pending(ids=body.ids, limit=body.limit)
    return {
        "resolved": len(results),
        "results": [{"id": cid, "resolution": res} for cid, res in results],
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run python -m pytest tests/test_intake_api.py -k resolve -v`
Expected: 2 passed。

- [ ] **Step 5: Commit**

```bash
git add api/routes/intake.py tests/test_intake_api.py
git commit -m "feat(api): POST /intake/resolve 委托 gate.resolve_pending"
```

---

## Task 6: PATCH /intake/candidates/{id}/review + POST /intake/promote

**Files:**
- Modify: `api/routes/intake.py`
- Test: `tests/test_intake_api.py`

- [ ] **Step 1: 写失败测试（review）**

在 `tests/test_intake_api.py` 追加：
```python
def test_review_approve_delegates_to_core(monkeypatch):
    import collector.candidate_store as cs
    seen = {}
    def fake_set(cid, status, note=None):
        seen.update(cid=cid, status=status, note=note)
    monkeypatch.setattr(cs, "set_review_status", fake_set)
    r = client.patch("/api/intake/candidates/IC-aaaa/review",
                     json={"review_status": "approved", "note": "good"})
    assert r.status_code == 200
    assert seen == {"cid": "IC-aaaa", "status": "approved", "note": "good"}


def test_review_bad_status_400():
    r = client.patch("/api/intake/candidates/IC-aaaa/review",
                     json={"review_status": "bogus"})
    assert r.status_code == 400


def test_review_not_found_404(monkeypatch):
    import collector.candidate_store as cs
    def boom(cid, status, note=None):
        raise KeyError(cid)
    monkeypatch.setattr(cs, "set_review_status", boom)
    r = client.patch("/api/intake/candidates/IC-nope/review",
                     json={"review_status": "rejected"})
    assert r.status_code == 404
```

- [ ] **Step 2: 写失败测试（promote，stub ingest_bridge.promote 避免真实 ingest 文件 IO）**

继续追加：
```python
def test_promote_delegates_to_bridge(monkeypatch):
    import collector.ingest_bridge as br
    calls = []
    def fake_promote(cid, *, library_root):
        calls.append((cid, str(library_root)))
        return f"W-{cid[-4:]}"
    monkeypatch.setattr(br, "promote", fake_promote)
    r = client.post("/api/intake/promote", json={"ids": ["IC-aaaa", "IC-dddd"]})
    assert r.status_code == 200
    body = r.json()
    assert body["promoted"] == [
        {"id": "IC-aaaa", "work_id": "W-aaaa"},
        {"id": "IC-dddd", "work_id": "W-dddd"},
    ]
    assert body["failed"] == []
    assert calls[0][1] == str(_tmp_dir)   # 用 patched LIBRARY_ROOT


def test_promote_collects_failures(monkeypatch):
    import collector.ingest_bridge as br
    def fake_promote(cid, *, library_root):
        if cid == "IC-bbbb":
            raise FileNotFoundError("no pdf")
        return "W-x"
    monkeypatch.setattr(br, "promote", fake_promote)
    r = client.post("/api/intake/promote", json={"ids": ["IC-aaaa", "IC-bbbb"]})
    body = r.json()
    assert body["promoted"] == [{"id": "IC-aaaa", "work_id": "W-x"}]
    assert len(body["failed"]) == 1 and body["failed"][0]["id"] == "IC-bbbb"


def test_promote_empty_ids_400():
    r = client.post("/api/intake/promote", json={"ids": []})
    assert r.status_code == 400
```

- [ ] **Step 3: 跑测试确认失败**

Run: `uv run python -m pytest tests/test_intake_api.py -k "review or promote" -v`
Expected: FAIL。

- [ ] **Step 4: 实现端点**

在 `api/routes/intake.py` 追加：
```python
class ReviewBody(BaseModel):
    review_status: str
    note: str | None = None


@router.patch("/intake/candidates/{candidate_id}/review")
def review_candidate(candidate_id: str, body: ReviewBody):
    if body.review_status not in candidate_store.VALID_REVIEW:
        raise HTTPException(400, f"review_status must be one of {sorted(candidate_store.VALID_REVIEW)}")
    try:
        candidate_store.set_review_status(candidate_id, body.review_status, note=body.note)
    except KeyError:
        raise HTTPException(404, f"candidate not found: {candidate_id}")
    return {"ok": True, "id": candidate_id, "review_status": body.review_status}


class PromoteBody(BaseModel):
    ids: list[str]


@router.post("/intake/promote")
def promote_candidates(body: PromoteBody):
    """A2 batch promote → reuse ingest_bridge (single nucleus). Collector never
    writes works directly. Returns per-id results; a single failure does not
    abort the batch."""
    if not body.ids:
        raise HTTPException(400, "ids is required and must be non-empty")
    promoted, failed = [], []
    for cid in body.ids:
        try:
            work_id = ingest_bridge.promote(cid, library_root=LIBRARY_ROOT)
            promoted.append({"id": cid, "work_id": work_id})
        except Exception as e:  # noqa: BLE001 — batch must not abort on one failure
            failed.append({"id": cid, "error": str(e)})
    return {"promoted": promoted, "failed": failed}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run python -m pytest tests/test_intake_api.py -k "review or promote" -v`
Expected: 6 passed。

- [ ] **Step 6: Commit**

```bash
git add api/routes/intake.py tests/test_intake_api.py
git commit -m "feat(api): PATCH /intake review + POST /intake/promote (A2 晋升闭环)"
```

---

## Task 7: GET/POST /intake/topics（委托 collector.topics）

**Files:**
- Modify: `api/routes/intake.py`
- Test: `tests/test_intake_api.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_intake_api.py` 追加：
```python
def test_topics_list_delegates(monkeypatch):
    import collector.topics as t
    monkeypatch.setattr(t, "list_topics",
                        lambda *, map_status=None, lifecycle=None: [
                            {"id": "CT-1", "name": "测试主题", "map_status": "seedling", "lifecycle": "active"}])
    r = client.get("/api/intake/topics", params={"map_status": "seedling"})
    assert r.status_code == 200
    body = r.json()
    assert body["topics"][0]["id"] == "CT-1"


def test_topics_transition_delegates(monkeypatch):
    import collector.topics as t
    seen = {}
    def fake_transition(tid, *, to_map_status=None, to_lifecycle=None,
                        mapped_tags=None, proposed_note=None):
        seen.update(tid=tid, to_map_status=to_map_status, proposed_note=proposed_note)
        return {"id": tid, "map_status": to_map_status}
    monkeypatch.setattr(t, "transition", fake_transition)
    r = client.post("/api/intake/topics", json={"id": "CT-1", "to_map_status": "proposed",
                                                "proposed_note": "criteria..."})
    assert r.status_code == 200
    assert seen == {"tid": "CT-1", "to_map_status": "proposed", "proposed_note": "criteria..."}


def test_topics_transition_bad_transition_400(monkeypatch):
    import collector.topics as t
    def boom(tid, **kw):
        raise ValueError("forbidden map_status transition mapped->seedling")
    monkeypatch.setattr(t, "transition", boom)
    r = client.post("/api/intake/topics", json={"id": "CT-1", "to_map_status": "seedling"})
    assert r.status_code == 400
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run python -m pytest tests/test_intake_api.py -k topics -v`
Expected: FAIL。

- [ ] **Step 3: 实现端点**

在 `api/routes/intake.py` 追加：
```python
@router.get("/intake/topics")
def intake_topics(map_status: str | None = Query(None), lifecycle: str | None = Query(None)):
    return {"topics": topics.list_topics(map_status=map_status, lifecycle=lifecycle)}


class TopicTransitionBody(BaseModel):
    id: str
    to_map_status: str | None = None
    to_lifecycle: str | None = None
    mapped_tags: list | None = None
    proposed_note: str | None = None


@router.post("/intake/topics")
def intake_topics_transition(body: TopicTransitionBody):
    """Maturity transition (seedling→proposed→mapped). Delegates to topics.transition;
    collector never writes the ontology vocab — it only records intent/mapping."""
    try:
        updated = topics.transition(
            body.id,
            to_map_status=body.to_map_status,
            to_lifecycle=body.to_lifecycle,
            mapped_tags=body.mapped_tags,
            proposed_note=body.proposed_note,
        )
    except KeyError:
        raise HTTPException(404, f"topic not found: {body.id}")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "topic": updated}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run python -m pytest tests/test_intake_api.py -k topics -v`
Expected: 3 passed。

- [ ] **Step 5: 全量测试**

Run: `uv run python -m pytest tests/ -q`
Expected: 全绿。

- [ ] **Step 6: Commit**

```bash
git add api/routes/intake.py tests/test_intake_api.py
git commit -m "feat(api): GET/POST /intake/topics 委托 collector.topics（成熟度流转）"
```

---

## Task 8: 前端 — api.js + IntakeReview.vue + 路由 + 侧边栏

**Files:**
- Modify: `web/src/api.js`
- Create: `web/src/views/IntakeReview.vue`
- Modify: `web/src/router.js`
- Modify: `web/src/components/AppLayout.vue`

- [ ] **Step 1: api.js 追加 intake 函数**

在 `web/src/api.js` 末尾追加：
```javascript
// ---- Intake (collector A2 review) ----
export function getIntakeCandidates(params = {}) {
  const q = new URLSearchParams(params).toString()
  return request(`/intake/candidates${q ? '?' + q : ''}`)
}

export function getIntakeStats() {
  return request('/intake/stats')
}

export function resolveIntake(data = {}) {
  return request('/intake/resolve', { method: 'POST', body: JSON.stringify(data) })
}

export function reviewCandidate(id, review_status, note = '') {
  return request(`/intake/candidates/${encodeURIComponent(id)}/review`, {
    method: 'PATCH', body: JSON.stringify({ review_status, note }),
  })
}

export function promoteCandidates(ids) {
  return request('/intake/promote', { method: 'POST', body: JSON.stringify({ ids }) })
}

export function getIntakeTopics(params = {}) {
  const q = new URLSearchParams(params).toString()
  return request(`/intake/topics${q ? '?' + q : ''}`)
}
```

- [ ] **Step 2: 创建 IntakeReview.vue**

仿 `MetadataReview.vue` 的两栏（列表 + 详情）结构，但聚焦四态判别 + approve/reject + 批量 promote。Create `web/src/views/IntakeReview.vue`:
```vue
<template>
  <AppLayout>
    <div class="intake-layout">
      <div class="list-panel">
        <h2 class="page-title">采集审核 <span class="muted tiny">collector A2</span></h2>

        <div class="filter-bar">
          <label>审核态：
            <select v-model="reviewFilter" @change="reload">
              <option value="pending">待审 ({{ stats.review?.pending || 0 }})</option>
              <option value="approved">已批准 ({{ stats.review?.approved || 0 }})</option>
              <option value="rejected">已拒绝 ({{ stats.review?.rejected || 0 }})</option>
              <option value="">全部</option>
            </select>
          </label>
          <label>判别：
            <select v-model="resolutionFilter" @change="reload">
              <option value="">全部</option>
              <option v-for="r in RESOLUTIONS" :key="r.key" :value="r.key">
                {{ r.label }} ({{ stats.resolution?.[r.key] || 0 }})
              </option>
            </select>
          </label>
          <input v-model="search" placeholder="搜标题/arXiv/ID" @keyup.enter="reload" class="search-input" />
          <button @click="reload">刷新</button>
        </div>

        <div class="ext-list">
          <div v-for="c in candidates" :key="c.id" class="ext-item"
               :class="{ selected: selected?.id === c.id, better: c.resolution === 'needs_better_copy' }"
               @click="selected = c">
            <div class="ext-title">{{ c.title || c.arxiv_id || c.id }}</div>
            <div class="ext-meta">
              <span class="badge" :class="resClass(c.resolution)">{{ resLabel(c.resolution) }}</span>
              <span class="badge review" :class="c.review_status">{{ reviewLabel(c.review_status) }}</span>
              <span class="muted tiny">{{ c.source_type }} · {{ c.arxiv_id || c.url_canonical }}</span>
            </div>
          </div>
          <div v-if="!candidates.length" class="empty muted">无候选。先用 CLI：python scripts/literature_intake.py collect --ids &lt;arxiv_id&gt;</div>
        </div>

        <div class="pager" v-if="total > perPage">
          <button :disabled="page <= 1" @click="page--; reload()">上一页</button>
          <span class="muted tiny">{{ page }} / {{ Math.ceil(total / perPage) }}</span>
          <button :disabled="page * perPage >= total" @click="page++; reload()">下一页</button>
        </div>
      </div>

      <div class="detail-panel" v-if="selected">
        <div class="detail-header">
          <div>
            <div class="ext-title">{{ selected.title || selected.id }}</div>
            <div class="muted tiny">{{ selected.id }} · {{ selected.source_type }} · {{ selected.collected_at?.slice(0,19) }}</div>
          </div>
          <div class="header-badges">
            <span class="badge" :class="resClass(selected.resolution)">{{ resLabel(selected.resolution) }}</span>
            <span class="badge review" :class="selected.review_status">{{ reviewLabel(selected.review_status) }}</span>
          </div>
        </div>

        <div class="better-banner" v-if="selected.resolution === 'needs_better_copy'">
          ⚠ needs_better_copy：命中隔离中的 work
          <span v-if="selected.matched_work_id">（{{ selected.matched_work_id }}）</span>——晋升会用好副本替换。
        </div>

        <table class="kv">
          <tr><th>arXiv</th><td>{{ selected.arxiv_id || '—' }}</td></tr>
          <tr><th>DOI</th><td>{{ selected.doi || '—' }}</td></tr>
          <tr><th>来源 URL</th><td><a :href="selected.url_canonical" target="_blank">{{ selected.url_canonical }}</a></td></tr>
          <tr><th>命中 work</th><td>
            <router-link v-if="selected.matched_work_id" :to="`/works/${selected.matched_work_id}`">{{ selected.matched_work_id }}</router-link>
            <span v-else>—</span>
          </td></tr>
          <tr><th>主题</th><td>{{ selected.topic_name || '—' }}</td></tr>
          <tr><th>状态</th><td>{{ selected.status }} / {{ selected.resolution }}</td></tr>
        </table>

        <details v-if="selected.raw_meta" class="raw">
          <summary>来源原始元数据</summary>
          <pre>{{ JSON.stringify(selected.raw_meta, null, 2) }}</pre>
        </details>

        <div class="review-bar">
          <button class="btn-approve" :disabled="busy" @click="doReview('approved')">批准</button>
          <button class="btn-reject" :disabled="busy" @click="doReview('rejected')">拒绝</button>
          <button class="btn-promote" :disabled="busy || promotedIds.length === 0" @click="doPromote">
            晋升已批准 ({{ promotedIds.length }})
          </button>
        </div>
        <div class="muted tiny" v-if="selected.ingested_work_id">
          已晋升为
          <router-link :to="`/works/${selected.ingested_work_id}`">{{ selected.ingested_work_id }}</router-link>
        </div>
      </div>
      <div class="detail-panel empty-state" v-else>
        <div class="muted">从左侧选择一个候选查看详情</div>
      </div>
    </div>
  </AppLayout>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import AppLayout from '../components/AppLayout.vue'
import { getIntakeCandidates, getIntakeStats, reviewCandidate, promoteCandidates } from '../api'

const RESOLUTIONS = [
  { key: 'new', label: '新文献' },
  { key: 'exact_hit', label: '精确命中' },
  { key: 'title_candidate', label: '标题疑似' },
  { key: 'needs_better_copy', label: '需好副本' },
  { key: 'sha256_duplicate', label: 'SHA256重复' },
  { key: 'fetch_failed', label: '下载失败' },
  { key: 'pending', label: '待判别' },
]
const RES_LABEL = Object.fromEntries(RESOLUTIONS.map(r => [r.key, r.label]))
const REVIEW_LABEL = { pending: '待审', approved: '已批准', rejected: '已拒绝' }

const candidates = ref([])
const stats = ref({})
const total = ref(0)
const page = ref(1)
const perPage = 20
const reviewFilter = ref('pending')
const resolutionFilter = ref('')
const search = ref('')
const selected = ref(null)
const busy = ref(false)

const resLabel = k => RES_LABEL[k] || k
const resClass = k => `res-${k}`
const reviewLabel = k => REVIEW_LABEL[k] || k

async function reload() {
  const body = await getIntakeCandidates({
    review_status: reviewFilter.value,
    resolution: resolutionFilter.value || undefined,
    search: search.value || undefined,
    page: page.value,
    per_page: perPage,
  })
  candidates.value = body.candidates
  total.value = body.total
  if (selected.value) {
    selected.value = candidates.value.find(c => c.id === selected.value.id) || null
  }
  await loadStats()
}

async function loadStats() {
  stats.value = await getIntakeStats()
}

// approved 候选（当前列表内）作为批量晋升对象
const promotedIds = ref([])

async function doReview(status) {
  if (!selected.value || busy.value) return
  busy.value = true
  try {
    await reviewCandidate(selected.value.id, status)
    await reload()
  } catch (e) {
    alert(e.message)
  } finally {
    busy.value = false
  }
}

async function doPromote() {
  // 取所有 review_status=approved 且尚未 ingested 的候选
  const targets = candidates.value
    .filter(c => c.review_status === 'approved' && !c.ingested_work_id)
    .map(c => c.id)
  if (!targets.length) { alert('没有可晋升的已批准候选'); return }
  if (!confirm(`晋升 ${targets.length} 个候选为 work？`)) return
  busy.value = true
  try {
    const res = await promoteCandidates(targets)
    const failed = res.failed?.length || 0
    alert(`晋升 ${res.promoted?.length || 0} 个${failed ? `，失败 ${failed} 个` : ''}`)
    await reload()
  } catch (e) {
    alert(e.message)
  } finally {
    busy.value = false
  }
}

onMounted(reload)
</script>

<style scoped>
.intake-layout { display: grid; grid-template-columns: 380px 1fr; gap: 16px; }
.list-panel, .detail-panel { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px; }
.page-title { font-size: 18px; margin-bottom: 12px; }
.filter-bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
.filter-bar select, .search-input { padding: 4px 6px; border: 1px solid var(--line); border-radius: 4px; }
.ext-list { display: flex; flex-direction: column; gap: 6px; }
.ext-item { padding: 10px; border: 1px solid var(--line); border-radius: 6px; cursor: pointer; }
.ext-item:hover { background: var(--bg); }
.ext-item.selected { border-color: var(--accent); background: #eef5ff; }
.ext-item.better { border-left: 3px solid var(--warn); }
.ext-title { font-weight: 600; }
.ext-meta { display: flex; gap: 6px; align-items: center; margin-top: 4px; flex-wrap: wrap; }
.badge { font-size: 12px; padding: 1px 6px; border-radius: 10px; background: var(--chip); }
.badge.res-new { background: #e6f4ea; color: var(--ok); }
.badge.res-exact_hit, .badge.res-sha256_duplicate { background: var(--chip); color: var(--muted); }
.badge.res-title_candidate { background: #fff8e1; color: var(--warn); }
.badge.res-needs_better_copy { background: #fdecea; color: var(--bad); }
.badge.res-fetch_failed { background: var(--chip); color: var(--bad); }
.badge.review.pending { background: var(--chip); }
.badge.review.approved { background: #e6f4ea; color: var(--ok); }
.badge.review.rejected { background: #fdecea; color: var(--bad); }
.muted { color: var(--muted); } .tiny { font-size: 12px; }
.empty { padding: 20px; text-align: center; }
.pager { display: flex; gap: 8px; align-items: center; justify-content: center; margin-top: 12px; }
.detail-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; }
.header-badges { display: flex; gap: 6px; }
.better-banner { background: #fff8e1; border: 1px solid var(--warn); border-radius: 6px; padding: 8px 10px; margin-bottom: 12px; color: var(--warn); }
table.kv { width: 100%; border-collapse: collapse; margin-bottom: 12px; }
table.kv th { text-align: left; width: 110px; color: var(--muted); padding: 4px 8px; vertical-align: top; }
table.kv td { padding: 4px 8px; }
.raw pre { background: var(--bg); padding: 8px; border-radius: 4px; font-size: 12px; overflow-x: auto; }
.review-bar { display: flex; gap: 8px; margin-top: 16px; }
.review-bar button { padding: 6px 14px; border-radius: 6px; border: 1px solid var(--line); cursor: pointer; background: var(--panel); }
.btn-approve { background: #e6f4ea; color: var(--ok); border-color: var(--ok); }
.btn-reject { background: #fdecea; color: var(--bad); border-color: var(--bad); }
.btn-promote { background: var(--accent); color: #fff; border-color: var(--accent); }
.review-bar button:disabled { opacity: .5; cursor: not-allowed; }
.empty-state { display: flex; align-items: center; justify-content: center; color: var(--muted); }
</style>
```

- [ ] **Step 3: 注册路由**

`web/src/router.js`：import 加：
```javascript
import IntakeReview from './views/IntakeReview.vue'
```
routes 数组加（在 `/classification` 后）：
```javascript
  { path: '/intake', component: IntakeReview },
```

- [ ] **Step 4: 侧边栏入口**

`web/src/components/AppLayout.vue`：在「分类审核」`router-link` 之后加：
```html
      <router-link to="/intake" class="nav-item" :class="{ active: $route.path === '/intake' }">
        <span class="nav-icon">📥</span><span class="nav-text">采集审核</span>
      </router-link>
```

- [ ] **Step 5: 前端构建**

Run: `cd web && npx vite build`
Expected: 构建成功无错误。

- [ ] **Step 6: Commit**

```bash
git add web/src/api.js web/src/views/IntakeReview.vue web/src/router.js web/src/components/AppLayout.vue
git commit -m "feat(web): IntakeReview.vue 采集审核页（A2 审核+晋升闭环）+ 侧边栏入口"
```

---

## Task 9: 自审、三链路 smoke、更新 FUTURE_WORK_PLAN

**Files:**
- Verify: tests, build, manual smoke
- Modify: `FUTURE_WORK_PLAN.md`（P6 状态注记）

- [ ] **Step 1: 全量后端测试**

Run: `uv run python -m pytest tests/ -q`
Expected: 全绿，无既有回归（含 collector 全部 + test_api.py 全部）。

- [ ] **Step 2: 确认根 pytest 不收集 parser/tests**

Run: `uv run python -m pytest --collect-only -q 2>&1 | grep -i parser/tests | head`
Expected: 无 parser/tests 用例被收集（已由 pyproject testpaths 限定）。若有泄漏，记录 flag 给人（Phase D 处理），不在本 phase 改。

- [ ] **Step 3: 前端构建复核**

Run: `cd web && npx vite build`
Expected: 成功。

- [ ] **Step 4: 三链路 smoke（CLI / API / UI 各走一遍同一动作）**

> 前提：真实库已有 `collection_topics`（Task 1）。需先有一条候选。用既有 CLI（不在本 Phase 实现 collect UI）灌一条：

```bash
# 1) collect 一条候选（既有 CLI）
python scripts/literature_intake.py collect --ids <某个真实 arxiv_id>
# 2) 闸门（既有 CLI）
python scripts/literature_intake.py resolve
# 3) 列出待晋升（既有 CLI）—— 确认有 resolution=new, review_status=pending 的候选
python scripts/literature_intake.py list
```

API 链（替换 `<IC-id>` 为上一步的真实候选 id；确认 uvicorn 跑在 19528 或 api 默认端口）：
```bash
# 启动 API（若未跑）：uv run uvicorn api.main:app --port <port>
curl 'http://127.0.0.1:<port>/api/intake/candidates?review_status=pending'
curl 'http://127.0.0.1:<port>/api/intake/stats'
curl -X PATCH 'http://127.0.0.1:<port>/api/intake/candidates/<IC-id>/review' \
     -H 'Content-Type: application/json' -d '{"review_status":"approved"}'
curl -X POST 'http://127.0.0.1:<port>/api/intake/promote' \
     -H 'Content-Type: application/json' -d '{"ids":["<IC-id>"]}'
# 确认返回 promoted[].work_id，且候选 status=ingested、ingested_work_id 回填
```

UI 链：
- 打开浏览器 → 侧边栏「采集审核」→ 看到候选 → 点开详情 → 批准 → 「晋升已批准」→ 出现 work_id 链接 → 点进 WorkDetail 确认新 work 存在、并出现在既有 metadata/分类审核流。

**验收点**：三链路结果一致——同一候选被晋升为同一 work_id，候选 `status=ingested`、`ingested_work_id` 回填，新 work 进入既有审核流。`needs_better_copy` 候选在 UI 有高亮+说明。

> 若手头无合适 arxiv 候选或不便联网，记为「smoke 待人工补」flag 给人，但 API 单元测试（Task 4-7）必须全绿作为可验证证据。

- [ ] **Step 5: 更新 FUTURE_WORK_PLAN.md**

在 P6 节追加一行状态注记（不改既有文字，只追加）：
```
- Phase A（collector 审核闭环 API + UI）：✅ 已完成（2026-06-28）。后端 api/routes/intake.py（candidates/stats/resolve/review/promote/topics，全委托 collector core）+ IntakeReview.vue + 侧边栏入口。core 抽 set_review_status / resolve_pending 为 nucleus（CLI 改调）。collection_topics 已迁移 live DB。三链路 smoke 见 docs/superpowers/plans/2026-06-28-phaseA-intake-review.md Task 9。Phase B/C/D 待续。
```

- [ ] **Step 6: 最终 commit**

```bash
git add FUTURE_WORK_PLAN.md
git commit -m "docs(plan): Phase A 完成状态注记"
```

---

## Self-Review（计划作者自检）

**1. Spec 覆盖（对照总体规划 §4 Phase A 验收 + §6）：**
- 部署前置 collection_topics 迁移 → Task 1 ✓
- `GET /api/intake/candidates`（过滤/分页）→ Task 4 ✓
- `GET /api/intake/stats` → Task 4 ✓
- `POST /api/intake/resolve`（批量闸门）→ Task 5 ✓
- `POST /api/intake/promote`（A2 批量晋升 → ingest_bridge）→ Task 6 ✓
- `GET/POST /api/intake/topics` → Task 7 ✓
- `IntakeReview.vue`（四态展示 + approve/reject + 批量 promote + needs_better_copy 高亮）→ Task 8 ✓
- 侧边栏入口 → Task 8 ✓
- 每端点配测试（temp DB + patch get_conn）→ Task 4-7 ✓
- 单核（API/CLI 不写业务逻辑）→ Task 2/3 抽 nucleus + 全程委托 ✓
- collector 不直接写 works（经 ingest_bridge）→ Task 6 用 ingest_bridge.promote ✓
- 三链路 smoke → Task 9 ✓
- 向后兼容（既有 6 路由 + 7 页面不动语义）→ 全程只新增 ✓

**2. Placeholder 扫描：** 无 TBD/TODO；每个代码步骤含完整代码；测试含真实断言。

**3. 类型/签名一致性：**
- `candidate_store.set_review_status(cid, status, note=None)` — Task 2 定义，Task 6 调用一致 ✓
- `candidate_store.VALID_REVIEW` — Task 2 定义，Task 6 引用一致 ✓
- `gate.resolve_pending(ids=None, limit=None) -> [(cid, res)]` — Task 3 定义，Task 5 调用一致 ✓
- `ingest_bridge.promote(cid, *, library_root)` — 既有签名，Task 6 调用一致 ✓
- `topics.list_topics(*, map_status, lifecycle)` / `topics.transition(tid, *, to_map_status, to_lifecycle, mapped_tags, proposed_note)` — 既有签名，Task 7 调用一致 ✓
- 前端 `getIntakeCandidates/getIntakeStats/resolveIntake/reviewCandidate/promoteCandidates/getIntakeTopics` — Task 8 定义并使用一致 ✓

**已知 flag（交人，不在本 phase 默写）：** Phase A smoke 依赖 collect 产候选（属 Phase B/C collect 链）；`resolve` 不主动下载（既有行为）。
