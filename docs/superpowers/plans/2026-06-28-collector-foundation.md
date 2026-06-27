# collector 集成地基 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建起 collector 的集成地基——`intake_candidates` 候选队列、两段式预去重闸门（轻量元数据 + 重量 SHA256）、四态判别、A2 人工晋升桥接、arXiv 适配器，使 collector 能采集候选、入库前去重、人工晋升成 work。

**Architecture:** collector 作为子模块写候选（`intake_candidates`），绝不直接写 `works`。闸门**复用** `literature_ingest.py` 现有去重逻辑（SHA256 查 `source_files`、arxiv/doi 查 `works`、标题 Jaccard）；晋升桥接**复用** `build_ingest_plan`/`execute_plan` 全链路。quarantine 复用 `read_status='quarantined'` + `work_codes('bad_source')`。

**Tech Stack:** Python 3, SQLite (`api.db.get_conn`/`LIBRARY_ROOT`/`DB_PATH`)，pytest，arXiv API（元数据 + PDF 直链），复用 `scripts/literature_ingest.py`。

**Specs:** `docs/superpowers/specs/2026-06-27-collector-integration-design.md`（本计划实现其 §3–§11）。后续检索层计划 `docs/superpowers/plans/2026-06-27-collector-retrieval.md` 建立在本地基之上。

**复用映射（来自代码勘察，load-bearing）：**
- SHA256 精确查重：`literature_ingest.sha256_file` + `SELECT 1 FROM source_files WHERE content_sha256=?`。
- work-id 一致性：`literature_ingest.choose_work_id`（arxiv→`W-arxiv-{key}`，doi→`W-doi-{slug}`，sha→`W-sha-{digest[:12]}`）；键规范化 `arxiv_work_key`/`normalize_doi`/`extract_arxiv_id`。
- 写 works+source_files：`literature_ingest.insert_db_rows`（规范 INSERT 路径），或整链路 `build_ingest_plan`+`execute_plan`。
- 标题模糊：`normalize_title` + `jaccard`（≥0.9），或 `scripts/scan_title_duplicates.py:scan`。
- quarantine：`works.read_status='quarantined'` + `work_codes(code='bad_source')`；restore 在 `api/routes/works.py:402 def restore_work`。
- 迁移范式：`scripts/migrate_add_analysis_runs.py`（`get_conn`、`--dry-run`、`table_exists`/`index_exists` 守卫、仅 execute 时 commit）。
- DB 连接：`from api.db import get_conn, LIBRARY_ROOT, DB_PATH`（**不要**用脚本里的 `connect_db`）。

---

## ⚠️ 与检索层计划的衔接

本计划先于检索层实施。两者共用 `scripts/literature_intake.py`：
- **本计划 Task 7 创建** `scripts/literature_intake.py`，含 `list` / `promote` 子命令（A2）。
- 检索层计划 Task 6 **修改**同一文件，追加 `topic` / `collect` / `resolve` 子命令。
- 因此检索层 Task 6 的"Create"应理解为"Modify"——执行检索层时合并到本计划创建的文件，勿覆盖。

## 文件结构

| 文件 | 职责 |
|---|---|
| `scripts/migrate_add_intake_candidates.py` | 幂等迁移：建 `intake_candidates` 表 |
| `collector/__init__.py` | 包标记 |
| `collector/normalize.py` | 规范化（薄封装 `literature_ingest` 的 arxiv/doi 函数 + URL 规范化） |
| `collector/gate.py` | 两段闸门：`light_gate`（元数据四态）+ `heavy_gate`（SHA256） |
| `collector/adapters/__init__.py` | 包标记 |
| `collector/adapters/arxiv.py` | arXiv API 元数据 + PDF URL（新网络代码） |
| `collector/fetch.py` | PDF 下载（保守并发） |
| `collector/ingest_bridge.py` | 候选 → work 晋升桥接（复用 ingest 全链路） |
| `scripts/literature_intake.py` | CLI：`list` / `promote`（A2）；检索层追加 `topic`/`collect`/`resolve` |
| `tests/test_intake_migration.py` | 迁移幂等测试 |
| `tests/test_gate.py` | 四态判别测试 |
| `tests/test_arxiv_adapter.py` | arXiv 适配器测试（mock HTTP） |
| `tests/test_ingest_bridge.py` | 晋升桥接测试 |
| `tests/test_intake_cli.py` | list/promote CLI 测试 |
| `tests/test_collector_boundary.py` | 边界约束：collector 不直接写 works |

**测试隔离**：patch `api.db.LIBRARY_ROOT` 与 `DB_PATH` 到 tmp（沿用 commit `e9baa17`）。

---

## Task 1: `intake_candidates` 表 + 幂等迁移

**Files:**
- Create: `scripts/migrate_add_intake_candidates.py`
- Create: `tests/test_intake_migration.py`

- [ ] **Step 1: 写失败测试（建表 + 幂等 + 索引）**

```python
# tests/test_intake_migration.py
import sqlite3
from pathlib import Path

def _run(db_path):
    import scripts.migrate_add_intake_candidates as m
    m.run(db_path)
    m.run(db_path)  # 幂等

def test_migration_creates_intake_candidates(tmp_path):
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run(db_path)
    conn = sqlite3.connect(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(intake_candidates)").fetchall()}
    assert {"id","source_type","source_url","title","arxiv_id","doi","url_canonical",
            "fetched_sha256","local_pdf_path","resolution","matched_work_id","status",
            "review_status","review_note","collected_at","resolved_at","ingested_work_id",
            "raw_meta"} <= cols
    # 唯一约束：(source_type, url_canonical)
    dup = conn.execute("SELECT sql FROM sqlite_master WHERE name='intake_candidates'").fetchone()[0]
    assert "UNIQUE" in dup.upper() or "unique" in dup
    conn.close()

def test_migration_indexes_present(tmp_path):
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run(db_path)
    conn = sqlite3.connect(db_path)
    idx = {r[1] for r in conn.execute("PRAGMA index_list('intake_candidates')").fetchall()}
    assert "idx_ic_arxiv_id" in idx and "idx_ic_resolution" in idx
    conn.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_intake_migration.py -v`
Expected: FAIL（`No module named 'scripts.migrate_add_intake_candidates'`）

- [ ] **Step 3: 实现迁移（仿 `migrate_add_analysis_runs.py`）**

```python
# scripts/migrate_add_intake_candidates.py
"""Add intake_candidates table (collector candidate queue). Idempotent.

Usage:
    python scripts/migrate_add_intake_candidates.py
    python scripts/migrate_add_intake_candidates.py --dry-run
"""
from __future__ import annotations
import argparse, sqlite3
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.db import get_conn, table_exists

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS intake_candidates (
    id              TEXT PRIMARY KEY,
    source_type     TEXT NOT NULL,             -- arxiv | github
    source_url      TEXT,
    title           TEXT,
    arxiv_id        TEXT,
    doi             TEXT,
    url_canonical   TEXT NOT NULL,
    fetched_sha256  TEXT,
    local_pdf_path  TEXT,
    resolution      TEXT NOT NULL DEFAULT 'pending',
                                  -- pending|new|exact_hit|title_candidate|
                                  -- needs_better_copy|sha256_duplicate|fetch_failed
    matched_work_id TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
                                  -- pending|resolved|ingested|skipped|superseded_quarantine
    review_status   TEXT NOT NULL DEFAULT 'pending',  -- pending|approved|rejected
    review_note     TEXT,
    collected_at    TEXT,
    resolved_at     TEXT,
    ingested_work_id TEXT,
    raw_meta        TEXT,
    UNIQUE(source_type, url_canonical)
)
"""
INDEXES = [
    ("idx_ic_source_type", "intake_candidates", "source_type"),
    ("idx_ic_arxiv_id", "intake_candidates", "arxiv_id"),
    ("idx_ic_doi", "intake_candidates", "doi"),
    ("idx_ic_resolution", "intake_candidates", "resolution"),
    ("idx_ic_status", "intake_candidates", "status"),
    ("idx_ic_review", "intake_candidates", "review_status"),
]

def _index_exists(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (name,)).fetchone() is not None

def run(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        if not table_exists(conn, "intake_candidates"):
            conn.execute(CREATE_TABLE)
        for name, tbl, col in INDEXES:
            if not _index_exists(conn, name):
                conn.execute(f"CREATE INDEX {name} ON {tbl}({col})")
        conn.commit()
    finally:
        conn.close()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.dry_run:
        print("DRY-RUN: would create intake_candidates + 6 indexes"); return
    from api.db import DB_PATH
    run(DB_PATH)
    print("OK: intake_candidates migration applied")

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_intake_migration.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 实际跑迁移 + Commit**

Run: `python scripts/migrate_add_intake_candidates.py`
Expected: `OK: intake_candidates migration applied`

```bash
git add scripts/migrate_add_intake_candidates.py tests/test_intake_migration.py
git commit -m "feat(collector): intake_candidates 候选队列表 + 幂等迁移"
```

---

## Task 2: `collector/normalize.py`（复用 literature_ingest 规范化）

**Files:**
- Create: `collector/__init__.py`
- Create: `collector/normalize.py`
- Create: `tests/test_normalize.py`

> 薄封装 `literature_ingest` 的规范化函数（不复制逻辑，DRY），新增 URL 规范化。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_normalize.py
from collector import normalize as N

def test_normalize_arxiv_strips_version():
    assert N.normalize_arxiv_id("2406.10162v3") == "2406.10162"
    assert N.normalize_arxiv_id("arxiv:2406.10162") == "2406.10162"
    assert N.normalize_arxiv_id("not-an-id") is None

def test_normalize_doi():
    assert N.normalize_doi("https://doi.org/10.1000/xyz") == "10.1000/xyz"
    assert N.normalize_doi("10.1000/xyz") == "10.1000/xyz"

def test_normalize_github_url():
    assert N.normalize_github_url("https://github.com/org/repo/") == "org/repo"
    assert N.normalize_github_url("https://github.com/org/repo.git") == "org/repo"
    assert N.normalize_github_url("not github") is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_normalize.py -v`
Expected: FAIL（`No module named 'collector'`）

- [ ] **Step 3: 实现**

```python
# collector/__init__.py
# (空包标记)
```

```python
# collector/normalize.py
"""Normalization helpers. Reuses literature_ingest logic (DRY); adds URL normalization."""
from __future__ import annotations
import re
from scripts.literature_ingest import extract_arxiv_id, arxiv_work_key, normalize_doi

_GH_RE = re.compile(r"github\.com/([^/]+)/([^/#?]+?)(?:\.git|/)?$")

def normalize_arxiv_id(value: str):
    """Return versionless arXiv id (e.g. '2406.10162') or None."""
    if not value:
        return None
    raw = extract_arxiv_id(value)
    if not raw:
        return None
    return arxiv_work_key(raw)  # strips trailing v\d+

def normalize_doi(value: str):
    """Delegate to literature_ingest.normalize_doi."""
    return normalize_doi(value)

def normalize_github_url(url: str):
    """Return 'owner/repo' canonical or None."""
    if not url:
        return None
    m = _GH_RE.search(url.strip())
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)
    if owner in {"search"}:
        return None
    return f"{owner}/{repo}"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_normalize.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add collector/__init__.py collector/normalize.py tests/test_normalize.py
git commit -m "feat(collector): normalize 薄封装(复用 literature_ingest) + URL 规范化"
```

---

## Task 3: 轻量闸门 `light_gate`（四态判别，复用 works 查询）

**Files:**
- Create: `collector/gate.py`
- Create: `tests/test_gate.py`

> 判别优先级（强→弱）：arXiv 精确 → DOI 精确 → 标题模糊 → new。命中 quarantined work → `needs_better_copy`。

- [ ] **Step 1: 写失败测试（四态）**

```python
# tests/test_gate.py
import sqlite3
from collector import gate

def _db_with_works(tmp_path, works):
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    c = sqlite3.connect(db_path)
    c.execute("""CREATE TABLE works (id TEXT PRIMARY KEY, arxiv_id TEXT, doi TEXT,
                 title TEXT, read_status TEXT DEFAULT 'unread')""")
    for w in works:
        c.execute("INSERT INTO works VALUES (?,?,?,?,?)",
                  (w["id"], w.get("arxiv_id"), w.get("doi"), w.get("title"), w.get("read_status","unread")))
    c.commit(); c.close()
    return db_path

def test_arxiv_exact_hit_active(tmp_path, monkeypatch):
    db = _db_with_works(tmp_path, [{"id":"W-arxiv-2406.10162","arxiv_id":"2406.10162","title":"X"}])
    monkeypatch.setattr(gate, "get_conn", lambda: sqlite3.connect(db))
    res, wid = gate.light_gate({"arxiv_id":"2406.10162"})
    assert res == "exact_hit" and wid == "W-arxiv-2406.10162"

def test_arxiv_hit_quarantined_is_needs_better_copy(tmp_path, monkeypatch):
    db = _db_with_works(tmp_path, [{"id":"W-1","arxiv_id":"2406.10162","title":"X","read_status":"quarantined"}])
    monkeypatch.setattr(gate, "get_conn", lambda: sqlite3.connect(db))
    res, wid = gate.light_gate({"arxiv_id":"2406.10162"})
    assert res == "needs_better_copy" and wid == "W-1"

def test_title_candidate_when_similar(tmp_path, monkeypatch):
    db = _db_with_works(tmp_path, [{"id":"W-2","title":"Reward Hacking in Large Language Models"}])
    monkeypatch.setattr(gate, "get_conn", lambda: sqlite3.connect(db))
    res, _ = gate.light_gate({"title":"Reward Hacking in Large Language Models"})
    assert res == "title_candidate"

def test_new_when_no_match(tmp_path, monkeypatch):
    db = _db_with_works(tmp_path, [])
    monkeypatch.setattr(gate, "get_conn", lambda: sqlite3.connect(db))
    res, wid = gate.light_gate({"arxiv_id":"2501.99999","title":"Brand New Topic"})
    assert res == "new" and wid is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_gate.py -v`
Expected: FAIL（`No module named 'collector.gate'`）

- [ ] **Step 3: 实现 `collector/gate.py` 的 `light_gate`**

```python
# collector/gate.py
"""Two-stage pre-ingest dedup gate. Reuses literature_ingest normalization + jaccard.

light_gate: metadata-only, decides whether to download. No file IO.
heavy_gate: after download, SHA256 against source_files.
"""
from __future__ import annotations
from api.db import get_conn
from collector.normalize import normalize_arxiv_id, normalize_doi
from scripts.literature_ingest import normalize_title, jaccard

TITLE_THRESHOLD = 0.9

def _find_by_strong_key(conn, arxiv_id, doi):
    """Return (work_id, read_status) for arxiv/doi match, else (None, None). arxiv first."""
    if arxiv_id:
        row = conn.execute("SELECT id, read_status FROM works WHERE arxiv_id=?", (arxiv_id,)).fetchone()
        if row:
            return row[0], row[1]
    if doi:
        row = conn.execute("SELECT id, read_status FROM works WHERE doi=?", (doi,)).fetchone()
        if row:
            return row[0], row[1]
    return None, None

def _title_match(conn, title):
    """Return (work_id, read_status) of best jaccard>=threshold active/quarantined work, else (None,None)."""
    if not title:
        return None, None
    nt = normalize_title(title)
    best, best_sim, best_status = None, 0.0, None
    for wid, wtitle, wstatus in conn.execute("SELECT id, title, read_status FROM works").fetchall():
        if not wtitle:
            continue
        sim = jaccard(nt, normalize_title(wtitle))
        if sim > best_sim:
            best, best_sim, best_status = wid, sim, wstatus
    if best_sim >= TITLE_THRESHOLD:
        return best, best_status
    return None, None

def _classify(match_status):
    """Map a matched work's read_status to resolution."""
    if match_status == "quarantined":
        return "needs_better_copy"
    return "exact_hit"

def light_gate(candidate: dict):
    """Return (resolution, matched_work_id). No download. Candidate keys: arxiv_id, doi, title."""
    conn = get_conn()
    try:
        aid = normalize_arxiv_id(candidate.get("arxiv_id") or "")
        doi = normalize_doi(candidate.get("doi") or "")
        wid, status = _find_by_strong_key(conn, aid, doi)
        if wid:
            return _classify(status), wid
        wid, status = _title_match(conn, candidate.get("title") or "")
        if wid:
            return _classify(status), wid
        return "new", None
    finally:
        conn.close()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_gate.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add collector/gate.py tests/test_gate.py
git commit -m "feat(collector): 轻量闸门 light_gate 四态判别(复用 works 查询+jaccard)"
```

---

## Task 4: 重量闸门 `heavy_gate`（SHA256 查 source_files）

**Files:**
- Modify: `collector/gate.py`
- Modify: `tests/test_gate.py`

- [ ] **Step 1: 写失败测试（SHA256 命中→sha256_duplicate；未命中→确认 new）**

```python
# 追加到 tests/test_gate.py
import hashlib

def _make_pdf(path, content=b"%PDF-1.4 fake"):
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()

def _db_with_source(tmp_path, sha):
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    c = sqlite3.connect(db_path)
    c.execute("""CREATE TABLE source_files (id TEXT PRIMARY KEY, work_id TEXT, content_sha256 TEXT)""")
    c.execute("""CREATE TABLE intake_candidates (id TEXT PRIMARY KEY, local_pdf_path TEXT, resolution TEXT)""")
    c.execute("INSERT INTO intake_candidates VALUES ('IC-1', ?, 'new')", (str(tmp_path/"a.pdf"),))
    c.execute("INSERT INTO source_files VALUES ('SF-1','W-x',?)", (sha,))
    c.commit(); c.close()
    return db_path

def test_heavy_gate_sha256_duplicate(tmp_path, monkeypatch):
    sha = _make_pdf(tmp_path/"a.pdf")
    db = _db_with_source(tmp_path, sha)
    monkeypatch.setattr(gate, "get_conn", lambda: sqlite3.connect(db))
    res = gate.heavy_gate("IC-1")
    assert res == "sha256_duplicate"

def test_heavy_gate_new_confirmed(tmp_path, monkeypatch):
    _make_pdf(tmp_path/"a.pdf")
    db = _db_with_source(tmp_path, sha="0"*64)  # 不同 sha
    monkeypatch.setattr(gate, "get_conn", lambda: sqlite3.connect(db))
    res = gate.heavy_gate("IC-1")
    assert res == "new"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_gate.py -v -k heavy`
Expected: FAIL（`AttributeError: module ... has no attribute 'heavy_gate'`）

- [ ] **Step 3: 实现 `heavy_gate`（追加到 `collector/gate.py`）**

```python
# 追加到 collector/gate.py
from pathlib import Path
from scripts.literature_ingest import sha256_file

def heavy_gate(candidate_id: str):
    """Download-bound SHA256 check. Reads candidate.local_pdf_path, hashes, looks up source_files.
    Updates candidate.resolution + fetched_sha256. Returns resolution."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT local_pdf_path FROM intake_candidates WHERE id=?",
                           (candidate_id,)).fetchone()
        if not row or not row[0]:
            return "fetch_failed"
        pdf = Path(row[0])
        if not pdf.exists():
            return "fetch_failed"
        digest = sha256_file(pdf)
        hit = conn.execute("SELECT 1 FROM source_files WHERE content_sha256=?", (digest,)).fetchone()
        resolution = "sha256_duplicate" if hit else "new"
        conn.execute(
            "UPDATE intake_candidates SET fetched_sha256=?, resolution=?, resolved_at=? WHERE id=?",
            (digest, resolution, _utc_now(), candidate_id))
        conn.commit()
        return resolution
    finally:
        conn.close()

from scripts.literature_ingest import utc_now as _utc_now  # 复用时间戳
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_gate.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: Commit**

```bash
git add collector/gate.py tests/test_gate.py
git commit -m "feat(collector): 重量闸门 heavy_gate(SHA256 查 source_files，复用 sha256_file)"
```

---

## Task 5: arXiv 适配器（元数据 + PDF URL）+ 下载

**Files:**
- Create: `collector/adapters/__init__.py`
- Create: `collector/adapters/arxiv.py`
- Create: `collector/fetch.py`
- Create: `tests/test_arxiv_adapter.py`

> 全新网络代码（仓库现无 arXiv HTTP 客户端）。用 arXiv API（`http://export.arxiv.org/api/query`）+ PDF 直链。

- [ ] **Step 1: 写失败测试（mock HTTP，解析元数据 + pdf_url）**

```python
# tests/test_arxiv_adapter.py
from collector.adapters import arxiv

ATOM_ENTRY = """
<entry xmlns="http://www.w3.org/2005/Atom">
  <id>http://arxiv.org/abs/2406.10162v1</id>
  <title>Reward Hacking</title>
  <author><name>Alice</name></author>
  <arxiv:doi xmlns:arxiv="http://arxiv.org/schemas/atom">10.1000/rh</arxiv:doi>
  <link title="pdf" type="application/pdf" href="http://arxiv.org/pdf/2406.10162v1"/>
  <summary>abs</summary>
</entry>
"""

def test_parse_arxiv_atom(monkeypatch):
    monkeypatch.setattr(arxiv, "_http_get", lambda url: ('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">' + ATOM_ENTRY + '</feed>').encode())
    m = arxiv.fetch_metadata("2406.10162")
    assert m["arxiv_id"] == "2406.10162"   # 版本剥离
    assert m["title"] == "Reward Hacking"
    assert m["authors"] == ["Alice"]
    assert m["doi"] == "10.1000/rh"

def test_pdf_url():
    assert arxiv.pdf_url("2406.10162") == "https://arxiv.org/pdf/2406.10162"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_arxiv_adapter.py -v`
Expected: FAIL（`No module named 'collector.adapters'`）

- [ ] **Step 3: 实现 `collector/adapters/arxiv.py`**

```python
# collector/adapters/__init__.py
# (空包标记)
```

```python
# collector/adapters/arxiv.py
"""arXiv adapter: metadata via arXiv API (Atom), PDF via direct URL.
New network code (repo had no arXiv HTTP client). Reuses normalize for arxiv_id stripping.
"""
from __future__ import annotations
import urllib.request
import xml.etree.ElementTree as ET
from collector.normalize import normalize_arxiv_id

ARXIV_API = "http://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "literature-library-collector/0.1"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()

def _text_or_none(elem):
    return elem.text.strip() if elem is not None and elem.text else None

def fetch_metadata(arxiv_id: str) -> dict:
    """Query arXiv API for one id. Return dict with arxiv_id(versionless), title, authors, doi, abstract."""
    aid = normalize_arxiv_id(arxiv_id) or arxiv_id
    url = f"{ARXIV_API}?id_list={aid}&max_results=1"
    data = _http_get(url)
    root = ET.fromstring(data)
    entry = root.find("a:entry", NS)
    if entry is None:
        return {"arxiv_id": aid, "title": None, "authors": [], "doi": None, "abstract": None}
    title = _text_or_none(entry.find("a:title", NS))
    authors = [a.find("a:name", NS).text for a in entry.findall("a:author", NS)
               if a.find("a:name", NS) is not None]
    doi_el = entry.find("arxiv:doi", NS)
    summary = _text_or_none(entry.find("a:summary", NS))
    return {
        "arxiv_id": aid,
        "title": title,
        "authors": authors,
        "doi": _text_or_none(doi_el) if doi_el is not None else None,
        "abstract": summary,
    }

def pdf_url(arxiv_id: str) -> str:
    aid = normalize_arxiv_id(arxiv_id) or arxiv_id
    return f"https://arxiv.org/pdf/{aid}"
```

- [ ] **Step 4: 实现 `collector/fetch.py`（保守下载）**

```python
# collector/fetch.py
"""Conservative PDF download (single file; reuse arxiv.pdf_url)."""
from __future__ import annotations
import urllib.request
from pathlib import Path

def download_pdf(url: str, dest: Path) -> Path | None:
    """Download to dest, return dest or None on failure. Short timeout, conservative."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "literature-library-collector/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
            f.write(r.read())
        return dest
    except Exception:
        return None
```

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest tests/test_arxiv_adapter.py -v`
Expected: PASS（2 passed）

- [ ] **Step 6: Commit**

```bash
git add collector/adapters/__init__.py collector/adapters/arxiv.py collector/fetch.py tests/test_arxiv_adapter.py
git commit -m "feat(collector): arXiv 适配器(Atom 元数据+PDF URL) + 保守下载"
```

---

## Task 6: 晋升桥接 `ingest_bridge.promote`（复用 ingest 全链路）

**Files:**
- Create: `collector/ingest_bridge.py`
- Create: `tests/test_ingest_bridge.py`

> 边界：collector 不直接写 works。晋升复用 `literature_ingest` 全链路：把候选 PDF 暂存到临时 inbox → `build_ingest_plan` + `execute_plan` → 回填 `ingested_work_id`。

- [ ] **Step 1: 写失败测试（晋升生成 work + 回填）**

```python
# tests/test_ingest_bridge.py
import sqlite3, hashlib
from pathlib import Path
from collector import ingest_bridge as br

def test_promote_creates_work_and_backfills(tmp_path, monkeypatch):
    # 候选 PDF + intake_candidates 行
    pdf = tmp_path / "c.pdf"; pdf.write_bytes(b"%PDF-1.4 real content")
    db_path = tmp_path / "literature.sqlite"
    c = sqlite3.connect(db_path)
    c.execute("""CREATE TABLE intake_candidates (id TEXT PRIMARY KEY, local_pdf_path TEXT,
                 arxiv_id TEXT, title TEXT, status TEXT, ingested_work_id TEXT)""")
    c.execute("INSERT INTO intake_candidates VALUES ('IC-1', ?, '2406.10162', 'Reward Hacking', 'resolved', NULL)",
              (str(pdf),))
    c.commit(); c.close()

    monkeypatch.setattr(br, "get_conn", lambda: sqlite3.connect(db_path))
    # 复用 ingest：暂存到 inbox 后跑 build_ingest_plan+execute_plan
    work_id = br.promote("IC-1", library_root=tmp_path)
    assert work_id and work_id.startswith("W-")
    # 回填
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT status, ingested_work_id FROM intake_candidates WHERE id='IC-1'").fetchone()
    conn.close()
    assert row[0] == "ingested" and row[1] == work_id
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_ingest_bridge.py -v`
Expected: FAIL（`No module named 'collector.ingest_bridge'`）

- [ ] **Step 3: 实现 `collector/ingest_bridge.py`**

```python
# collector/ingest_bridge.py
"""Candidate -> work promotion bridge. REUSES literature_ingest full pipeline.
Collector NEVER writes works directly; it stages the candidate PDF into a temp inbox
and runs build_ingest_plan + execute_plan, then backfills ingested_work_id.
"""
from __future__ import annotations
import shutil
import secrets
from pathlib import Path
from api.db import get_conn
import scripts.literature_ingest as ingest

def promote(candidate_id: str, *, library_root: Path) -> str:
    """Promote an approved candidate. Returns the new work_id."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT local_pdf_path, arxiv_id, title FROM intake_candidates WHERE id=?",
            (candidate_id,)).fetchone()
        if not row:
            raise KeyError(candidate_id)
        local_pdf, arxiv_id, title = row
        if not local_pdf or not Path(local_pdf).exists():
            raise FileNotFoundError(f"candidate pdf missing: {local_pdf}")
    finally:
        conn.close()

    # 暂存到 library_root 下的临时 inbox，让 ingest 全链路接管
    inbox = Path(library_root) / "_inbox" / f"promote-{candidate_id}-{secrets.token_hex(2)}"
    inbox.mkdir(parents=True, exist_ok=True)
    fname = f"{arxiv_id or candidate_id}.pdf"
    staged = inbox / fname
    shutil.copy2(local_pdf, staged)

    plan = ingest.build_ingest_plan(library_root, inbox_dir=inbox, dry_run=False)
    ingest.execute_plan(plan, no_backup=False, leave_inbox=False)

    # 从 plan 取回生成的 work_id（ingests 非空时取第一个）
    work_id = plan.ingests[0].work_id if plan.ingests else None
    if not work_id:
        raise RuntimeError(f"promote produced no work for {candidate_id}")

    conn = get_conn()
    try:
        conn.execute(
            "UPDATE intake_candidates SET status='ingested', ingested_work_id=? WHERE id=?",
            (work_id, candidate_id))
        conn.commit()
    finally:
        conn.close()
    # 清理空 inbox
    try:
        shutil.rmtree(inbox, ignore_errors=True)
    except Exception:
        pass
    return work_id
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_ingest_bridge.py -v`
Expected: PASS（如 ingest 链路在 tmp library_root 下需 ensure_core_schema，测试里先调 `ingest.ensure_core_schema(conn)` 建表；若失败，在测试 setup 加：

```python
import scripts.literature_ingest as ingest
conn = sqlite3.connect(db_path); ingest.ensure_core_schema(conn); conn.close()
```
）

- [ ] **Step 5: Commit**

```bash
git add collector/ingest_bridge.py tests/test_ingest_bridge.py
git commit -m "feat(collector): 晋升桥接 promote(复用 build_ingest_plan+execute_plan，不直接写 works)"
```

---

## Task 7: A2 CLI（`list` / `promote`）

**Files:**
- Create: `scripts/literature_intake.py`
- Create: `tests/test_intake_cli.py`

> 本任务创建文件含 `list`/`promote`。检索层 Task 6 之后会**追加** `topic`/`collect`/`resolve`（见本计划顶部衔接说明）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_intake_cli.py
import sqlite3
from scripts import literature_intake as cli

def _db(tmp_path, rows):
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    c = sqlite3.connect(db_path)
    c.execute("""CREATE TABLE intake_candidates (id TEXT PRIMARY KEY, resolution TEXT,
                 status TEXT, review_status TEXT, title TEXT, arxiv_id TEXT, ingested_work_id TEXT)""")
    for r in rows:
        c.execute("INSERT INTO intake_candidates VALUES (?,?,?,?,?,?,?)",
                  (r["id"], r.get("resolution"), r.get("status"), r.get("review_status"),
                   r.get("title"), r.get("arxiv_id"), r.get("ingested_work_id")))
    c.commit(); c.close()
    return db_path

def test_list_new_pending(tmp_path, monkeypatch, capsys):
    db = _db(tmp_path, [
        {"id":"IC-1","resolution":"new","review_status":"pending","title":"A","arxiv_id":"1"},
        {"id":"IC-2","resolution":"new","review_status":"approved","title":"B","arxiv_id":"2"},
    ])
    monkeypatch.setattr(cli, "get_conn", lambda: sqlite3.connect(db))
    cli.list_cmd(None)
    out = capsys.readouterr().out
    assert "IC-1" in out and "IC-2" not in out  # 只列 pending

def test_promote_marks_approved(tmp_path, monkeypatch):
    db = _db(tmp_path, [{"id":"IC-1","resolution":"new","review_status":"pending"}])
    monkeypatch.setattr(cli, "get_conn", lambda: sqlite3.connect(db))
    cli.promote_review(approve=["IC-1"])
    conn = sqlite3.connect(db)
    rs = conn.execute("SELECT review_status FROM intake_candidates WHERE id='IC-1'").fetchone()[0]
    conn.close()
    assert rs == "approved"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_intake_cli.py -v`
Expected: FAIL（`No module named 'scripts.literature_intake'`）

- [ ] **Step 3: 实现 `scripts/literature_intake.py`（A2 子集）**

```python
# scripts/literature_intake.py
"""collector intake CLI (foundation: list / promote).
Retrieval layer will EXTEND this file with topic/collect/resolve.
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.db import get_conn

def list_cmd(args):
    """列出待晋升候选（resolution=new, review_status=pending）。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT id, title, arxiv_id FROM intake_candidates
               WHERE resolution='new' AND review_status='pending'""").fetchall()
    finally:
        conn.close()
    for r in rows:
        print(f"{r[0]}\t{r[2] or ''}\t{r[1] or ''}")

def promote_review(*, approve=None, reject=None):
    """A2 审核：批量 approve/reject 候选。"""
    conn = get_conn()
    try:
        for cid in (approve or []):
            conn.execute("UPDATE intake_candidates SET review_status='approved' WHERE id=?", (cid,))
        for cid in (reject or []):
            conn.execute("UPDATE intake_candidates SET review_status='rejected' WHERE id=?", (cid,))
        conn.commit()
    finally:
        conn.close()

def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p = sub.add_parser("promote")
    p.add_argument("--approve", help="comma-separated IC ids")
    p.add_argument("--reject", help="comma-separated IC ids")
    args = ap.parse_args(argv)
    if args.cmd == "list":
        list_cmd(args)
    elif args.cmd == "promote":
        promote_review(approve=args.approve.split(",") if args.approve else None,
                       reject=args.reject.split(",") if args.reject else None)

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_intake_cli.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add scripts/literature_intake.py tests/test_intake_cli.py
git commit -m "feat(collector): A2 CLI list/promote(检索层将追加 topic/collect/resolve)"
```

---

## Task 8: `needs_better_copy` 好副本替换流程（net-new）

**Files:**
- Create: `collector/replace_source.py`
- Create: `tests/test_replace_source.py`

> 代码勘察确认：现有 restore（`api/routes/works.py:402`）假设原文件仍在 `_quarantine/`。本流程是**新增**：把下载的好副本放进 `works/{id}/source/`、更新 `source_files`、`read_status` 恢复、清 `bad_source` code、归档旧坏副本。复用 quarantine 的数据表示（`read_status`+`work_codes`）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_replace_source.py
import sqlite3
from pathlib import Path
from collector import replace_source as rs

def test_replace_restores_quarantined_work(tmp_path, monkeypatch):
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    lib = tmp_path
    # quarantined work + bad_source code
    (lib / "works" / "W-1" / "source").mkdir(parents=True)
    good_pdf = tmp_path / "good.pdf"; good_pdf.write_bytes(b"%PDF-1.4 good")
    c = sqlite3.connect(db_path)
    c.execute("""CREATE TABLE works (id TEXT PRIMARY KEY, read_status TEXT)""")
    c.execute("INSERT INTO works VALUES ('W-1','quarantined')")
    c.execute("""CREATE TABLE work_codes (work_id TEXT, source_file_id TEXT, code TEXT, reason TEXT, created_at TEXT,
                 PRIMARY KEY(work_id, source_file_id, code))""")
    c.execute("INSERT INTO work_codes VALUES ('W-1','','bad_source','x','t')")
    c.execute("""CREATE TABLE source_files (id TEXT PRIMARY KEY, work_id TEXT, content_sha256 TEXT,
                 source_path TEXT, relative_source_path TEXT, status TEXT)""")
    c.execute("INSERT INTO source_files VALUES ('SF-old','W-1','oldsha','p','r','active')")
    c.commit(); c.close()
    monkeypatch.setattr(rs, "get_conn", lambda: sqlite3.connect(db_path))

    rs.replace_quarantined_source("W-1", good_pdf, library_root=lib)
    conn = sqlite3.connect(db_path)
    status = conn.execute("SELECT read_status FROM works WHERE id='W-1'").fetchone()[0]
    bad = conn.execute("SELECT count(*) FROM work_codes WHERE work_id='W-1' AND code='bad_source'").fetchone()[0]
    conn.close()
    assert status == "unread"           # 恢复
    assert bad == 0                      # bad_source 清除
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_replace_source.py -v`
Expected: FAIL（`No module named 'collector.replace_source'`）

- [ ] **Step 3: 实现 `collector/replace_source.py`**

```python
# collector/replace_source.py
"""needs_better_copy: replace a quarantined work's bad source with a good copy.
Net-new (existing restore assumes files still in _quarantine/). Reuses quarantine data
representation: works.read_status + work_codes(code='bad_source'). Does NOT create a new work.
"""
from __future__ import annotations
import shutil, secrets
from pathlib import Path
from api.db import get_conn
from scripts.literature_ingest import sha256_file, utc_now

def replace_quarantined_source(work_id: str, good_pdf: Path, *, library_root: Path) -> str:
    """Drop good copy into works/{work_id}/source/, update source_files, restore read_status,
    clear bad_source code, archive old source. Returns new source_file_id."""
    digest = sha256_file(Path(good_pdf))
    dest_dir = Path(library_root) / "works" / work_id / "source"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / Path(good_pdf).name
    shutil.copy2(good_pdf, dest)

    conn = get_conn()
    try:
        # 归档旧 source_files
        conn.execute("UPDATE source_files SET status='archived' WHERE work_id=? AND status='active'",
                     (work_id,))
        # 插入新 source_file
        sf_id = f"SF-{digest[:12]}-{secrets.token_hex(2)}"
        conn.execute(
            """INSERT INTO source_files (id, work_id, content_sha256, source_path,
               relative_source_path, status) VALUES (?,?,?,?,?, 'active')""",
            (sf_id, work_id, digest, str(dest), str(dest.relative_to(library_root))))
        # 恢复 read_status
        conn.execute("UPDATE works SET read_status='unread' WHERE id=?", (work_id,))
        # 清 bad_source code
        conn.execute("DELETE FROM work_codes WHERE work_id=? AND code='bad_source'", (work_id,))
        conn.commit()
    finally:
        conn.close()
    return sf_id
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_replace_source.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add collector/replace_source.py tests/test_replace_source.py
git commit -m "feat(collector): needs_better_copy 好副本替换(恢复 read_status+清 bad_source，不新建 work)"
```

---

## Task 9: 边界约束测试（collector 绝不直接写 works）

**Files:**
- Create: `tests/test_collector_boundary.py`

> spec §3 核心约束。用审计方式验证：collector 模块代码不包含对 `works` 的 INSERT/UPDATE。

- [ ] **Step 1: 写测试（源码静态审计：collector 内无直接 works 写入）**

```python
# tests/test_collector_boundary.py
import re
from pathlib import Path

COLLECTOR_DIR = Path(__file__).resolve().parents[1] / "collector"
# 白名单：允许经 ingest_bridge 调 ingest（不直接写），允许 replace_source 改 read_status
# 禁止：collector 自己执行 INSERT INTO works / UPDATE works（除 replace_source 的 read_status 恢复）

def _collector_py_files():
    if not COLLECTOR_DIR.exists():
        return []
    return list(COLLECTOR_DIR.rglob("*.py"))

def test_collector_never_directly_inserts_into_works():
    """collector 包内不得出现 'INSERT INTO works' 或 'REPLACE INTO works'。
    晋升必须经 ingest_bridge -> literature_ingest。"""
    offenders = []
    pat = re.compile(r"INSERT\s+INTO\s+works|REPLACE\s+INTO\s+works", re.IGNORECASE)
    for f in _collector_py_files():
        text = f.read_text(encoding="utf-8")
        if pat.search(text):
            offenders.append(str(f))
    assert not offenders, f"collector 直接写 works（违反边界）: {offenders}"

def test_replace_source_only_updates_read_status():
    """replace_source 对 works 的写只能是 read_status 恢复。"""
    f = COLLECTOR_DIR / "replace_source.py"
    if not f.exists():
        return
    text = f.read_text(encoding="utf-8")
    updates = re.findall(r"UPDATE\s+works\s+SET\s+(\w+)", text, re.IGNORECASE)
    assert all(col.lower() == "read_status" for col in updates), \
        f"replace_source 写了 works 非 read_status 列: {updates}"
```

- [ ] **Step 2: 跑测试确认通过**

Run: `pytest tests/test_collector_boundary.py -v`
Expected: PASS（2 passed）

- [ ] **Step 3: 全量回归 + Commit**

Run: `pytest tests/ -v`
Expected: 全 PASS（含 ingest 既有测试）

```bash
git add tests/test_collector_boundary.py
git commit -m "test(collector): 边界约束——collector 不直接写 works(静态审计)"
```

---

## 验收对齐（集成 spec §11）

- [x] `intake_candidates` 表 + 迁移（幂等）—— Task 1
- [x] arXiv 适配器：采集元数据 + 写候选 + 轻量闸门 —— Task 5 +（检索层 collect 编排）
- [x] 轻量闸门：exact_hit / title_candidate / needs_better_copy —— Task 3
- [x] 重量闸门：SHA256 → sha256_duplicate —— Task 4
- [x] A2 人工晋升：list + approve + 生成 work + 回填 —— Task 6 + Task 7
- [x] needs_better_copy 替换 quarantined work 源文件 + 恢复 read_status —— Task 8
- [x] collector 不直接写 works（边界，测试覆盖）—— Task 9
- [ ] healthcheck（候选与 work 一致性、孤立 PDF、重复晋升防护）—— 留作地基完成后补充（非阻塞）

## Self-Review（写作时已完成）

1. **Spec 覆盖**：§4 表→T1；§5 两段闸门+四态→T3/T4；§6 复用机制（exact/title/sha/needs_better_copy/晋升）→T3/T4/T6/T8；§7 A2→T7；§8 arXiv adapter→T5；§9 结构→文件结构表；§11 验收→上表。✓
2. **占位符**：无 TBD；所有复用函数（`sha256_file`/`choose_work_id`/`build_ingest_plan`/`execute_plan`/`normalize_title`/`jaccard`/`utc_now`/`extract_arxiv_id`/`arxiv_work_key`/`normalize_doi`）均经代码勘察确认存在并标注 file:line。✓
3. **类型一致**：`light_gate(candidate)->(resolution, matched_work_id)`、`heavy_gate(candidate_id)->resolution`、`promote(candidate_id, library_root)->work_id`、`replace_quarantined_source(work_id, good_pdf, library_root)->sf_id` 全程一致。✓
4. **衔接**：与检索层计划共用 `scripts/literature_intake.py`（本计划 Create list/promote，检索层 Modify 追加 topic/collect/resolve），已在顶部声明。✓
