"""Tests for P2-03: promote idempotency for already-ingested candidates.

Uses temp DB. Never touches real literature.sqlite.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.main import app


def _make_temp_library():
    root = Path(tempfile.mkdtemp(prefix="litlib_promote_test_"))
    db_path = root / "literature.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE works (
            id TEXT PRIMARY KEY, title TEXT, authors TEXT, year INTEGER,
            arxiv_id TEXT, doi TEXT, doc_type TEXT, language TEXT DEFAULT 'unknown',
            metadata_status TEXT DEFAULT 'auto', parse_status TEXT DEFAULT 'unknown',
            read_status TEXT DEFAULT 'unread', created_at TEXT, updated_at TEXT
        );
        CREATE TABLE source_files (
            id TEXT PRIMARY KEY, work_id TEXT NOT NULL, content_sha256 TEXT NOT NULL,
            original_name TEXT, source_path TEXT NOT NULL,
            relative_source_path TEXT NOT NULL, file_size INTEGER, file_ext TEXT,
            import_time TEXT, mtime TEXT, status TEXT DEFAULT 'active',
            archived_at TEXT, archive_path TEXT, archive_reason TEXT
        );
        CREATE TABLE intake_candidates (
            id TEXT PRIMARY KEY, source_type TEXT, url_canonical TEXT,
            title TEXT, arxiv_id TEXT, doi TEXT, resolution TEXT,
            status TEXT DEFAULT 'pending', review_status TEXT DEFAULT 'pending',
            review_note TEXT, ingested_work_id TEXT, raw_meta TEXT,
            collection_topic_id TEXT, collected_at TEXT, matched_work_id TEXT,
            local_pdf_path TEXT, source_url TEXT, fetched_sha256 TEXT,
            resolved_at TEXT, UNIQUE(source_type, url_canonical)
        );
        CREATE TABLE work_codes (
            work_id TEXT, source_file_id TEXT, code TEXT, reason TEXT,
            created_at TEXT, UNIQUE(work_id, code)
        );
        CREATE TABLE IF NOT EXISTS classification_extractions (
            id TEXT PRIMARY KEY, work_id TEXT, model_name TEXT,
            prompt_version TEXT, extracted_json TEXT, confidence_json TEXT,
            ambiguity_score INTEGER, ambiguity_reasons TEXT,
            review_status TEXT DEFAULT 'pending', applied INTEGER DEFAULT 0,
            applied_at TEXT, raw_response TEXT, created_at TEXT, updated_at TEXT
        );
    """)
    conn.commit()
    conn.close()
    return root, db_path


def _conn(db_path):
    c = sqlite3.connect(str(db_path))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


class TestPromoteIdempotent(unittest.TestCase):
    """P2-03: Re-promoting an already-ingested candidate returns existing work_id."""

    def setUp(self):
        self.root, self.db_path = _make_temp_library()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _get_conn(self):
        return _conn(self.db_path)

    def test_first_promote_succeeds(self):
        """Approved + pending candidate → first promote succeeds."""
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO intake_candidates
               (id, source_type, url_canonical, title, arxiv_id, resolution, status, review_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("IC-test-01", "arxiv", "https://arxiv.org/abs/2501.00001",
             "Paper One", "2501.00001", "new", "pending", "approved"),
        )
        conn.commit()
        conn.close()

        def _test_get_conn():
            return _conn(self.db_path)

        with patch("api.routes.intake.get_conn", _test_get_conn), \
             patch("api.routes.intake.LIBRARY_ROOT", self.root), \
             patch("collector.ingest_bridge.get_conn", _test_get_conn), \
             patch("collector.candidate_store.get_conn", _test_get_conn), \
             patch("collector.gate.get_conn", _test_get_conn):
            # Mock the actual promote to avoid real ingest
            import collector.ingest_bridge as br
            with patch.object(br, "promote", return_value="W-new-work"):
                client = TestClient(app)
                resp = client.post("/api/intake/promote", json={"ids": ["IC-test-01"]})

        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(len(data["promoted"]), 1)
        self.assertEqual(data["promoted"][0]["work_id"], "W-new-work")
        self.assertNotIn("already_ingested", data["promoted"][0])

    def test_re_promote_ingested_with_work_id_returns_existing(self):
        """Approved + ingested + ingested_work_id → re-promote returns same work_id."""
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO intake_candidates
               (id, source_type, url_canonical, title, arxiv_id, resolution,
                status, review_status, ingested_work_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("IC-test-02", "arxiv", "https://arxiv.org/abs/2501.00002",
             "Paper Two", "2501.00002", "new", "ingested", "approved", "W-existing-work"),
        )
        conn.commit()
        conn.close()

        def _test_get_conn():
            return _conn(self.db_path)

        import collector.ingest_bridge as br
        promote_calls = []

        def fake_promote(cid, *, library_root):
            promote_calls.append(cid)
            return "W-should-not-be-called"

        with patch("api.routes.intake.get_conn", _test_get_conn), \
             patch("api.routes.intake.LIBRARY_ROOT", self.root), \
             patch.object(br, "promote", fake_promote):
            client = TestClient(app)
            resp = client.post("/api/intake/promote", json={"ids": ["IC-test-02"]})

        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(len(data["promoted"]), 1)
        self.assertEqual(data["promoted"][0]["work_id"], "W-existing-work")
        self.assertTrue(data["promoted"][0]["already_ingested"])
        self.assertEqual(len(promote_calls), 0, "ingest_bridge.promote should NOT be called")

    def test_ingested_no_work_id_returns_error(self):
        """Approved + ingested + no work_id → returns error."""
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO intake_candidates
               (id, source_type, url_canonical, title, arxiv_id, resolution,
                status, review_status, ingested_work_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("IC-test-03", "arxiv", "https://arxiv.org/abs/2501.00003",
             "Paper Three", "2501.00003", "new", "ingested", "approved", None),
        )
        conn.commit()
        conn.close()

        def _test_get_conn():
            return _conn(self.db_path)

        import collector.ingest_bridge as br

        with patch("api.routes.intake.get_conn", _test_get_conn), \
             patch("api.routes.intake.LIBRARY_ROOT", self.root), \
             patch.object(br, "promote", side_effect=AssertionError("should not be called")):
            client = TestClient(app)
            resp = client.post("/api/intake/promote", json={"ids": ["IC-test-03"]})

        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(len(data["promoted"]), 0)
        self.assertEqual(len(data["failed"]), 1)
        self.assertEqual(data["failed"][0]["id"], "IC-test-03")
        self.assertIn("ingested", data["failed"][0]["error"])

    def test_mixed_batch_ingested_and_pending(self):
        """Batch with both ingested and pending candidates handles both correctly."""
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO intake_candidates
               (id, source_type, url_canonical, title, arxiv_id, resolution,
                status, review_status, ingested_work_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("IC-ingested", "arxiv", "https://arxiv.org/abs/2501.00010",
             "Ingested Paper", "2501.00010", "new", "ingested", "approved", "W-old-work"),
        )
        conn.execute(
            """INSERT INTO intake_candidates
               (id, source_type, url_canonical, title, arxiv_id, resolution,
                status, review_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("IC-pending", "arxiv", "https://arxiv.org/abs/2501.00011",
             "Pending Paper", "2501.00011", "new", "pending", "approved"),
        )
        conn.commit()
        conn.close()

        def _test_get_conn():
            return _conn(self.db_path)

        import collector.ingest_bridge as br

        with patch("api.routes.intake.get_conn", _test_get_conn), \
             patch("api.routes.intake.LIBRARY_ROOT", self.root), \
             patch.object(br, "promote", return_value="W-new-work"):
            client = TestClient(app)
            resp = client.post("/api/intake/promote",
                               json={"ids": ["IC-ingested", "IC-pending"]})

        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        promoted_ids = {p["id"] for p in data["promoted"]}
        self.assertIn("IC-ingested", promoted_ids)
        self.assertIn("IC-pending", promoted_ids)

        # Check already_ingested flag
        for p in data["promoted"]:
            if p["id"] == "IC-ingested":
                self.assertTrue(p["already_ingested"])
                self.assertEqual(p["work_id"], "W-old-work")
            elif p["id"] == "IC-pending":
                self.assertNotIn("already_ingested", p)


if __name__ == "__main__":
    unittest.main()
