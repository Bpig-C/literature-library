# tests/test_discovery_core.py
"""V1.1 Discovery core tests (collector/discovery.py).

All tests use tmp_path + monkeypatch get_conn to avoid real network.
"""
import json
import sqlite3

import pytest

import scripts.migrate_add_intake_candidates as mic
import scripts.migrate_add_discovery as md
from collector import discovery as disc
from collector import candidate_store as cs


def _db(tmp_path):
    db_path = tmp_path / "literature.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS works (
            id TEXT PRIMARY KEY, title TEXT, arxiv_id TEXT, doi TEXT, read_status TEXT
        );
        CREATE TABLE IF NOT EXISTS collection_topics (
            id TEXT PRIMARY KEY, name TEXT, description TEXT, query_def TEXT,
            map_status TEXT, lifecycle TEXT, mapped_tags TEXT, proposed_note TEXT,
            axis_hint TEXT, created_at TEXT, updated_at TEXT
        );
    """)
    conn.commit()
    conn.close()
    mic.run(db_path)
    md.run(db_path)
    return db_path


def _conn(db_path):
    c = sqlite3.connect(str(db_path))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _seed_topic(db_path, topic_id="CT-test", name="test topic", qd=None):
    if qd is None:
        qd = {"keywords": [], "known_names": [], "known_titles": [],
              "known_urls": [], "explicit_ids": [], "seed_paper_ids": []}
    conn = _conn(db_path)
    conn.execute(
        """INSERT OR REPLACE INTO collection_topics
           (id, name, description, query_def, map_status, lifecycle, created_at, updated_at)
           VALUES (?,?,?,?, 'seedling', 'active', '2026-06-30T00:00:00', '2026-06-30T00:00:00')""",
        (topic_id, name, "test", json.dumps(qd, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Plan generation
# ---------------------------------------------------------------------------

class TestDraftSearchPlan:
    def test_name_plan_exact_quoted_query(self):
        plan = disc.draft_search_plan(mode="name", name="GPT-5.6 system card")
        assert plan["mode"] == "name"
        assert any('"GPT-5.6 system card"' in q for q in plan["queries"])

    def test_title_plan_exact_quoted_query_with_academic_sources(self):
        plan = disc.draft_search_plan(mode="title", title="A Survey of AI Evaluation Methods")
        assert plan["mode"] == "title"
        assert any('"A Survey of AI Evaluation Methods"' in q for q in plan["queries"])
        assert "openalex" in plan["sources"]

    def test_topic_plan_merges_keywords_and_known_names(self, tmp_path, monkeypatch):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        _seed_topic(db, "CT-1", "frontier model system cards", {
            "keywords": ["system card", "model card"],
            "known_names": ["GPT-5.6 system card"],
            "known_titles": ["Safety Report 2026"],
        })
        plan = disc.draft_search_plan(
            mode="topic",
            topic_id="CT-1",
            topic_name="frontier model system cards",
            topic_keywords=["system card", "model card"],
            topic_known_names=["GPT-5.6 system card"],
            topic_known_titles=["Safety Report 2026"],
        )
        assert plan["mode"] == "topic"
        assert "frontier model system cards" in plan["queries"]
        assert "system card" in plan["queries"]
        assert "GPT-5.6 system card" in plan["queries"]
        assert '"Safety Report 2026"' in plan["queries"]

    def test_topic_plan_reads_topic_id_when_no_fields_supplied(self, monkeypatch):
        from collector import topics
        monkeypatch.setattr(topics, "get", lambda topic_id: {
            "id": topic_id,
            "name": "frontier model system cards",
            "query_def": {
                "keywords": ["system card"],
                "known_names": ["GPT-5.6 system card"],
                "known_titles": ["Safety Report 2026"],
            },
        })
        plan = disc.draft_search_plan(mode="topic", topic_id="CT-1")
        assert "frontier model system cards" in plan["queries"]
        assert "system card" in plan["queries"]
        assert "GPT-5.6 system card" in plan["queries"]
        assert '"Safety Report 2026"' in plan["queries"]

    def test_url_plan_uses_manual_url_source(self):
        plan = disc.draft_search_plan(mode="url", known_url="https://openai.com/system-card")
        assert plan["mode"] == "url"
        assert "manual_url" in plan["sources"]

    def test_unsupported_doi_raises(self):
        with pytest.raises(ValueError, match="not supported in V1.1"):
            disc.draft_search_plan(mode="doi")

    def test_unsupported_arxiv_raises(self):
        with pytest.raises(ValueError, match="not supported in V1.1"):
            disc.draft_search_plan(mode="arxiv")

    def test_unsupported_github_url_raises(self):
        with pytest.raises(ValueError, match="not supported in V1.1"):
            disc.draft_search_plan(mode="github_url")

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="invalid mode"):
            disc.draft_search_plan(mode="bogus")

    def test_name_plan_system_card_includes_github_huggingface(self):
        plan = disc.draft_search_plan(
            mode="name", name="Claude 4 system card", artifact_type_hint="system_card"
        )
        assert "github" in plan["sources"]
        assert "huggingface" in plan["sources"]

    def test_max_results_clamped(self):
        plan = disc.draft_search_plan(mode="name", name="test", max_results=999)
        assert plan["max_results"] == 100
        plan2 = disc.draft_search_plan(mode="name", name="test", max_results=0)
        assert plan2["max_results"] == 1


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------

class TestCreateDiscoveryRun:
    def test_create_run_returns_dict_with_id(self, tmp_path, monkeypatch):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        run = disc.create_discovery_run(
            mode="name", input_json={"name": "test"}, search_plan_json={}, executor="python"
        )
        assert run["id"].startswith("DR-")
        assert run["status"] == "planned"
        assert run["mode"] == "name"

    def test_create_run_agent_executor_returns_planned(self, tmp_path, monkeypatch):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        run = disc.create_discovery_run(
            mode="name", input_json={}, search_plan_json={}, executor="agent:web-access"
        )
        assert run["status"] == "planned"
        assert run["hits_created"] == 0

    def test_create_run_unsupported_mode_raises(self, tmp_path, monkeypatch):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        with pytest.raises(ValueError, match="not supported in V1.1"):
            disc.create_discovery_run(
                mode="doi", input_json={}, search_plan_json={}, executor="python"
            )

    def test_create_run_invalid_executor_raises(self, tmp_path, monkeypatch):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        with pytest.raises(ValueError, match="invalid executor"):
            disc.create_discovery_run(
                mode="name", input_json={}, search_plan_json={}, executor="bogus"
            )


# ---------------------------------------------------------------------------
# Hit insertion
# ---------------------------------------------------------------------------

class TestInsertDiscoveryHit:
    def test_insert_hit_created(self, tmp_path, monkeypatch):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        run = disc.create_discovery_run(
            mode="name", input_json={}, search_plan_json={}, executor="python"
        )
        r = disc.insert_discovery_hit(
            run_id=run["id"],
            url="https://openai.com/gpt56-system-card",
            title="GPT-5.6 System Card",
            query='"GPT-5.6 system card"',
            source_type="official_domain",
            reason="Official release page",
            confidence="high",
        )
        assert r["status"] == "created"
        assert r["id"].startswith("DH-")

    def test_insert_hit_dedup_same_url(self, tmp_path, monkeypatch):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        run = disc.create_discovery_run(
            mode="name", input_json={}, search_plan_json={}, executor="python"
        )
        r1 = disc.insert_discovery_hit(
            run_id=run["id"], url="https://openai.com/system-card", title="First"
        )
        r2 = disc.insert_discovery_hit(
            run_id=run["id"], url="https://openai.com/system-card", title="Duplicate"
        )
        assert r1["status"] == "created"
        assert r2["status"] == "skipped_dup"

    def test_insert_hit_requires_url_or_title(self, tmp_path, monkeypatch):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        run = disc.create_discovery_run(
            mode="name", input_json={}, search_plan_json={}, executor="python"
        )
        with pytest.raises(ValueError, match="must have at least url or title"):
            disc.insert_discovery_hit(run_id=run["id"])

    def test_insert_hit_nonexistent_run_raises(self, tmp_path, monkeypatch):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        with pytest.raises(KeyError, match="run not found"):
            disc.insert_discovery_hit(run_id="DR-nonexistent", url="https://a.com")

    def test_insert_hit_title_only(self, tmp_path, monkeypatch):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        run = disc.create_discovery_run(
            mode="name", input_json={}, search_plan_json={}, executor="python"
        )
        r = disc.insert_discovery_hit(run_id=run["id"], title="Some Paper Title")
        assert r["status"] == "created"

    def test_batch_insert_hits(self, tmp_path, monkeypatch):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        run = disc.create_discovery_run(
            mode="name", input_json={}, search_plan_json={}, executor="python"
        )
        hits = [
            {"url": "https://example.com/a", "title": "A"},
            {"url": "https://example.com/b", "title": "B"},
            {"url": "https://example.com/a", "title": "A dup"},
        ]
        results = disc.batch_insert_hits(run_id=run["id"], hits=hits)
        assert len(results) == 3
        assert results[0]["status"] == "created"
        assert results[1]["status"] == "created"
        assert results[2]["status"] == "skipped_dup"


# ---------------------------------------------------------------------------
# Accept hit to intake
# ---------------------------------------------------------------------------

class TestAcceptHitToIntake:
    def test_accept_creates_intake_candidate(self, tmp_path, monkeypatch):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        monkeypatch.setattr(cs, "get_conn", lambda: _conn(db))
        run = disc.create_discovery_run(
            mode="name", input_json={}, search_plan_json={}, executor="python"
        )
        hit = disc.insert_discovery_hit(
            run_id=run["id"], url="https://openai.com/system-card",
            title="GPT-5.6 System Card", source_type="official_domain",
            reason="Official release page",
        )
        result = disc.accept_hit_to_intake(hit["id"])
        assert result["candidate_id"].startswith("IC-")
        assert result["status"] in ("created", "skipped_dup")

    def test_accept_non_paper_url_creates_candidate_without_doi(self, tmp_path, monkeypatch):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        monkeypatch.setattr(cs, "get_conn", lambda: _conn(db))
        run = disc.create_discovery_run(
            mode="name", input_json={}, search_plan_json={}, executor="python"
        )
        hit = disc.insert_discovery_hit(
            run_id=run["id"], url="https://openai.com/gpt56-system-card",
            title="GPT-5.6 System Card (HTML)", content_type="html",
        )
        result = disc.accept_hit_to_intake(hit["id"])
        assert result["candidate_id"].startswith("IC-")
        conn = _conn(db)
        row = conn.execute(
            "SELECT doi, arxiv_id, resolution FROM intake_candidates WHERE id=?",
            (result["candidate_id"],),
        ).fetchone()
        conn.close()
        assert row["doi"] is None
        assert row["arxiv_id"] is None
        assert row["resolution"] == "pending"

    def test_accept_preserves_raw_meta(self, tmp_path, monkeypatch):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        monkeypatch.setattr(cs, "get_conn", lambda: _conn(db))
        run = disc.create_discovery_run(
            mode="name", input_json={}, search_plan_json={}, executor="python"
        )
        hit = disc.insert_discovery_hit(
            run_id=run["id"], url="https://example.com/paper",
            title="Test Paper", query='"test"', reason="Found via search",
        )
        result = disc.accept_hit_to_intake(hit["id"])
        conn = _conn(db)
        row = conn.execute(
            "SELECT raw_meta FROM intake_candidates WHERE id=?",
            (result["candidate_id"],),
        ).fetchone()
        conn.close()
        meta = json.loads(row["raw_meta"])
        assert meta["discovery_hit_id"] == hit["id"]
        assert meta["discovery_run_id"] == run["id"]
        assert meta["reason"] == "Found via search"

    def test_accept_nonexistent_hit_raises(self, tmp_path, monkeypatch):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        with pytest.raises(KeyError, match="hit not found"):
            disc.accept_hit_to_intake("DH-nonexistent")

    def test_accept_idempotent(self, tmp_path, monkeypatch):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        monkeypatch.setattr(cs, "get_conn", lambda: _conn(db))
        run = disc.create_discovery_run(
            mode="name", input_json={}, search_plan_json={}, executor="python"
        )
        hit = disc.insert_discovery_hit(
            run_id=run["id"], url="https://example.com/paper", title="Test"
        )
        r1 = disc.accept_hit_to_intake(hit["id"])
        r2 = disc.accept_hit_to_intake(hit["id"])
        assert r1["candidate_id"] == r2["candidate_id"]
        assert r2["status"] == "already_accepted"


# ---------------------------------------------------------------------------
# Reject hit
# ---------------------------------------------------------------------------

class TestRejectHit:
    def test_reject_sets_status(self, tmp_path, monkeypatch):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        run = disc.create_discovery_run(
            mode="name", input_json={}, search_plan_json={}, executor="python"
        )
        hit = disc.insert_discovery_hit(
            run_id=run["id"], url="https://example.com/noise", title="Noise"
        )
        result = disc.reject_hit(hit["id"], review_note="not relevant")
        assert result["hit_id"] == hit["id"]
        assert result["review_status"] == "rejected"

    def test_reject_nonexistent_raises(self, tmp_path, monkeypatch):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        with pytest.raises(KeyError):
            disc.reject_hit("DH-nonexistent")


# ---------------------------------------------------------------------------
# Query functions
# ---------------------------------------------------------------------------

class TestQueryFunctions:
    def test_list_runs(self, tmp_path, monkeypatch):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        disc.create_discovery_run(mode="name", input_json={}, search_plan_json={}, executor="python")
        disc.create_discovery_run(mode="title", input_json={}, search_plan_json={}, executor="python")
        result = disc.list_discovery_runs()
        assert result["total"] == 2

    def test_list_runs_filter_status(self, tmp_path, monkeypatch):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        run = disc.create_discovery_run(mode="name", input_json={}, search_plan_json={}, executor="python")
        disc.update_run_status(run["id"], status="succeeded")
        disc.create_discovery_run(mode="title", input_json={}, search_plan_json={}, executor="python")
        result = disc.list_discovery_runs(status="planned")
        assert result["total"] == 1

    def test_list_hits(self, tmp_path, monkeypatch):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        run = disc.create_discovery_run(mode="name", input_json={}, search_plan_json={}, executor="python")
        disc.insert_discovery_hit(run_id=run["id"], url="https://a.com", title="A")
        disc.insert_discovery_hit(run_id=run["id"], url="https://b.com", title="B")
        result = disc.list_discovery_hits(run_id=run["id"])
        assert result["total"] == 2

    def test_get_run(self, tmp_path, monkeypatch):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        run = disc.create_discovery_run(
            mode="name", input_json={"name": "test"}, search_plan_json={}, executor="python"
        )
        detail = disc.get_discovery_run(run["id"])
        assert detail is not None
        assert detail["mode"] == "name"

    def test_get_nonexistent_run_returns_none(self, tmp_path, monkeypatch):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        assert disc.get_discovery_run("DR-nonexistent") is None

    def test_get_hit(self, tmp_path, monkeypatch):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        run = disc.create_discovery_run(mode="name", input_json={}, search_plan_json={}, executor="python")
        hit = disc.insert_discovery_hit(run_id=run["id"], url="https://a.com", title="A")
        detail = disc.get_discovery_hit(hit["id"])
        assert detail is not None
        assert detail["url"] == "https://a.com"

    def test_get_nonexistent_hit_returns_none(self, tmp_path, monkeypatch):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        assert disc.get_discovery_hit("DH-nonexistent") is None


# ---------------------------------------------------------------------------
# Batch accept
# ---------------------------------------------------------------------------

class TestBatchAccept:
    def test_batch_accept_mixed(self, tmp_path, monkeypatch):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        monkeypatch.setattr(cs, "get_conn", lambda: _conn(db))
        run = disc.create_discovery_run(mode="name", input_json={}, search_plan_json={}, executor="python")
        h1 = disc.insert_discovery_hit(run_id=run["id"], url="https://a.com", title="A")
        h2 = disc.insert_discovery_hit(run_id=run["id"], url="https://b.com", title="B")
        result = disc.batch_accept_hits([h1["id"], h2["id"], "DH-nonexistent"])
        assert len(result["accepted"]) == 2
        assert len(result["failed"]) == 1
        assert result["failed"][0]["hit_id"] == "DH-nonexistent"

    def test_batch_accept_title_only_low_confidence(self, tmp_path, monkeypatch):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        monkeypatch.setattr(cs, "get_conn", lambda: _conn(db))
        run = disc.create_discovery_run(mode="name", input_json={}, search_plan_json={}, executor="python")
        hit = disc.insert_discovery_hit(
            run_id=run["id"], title="Title Only", confidence="low"
        )
        result = disc.batch_accept_hits([hit["id"]])
        assert result["accepted"] == []
        assert len(result["failed"]) == 1
        assert "title-only" in result["failed"][0]["error"]
