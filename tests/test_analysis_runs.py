"""Tests for P1.1 AnalysisRun: migrate, plan, submit, review, status.

Uses a temporary copy of the database to verify analysis run workflows,
ensuring tests never modify the real library data.
Run with: $env:PYTHONPATH=(Get-Location).Path; uv run pytest tests/test_analysis_runs.py -v
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest

from api.db import DB_PATH

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def tmp_db(tmp_path_factory):
    """Copy real DB to a temp directory for test isolation."""
    tmp_dir = tmp_path_factory.mktemp("litlib_ar_test")
    tmp_db = tmp_dir / "literature.sqlite"
    shutil.copy2(str(DB_PATH), str(tmp_db))
    return tmp_db


@pytest.fixture(scope="module")
def conn(tmp_db):
    """Provide a connection to the temp DB."""
    c = sqlite3.connect(str(tmp_db))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    yield c
    c.close()


@pytest.fixture(autouse=True, scope="module")
def patch_get_conn(tmp_db, conn):
    """Patch get_conn in literature_analyze to use the temp DB."""
    import scripts.literature_analyze as mod

    def _test_get_conn():
        c = sqlite3.connect(str(tmp_db))
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        return c

    original = mod.get_conn
    mod.get_conn = _test_get_conn
    yield
    mod.get_conn = original


# ---------------------------------------------------------------------------
# Helper: find a non-quarantined work_id with content_md_path in temp DB
# ---------------------------------------------------------------------------

def _find_eligible_work(conn):
    """Return (work_id, content_md_path) for a non-quarantined work with parse success."""
    row = conn.execute("""
        SELECT w.id, lpr.content_md_path
        FROM works w
        JOIN literature_parse_runs lpr ON lpr.work_id = w.id
        WHERE lpr.status = 'succeeded'
          AND lpr.content_md_path IS NOT NULL AND lpr.content_md_path != ''
          AND w.read_status != 'quarantined'
        LIMIT 1
    """).fetchone()
    return (row["id"], row["content_md_path"]) if row else (None, None)


def _find_quarantined_work_id(conn):
    """Return a quarantined work_id."""
    row = conn.execute(
        "SELECT id FROM works WHERE read_status = 'quarantined' LIMIT 1"
    ).fetchone()
    return row["id"] if row else None


def _make_valid_envelope(work_id: str, angle: str = "digest", tv: int = 1) -> dict:
    """Return a valid analysis envelope JSON dict."""
    return {
        "work_id": work_id,
        "angle": angle,
        "template_version": tv,
        "confidence": "high",
        "fields": {
            "summary": {
                "value": "Test summary for analysis run.",
                "evidence": {
                    "quote": "This is a test quote from the paper.",
                    "location": "Section 1, Paragraph 2",
                },
            },
        },
        "evidence": {"summary": "Top-level evidence."},
    }


# ---------------------------------------------------------------------------
# 1. Migration idempotency
# ---------------------------------------------------------------------------

class TestMigrationIdempotent:
    def test_run_migration_twice_no_error(self, tmp_db):
        """Running migration twice should not raise or duplicate schema."""
        from scripts.migrate_add_analysis_runs import run_migration

        # Run once (table may already exist from real DB copy)
        run_migration(dry_run=False)
        # Run again - must not error
        run_migration(dry_run=False)

        # Verify table exists
        c = sqlite3.connect(str(tmp_db))
        row = c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='analysis_runs'"
        ).fetchone()
        assert row is not None
        c.close()


# ---------------------------------------------------------------------------
# 2. --plan excludes quarantined works
# ---------------------------------------------------------------------------

class TestPlanExcludesQuarantined:
    def test_plan_no_quarantined_work_ids(self, conn, capsys):
        """Plan output must not contain any quarantined work_id."""
        from scripts.literature_analyze import cmd_plan

        quarantined_id = _find_quarantined_work_id(conn)
        if not quarantined_id:
            pytest.skip("No quarantined works in test DB")

        cmd_plan("digest", 1)
        output = capsys.readouterr().out
        plan = json.loads(output)

        task_work_ids = {t["work_id"] for t in plan.get("tasks", [])}
        assert quarantined_id not in task_work_ids, (
            f"Quarantined work {quarantined_id} found in plan tasks"
        )


# ---------------------------------------------------------------------------
# 3. --plan only uses content_md_path (every task has it and file exists)
# ---------------------------------------------------------------------------

class TestPlanContentMdPath:
    def test_plan_tasks_have_content_md_path(self, capsys):
        """Every task in plan output must have content_md_path pointing to an existing file."""
        from scripts.literature_analyze import cmd_plan

        cmd_plan("digest", 1)
        output = capsys.readouterr().out
        plan = json.loads(output)

        tasks = plan.get("tasks", [])
        if not tasks:
            pytest.skip("No pending tasks in plan")

        for task in tasks:
            assert "content_md_path" in task, f"Task missing content_md_path: {task}"
            md_path = Path(task["content_md_path"])
            assert md_path.exists(), (
                f"content_md_path does not exist: {task['content_md_path']}"
            )


# ---------------------------------------------------------------------------
# 4. --submit writes to DB
# ---------------------------------------------------------------------------

class TestSubmitWritesDB:
    def test_submit_creates_analysis_run_record(self, conn, tmp_path):
        """Submitting a valid JSON should insert a row into analysis_runs."""
        from scripts.literature_analyze import cmd_submit

        work_id, _ = _find_eligible_work(conn)
        if not work_id:
            pytest.skip("No eligible works in test DB")

        # Clean up any previous test run for this work_id
        conn.execute(
            "DELETE FROM analysis_runs WHERE work_id = ? AND angle = 'digest' AND template_version = 1",
            (work_id,),
        )
        conn.commit()

        envelope = _make_valid_envelope(work_id)
        json_file = tmp_path / "test_submit.json"
        json_file.write_text(json.dumps(envelope), encoding="utf-8")

        cmd_submit(str(json_file), "human", None, False)

        row = conn.execute(
            "SELECT * FROM analysis_runs WHERE work_id = ? AND angle = 'digest' AND template_version = 1",
            (work_id,),
        ).fetchone()
        assert row is not None, "No analysis_runs row found after submit"
        assert row["review_status"] == "pending"
        assert row["executor"] == "human"

        # Cleanup
        conn.execute("DELETE FROM analysis_runs WHERE id = ?", (row["id"],))
        conn.commit()


# ---------------------------------------------------------------------------
# 5. --submit generates Markdown file
# ---------------------------------------------------------------------------

class TestSubmitGeneratesMarkdown:
    def test_submit_creates_md_file(self, conn, tmp_path):
        """After submit, works/{work_id}/analyses/ should contain a .md file."""
        from scripts.literature_analyze import cmd_submit, LIBRARY_ROOT

        work_id, _ = _find_eligible_work(conn)
        if not work_id:
            pytest.skip("No eligible works in test DB")

        # Clean up
        conn.execute(
            "DELETE FROM analysis_runs WHERE work_id = ? AND angle = 'digest' AND template_version = 1",
            (work_id,),
        )
        conn.commit()

        envelope = _make_valid_envelope(work_id)
        json_file = tmp_path / "test_md_gen.json"
        json_file.write_text(json.dumps(envelope), encoding="utf-8")

        cmd_submit(str(json_file), "human", None, False)

        analyses_dir = LIBRARY_ROOT / "works" / work_id / "analyses"
        assert analyses_dir.exists(), f"analyses dir not created: {analyses_dir}"
        md_files = list(analyses_dir.glob("*_digest@v1.md"))
        assert len(md_files) >= 1, f"No digest md file found in {analyses_dir}"

        # Verify md content has expected header
        md_text = md_files[0].read_text(encoding="utf-8")
        assert "# Analysis: digest v1" in md_text

        # Cleanup DB + file
        conn.execute(
            "DELETE FROM analysis_runs WHERE work_id = ? AND angle = 'digest'",
            (work_id,),
        )
        conn.commit()
        for f in md_files:
            f.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 6. --submit rejects missing evidence
# ---------------------------------------------------------------------------

class TestSubmitRejectsMissingEvidence:
    def test_submit_no_evidence_rejected(self, conn, tmp_path, capsys):
        """Envelope without quote or location in evidence should be rejected."""
        from scripts.literature_analyze import cmd_submit

        work_id, _ = _find_eligible_work(conn)
        if not work_id:
            pytest.skip("No eligible works in test DB")

        # Envelope with no evidence at all
        bad_envelope = {
            "work_id": work_id,
            "angle": "digest",
            "template_version": 1,
            "confidence": "high",
            "fields": {"summary": {"value": "no evidence"}},
        }
        json_file = tmp_path / "bad_evidence.json"
        json_file.write_text(json.dumps(bad_envelope), encoding="utf-8")

        cmd_submit(str(json_file), "human", None, False)
        output = capsys.readouterr().out
        result = json.loads(output)
        assert len(result["results"]) > 0
        assert result["results"][0]["status"] == "rejected"
        errors = result["results"][0].get("errors", [])
        assert any("evidence" in e for e in errors)


# ---------------------------------------------------------------------------
# 7. Duplicate submit rejected (same work_id + angle + template_version)
# ---------------------------------------------------------------------------

class TestDuplicateSubmitRejected:
    def test_second_submit_same_key_rejected(self, conn, tmp_path, capsys):
        """Second submit with same work_id+angle+template_version should be rejected."""
        from scripts.literature_analyze import cmd_submit

        work_id, _ = _find_eligible_work(conn)
        if not work_id:
            pytest.skip("No eligible works in test DB")

        # Clean up
        conn.execute(
            "DELETE FROM analysis_runs WHERE work_id = ? AND angle = 'digest' AND template_version = 1",
            (work_id,),
        )
        conn.commit()

        envelope = _make_valid_envelope(work_id)
        json_file = tmp_path / "dup_submit.json"
        json_file.write_text(json.dumps(envelope), encoding="utf-8")

        # First submit
        cmd_submit(str(json_file), "human", None, False)
        capsys.readouterr()  # flush first submit output

        # Second submit (should be rejected)
        cmd_submit(str(json_file), "human", None, False)
        output = capsys.readouterr().out
        result = json.loads(output)
        assert len(result["results"]) > 0
        assert result["results"][0]["status"] == "rejected"
        assert "not superseded" in result["results"][0]["error"]

        # Cleanup
        conn.execute(
            "DELETE FROM analysis_runs WHERE work_id = ? AND angle = 'digest'",
            (work_id,),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# 8. --review status transition
# ---------------------------------------------------------------------------

class TestReviewStatusTransition:
    def test_review_updates_status(self, conn, tmp_path):
        """Review should update review_status on the analysis run."""
        from scripts.literature_analyze import cmd_submit, cmd_review

        work_id, _ = _find_eligible_work(conn)
        if not work_id:
            pytest.skip("No eligible works in test DB")

        # Clean up
        conn.execute(
            "DELETE FROM analysis_runs WHERE work_id = ? AND angle = 'digest' AND template_version = 1",
            (work_id,),
        )
        conn.commit()

        # Submit first
        envelope = _make_valid_envelope(work_id)
        json_file = tmp_path / "review_test.json"
        json_file.write_text(json.dumps(envelope), encoding="utf-8")
        cmd_submit(str(json_file), "human", None, False)

        # Get the run_id
        row = conn.execute(
            "SELECT id FROM analysis_runs WHERE work_id = ? AND angle = 'digest'",
            (work_id,),
        ).fetchone()
        assert row is not None
        run_id = row["id"]

        # Review as approved
        cmd_review(run_id, "approved", "LGTM", "human")

        row = conn.execute(
            "SELECT review_status, review_note FROM analysis_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        assert row["review_status"] == "approved"
        assert row["review_note"] == "LGTM"

        # Cleanup
        conn.execute("DELETE FROM analysis_runs WHERE id = ?", (run_id,))
        conn.commit()


# ---------------------------------------------------------------------------
# 9. --status statistics correct
# ---------------------------------------------------------------------------

class TestStatusStatistics:
    def test_status_output_after_data(self, conn, tmp_path, capsys):
        """Status output should reflect correct counts after inserting a run."""
        from scripts.literature_analyze import cmd_submit, cmd_status

        work_id, _ = _find_eligible_work(conn)
        if not work_id:
            pytest.skip("No eligible works in test DB")

        # Clean up
        conn.execute(
            "DELETE FROM analysis_runs WHERE work_id = ? AND angle = 'digest' AND template_version = 1",
            (work_id,),
        )
        conn.commit()

        # Submit a run
        envelope = _make_valid_envelope(work_id)
        json_file = tmp_path / "status_test.json"
        json_file.write_text(json.dumps(envelope), encoding="utf-8")
        cmd_submit(str(json_file), "human", None, False)
        capsys.readouterr()  # flush submit output

        # Get status
        cmd_status()
        output = capsys.readouterr().out
        status = json.loads(output)

        assert "active_works" in status
        assert "total_runs" in status
        assert status["total_runs"] >= 1

        # Find our angle in the list
        digest_angles = [
            a for a in status["angles"]
            if a["angle"] == "digest" and a["template_version"] == 1
        ]
        assert len(digest_angles) >= 1, "digest@v1 not found in status angles"
        assert digest_angles[0]["pending"] >= 1

        # Cleanup
        conn.execute(
            "DELETE FROM analysis_runs WHERE work_id = ? AND angle = 'digest'",
            (work_id,),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Edge cases and validation
# ---------------------------------------------------------------------------

class TestValidateEnvelope:
    def test_validate_envelope_missing_fields(self):
        """validate_envelope should catch missing required fields."""
        from scripts.literature_analyze import validate_envelope

        errors = validate_envelope({})
        assert len(errors) > 0
        assert any("angle" in e for e in errors)
        assert any("template_version" in e for e in errors)
        assert any("work_id" in e for e in errors)
        assert any("fields" in e for e in errors)
        assert any("confidence" in e for e in errors)

    def test_validate_envelope_invalid_confidence(self):
        from scripts.literature_analyze import validate_envelope

        data = {
            "work_id": "W-test",
            "angle": "digest",
            "template_version": 1,
            "fields": {"f": {"value": "v"}},
            "confidence": "invalid",
        }
        errors = validate_envelope(data)
        assert any("confidence" in e for e in errors)

    def test_validate_envelope_valid(self):
        from scripts.literature_analyze import validate_envelope

        data = _make_valid_envelope("W-test")
        errors = validate_envelope(data)
        assert errors == []


class TestRenderMarkdown:
    def test_render_markdown_contains_fields(self):
        """render_markdown output should contain work_id and fields."""
        from scripts.literature_analyze import render_markdown

        data = _make_valid_envelope("W-test-render")
        md = render_markdown(data, "digest", 1)
        assert "W-test-render" in md
        assert "summary" in md
        assert "This is a test quote" in md


class TestCmdPlanTemplateNotFound:
    def test_plan_nonexistent_template(self, capsys):
        """Plan with non-existent template should output error JSON."""
        from scripts.literature_analyze import cmd_plan

        with pytest.raises(SystemExit):
            cmd_plan("nonexistent_angle", 999)


class TestCmdSubmitInvalidPath:
    def test_submit_nonexistent_path(self, capsys):
        """Submit with non-existent path should exit with error."""
        from scripts.literature_analyze import cmd_submit

        with pytest.raises(SystemExit):
            cmd_submit("/nonexistent/path/does/not/exist.json", "human", None, False)


class TestCmdReviewNotFound:
    def test_review_nonexistent_run(self, capsys):
        """Review of non-existent run_id should exit with error."""
        from scripts.literature_analyze import cmd_review

        with pytest.raises(SystemExit):
            cmd_review("AR-nonexistent123", "approved", "note", "human")
