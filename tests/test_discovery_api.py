# tests/test_discovery_api.py
"""Tests for V1.1 constrained discovery: migration, plan, run, hit, accept."""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.db import DB_PATH, table_exists


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_test_conn(db_path):
    """Return a connection with row_factory=sqlite3.Row."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _fresh_db(tmp_path):
    """Create a fresh DB with intake_candidates + collection_topics tables."""
    db_path = tmp_path / "literature.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS intake_candidates (
            id TEXT PRIMARY KEY, source_type TEXT, source_url TEXT, title TEXT,
            arxiv_id TEXT, doi TEXT, url_canonical TEXT, fetched_sha256 TEXT,
            local_pdf_path TEXT, resolution TEXT, matched_work_id TEXT,
            status TEXT DEFAULT 'pending', review_status TEXT DEFAULT 'pending',
            review_note TEXT, collected_at TEXT, resolved_at TEXT,
            ingested_work_id TEXT, raw_meta TEXT, collection_topic_id TEXT
        );
        CREATE TABLE IF NOT EXISTS collection_topics (
            id TEXT PRIMARY KEY, name TEXT, description TEXT, query_def TEXT,
            map_status TEXT, lifecycle TEXT, mapped_tags TEXT, proposed_note TEXT,
            axis_hint TEXT, created_at TEXT, updated_at TEXT
        );
    """)
    conn.close()
    return db_path


def _run_migration(db_path):
    import scripts.migrate_add_discovery as md
    md.run(db_path)


def _seed_topic(db_path, topic_id="CT-1", name="Test Topic", query_def=None):
    now = "2026-06-30T00:00:00"
    qd = json.dumps(query_def or {
        "keywords": ["safety", "alignment"],
        "known_names": ["GPT-4"],
        "known_titles": ["Attention Is All You Need"],
    })
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT OR REPLACE INTO collection_topics "
        "(id,name,description,query_def,map_status,lifecycle,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (topic_id, name, "desc", qd, "seedling", "active", now, now),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Migration tests
# ---------------------------------------------------------------------------

def test_migration_fresh_db(tmp_path):
    """Migration creates both tables on a fresh DB."""
    db_path = tmp_path / "literature.sqlite"
    sqlite3.connect(db_path).close()
    _run_migration(db_path)
    conn = sqlite3.connect(db_path)
    assert table_exists(conn, "discovery_runs")
    assert table_exists(conn, "discovery_hits")
    cols_dr = {r[1] for r in conn.execute("PRAGMA table_info(discovery_runs)").fetchall()}
    cols_dh = {r[1] for r in conn.execute("PRAGMA table_info(discovery_hits)").fetchall()}
    assert {"id", "collection_topic_id", "mode", "executor", "status", "hits_created"} <= cols_dr
    assert {"id", "run_id", "url", "title", "dedup_key", "review_status", "confidence"} <= cols_dh
    conn.close()


def test_migration_idempotent(tmp_path):
    """Running migration twice does not error."""
    db_path = tmp_path / "literature.sqlite"
    sqlite3.connect(db_path).close()
    _run_migration(db_path)
    _run_migration(db_path)  # should not raise
    conn = sqlite3.connect(db_path)
    assert table_exists(conn, "discovery_runs")
    assert table_exists(conn, "discovery_hits")
    conn.close()


# ---------------------------------------------------------------------------
# Plan tests (use collector.discovery directly)
# ---------------------------------------------------------------------------

def test_name_plan_generates_exact_quoted_query(tmp_path, monkeypatch):
    from collector import discovery
    db_path = _fresh_db(tmp_path)
    _run_migration(db_path)
    monkeypatch.setattr(discovery, "get_conn", lambda: _get_test_conn(db_path))

    plan = discovery.draft_search_plan(mode="name", name="Claude 3.5 Sonnet")
    assert plan["mode"] == "name"
    assert any('"Claude 3.5 Sonnet"' in q for q in plan["queries"])


def test_title_plan_generates_exact_quoted_query(tmp_path, monkeypatch):
    from collector import discovery
    db_path = _fresh_db(tmp_path)
    _run_migration(db_path)
    monkeypatch.setattr(discovery, "get_conn", lambda: _get_test_conn(db_path))

    plan = discovery.draft_search_plan(mode="title", title="Attention Is All You Need")
    assert plan["mode"] == "title"
    assert any('"Attention Is All You Need"' in q for q in plan["queries"])


def test_topic_plan_merges_topic_info(tmp_path, monkeypatch):
    from collector import discovery
    db_path = _fresh_db(tmp_path)
    _run_migration(db_path)
    _seed_topic(db_path)
    monkeypatch.setattr(discovery, "get_conn", lambda: _get_test_conn(db_path))

    plan = discovery.draft_search_plan(
        mode="topic",
        topic_id="CT-1",
        topic_name="Test Topic",
        topic_keywords=["safety", "alignment"],
        topic_known_names=["GPT-4"],
        topic_known_titles=["Attention Is All You Need"],
    )
    assert plan["mode"] == "topic"
    assert "Test Topic" in plan["queries"]
    assert "safety" in plan["queries"]
    assert "GPT-4" in plan["queries"]
    assert '"Attention Is All You Need"' in plan["queries"]


def test_url_plan_manual_url(tmp_path, monkeypatch):
    from collector import discovery
    db_path = _fresh_db(tmp_path)
    _run_migration(db_path)
    monkeypatch.setattr(discovery, "get_conn", lambda: _get_test_conn(db_path))

    plan = discovery.draft_search_plan(mode="url", known_url="https://example.com/model")
    assert plan["mode"] == "url"
    assert plan["queries"] == ["https://example.com/model"]


# ---------------------------------------------------------------------------
# Unsupported mode tests
# ---------------------------------------------------------------------------

def test_unsupported_doi_plan_raises(tmp_path, monkeypatch):
    from collector import discovery
    db_path = _fresh_db(tmp_path)
    _run_migration(db_path)
    monkeypatch.setattr(discovery, "get_conn", lambda: _get_test_conn(db_path))

    with pytest.raises(ValueError, match="not supported"):
        discovery.draft_search_plan(mode="doi")


def test_unsupported_arxiv_plan_raises(tmp_path, monkeypatch):
    from collector import discovery
    db_path = _fresh_db(tmp_path)
    _run_migration(db_path)
    monkeypatch.setattr(discovery, "get_conn", lambda: _get_test_conn(db_path))

    with pytest.raises(ValueError, match="not supported"):
        discovery.draft_search_plan(mode="arxiv")


def test_unsupported_github_url_plan_raises(tmp_path, monkeypatch):
    from collector import discovery
    db_path = _fresh_db(tmp_path)
    _run_migration(db_path)
    monkeypatch.setattr(discovery, "get_conn", lambda: _get_test_conn(db_path))

    with pytest.raises(ValueError, match="not supported"):
        discovery.draft_search_plan(mode="github_url")


# ---------------------------------------------------------------------------
# Run tests
# ---------------------------------------------------------------------------

def test_agent_web_access_run_returns_planned(tmp_path, monkeypatch):
    from collector import discovery
    db_path = _fresh_db(tmp_path)
    _run_migration(db_path)
    monkeypatch.setattr(discovery, "get_conn", lambda: _get_test_conn(db_path))

    run = discovery.create_discovery_run(
        mode="name",
        input_json={"name": "Test"},
        search_plan_json={"mode": "name", "queries": []},
        executor="agent:web-access",
    )
    assert run["status"] == "planned"
    assert run["hits_created"] == 0


def test_manual_url_run_with_separate_hit(tmp_path, monkeypatch):
    from collector import discovery
    db_path = _fresh_db(tmp_path)
    _run_migration(db_path)
    monkeypatch.setattr(discovery, "get_conn", lambda: _get_test_conn(db_path))

    run = discovery.create_discovery_run(
        mode="url",
        input_json={"url": "https://example.com/model"},
        search_plan_json={"mode": "url", "queries": ["https://example.com/model"]},
        executor="manual",
    )
    assert run["status"] == "planned"
    # Manual URL mode: caller inserts hit separately
    hit = discovery.insert_discovery_hit(
        run_id=run["id"],
        url="https://example.com/model",
        title="Test Model",
        source_type="manual_url",
        confidence="high",
    )
    assert hit["status"] == "created"
    assert hit["id"].startswith("DH-")


# ---------------------------------------------------------------------------
# Hit backfill tests
# ---------------------------------------------------------------------------

def test_post_hits_backfill(tmp_path, monkeypatch):
    from collector import discovery
    db_path = _fresh_db(tmp_path)
    _run_migration(db_path)
    monkeypatch.setattr(discovery, "get_conn", lambda: _get_test_conn(db_path))

    run = discovery.create_discovery_run(
        mode="name",
        input_json={"name": "Test"},
        search_plan_json={"mode": "name", "queries": []},
        executor="agent:web-access",
    )
    hit = discovery.insert_discovery_hit(
        run_id=run["id"],
        url="https://example.com/result",
        title="Test Result",
        confidence="high",
        reason="search result",
    )
    assert hit["status"] == "created"

    # Verify hit exists
    hits = discovery.list_discovery_hits(run_id=run["id"])
    assert hits["total"] == 1
    assert hits["hits"][0]["url"] == "https://example.com/result"
    assert hits["hits"][0]["review_status"] == "pending"


def test_dedup_same_run_id_and_dedup_key(tmp_path, monkeypatch):
    from collector import discovery
    db_path = _fresh_db(tmp_path)
    _run_migration(db_path)
    monkeypatch.setattr(discovery, "get_conn", lambda: _get_test_conn(db_path))

    run = discovery.create_discovery_run(
        mode="name",
        input_json={"name": "Test"},
        search_plan_json={"mode": "name", "queries": []},
        executor="agent:web-access",
    )
    hit1 = discovery.insert_discovery_hit(
        run_id=run["id"], url="https://example.com/a", title="A",
    )
    hit2 = discovery.insert_discovery_hit(
        run_id=run["id"], url="https://example.com/a", title="A",
    )
    assert hit1["status"] == "created"
    assert hit2["status"] == "skipped_dup"
    assert hit1["id"] == hit2["id"]


def test_different_runs_same_url_different_hits(tmp_path, monkeypatch):
    from collector import discovery
    db_path = _fresh_db(tmp_path)
    _run_migration(db_path)
    monkeypatch.setattr(discovery, "get_conn", lambda: _get_test_conn(db_path))

    run1 = discovery.create_discovery_run(
        mode="name", input_json={"name": "A"},
        search_plan_json={}, executor="agent:web-access",
    )
    run2 = discovery.create_discovery_run(
        mode="name", input_json={"name": "B"},
        search_plan_json={}, executor="agent:web-access",
    )
    hit1 = discovery.insert_discovery_hit(
        run_id=run1["id"], url="https://example.com/x",
    )
    hit2 = discovery.insert_discovery_hit(
        run_id=run2["id"], url="https://example.com/x",
    )
    assert hit1["id"] != hit2["id"]  # different runs -> different hits


# ---------------------------------------------------------------------------
# Accept tests
# ---------------------------------------------------------------------------

def test_accept_hit_creates_intake_candidate(tmp_path, monkeypatch):
    from collector import discovery
    from collector import candidate_store as cs
    db_path = _fresh_db(tmp_path)
    _run_migration(db_path)
    monkeypatch.setattr(discovery, "get_conn", lambda: _get_test_conn(db_path))
    monkeypatch.setattr(cs, "get_conn", lambda: _get_test_conn(db_path))

    run = discovery.create_discovery_run(
        mode="name", input_json={"name": "Test"},
        search_plan_json={}, executor="agent:web-access",
    )
    hit = discovery.insert_discovery_hit(
        run_id=run["id"],
        url="https://example.com/paper", title="Paper",
    )
    result = discovery.accept_hit_to_intake(hit["id"])
    assert result["candidate_id"].startswith("IC-")
    assert result["status"] == "created"

    # Verify candidate exists and has correct fields
    conn = _get_test_conn(db_path)
    cand = conn.execute("SELECT * FROM intake_candidates WHERE id=?", (result["candidate_id"],)).fetchone()
    assert cand is not None
    assert cand["resolution"] == "pending"
    assert cand["status"] == "pending"
    raw = json.loads(cand["raw_meta"])
    assert raw["discovery_hit_id"] == hit["id"]
    conn.close()


def test_accept_hit_reuses_existing_candidate(tmp_path, monkeypatch):
    from collector import discovery
    from collector import candidate_store as cs
    db_path = _fresh_db(tmp_path)
    _run_migration(db_path)
    monkeypatch.setattr(discovery, "get_conn", lambda: _get_test_conn(db_path))
    monkeypatch.setattr(cs, "get_conn", lambda: _get_test_conn(db_path))

    # Pre-create an existing candidate
    conn = _get_test_conn(db_path)
    conn.execute(
        "INSERT INTO intake_candidates (id, source_type, url_canonical, title, resolution, status, review_status, collected_at) "
        "VALUES ('IC-existing', 'web', 'https://example.com/paper', 'Existing', 'pending', 'pending', 'pending', '2026-01-01')"
    )
    conn.commit()
    conn.close()

    run = discovery.create_discovery_run(
        mode="name", input_json={"name": "Test"},
        search_plan_json={}, executor="agent:web-access",
    )
    hit = discovery.insert_discovery_hit(
        run_id=run["id"],
        url="https://example.com/paper", title="Paper",
    )
    result = discovery.accept_hit_to_intake(hit["id"])
    assert result["candidate_id"] == "IC-existing"
    assert result["status"] == "skipped_dup"


# ---------------------------------------------------------------------------
# Batch accept tests
# ---------------------------------------------------------------------------

def test_batch_accept_with_url_hit_succeeds(tmp_path, monkeypatch):
    from collector import discovery
    from collector import candidate_store as cs
    db_path = _fresh_db(tmp_path)
    _run_migration(db_path)
    monkeypatch.setattr(discovery, "get_conn", lambda: _get_test_conn(db_path))
    monkeypatch.setattr(cs, "get_conn", lambda: _get_test_conn(db_path))

    run = discovery.create_discovery_run(
        mode="name", input_json={"name": "Test"},
        search_plan_json={}, executor="agent:web-access",
    )
    hit = discovery.insert_discovery_hit(
        run_id=run["id"],
        url="https://example.com/paper", title="Paper", confidence="medium",
    )
    result = discovery.batch_accept_hits([hit["id"]])
    assert len(result["accepted"]) == 1
    assert len(result["failed"]) == 0


# ---------------------------------------------------------------------------
# Reject tests
# ---------------------------------------------------------------------------

def test_reject_hit_with_note(tmp_path, monkeypatch):
    from collector import discovery
    db_path = _fresh_db(tmp_path)
    _run_migration(db_path)
    monkeypatch.setattr(discovery, "get_conn", lambda: _get_test_conn(db_path))

    run = discovery.create_discovery_run(
        mode="name", input_json={"name": "Test"},
        search_plan_json={}, executor="agent:web-access",
    )
    hit = discovery.insert_discovery_hit(
        run_id=run["id"],
        url="https://example.com/x", title="X",
    )
    result = discovery.reject_hit(hit["id"], review_note="not relevant")
    assert result["ok"] is True
    assert result["review_status"] == "rejected"

    # Verify note persisted
    updated = discovery.get_discovery_hit(hit["id"])
    assert updated["review_status"] == "rejected"
    assert updated["review_note"] == "not relevant"


# ---------------------------------------------------------------------------
# API endpoint tests (via TestClient)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def _api_client():
    """Create a TestClient with patched DB for the API endpoints."""
    import shutil
    import scripts.migrate_add_discovery as md
    from unittest.mock import patch

    tmp_dir = tempfile.mkdtemp(prefix="litlib_discovery_")
    db_path = Path(tmp_dir) / "literature.sqlite"

    # Create minimal schema
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS intake_candidates (
            id TEXT PRIMARY KEY, source_type TEXT, source_url TEXT, title TEXT,
            arxiv_id TEXT, doi TEXT, url_canonical TEXT, fetched_sha256 TEXT,
            local_pdf_path TEXT, resolution TEXT, matched_work_id TEXT,
            status TEXT DEFAULT 'pending', review_status TEXT DEFAULT 'pending',
            review_note TEXT, collected_at TEXT, resolved_at TEXT,
            ingested_work_id TEXT, raw_meta TEXT, collection_topic_id TEXT
        );
        CREATE TABLE IF NOT EXISTS collection_topics (
            id TEXT PRIMARY KEY, name TEXT, description TEXT, query_def TEXT,
            map_status TEXT, lifecycle TEXT, mapped_tags TEXT, proposed_note TEXT,
            axis_hint TEXT, created_at TEXT, updated_at TEXT
        );
    """)
    conn.close()
    md.run(db_path)

    # Monkey-patch get_conn
    import api.db as db_mod
    import collector.discovery as disc_mod
    import collector.candidate_store as cs_mod
    import collector.gate as gate_mod

    def _test_conn():
        c = sqlite3.connect(str(db_path))
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        return c

    from api.main import app

    with patch.object(db_mod, "get_conn", _test_conn), \
         patch.object(disc_mod, "get_conn", _test_conn), \
         patch.object(cs_mod, "get_conn", _test_conn), \
         patch.object(gate_mod, "get_conn", _test_conn):
        yield TestClient(app), db_path

    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_api_plan_unsupported_doi(_api_client):
    client, _ = _api_client
    r = client.post("/api/discovery/plan", json={"mode": "doi"})
    assert r.status_code == 400
    assert "not supported" in r.json()["detail"]


def test_api_plan_unsupported_arxiv(_api_client):
    client, _ = _api_client
    r = client.post("/api/discovery/plan", json={"mode": "arxiv"})
    assert r.status_code == 400


def test_api_plan_unsupported_github_url(_api_client):
    client, _ = _api_client
    r = client.post("/api/discovery/plan", json={"mode": "github_url"})
    assert r.status_code == 400


def test_api_plan_name_ok(_api_client):
    client, _ = _api_client
    r = client.post("/api/discovery/plan", json={"mode": "name", "name": "Claude"})
    assert r.status_code == 200
    plan = r.json()
    assert plan["mode"] == "name"


def test_api_run_agent_web_access_returns_planned(_api_client):
    client, _ = _api_client
    r = client.post("/api/discovery/run", json={
        "mode": "name",
        "input": {"name": "Test"},
        "plan": {"mode": "name", "queries": []},
        "executor": "agent:web-access",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "planned"
    assert body["hits_created"] == 0


def test_api_run_manual_url_creates_hit(_api_client):
    client, _ = _api_client
    r = client.post("/api/discovery/run", json={
        "mode": "url",
        "input": {"url": "https://example.com/m"},
        "plan": {"mode": "url", "queries": ["https://example.com/m"]},
        "executor": "manual",
    })
    assert r.status_code == 200
    body = r.json()
    # V1.1: manual URL run creates a manual_url hit synchronously.
    assert body["run_id"].startswith("DR-")
    assert body["status"] == "planned"
    assert body["hits_created"] == 1
    assert body["hits"][0]["status"] == "created"


def test_api_list_runs(_api_client):
    client, _ = _api_client
    r = client.get("/api/discovery/runs")
    assert r.status_code == 200
    assert r.json()["total"] >= 1


def test_api_get_run(_api_client):
    client, _ = _api_client
    # Create a run first
    r = client.post("/api/discovery/run", json={
        "mode": "name", "input": {"name": "X"},
        "plan": {}, "executor": "agent:web-access",
    })
    run_id = r.json()["run_id"]
    r2 = client.get(f"/api/discovery/runs/{run_id}")
    assert r2.status_code == 200
    assert r2.json()["id"] == run_id


def test_api_get_run_not_found(_api_client):
    client, _ = _api_client
    r = client.get("/api/discovery/runs/DR-nonexistent")
    assert r.status_code == 404


def test_api_backfill_hits(_api_client):
    client, _ = _api_client
    # Create run
    r = client.post("/api/discovery/run", json={
        "mode": "name", "input": {"name": "Test"},
        "plan": {}, "executor": "agent:web-access",
    })
    run_id = r.json()["run_id"]
    # Backfill hits
    r2 = client.post(f"/api/discovery/runs/{run_id}/hits", json=[{
        "source_type": "web",
        "url": "https://example.com/backfill",
        "title": "Backfilled",
    }])
    assert r2.status_code == 200
    assert r2.json()["created"] == 1


def test_api_backfill_hits_run_not_found(_api_client):
    client, _ = _api_client
    r = client.post("/api/discovery/runs/DR-nonexistent/hits", json=[{
        "source_type": "web", "url": "https://example.com/x",
    }])
    assert r.status_code == 404


def test_api_list_hits(_api_client):
    client, _ = _api_client
    r = client.get("/api/discovery/hits")
    assert r.status_code == 200
    assert r.json()["total"] >= 1


def test_api_accept_hit(_api_client):
    client, _ = _api_client
    # Create run + hit
    r = client.post("/api/discovery/run", json={
        "mode": "name", "input": {"name": "Accept"},
        "plan": {}, "executor": "agent:web-access",
    })
    run_id = r.json()["run_id"]
    r2 = client.post(f"/api/discovery/runs/{run_id}/hits", json=[{
        "source_type": "web", "url": "https://example.com/accept", "title": "Accept Me",
    }])
    hit_id = r2.json()["results"][0]["id"]
    r3 = client.post(f"/api/discovery/hits/{hit_id}/accept", json={"review_note": ""})
    assert r3.status_code == 200
    assert r3.json()["candidate_id"].startswith("IC-")


def test_api_batch_accept_empty_ids_400(_api_client):
    client, _ = _api_client
    r = client.post("/api/discovery/hits/batch-accept", json={"hit_ids": []})
    assert r.status_code == 400


def test_api_batch_accept_title_only_fails(_api_client):
    client, _ = _api_client
    r = client.post("/api/discovery/run", json={
        "mode": "name", "input": {"name": "Title Only"},
        "plan": {}, "executor": "agent:web-access",
    })
    run_id = r.json()["run_id"]
    r2 = client.post(f"/api/discovery/runs/{run_id}/hits", json=[{
        "source_type": "web", "title": "Title Only", "confidence": "low",
    }])
    hit_id = r2.json()["results"][0]["id"]
    r3 = client.post("/api/discovery/hits/batch-accept", json={"hit_ids": [hit_id]})
    assert r3.status_code == 200
    body = r3.json()
    assert body["accepted"] == []
    assert "title-only" in body["failed"][0]["error"]


def test_api_reject_hit_with_note(_api_client):
    client, _ = _api_client
    # Create run + hit
    r = client.post("/api/discovery/run", json={
        "mode": "name", "input": {"name": "Reject"},
        "plan": {}, "executor": "agent:web-access",
    })
    run_id = r.json()["run_id"]
    r2 = client.post(f"/api/discovery/runs/{run_id}/hits", json=[{
        "source_type": "web", "url": "https://example.com/reject", "title": "Reject Me",
    }])
    hit_id = r2.json()["results"][0]["id"]
    r3 = client.post(f"/api/discovery/hits/{hit_id}/reject", json={"review_note": "not relevant"})
    assert r3.status_code == 200
    assert r3.json()["review_status"] == "rejected"


# ---------------------------------------------------------------------------
# Composite Plan API endpoint tests
# ---------------------------------------------------------------------------

def test_api_composite_plan_basic(_api_client):
    client, _ = _api_client
    r = client.post("/api/discovery/composite-plan", json={
        "names": ["GPT-5.6 system card"],
        "keywords": ["safety"],
    })
    assert r.status_code == 200
    plan = r.json()
    assert plan["mode"] == "composite"
    assert len(plan["queries"]) > 0
    assert any("GPT-5.6" in q for q in plan["queries"])
    assert "dedup_guidance" in plan
    assert "input_signals" in plan


def test_api_composite_plan_with_all_fields(_api_client):
    client, _ = _api_client
    r = client.post("/api/discovery/composite-plan", json={
        "names": ["Claude Opus"],
        "titles": ["Safety Report"],
        "authors": ["Alice Researcher"],
        "institutions": ["AI Lab"],
        "keywords": ["safety", "alignment"],
        "known_urls": ["https://example.com/report"],
        "preferred_domains": ["openai.com"],
        "exclude_terms": ["reddit", "forum"],
        "artifact_type_hint": "system_card",
        "max_results": 10,
        "freeform_note": "Looking for frontier model safety reports",
    })
    assert r.status_code == 200
    plan = r.json()
    assert plan["mode"] == "composite"
    assert len(plan["exclude_terms"]) == 2
    assert len(plan["preferred_domains"]) == 1
    assert plan["max_results"] == 10
    assert plan["input_signals"]["freeform_note"] != ""


def test_api_composite_plan_empty_signals(_api_client):
    client, _ = _api_client
    r = client.post("/api/discovery/composite-plan", json={})
    assert r.status_code == 200
    plan = r.json()
    assert plan["mode"] == "composite"
    assert plan["queries"] == []


def test_api_composite_plan_query_cap(_api_client):
    client, _ = _api_client
    r = client.post("/api/discovery/composite-plan", json={
        "names": [f"name-{i}" for i in range(15)],
        "titles": [f"title-{i}" for i in range(15)],
        "keywords": [f"kw-{i}" for i in range(15)],
    })
    assert r.status_code == 200
    plan = r.json()
    assert len(plan["queries"]) <= 10


def test_api_composite_plan_existing_modes_unchanged(_api_client):
    """Verify that existing name/title/url/topic modes still work."""
    client, _ = _api_client

    # Name mode should still work
    r = client.post("/api/discovery/plan", json={"mode": "name", "name": "GPT"})
    assert r.status_code == 200
    assert r.json()["mode"] == "name"

    # Title mode should still work
    r2 = client.post("/api/discovery/plan", json={"mode": "title", "title": "Paper Title"})
    assert r2.status_code == 200
    assert r2.json()["mode"] == "title"


# ---------------------------------------------------------------------------
# P0-1: Complete endpoint and backfill status flip
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_run_id(_api_client):
    """Create a discovery run and return its ID."""
    client, _ = _api_client
    r = client.post("/api/discovery/run", json={
        "mode": "composite",
        "input": {},
        "plan": {},
        "executor": "agent:web-access",
    })
    return r.json()["run_id"]


def test_complete_run_endpoint(_api_client, sample_run_id):
    """P0-1: POST /discovery/runs/{id}/complete 标记 succeeded；非法 status 返 422。"""
    client, _ = _api_client
    r = client.post(f"/api/discovery/runs/{sample_run_id}/complete",
                    json={"status": "succeeded"})
    assert r.status_code == 200
    assert r.json()["status"] == "succeeded"

    bad = client.post(f"/api/discovery/runs/{sample_run_id}/complete",
                      json={"status": "running"})
    assert bad.status_code == 422

    missing = client.post("/api/discovery/runs/DR-nope/complete",
                          json={"status": "failed"})
    assert missing.status_code == 404


def test_backfill_marks_succeeded_when_created(_api_client, sample_run_id):
    """P0-1: backfill 有 created hit 后 run 必须 succeeded（无论起点 planned 还是 running）。"""
    client, _ = _api_client
    r = client.post(f"/api/discovery/runs/{sample_run_id}/hits",
                    json=[{"url": "https://arxiv.org/abs/2501.88888",
                           "title": "Backfill Paper", "query": "q"}])
    assert r.status_code == 200
    assert r.json()["created"] == 1
    run = client.get(f"/api/discovery/runs/{sample_run_id}").json()
    assert run["status"] == "succeeded"


# ---------------------------------------------------------------------------
# P0-2: Works-level dedup (dup_of_works) via API
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_work_with_arxiv(_api_client):
    """Create a work with arxiv_id in the database for dedup testing."""
    client, db_path = _api_client
    conn = _get_test_conn(db_path)
    # Create works table if not exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS works (
            id TEXT PRIMARY KEY, title TEXT, arxiv_id TEXT, doi TEXT, read_status TEXT
        )
    """)
    conn.execute(
        "INSERT OR REPLACE INTO works (id, title, arxiv_id, doi) VALUES (?, ?, ?, ?)",
        ("W-1", "Test Paper", "2501.12345", None),
    )
    conn.commit()
    conn.close()
    yield


def test_backfill_dup_by_arxiv_id_marked(_api_client, sample_work_with_arxiv):
    """P0-2: agent 回填带 arxiv_id 且 works 已有该 arxiv_id → hit 标 dup_of_works。"""
    client, _ = _api_client
    # Create run
    r = client.post("/api/discovery/run", json={
        "mode": "composite", "input": {"mode": "composite"},
        "plan": {"queries": []}, "executor": "agent:web-access",
    })
    run_id = r.json()["run_id"]
    # Backfill hit with arxiv_id
    r = client.post(f"/api/discovery/runs/{run_id}/hits", json=[
        {"url": "https://arxiv.org/abs/2501.12345",
         "title": "Whatever", "arxiv_id": "2501.12345", "query": "q"}])
    assert r.status_code == 200
    hit = client.get(f"/api/discovery/hits?run_id={run_id}").json()["hits"][0]
    assert hit["verification_status"] == "dup_of_works"


def test_backfill_dup_by_doi_marked(_api_client):
    """P0-2: agent 回填带 doi 且 works 已有该 doi → hit 标 dup_of_works。"""
    client, db_path = _api_client
    # Create works table and seed a work with DOI
    conn = _get_test_conn(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS works (
            id TEXT PRIMARY KEY, title TEXT, arxiv_id TEXT, doi TEXT, read_status TEXT
        )
    """)
    conn.execute(
        "INSERT OR REPLACE INTO works (id, title, arxiv_id, doi, read_status) VALUES (?, ?, ?, ?, ?)",
        ("W-2", "DOI Paper", None, "10.1234/example", "active"),
    )
    conn.commit()
    conn.close()
    # Create run
    r = client.post("/api/discovery/run", json={
        "mode": "composite", "input": {"mode": "composite"},
        "plan": {"queries": []}, "executor": "agent:web-access",
    })
    run_id = r.json()["run_id"]
    # Backfill hit with DOI
    r = client.post(f"/api/discovery/runs/{run_id}/hits", json=[
        {"url": "https://doi.org/10.1234/example",
         "title": "Another Title", "doi": "10.1234/example", "query": "q"}])
    assert r.status_code == 200
    hit = client.get(f"/api/discovery/hits?run_id={run_id}").json()["hits"][0]
    assert hit["verification_status"] == "dup_of_works"


# ---------------------------------------------------------------------------
# P1-1: Topic inheritance from run → hit → intake_candidate
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_topic(_api_client):
    """Create a collection_topic for testing topic_id inheritance."""
    client, db_path = _api_client
    _seed_topic(db_path, topic_id="CT-P1-1", name="P1-1 Test Topic")
    return {"id": "CT-P1-1", "name": "P1-1 Test Topic"}


def test_composite_run_with_topic_inherits_to_candidate(_api_client, sample_topic):
    """P1-1: run 带 topic_id → hit 继承 → accept 后 intake_candidate 带 collection_topic_id。"""
    client, db_path = _api_client
    # 1. 建 run（带 topic_id）
    run = client.post("/api/discovery/run", json={
        "mode": "composite",
        "input": {"mode": "composite"},
        "plan": {"queries": ["q"]},
        "executor": "agent:web-access",
        "topic_id": sample_topic["id"],
    }).json()
    assert run["run_id"]
    # 2. 回填 hit
    client.post(f"/api/discovery/runs/{run['run_id']}/hits", json=[
        {"url": "https://arxiv.org/abs/2501.00001", "title": "Inherited Paper", "query": "q"}])
    hit = client.get(f"/api/discovery/hits?run_id={run['run_id']}").json()["hits"][0]
    assert hit["collection_topic_id"] == sample_topic["id"]
    # 3. accept
    r = client.post(f"/api/discovery/hits/{hit['id']}/accept", json={"review_note": ""})
    candidate_id = r.json()["candidate_id"]
    # 4. 直接查 test DB 验证 intake_candidate 带 collection_topic_id
    conn = _get_test_conn(db_path)
    cand = conn.execute(
        "SELECT collection_topic_id FROM intake_candidates WHERE id=?",
        (candidate_id,),
    ).fetchone()
    conn.close()
    assert cand is not None
    assert cand["collection_topic_id"] == sample_topic["id"]
