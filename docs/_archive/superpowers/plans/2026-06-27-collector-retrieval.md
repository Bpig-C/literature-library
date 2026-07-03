# collector 检索层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 collector 集成地基之上，实现"检索层"——研究主题（含成熟度阶梯）、(a) 显式 ID + (c) 引用图发现、collect/resolve 拆步、GitHub 跨源去重，使 collector 能按主题批量发现并投递候选。

**Architecture:** 新增 `collection_topics` 表（主题 + 成熟度 `map_status`/`lifecycle`）与 `intake_candidates.collection_topic_id`。检索层只写候选、只记录主题-本体映射，**绝不写本体词表**。发现机制分两个 adapter：显式 ID（arXiv）与引用图（Semantic Scholar 1 跳）。collect（轻量闸门，不下载）与 resolve（下载+SHA256）默认拆两步。

**Tech Stack:** Python 3, SQLite (`api.db.get_conn`)，pytest，arXiv API，Semantic Scholar Graph API，GitHub（经 `gh api` 复用本机认证）。

**Specs:** `docs/superpowers/specs/2026-06-27-collector-retrieval-design.md`（本层）+ `docs/superpowers/specs/2026-06-27-collector-integration-design.md`（地基）。

---

## ⚠️ 前置条件（Phase 0，须先有独立计划/实现）

本计划实现**检索层**，依赖集成地基已就绪。执行本计划前，以下须存在（来自集成 spec，需单独计划）：

- 表 `intake_candidates`（schema 见集成 spec §4），含字段 `resolution`、`status`、`review_status`、`fetched_sha256`、`local_pdf_path`、`raw_meta` 等。
- `collector/gate.py` 暴露：
  - `light_gate(conn, candidate: dict) -> str` —— 返回 `new`/`exact_hit`/`title_candidate`/`needs_better_copy`（不下载）。
  - `heavy_gate(conn, candidate_id: str) -> str` —— 下载后跑 SHA256，返回 `sha256_duplicate` 或确认 `new`。
- `collector/ingest_bridge.py` 暴露 `promote(conn, candidate_id: str) -> str`（返回 ingested_work_id）。
- `collector/normalize.py` 暴露 `normalize_arxiv_id(s) -> str|None`、`normalize_doi(s) -> str|None`、`normalize_github_url(s) -> str|None`。
- `collector/adapters/arxiv.py` 暴露 `fetch_metadata(arxiv_id) -> dict`、`pdf_url(arxiv_id) -> str`。

> 若地基未实现，先做地基计划；本计划的 Task 7（`collection_topic_id` 桥接）与 Task 5（collect/resolve 编排）会调用上述契约，签名须与本计划一致。

## 文件结构

| 文件 | 职责 |
|---|---|
| `scripts/migrate_add_collection_topics.py` | 幂等迁移：建 `collection_topics` 表 + `intake_candidates.collection_topic_id` 列 |
| `collector/__init__.py` | 包标记（若地基未建则一并建） |
| `collector/topics.py` | 主题 CRUD + 成熟度状态机（`map_status`/`lifecycle` 流转） |
| `collector/discovery_explicit.py` | (a) 显式 arXiv ID → 候选行 |
| `collector/discovery_citation.py` | (c) Semantic Scholar 引用图 1 跳 → 候选行 |
| `collector/adapters/github.py` | GitHub 论文 PDF 采集 + README 强键抽取 + 跨源对齐 |
| `scripts/literature_intake.py` | CLI：`topic`/`collect`/`resolve`（默认拆步，`--auto-resolve` 链式） |
| `tests/test_collection_topics.py` | 主题状态机 + 迁移测试 |
| `tests/test_discovery_explicit.py` | 显式 ID 发现测试 |
| `tests/test_discovery_citation.py` | 引用图发现测试（mock S2 API） |
| `tests/test_github_adapter.py` | GitHub 强键抽取 + 跨源对齐测试 |
| `tests/test_intake_cli.py` | collect/resolve 拆步编排测试 |

**测试隔离约定**（沿用 commit `e9baa17`）：测试 patch `api.db.LIBRARY_ROOT` 与 `DB_PATH` 指向 tmp 目录，restore 时清空。

---

## Task 1: `collection_topics` 表 + 幂等迁移

**Files:**
- Create: `scripts/migrate_add_collection_topics.py`
- Create: `tests/test_collection_topics.py`

- [ ] **Step 1: 写失败测试（迁移建表 + 幂等）**

```python
# tests/test_collection_topics.py
import sqlite3
import importlib
from pathlib import Path

def _run_migration(conn_path):
    import api.db as db
    db.LIBRARY_ROOT = conn_path.parent
    db.DB_PATH = conn_path
    import scripts.migrate_add_collection_topics as m
    m.run(conn_path)
    m.run(conn_path)  # 幂等：再跑不报错

def test_migration_creates_collection_topics(tmp_path, monkeypatch):
    db_path = tmp_path / "literature.sqlite"
    sqlite3.connect(db_path).close()
    _run_migration(db_path)
    conn = sqlite3.connect(db_path)
    rows = conn.execute("PRAGMA table_info(collection_topics)").fetchall()
    cols = {r[1] for r in rows}
    assert {"id","name","description","query_def","map_status","lifecycle",
            "mapped_tags","proposed_note","axis_hint","created_at","updated_at"} <= cols
    conn.close()

def test_migration_adds_topic_fk_column(tmp_path):
    db_path = tmp_path / "literature.sqlite"
    c = sqlite3.connect(db_path)
    # 地基已建 intake_candidates 的前提：测试里手动建一个最小占位表
    c.execute("CREATE TABLE intake_candidates (id TEXT PRIMARY KEY)")
    c.close()
    _run_migration(db_path)
    conn = sqlite3.connect(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(intake_candidates)").fetchall()}
    assert "collection_topic_id" in cols
    conn.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_collection_topics.py -v`
Expected: FAIL（`No module named 'scripts.migrate_add_collection_topics'`）

- [ ] **Step 3: 实现迁移脚本（仿 `migrate_add_classification_columns.py`）**

```python
# scripts/migrate_add_collection_topics.py
"""Add collection_topics table + intake_candidates.collection_topic_id.

Idempotent. Usage:
    python scripts/migrate_add_collection_topics.py
    python scripts/migrate_add_collection_topics.py --dry-run
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.db import get_conn

CREATE_COLLECTION_TOPICS = """
CREATE TABLE IF NOT EXISTS collection_topics (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    description   TEXT,
    query_def     TEXT,            -- JSON: {explicit_ids, seed_paper_ids, ...}
    map_status    TEXT NOT NULL DEFAULT 'seedling',  -- seedling|proposed|mapped
    lifecycle     TEXT NOT NULL DEFAULT 'active',     -- active|paused|retired
    mapped_tags   TEXT,            -- JSON [{group,value}]
    proposed_note TEXT,
    axis_hint     TEXT,            -- risk_domain|reading_lane
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
)
"""
INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_ct_map_status ON collection_topics(map_status)",
    "CREATE INDEX IF NOT EXISTS idx_ct_lifecycle ON collection_topics(lifecycle)",
]

def _column_exists(conn, table, col):
    return any(r[1] == col for r in conn.execute(f"PRAGMA table_info({table})").fetchall())

def run(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(CREATE_COLLECTION_TOPICS)
        for idx in INDEXES:
            conn.execute(idx)
        if not _column_exists(conn, "intake_candidates", "collection_topic_id"):
            conn.execute("ALTER TABLE intake_candidates ADD COLUMN collection_topic_id TEXT")
        conn.commit()
    finally:
        conn.close()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.dry_run:
        print("DRY-RUN: would create collection_topics + add collection_topic_id"); return
    from api.db import DB_PATH
    run(DB_PATH)
    print("OK: collection_topics migration applied")

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_collection_topics.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add scripts/migrate_add_collection_topics.py tests/test_collection_topics.py
git commit -m "feat(collector): collection_topics 表 + 幂等迁移"
```

---

## Task 2: 主题 CRUD + 成熟度状态机

**Files:**
- Create: `collector/topics.py`
- Modify: `tests/test_collection_topics.py`（追加状态机测试）

- [ ] **Step 1: 写失败测试（状态机合法/非法流转）**

```python
# 追加到 tests/test_collection_topics.py
from collector import topics

def test_create_topic_defaults_to_seedling_active(tmp_path, monkeypatch):
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="目标错误泛化", description="hunch", seed_paper_ids=["2210.00001"])
    assert ct["map_status"] == "seedling" and ct["lifecycle"] == "active"
    assert ct["query_def"]["seed_paper_ids"] == ["2210.00001"]

def test_transition_seedling_to_proposed_allowed(tmp_path, monkeypatch):
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="X", description="")
    topics.transition(ct["id"], to_map_status="proposed", proposed_note="复现5篇/不可折叠/轴risk_domain/边界可述")
    assert topics.get(ct["id"])["map_status"] == "proposed"

def test_transition_mapped_to_seedling_forbidden(tmp_path, monkeypatch):
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="Y", description="")
    topics.transition(ct["id"], to_map_status="proposed", proposed_note="n")
    topics.transition(ct["id"], to_map_status="mapped", mapped_tags=[{"group":"risk_domain","value":"y"}])
    import pytest
    with pytest.raises(ValueError):
        topics.transition(ct["id"], to_map_status="seedling")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_collection_topics.py -v`
Expected: FAIL（`No module named 'collector.topics'`）

- [ ] **Step 3: 实现 `collector/topics.py`**

```python
# collector/topics.py
"""Research collection topics with maturity ladder.

map_status (ontology relationship): seedling -> proposed -> mapped (no auto-backward).
lifecycle (collection activity, orthogonal): active | paused | retired.

Boundary: this module NEVER writes the library ontology vocab (risk_domain etc.).
Mapping to mapped_tags only records the intent; the vocab value must already exist.
"""
from __future__ import annotations
import json, secrets
from datetime import datetime, timezone
from api.db import get_conn

ALLOWED_MAP = {"seedling", "proposed", "mapped"}
ALLOWED_LIFE = {"active", "paused", "retired"}
# 合法 map_status 前进路径（不允许 mapped -> seedling/proposed 回退，除非显式 reset，v1 不提供）
FORWARD = {("seedling", "proposed"), ("proposed", "mapped"), ("seedling", "mapped")}

def _now():
    return datetime.now(timezone.utc).isoformat()

def _new_id():
    return "CT-" + secrets.token_hex(4)

def create(*, name, description="", seed_paper_ids=None, explicit_ids=None,
           axis_hint=None, map_status="seedling", lifecycle="active"):
    if map_status not in ALLOWED_MAP:
        raise ValueError(f"bad map_status {map_status}")
    qd = {"explicit_ids": explicit_ids or [], "seed_paper_ids": seed_paper_ids or []}
    conn = get_conn()
    try:
        ct = {
            "id": _new_id(), "name": name, "description": description,
            "query_def": qd, "map_status": map_status, "lifecycle": lifecycle,
            "mapped_tags": None, "proposed_note": None, "axis_hint": axis_hint,
            "created_at": _now(), "updated_at": _now(),
        }
        conn.execute(
            """INSERT INTO collection_topics
               (id,name,description,query_def,map_status,lifecycle,mapped_tags,
                proposed_note,axis_hint,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (ct["id"], ct["name"], ct["description"], json.dumps(qd, ensure_ascii=False),
             ct["map_status"], ct["lifecycle"], None, None, ct["axis_hint"],
             ct["created_at"], ct["updated_at"]))
        conn.commit()
        return ct
    finally:
        conn.close()

def get(topic_id):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM collection_topics WHERE id=?", (topic_id,)).fetchone()
        if not row:
            return None
        cols = [d[0] for d in conn.execute("SELECT * FROM collection_topics LIMIT 1").description]
        d = dict(zip(cols, row))
        d["query_def"] = json.loads(d["query_def"] or "{}")
        if d.get("mapped_tags"):
            d["mapped_tags"] = json.loads(d["mapped_tags"])
        return d
    finally:
        conn.close()

def transition(topic_id, *, to_map_status=None, to_lifecycle=None,
               mapped_tags=None, proposed_note=None):
    cur = get(topic_id)
    if cur is None:
        raise KeyError(topic_id)
    if to_map_status and to_map_status != cur["map_status"]:
        if (cur["map_status"], to_map_status) not in FORWARD:
            raise ValueError(f"forbidden map_status transition {cur['map_status']}->{to_map_status}")
    if to_map_status == "mapped" and not mapped_tags:
        raise ValueError("mapped requires mapped_tags")
    if to_map_status == "proposed" and not proposed_note:
        raise ValueError("proposed requires proposed_note (the 4 criteria)")
    if to_lifecycle and to_lifecycle not in ALLOWED_LIFE:
        raise ValueError(f"bad lifecycle {to_lifecycle}")
    conn = get_conn()
    try:
        sets, args = [], []
        if to_map_status:
            sets.append("map_status=?"); args.append(to_map_status)
        if to_lifecycle:
            sets.append("lifecycle=?"); args.append(to_lifecycle)
        if mapped_tags is not None:
            sets.append("mapped_tags=?"); args.append(json.dumps(mapped_tags, ensure_ascii=False))
        if proposed_note is not None:
            sets.append("proposed_note=?"); args.append(proposed_note)
        sets.append("updated_at=?"); args.append(_now())
        args.append(topic_id)
        conn.execute(f"UPDATE collection_topics SET {', '.join(sets)} WHERE id=?", args)
        conn.commit()
    finally:
        conn.close()
    return get(topic_id)

def list_topics(*, map_status=None, lifecycle=None):
    conn = get_conn()
    try:
        q = "SELECT id,name,map_status,lifecycle FROM collection_topics WHERE 1=1"
        args = []
        if map_status:
            q += " AND map_status=?"; args.append(map_status)
        if lifecycle:
            q += " AND lifecycle=?"; args.append(lifecycle)
        return [dict(zip(["id","name","map_status","lifecycle"], r))
                for r in conn.execute(q, args).fetchall()]
    finally:
        conn.close()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_collection_topics.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

```bash
git add collector/topics.py tests/test_collection_topics.py
git commit -m "feat(collector): 主题 CRUD + 成熟度状态机(map_status/lifecycle)"
```

---

## Task 3: (a) 显式 ID 发现 adapter

**Files:**
- Create: `collector/discovery_explicit.py`
- Create: `tests/test_discovery_explicit.py`

> 依赖地基 `collector/adapters/arxiv.py:fetch_metadata`、`collector/normalize.py:normalize_arxiv_id`。本任务把它们编排成"显式 ID → 候选行（不下载）"。若地基尚未提供，先用下文契约打桩。

- [ ] **Step 1: 写失败测试（显式 ID 写候选 + 去 url 唯一）**

```python
# tests/test_discovery_explicit.py
import sqlite3
from collector import discovery_explicit as de

def test_explicit_ids_create_pending_candidates(tmp_path, monkeypatch):
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    # 占位 intake_candidates（地基未就绪时）
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE intake_candidates
        (id TEXT PRIMARY KEY, source_type TEXT, source_url TEXT, title TEXT,
         arxiv_id TEXT, doi TEXT, url_canonical TEXT, resolution TEXT,
         status TEXT, review_status TEXT, raw_meta TEXT, collection_topic_id TEXT,
         UNIQUE(source_type, url_canonical))""")
    conn.commit(); conn.close()
    monkeypatch.setattr(de, "get_conn", lambda: sqlite3.connect(db_path))

    def fake_fetch(arxiv_id):
        return {"title": "Paper "+arxiv_id, "arxiv_id": arxiv_id, "doi": None}
    monkeypatch.setattr(de, "fetch_metadata", fake_fetch)

    created = de.collect_explicit(["2501.17805", "2501.00002"], source_type="arxiv")
    assert len(created) == 2
    assert created[0]["resolution"] == "pending"
    # 重复投递同 ID 不新增（唯一约束）
    again = de.collect_explicit(["2501.17805"], source_type="arxiv")
    assert len(again) == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_discovery_explicit.py -v`
Expected: FAIL（`No module named 'collector.discovery_explicit'`）

- [ ] **Step 3: 实现 `collector/discovery_explicit.py`**

```python
# collector/discovery_explicit.py
"""(a) Explicit-ID discovery: turn a list of arXiv IDs into pending intake_candidates.
No download. Writes raw_meta from fetch_metadata. Idempotent via (source_type,url_canonical) UNIQUE.
"""
from __future__ import annotations
import json, secrets
from datetime import datetime, timezone
from api.db import get_conn
from collector.normalize import normalize_arxiv_id   # 地基
from collector.adapters import arxiv                  # 地基
fetch_metadata = arxiv.fetch_metadata

def _now():
    return datetime.now(timezone.utc).isoformat()

def _canonical(arxiv_id):
    return f"https://arxiv.org/abs/{arxiv_id}"

def collect_explicit(arxiv_ids, *, source_type="arxiv", collection_topic_id=None):
    conn = get_conn()
    created = []
    try:
        for raw in arxiv_ids:
            aid = normalize_arxiv_id(raw)
            if not aid:
                continue
            url = _canonical(aid)
            meta = fetch_metadata(aid)
            try:
                cid = "IC-" + secrets.token_hex(4)
                conn.execute(
                    """INSERT INTO intake_candidates
                       (id,source_type,source_url,title,arxiv_id,doi,url_canonical,
                        resolution,status,review_status,raw_meta,collection_topic_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (cid, source_type, url, meta.get("title"), aid, meta.get("doi"),
                     url, "pending", "pending", "pending",
                     json.dumps(meta, ensure_ascii=False), collection_topic_id))
                created.append({"id": cid, "arxiv_id": aid, "resolution": "pending"})
            except Exception:
                # UNIQUE 冲突 -> 已存在，跳过
                continue
        conn.commit()
        return created
    finally:
        conn.close()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_discovery_explicit.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add collector/discovery_explicit.py tests/test_discovery_explicit.py
git commit -m "feat(collector): (a) 显式 arXiv ID 发现 adapter"
```

---

## Task 4: (c) 引用图发现 adapter（Semantic Scholar 1 跳）

**Files:**
- Create: `collector/discovery_citation.py`
- Create: `tests/test_discovery_citation.py`

- [ ] **Step 1: 写失败测试（1 跳 citing+cited → 候选，mock S2）**

```python
# tests/test_discovery_citation.py
import sqlite3
from collector import discovery_citation as dc

def _db(tmp_path):
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    c = sqlite3.connect(db_path)
    c.execute("""CREATE TABLE intake_candidates
        (id TEXT PRIMARY KEY, source_type TEXT, source_url TEXT, title TEXT,
         arxiv_id TEXT, doi TEXT, url_canonical TEXT, resolution TEXT,
         status TEXT, review_status TEXT, raw_meta TEXT, collection_topic_id TEXT,
         UNIQUE(source_type, url_canonical))""")
    c.commit(); c.close()
    return db_path

def test_citation_expansion_one_hop(tmp_path, monkeypatch):
    db_path = _db(tmp_path)
    monkeypatch.setattr(dc, "get_conn", lambda: sqlite3.connect(db_path))

    def fake_expand(seed_arxiv_id):
        # 返回 (citing, cited) 各一篇
        return ([{"arxiv_id":"2502.00010","title":"Cites seed"}],
                [{"arxiv_id":"2401.00001","title":"Cited by seed"}])
    monkeypatch.setattr(dc, "expand_one_hop", fake_expand)

    created = dc.collect_from_seeds(["2501.17805"], source_type="arxiv")
    aids = {c["arxiv_id"] for c in created}
    assert aids == {"2502.00010", "2401.00001"}
    assert all(c["resolution"] == "pending" for c in created)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_discovery_citation.py -v`
Expected: FAIL（`No module named 'collector.discovery_citation'`）

- [ ] **Step 3: 实现 `collector/discovery_citation.py`**

```python
# collector/discovery_citation.py
"""(c) Citation-graph discovery, 1 hop, via Semantic Scholar Graph API.
For each seed paper: forward (papers that cite the seed) + backward (papers the seed cites).
Results become pending intake_candidates. No multi-hop in v1.
"""
from __future__ import annotations
import json, secrets, urllib.parse, urllib.request
from datetime import datetime, timezone
from api.db import get_conn
from collector.normalize import normalize_arxiv_id
from collector.discovery_explicit import collect_explicit  # 复用候选写入

S2_BASE = "https://api.semanticscholar.org/graph/v1/paper"

def _now():
    return datetime.now(timezone.utc).isoformat()

def _s2_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "literature-library-collector/0.1"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))

def _arxiv_to_s2paper(arxiv_id):
    """Resolve an arXiv id to a Semantic Scholar paperId via ARXIV: prefix."""
    data = _s2_get(f"{S2_BASE}/ARXIV:{arxiv_id}?fields=externalIds,title")
    return data

def expand_one_hop(seed_arxiv_id):
    """Return (forward_list, backward_list); each item {arxiv_id,title}.
    forward = papers citing the seed; backward = papers the seed cites."""
    paper = _arxiv_to_s2paper(seed_arxiv_id)
    pid = paper["paperId"]
    # forward: who cites this paper
    fwd = _s2_get(f"{S2_BASE}/{pid}/citations?fields=externalIds,title&limit=100")
    forward = []
    for row in fwd.get("data", []):
        p = row.get("citingPaper") or {}
        ext = p.get("externalIds") or {}
        if ext.get("ArXiv"):
            forward.append({"arxiv_id": normalize_arxiv_id(ext["ArXiv"]), "title": p.get("title")})
    # backward: this paper's references
    bwd = _s2_get(f"{S2_BASE}/{pid}/references?fields=externalIds,title&limit=100")
    backward = []
    for row in bwd.get("data", []):
        p = row.get("citedPaper") or {}
        ext = p.get("externalIds") or {}
        if ext.get("ArXiv"):
            backward.append({"arxiv_id": normalize_arxiv_id(ext["ArXiv"]), "title": p.get("title")})
    return forward, backward

def collect_from_seeds(seed_arxiv_ids, *, source_type="arxiv", collection_topic_id=None):
    found = []
    for seed in seed_arxiv_ids:
        aid = normalize_arxiv_id(seed)
        if not aid:
            continue
        forward, backward = expand_one_hop(aid)
        for p in forward + backward:
            if p["arxiv_id"]:
                found.append(p["arxiv_id"])
    # collect_explicit handles dedup + candidate writing + raw_meta
    return collect_explicit(found, source_type=source_type, collection_topic_id=collection_topic_id)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_discovery_citation.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add collector/discovery_citation.py tests/test_discovery_citation.py
git commit -m "feat(collector): (c) Semantic Scholar 引用图 1 跳发现"
```

---

## Task 5: GitHub adapter —— 论文 PDF + 强键抽取 + 跨源对齐

**Files:**
- Create: `collector/adapters/github.py`
- Create: `tests/test_github_adapter.py`

> 核心认知（spec §4.3）：跨源"同一篇"靠 arXiv ID/DOI 强键判，**不靠 SHA256**。本 adapter 从 repo 元数据抽强键喂轻量闸门。

- [ ] **Step 1: 写失败测试（README 抽 arXiv ID + 命中已有 work 标 exact_hit）**

```python
# tests/test_github_adapter.py
import sqlite3
from collector.adapters import github as gh

README_WITH_ARXIV = """
# My Paper Repo
Code for our paper. See https://arxiv.org/abs/2210.11314 for details.
"""

def test_extract_arxiv_id_from_readme():
    assert gh.extract_arxiv_id(README_WITH_ARXIV) == "2210.11314"

def test_extract_arxiv_id_none():
    assert gh.extract_arxiv_id("# just code") is None

def test_github_pdf_aligns_to_existing_arxiv_work(tmp_path, monkeypatch):
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    c = sqlite3.connect(db_path)
    c.execute("""CREATE TABLE works (id TEXT PRIMARY KEY, arxiv_id TEXT, title TEXT)""")
    c.execute("INSERT INTO works VALUES ('W-1','2210.11314','Existing')")
    c.execute("""CREATE TABLE intake_candidates
        (id TEXT PRIMARY KEY, source_type TEXT, source_url TEXT, title TEXT,
         arxiv_id TEXT, doi TEXT, url_canonical TEXT, resolution TEXT,
         status TEXT, review_status TEXT, raw_meta TEXT, collection_topic_id TEXT,
         UNIQUE(source_type, url_canonical))""")
    c.commit(); c.close()
    monkeypatch.setattr(gh, "get_conn", lambda: sqlite3.connect(db_path))

    # 模拟从 repo 抓到 README
    monkeypatch.setattr(gh, "fetch_repo_readme", lambda repo_url: README_WITH_ARXIV)
    cand = gh.collect_repo_paper("https://github.com/org/repo")
    # 命中已有 arXiv work -> exact_hit（跨源对齐靠强键）
    assert cand["arxiv_id"] == "2210.11314"
    assert cand["resolution"] == "exact_hit"
    assert cand["matched_work_id"] == "W-1"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_github_adapter.py -v`
Expected: FAIL（`No module named 'collector.adapters.github'`）

- [ ] **Step 3: 实现 `collector/adapters/github.py`**

```python
# collector/adapters/github.py
"""GitHub adapter (v1): collect paper/report PDFs only.
Cross-source alignment to existing arXiv works is done by STRONG KEYS (arXiv ID/DOI),
never SHA256 (different hosts => different bytes).
Reuses machine gh auth via `gh api` (no separate token). Code repos: URL -> raw_meta only, no work.
"""
from __future__ import annotations
import json, re, secrets, subprocess
from datetime import datetime, timezone
from api.db import get_conn
from collector.normalize import normalize_arxiv_id, normalize_github_url

_ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5})", re.IGNORECASE)

def _now():
    return datetime.now(timezone.utc).isoformat()

def fetch_repo_readme(repo_url):
    """Fetch README text via gh api (reuses local gh auth). Returns '' on failure."""
    repo = normalize_github_url(repo_url)  # e.g. owner/name
    if not repo:
        return ""
    try:
        out = subprocess.run(
            ["gh", "api", f"repos/{repo}/readme", "-H", "Accept: application/vnd.github.raw"],
            capture_output=True, text=True, timeout=20, check=True)
        return out.stdout
    except Exception:
        return ""

def extract_arxiv_id(text):
    if not text:
        return None
    m = _ARXIV_RE.search(text)
    return normalize_arxiv_id(m.group(1)) if m else None

def _existing_work_for_arxiv(conn, arxiv_id):
    row = conn.execute("SELECT id FROM works WHERE arxiv_id=?", (arxiv_id,)).fetchone()
    return row[0] if row else None

def collect_repo_paper(repo_url, *, collection_topic_id=None):
    """Collect a GitHub paper PDF. Extract strong key from README; align to existing work."""
    readme = fetch_repo_readme(repo_url)
    aid = extract_arxiv_id(readme)
    canonical = normalize_github_url(repo_url) or repo_url
    resolution = "pending"
    matched = None
    conn = get_conn()
    try:
        if aid:
            matched = _existing_work_for_arxiv(conn, aid)
            if matched:
                resolution = "exact_hit"  # 跨源对齐：同一 work 的多源，不新建
        cid = "IC-" + secrets.token_hex(4)
        raw = {"repo_url": repo_url, "extracted_arxiv_id": aid, "readme_excerpt": readme[:500]}
        conn.execute(
            """INSERT INTO intake_candidates
               (id,source_type,source_url,title,arxiv_id,doi,url_canonical,
                resolution,status,review_status,raw_meta,collection_topic_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (cid, "github", repo_url, None, aid, None, canonical,
             resolution, "pending", "pending", json.dumps(raw, ensure_ascii=False),
             collection_topic_id))
        conn.commit()
        return {"id": cid, "arxiv_id": aid, "resolution": resolution, "matched_work_id": matched}
    finally:
        conn.close()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_github_adapter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add collector/adapters/github.py tests/test_github_adapter.py
git commit -m "feat(collector): GitHub 论文 PDF adapter + README 强键抽取 + 跨源对齐"
```

---

## Task 6: collect / resolve 拆步编排 + CLI

**Files:**
- Create: `scripts/literature_intake.py`
- Create: `tests/test_intake_cli.py`

> `collect` 只跑轻量闸门、不下载；`resolve` 默认只对 `new`/`needs_better_copy` 下载 + SHA256。`--auto-resolve` 链式。

- [ ] **Step 1: 写失败测试（collect 不下载；resolve 默认只处理 new/needs_better_copy）**

```python
# tests/test_intake_cli.py
import sqlite3
from scripts import literature_intake as cli

def _db(tmp_path):
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    c = sqlite3.connect(db_path)
    c.execute("""CREATE TABLE intake_candidates
        (id TEXT PRIMARY KEY, source_type TEXT, arxiv_id TEXT, url_canonical TEXT,
         title TEXT, resolution TEXT, status TEXT, review_status TEXT,
         local_pdf_path TEXT, fetched_sha256 TEXT, collection_topic_id TEXT)""")
    # 一个 new、一个 exact_hit、一个 needs_better_copy
    c.execute("INSERT INTO intake_candidates (id,resolution) VALUES ('IC-1','new')")
    c.execute("INSERT INTO intake_candidates (id,resolution) VALUES ('IC-2','exact_hit')")
    c.execute("INSERT INTO intake_candidates (id,resolution) VALUES ('IC-3','needs_better_copy')")
    c.commit(); c.close()
    return db_path

def test_resolve_default_only_handles_new_and_better_copy(tmp_path, monkeypatch):
    db_path = _db(tmp_path)
    monkeypatch.setattr(cli, "get_conn", lambda: sqlite3.connect(db_path))

    resolved = []
    def fake_resolve_one(conn, cid):
        resolved.append(cid); return "new"
    monkeypatch.setattr(cli, "resolve_one", fake_resolve_one)

    cli.resolve()
    assert set(resolved) == {"IC-1", "IC-3"}  # exact_hit 不下载
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_intake_cli.py -v`
Expected: FAIL（`No module named 'scripts.literature_intake'`）

- [ ] **Step 3: 实现 `scripts/literature_intake.py`**

```python
# scripts/literature_intake.py
"""collector intake CLI: topic / collect / resolve.

collect: discovery + light gate, NO download.
resolve: download + SHA256 heavy gate; by default only for resolution in {new, needs_better_copy}.
--auto-resolve: chain resolve after collect.
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.db import get_conn
from collector import topics
from collector.discovery_explicit import collect_explicit
from collector.discovery_citation import collect_from_seeds
from collector.adapters.github import collect_repo_paper
from collector.gate import light_gate, heavy_gate   # 地基

RESOLVE_TARGETS = {"new", "needs_better_copy"}

def collect(args):
    """跑发现 + 轻量闸门，不下载。"""
    created = []
    if args.topic:
        t = topics.get(args.topic)
        qd = t["query_def"]
        if qd.get("explicit_ids"):
            created += collect_explicit(qd["explicit_ids"], collection_topic_id=args.topic)
        if qd.get("seed_paper_ids"):
            created += collect_from_seeds(qd["seed_paper_ids"], collection_topic_id=args.topic)
    if args.ids:
        created += collect_explicit(args.ids.split(","), source_type="arxiv")
    if args.github:
        for url in args.github.split(","):
            created.append(collect_repo_paper(url))
    # 跑轻量闸门（不下载），写回 resolution
    conn = get_conn()
    try:
        for c in created:
            res = light_gate(conn, {"arxiv_id": c.get("arxiv_id"),
                                    "url_canonical": c.get("url_canonical"),
                                    "title": c.get("title")})
            conn.execute("UPDATE intake_candidates SET resolution=? WHERE id=?", (res, c["id"]))
        conn.commit()
    finally:
        conn.close()
    print(f"collected {len(created)} candidates")
    if args.auto_resolve:
        resolve()

def resolve_one(conn, cid):
    """下载 + SHA256 重量闸门（地基提供）。"""
    return heavy_gate(conn, cid)

def resolve(args=None):
    """默认只对 resolution in {new, needs_better_copy} 的候选下载+SHA256。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id FROM intake_candidates WHERE resolution IN ('new','needs_better_copy')").fetchall()
        n = 0
        for (cid,) in rows:
            resolve_one(conn, cid); n += 1
        conn.commit()
        print(f"resolved {n} candidates")
    finally:
        conn.close()

def topic(args):
    if args.action == "add":
        t = topics.create(name=args.name, description=args.description or "",
                          seed_paper_ids=args.seeds.split(",") if args.seeds else None,
                          axis_hint=args.axis, map_status=args.map_status or "seedling")
        print(t["id"])
    elif args.action == "list":
        for t in topics.list_topics(map_status=args.map_status):
            print(f"{t['id']}\t{t['map_status']}\t{t['lifecycle']}\t{t['name']}")
    elif args.action == "propose":
        topics.transition(args.id, to_map_status="proposed", proposed_note=args.note or "")
        print("proposed")

def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("topic")
    t.add_argument("action", choices=["add", "list", "propose"])
    t.add_argument("--name"); t.add_argument("--description"); t.add_argument("--seeds")
    t.add_argument("--axis"); t.add_argument("--map-status"); t.add_argument("--id"); t.add_argument("--note")

    c = sub.add_parser("collect")
    c.add_argument("--topic"); c.add_argument("--ids"); c.add_argument("--github")
    c.add_argument("--auto-resolve", action="store_true")

    r = sub.add_parser("resolve")

    args = ap.parse_args(argv)
    if args.cmd == "topic": topic(args)
    elif args.cmd == "collect": collect(args)
    elif args.cmd == "resolve": resolve(args)

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_intake_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/literature_intake.py tests/test_intake_cli.py
git commit -m "feat(collector): collect/resolve 拆步 CLI + --auto-resolve 链式"
```

---

## Task 7: 晋升时主题标签建议（collection_topic_id 桥接）

**Files:**
- Modify: `collector/ingest_bridge.py`（地基提供 `promote`，本任务在晋升后补主题标签建议）
- Create: `tests/test_promote_topic_tags.py`

> 边界：collector 不绕过分类审核门禁。`mapped_tags` 仅作为**建议标签**写入 `classification_extractions`（source=collector, review_status=pending），等人审。

- [ ] **Step 1: 写失败测试（晋升后建议标签落 classification_extractions pending）**

```python
# tests/test_promote_topic_tags.py
import sqlite3
from collector import ingest_bridge as br

def test_promote_writes_suggested_tags_pending(tmp_path, monkeypatch):
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    c = sqlite3.connect(db_path)
    c.execute("CREATE TABLE works (id TEXT PRIMARY KEY)")
    c.execute("""CREATE TABLE intake_candidates
        (id TEXT PRIMARY KEY, collection_topic_id TEXT, ingested_work_id TEXT)""")
    c.execute("INSERT INTO intake_candidates VALUES ('IC-1','CT-1',NULL)")
    c.execute("""CREATE TABLE collection_topics
        (id TEXT PRIMARY KEY, name TEXT, mapped_tags TEXT)""")
    c.execute("INSERT INTO collection_topics VALUES ('CT-1','奖励黑客',
        '[{\"group\":\"risk_domain\",\"value\":\"reward_hacking\"}]')")
    c.execute("""CREATE TABLE classification_extractions
        (id TEXT PRIMARY KEY, work_id TEXT, source TEXT, review_status TEXT,
         extracted_json TEXT, created_at TEXT, updated_at TEXT)""")
    c.commit(); c.close()
    monkeypatch.setattr(br, "get_conn", lambda: sqlite3.connect(db_path))
    monkeypatch.setattr(br, "_do_ingest", lambda conn, cid: "W-9")  # 地基晋升桩

    br.promote("IC-1")
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT source,review_status FROM classification_extractions WHERE work_id='W-9'").fetchone()
    conn.close()
    assert row == ("collector", "pending")  # 建议标签，等人审
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_promote_topic_tags.py -v`
Expected: FAIL（`AttributeError`/未实现）

- [ ] **Step 3: 实现/修改 `collector/ingest_bridge.py`（补标签建议）**

```python
# collector/ingest_bridge.py （在 promote 中追加；_do_ingest 为地基实际晋升逻辑）
from __future__ import annotations
import json, secrets
from datetime import datetime, timezone
from api.db import get_conn

def _now():
    return datetime.now(timezone.utc).isoformat()

def _do_ingest(conn, candidate_id):
    """地基：实际晋升逻辑，返回 work_id。这里仅占位签名。"""
    raise NotImplementedError

def _write_suggested_tags(conn, work_id, topic_id):
    row = conn.execute("SELECT mapped_tags FROM collection_topics WHERE id=?", (topic_id,)).fetchone()
    if not row or not row[0]:
        return
    tags = json.loads(row[0])
    if not tags:
        return
    eid = "CE-" + secrets.token_hex(4)
    conn.execute(
        """INSERT INTO classification_extractions
           (id,work_id,source,review_status,extracted_json,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?)""",
        (eid, work_id, "collector", "pending", json.dumps({"suggested_tags": tags}, ensure_ascii=False),
         _now(), _now()))

def promote(candidate_id):
    conn = get_conn()
    try:
        work_id = _do_ingest(conn, candidate_id)
        topic_id = conn.execute(
            "SELECT collection_topic_id FROM intake_candidates WHERE id=?", (candidate_id,)).fetchone()
        if topic_id and topic_id[0]:
            _write_suggested_tags(conn, work_id, topic_id[0])
        conn.execute("UPDATE intake_candidates SET ingested_work_id=?, status='ingested' WHERE id=?",
                     (work_id, candidate_id))
        conn.commit()
        return work_id
    finally:
        conn.close()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_promote_topic_tags.py -v`
Expected: PASS

- [ ] **Step 5: 全量回归 + Commit**

Run: `pytest tests/ -v`
Expected: 全 PASS（含地基既有测试）

```bash
git add collector/ingest_bridge.py tests/test_promote_topic_tags.py
git commit -m "feat(collector): 晋升后写入主题建议标签(classification_extractions pending)"
```

---

## 验收对齐（spec §9）

- [x] `collection_topics` 表 + 迁移（幂等）—— Task 1
- [x] `intake_candidates.collection_topic_id` —— Task 1
- [x] 主题管理 CLI + map_status/lifecycle 流转 —— Task 2 + Task 6
- [x] (a) 显式 ID 发现 —— Task 3
- [x] (c) 引用图 1 跳 —— Task 4
- [x] collect/resolve 拆分 + `--auto-resolve` —— Task 6
- [x] GitHub 强键抽取 + 跨源 exact_hit/多源 —— Task 5
- [x] 代码仓库 URL 进 raw_meta、不建 work —— Task 5（raw_meta，纯仓库不调 collect_repo_paper）
- [ ] collector 绝不写本体词表 —— Task 2 状态机边界（mapped 只记 mapped_tags，不动 vocab）；补一条断言测试：见下

### 补充测试（边界约束）：collector 不写词表

- [ ] 在 `tests/test_collection_topics.py` 追加：`transition(..., to_map_status="mapped", mapped_tags=[...])` 只更新 `collection_topics.mapped_tags`，**不**触发任何向分类规范文件/词表常量的写入（断言无文件 IO、无 vocab 表插入）。

```python
def test_mapped_does_not_touch_vocab(tmp_path, monkeypatch):
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="Z", description="")
    topics.transition(ct["id"], to_map_status="proposed", proposed_note="n")
    out = topics.transition(ct["id"], to_map_status="mapped",
                            mapped_tags=[{"group":"risk_domain","value":"z"}])
    assert out["map_status"] == "mapped"
    # 无 vocab 表（methodology 词表在文档里，不在 DB）；mapped_tags 只是 JSON 记录
    conn = sqlite3.connect(db_path)
    tabs = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "risk_domain_vocab" not in tabs  # collector 不维护词表
```

---

## Self-Review（写作时已完成）

1. **Spec 覆盖**：§3 主题模型→T1/T2；§3.5 发现→T3/T4；§3.3 不碰词表→T2+边界测试；§4 GitHub→T5；§5 collect/resolve→T6；§3.6 桥接→T7。✓
2. **占位符**：无 TBD/TODO；`_do_ingest`/`fetch_metadata`/`light_gate`/`heavy_gate` 为地基契约，已在 Phase 0 显式声明。✓
3. **类型一致**：`map_status` 取值、`collect_explicit` 返回 `[{id,arxiv_id,resolution}]`、`promote(candidate_id)->work_id` 全程一致。✓

---

## 实施偏差记录（实施后补记，2026-06-28）

> 以下各 task 的**示例代码块**是写作时的草稿，实际实施时发现与地基真实契约不符，已按真实契约实现。示例代码块**不再权威**，以代码为准。每处偏差都经过 implementer 核验 + spec/质量两阶段审查确认正确。

1. **发现适配器候选写入**（Task 3/4/5 示例）：示例用裸 `INSERT INTO intake_candidates` + 捕获 UNIQUE。**实际改为调用 `collector.candidate_store.insert_candidate(...)`**（地基的候选层去重 chokepoint，分层强键→url 兜底），只统计 `status=='created'` 为新增。裸 INSERT 会丢失候选层去重，故禁用。

2. **闸门签名**（Task 6 示例）：示例写 `light_gate(conn, candidate)` / `heavy_gate(conn, cid)`。**地基真实签名是 `light_gate(candidate: dict) -> (resolution, matched_work_id)` 与 `heavy_gate(candidate_id: str) -> resolution`——均无 conn 参数，自管连接**。CLI 据此调用。

3. **promote 签名与结构**（Task 7 示例）：示例整段重写 `promote(candidate_id)` 并引入桩 `_do_ingest`。**实际保留地基真实签名 `promote(candidate_id, *, library_root) -> str`**，把既有晋升逻辑（暂存 PDF + build_ingest_plan + execute_plan + cleanup）原样抽进 `_do_ingest`，仅在晋升后追加 `_write_suggested_tags`。建议标签是 best-effort（独立 try/except），**绝不阻断晋升**。

4. **建议标签列名**（Task 7 示例）：示例用 `classification_extractions.source`。**真实表无 `source` 列，用 `model_name`**（与既有抽取约定一致）；写入 `model_name='collector'`、`review_status='pending'`、`applied=0`（建议，不绕过人审）。

5. **Task 6 是 MODIFY**：`scripts/literature_intake.py` 地基已有 `list`/`promote` 子命令，示例写成新建会覆盖。实际为合并式 MODIFY，保留 `list_cmd`/`promote_review`，追加 `topic`/`collect`/`resolve`。

6. **测试隔离**：跨模块编排（discovery、gate、collect 流）patch `api.db.DB_PATH`（`get_conn` 调用时读此全局，覆盖 candidate_store/gate/github/cli 全部连接）；单模块测试（topics、cli list/promote）patch 各模块的 `get_conn`。两种模式均有据可循。

7. **GitHub 跨源对齐**（Task 5）：示例手动查 works。实际复用 `light_gate` 做强键对齐（arXiv ID/DOI），**绝不靠 SHA256**（不同主机字节流不同）。`skipped_dup` 时短路、不改写已有候选行的 resolution。
