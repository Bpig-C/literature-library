# tests/test_discovery_smoke.py
"""Offline smoke test for V1.1 discovery end-to-end flow.

No real network. Uses tmp_path + monkeypatched get_conn.
Tests the complete lifecycle:
  1. Create topic
  2. Generate plan
  3. Create run
  4. Backfill hits (simulated agent backfill)
  5. Accept hit to intake
  6. Verify intake candidate exists with resolution='pending'
"""
from __future__ import annotations

import json
import sqlite3

import pytest

import scripts.migrate_add_intake_candidates as mic
import scripts.migrate_add_discovery as md
from collector import discovery as disc
from collector import candidate_store as cs
from collector import topics


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


class TestDiscoverySmoke:
    """End-to-end offline smoke: topic -> plan -> run -> backfill -> accept -> verify."""

    def test_full_name_discovery_flow(self, tmp_path, monkeypatch):
        """Smoke: name-based discovery from plan to intake candidate."""
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        monkeypatch.setattr(cs, "get_conn", lambda: _conn(db))
        monkeypatch.setattr(topics, "get_conn", lambda: _conn(db))

        # Step 1: Create topic
        topic = topics.create(
            name="frontier model system cards",
            description="collect system cards from major frontier labs",
        )
        assert topic["id"].startswith("CT-")

        # Step 2: Generate plan
        plan = disc.draft_search_plan(
            mode="name",
            name="GPT-5.6 system card",
            artifact_type_hint="system_card",
        )
        assert plan["mode"] == "name"
        assert len(plan["queries"]) > 0
        assert '"GPT-5.6 system card"' in plan["queries"][0]

        # Step 3: Create run (agent:web-access to simulate agent workflow)
        run = disc.create_discovery_run(
            mode="name",
            input_json={"name": "GPT-5.6 system card", "artifact_type_hint": "system_card"},
            search_plan_json=plan,
            executor="agent:web-access",
            collection_topic_id=topic["id"],
        )
        assert run["id"].startswith("DR-")
        assert run["status"] == "planned"
        assert run["hits_created"] == 0

        # Step 4: Agent backfills hits (simulated)
        agent_hits = [
            {
                "source_type": "official_domain",
                "url": "https://openai.com/gpt56-system-card",
                "title": "GPT-5.6 System Card",
                "confidence": "high",
                "reason": "Official OpenAI release page for GPT-5.6 system card",
                "query": '"GPT-5.6 system card"',
                "artifact_type_hint": "system_card",
                "primary_source": "true",
                "content_type": "html",
            },
            {
                "source_type": "web",
                "url": "https://arxiv.org/abs/2501.99999",
                "title": "GPT-5.6 System Card (PDF mirror)",
                "confidence": "medium",
                "reason": "PDF hosted on arxiv, secondary source",
                "query": '"GPT-5.6 system card"',
                "artifact_type_hint": "system_card",
                "primary_source": "false",
                "content_type": "pdf",
            },
            {
                "source_type": "web",
                "url": "https://reddit.com/r/ml/something",
                "title": "Discussion about GPT-5.6 system card",
                "confidence": "low",
                "reason": "Forum discussion, not primary source",
                "query": '"GPT-5.6 system card"',
                "artifact_type_hint": "unknown",
                "primary_source": "false",
                "content_type": "html",
            },
        ]
        results = disc.batch_insert_hits(run_id=run["id"], hits=agent_hits)
        assert all(r["status"] == "created" for r in results)

        # Verify run status updated
        updated_run = disc.get_discovery_run(run["id"])
        assert updated_run["hits_created"] == 3

        # Step 5: Accept high-confidence hit to intake
        hits = disc.list_discovery_hits(run_id=run["id"])
        assert hits["total"] == 3

        high_conf_hit = next(h for h in hits["hits"] if h["confidence"] == "high")
        accept_result = disc.accept_hit_to_intake(high_conf_hit["id"])
        assert accept_result["candidate_id"].startswith("IC-")
        assert accept_result["status"] == "created"

        # Step 6: Verify intake candidate
        conn = _conn(db)
        row = conn.execute(
            """SELECT id, source_type, url_canonical, title, resolution,
                      review_status, collection_topic_id, raw_meta
               FROM intake_candidates WHERE id=?""",
            (accept_result["candidate_id"],),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row["resolution"] == "pending"
        assert row["review_status"] == "pending"
        assert row["collection_topic_id"] == topic["id"]
        assert row["url_canonical"] == "https://openai.com/gpt56-system-card"

        # Verify raw_meta preserves discovery evidence
        meta = json.loads(row["raw_meta"])
        assert meta["discovery_hit_id"] == high_conf_hit["id"]
        assert meta["discovery_run_id"] == run["id"]
        assert meta["source_type"] == "official_domain"
        assert meta["reason"] == "Official OpenAI release page for GPT-5.6 system card"

        # Verify hit is marked as accepted
        accepted_hit = disc.get_discovery_hit(high_conf_hit["id"])
        assert accepted_hit["review_status"] == "accepted"
        assert accepted_hit["candidate_id"] == accept_result["candidate_id"]

    def test_full_title_discovery_flow(self, tmp_path, monkeypatch):
        """Smoke: title-based discovery with academic source hints."""
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        monkeypatch.setattr(cs, "get_conn", lambda: _conn(db))

        # Plan
        plan = disc.draft_search_plan(
            mode="title",
            title="A Survey of AI Evaluation Methods for Frontier Models",
        )
        assert plan["mode"] == "title"
        assert "openalex" in plan["sources"]

        # Run
        run = disc.create_discovery_run(
            mode="title",
            input_json={"title": "A Survey of AI Evaluation Methods for Frontier Models"},
            search_plan_json=plan,
            executor="agent:web-access",
        )

        # Backfill
        disc.batch_insert_hits(run_id=run["id"], hits=[
            {
                "source_type": "semantic_scholar",
                "url": "https://arxiv.org/abs/2501.12345",
                "title": "A Survey of AI Evaluation Methods for Frontier Models",
                "confidence": "high",
                "reason": "Exact title match on Semantic Scholar",
            },
        ])

        # Accept
        hits = disc.list_discovery_hits(run_id=run["id"])
        r = disc.accept_hit_to_intake(hits["hits"][0]["id"])
        assert r["candidate_id"].startswith("IC-")

        # Verify
        conn = _conn(db)
        row = conn.execute(
            "SELECT resolution FROM intake_candidates WHERE id=?",
            (r["candidate_id"],),
        ).fetchone()
        conn.close()
        assert row["resolution"] == "pending"

    def test_topic_discovery_flow(self, tmp_path, monkeypatch):
        """Smoke: topic-based discovery generates plan from topic query_def."""
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        monkeypatch.setattr(cs, "get_conn", lambda: _conn(db))
        monkeypatch.setattr(topics, "get_conn", lambda: _conn(db))

        topic = topics.create(
            name="AI safety benchmarks",
            description="Collect benchmark papers",
        )
        # Add keywords via direct DB update (simulating topic transition)
        qd = {"keywords": ["safety benchmark", "evaluation framework"],
              "known_names": ["HELM"], "known_titles": [], "known_urls": [],
              "explicit_ids": [], "seed_paper_ids": []}
        conn = _conn(db)
        conn.execute(
            "UPDATE collection_topics SET query_def=? WHERE id=?",
            (json.dumps(qd), topic["id"]))
        conn.commit()
        conn.close()

        plan = disc.draft_search_plan(
            mode="topic",
            topic_id=topic["id"],
            topic_name="AI safety benchmarks",
            topic_keywords=qd["keywords"],
            topic_known_names=qd["known_names"],
        )
        assert "AI safety benchmarks" in plan["queries"]
        assert "safety benchmark" in plan["queries"]
        assert "HELM" in plan["queries"]

    def test_reject_hit_flow(self, tmp_path, monkeypatch):
        """Smoke: reject a noisy hit."""
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))

        run = disc.create_discovery_run(
            mode="name", input_json={}, search_plan_json={}, executor="python"
        )
        hit = disc.insert_discovery_hit(
            run_id=run["id"],
            url="https://reddit.com/r/ml/noise",
            title="Noise",
            confidence="low",
        )
        r = disc.reject_hit(hit["id"], review_note="forum noise")
        assert r["review_status"] == "rejected"

        # Verify not in intake
        conn = _conn(db)
        count = conn.execute("SELECT COUNT(*) FROM intake_candidates").fetchone()[0]
        conn.close()
        assert count == 0

    def test_dedup_within_run(self, tmp_path, monkeypatch):
        """Smoke: duplicate URLs within same run are deduped."""
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))

        run = disc.create_discovery_run(
            mode="name", input_json={}, search_plan_json={}, executor="python"
        )
        r1 = disc.insert_discovery_hit(
            run_id=run["id"], url="https://example.com/same", title="First",
        )
        r2 = disc.insert_discovery_hit(
            run_id=run["id"], url="https://example.com/same", title="Duplicate",
        )
        assert r1["status"] == "created"
        assert r2["status"] == "skipped_dup"
        assert r1["id"] == r2["id"]

        hits = disc.list_discovery_hits(run_id=run["id"])
        assert hits["total"] == 1
