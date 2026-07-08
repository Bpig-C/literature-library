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

    Function-scoped (not session) on purpose: a session-scoped patch.object on
    shared module symbols (collector.*.get_conn) would stay armed across other
    test files in the same pytest session and silently rebind their get_conn to
    our temp DB. Per-function teardown restores the originals between tests.
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
    # Uses _conn() directly (not the patched get_conn symbol) so seeding is
    # independent of the function-scoped _patch_get_conn fixture's ordering.
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
         None, "new", "pending", None, "CT-1", "2026-06-28T00:00:04"),
        ("IC-bbbb", "arxiv", "https://arxiv.org/abs/2501.00002", "Paper Two", "2501.00002",
         None, "exact_hit", "pending", "W-existing", None, "2026-06-28T00:00:03"),
        ("IC-cccc", "github", "https://github.com/x/y", "Repo Paper", None,
         None, "needs_better_copy", "approved", "W-quar", None, "2026-06-28T00:00:02"),
        ("IC-dddd", "arxiv", "https://arxiv.org/abs/2501.00003", "Paper Three", "2501.00003",
         None, "new", "rejected", None, "CT-1", "2026-06-28T00:00:01"),
        ("IC-eeee", "arxiv", "https://arxiv.org/abs/2501.00005", "Paper Five", "2501.00005",
         None, "new", "approved", None, "CT-1", "2026-06-28T00:00:00"),
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
    # 前端默认 inbox 视图 = pending；API 本身 review_status 默认 None（全部），
    # 由调用方显式传 review_status=pending。
    r = client.get("/api/intake/candidates", params={"review_status": "pending"})
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()["candidates"]]
    assert set(ids) == {"IC-aaaa", "IC-bbbb"}


def test_list_candidates_no_filter_returns_all():
    # review_status 默认 None → 不过滤，返回全部审核态
    r = client.get("/api/intake/candidates")
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()["candidates"]]
    assert set(ids) == {"IC-aaaa", "IC-bbbb", "IC-cccc", "IC-dddd", "IC-eeee"}


def test_list_candidates_filter_resolution():
    r = client.get("/api/intake/candidates", params={"resolution": "needs_better_copy"})
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()["candidates"]]
    assert ids == ["IC-cccc"]


def test_list_candidates_filter_topic():
    r = client.get("/api/intake/candidates", params={"topic": "CT-1"})
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()["candidates"]]
    assert set(ids) == {"IC-aaaa", "IC-dddd", "IC-eeee"}


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
    assert s["resolution"]["new"] == 3          # IC-aaaa, IC-dddd, IC-eeee
    assert s["resolution"]["exact_hit"] == 1
    assert s["resolution"]["needs_better_copy"] == 1
    assert s["review"]["pending"] == 2
    assert s["review"]["approved"] == 2         # IC-cccc, IC-eeee
    assert s["review"]["rejected"] == 1


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


def test_promote_only_approved_delegates_to_bridge(monkeypatch):
    # A2 守卫：只有 review_status=approved 的候选才 promote（IC-eeee，resolution=new）；
    # 未 approved（IC-aaaa pending / IC-dddd rejected）进 failed，且不调 ingest_bridge
    import collector.ingest_bridge as br
    calls = []
    def fake_promote(cid, *, library_root):
        calls.append((cid, str(library_root)))
        return f"W-{cid[-4:]}"
    monkeypatch.setattr(br, "promote", fake_promote)
    r = client.post("/api/intake/promote", json={"ids": ["IC-eeee", "IC-aaaa", "IC-dddd"]})
    assert r.status_code == 200
    body = r.json()
    assert body["promoted"] == [{"id": "IC-eeee", "work_id": "W-eeee"}]
    assert {f["id"] for f in body["failed"]} == {"IC-aaaa", "IC-dddd"}
    assert [c[0] for c in calls] == ["IC-eeee"]   # ingest_bridge 只被 approved 候选调用
    assert calls[0][1] == str(_tmp_dir)            # 用 patched LIBRARY_ROOT


def test_promote_rejects_needs_better_copy(monkeypatch):
    # P1-03: needs_better_copy 候选即使 approved 也不走 ingest_bridge（否则会建重复 work）。
    # 安全拦截：进 failed，不调 ingest_bridge，不创建 work。replace 能力为 V1 后续。
    import collector.ingest_bridge as br
    calls = []
    def fake_promote(cid, *, library_root):
        calls.append(cid)
        return f"W-{cid[-4:]}"
    monkeypatch.setattr(br, "promote", fake_promote)
    r = client.post("/api/intake/promote", json={"ids": ["IC-cccc"]})
    assert r.status_code == 200
    body = r.json()
    assert body["promoted"] == []
    assert len(body["failed"]) == 1 and body["failed"][0]["id"] == "IC-cccc"
    assert "needs_better_copy" in body["failed"][0]["error"]
    assert calls == []  # ingest_bridge 绝不被调用


def test_promote_rejects_sha256_duplicate(monkeypatch):
    import collector.ingest_bridge as br
    calls = []
    monkeypatch.setattr(br, "promote", lambda cid, *, library_root: calls.append(cid) or f"W-{cid[-4:]}")
    conn = _conn()
    conn.execute("""INSERT INTO intake_candidates
        (id,source_type,url_canonical,title,arxiv_id,doi,resolution,review_status,
         matched_work_id,collection_topic_id,status,raw_meta,collected_at)
        VALUES ('IC-dupe','arxiv','https://arxiv.org/abs/2501.00006','Dup','2501.00006',
                NULL,'sha256_duplicate','approved',NULL,'CT-1','pending',NULL,
                '2026-06-28T00:00:05')""")
    conn.commit(); conn.close()

    r = client.post("/api/intake/promote", json={"ids": ["IC-dupe"]})
    body = r.json()
    assert body["promoted"] == []
    assert len(body["failed"]) == 1 and body["failed"][0]["id"] == "IC-dupe"
    assert "sha256_duplicate" in body["failed"][0]["error"]
    assert calls == []


def test_promote_rechecks_new_pdf_before_ingest(monkeypatch):
    import collector.gate as gate
    import collector.ingest_bridge as br
    calls = []
    monkeypatch.setattr(gate, "heavy_gate", lambda cid: "sha256_duplicate")
    monkeypatch.setattr(br, "promote", lambda cid, *, library_root: calls.append(cid) or f"W-{cid[-4:]}")
    conn = _conn()
    conn.execute("""INSERT INTO intake_candidates
        (id,source_type,url_canonical,title,arxiv_id,doi,resolution,review_status,
         matched_work_id,collection_topic_id,status,raw_meta,local_pdf_path,collected_at)
        VALUES ('IC-stale','arxiv','https://arxiv.org/abs/2501.00007','Stale','2501.00007',
                NULL,'new','approved',NULL,'CT-1','pending',NULL,
                '_collector_cache/IC-stale.pdf','2026-06-28T00:00:06')""")
    conn.commit(); conn.close()

    r = client.post("/api/intake/promote", json={"ids": ["IC-stale"]})
    body = r.json()
    assert body["promoted"] == []
    assert len(body["failed"]) == 1 and body["failed"][0]["id"] == "IC-stale"
    assert "sha256_duplicate" in body["failed"][0]["error"]
    assert calls == []


def test_promote_collects_ingest_failures(monkeypatch):
    # approved 候选（非 needs_better_copy）但 ingest 抛错 → 进 failed（批次不中断）
    import collector.ingest_bridge as br
    def fake_promote(cid, *, library_root):
        raise FileNotFoundError("no pdf")
    monkeypatch.setattr(br, "promote", fake_promote)
    r = client.post("/api/intake/promote", json={"ids": ["IC-eeee"]})
    body = r.json()
    assert body["promoted"] == []
    assert len(body["failed"]) == 1 and body["failed"][0]["id"] == "IC-eeee"


def test_promote_empty_ids_400():
    r = client.post("/api/intake/promote", json={"ids": []})
    assert r.status_code == 400


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


# ---- POST /intake/collect (§2 薄适配: 委托 collector.collect.collect_once) ----
def test_intake_collect_delegates(monkeypatch):
    import api.routes.intake as intake_route
    called = {}

    def fake_once(*, topic_id=None, explicit_ids=None, seed_paper_ids=None, github_urls=None):
        called["args"] = dict(topic_id=topic_id, explicit_ids=explicit_ids,
                              seed_paper_ids=seed_paper_ids, github_urls=github_urls)
        return {"created": 3}

    # 路由侧 import 的 collect_once 需指向同桩
    monkeypatch.setattr(intake_route, "collect_once", fake_once)

    resp = client.post("/api/intake/collect",
                       json={"topic_id": "T-seed", "explicit_ids": ["2501.1"]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] == 3
    assert called["args"]["topic_id"] == "T-seed"
    assert called["args"]["explicit_ids"] == ["2501.1"]


def test_intake_collect_requires_selector():
    # 必须给 topic_id / explicit_ids / seed_paper_ids / github_urls 之一
    resp = client.post("/api/intake/collect", json={})
    assert resp.status_code == 400


def test_intake_collect_unknown_topic_400(monkeypatch):
    import api.routes.intake as intake_route

    def boom(**kw):
        raise ValueError("unknown topic CT-nope")
    monkeypatch.setattr(intake_route, "collect_once", boom)
    resp = client.post("/api/intake/collect", json={"topic_id": "CT-nope"})
    assert resp.status_code == 400


# ---- POST /intake/topics invalid mapped_tags → 400 ----
def test_topics_transition_invalid_mapped_tags_400(monkeypatch):
    """Invalid mapped_tags should surface as HTTP 400 via the existing ValueError handler."""
    import collector.topics as t
    def boom(tid, **kw):
        raise ValueError("invalid mapped_tags: risk_domain=nonexistent_999 is not in vocab")
    monkeypatch.setattr(t, "transition", boom)
    r = client.post("/api/intake/topics", json={
        "id": "CT-1",
        "to_map_status": "mapped",
        "mapped_tags": [{"group": "risk_domain", "value": "nonexistent_999"}],
    })
    assert r.status_code == 400
    assert "not in vocab" in r.json()["detail"]
