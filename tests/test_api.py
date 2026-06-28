"""Basic API route tests for the literature library.

Uses a temporary copy of the database to verify core API endpoints,
ensuring tests never modify the real library data.
Run with: uv run python -m pytest tests/test_api.py -v
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.db import DB_PATH
from api.main import app

# Create a temporary copy of the real DB for testing
_tmp_dir = tempfile.mkdtemp(prefix="litlib_test_")
_tmp_db = Path(_tmp_dir) / "literature.sqlite"
shutil.copy2(str(DB_PATH), str(_tmp_db))


def _test_get_conn():
    conn = sqlite3.connect(str(_tmp_db))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# Patch get_conn in all route modules so routes use the temp DB
@pytest.fixture(autouse=True, scope="session")
def _patch_get_conn():
    with patch("api.routes.works.get_conn", _test_get_conn), \
         patch("api.routes.relations.get_conn", _test_get_conn), \
         patch("api.routes.duplicates.get_conn", _test_get_conn), \
         patch("api.routes.files.get_conn", _test_get_conn), \
         patch("api.routes.metadata.get_conn", _test_get_conn), \
         patch("api.routes.classification.get_conn", _test_get_conn):
        yield


@pytest.fixture(autouse=True, scope="session")
def _cleanup_temp_db():
    yield
    shutil.rmtree(_tmp_dir, ignore_errors=True)


@pytest.fixture(autouse=True, scope="session")
def _seed_classification_extractions():
    """Seed synthetic classification_extractions for testing."""
    import json as _json
    from datetime import datetime, timezone

    conn = _test_get_conn()
    # Check if classification_extractions table exists
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='classification_extractions'"
    ).fetchone()
    if not exists:
        conn.close()
        return

    # Get a work_id to attach extractions to
    row = conn.execute("SELECT id FROM works LIMIT 1").fetchone()
    if not row:
        conn.close()
        return
    work_id = row["id"]

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Get a second work_id for the approve test (isolated from batch approve)
    row2 = conn.execute("SELECT id FROM works WHERE id != ? LIMIT 1", (work_id,)).fetchone()
    work_id_2 = row2["id"] if row2 else work_id

    # Seed synthetic extractions
    seeds = [
        {
            "id": "CE-test-pending-low",
            "work_id": work_id,
            "model_name": "qwen3:4b-instruct-2507-q4_K_M",
            "prompt_version": "v1",
            "extracted_json": _json.dumps({
                "primary_doc_type": "evaluation_report",
                "publication_status": "published",
                "reading_lane": ["evaluation_method"],
                "artifact_focus": ["audit_finding"],
                "evidence": {"primary_doc_type": "third-party evaluation of model"},
            }, ensure_ascii=False),
            "confidence_json": _json.dumps({"primary_doc_type": "high"}),
            "ambiguity_score": 10,
            "ambiguity_reasons": _json.dumps(["1 alternative proposed"]),
            "review_status": "pending",
            "applied": 0,
            "raw_response": "{}",
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": "CE-test-approve-only",
            "work_id": work_id_2,
            "model_name": "qwen3:4b-instruct-2507-q4_K_M",
            "prompt_version": "v1",
            "extracted_json": _json.dumps({
                "primary_doc_type": "standard_guideline",
                "publication_status": "published",
                "reading_lane": ["governance_method"],
                "artifact_focus": ["framework_proposal"],
                "evidence": {"primary_doc_type": "standard guideline document"},
            }, ensure_ascii=False),
            "confidence_json": _json.dumps({"primary_doc_type": "high"}),
            "ambiguity_score": 25,
            "ambiguity_reasons": _json.dumps(["medium ambiguity"]),
            "review_status": "pending",
            "applied": 0,
            "raw_response": "{}",
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": "CE-test-pending-high",
            "work_id": work_id,
            "model_name": "qwen3:4b-instruct-2507-q4_K_M",
            "prompt_version": "v1",
            "extracted_json": _json.dumps({
                "primary_doc_type": None,
                "reading_lane": [],
                "artifact_focus": [],
                "evidence": {},
            }, ensure_ascii=False),
            "confidence_json": _json.dumps({}),
            "ambiguity_score": 70,
            "ambiguity_reasons": _json.dumps(["primary_doc_type is null"]),
            "review_status": "pending",
            "applied": 0,
            "raw_response": "{}",
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": "CE-test-approved",
            "work_id": work_id,
            "model_name": "qwen3:4b-instruct-2507-q4_K_M",
            "prompt_version": "v1",
            "extracted_json": _json.dumps({
                "primary_doc_type": "technical_report",
                "publication_status": "published",
                "reading_lane": ["system_transparency"],
                "artifact_focus": ["capability_profile"],
                "evidence": {"primary_doc_type": "technical report about system"},
            }, ensure_ascii=False),
            "confidence_json": _json.dumps({"primary_doc_type": "high"}),
            "ambiguity_score": 5,
            "ambiguity_reasons": _json.dumps([]),
            "review_status": "approved",
            "applied": 1,
            "applied_at": now,
            "raw_response": "{}",
            "created_at": now,
            "updated_at": now,
        },
    ]

    for s in seeds:
        conn.execute(
            "INSERT OR REPLACE INTO classification_extractions "
            "(id, work_id, model_name, prompt_version, extracted_json, confidence_json, "
            "ambiguity_score, ambiguity_reasons, review_status, applied, applied_at, "
            "raw_response, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (s["id"], s["work_id"], s["model_name"], s["prompt_version"],
             s["extracted_json"], s["confidence_json"], s["ambiguity_score"],
             s["ambiguity_reasons"], s["review_status"], s["applied"],
             s.get("applied_at"), s["raw_response"], s["created_at"], s["updated_at"]),
        )
    conn.commit()
    conn.close()


client = TestClient(app)


class TestWorksList(unittest.TestCase):
    def test_list_works_returns_results(self):
        resp = client.get("/api/works")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("works", data)
        self.assertIn("total", data)
        self.assertGreater(data["total"], 0)

    def test_list_works_has_summary(self):
        resp = client.get("/api/works")
        data = resp.json()
        self.assertIn("summary", data)
        self.assertIn("total", data["summary"])
        self.assertIn("statuses", data["summary"])

    def test_list_works_search(self):
        resp = client.get("/api/works?search=arxiv")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("works", data)

    def test_list_works_filter_status(self):
        resp = client.get("/api/works?status=unread")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for w in data["works"]:
            self.assertEqual(w["read_status"], "unread")

    def test_list_works_pagination(self):
        resp = client.get("/api/works?page=1&per_page=5")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertLessEqual(len(data["works"]), 5)

    def test_list_works_has_unique_source_count(self):
        resp = client.get("/api/works?per_page=3")
        data = resp.json()
        for w in data["works"]:
            self.assertIn("unique_source_count", w)
            self.assertGreaterEqual(w["unique_source_count"], 1)
            self.assertLessEqual(w["unique_source_count"], w["source_count"])


class TestWorkDetail(unittest.TestCase):
    def _get_first_work_id(self):
        resp = client.get("/api/works?per_page=1")
        return resp.json()["works"][0]["id"]

    def test_get_work_detail(self):
        wid = self._get_first_work_id()
        resp = client.get(f"/api/works/{wid}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["id"], wid)
        self.assertIn("title", data)
        self.assertIn("source_files", data)
        self.assertIn("relations", data)

    def test_get_work_not_found(self):
        resp = client.get("/api/works/W-nonexistent-999")
        self.assertEqual(resp.status_code, 404)


class TestFileContent(unittest.TestCase):
    def _get_first_work_id(self):
        resp = client.get("/api/works?per_page=1")
        return resp.json()["works"][0]["id"]

    def test_get_content(self):
        wid = self._get_first_work_id()
        resp = client.get(f"/api/files/{wid}/content")
        # Content may or may not exist, but endpoint should not 500
        self.assertIn(resp.status_code, [200, 404])


class TestQuarantineRestore(unittest.TestCase):
    def test_quarantine_and_restore_roundtrip(self):
        """Test quarantine then restore on a work (safe: restores original state)."""
        # Find an unread work
        resp = client.get("/api/works?status=unread&per_page=1")
        works = resp.json()["works"]
        self.assertTrue(len(works) > 0, "No unread works found")
        wid = works[0]["id"]

        # Quarantine
        resp = client.post(f"/api/works/{wid}/quarantine", json={"reason": "test quarantine"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))

        # Verify quarantined
        resp = client.get(f"/api/works/{wid}")
        self.assertEqual(resp.json()["read_status"], "quarantined")

        # Restore
        resp = client.post(f"/api/works/{wid}/restore")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))

        # Verify restored
        resp = client.get(f"/api/works/{wid}")
        self.assertEqual(resp.json()["read_status"], "unread")

    def test_quarantine_not_found(self):
        resp = client.post("/api/works/W-nonexistent-999/quarantine", json={})
        self.assertEqual(resp.status_code, 404)


class TestDuplicates(unittest.TestCase):
    def test_list_duplicates(self):
        resp = client.get("/api/duplicates")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("groups", data)
        self.assertIn("total_groups", data)
        self.assertGreater(data["total_groups"], 0)

    def test_duplicates_have_candidates(self):
        resp = client.get("/api/duplicates")
        data = resp.json()
        for g in data["groups"]:
            self.assertIn("candidates", g)
            self.assertIsInstance(g["candidates"], list)

    def test_review_endpoint_returns_actions(self):
        """Test review endpoint structure by re-reviewing an already-reviewed group."""
        resp = client.get("/api/duplicates")
        groups = resp.json()["groups"]
        # Find an already-reviewed exact_sha256 group
        reviewed = [g for g in groups if g["auto_confirmed"] and g["candidates"][0].get("reviewed")]
        self.assertTrue(len(reviewed) > 0, "No reviewed groups found")
        gid = reviewed[0]["id"]
        # Re-review with same_work (should be idempotent)
        resp = client.post(f"/api/duplicates/{gid}/review", json={
            "decision": "same_work",
            "note": "test re-review",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertIn("actions", data)


class TestRelations(unittest.TestCase):
    def test_list_relations(self):
        resp = client.get("/api/relations")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("relations", data)

    def test_create_and_delete_relation(self):
        import json as _json

        # Get two distinct work IDs
        resp = client.get("/api/works?per_page=10")
        works = resp.json()["works"]
        self.assertGreaterEqual(len(works), 2)
        wid_a = works[0]["id"]
        wid_b = works[1]["id"]

        # Create relation
        resp = client.post("/api/relations", json={
            "work_id_a": wid_a,
            "work_id_b": wid_b,
            "relation_type": "not_duplicate",
            "note": "test relation",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))

        # Delete relation (TestClient.delete doesn't support json=, use request)
        resp = client.request(
            "DELETE", "/api/relations",
            content=_json.dumps({
                "work_id_a": wid_a,
                "work_id_b": wid_b,
                "relation_type": "not_duplicate",
            }),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))


class TestMetadata(unittest.TestCase):
    def test_list_metadata(self):
        resp = client.get("/api/metadata?status=all")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("extractions", data)
        self.assertIn("total", data)
        self.assertIn("summary", data)

    def test_list_metadata_summary(self):
        resp = client.get("/api/metadata?status=all")
        data = resp.json()
        summary = data["summary"]
        self.assertIn("pending", summary)
        self.assertIn("approved", summary)
        self.assertIn("all", summary)

    def test_get_metadata_detail(self):
        resp = client.get("/api/metadata?status=all&per_page=1")
        exts = resp.json()["extractions"]
        if not exts:
            self.skipTest("No metadata extractions in test DB")
            return
        ext_id = exts[0]["id"]
        resp = client.get(f"/api/metadata/{ext_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["id"], ext_id)
        self.assertIn("extracted_json", data)
        self.assertIn("current", data)

    def test_get_metadata_not_found(self):
        resp = client.get("/api/metadata/ME-nonexistent")
        self.assertEqual(resp.status_code, 404)

    def test_review_metadata(self):
        resp = client.get("/api/metadata?status=pending&per_page=1")
        exts = resp.json()["extractions"]
        if not exts:
            self.skipTest("No pending extractions")
            return
        ext_id = exts[0]["id"]
        resp = client.patch(f"/api/metadata/{ext_id}/review", json={
            "review_status": "approved",
            "review_note": "test review",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))

        # Verify status changed
        resp = client.get(f"/api/metadata/{ext_id}")
        self.assertEqual(resp.json()["review_status"], "approved")

    def test_review_invalid_status(self):
        resp = client.get("/api/metadata?status=all&per_page=1")
        exts = resp.json()["extractions"]
        if not exts:
            self.skipTest("No extractions")
            return
        ext_id = exts[0]["id"]
        resp = client.patch(f"/api/metadata/{ext_id}/review", json={
            "review_status": "invalid_status",
        })
        self.assertEqual(resp.status_code, 400)

    def test_apply_approved(self):
        resp = client.post("/api/metadata/apply-approved")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("applied", resp.json())

    def test_approve_fills_works_and_marks_only_current(self):
        """Approve an extraction: works fields filled, only that ext marked applied."""
        import json as _json

        # Find a pending extraction for a work with empty doi
        resp = client.get("/api/metadata?status=pending&per_page=50")
        exts = resp.json()["extractions"]
        target = None
        for e in exts:
            ej = e.get("extracted_json", {})
            conf = e.get("confidence_json", {})
            # Need an extraction with high-confidence doi and work.doi is empty
            if conf.get("doi") == "high" and ej.get("doi") and not e.get("current", {}).get("doi"):
                target = e
                break
        if not target:
            self.skipTest("No pending extraction with high-conf doi for empty work")
            return

        ext_id = target["id"]
        work_id = target["work_id"]
        new_doi = target["extracted_json"]["doi"]

        # Approve
        resp = client.patch(f"/api/metadata/{ext_id}/review", json={
            "review_status": "approved",
            "review_note": "test apply",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("applied"), 1, "Should have applied to works")

        # Verify works.doi was filled
        resp = client.get(f"/api/works/{work_id}")
        self.assertEqual(resp.json()["doi"], new_doi)

        # Verify only this extraction is marked applied (not others with same work_id)
        conn = _test_get_conn()
        rows = conn.execute(
            "SELECT id, applied FROM metadata_extractions WHERE work_id = ?", (work_id,)
        ).fetchall()
        applied_ids = [r["id"] for r in rows if r["applied"]]
        self.assertEqual(applied_ids, [ext_id],
                         f"Only {ext_id} should be applied, but got {applied_ids}")
        conn.close()

    def test_approve_sets_fix_action_on_edit(self):
        """When edited_fields provided, fix_action should be 'edited'."""
        resp = client.get("/api/metadata?status=pending&per_page=1")
        exts = resp.json()["extractions"]
        if not exts:
            self.skipTest("No pending extractions")
            return
        ext_id = exts[0]["id"]
        resp = client.patch(f"/api/metadata/{ext_id}/review", json={
            "review_status": "needs_fix",
            "review_note": "edited test",
            "edited_fields": {"venue": "Test Venue"},
        })
        self.assertEqual(resp.status_code, 200)

        # Verify fix_action
        conn = _test_get_conn()
        row = conn.execute(
            "SELECT fix_action FROM metadata_extractions WHERE id = ?", (ext_id,)
        ).fetchone()
        conn.close()
        self.assertEqual(row["fix_action"], "edited")

    def test_human_edit_promotes_field_for_apply(self):
        """Human-edited fields should apply even when model confidence was low."""
        import json as _json

        conn = _test_get_conn()
        work = conn.execute(
            "SELECT id FROM works WHERE venue IS NULL OR venue = '' LIMIT 1"
        ).fetchone()
        if not work:
            conn.close()
            self.skipTest("No work with empty venue")
            return

        work_id = work["id"]
        ext_id = "ME-test-human-edit-promote"
        conn.execute("DELETE FROM metadata_extractions WHERE id = ?", (ext_id,))
        conn.execute(
            """
            INSERT INTO metadata_extractions
            (id, work_id, model_name, content_md_path, input_chars, input_tokens_est,
             raw_response, extracted_json, confidence_json, applied, created_at,
             review_status, review_note, risk_level, risk_score, risk_reasons,
             review_source, fix_action, superseded_by)
            VALUES (?, ?, 'test-model', '', 0, 0, '{}', ?, ?, 0, datetime('now'),
                    'pending', '', 'low', 0, '[]', 'human', '', '')
            """,
            (
                ext_id,
                work_id,
                _json.dumps({"venue": "Untrusted Venue"}, ensure_ascii=False),
                _json.dumps({"venue": "low"}, ensure_ascii=False),
            ),
        )
        conn.commit()
        conn.close()

        resp = client.patch(f"/api/metadata/{ext_id}/review", json={
            "review_status": "approved",
            "review_note": "human confirmed venue",
            "edited_fields": {"venue": "Human Confirmed Venue"},
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("applied"), 1)

        resp = client.get(f"/api/works/{work_id}")
        self.assertEqual(resp.json()["venue"], "Human Confirmed Venue")

        conn = _test_get_conn()
        row = conn.execute(
            "SELECT confidence_json, fix_action, applied FROM metadata_extractions WHERE id = ?",
            (ext_id,),
        ).fetchone()
        conn.close()
        confidence = _json.loads(row["confidence_json"])
        self.assertEqual(confidence["venue"], "high")
        self.assertEqual(row["fix_action"], "edited")
        self.assertEqual(row["applied"], 1)

    def test_rerun_supersede_write_marks_old_and_creates_new(self):
        """Rerun writer should create a new extraction and link the old one."""
        import json as _json
        from scripts.literature_metadata_rerun import write_superseding_extraction

        conn = _test_get_conn()
        work = conn.execute("SELECT id FROM works LIMIT 1").fetchone()
        if not work:
            conn.close()
            self.skipTest("No works")
            return

        work_id = work["id"]
        old_id = "ME-test-rerun-old"
        new_id = "ME-test-rerun-new"
        conn.execute("DELETE FROM metadata_extractions WHERE id IN (?, ?)", (old_id, new_id))
        conn.execute(
            """
            INSERT INTO metadata_extractions
            (id, work_id, model_name, content_md_path, input_chars, input_tokens_est,
             raw_response, extracted_json, confidence_json, applied, created_at,
             review_status, review_note, risk_level, risk_score, risk_reasons,
             review_source, fix_action, superseded_by)
            VALUES (?, ?, 'test-model', '', 0, 0, '{}', '{}', '{}', 0, datetime('now'),
                    'needs_fix', 'old note', 'high', 80, '[]', 'human', '', '')
            """,
            (old_id, work_id),
        )

        write_superseding_extraction(conn, {
            "id": new_id,
            "old_id": old_id,
            "work_id": work_id,
            "model_name": "test-model",
            "content_md_path": "",
            "input_chars": 10,
            "input_tokens_est": 3,
            "raw_response": "{}",
            "extracted_json": {"title": "New title", "confidence": {"title": "high"}},
            "confidence_json": {"title": "high"},
            "risk": {"risk_level": "low", "risk_score": 0, "risk_reasons": []},
            "review_note": "rerun from old",
            "created_at": "2026-01-01T00:00:00+00:00",
        })

        old_row = conn.execute(
            "SELECT superseded_by, fix_action FROM metadata_extractions WHERE id = ?",
            (old_id,),
        ).fetchone()
        new_row = conn.execute(
            "SELECT review_status, review_source, extracted_json FROM metadata_extractions WHERE id = ?",
            (new_id,),
        ).fetchone()
        conn.close()

        self.assertEqual(old_row["superseded_by"], new_id)
        self.assertEqual(old_row["fix_action"], "rerun_requested")
        self.assertEqual(new_row["review_status"], "pending")
        self.assertEqual(new_row["review_source"], "agent")
        self.assertEqual(_json.loads(new_row["extracted_json"])["title"], "New title")

    def test_supersede_requires_explicit_replacement_fields(self):
        resp = client.get("/api/metadata?status=all&per_page=1")
        exts = resp.json()["extractions"]
        if not exts:
            self.skipTest("No metadata extractions")
            return
        resp = client.post(f"/api/metadata/{exts[0]['id']}/supersede", json={
            "review_note": "no replacement",
        })
        self.assertEqual(resp.status_code, 400)


class TestMetadataQuarantine(unittest.TestCase):
    """Tests for quarantining works from the metadata review page."""

    def _find_non_quarantined_ext(self):
        """Find a pending extraction for a non-quarantined work."""
        resp = client.get("/api/metadata?status=all&per_page=50")
        exts = resp.json()["extractions"]
        for e in exts:
            if e.get("review_status") == "pending":
                return e
        # Fall back to any extraction
        return exts[0] if exts else None

    def test_quarantine_requires_valid_reason(self):
        ext = self._find_non_quarantined_ext()
        if not ext:
            self.skipTest("No extractions")
            return
        # No reason
        resp = client.post(f"/api/metadata/{ext['id']}/quarantine", json={})
        self.assertEqual(resp.status_code, 400)
        # Invalid reason
        resp = client.post(f"/api/metadata/{ext['id']}/quarantine", json={"reason": "invalid"})
        self.assertEqual(resp.status_code, 400)

    def test_quarantine_not_found(self):
        resp = client.post("/api/metadata/ME-nonexistent/quarantine", json={"reason": "bad_source"})
        self.assertEqual(resp.status_code, 404)

    def test_quarantine_marks_extraction_and_work(self):
        """Quarantine should mark extraction as rejected and work as quarantined."""
        import json as _json

        conn = _test_get_conn()
        # Find a work that's not quarantined and has a pending extraction
        row = conn.execute(
            "SELECT me.id AS ext_id, me.work_id FROM metadata_extractions me "
            "JOIN works w ON w.id = me.work_id "
            "WHERE me.review_status = 'pending' AND w.read_status != 'quarantined' LIMIT 1"
        ).fetchone()
        if not row:
            conn.close()
            self.skipTest("No pending extraction for non-quarantined work")
            return
        ext_id = row["ext_id"]
        work_id = row["work_id"]
        conn.close()

        resp = client.post(f"/api/metadata/{ext_id}/quarantine", json={"reason": "bad_source"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))
        self.assertEqual(resp.json()["work_id"], work_id)

        # Verify extraction is rejected with quarantined fix_action
        conn = _test_get_conn()
        ext_row = conn.execute(
            "SELECT review_status, fix_action, review_source FROM metadata_extractions WHERE id = ?",
            (ext_id,),
        ).fetchone()
        self.assertEqual(ext_row["review_status"], "rejected")
        self.assertEqual(ext_row["fix_action"], "quarantined")
        self.assertEqual(ext_row["review_source"], "human")

        # Verify work is quarantined
        work_row = conn.execute(
            "SELECT read_status FROM works WHERE id = ?", (work_id,)
        ).fetchone()
        self.assertEqual(work_row["read_status"], "quarantined")

        # Verify work_codes has quarantine entry
        code_row = conn.execute(
            "SELECT code, reason FROM work_codes WHERE work_id = ? AND code = 'quarantined'",
            (work_id,),
        ).fetchone()
        self.assertIsNotNone(code_row)
        self.assertEqual(code_row["reason"], "bad_source")
        conn.close()

        # Restore the work for other tests
        resp = client.post(f"/api/works/{work_id}/restore")
        self.assertEqual(resp.status_code, 200)

        # Reset extraction review_status for isolation
        conn = _test_get_conn()
        conn.execute(
            "UPDATE metadata_extractions SET review_status = 'pending', fix_action = '', review_source = 'human' WHERE id = ?",
            (ext_id,),
        )
        conn.commit()
        conn.close()

    def test_quarantine_marks_all_pending_for_work(self):
        """All pending extractions for the same work should be marked rejected."""
        import json as _json

        conn = _test_get_conn()
        # Find a work with at least one pending extraction
        row = conn.execute(
            "SELECT me.work_id FROM metadata_extractions me "
            "JOIN works w ON w.id = me.work_id "
            "WHERE me.review_status = 'pending' AND w.read_status != 'quarantined' LIMIT 1"
        ).fetchone()
        if not row:
            conn.close()
            self.skipTest("No pending extraction for non-quarantined work")
            return
        work_id = row["work_id"]

        # Create a second pending extraction for this work
        extra_id = "ME-test-quarantine-extra"
        conn.execute("DELETE FROM metadata_extractions WHERE id = ?", (extra_id,))
        conn.execute(
            "INSERT INTO metadata_extractions "
            "(id, work_id, model_name, content_md_path, input_chars, input_tokens_est, "
            "raw_response, extracted_json, confidence_json, applied, created_at, "
            "review_status, risk_level, risk_score, risk_reasons, review_source, fix_action, superseded_by) "
            "VALUES (?, ?, 'test', '', 0, 0, '{}', '{}', '{}', 0, datetime('now'), "
            "'pending', 'low', 0, '[]', 'human', '', '')",
            (extra_id, work_id),
        )
        conn.commit()

        # Find the first pending extraction to quarantine from
        ext_row = conn.execute(
            "SELECT id FROM metadata_extractions WHERE work_id = ? AND review_status = 'pending' AND id != ? LIMIT 1",
            (work_id, extra_id),
        ).fetchone()
        if not ext_row:
            conn.close()
            self.skipTest("No pending extraction found")
            return
        ext_id = ext_row["id"]
        conn.close()

        # Quarantine
        resp = client.post(f"/api/metadata/{ext_id}/quarantine", json={"reason": "out_of_scope"})
        self.assertEqual(resp.status_code, 200)

        # Verify both extractions are rejected
        conn = _test_get_conn()
        rows = conn.execute(
            "SELECT id, review_status, fix_action FROM metadata_extractions WHERE work_id = ? AND fix_action = 'quarantined'",
            (work_id,),
        ).fetchall()
        ids = {r["id"] for r in rows}
        self.assertIn(ext_id, ids)
        self.assertIn(extra_id, ids)
        for r in rows:
            self.assertEqual(r["review_status"], "rejected")
        conn.close()

        # Restore
        client.post(f"/api/works/{work_id}/restore")
        conn = _test_get_conn()
        conn.execute(
            "UPDATE metadata_extractions SET review_status = 'pending', fix_action = '' WHERE work_id = ? AND id IN (?, ?)",
            (work_id, ext_id, extra_id),
        )
        conn.execute("DELETE FROM metadata_extractions WHERE id = ?", (extra_id,))
        conn.execute("DELETE FROM work_codes WHERE work_id = ? AND code = 'quarantined'", (work_id,))
        conn.commit()
        conn.close()

    def test_quarantine_excludes_from_default_list(self):
        """Quarantined works should not appear in default metadata list."""
        conn = _test_get_conn()
        row = conn.execute(
            "SELECT me.id AS ext_id, me.work_id FROM metadata_extractions me "
            "JOIN works w ON w.id = me.work_id "
            "WHERE w.read_status != 'quarantined' LIMIT 1"
        ).fetchone()
        if not row:
            conn.close()
            self.skipTest("No non-quarantined extraction")
            return
        ext_id = row["ext_id"]
        work_id = row["work_id"]
        conn.close()

        # Quarantine
        resp = client.post(f"/api/metadata/{ext_id}/quarantine", json={"reason": "not_literature"})
        self.assertEqual(resp.status_code, 200)

        # Default list should not include this work's extractions.
        # Use &search={work_id} to scope to this work — otherwise the work may
        # fall off page 1 (LIMIT 20) for reasons unrelated to quarantine.
        resp = client.get(f"/api/metadata?status=all&search={work_id}")
        data = resp.json()
        work_ids_in_list = [e["work_id"] for e in data["extractions"]]
        self.assertNotIn(work_id, work_ids_in_list)

        # include_quarantined=true should include it
        resp = client.get(f"/api/metadata?status=all&include_quarantined=true&search={work_id}")
        data = resp.json()
        work_ids_in_list = [e["work_id"] for e in data["extractions"]]
        self.assertIn(work_id, work_ids_in_list)

        # Restore
        client.post(f"/api/works/{work_id}/restore")
        conn = _test_get_conn()
        conn.execute(
            "UPDATE metadata_extractions SET review_status = 'pending', fix_action = '' WHERE id = ?",
            (ext_id,),
        )
        conn.execute("DELETE FROM work_codes WHERE work_id = ? AND code = 'quarantined'", (work_id,))
        conn.commit()
        conn.close()

    def test_quarantine_excludes_from_agent_queue(self):
        """Quarantined works should not appear in agent queue."""
        conn = _test_get_conn()
        row = conn.execute(
            "SELECT me.id AS ext_id, me.work_id FROM metadata_extractions me "
            "JOIN works w ON w.id = me.work_id "
            "WHERE w.read_status != 'quarantined' AND me.review_status = 'pending' LIMIT 1"
        ).fetchone()
        if not row:
            conn.close()
            self.skipTest("No non-quarantined pending extraction")
            return
        ext_id = row["ext_id"]
        work_id = row["work_id"]
        conn.close()

        # Quarantine
        resp = client.post(f"/api/metadata/{ext_id}/quarantine", json={"reason": "duplicate_residual"})
        self.assertEqual(resp.status_code, 200)

        # Agent queue should not include quarantined works
        resp = client.get("/api/metadata/agent/queue?status=rejected")
        data = resp.json()
        queue_work_ids = [item["work_id"] for item in data["items"]]
        self.assertNotIn(work_id, queue_work_ids)

        # Restore
        client.post(f"/api/works/{work_id}/restore")
        conn = _test_get_conn()
        conn.execute(
            "UPDATE metadata_extractions SET review_status = 'pending', fix_action = '' WHERE id = ?",
            (ext_id,),
        )
        conn.execute("DELETE FROM work_codes WHERE work_id = ? AND code = 'quarantined'", (work_id,))
        conn.commit()
        conn.close()

    def test_apply_approved_skips_quarantined(self):
        """apply-approved should skip extractions for quarantined works."""
        import json as _json

        conn = _test_get_conn()
        # Find a non-quarantined work
        row = conn.execute(
            "SELECT id FROM works WHERE read_status != 'quarantined' LIMIT 1"
        ).fetchone()
        if not row:
            conn.close()
            self.skipTest("No non-quarantined works")
            return
        work_id = row["id"]

        # Create an approved extraction for this work
        ext_id = "ME-test-apply-skip-q"
        conn.execute("DELETE FROM metadata_extractions WHERE id = ?", (ext_id,))
        conn.execute(
            "INSERT INTO metadata_extractions "
            "(id, work_id, model_name, content_md_path, input_chars, input_tokens_est, "
            "raw_response, extracted_json, confidence_json, applied, created_at, "
            "review_status, risk_level, risk_score, risk_reasons, review_source, fix_action, superseded_by) "
            "VALUES (?, ?, 'test', '', 0, 0, '{}', ?, ?, 0, datetime('now'), "
            "'approved', 'low', 0, '[]', 'human', '', '')",
            (
                ext_id, work_id,
                _json.dumps({"venue": "Quarantine Skip Test Venue"}, ensure_ascii=False),
                _json.dumps({"venue": "high"}, ensure_ascii=False),
            ),
        )
        conn.commit()
        conn.close()

        # Quarantine the work
        conn = _test_get_conn()
        conn.execute("UPDATE works SET read_status = 'quarantined' WHERE id = ?", (work_id,))
        conn.commit()
        conn.close()

        # Apply approved should skip this
        resp = client.post("/api/metadata/apply-approved")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        # The extraction should still not be applied
        conn = _test_get_conn()
        ext_row = conn.execute("SELECT applied FROM metadata_extractions WHERE id = ?", (ext_id,)).fetchone()
        self.assertEqual(ext_row["applied"], 0)

        # Restore and cleanup
        conn.execute("UPDATE works SET read_status = 'unread' WHERE id = ?", (work_id,))
        conn.execute("DELETE FROM metadata_extractions WHERE id = ?", (ext_id,))
        conn.commit()
        conn.close()

    def test_restore_does_not_auto_reopen_extractions(self):
        """After restore, rejected/quarantined extractions should stay rejected."""
        conn = _test_get_conn()
        row = conn.execute(
            "SELECT me.id AS ext_id, me.work_id FROM metadata_extractions me "
            "JOIN works w ON w.id = me.work_id "
            "WHERE w.read_status != 'quarantined' AND me.review_status = 'pending' LIMIT 1"
        ).fetchone()
        if not row:
            conn.close()
            self.skipTest("No non-quarantined pending extraction")
            return
        ext_id = row["ext_id"]
        work_id = row["work_id"]
        conn.close()

        # Quarantine
        resp = client.post(f"/api/metadata/{ext_id}/quarantine", json={"reason": "user_removed"})
        self.assertEqual(resp.status_code, 200)

        # Verify rejected
        conn = _test_get_conn()
        ext_row = conn.execute("SELECT review_status FROM metadata_extractions WHERE id = ?", (ext_id,)).fetchone()
        self.assertEqual(ext_row["review_status"], "rejected")
        conn.close()

        # Restore
        resp = client.post(f"/api/works/{work_id}/restore")
        self.assertEqual(resp.status_code, 200)

        # Extraction should still be rejected (not auto-reopened to pending)
        conn = _test_get_conn()
        ext_row = conn.execute("SELECT review_status FROM metadata_extractions WHERE id = ?", (ext_id,)).fetchone()
        self.assertEqual(ext_row["review_status"], "rejected")
        conn.close()

        # Cleanup
        conn = _test_get_conn()
        conn.execute(
            "UPDATE metadata_extractions SET review_status = 'pending', fix_action = '' WHERE id = ?",
            (ext_id,),
        )
        conn.execute("DELETE FROM work_codes WHERE work_id = ? AND code = 'quarantined'", (work_id,))
        conn.commit()
        conn.close()


class TestQuarantineEdgeCases(unittest.TestCase):
    """Tests for P1 review findings: quarantine boundary protection."""

    def test_quarantine_blocks_approved_unapplied_extractions(self):
        """Quarantine should also reject approved extractions that haven't been applied."""
        import json as _json

        conn = _test_get_conn()
        row = conn.execute(
            "SELECT id FROM works WHERE read_status != 'quarantined' LIMIT 1"
        ).fetchone()
        if not row:
            conn.close()
            self.skipTest("No non-quarantined works")
            return
        work_id = row["id"]

        # Create an approved-but-unapplied extraction
        ext_approved = "ME-test-q-blocks-approved"
        conn.execute("DELETE FROM metadata_extractions WHERE id = ?", (ext_approved,))
        conn.execute(
            "INSERT INTO metadata_extractions "
            "(id, work_id, model_name, content_md_path, input_chars, input_tokens_est, "
            "raw_response, extracted_json, confidence_json, applied, created_at, "
            "review_status, risk_level, risk_score, risk_reasons, review_source, fix_action, superseded_by) "
            "VALUES (?, ?, 'test', '', 0, 0, '{}', '{}', '{}', 0, datetime('now'), "
            "'approved', 'low', 0, '[]', 'human', '', '')",
            (ext_approved, work_id),
        )
        conn.commit()
        conn.close()

        # Create a pending extraction to quarantine from
        conn = _test_get_conn()
        ext_pending = "ME-test-q-blocks-pending"
        conn.execute("DELETE FROM metadata_extractions WHERE id = ?", (ext_pending,))
        conn.execute(
            "INSERT INTO metadata_extractions "
            "(id, work_id, model_name, content_md_path, input_chars, input_tokens_est, "
            "raw_response, extracted_json, confidence_json, applied, created_at, "
            "review_status, risk_level, risk_score, risk_reasons, review_source, fix_action, superseded_by) "
            "VALUES (?, ?, 'test', '', 0, 0, '{}', '{}', '{}', 0, datetime('now'), "
            "'pending', 'low', 0, '[]', 'human', '', '')",
            (ext_pending, work_id),
        )
        conn.commit()
        conn.close()

        # Quarantine via the pending extraction
        resp = client.post(f"/api/metadata/{ext_pending}/quarantine", json={"reason": "bad_source"})
        self.assertEqual(resp.status_code, 200)

        # Verify the approved extraction was also rejected
        conn = _test_get_conn()
        ext_row = conn.execute(
            "SELECT review_status, fix_action FROM metadata_extractions WHERE id = ?",
            (ext_approved,),
        ).fetchone()
        self.assertEqual(ext_row["review_status"], "rejected")
        self.assertEqual(ext_row["fix_action"], "quarantined")

        # Cleanup
        conn.execute("DELETE FROM metadata_extractions WHERE id IN (?, ?)", (ext_approved, ext_pending))
        conn.execute("DELETE FROM work_codes WHERE work_id = ? AND code = 'quarantined'", (work_id,))
        conn.execute("UPDATE works SET read_status = 'unread' WHERE id = ?", (work_id,))
        conn.commit()
        conn.close()

    def test_review_approve_skips_quarantined_work(self):
        """Approving an extraction for a quarantined work should not apply to works."""
        import json as _json

        conn = _test_get_conn()
        row = conn.execute(
            "SELECT id FROM works WHERE read_status != 'quarantined' LIMIT 1"
        ).fetchone()
        if not row:
            conn.close()
            self.skipTest("No non-quarantined works")
            return
        work_id = row["id"]

        # Create extraction with high-confidence venue for empty-venue work
        ext_id = "ME-test-approve-skip-q"
        conn.execute("DELETE FROM metadata_extractions WHERE id = ?", (ext_id,))
        conn.execute(
            "INSERT INTO metadata_extractions "
            "(id, work_id, model_name, content_md_path, input_chars, input_tokens_est, "
            "raw_response, extracted_json, confidence_json, applied, created_at, "
            "review_status, risk_level, risk_score, risk_reasons, review_source, fix_action, superseded_by) "
            "VALUES (?, ?, 'test', '', 0, 0, '{}', ?, ?, 0, datetime('now'), "
            "'pending', 'low', 0, '[]', 'human', '', '')",
            (
                ext_id, work_id,
                _json.dumps({"venue": "Quarantine Block Test"}, ensure_ascii=False),
                _json.dumps({"venue": "high"}, ensure_ascii=False),
            ),
        )
        conn.commit()

        # Quarantine the work
        conn.execute("UPDATE works SET read_status = 'quarantined' WHERE id = ?", (work_id,))
        conn.commit()
        conn.close()

        # Try to approve the extraction
        resp = client.patch(f"/api/metadata/{ext_id}/review", json={
            "review_status": "approved",
            "review_note": "should not apply",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("applied"), 0, "Should NOT apply to quarantined work")

        # Verify work venue was NOT updated
        resp = client.get(f"/api/works/{work_id}")
        self.assertNotEqual(resp.json().get("venue"), "Quarantine Block Test")

        # Cleanup
        conn = _test_get_conn()
        conn.execute("DELETE FROM metadata_extractions WHERE id = ?", (ext_id,))
        conn.execute("UPDATE works SET read_status = 'unread' WHERE id = ?", (work_id,))
        conn.commit()
        conn.close()

    def test_works_list_excludes_quarantined_by_default(self):
        """Default works list should not include quarantined works."""
        conn = _test_get_conn()
        # Find a quarantined work (or create one temporarily)
        row = conn.execute(
            "SELECT id FROM works WHERE read_status != 'quarantined' LIMIT 1"
        ).fetchone()
        if not row:
            conn.close()
            self.skipTest("No works")
            return
        work_id = row["id"]
        conn.execute("UPDATE works SET read_status = 'quarantined' WHERE id = ?", (work_id,))
        conn.commit()
        conn.close()

        # Default list should NOT include this work
        resp = client.get("/api/works")
        work_ids = [w["id"] for w in resp.json()["works"]]
        self.assertNotIn(work_id, work_ids)

        # include_quarantined=true should include it (use large per_page to cover all)
        resp = client.get("/api/works?include_quarantined=true&per_page=200")
        work_ids = [w["id"] for w in resp.json()["works"]]
        self.assertIn(work_id, work_ids)

        # status=quarantined should also work
        resp = client.get("/api/works?status=quarantined")
        work_ids = [w["id"] for w in resp.json()["works"]]
        self.assertIn(work_id, work_ids)

        # Restore
        conn = _test_get_conn()
        conn.execute("UPDATE works SET read_status = 'unread' WHERE id = ?", (work_id,))
        conn.commit()
        conn.close()

    def test_restore_cleans_quarantined_code(self):
        """Restore should remove both bad_source and quarantined codes."""
        conn = _test_get_conn()
        row = conn.execute(
            "SELECT id FROM works WHERE read_status != 'quarantined' LIMIT 1"
        ).fetchone()
        if not row:
            conn.close()
            self.skipTest("No works")
            return
        work_id = row["id"]

        # Set up quarantined state with 'quarantined' code
        conn.execute("UPDATE works SET read_status = 'quarantined' WHERE id = ?", (work_id,))
        conn.execute(
            "INSERT INTO work_codes (work_id, source_file_id, code, reason) VALUES (?, '', 'quarantined', 'test')",
            (work_id,),
        )
        conn.commit()
        conn.close()

        # Restore
        resp = client.post(f"/api/works/{work_id}/restore")
        self.assertEqual(resp.status_code, 200)

        # Verify quarantined code was removed
        conn = _test_get_conn()
        code_row = conn.execute(
            "SELECT * FROM work_codes WHERE work_id = ? AND code = 'quarantined'",
            (work_id,),
        ).fetchone()
        conn.close()
        self.assertIsNone(code_row, "quarantined code should be removed after restore")

    def test_quarantine_preserves_existing_review_note(self):
        """Quarantining a work should not overwrite review_note on other extractions."""
        import json as _json

        conn = _test_get_conn()
        row = conn.execute(
            "SELECT id FROM works WHERE read_status != 'quarantined' LIMIT 1"
        ).fetchone()
        if not row:
            conn.close()
            self.skipTest("No works")
            return
        work_id = row["id"]

        # Create a pending extraction with an existing review_note
        ext_pending = "ME-test-note-preserve-pending"
        conn.execute("DELETE FROM metadata_extractions WHERE id = ?", (ext_pending,))
        conn.execute(
            "INSERT INTO metadata_extractions "
            "(id, work_id, model_name, content_md_path, input_chars, input_tokens_est, "
            "raw_response, extracted_json, confidence_json, applied, created_at, "
            "review_status, risk_level, risk_score, risk_reasons, review_source, fix_action, "
            "superseded_by, review_note) "
            "VALUES (?, ?, 'test', '', 0, 0, '{}', '{}', '{}', 0, datetime('now'), "
            "'pending', 'low', 0, '[]', '', '', '', ?)",
            (ext_pending, work_id, "original pending note"),
        )

        # Create the extraction that will be quarantined
        ext_main = "ME-test-note-preserve-main"
        conn.execute("DELETE FROM metadata_extractions WHERE id = ?", (ext_main,))
        conn.execute(
            "INSERT INTO metadata_extractions "
            "(id, work_id, model_name, content_md_path, input_chars, input_tokens_est, "
            "raw_response, extracted_json, confidence_json, applied, created_at, "
            "review_status, risk_level, risk_score, risk_reasons, review_source, fix_action, "
            "superseded_by, review_note) "
            "VALUES (?, ?, 'test', '', 0, 0, '{}', '{}', '{}', 0, datetime('now'), "
            "'pending', 'low', 0, '[]', '', '', '', '')",
            (ext_main, work_id),
        )
        conn.commit()
        conn.close()

        # Quarantine via the main extraction
        resp = client.post(f"/api/metadata/{ext_main}/quarantine", json={
            "reason": "bad_source",
        })
        self.assertEqual(resp.status_code, 200)

        # The pending extraction should retain its original review_note
        conn = _test_get_conn()
        pending_row = conn.execute(
            "SELECT review_note FROM metadata_extractions WHERE id = ?",
            (ext_pending,),
        ).fetchone()
        self.assertEqual(pending_row["review_note"], "original pending note")

        # The main extraction should have the quarantine reason
        main_row = conn.execute(
            "SELECT review_note FROM metadata_extractions WHERE id = ?",
            (ext_main,),
        ).fetchone()
        self.assertEqual(main_row["review_note"], "bad_source")

        # Cleanup
        conn.execute("UPDATE works SET read_status = 'unread' WHERE id = ?", (work_id,))
        conn.execute("DELETE FROM metadata_extractions WHERE id IN (?, ?)", (ext_pending, ext_main))
        conn.execute("DELETE FROM work_codes WHERE work_id = ? AND code = 'quarantined'", (work_id,))
        conn.commit()
        conn.close()


class TestClassificationFields(unittest.TestCase):
    """Tests for Phase 1 classification fields: filters, get_work, update_work."""

    def test_list_works_filter_primary_doc_type(self):
        resp = client.get("/api/works?primary_doc_type=system_model_card&per_page=5")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for w in data["works"]:
            self.assertEqual(w["primary_doc_type"], "system_model_card")

    def test_list_works_filter_ingestion_state(self):
        resp = client.get("/api/works?ingestion_state=verified&per_page=5")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for w in data["works"]:
            self.assertEqual(w["ingestion_state"], "verified")

    def test_list_works_filter_publication_status(self):
        resp = client.get("/api/works?publication_status=preprint&per_page=5")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for w in data["works"]:
            self.assertEqual(w["publication_status"], "preprint")

    def test_list_works_filter_priority(self):
        resp = client.get("/api/works?priority=P1&per_page=5")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for w in data["works"]:
            self.assertEqual(w["priority"], "P1")

    def test_list_works_combined_filters(self):
        resp = client.get("/api/works?primary_doc_type=system_model_card&ingestion_state=verified&per_page=5")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for w in data["works"]:
            self.assertEqual(w["primary_doc_type"], "system_model_card")
            self.assertEqual(w["ingestion_state"], "verified")

    def test_get_work_has_classification_fields(self):
        resp = client.get("/api/works?primary_doc_type=system_model_card&per_page=1")
        data = resp.json()
        if not data["works"]:
            self.skipTest("No system_model_card works")
            return
        wid = data["works"][0]["id"]
        resp = client.get(f"/api/works/{wid}")
        self.assertEqual(resp.status_code, 200)
        work = resp.json()
        self.assertIn("primary_doc_type", work)
        self.assertIn("publication_status", work)
        self.assertIn("ingestion_state", work)
        self.assertIn("priority", work)
        self.assertIn("classification_tags", work)
        self.assertIsInstance(work["classification_tags"], dict)

    def test_update_work_classification_fields(self):
        resp = client.get("/api/works?primary_doc_type=system_model_card&per_page=1")
        data = resp.json()
        if not data["works"]:
            self.skipTest("No system_model_card works")
            return
        wid = data["works"][0]["id"]
        resp = client.patch(f"/api/works/{wid}", json={
            "priority": "P1",
            "region": "US",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))
        resp = client.get(f"/api/works/{wid}")
        self.assertEqual(resp.json()["priority"], "P1")
        self.assertEqual(resp.json()["region"], "US")
        # Restore
        client.patch(f"/api/works/{wid}", json={"priority": None, "region": None})

    def test_update_work_is_core_literature_bool(self):
        resp = client.get("/api/works?primary_doc_type=system_model_card&per_page=1")
        data = resp.json()
        if not data["works"]:
            self.skipTest("No system_model_card works")
            return
        wid = data["works"][0]["id"]
        resp = client.patch(f"/api/works/{wid}", json={"is_core_literature": True})
        self.assertEqual(resp.status_code, 200)
        resp = client.get(f"/api/works/{wid}")
        self.assertEqual(resp.json()["is_core_literature"], 1)
        # Restore
        client.patch(f"/api/works/{wid}", json={"is_core_literature": None})

    def test_old_doc_type_filter_still_works(self):
        resp = client.get("/api/works?doc_type=system_card&per_page=5")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for w in data["works"]:
            self.assertEqual(w["doc_type"], "system_card")

    def test_backfill_script_dry_run(self):
        from scripts.migrate_backfill_doc_type import run_backfill
        stats = run_backfill(dry_run=True)
        self.assertIn("total", stats)
        self.assertIn("auto_mapped", stats)
        self.assertIn("needs_review", stats)
        self.assertGreater(stats["total"], 0)

    def test_migration_idempotent(self):
        from scripts.migrate_add_classification_columns import run_migration
        # Run again - should not error
        run_migration(dry_run=False)
        # Verify columns still exist
        conn = _test_get_conn()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(works)").fetchall()}
        conn.close()
        self.assertIn("primary_doc_type", cols)
        self.assertIn("publication_status", cols)
        self.assertIn("ingestion_state", cols)
        self.assertIn("priority", cols)


class TestClassificationRoutes(unittest.TestCase):
    """Tests for classification tags CRUD and vocab endpoints."""

    def _get_work_id(self):
        resp = client.get("/api/works?per_page=1")
        return resp.json()["works"][0]["id"]

    def test_get_tags_empty(self):
        wid = self._get_work_id()
        resp = client.get(f"/api/classification/tags/{wid}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("tags", data)
        self.assertIsInstance(data["tags"], list)

    def test_create_tag(self):
        wid = self._get_work_id()
        resp = client.post(f"/api/classification/tags/{wid}", json={
            "tag_group": "reading_lane",
            "tag_value": "evaluation_method",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))
        tag_id = resp.json()["tag_id"]
        self.assertTrue(tag_id.startswith("CT-"))

        # Verify tag appears in list
        resp = client.get(f"/api/classification/tags/{wid}")
        tag_groups = [t["tag_group"] for t in resp.json()["tags"]]
        self.assertIn("reading_lane", tag_groups)

        # Cleanup
        client.delete(f"/api/classification/tags/{tag_id}")

    def test_create_tag_invalid_value(self):
        wid = self._get_work_id()
        resp = client.post(f"/api/classification/tags/{wid}", json={
            "tag_group": "reading_lane",
            "tag_value": "invalid_nonexistent_tag",
        })
        self.assertEqual(resp.status_code, 400)

    def test_create_tag_invalid_work(self):
        resp = client.post("/api/classification/tags/W-nonexistent-999", json={
            "tag_group": "reading_lane",
            "tag_value": "evaluation_method",
        })
        self.assertEqual(resp.status_code, 404)

    def test_delete_tag(self):
        wid = self._get_work_id()
        # Create
        resp = client.post(f"/api/classification/tags/{wid}", json={
            "tag_group": "artifact_focus",
            "tag_value": "benchmark",
        })
        tag_id = resp.json()["tag_id"]
        # Delete
        resp = client.delete(f"/api/classification/tags/{tag_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))
        # Verify gone
        resp = client.get(f"/api/classification/tags/{wid}")
        tag_ids = [t["id"] for t in resp.json()["tags"]]
        self.assertNotIn(tag_id, tag_ids)

    def test_delete_tag_not_found(self):
        resp = client.delete("/api/classification/tags/CT-nonexistent")
        self.assertEqual(resp.status_code, 404)

    def test_batch_create_tags(self):
        wid = self._get_work_id()
        resp = client.post(f"/api/classification/tags/{wid}/batch", json={
            "tags": [
                {"tag_group": "reading_lane", "tag_value": "evaluation_method"},
                {"tag_group": "artifact_focus", "tag_value": "benchmark"},
            ]
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["created"], 2)
        # Cleanup
        for tid in resp.json()["tag_ids"]:
            client.delete(f"/api/classification/tags/{tid}")

    def test_vocab_endpoint(self):
        resp = client.get("/api/classification/vocab")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("primary_doc_type", data)
        self.assertIn("reading_lane", data)
        self.assertIn("artifact_focus", data)
        self.assertIsInstance(data["primary_doc_type"], list)
        self.assertGreater(len(data["primary_doc_type"]), 0)

    def test_tag_filter_in_list_works(self):
        wid = self._get_work_id()
        # Create a tag
        resp = client.post(f"/api/classification/tags/{wid}", json={
            "tag_group": "reading_lane",
            "tag_value": "evaluation_method",
        })
        tag_id = resp.json()["tag_id"]
        # Filter by reading_lane
        resp = client.get("/api/works?reading_lane=evaluation_method&per_page=50")
        self.assertEqual(resp.status_code, 200)
        work_ids = [w["id"] for w in resp.json()["works"]]
        self.assertIn(wid, work_ids)
        # Cleanup
        client.delete(f"/api/classification/tags/{tag_id}")

    def test_relation_category(self):
        resp = client.get("/api/works?per_page=10")
        works = resp.json()["works"]
        self.assertGreaterEqual(len(works), 2)
        wid_a = works[0]["id"]
        wid_b = works[1]["id"]
        # Create relation with category
        resp = client.post("/api/relations", json={
            "work_id_a": wid_a,
            "work_id_b": wid_b,
            "relation_type": "companion",
            "relation_category": "document_structure",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))
        # Verify category in list
        resp = client.get("/api/relations")
        for r in resp.json()["relations"]:
            if r["work_id_a"] == wid_a and r["work_id_b"] == wid_b and r["relation_type"] == "companion":
                self.assertEqual(r["relation_category"], "document_structure")
                break
        # Cleanup
        client.request("DELETE", "/api/relations", content=__import__("json").dumps({
            "work_id_a": wid_a, "work_id_b": wid_b, "relation_type": "companion",
        }), headers={"Content-Type": "application/json"})

    def test_relation_category_default_content(self):
        resp = client.get("/api/works?per_page=10")
        works = resp.json()["works"]
        wid_a = works[0]["id"]
        wid_b = works[1]["id"]
        # Create relation without category (should default to content)
        resp = client.post("/api/relations", json={
            "work_id_a": wid_a,
            "work_id_b": wid_b,
            "relation_type": "not_duplicate",
        })
        self.assertEqual(resp.status_code, 200)
        # Verify default category
        resp = client.get("/api/relations")
        for r in resp.json()["relations"]:
            if r["work_id_a"] == wid_a and r["work_id_b"] == wid_b and r["relation_type"] == "not_duplicate":
                self.assertEqual(r.get("relation_category", "content"), "content")
                break
        # Cleanup
        client.request("DELETE", "/api/relations", content=__import__("json").dumps({
            "work_id_a": wid_a, "work_id_b": wid_b, "relation_type": "not_duplicate",
        }), headers={"Content-Type": "application/json"})


class TestClassificationExtractions(unittest.TestCase):
    """Tests for classification extraction CRUD and review routes."""

    def _create_classification_fixture(
        self,
        work_id: str,
        ext_id: str,
        *,
        read_status: str = "unread",
        review_status: str = "pending",
        ambiguity_score: int = 10,
    ):
        import json as _json

        conn = _test_get_conn()
        conn.execute("DELETE FROM classification_extractions WHERE id = ?", (ext_id,))
        conn.execute("DELETE FROM works WHERE id = ?", (work_id,))
        conn.execute(
            """
            INSERT INTO works
            (id, title, authors, doc_type, language, metadata_status, parse_status,
             read_status, created_at, updated_at)
            VALUES (?, ?, '[]', 'paper', 'en', 'pending', 'parsed', ?, datetime('now'), datetime('now'))
            """,
            (work_id, f"Test classification fixture {work_id}", read_status),
        )
        conn.execute(
            """
            INSERT INTO classification_extractions
            (id, work_id, model_name, prompt_version, extracted_json, confidence_json,
             ambiguity_score, ambiguity_reasons, review_status, applied, raw_response,
             created_at, updated_at)
            VALUES (?, ?, 'test-model', 'v1', ?, ?, ?, '[]', ?, 0, '{}',
                    datetime('now'), datetime('now'))
            """,
            (
                ext_id,
                work_id,
                _json.dumps({
                    "primary_doc_type": "evaluation_report",
                    "publication_status": "published",
                    "reading_lane": ["evaluation_method"],
                    "artifact_focus": ["audit_finding"],
                    "evidence": {"primary_doc_type": "evaluation evidence"},
                }, ensure_ascii=False),
                _json.dumps({"primary_doc_type": "high"}, ensure_ascii=False),
                ambiguity_score,
                review_status,
            ),
        )
        conn.commit()
        conn.close()

    def _delete_classification_fixture(self, work_id: str, ext_id: str):
        conn = _test_get_conn()
        conn.execute("DELETE FROM work_codes WHERE work_id = ?", (work_id,))
        conn.execute("DELETE FROM work_classification_tags WHERE work_id = ?", (work_id,))
        conn.execute("DELETE FROM classification_extractions WHERE id = ?", (ext_id,))
        conn.execute("DELETE FROM works WHERE id = ?", (work_id,))
        conn.commit()
        conn.close()

    def test_list_extractions(self):
        resp = client.get("/api/classification/extractions?status=all")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("extractions", data)
        self.assertIn("total", data)
        self.assertIn("summary", data)

    def test_list_extractions_pending(self):
        resp = client.get("/api/classification/extractions?status=pending")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data["extractions"], list)

    def test_get_extraction_not_found(self):
        resp = client.get("/api/classification/extractions/CE-nonexistent")
        self.assertEqual(resp.status_code, 404)

    def test_review_extraction_invalid_status(self):
        conn = _test_get_conn()
        row = conn.execute("SELECT id FROM classification_extractions LIMIT 1").fetchone()
        conn.close()
        if not row:
            self.skipTest("No classification extractions")
            return
        resp = client.patch(f"/api/classification/extractions/{row['id']}/review", json={
            "review_status": "invalid_status",
        })
        self.assertEqual(resp.status_code, 400)

    def test_review_extraction_not_found(self):
        resp = client.patch("/api/classification/extractions/CE-nonexistent/review", json={
            "review_status": "approved",
        })
        self.assertEqual(resp.status_code, 404)

    def test_review_extraction_approved_writes_tags(self):
        """Approving an extraction should write tags to work_classification_tags."""
        import json as _json

        conn = _test_get_conn()
        row = conn.execute(
            "SELECT id, work_id, extracted_json FROM classification_extractions "
            "WHERE review_status = 'pending' AND id = 'CE-test-approve-only'"
        ).fetchone()
        if not row:
            conn.close()
            self.skipTest("No pending classification extractions")
            return
        ext_id = row["id"]
        work_id = row["work_id"]
        extracted = _json.loads(row["extracted_json"])

        # Clean any pre-existing model tags for this work to get a clean baseline
        conn.execute(
            "DELETE FROM work_classification_tags WHERE work_id = ? AND source = 'model'",
            (work_id,),
        )
        conn.commit()
        conn.close()

        # Count tags before approve (should be 0 after cleanup)
        conn = _test_get_conn()
        tags_before = conn.execute(
            "SELECT COUNT(*) as cnt FROM work_classification_tags WHERE work_id = ? AND source = 'model'",
            (work_id,),
        ).fetchone()["cnt"]
        conn.close()
        self.assertEqual(tags_before, 0)

        # Review as approved
        resp = client.patch(f"/api/classification/extractions/{ext_id}/review", json={
            "review_status": "approved",
            "review_note": "test approve",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))

        # Verify extraction is now approved and applied
        conn = _test_get_conn()
        ext_row = conn.execute(
            "SELECT review_status, applied FROM classification_extractions WHERE id = ?", (ext_id,)
        ).fetchone()
        self.assertEqual(ext_row["review_status"], "approved")
        self.assertEqual(ext_row["applied"], 1)

        # Verify tags were written to work_classification_tags
        tags_after = conn.execute(
            "SELECT COUNT(*) as cnt FROM work_classification_tags WHERE work_id = ? AND source = 'model'",
            (work_id,),
        ).fetchone()["cnt"]
        self.assertGreater(tags_after, 0, "Tags should have been written on approve")

        # Verify specific tag values from extracted_json
        expected_tags = set()
        for group in ("reading_lane", "artifact_focus"):
            for v in (extracted.get(group) or []):
                expected_tags.add((group, v))
        if expected_tags:
            actual_tags = conn.execute(
                "SELECT tag_group, tag_value FROM work_classification_tags WHERE work_id = ? AND source = 'model'",
                (work_id,),
            ).fetchall()
            actual_set = {(r["tag_group"], r["tag_value"]) for r in actual_tags}
            for tag in expected_tags:
                self.assertIn(tag, actual_set, f"Expected tag {tag} not found in work_classification_tags")
        conn.close()

        # Reset for other tests
        conn = _test_get_conn()
        conn.execute(
            "UPDATE classification_extractions SET review_status = 'pending', applied = 0 WHERE id = ?",
            (ext_id,),
        )
        conn.execute(
            "DELETE FROM work_classification_tags WHERE work_id = ? AND source = 'model'",
            (work_id,),
        )
        conn.commit()
        conn.close()

    def test_review_extraction_rejected(self):
        conn = _test_get_conn()
        row = conn.execute(
            "SELECT id FROM classification_extractions WHERE review_status = 'pending' LIMIT 1"
        ).fetchone()
        if not row:
            conn.close()
            self.skipTest("No pending classification extractions")
            return
        ext_id = row["id"]
        conn.close()

        resp = client.patch(f"/api/classification/extractions/{ext_id}/review", json={
            "review_status": "rejected",
            "review_note": "test reject",
        })
        self.assertEqual(resp.status_code, 200)

        # Verify
        conn = _test_get_conn()
        ext_row = conn.execute(
            "SELECT review_status FROM classification_extractions WHERE id = ?", (ext_id,)
        ).fetchone()
        self.assertEqual(ext_row["review_status"], "rejected")
        conn.close()

        # Reset
        conn = _test_get_conn()
        conn.execute(
            "UPDATE classification_extractions SET review_status = 'pending' WHERE id = ?", (ext_id,)
        )
        conn.commit()
        conn.close()

    def test_batch_approve_low_ambiguity(self):
        resp = client.post("/api/classification/extractions/batch-approve-low-risk")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertIn("approved", data)

    def test_classification_list_excludes_quarantined_by_default(self):
        work_id = "W-test-cls-quarantine-list"
        ext_id = "CE-test-cls-quarantine-list"
        self._create_classification_fixture(work_id, ext_id, read_status="quarantined")
        try:
            resp = client.get("/api/classification/extractions?status=all&include_quarantined=false&search=W-test-cls-quarantine-list")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["total"], 0)

            resp = client.get("/api/classification/extractions?status=all&include_quarantined=true&search=W-test-cls-quarantine-list")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["total"], 1)
            self.assertEqual(resp.json()["extractions"][0]["work_read_status"], "quarantined")
        finally:
            self._delete_classification_fixture(work_id, ext_id)

    def test_classification_quarantine_marks_work_and_extraction(self):
        work_id = "W-test-cls-quarantine-action"
        ext_id = "CE-test-cls-quarantine-action"
        self._create_classification_fixture(work_id, ext_id)
        try:
            resp = client.post(f"/api/classification/extractions/{ext_id}/quarantine", json={
                "reason": "out_of_scope",
            })
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.json().get("ok"))

            conn = _test_get_conn()
            work = conn.execute("SELECT read_status FROM works WHERE id = ?", (work_id,)).fetchone()
            ext = conn.execute(
                "SELECT review_status, fix_action, review_note FROM classification_extractions WHERE id = ?",
                (ext_id,),
            ).fetchone()
            code = conn.execute(
                "SELECT reason FROM work_codes WHERE work_id = ? AND code = 'quarantined'",
                (work_id,),
            ).fetchone()
            conn.close()
            self.assertEqual(work["read_status"], "quarantined")
            self.assertEqual(ext["review_status"], "rejected")
            self.assertEqual(ext["fix_action"], "quarantined")
            self.assertEqual(ext["review_note"], "out_of_scope")
            self.assertIsNotNone(code)
        finally:
            self._delete_classification_fixture(work_id, ext_id)

    def test_classification_approve_skips_quarantined_work(self):
        work_id = "W-test-cls-quarantine-approve"
        ext_id = "CE-test-cls-quarantine-approve"
        self._create_classification_fixture(work_id, ext_id, read_status="quarantined")
        try:
            resp = client.patch(f"/api/classification/extractions/{ext_id}/review", json={
                "review_status": "approved",
                "review_note": "should not apply",
            })
            self.assertEqual(resp.status_code, 200)

            conn = _test_get_conn()
            work = conn.execute(
                "SELECT primary_doc_type FROM works WHERE id = ?", (work_id,)
            ).fetchone()
            ext = conn.execute(
                "SELECT review_status, applied FROM classification_extractions WHERE id = ?",
                (ext_id,),
            ).fetchone()
            tag_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM work_classification_tags WHERE work_id = ?",
                (work_id,),
            ).fetchone()["cnt"]
            conn.close()
            self.assertEqual(ext["review_status"], "approved")
            self.assertEqual(ext["applied"], 0)
            self.assertIsNone(work["primary_doc_type"])
            self.assertEqual(tag_count, 0)
        finally:
            self._delete_classification_fixture(work_id, ext_id)

    def test_ambiguity_scoring(self):
        """Test the ambiguity scoring module."""
        from api.classification_ambiguity import compute_ambiguity

        # High ambiguity: no primary_doc_type
        result = compute_ambiguity({}, {})
        self.assertGreaterEqual(result["score"], 50)
        self.assertTrue(len(result["reasons"]) > 0)

        # Low ambiguity: high confidence primary_doc_type with evidence
        result = compute_ambiguity(
            {
                "primary_doc_type": "evaluation_report",
                "publication_status": "published",
                "reading_lane": ["evaluation_method"],
                "artifact_focus": ["audit_finding"],
                "evidence": {"primary_doc_type": "third-party evaluation"},
            },
            {"primary_doc_type": "high", "publication_status": "high"},
        )
        self.assertLessEqual(result["score"], 20)

        # Medium ambiguity: medium confidence
        result = compute_ambiguity(
            {"primary_doc_type": "technical_report"},
            {"primary_doc_type": "medium"},
        )
        self.assertGreater(result["score"], 0)
        self.assertLess(result["score"], 50)

    def test_classification_vocab_endpoint(self):
        resp = client.get("/api/classification/vocab")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("primary_doc_type", data)
        self.assertIn("reading_lane", data)
        self.assertIn("risk_domain", data)

    def test_idempotent_approve(self):
        """Approving the same extraction twice should not create duplicate tags."""
        conn = _test_get_conn()
        row = conn.execute(
            "SELECT id, work_id FROM classification_extractions WHERE review_status = 'pending' LIMIT 1"
        ).fetchone()
        if not row:
            conn.close()
            self.skipTest("No pending classification extractions")
            return
        ext_id = row["id"]
        work_id = row["work_id"]
        conn.close()

        # First approve
        resp = client.patch(f"/api/classification/extractions/{ext_id}/review", json={
            "review_status": "approved",
            "review_note": "idempotent test",
        })
        self.assertEqual(resp.status_code, 200)

        # Count tags after first approve
        conn = _test_get_conn()
        count1 = conn.execute(
            "SELECT COUNT(*) as cnt FROM work_classification_tags WHERE work_id = ? AND source = 'model'",
            (work_id,),
        ).fetchone()["cnt"]

        # Second approve (should short-circuit)
        resp = client.patch(f"/api/classification/extractions/{ext_id}/review", json={
            "review_status": "approved",
            "review_note": "idempotent test 2",
        })
        self.assertEqual(resp.status_code, 200)

        # Count tags after second approve (should be same)
        count2 = conn.execute(
            "SELECT COUNT(*) as cnt FROM work_classification_tags WHERE work_id = ? AND source = 'model'",
            (work_id,),
        ).fetchone()["cnt"]
        conn.close()

        self.assertEqual(count1, count2)

        # Reset
        conn = _test_get_conn()
        conn.execute(
            "UPDATE classification_extractions SET review_status = 'pending', applied = 0 WHERE id = ?",
            (ext_id,),
        )
        conn.commit()
        conn.close()

    def test_list_extractions_search_and_pagination(self):
        """Test search and pagination on list_extractions."""
        resp = client.get("/api/classification/extractions?status=all&limit=2&offset=0")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertLessEqual(len(data["extractions"]), 2)

        # Search
        resp = client.get("/api/classification/extractions?status=all&search=nonexistent_xyz_123")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data["extractions"]), 0)

    def test_edit_promotes_confidence(self):
        """Editing a field via save-draft should promote its confidence to high."""
        import json as _json

        work_id = "W-test-edit-promote"
        ext_id = "CE-test-edit-promote"
        self._create_classification_fixture(work_id, ext_id)
        try:
            # Edit a field that was low confidence
            resp = client.patch(f"/api/classification/extractions/{ext_id}/save-draft", json={
                "edited_fields": {"publication_status": "preprint"},
            })
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.json().get("ok"))

            # Verify confidence was promoted
            conn = _test_get_conn()
            row = conn.execute(
                "SELECT confidence_json FROM classification_extractions WHERE id = ?",
                (ext_id,),
            ).fetchone()
            conn.close()
            confidence = _json.loads(row["confidence_json"])
            self.assertEqual(confidence["publication_status"], "high",
                             "Edited field confidence should be promoted to high")
        finally:
            self._delete_classification_fixture(work_id, ext_id)

    def test_save_draft_no_change_preserves_score(self):
        """Saving draft without actual value changes should not alter ambiguity score."""
        import json as _json

        work_id = "W-test-no-change"
        ext_id = "CE-test-no-change"
        self._create_classification_fixture(work_id, ext_id, ambiguity_score=10)
        try:
            # First save triggers recomputation (fixes hand-filled score)
            resp = client.patch(f"/api/classification/extractions/{ext_id}/save-draft", json={
                "edited_fields": {},
            })
            self.assertEqual(resp.status_code, 200)

            # Get the recomputed score
            conn = _test_get_conn()
            row = conn.execute(
                "SELECT ambiguity_score FROM classification_extractions WHERE id = ?",
                (ext_id,),
            ).fetchone()
            recomputed_score = row["ambiguity_score"]
            conn.close()

            # Save draft again with same values (simulating open-and-save without edits)
            resp = client.patch(f"/api/classification/extractions/{ext_id}/save-draft", json={
                "edited_fields": {
                    "primary_doc_type": "evaluation_report",
                    "publication_status": "published",
                },
            })
            self.assertEqual(resp.status_code, 200)

            # Score should be unchanged after second save
            conn = _test_get_conn()
            row = conn.execute(
                "SELECT ambiguity_score FROM classification_extractions WHERE id = ?",
                (ext_id,),
            ).fetchone()
            conn.close()
            self.assertEqual(row["ambiguity_score"], recomputed_score,
                             "Score should not change when no actual value changes")
        finally:
            self._delete_classification_fixture(work_id, ext_id)

    def test_dual_source_confidence_merge(self):
        """Ambiguity computation should merge embedded and column confidence."""
        import json as _json
        from api.classification_ambiguity import compute_ambiguity

        extracted = {
            "primary_doc_type": "evaluation_report",
            "publication_status": "published",
            "reading_lane": ["evaluation_method"],
            "artifact_focus": ["audit_finding"],
            "evidence": {"primary_doc_type": "evaluation"},
            "confidence": {"primary_doc_type": "high", "publication_status": "high"},
        }
        # Column confidence is sparse (only primary_doc_type)
        column_confidence = {"primary_doc_type": "high"}

        # Merge dual-source
        embedded_confidence = extracted.get("confidence", {})
        merged = {**embedded_confidence, **column_confidence}

        result = compute_ambiguity(extracted, merged)
        # Should be low ambiguity because embedded confidence covers publication_status
        self.assertLessEqual(result["score"], 15,
                             "Merged confidence should produce low ambiguity")

        # Without merge (old behavior), publication_status would be "low" default
        result_old = compute_ambiguity(extracted, column_confidence)
        self.assertGreater(result_old["score"], result["score"],
                           "Without merge, score should be higher due to missing confidence")

    def test_review_extraction_promotes_confidence(self):
        """Reviewing with edited fields should also promote confidence."""
        import json as _json

        work_id = "W-test-review-promote"
        ext_id = "CE-test-review-promote"
        self._create_classification_fixture(work_id, ext_id)
        try:
            resp = client.patch(f"/api/classification/extractions/{ext_id}/review", json={
                "review_status": "needs_fix",
                "review_note": "edited field",
                "edited_fields": {"publication_status": "preprint"},
            })
            self.assertEqual(resp.status_code, 200)

            # Verify confidence was promoted
            conn = _test_get_conn()
            row = conn.execute(
                "SELECT confidence_json FROM classification_extractions WHERE id = ?",
                (ext_id,),
            ).fetchone()
            conn.close()
            confidence = _json.loads(row["confidence_json"])
            self.assertEqual(confidence["publication_status"], "high")
        finally:
            self._delete_classification_fixture(work_id, ext_id)

    def test_approve_writes_tags_with_merged_confidence(self):
        """Approving should write tags using merged (embedded + column) confidence.

        Regression test: Mimo batch records have embedded confidence like
        {"risk_domain": "high"} but sparse column confidence_json. Tags must
        reflect the merged confidence, not just the column.
        """
        import json as _json

        work_id = "W-test-merged-conf-tag"
        ext_id = "CE-test-merged-conf-tag"
        conn = _test_get_conn()
        conn.execute("DELETE FROM classification_extractions WHERE id = ?", (ext_id,))
        conn.execute("DELETE FROM works WHERE id = ?", (work_id,))
        conn.execute(
            """
            INSERT INTO works
            (id, title, authors, doc_type, language, metadata_status, parse_status,
             read_status, created_at, updated_at)
            VALUES (?, 'Test merged confidence', '[]', 'paper', 'en', 'pending', 'parsed',
                    'unread', datetime('now'), datetime('now'))
            """,
            (work_id,),
        )
        # Simulate Mimo batch pattern: embedded confidence has risk_domain=high,
        # but column confidence_json is sparse (only primary_doc_type)
        conn.execute(
            """
            INSERT INTO classification_extractions
            (id, work_id, model_name, prompt_version, extracted_json, confidence_json,
             ambiguity_score, ambiguity_reasons, review_status, applied, raw_response,
             created_at, updated_at)
            VALUES (?, ?, 'mimo-test', 'v1', ?, ?, 5, '[]', 'pending', 0, '{}',
                    datetime('now'), datetime('now'))
            """,
            (
                ext_id,
                work_id,
                _json.dumps({
                    "primary_doc_type": "evaluation_report",
                    "publication_status": "published",
                    "reading_lane": ["evaluation_method"],
                    "artifact_focus": ["audit_finding"],
                    "risk_domain": ["fairness"],
                    "evidence": {"primary_doc_type": "test"},
                    "confidence": {
                        "primary_doc_type": "high",
                        "risk_domain": "high",
                        "reading_lane": "medium",
                    },
                }, ensure_ascii=False),
                _json.dumps({"primary_doc_type": "high"}, ensure_ascii=False),
            ),
        )
        conn.commit()
        conn.close()

        try:
            resp = client.patch(f"/api/classification/extractions/{ext_id}/review", json={
                "review_status": "approved",
                "review_note": "test merged confidence in tags",
            })
            self.assertEqual(resp.status_code, 200)

            # Verify tags have merged confidence, not just column confidence
            conn = _test_get_conn()
            tags = conn.execute(
                "SELECT tag_group, confidence FROM work_classification_tags "
                "WHERE work_id = ? AND source = 'model'",
                (work_id,),
            ).fetchall()
            conn.close()

            tag_conf = {t["tag_group"]: t["confidence"] for t in tags}
            # risk_domain should be "high" from embedded confidence, not "low"
            self.assertEqual(tag_conf.get("risk_domain"), "high",
                             "risk_domain tag should use embedded confidence (high), not column default (low)")
            # reading_lane should be "medium" from embedded confidence
            self.assertEqual(tag_conf.get("reading_lane"), "medium",
                             "reading_lane tag should use embedded confidence (medium)")
        finally:
            conn = _test_get_conn()
            conn.execute("DELETE FROM work_classification_tags WHERE work_id = ?", (work_id,))
            conn.execute("DELETE FROM classification_extractions WHERE id = ?", (ext_id,))
            conn.execute("DELETE FROM works WHERE id = ?", (work_id,))
            conn.commit()
            conn.close()

    def test_batch_approve_with_tag_writes_merged_confidence(self):
        """Batch approve with tag should write tags using merged confidence.

        Regression test: ensures batch-approve-with-tag endpoint merges embedded
        confidence before writing work_classification_tags, not just column confidence.
        """
        import json as _json

        work_id = "W-test-batch-tag-conf"
        ext_id = "CE-test-batch-tag-conf"
        conn = _test_get_conn()
        conn.execute("DELETE FROM classification_extractions WHERE id = ?", (ext_id,))
        conn.execute("DELETE FROM works WHERE id = ?", (work_id,))
        conn.execute(
            """
            INSERT INTO works
            (id, title, authors, doc_type, language, metadata_status, parse_status,
             read_status, created_at, updated_at)
            VALUES (?, 'Test batch tag confidence', '[]', 'paper', 'en', 'pending', 'parsed',
                    'unread', datetime('now'), datetime('now'))
            """,
            (work_id,),
        )
        # Embedded confidence: risk_domain=high, artifact_focus=medium
        # Column confidence: only primary_doc_type=high
        conn.execute(
            """
            INSERT INTO classification_extractions
            (id, work_id, model_name, prompt_version, extracted_json, confidence_json,
             ambiguity_score, ambiguity_reasons, review_status, applied, raw_response,
             created_at, updated_at)
            VALUES (?, ?, 'mimo-test', 'v1', ?, ?, 5, '[]', 'pending', 0, '{}',
                    datetime('now'), datetime('now'))
            """,
            (
                ext_id,
                work_id,
                _json.dumps({
                    "primary_doc_type": "evaluation_report",
                    "publication_status": "published",
                    "reading_lane": ["evaluation_method"],
                    "artifact_focus": ["audit_finding"],
                    "risk_domain": ["fairness"],
                    "evidence": {"primary_doc_type": "test"},
                    "confidence": {
                        "primary_doc_type": "high",
                        "risk_domain": "high",
                        "artifact_focus": "medium",
                    },
                }, ensure_ascii=False),
                _json.dumps({"primary_doc_type": "high"}, ensure_ascii=False),
            ),
        )
        conn.commit()
        conn.close()

        try:
            resp = client.post("/api/classification/extractions/batch-approve-with-tag", json={
                "threshold": 100,
                "tag": "test-batch-merged-conf",
            })
            self.assertEqual(resp.status_code, 200)
            self.assertGreaterEqual(resp.json()["approved"], 1, "Should approve at least our test extraction")

            # Verify our specific extraction was approved
            conn = _test_get_conn()
            ext_row = conn.execute(
                "SELECT review_status, review_note FROM classification_extractions WHERE id = ?",
                (ext_id,),
            ).fetchone()
            self.assertEqual(ext_row["review_status"], "approved")
            self.assertEqual(ext_row["review_note"], "test-batch-merged-conf")

            # Verify tags for our specific work have merged confidence
            tags = conn.execute(
                "SELECT tag_group, confidence FROM work_classification_tags "
                "WHERE work_id = ? AND source = 'model'",
                (work_id,),
            ).fetchall()
            conn.close()

            tag_conf = {t["tag_group"]: t["confidence"] for t in tags}
            self.assertEqual(tag_conf.get("risk_domain"), "high",
                             "Batch approve: risk_domain should use embedded confidence (high)")
            self.assertEqual(tag_conf.get("artifact_focus"), "medium",
                             "Batch approve: artifact_focus should use embedded confidence (medium)")
        finally:
            conn = _test_get_conn()
            conn.execute("DELETE FROM work_classification_tags WHERE work_id = ?", (work_id,))
            conn.execute("DELETE FROM classification_extractions WHERE id = ?", (ext_id,))
            conn.execute("DELETE FROM works WHERE id = ?", (work_id,))
            conn.commit()
            conn.close()

    def test_cli_apply_to_works_writes_merged_confidence(self):
        """CLI apply_to_works should write tags using merged confidence.

        Regression test: ensures scripts/literature_classification_extract.apply_to_works
        merges embedded + column confidence before writing work_classification_tags.
        """
        import json as _json
        from scripts.literature_classification_extract import apply_to_works

        work_id = "W-test-cli-apply-conf"
        ext_id = "CE-test-cli-apply-conf"
        conn = _test_get_conn()
        conn.execute("DELETE FROM classification_extractions WHERE id = ?", (ext_id,))
        conn.execute("DELETE FROM work_classification_tags WHERE work_id = ?", (work_id,))
        conn.execute("DELETE FROM works WHERE id = ?", (work_id,))
        conn.execute(
            """
            INSERT INTO works
            (id, title, authors, doc_type, language, metadata_status, parse_status,
             read_status, created_at, updated_at)
            VALUES (?, 'Test CLI apply confidence', '[]', 'paper', 'en', 'pending', 'parsed',
                    'unread', datetime('now'), datetime('now'))
            """,
            (work_id,),
        )
        # Embedded confidence: risk_domain=high, method_tags=medium
        # Column confidence: only primary_doc_type=high
        extracted_json = _json.dumps({
            "primary_doc_type": "evaluation_report",
            "publication_status": "published",
            "reading_lane": ["evaluation_method"],
            "artifact_focus": ["audit_finding"],
            "risk_domain": ["fairness"],
            "method_tags": ["standard_comparison"],
            "evidence": {"primary_doc_type": "test"},
            "confidence": {
                "primary_doc_type": "high",
                "risk_domain": "high",
                "method_tags": "medium",
            },
        }, ensure_ascii=False)
        confidence_json = _json.dumps({"primary_doc_type": "high"}, ensure_ascii=False)

        conn.execute(
            """
            INSERT INTO classification_extractions
            (id, work_id, model_name, prompt_version, extracted_json, confidence_json,
             ambiguity_score, ambiguity_reasons, review_status, applied, raw_response,
             created_at, updated_at)
            VALUES (?, ?, 'mimo-test', 'v1', ?, ?, 5, '[]', 'pending', 0, '{}',
                    datetime('now'), datetime('now'))
            """,
            (ext_id, work_id, extracted_json, confidence_json),
        )
        conn.commit()

        # Call apply_to_works
        ext_row = conn.execute(
            "SELECT * FROM classification_extractions WHERE id = ?", (ext_id,)
        ).fetchone()
        count = apply_to_works(conn, [dict(ext_row)], ambiguity_threshold=20)
        conn.commit()

        self.assertEqual(count, 1, "apply_to_works should apply 1 extraction")

        # Verify tags have merged confidence
        tags = conn.execute(
            "SELECT tag_group, confidence FROM work_classification_tags "
            "WHERE work_id = ? AND source = 'model'",
            (work_id,),
        ).fetchall()
        conn.close()

        tag_conf = {t["tag_group"]: t["confidence"] for t in tags}
        self.assertEqual(tag_conf.get("risk_domain"), "high",
                         "CLI apply: risk_domain should use embedded confidence (high)")
        self.assertEqual(tag_conf.get("method_tags"), "medium",
                         "CLI apply: method_tags should use embedded confidence (medium)")

        # Cleanup
        conn = _test_get_conn()
        conn.execute("DELETE FROM work_classification_tags WHERE work_id = ?", (work_id,))
        conn.execute("DELETE FROM classification_extractions WHERE id = ?", (ext_id,))
        conn.execute("DELETE FROM works WHERE id = ?", (work_id,))
        conn.commit()
        conn.close()


if __name__ == "__main__":
    unittest.main()
