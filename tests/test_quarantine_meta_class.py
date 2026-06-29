"""Tests for P2-POST-01: metadata/classification quarantine reuses works.py safe filename logic.

Uses temp DB + temp file system. Never touches real literature.sqlite.
"""
from __future__ import annotations

import shutil
import sqlite3
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


def _make_temp_library():
    """Create a minimal temp library with DB + works dir."""
    import tempfile
    root = Path(tempfile.mkdtemp(prefix="litlib_meta_class_test_"))
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
        CREATE TABLE work_codes (
            work_id TEXT, source_file_id TEXT, code TEXT, reason TEXT,
            created_at TEXT, UNIQUE(work_id, code)
        );
        CREATE TABLE metadata_extractions (
            id TEXT PRIMARY KEY, work_id TEXT, model_name TEXT,
            content_md_path TEXT, input_chars INTEGER DEFAULT 0,
            input_tokens_est INTEGER DEFAULT 0, raw_response TEXT DEFAULT '{}',
            extracted_json TEXT DEFAULT '{}', confidence_json TEXT DEFAULT '{}',
            applied INTEGER DEFAULT 0, applied_at TEXT, created_at TEXT,
            review_status TEXT DEFAULT 'pending', review_note TEXT DEFAULT '',
            reviewed_at TEXT, risk_level TEXT DEFAULT 'low', risk_score INTEGER DEFAULT 0,
            risk_reasons TEXT DEFAULT '[]', review_source TEXT DEFAULT 'human',
            fix_action TEXT DEFAULT '', superseded_by TEXT DEFAULT ''
        );
        CREATE TABLE classification_extractions (
            id TEXT PRIMARY KEY, work_id TEXT, model_name TEXT,
            prompt_version TEXT, extracted_json TEXT DEFAULT '{}',
            confidence_json TEXT DEFAULT '{}', ambiguity_score INTEGER DEFAULT 0,
            ambiguity_reasons TEXT DEFAULT '[]', review_status TEXT DEFAULT 'pending',
            review_note TEXT, reviewed_at TEXT, fix_action TEXT,
            applied INTEGER DEFAULT 0, applied_at TEXT, raw_response TEXT DEFAULT '{}',
            created_at TEXT, updated_at TEXT
        );
    """)
    conn.close()
    return root, db_path


def _conn(db_path):
    c = sqlite3.connect(str(db_path))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _seed_work_and_source(conn, work_id="W-test-001", source_id="SF-test-001",
                          original_name="paper.pdf", source_path=None):
    conn.execute(
        "INSERT INTO works (id, title, read_status) VALUES (?, ?, ?)",
        (work_id, "Test Paper", "unread"),
    )
    conn.execute(
        """INSERT INTO source_files
           (id, work_id, content_sha256, original_name, source_path,
            relative_source_path, file_size, file_ext, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (source_id, work_id, "abc123", original_name, str(source_path),
         f"works/{work_id}/source/{Path(source_path).name}", 100, ".pdf", "active"),
    )
    conn.commit()


class TestMetadataQuarantinePathSafety(unittest.TestCase):
    """P2-POST-01: metadata quarantine must reject dirty original_name via _sanitize_filename."""

    def setUp(self):
        self.root, self.db_path = _make_temp_library()
        self.work_dir = self.root / "works" / "W-test-001" / "source"
        self.work_dir.mkdir(parents=True)
        self.pdf = self.work_dir / "normal.pdf"
        self.pdf.write_bytes(b"%PDF fake content")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _quarantine(self, original_name):
        """Run metadata quarantine and return response."""
        conn = _conn(self.db_path)
        _seed_work_and_source(conn, original_name=original_name, source_path=self.pdf)
        conn.execute(
            "INSERT INTO metadata_extractions (id, work_id, model_name, review_status) "
            "VALUES ('ME-test', 'W-test-001', 'test', 'pending')",
        )
        conn.commit()
        conn.close()

        def _test_get_conn():
            return _conn(self.db_path)

        from unittest.mock import patch
        with patch("api.routes.metadata.get_conn", _test_get_conn), \
             patch("api.routes.metadata.LIBRARY_ROOT", self.root):
            from api.main import app
            client = TestClient(app)
            resp = client.post(
                "/api/metadata/ME-test/quarantine",
                json={"reason": "bad_source"},
            )
        return resp

    def test_dotdot_slash_rejected(self):
        resp = self._quarantine("../evil.pdf")
        self.assertEqual(resp.status_code, 422, resp.text)
        self.assertIn("Invalid filename", resp.text)
        self.assertTrue(self.pdf.exists(), "File should NOT be moved")

        conn = _conn(self.db_path)
        w = conn.execute("SELECT read_status FROM works WHERE id='W-test-001'").fetchone()
        conn.close()
        self.assertEqual(w["read_status"], "unread")

    def test_absolute_path_rejected(self):
        resp = self._quarantine("C:\\tmp\\evil.pdf")
        self.assertEqual(resp.status_code, 422, resp.text)
        self.assertTrue(self.pdf.exists())

    def test_slash_in_name_rejected(self):
        resp = self._quarantine("a/b.pdf")
        self.assertEqual(resp.status_code, 422, resp.text)
        self.assertTrue(self.pdf.exists())

    def test_backslash_dotdot_rejected(self):
        resp = self._quarantine("..\\evil.pdf")
        self.assertEqual(resp.status_code, 422, resp.text)
        self.assertTrue(self.pdf.exists())

    def test_null_original_name_ok(self):
        resp = self._quarantine(None)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertFalse(self.pdf.exists(), "File should have been moved")

        quarantine_dir = self.root / "_quarantine" / "W-test-001"
        moved = list(quarantine_dir.glob("*"))
        self.assertEqual(len(moved), 1)
        self.assertEqual(moved[0].name, "normal.pdf")


class TestClassificationQuarantinePathSafety(unittest.TestCase):
    """P2-POST-01: classification quarantine must reject dirty original_name via _sanitize_filename."""

    def setUp(self):
        self.root, self.db_path = _make_temp_library()
        self.work_dir = self.root / "works" / "W-test-001" / "source"
        self.work_dir.mkdir(parents=True)
        self.pdf = self.work_dir / "normal.pdf"
        self.pdf.write_bytes(b"%PDF fake content")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _quarantine(self, original_name):
        conn = _conn(self.db_path)
        _seed_work_and_source(conn, original_name=original_name, source_path=self.pdf)
        conn.execute(
            "INSERT INTO classification_extractions "
            "(id, work_id, model_name, review_status) "
            "VALUES ('CE-test', 'W-test-001', 'test', 'pending')",
        )
        conn.commit()
        conn.close()

        def _test_get_conn():
            return _conn(self.db_path)

        from unittest.mock import patch
        with patch("api.routes.classification.get_conn", _test_get_conn), \
             patch("api.routes.classification.LIBRARY_ROOT", self.root):
            from api.main import app
            client = TestClient(app)
            resp = client.post(
                "/api/classification/extractions/CE-test/quarantine",
                json={"reason": "bad_source"},
            )
        return resp

    def test_dotdot_slash_rejected(self):
        resp = self._quarantine("../evil.pdf")
        self.assertEqual(resp.status_code, 422, resp.text)
        self.assertIn("Invalid filename", resp.text)
        self.assertTrue(self.pdf.exists())

    def test_absolute_path_rejected(self):
        resp = self._quarantine("C:\\tmp\\evil.pdf")
        self.assertEqual(resp.status_code, 422, resp.text)
        self.assertTrue(self.pdf.exists())

    def test_slash_in_name_rejected(self):
        resp = self._quarantine("a/b.pdf")
        self.assertEqual(resp.status_code, 422, resp.text)
        self.assertTrue(self.pdf.exists())

    def test_backslash_dotdot_rejected(self):
        resp = self._quarantine("..\\evil.pdf")
        self.assertEqual(resp.status_code, 422, resp.text)
        self.assertTrue(self.pdf.exists())

    def test_null_original_name_ok(self):
        resp = self._quarantine(None)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertFalse(self.pdf.exists())

        quarantine_dir = self.root / "_quarantine" / "W-test-001"
        moved = list(quarantine_dir.glob("*"))
        self.assertEqual(len(moved), 1)
        self.assertEqual(moved[0].name, "normal.pdf")


if __name__ == "__main__":
    unittest.main()
