# Phase C collector topics/collect 进 UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 把 collector 的 topics 成熟度闸门（seedling/proposed/mapped，人拍板）与"按主题发起一次采集"入口补进 UI；为 collect 补 API。真价值在 topics 闸门；collect/resolve 重批量主战场留 CLI/loop，UI 只做发起入口。

**Architecture:** 三步：(1) §2 关键——把锁在 CLI `scripts/literature_intake.py:37-74` 的 collect 编排（按 topic query_def 分发到 collect_explicit/collect_from_seeds/collect_repo_paper + light_gate 写 resolution）提取为 core 函数 `collector/collect.py::collect_once`，CLI 改薄包装；(2) API 薄包装 `POST /intake/collect` 委托 collect_once，并补 topics 读侧字段（additive）；(3) UI：TopicsReview.vue（成熟度闸门 + 4 判据 proposed_note / mapped_tags）+ 按主题发起采集按钮 + resolve 触发。

**Tech Stack:** FastAPI / sqlite3 / Vue3 / pytest（function-scoped temp DB + patch get_conn，仿 tests/test_intake_api.py；collect 触达网络，测试桩 collect_explicit/collect_from_seeds/collect_repo_paper/light_gate）。

**硬约束（每任务必守）：**
1. §2 单核：collect 编排逻辑**只在** `collector/collect.py::collect_once`；CLI 与 API 都是薄包装，零逻辑复制。`collector/` 写 works 必经 ingest_bridge（既有 boundary 测试守卫，勿破）。
2. 解析输出契约不变（本 phase 不碰 parser）。
3. 测试纪律：每端点配测试；temp DB + patch `collector.{collect,candidate_store,gate,topics}.get_conn` 与 `api.routes.intake.get_conn`（function-scoped，仿 test_intake_api.py:32-52）；collect 触达网络——桩 3 个发现入口 + light_gate，不触真网络。
4. 向后兼容：既有 `GET/POST /intake/topics`、`POST /intake/resolve` 语义不变；`topics.list_topics` 改为 **additive**（只增列不减）；CLI `collect` 行为不变。
5. 边界：UI collect 只做"按主题发起一次采集"入口；持续 loop/批量订阅留 CLI。

**接力点实锤（来自调研）：**
- collect 编排（要提取）：`scripts/literature_intake.py:37-74`。依赖：`topics.get`(id)→`query_def`；`collect_explicit(arxiv_ids,*,source_type,collection_topic_id)`(`collector/discovery_explicit.py:17`)；`collect_from_seeds(seed_arxiv_ids,*,source_type,collection_topic_id)`(`collector/discovery_citation.py:72`)；`collect_repo_paper(repo_url,*,collection_topic_id)`(`collector/adapters/github.py:38`)；`light_gate({"arxiv_id","doi","title"})`(`collector/gate.py:47`)。
- topics core：`collector/topics.py`——`list_topics`(`:140`，**只回 id/name/map_status/lifecycle 4 列**)、`get(topic_id)`(`:75`，回全行)、`transition`(`:93`)、`create`(`:40`)。`ALLOWED_MAP={"seedling","proposed","mapped"}`(`:26`)，`FORWARD` 边(`:29`)。4 判据=约定（复现性/不可折叠/轴归属/边界可述），core 只强制 proposed 带非空 proposed_note、mapped 带 mapped_tags(`:114-117`)。
- 现有 API：`api/routes/intake.py:172 GET /intake/topics`(调 list_topics)、`:185 POST /intake/topics`(调 transition)、`:106 POST /intake/resolve`(调 gate.resolve_pending)。
- 范本：API 测试 `tests/test_intake_api.py:32-52`（function-scoped patch）；前端 `web/src/views/IntakeReview.vue`、`web/src/api.js`（已声明 `getIntakeTopics`:`208`、`resolveIntake`:`194` 但 UI 未用）。
- 挂载：`api/main.py:23-30`；前端 `web/src/router.js`、`web/src/components/AppLayout.vue:29-31`。

---

## Task 1: 提取 collect 编排到 core（§2 单核，TDD）

**Files:**
- Create: `collector/collect.py`（`collect_once` nucleus）
- Modify: `scripts/literature_intake.py:37-74`（`collect()` 改薄包装调 collect_once）
- Test: `tests/test_collect_once.py`

- [ ] **Step 1: 写失败测试 —— collect_once 编排（桩网络）**

Create `tests/test_collect_once.py`：
```python
"""collect_once 编排 nucleus 测试。桩 3 个发现入口 + light_gate，不触网络。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """temp DB + patch collector 各模块 get_conn。"""
    db = tmp_path / "literature.sqlite"
    conn = sqlite3.connect(str(db))
    # 复用 intake 迁移建 collection_topics + intake_candidates
    import importlib
    mig = importlib.import_module("scripts.migrate_add_collection_topics")
    mig.run(str(db))
    mig_c = importlib.import_module("scripts.migrate_add_intake_candidates")
    mig_c.run(str(db))
    conn.close()

    import collector.collect as collect_mod
    import collector.candidate_store as cs
    import collector.gate as gate
    import collector.topics as topics
    def _conn():
        c = sqlite3.connect(str(db)); c.row_factory = sqlite3.Row; return c
    for m in (collect_mod, cs, gate, topics):
        monkeypatch.setattr(m, "get_conn", _conn)
    return db


def test_collect_once_by_topic_dispatches_and_gates(temp_db, monkeypatch):
    """按 topic：读 query_def 分发到 collect_explicit/collect_from_seeds，再 light_gate 写 resolution。"""
    import collector.collect as collect_mod
    import collector.topics as topics

    # 建一个 proposed 主题带 explicit_ids
    topics.create(name="T1", description="d", seed_paper_ids=[], explicit_ids=["2501.11111"],
                  axis_hint="risk_domain")
    tid = topics.list_topics()[0]["id"]

    calls = {"explicit": [], "seeds": [], "gate": 0}

    def fake_explicit(ids, *, source_type="arxiv", collection_topic_id=None):
        calls["explicit"].append(list(ids))
        return [{"id": "C1", "arxiv_id": ids[0], "title": "t", "resolution": "pending"}]

    def fake_seeds(seeds, *, source_type="arxiv", collection_topic_id=None):
        calls["seeds"].append(list(seeds))
        return []

    def fake_gate(meta):
        calls["gate"] += 1
        return "new", None

    monkeypatch.setattr(collect_mod, "collect_explicit", fake_explicit)
    monkeypatch.setattr(collect_mod, "collect_from_seeds", fake_seeds)
    monkeypatch.setattr(collect_mod, "light_gate", fake_gate)

    result = collect_mod.collect_once(topic_id=tid)
    assert calls["explicit"] == [["2501.11111"]]
    assert calls["gate"] == 1
    # resolution 被写入 DB
    conn = sqlite3.connect(str(temp_db))
    try:
        r = conn.execute("SELECT resolution FROM intake_candidates WHERE id='C1'").fetchone()
    finally:
        conn.close()
    assert r[0] == "new"
    assert result["created"] >= 1


def test_collect_once_explicit_ids_and_github(temp_db, monkeypatch):
    import collector.collect as collect_mod
    monkeypatch.setattr(collect_mod, "collect_explicit",
                        lambda ids, **k: [{"id": "C2", "arxiv_id": ids[0], "title": "t", "resolution": "pending"}])
    monkeypatch.setattr(collect_mod, "collect_from_seeds", lambda *a, **k: [])
    monkeypatch.setattr(collect_mod, "collect_repo_paper",
                        lambda url, **k: {"id": "C3", "resolution": "new"})
    monkeypatch.setattr(collect_mod, "light_gate", lambda m: ("new", None))
    result = collect_mod.collect_once(explicit_ids=["2501.22222"], github_urls=["https://github.com/x/y"])
    assert result["created"] >= 2
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run python -m pytest tests/test_collect_once.py -q`
Expected: FAIL（`collector.collect` 模块/`collect_once` 不存在）。

- [ ] **Step 3: 实现 collector/collect.py nucleus**

Create `collector/collect.py`：
```python
"""collector 采集编排 nucleus（§2 单核）：按主题/显式 ID/种子/GitHub 发起一次采集 + 轻量闸门。

CLI(scripts/literature_intake.collect) 与 API(api.routes.intake) 共用本函数，零逻辑复制。
触达网络(arxiv / Semantic Scholar / GitHub)——由调用方/测试桩各发现入口。
"""
from __future__ import annotations

from api.db import get_conn
from collector import topics
from collector.discovery_explicit import collect_explicit
from collector.discovery_citation import collect_from_seeds
from collector.adapters.github import collect_repo_paper
from collector.gate import light_gate


def collect_once(*, topic_id: str | None = None, explicit_ids: list[str] | None = None,
                 seed_paper_ids: list[str] | None = None,
                 github_urls: list[str] | None = None) -> dict:
    """发起一次采集 + 轻量闸门（不下载）。返回 {created, ...} 统计。

    - topic_id 给定：读该主题 query_def 的 explicit_ids / seed_paper_ids（与显式参数合并）。
    - 对仍是 resolution='pending' 的候选跑 light_gate 写 resolution/matched_work_id。
    """
    created: list[dict] = []
    if topic_id:
        t = topics.get(topic_id)
        if t is None:
            raise ValueError(f"unknown topic {topic_id}")
        qd = t["query_def"] or {}
        explicit_ids = list(explicit_ids or []) + list(qd.get("explicit_ids") or [])
        seed_paper_ids = list(seed_paper_ids or []) + list(qd.get("seed_paper_ids") or [])
        kw_topic = {"collection_topic_id": topic_id}
    else:
        kw_topic = {}

    if explicit_ids:
        created += collect_explicit(explicit_ids, source_type="arxiv", **kw_topic)
    if seed_paper_ids:
        created += collect_from_seeds(seed_paper_ids, source_type="arxiv", **kw_topic)
    if github_urls:
        for url in github_urls:
            created.append(collect_repo_paper(url, **kw_topic))

    # 轻量闸门（不下载）：只对 pending 候选跑
    conn = get_conn()
    try:
        for c in created:
            if c.get("resolution") == "pending":
                res, matched = light_gate({"arxiv_id": c.get("arxiv_id"),
                                           "doi": None, "title": c.get("title")})
                conn.execute(
                    "UPDATE intake_candidates SET resolution=?, matched_work_id=? WHERE id=?",
                    (res, matched, c["id"]),
                )
        conn.commit()
    finally:
        conn.close()

    return {"created": len(created)}
```

- [ ] **Step 4: 运行测试通过**

Run: `uv run python -m pytest tests/test_collect_once.py -q`
Expected: 2 passed。

- [ ] **Step 5: CLI collect() 改薄包装（行为不变）**

In `scripts/literature_intake.py`：把 `collect(args)`(行 37-74) 的编排体替换为委托 `collect_once`，保留 CLI 的 args 解析与打印：
```python
def collect(args):
    """跑发现 + 轻量闸门，不下载（委托 collector.collect.collect_once 单一 nucleus）。"""
    from collector.collect import collect_once
    topic_id = getattr(args, "topic", None)
    if topic_id:
        if topics.get(topic_id) is None:
            print(f"error: unknown topic {topic_id}", file=sys.stderr)
            sys.exit(1)
    ids = [s.strip() for s in args.ids.split(",") if s.strip()] if getattr(args, "ids", None) else None
    gh = [s.strip() for s in args.github.split(",") if s.strip()] if getattr(args, "github", None) else None
    result = collect_once(topic_id=topic_id, explicit_ids=ids, github_urls=gh)
    print(f"collected {result['created']} candidates")
    if getattr(args, "auto_resolve", False):
        resolve()
```
（删除原行 42-72 的内联编排与 get_conn/light_gate 直写——已移入 nucleus。保留 `resolve()`/`resolve_one`/`topic`/`promote_review`/`list_cmd` 不变。）

- [ ] **Step 6: CLI 回归 + §2 核验**

Run:
```bash
uv run python -m pytest tests/test_intake_cli.py tests/test_collect_once.py -q 2>&1 | tail -3
grep -n "collect_explicit\|collect_from_seeds\|light_gate" scripts/literature_intake.py
```
Expected: CLI 测试全 passed（行为不变）；grep 命中只剩 import 或无命中（编排已不在 CLI）。

- [ ] **Step 7: Commit**

```bash
git add collector/collect.py scripts/literature_intake.py tests/test_collect_once.py
git commit -m "refactor(P3.5/C): collect 编排提取为 core collector.collect.collect_once(§2 单核)

scripts/literature_intake.collect 的编排(按 topic query_def 分发到 3 发现入口
+ light_gate 写 resolution) 提取到 collector/collect.py::collect_once。
CLI 改薄包装调 nucleus,行为不变。为 API 薄适配铺路(避免复制编排逻辑)。
tests/test_collect_once.py: 桩网络入口, 验证分发+闸门写入。"
```

---

## Task 2: API —— POST /intake/collect + topics 读侧补字段（TDD）

**Files:**
- Modify: `api/routes/intake.py`（加 `POST /intake/collect`；`GET /intake/topics` 补字段）
- Modify: `collector/topics.py`（`list_topics` additive 返回更多列）
- Test: `tests/test_intake_api.py`（加 collect 端点测试）

- [ ] **Step 1: 写失败测试 —— /intake/collect 委托 collect_once（桩）**

Append to `tests/test_intake_api.py`（复用其 function-scoped patch 夹具；额外 patch `collector.collect.collect_once` 与各发现入口）：
```python
def test_intake_collect_delegates(monkeypatch):
    import collector.collect as collect_mod
    called = {}
    def fake_once(*, topic_id=None, explicit_ids=None, seed_paper_ids=None, github_urls=None):
        called["args"] = dict(topic_id=topic_id, explicit_ids=explicit_ids,
                              seed_paper_ids=seed_paper_ids, github_urls=github_urls)
        return {"created": 3}
    monkeypatch.setattr(collect_mod, "collect_once", fake_once)
    # 路由侧 import 的 collect_once 也需指向同桩——patch api.routes.intake.collect_once
    import api.routes.intake as intake_route
    monkeypatch.setattr(intake_route, "collect_once", fake_once)

    resp = client.post("/api/intake/collect", json={"topic_id": "T-seed", "explicit_ids": ["2501.1"]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] == 3
    assert called["args"]["topic_id"] == "T-seed"
    assert called["args"]["explicit_ids"] == ["2501.1"]


def test_intake_collect_requires_selector():
    resp = client.post("/api/intake/collect", json={})
    assert resp.status_code == 400  # 必须给 topic_id / explicit_ids / github_urls 之一
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run python -m pytest tests/test_intake_api.py::test_intake_collect_delegates -q`
Expected: FAIL（无 `/api/intake/collect` → 404）。

- [ ] **Step 3: 加 POST /intake/collect 薄端点**

In `api/routes/intake.py`：import 区加 `from collector.collect import collect_once`；加端点：
```python
class CollectBody(BaseModel):
    topic_id: str | None = None
    explicit_ids: list[str] | None = None
    seed_paper_ids: list[str] | None = None
    github_urls: list[str] | None = None


@router.post("/intake/collect")
def intake_collect(body: CollectBody):
    """按主题/显式 ID/种子/GitHub 发起一次采集（委托 collect_once 单一 nucleus）。
    触达网络。UI 的'按主题发起一次采集'入口；持续 loop 留 CLI。"""
    if not (body.topic_id or body.explicit_ids or body.seed_paper_ids or body.github_urls):
        raise HTTPException(400, "provide topic_id / explicit_ids / seed_paper_ids / github_urls")
    try:
        result = collect_once(topic_id=body.topic_id, explicit_ids=body.explicit_ids,
                              seed_paper_ids=body.seed_paper_ids, github_urls=body.github_urls)
    except ValueError as e:  # unknown topic
        raise HTTPException(400, str(e))
    return result
```

- [ ] **Step 4: 运行 collect 端点测试通过**

Run: `uv run python -m pytest tests/test_intake_api.py -q 2>&1 | tail -3`
Expected: 全 passed（+2 新）。

- [ ] **Step 5: topics list_topics additive 补字段 + 测试**

In `collector/topics.py:list_topics`(`:140`)：SELECT 增列 `description, query_def, mapped_tags, proposed_note, axis_hint`（additive，返回 dict 多键；既有消费者按 key 取不受影响）。同步在 `tests/test_collection_topics.py` 加断言：`list_topics()[0]` 含 `description`/`axis_hint` 键。
Run: `uv run python -m pytest tests/test_collection_topics.py tests/test_intake_api.py -q 2>&1 | tail -3` → 全 passed。

- [ ] **Step 6: 全量回归**

Run: `uv run python -m pytest tests/ -q 2>&1 | tail -3`
Expected: 全 passed / 0 failed。

- [ ] **Step 7: Commit**

```bash
git add api/routes/intake.py collector/topics.py tests/test_intake_api.py tests/test_collection_topics.py
git commit -m "feat(P3.5/C): POST /intake/collect 委托 collect_once + topics list 读侧补字段

API 薄适配器(§2): collect 端点零编排逻辑,全委托 collector.collect.collect_once。
topics.list_topics additive 补 description/query_def/mapped_tags/proposed_note/
axis_hint(UI 展示主题详情/4 判据/映射标签所需)。既有语义不变。"
```

---

## Task 3: UI —— TopicsReview.vue（成熟度闸门 + 发起采集）+ resolve 触发

**Files:**
- Modify: `web/src/api.js`（加 `transitionTopic`/`createTopic`/`collectIntake`；`getIntakeTopics`/`resolveIntake` 已声明）
- Create: `web/src/views/TopicsReview.vue`
- Modify: `web/src/router.js`、`web/src/components/AppLayout.vue`

- [ ] **Step 1: 补 api.js client 函数**

In `web/src/api.js`，仿现有模式加：
```javascript
export async function transitionTopic(id, body) {
  return fetchJSON(`/api/intake/topics`, { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id, ...body }) })
}
export async function collectIntake(body) {
  return fetchJSON('/api/intake/collect', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
}
```
（`getIntakeTopics`:`208`、`resolveIntake`:`194` 已存在，复用。`POST /intake/topics` body 形状对齐 `api/routes/intake.py:185` 的 `TopicTransitionBody`。）

- [ ] **Step 2: 创建 TopicsReview.vue（仿 IntakeReview.vue）**

Create `web/src/views/TopicsReview.vue`，用 `<AppLayout>` 包裹，双栏：
- 左栏：主题列表（`getIntakeTopics` → name + map_status badge(seedling/proposed/mapped 三色) + lifecycle + axis_hint）。
- 右栏：选中主题详情（description / query_def 的 explicit_ids/seed_paper_ids / mapped_tags / proposed_note(4 判据)）+ 操作：
  - **成熟度闸门按钮**：seedling→proposed（弹框填 proposed_note，提示 4 判据：复现性/不可折叠/轴归属/边界可述）→ proposed→mapped（填 mapped_tags）。调 `transitionTopic`。
  - **按主题发起采集**按钮：调 `collectIntake({topic_id})`，alert created 数。
  - （可选）**触发 resolve**按钮：调 `resolveIntake({})`。
- 写动作带 busy 锁 + confirm + alert + reload，风格对齐 IntakeReview.vue。

- [ ] **Step 3: 注册路由 + 侧边栏**

In `web/src/router.js`：`import TopicsReview from './views/TopicsReview.vue'` + `{ path: '/topics', component: TopicsReview }`。
In `web/src/components/AppLayout.vue`：侧边栏加 `🗂 主题闸门 → /topics`（仿 `:29-31`）。

- [ ] **Step 4: 前端构建验证**

Run:
```bash
cd web && npm run build 2>&1 | tail -10
```
Expected: 构建无错。（无 build 脚本则 `npm run lint` 或 dev 启动确认。）

- [ ] **Step 5: Commit**

```bash
git add web/src/api.js web/src/views/TopicsReview.vue web/src/router.js web/src/components/AppLayout.vue
git commit -m "feat(P3.5/C): TopicsReview.vue 主题成熟度闸门 + 按主题发起采集 UI

左栏主题列表(map_status 三色 badge) + 右栏详情 + 成熟度闸门按钮
(seedling→proposed 带 4 判据 proposed_note →mapped 带 mapped_tags) +
按主题发起采集按钮(collectIntake)。api.js 加 transitionTopic/collectIntake。"
```

---

## Task 4: 收尾（矩阵/FUTURE_WORK/§2 核验）

**Files:**
- Update: `docs/superpowers/specs/2026-06-28-three-chain-completeness-plan.md`（Phase C → ✅；矩阵 collector-A UI / collector-B API+UI / collector-C UI → ✅）
- Update: `FUTURE_WORK_PLAN.md`

- [ ] **Step 1: §2 单核核验**

Run:
```bash
grep -rn "def collect_once" --include=*.py . | grep -v "_archive\|/docs/"
grep -rn "def route_and_parse" --include=*.py . | grep -v "_archive\|/docs/"
grep -n "INSERT INTO works" api/routes/intake.py
```
Expected: `collect_once` 仅 `collector/collect.py`；`route_and_parse` 仅 `parser/core/mineru/router.py`；intake 路由零 `INSERT INTO works`。

- [ ] **Step 2: collector 写 works 仍经 ingest_bridge（boundary 测试）**

Run: `uv run python -m pytest tests/test_collector_boundary.py -q 2>&1 | tail -3`
Expected: passed（未破契约）。

- [ ] **Step 3: 全量绿 + 裸 pytest**

Run:
```bash
uv run python -m pytest tests/ -q 2>&1 | tail -3
uv run python -m pytest --collect-only -q 2>&1 | tail -3
```
Expected: 全 passed / 0 failed；干净收集。

- [ ] **Step 4: 更新矩阵 + FUTURE_WORK + Commit**

Phase C 行 → ✅。
```bash
git add -A
git commit -m "docs(P3.5/C): Phase C collector topics/collect 进 UI 完成标记"
```

---

## Self-Review
- §2 collect 编排提取 → Task 1 ✅；collect API + topics 读侧 → Task 2 ✅；UI → Task 3 ✅；收尾 → Task 4 ✅。
- 单核：collect_once 唯一、route_and_parse 唯一、intake 路由零 INSERT INTO works（Task 4 Step 1 grep 守卫）✅。
- 向后兼容：list_topics additive；CLI collect 行为不变（test_intake_cli 回归）✅。
- 测试纪律：collect 桩网络入口；function-scoped patch get_conn 仿 test_intake_api ✅。
- 边界：UI collect 只发起一次采集，loop 留 CLI ✅。
