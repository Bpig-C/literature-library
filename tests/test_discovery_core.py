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
# Composite Plan generation
# ---------------------------------------------------------------------------

class TestDraftCompositePlan:
    def test_composite_mode_in_valid_modes(self):
        assert "composite" in disc.VALID_MODES

    def test_composite_plan_basic(self):
        plan = disc.draft_composite_plan(names=["GPT-5.6 system card"])
        assert plan["mode"] == "composite"
        assert len(plan["queries"]) > 0
        assert any('"GPT-5.6 system card"' in q for q in plan["queries"])
        assert "reasoning" in plan
        assert "search_strategy" in plan
        assert "dedup_guidance" in plan
        assert "input_signals" in plan
        assert plan["dedup_guidance"]["by_url"] is True
        assert plan["dedup_guidance"]["by_title"] is True
        assert plan["dedup_guidance"]["fuzzy_threshold"] == 0.85

    def test_composite_plan_names_generate_exact_and_fuzzy(self):
        plan = disc.draft_composite_plan(names=["Claude 4 Opus"])
        exact = [q for q in plan['queries'] if '"Claude 4 Opus"' in q]
        fuzzy = [q for q in plan['queries'] if q == 'Claude 4 Opus' and '"' not in q]
        assert len(exact) >= 1
        assert len(fuzzy) >= 1

    def test_composite_plan_titles_generate_phrase_queries(self):
        plan = disc.draft_composite_plan(titles=["Attention Is All You Need"])
        assert any('"Attention Is All You Need"' in q for q in plan["queries"])

    def test_composite_plan_authors_and_institutions_combined(self):
        plan = disc.draft_composite_plan(
            authors=["Yann LeCun"], institutions=["Meta AI"]
        )
        # Should have combined author-institution query
        has_combined = any('Yann LeCun' in q and 'Meta AI' in q for q in plan["queries"])
        assert has_combined

    def test_composite_plan_keywords_as_queries(self):
        plan = disc.draft_composite_plan(keywords=["transformer", "attention mechanism"])
        assert "transformer" in plan["queries"]
        assert "attention mechanism" in plan["queries"]

    def test_composite_plan_cross_signal_combinations(self):
        plan = disc.draft_composite_plan(
            names=["GPT-5"], keywords=["safety report"]
        )
        # Should have name+keyword combination
        has_cross = any("GPT-5" in q and "safety report" in q for q in plan["queries"])
        assert has_cross

    def test_composite_plan_known_urls_as_hints_not_hits(self):
        plan = disc.draft_composite_plan(
            known_urls=["https://openai.com/system-card"],
            titles=["System Card"],
        )
        assert "manual_url" in plan["source_hints"]
        # known_urls should be in input_signals, not auto-created as hits
        assert plan["input_signals"]["known_urls"] == ["https://openai.com/system-card"]

    def test_composite_plan_exclude_terms(self):
        plan = disc.draft_composite_plan(
            names=["test"],
            exclude_terms=["reddit", "forum"],
        )
        assert plan["exclude_terms"] == ["reddit", "forum"]

    def test_composite_plan_preferred_domains(self):
        plan = disc.draft_composite_plan(
            names=["test"],
            preferred_domains=["openai.com", "arxiv.org"],
        )
        assert plan["preferred_domains"] == ["openai.com", "arxiv.org"]

    def test_composite_plan_max_results_clamped(self):
        plan = disc.draft_composite_plan(names=["test"], max_results=999)
        assert plan["max_results"] == 100
        plan2 = disc.draft_composite_plan(names=["test"], max_results=0)
        assert plan2["max_results"] == 1

    def test_composite_plan_empty_signals_returns_valid_plan(self):
        plan = disc.draft_composite_plan()
        assert plan["mode"] == "composite"
        assert plan["queries"] == []
        assert isinstance(plan["source_hints"], list)

    def test_composite_plan_query_cap_avoids_explosion(self):
        plan = disc.draft_composite_plan(
            names=[f"name-{i}" for i in range(20)],
            titles=[f"title-{i}" for i in range(20)],
            keywords=[f"kw-{i}" for i in range(20)],
        )
        assert len(plan["queries"]) <= 10

    def test_composite_plan_freeform_note_in_input_signals(self):
        plan = disc.draft_composite_plan(
            names=["test"],
            freeform_note="Looking for recent safety reports on frontier models",
        )
        assert plan["input_signals"]["freeform_note"] == "Looking for recent safety reports on frontier models"

    def test_composite_plan_search_strategy_focused_for_many_signals(self):
        plan = disc.draft_composite_plan(
            names=["n1", "n2"],
            titles=["t1", "t2"],
            authors=["a1", "a2"],
            institutions=["i1", "i2"],
            keywords=["k1", "k2"],
        )
        assert plan["search_strategy"] == "focused"

    def test_composite_plan_search_strategy_broad_for_few_signals(self):
        plan = disc.draft_composite_plan(names=["only one signal"])
        assert plan["search_strategy"] == "broad"

    def test_composite_plan_search_strategy_hybrid_for_medium_signals(self):
        plan = disc.draft_composite_plan(
            names=["n1", "n2", "n3"],
            keywords=["k1"],
        )
        assert plan["search_strategy"] == "hybrid"

    def test_composite_plan_artifact_type_affects_sources(self):
        plan = disc.draft_composite_plan(
            names=["test model"],
            artifact_type_hint="system_card",
        )
        assert "github" in plan["source_hints"]
        assert "huggingface" in plan["source_hints"]

    # P0-1: Contradiction detection
    def test_composite_plan_contradiction_removes_conflicting_exclude(self):
        plan = disc.draft_composite_plan(
            keywords=["transformer", "attention mechanism"],
            exclude_terms=["attention"],  # "attention" appears in keyword "attention mechanism"
        )
        # "attention" should be removed from exclude_terms due to conflict with signal text
        assert "attention" not in plan["exclude_terms"]
        assert "WARNING" in plan["reasoning"]
        assert "exclude_term" in plan["reasoning"].lower()

    def test_composite_plan_no_contradiction_when_excludes_dont_overlap(self):
        plan = disc.draft_composite_plan(
            keywords=["transformer", "attention mechanism"],
            exclude_terms=["reddit", "blog post"],
        )
        assert plan["exclude_terms"] == ["reddit", "blog post"]
        assert "WARNING" not in plan["reasoning"]

    def test_composite_plan_contradiction_with_name_signal(self):
        plan = disc.draft_composite_plan(
            names=["GPT-5 system card"],
            exclude_terms=["system card"],
        )
        assert "system card" not in plan["exclude_terms"]
        assert "WARNING" in plan["reasoning"]

    # P1-1: Priority-ordered query generation
    def test_composite_plan_priority_name_title_first(self):
        plan = disc.draft_composite_plan(
            names=["Model A"],
            titles=["Important Paper"],
            keywords=["kw1", "kw2", "kw3", "kw4", "kw5", "kw6", "kw7", "kw8"],
        )
        # name+title combination should appear before standalone keywords
        queries = plan["queries"]
        has_name_title = any('"Model A"' in q and '"Important Paper"' in q for q in queries)
        assert has_name_title

    def test_composite_plan_queries_capped_at_10_after_priority_sorting(self):
        plan = disc.draft_composite_plan(
            names=[f"N{i}" for i in range(5)],
            titles=[f"T{i}" for i in range(5)],
            authors=[f"A{i}" for i in range(5)],
            institutions=[f"I{i}" for i in range(5)],
            keywords=[f"K{i}" for i in range(8)],
        )
        assert len(plan["queries"]) <= 10

    # P1-3: freeform_note sanitization
    def test_composite_plan_freeform_note_truncated_at_500_chars(self):
        long_note = "x" * 600
        plan = disc.draft_composite_plan(names=["test"], freeform_note=long_note)
        assert len(plan["input_signals"]["freeform_note"]) <= 515  # 500 + "... [truncated]"
        assert plan["input_signals"]["freeform_note"].endswith("[truncated]")

    def test_composite_plan_freeform_note_strips_control_chars(self):
        note = "hello\x00world\x1f\x0btest"
        plan = disc.draft_composite_plan(names=["test"], freeform_note=note)
        assert "\x00" not in plan["input_signals"]["freeform_note"]
        assert "\x1f" not in plan["input_signals"]["freeform_note"]


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


# ---------------------------------------------------------------------------
# P0-1: Run status machine (planned→running→succeeded/failed)
# ---------------------------------------------------------------------------

def test_insert_hit_flips_planned_to_running(tmp_path, monkeypatch):
    """P0-1: 第一条 hit 回填后，run.status 必须从 planned 变为 running。"""
    db = _db(tmp_path)
    monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
    run = disc.create_discovery_run(
        mode="composite",
        input_json={"mode": "composite"},
        search_plan_json={"queries": ["q"]},
        executor="agent:web-access",
    )
    assert run["status"] == "planned"

    disc.insert_discovery_hit(
        run_id=run["id"], url="https://arxiv.org/abs/2501.99999",
        title="A Test Paper", query="q",
    )
    refreshed = disc.get_discovery_run(run["id"])
    assert refreshed["status"] == "running", refreshed["status"]
    assert refreshed["hits_created"] == 1


def test_complete_run_only_accepts_terminal_status(tmp_path, monkeypatch):
    """P0-1: complete_run 只接受 succeeded/failed，拒绝 planned/running。"""
    db = _db(tmp_path)
    monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
    run = disc.create_discovery_run(
        mode="composite", input_json={}, search_plan_json={},
        executor="agent:web-access")
    disc.complete_run(run["id"], status="succeeded")
    assert disc.get_discovery_run(run["id"])["status"] == "succeeded"

    with pytest.raises(ValueError):
        disc.complete_run(run["id"], status="running")
    with pytest.raises(KeyError):
        disc.complete_run("DR-does-not-exist", status="failed")


# ---------------------------------------------------------------------------
# P0-2: Works-level dedup (dup_of_works)
# ---------------------------------------------------------------------------

class TestWorksLevelDedup:
    def _seed_work(self, db_path, work_id="W-1", title="Goal Misgeneralization Survey",
                   arxiv_id=None, doi=None):
        """Insert a work into the works table for testing."""
        conn = _conn(db_path)
        conn.execute(
            "INSERT OR REPLACE INTO works (id, title, arxiv_id, doi) VALUES (?,?,?,?)",
            (work_id, title, arxiv_id, doi),
        )
        conn.commit()
        conn.close()

    def test_hit_dup_of_existing_work_marked(self, tmp_path, monkeypatch):
        """P0-2: 回填一条 title 与 works 中已有文献高度相似的 hit → 自动带 dup_of_works。"""
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        # Also patch gate.get_conn for light_gate
        from collector import gate
        monkeypatch.setattr(gate, "get_conn", lambda: _conn(db))

        # Seed a work in the database
        self._seed_work(db, work_id="W-1", title="Goal Misgeneralization Survey")

        run = disc.create_discovery_run(
            mode="composite", input_json={}, search_plan_json={},
            executor="agent:web-access")
        res = disc.insert_discovery_hit(
            run_id=run["id"], title="Goal Misgeneralization Survey",
            url="https://example.org/some-blog", query="q",
        )
        assert res["status"] == "created"
        hit = disc.list_discovery_hits(run_id=run["id"])["hits"][0]
        assert hit["verification_status"] == "dup_of_works"
        raw = hit["raw_json"] if isinstance(hit["raw_json"], dict) else {}
        assert raw.get("dup_of_work_id") == "W-1"

    def test_hit_new_when_no_work_match(self, tmp_path, monkeypatch):
        """P0-2: 全新标题 → verification_status 保持 unverified。"""
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        from collector import gate
        monkeypatch.setattr(gate, "get_conn", lambda: _conn(db))

        # No works seeded
        run = disc.create_discovery_run(
            mode="composite", input_json={}, search_plan_json={},
            executor="agent:web-access")
        disc.insert_discovery_hit(
            run_id=run["id"], title="A Brand New Unrelated Paper XYZ123",
            url="https://example.org/new", query="q")
        hit = disc.list_discovery_hits(run_id=run["id"])["hits"][0]
        assert hit["verification_status"] == "unverified"

    def test_hit_dup_does_not_block_insert(self, tmp_path, monkeypatch):
        """P0-2: 即使是重复，也必须插入（status=created），不阻止。"""
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        from collector import gate
        monkeypatch.setattr(gate, "get_conn", lambda: _conn(db))

        # Seed a work
        self._seed_work(db, work_id="W-1", title="Goal Misgeneralization Survey")

        run = disc.create_discovery_run(
            mode="composite", input_json={}, search_plan_json={},
            executor="agent:web-access")
        res = disc.insert_discovery_hit(
            run_id=run["id"], title="Goal Misgeneralization Survey", url="https://x.org/y")
        assert res["status"] == "created"
