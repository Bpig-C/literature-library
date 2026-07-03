# tests/test_discovery_cli.py
"""V1.1 Discovery CLI tests (scripts/literature_discovery.py).

Uses tmp_path + monkeypatched get_conn. No real network.
"""
from __future__ import annotations

import json
import sqlite3

import pytest
from types import SimpleNamespace

import scripts.migrate_add_intake_candidates as mic
import scripts.migrate_add_discovery as md
import scripts.literature_discovery as cli
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
    return c


# ---------------------------------------------------------------------------
# plan command
# ---------------------------------------------------------------------------

class TestPlanCmd:
    def test_plan_name_outputs_json(self, tmp_path, monkeypatch, capsys):
        args = SimpleNamespace(
            mode=None, name="GPT-5.6 system card", title=None, url=None,
            topic=None, artifact_type_hint=None, max_results=20, doi=False,
            arxiv=False, github_url=False,
        )
        cli.plan_cmd(args)
        out = json.loads(capsys.readouterr().out)
        assert out["mode"] == "name"
        assert '"GPT-5.6 system card"' in out["queries"][0]

    def test_plan_title_outputs_json(self, tmp_path, monkeypatch, capsys):
        args = SimpleNamespace(
            mode=None, name=None, title="Exact Paper Title", url=None,
            topic=None, artifact_type_hint=None, max_results=20, doi=False,
            arxiv=False, github_url=False,
        )
        cli.plan_cmd(args)
        out = json.loads(capsys.readouterr().out)
        assert out["mode"] == "title"

    def test_plan_url_outputs_json(self, tmp_path, monkeypatch, capsys):
        args = SimpleNamespace(
            mode=None, name=None, title=None, url="https://example.com/paper.pdf",
            topic=None, artifact_type_hint=None, max_results=20, doi=False,
            arxiv=False, github_url=False,
        )
        cli.plan_cmd(args)
        out = json.loads(capsys.readouterr().out)
        assert out["mode"] == "url"

    def test_plan_topic_outputs_queries(self, tmp_path, monkeypatch, capsys):
        from collector import topics
        monkeypatch.setattr(topics, "get", lambda topic_id: {
            "id": topic_id,
            "name": "frontier model system cards",
            "query_def": {"keywords": ["system card"], "known_names": [], "known_titles": []},
        })
        args = SimpleNamespace(
            mode=None, name=None, title=None, url=None, topic="CT-1",
            artifact_type_hint=None, max_results=20, doi=False, arxiv=False,
            github_url=False,
        )
        cli.plan_cmd(args)
        out = json.loads(capsys.readouterr().out)
        assert out["mode"] == "topic"
        assert "frontier model system cards" in out["queries"]
        assert "system card" in out["queries"]

    def test_plan_doi_exits(self, tmp_path, monkeypatch):
        args = SimpleNamespace(
            mode=None, name=None, title=None, url=None, topic=None,
            artifact_type_hint=None, max_results=20, doi=True, arxiv=False,
            github_url=False,
        )
        with pytest.raises(SystemExit):
            cli.plan_cmd(args)

    def test_plan_no_input_exits(self, tmp_path, monkeypatch):
        args = SimpleNamespace(
            mode=None, name=None, title=None, url=None, topic=None,
            artifact_type_hint=None, max_results=20, doi=False, arxiv=False,
            github_url=False,
        )
        with pytest.raises(SystemExit):
            cli.plan_cmd(args)


# ---------------------------------------------------------------------------
# run command
# ---------------------------------------------------------------------------

class TestRunCmd:
    def test_run_creates_discovery_run(self, tmp_path, monkeypatch, capsys):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        args = SimpleNamespace(
            mode="name",
            input='{"name": "GPT-5.6 system card"}',
            plan=None,
            executor="python",
            topic=None,
        )
        cli.run_cmd(args)
        out = json.loads(capsys.readouterr().out)
        assert out["id"].startswith("DR-")
        assert out["status"] == "planned"

    def test_run_invalid_json_exits(self, tmp_path, monkeypatch):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        args = SimpleNamespace(
            mode="name", input="not-json", plan=None,
            executor="python", topic=None,
        )
        with pytest.raises(SystemExit):
            cli.run_cmd(args)

    def test_run_unsupported_mode_exits(self, tmp_path, monkeypatch):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        args = SimpleNamespace(
            mode="doi", input="{}", plan=None,
            executor="python", topic=None,
        )
        with pytest.raises(SystemExit):
            cli.run_cmd(args)


# ---------------------------------------------------------------------------
# hits command
# ---------------------------------------------------------------------------

class TestHitsCmd:
    def test_hits_output_json(self, tmp_path, monkeypatch, capsys):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        run = disc.create_discovery_run(
            mode="name", input_json={}, search_plan_json={}, executor="python"
        )
        disc.insert_discovery_hit(run_id=run["id"], url="https://a.com", title="A")

        args = SimpleNamespace(run=run["id"], review_status=None)
        cli.hits_cmd(args)
        out = json.loads(capsys.readouterr().out)
        assert out["total"] >= 1

    def test_hits_empty_run_prints_zero(self, tmp_path, monkeypatch, capsys):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        run = disc.create_discovery_run(
            mode="name", input_json={}, search_plan_json={}, executor="python"
        )
        args = SimpleNamespace(run=run["id"], review_status=None)
        cli.hits_cmd(args)
        out = json.loads(capsys.readouterr().out)
        assert out["total"] == 0


# ---------------------------------------------------------------------------
# runs command
# ---------------------------------------------------------------------------

class TestRunsCmd:
    def test_runs_filters_by_topic(self, tmp_path, monkeypatch, capsys):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        disc.create_discovery_run(
            mode="topic", input_json={}, search_plan_json={}, executor="python",
            collection_topic_id="CT-1",
        )
        disc.create_discovery_run(
            mode="topic", input_json={}, search_plan_json={}, executor="python",
            collection_topic_id="CT-2",
        )
        args = SimpleNamespace(topic="CT-1", status=None)
        cli.runs_cmd(args)
        out = json.loads(capsys.readouterr().out)
        assert out["total"] == 1
        assert out["runs"][0]["collection_topic_id"] == "CT-1"


# ---------------------------------------------------------------------------
# accept command
# ---------------------------------------------------------------------------

class TestAcceptCmd:
    def test_accept_creates_intake_candidate(self, tmp_path, monkeypatch, capsys):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        monkeypatch.setattr(cs, "get_conn", lambda: _conn(db))
        run = disc.create_discovery_run(
            mode="name", input_json={}, search_plan_json={}, executor="python"
        )
        hit = disc.insert_discovery_hit(
            run_id=run["id"], url="https://example.com/paper", title="Test"
        )

        args = SimpleNamespace(hits=hit["id"], note=None)
        cli.accept_cmd(args)
        out = json.loads(capsys.readouterr().out)
        assert len(out["accepted"]) == 1
        assert out["accepted"][0]["candidate_id"].startswith("IC-")

    def test_accept_multiple_hits(self, tmp_path, monkeypatch, capsys):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        monkeypatch.setattr(cs, "get_conn", lambda: _conn(db))
        run = disc.create_discovery_run(
            mode="name", input_json={}, search_plan_json={}, executor="python"
        )
        h1 = disc.insert_discovery_hit(run_id=run["id"], url="https://a.com", title="A")
        h2 = disc.insert_discovery_hit(run_id=run["id"], url="https://b.com", title="B")

        args = SimpleNamespace(hits=f"{h1['id']},{h2['id']}", note=None)
        cli.accept_cmd(args)
        out = json.loads(capsys.readouterr().out)
        assert len(out["accepted"]) == 2

    def test_accept_nonexistent_hit_in_failed(self, tmp_path, monkeypatch, capsys):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        monkeypatch.setattr(cs, "get_conn", lambda: _conn(db))
        args = SimpleNamespace(hits="DH-nonexistent", note=None)
        cli.accept_cmd(args)
        out = json.loads(capsys.readouterr().out)
        assert len(out["failed"]) == 1

    def test_accept_empty_hits_exits(self, tmp_path, monkeypatch):
        args = SimpleNamespace(hits="", note=None)
        with pytest.raises(SystemExit):
            cli.accept_cmd(args)


# ---------------------------------------------------------------------------
# reject command
# ---------------------------------------------------------------------------

class TestRejectCmd:
    def test_reject_sets_status(self, tmp_path, monkeypatch, capsys):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        run = disc.create_discovery_run(
            mode="name", input_json={}, search_plan_json={}, executor="python"
        )
        hit = disc.insert_discovery_hit(
            run_id=run["id"], url="https://example.com/noise", title="Noise"
        )
        args = SimpleNamespace(hit=hit["id"], note="not relevant")
        cli.reject_cmd(args)
        out = json.loads(capsys.readouterr().out)
        assert out["review_status"] == "rejected"


# ---------------------------------------------------------------------------
# composite-plan command
# ---------------------------------------------------------------------------

class TestCompositePlanCmd:
    def test_composite_plan_basic_outputs_json(self, tmp_path, monkeypatch, capsys):
        args = SimpleNamespace(
            topic_id=None,
            names=["GPT-5.6 system card"],
            titles=[],
            authors=[],
            institutions=[],
            keywords=["safety"],
            known_urls=[],
            preferred_domains=[],
            exclude_terms=[],
            artifact_type_hint="unknown",
            max_results=20,
            freeform_note="",
        )
        cli.composite_plan_cmd(args)
        out = json.loads(capsys.readouterr().out)
        assert out["mode"] == "composite"
        assert len(out["queries"]) > 0
        assert any("GPT-5.6" in q for q in out["queries"])
        assert out["dedup_guidance"]["by_url"] is True

    def test_composite_plan_with_all_fields(self, tmp_path, monkeypatch, capsys):
        args = SimpleNamespace(
            topic_id=None,
            names=["Claude Opus 4"],
            titles=["Safety Report 2026"],
            authors=["Alice Smith"],
            institutions=["AI Research Lab"],
            keywords=["alignment", "safety evaluation"],
            known_urls=["https://anthropic.com/safety"],
            preferred_domains=["anthropic.com", "arxiv.org"],
            exclude_terms=["reddit", "social media"],
            artifact_type_hint="technical_report",
            max_results=15,
            freeform_note="Looking for recent safety reports",
        )
        cli.composite_plan_cmd(args)
        out = json.loads(capsys.readouterr().out)
        assert out["mode"] == "composite"
        assert len(out["exclude_terms"]) == 2
        assert len(out["preferred_domains"]) == 2
        assert out["max_results"] == 15
        assert out["input_signals"]["freeform_note"] != ""
        assert "github" in out["source_hints"]  # technical_report triggers github/huggingface

    def test_composite_plan_empty_signals(self, tmp_path, monkeypatch, capsys):
        args = SimpleNamespace(
            topic_id=None,
            names=[],
            titles=[],
            authors=[],
            institutions=[],
            keywords=[],
            known_urls=[],
            preferred_domains=[],
            exclude_terms=[],
            artifact_type_hint="unknown",
            max_results=20,
            freeform_note="",
        )
        cli.composite_plan_cmd(args)
        out = json.loads(capsys.readouterr().out)
        assert out["mode"] == "composite"
        assert out["queries"] == []

    def test_composite_plan_query_cap(self, tmp_path, monkeypatch, capsys):
        args = SimpleNamespace(
            topic_id=None,
            names=[f"name-{i}" for i in range(10)],
            titles=[f"title-{i}" for i in range(10)],
            authors=[f"author-{i}" for i in range(5)],
            institutions=[f"inst-{i}" for i in range(5)],
            keywords=[f"kw-{i}" for i in range(10)],
            known_urls=[],
            preferred_domains=[],
            exclude_terms=[],
            artifact_type_hint="unknown",
            max_results=20,
            freeform_note="",
        )
        cli.composite_plan_cmd(args)
        out = json.loads(capsys.readouterr().out)
        assert len(out["queries"]) <= 10


# ---------------------------------------------------------------------------
# Full workflow
# ---------------------------------------------------------------------------

class TestFullWorkflow:
    def test_full_workflow_plan_hit_accept(self, tmp_path, monkeypatch, capsys):
        db = _db(tmp_path)
        monkeypatch.setattr(disc, "get_conn", lambda: _conn(db))
        monkeypatch.setattr(cs, "get_conn", lambda: _conn(db))

        # Plan
        plan_args = SimpleNamespace(
            mode=None, name="GPT-5.6 system card", title=None, url=None,
            topic=None, artifact_type_hint="system_card", max_results=10,
            doi=False, arxiv=False, github_url=False,
        )
        cli.plan_cmd(plan_args)
        plan_out = json.loads(capsys.readouterr().out)
        assert plan_out["mode"] == "name"

        # Run
        run_args = SimpleNamespace(
            mode="name",
            input='{"name": "GPT-5.6 system card"}',
            plan=json.dumps(plan_out),
            executor="python",
            topic=None,
        )
        cli.run_cmd(run_args)
        run_out = json.loads(capsys.readouterr().out)
        assert run_out["id"].startswith("DR-")

        # Insert hit manually
        hit = disc.insert_discovery_hit(
            run_id=run_out["id"],
            url="https://openai.com/system-card",
            title="GPT-5.6 System Card",
        )

        # Accept
        accept_args = SimpleNamespace(hits=hit["id"], note=None)
        cli.accept_cmd(accept_args)
        accept_out = json.loads(capsys.readouterr().out)
        assert len(accept_out["accepted"]) == 1
        assert accept_out["accepted"][0]["candidate_id"].startswith("IC-")

        # Verify intake candidate exists with resolution='pending'
        conn = _conn(db)
        row = conn.execute(
            "SELECT resolution FROM intake_candidates WHERE id=?",
            (accept_out["accepted"][0]["candidate_id"],),
        ).fetchone()
        conn.close()
        assert row["resolution"] == "pending"
