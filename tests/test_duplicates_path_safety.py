"""Tests for P2-F2: duplicates file-move paths must sanitize original_name.

``api/routes/duplicates.py`` moves source files during a quarantine decision
(``_move_to_quarantine``) and during a same_work merge (archive secondary). Both
constructed destination paths from the raw DB ``source_files.original_name``
without going through ``api.path_safety._sanitize_filename``, leaving a path
traversal surface if ``original_name`` ever holds ``../`` or an absolute path.

These tests drive the public ``/duplicates/{group_id}/review`` endpoint with
``decision='quarantine'`` and assert dirty names are rejected (422) and the file
is not moved out of ``works/``. Uses a temp library; never touches the real one.
"""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


def _make_temp_library():
    root = Path(tempfile.mkdtemp(prefix="litlib_dupsafe_test_"))
    db_path = root / "literature.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE works (
            id TEXT PRIMARY KEY, title TEXT, read_status TEXT DEFAULT 'unread',
            updated_at TEXT
        );
        CREATE TABLE source_files (
            id TEXT PRIMARY KEY, work_id TEXT NOT NULL, content_sha256 TEXT NOT NULL,
            original_name TEXT, source_path TEXT NOT NULL,
            relative_source_path TEXT NOT NULL, file_size INTEGER, file_ext TEXT,
            import_time TEXT, status TEXT DEFAULT 'active'
        );
        CREATE TABLE work_codes (
            work_id TEXT, source_file_id TEXT, code TEXT, reason TEXT,
            created_at TEXT, UNIQUE(work_id, code)
        );
        CREATE TABLE duplicate_groups (
            id TEXT PRIMARY KEY, duplicate_type TEXT, key TEXT, count INTEGER
        );
        CREATE TABLE duplicate_candidates (
            id TEXT PRIMARY KEY, group_id TEXT, source_file_id TEXT,
            work_id TEXT, reviewed INTEGER DEFAULT 0
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


class TestDuplicatesQuarantinePathSafety(unittest.TestCase):
    """``decision='quarantine'`` must reject dirty original_name."""

    def setUp(self):
        self.root, self.db_path = _make_temp_library()
        self.work_dir = self.root / "works" / "W-dup-001" / "source"
        self.work_dir.mkdir(parents=True)
        self.pdf = self.work_dir / "normal.pdf"
        self.pdf.write_bytes(b"%PDF dup content")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _seed(self, original_name):
        conn = _conn(self.db_path)
        conn.execute(
            "INSERT INTO works (id, title, read_status) VALUES ('W-dup-001', 'Dup', 'unread')"
        )
        conn.execute(
            """INSERT INTO source_files
               (id, work_id, content_sha256, original_name, source_path,
                relative_source_path, file_size, file_ext, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')""",
            ("SF-dup-001", "W-dup-001", "sha1", original_name, str(self.pdf),
             f"works/W-dup-001/source/{self.pdf.name}", 100, ".pdf"),
        )
        conn.execute(
            "INSERT INTO duplicate_groups (id, duplicate_type, key, count) "
            "VALUES ('DG-dup-001', 'title_candidate', 'k', 1)"
        )
        conn.execute(
            "INSERT INTO duplicate_candidates (id, group_id, source_file_id, work_id, reviewed) "
            "VALUES ('DC-dup-001', 'DG-dup-001', 'SF-dup-001', 'W-dup-001', 0)"
        )
        conn.commit()
        conn.close()

    def _review_quarantine(self):
        def _test_get_conn():
            return _conn(self.db_path)
        with patch("api.routes.duplicates.get_conn", _test_get_conn), \
             patch("api.routes.duplicates.LIBRARY_ROOT", self.root):
            from api.main import app
            client = TestClient(app)
            return client.post(
                "/api/duplicates/DG-dup-001/review",
                json={"decision": "quarantine", "note": "bad_source"},
            )

    def test_dotdot_slash_rejected(self):
        self._seed("../evil.pdf")
        resp = self._review_quarantine()
        self.assertEqual(resp.status_code, 422, resp.text)
        self.assertIn("Invalid filename", resp.text)
        # File must NOT have been moved out of works/
        self.assertTrue(self.pdf.exists(), "File should NOT be moved")

    def test_absolute_path_rejected(self):
        self._seed("C:\\tmp\\evil.pdf")
        resp = self._review_quarantine()
        self.assertEqual(resp.status_code, 422, resp.text)
        self.assertTrue(self.pdf.exists())

    def test_backslash_dotdot_rejected(self):
        self._seed("..\\evil.pdf")
        resp = self._review_quarantine()
        self.assertEqual(resp.status_code, 422, resp.text)
        self.assertTrue(self.pdf.exists())

    def test_clean_name_moves_file(self):
        """A clean original_name still moves the file into _quarantine/."""
        self._seed("paper.pdf")
        resp = self._review_quarantine()
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertFalse(self.pdf.exists(), "File should have been moved")
        moved = list((self.root / "_quarantine" / "W-dup-001").glob("*"))
        self.assertEqual(len(moved), 1)
        self.assertEqual(moved[0].name, "paper.pdf")


if __name__ == "__main__":
    unittest.main()
