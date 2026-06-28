# tests/test_collect_once.py
"""collect_once 编排 nucleus 测试。桩 3 个发现入口 + light_gate，不触网络。"""
from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """temp DB + patch collector 各模块 get_conn。"""
    db = tmp_path / "literature.sqlite"
    # 复用 intake 迁移建 collection_topics + intake_candidates
    mig = importlib.import_module("scripts.migrate_add_collection_topics")
    mig.run(str(db))
    mig_c = importlib.import_module("scripts.migrate_add_intake_candidates")
    mig_c.run(str(db))

    import collector.collect as collect_mod
    import collector.candidate_store as cs
    import collector.gate as gate
    import collector.topics as topics

    def _conn():
        c = sqlite3.connect(str(db)); c.row_factory = sqlite3.Row; return c

    for m in (collect_mod, cs, gate, topics):
        monkeypatch.setattr(m, "get_conn", _conn)
    return db


def _insert_candidate(conn, cid, *, arxiv_id="x", title="t", resolution="pending"):
    """辅助：把一个候选行真正写进 intake_candidates（collect_once 的 UPDATE 才能命中）。"""
    conn.execute(
        """INSERT OR REPLACE INTO intake_candidates
           (id, source_type, url_canonical, title, arxiv_id, doi, resolution, review_status, status)
           VALUES (?, 'arxiv', ?, ?, ?, NULL, ?, 'pending', 'pending')""",
        (cid, f"https://arxiv.org/abs/{arxiv_id}", title, arxiv_id, resolution),
    )
    conn.commit()


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
        # 真正把候选写进 DB（collect_once 的 UPDATE 才能命中、断言才能读回）
        conn = collect_mod.get_conn()
        try:
            _insert_candidate(conn, "C1", arxiv_id=ids[0], title="t", resolution="pending")
        finally:
            conn.close()
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
    """直接给 explicit_ids + github_urls：分别委托 collect_explicit / collect_repo_paper。"""
    import collector.collect as collect_mod

    def fake_explicit(ids, *, source_type="arxiv", collection_topic_id=None):
        conn = collect_mod.get_conn()
        try:
            _insert_candidate(conn, "C2", arxiv_id=ids[0], title="t", resolution="pending")
        finally:
            conn.close()
        return [{"id": "C2", "arxiv_id": ids[0], "title": "t", "resolution": "pending"}]

    def fake_seeds(*a, **k):
        return []

    def fake_repo(url, *, collection_topic_id=None):
        conn = collect_mod.get_conn()
        try:
            _insert_candidate(conn, "C3", arxiv_id="repo", title="repo", resolution="new")
        finally:
            conn.close()
        return {"id": "C3", "resolution": "new"}

    monkeypatch.setattr(collect_mod, "collect_explicit", fake_explicit)
    monkeypatch.setattr(collect_mod, "collect_from_seeds", fake_seeds)
    monkeypatch.setattr(collect_mod, "collect_repo_paper", fake_repo)
    monkeypatch.setattr(collect_mod, "light_gate", lambda m: ("new", None))

    result = collect_mod.collect_once(explicit_ids=["2501.22222"],
                                      github_urls=["https://github.com/x/y"])
    assert result["created"] >= 2


def test_collect_once_unknown_topic_raises(temp_db, monkeypatch):
    """topic_id 不存在 → ValueError（API 端会转 400）。"""
    import collector.collect as collect_mod
    monkeypatch.setattr(collect_mod, "collect_explicit", lambda *a, **k: [])
    monkeypatch.setattr(collect_mod, "collect_from_seeds", lambda *a, **k: [])
    monkeypatch.setattr(collect_mod, "light_gate", lambda m: ("new", None))
    with pytest.raises(ValueError):
        collect_mod.collect_once(topic_id="CT-nope")


def test_collect_once_skips_gate_for_non_pending(temp_db, monkeypatch):
    """已是 resolution!='pending' 的候选（如 github 自带 'new'）不跑 light_gate。"""
    import collector.collect as collect_mod
    gated = {"n": 0}

    def fake_explicit(ids, *, source_type="arxiv", collection_topic_id=None):
        conn = collect_mod.get_conn()
        try:
            _insert_candidate(conn, "C4", arxiv_id=ids[0], title="t", resolution="new")
        finally:
            conn.close()
        return [{"id": "C4", "arxiv_id": ids[0], "title": "t", "resolution": "new"}]

    def fake_gate(meta):
        gated["n"] += 1
        return "new", None

    monkeypatch.setattr(collect_mod, "collect_explicit", fake_explicit)
    monkeypatch.setattr(collect_mod, "collect_from_seeds", lambda *a, **k: [])
    monkeypatch.setattr(collect_mod, "light_gate", fake_gate)

    collect_mod.collect_once(explicit_ids=["2501.33333"])
    assert gated["n"] == 0  # 非 pending，不跑闸门
