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
         patch("api.routes.files.get_conn", _test_get_conn):
        yield


@pytest.fixture(autouse=True, scope="session")
def _cleanup_temp_db():
    yield
    shutil.rmtree(_tmp_dir, ignore_errors=True)


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


if __name__ == "__main__":
    unittest.main()
