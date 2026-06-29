"""Tests for POST /api/works/{work_id}/sources/{source_file_id}/archive and restore.

Uses temp DB + temp file system. Never touches real literature.sqlite.
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
    """Create a minimal temp library with DB + works dir."""
    root = Path(tempfile.mkdtemp(prefix="litlib_archive_test_"))
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
        CREATE TABLE literature_parse_runs (
            id TEXT PRIMARY KEY, work_id TEXT NOT NULL,
            source_file_id TEXT NOT NULL, source_path TEXT,
            task_id TEXT, status TEXT DEFAULT 'pending',
            backend TEXT, parse_method TEXT, file_size INTEGER,
            started_at TEXT, finished_at TEXT, output_dir TEXT,
            error TEXT, content_json_path TEXT,
            content_md_path TEXT, package_path TEXT
        );
        CREATE TABLE work_codes (
            work_id TEXT, source_file_id TEXT, code TEXT, reason TEXT,
            created_at TEXT, UNIQUE(work_id, code)
        );
    """)
    conn.close()
    return root, db_path


def _conn(db_path):
    c = sqlite3.connect(str(db_path))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _seed_work(conn, work_id="W1", read_status="unread", parse_status="unknown"):
    conn.execute(
        "INSERT INTO works (id, title, read_status, parse_status) VALUES (?, ?, ?, ?)",
        (work_id, "Test Paper", read_status, parse_status),
    )


def _seed_source(conn, sf_id, work_id="W1", status="active",
                 original_name="paper.pdf", source_path="/fake/paper.pdf"):
    conn.execute(
        "INSERT INTO source_files "
        "(id, work_id, content_sha256, original_name, source_path, "
        "relative_source_path, file_size, file_ext, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (sf_id, work_id, f"sha_{sf_id}", original_name, source_path,
         f"works/{work_id}/source/{Path(source_path).name}", 100, ".pdf", status),
    )


def _seed_run(conn, run_id, sf_id, work_id="W1", status="succeeded",
              content_md_path="/fake/content.md"):
    conn.execute(
        "INSERT INTO literature_parse_runs "
        "(id, work_id, source_file_id, source_path, status, content_md_path) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, work_id, sf_id, f"/fake/{sf_id}.pdf", status, content_md_path),
    )


class TestSourceFileArchive(unittest.TestCase):

    def setUp(self):
        self.root, self.db_path = _make_temp_library()
        self.work_dir = self.root / "works" / "W1" / "source"
        self.work_dir.mkdir(parents=True)
        self.pdf1 = self.work_dir / "main.pdf"
        self.pdf1.write_bytes(b"%PDF main content")
        self.pdf2 = self.work_dir / "supplement.pdf"
        self.pdf2.write_bytes(b"%PDF supplement content")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _make_client(self):
        def _test_get_conn():
            return _conn(self.db_path)

        from api.main import app
        return TestClient(app), _test_get_conn

    def test_archive_failed_source_restores_parse_status(self):
        """Archive a failed source → only succeeded source remains → parse_status='succeeded'."""
        conn = _conn(self.db_path)
        _seed_work(conn, parse_status="partial")
        _seed_source(conn, "SF1", original_name="main.pdf", source_path=str(self.pdf1))
        _seed_source(conn, "SF2", original_name="supplement.pdf", source_path=str(self.pdf2))
        _seed_run(conn, "R1", "SF1", status="succeeded", content_md_path="/md/c.md")
        _seed_run(conn, "R2", "SF2", status="failed", content_md_path="")
        conn.commit()
        conn.close()

        client, get_conn_fn = self._make_client()
        with patch("api.routes.works.get_conn", get_conn_fn), \
             patch("api.routes.works.LIBRARY_ROOT", self.root):
            resp = client.post(
                "/api/works/W1/sources/SF2/archive",
                json={"reason": "cannot parse"},
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["parse_status"], "succeeded")

        # Verify DB
        conn = _conn(self.db_path)
        sf2 = conn.execute("SELECT status, archived_at, archive_reason FROM source_files WHERE id='SF2'").fetchone()
        self.assertEqual(sf2["status"], "archived")
        self.assertIsNotNone(sf2["archived_at"])
        self.assertEqual(sf2["archive_reason"], "cannot parse")
        # read_status must NOT change
        w = conn.execute("SELECT read_status, parse_status FROM works WHERE id='W1'").fetchone()
        self.assertEqual(w["read_status"], "unread")
        self.assertEqual(w["parse_status"], "succeeded")
        # source_path must follow the file to its archive location (house convention:
        # archived rows keep source_path == archive_path, both existing) so that
        # archiving does NOT create a healthcheck phantom.
        sf2 = conn.execute(
            "SELECT source_path, archive_path FROM source_files WHERE id='SF2'"
        ).fetchone()
        self.assertEqual(sf2["source_path"], sf2["archive_path"])
        self.assertTrue(Path(sf2["source_path"]).exists())
        conn.close()

        # Archiving must keep healthcheck clean (no phantom from the moved file)
        from scripts.healthcheck_library import run_healthcheck
        hc = run_healthcheck(self.root, dry_run=True)
        self.assertEqual(hc.phantom_db_entries, [])
        self.assertFalse(hc.has_issues())

    def test_archive_nonexistent_source_returns_404(self):
        conn = _conn(self.db_path)
        _seed_work(conn)
        _seed_source(conn, "SF1", source_path=str(self.pdf1))
        conn.commit()
        conn.close()

        client, get_conn_fn = self._make_client()
        with patch("api.routes.works.get_conn", get_conn_fn), \
             patch("api.routes.works.LIBRARY_ROOT", self.root):
            resp = client.post(
                "/api/works/W1/sources/SF-NONEXISTENT/archive",
                json={"reason": "test"},
            )
        self.assertEqual(resp.status_code, 404)

    def test_archive_source_from_other_work_returns_404(self):
        conn = _conn(self.db_path)
        _seed_work(conn, work_id="W1")
        _seed_work(conn, work_id="W2")
        _seed_source(conn, "SF1", work_id="W2", source_path=str(self.pdf1))
        conn.commit()
        conn.close()

        client, get_conn_fn = self._make_client()
        with patch("api.routes.works.get_conn", get_conn_fn), \
             patch("api.routes.works.LIBRARY_ROOT", self.root):
            resp = client.post(
                "/api/works/W1/sources/SF1/archive",
                json={"reason": "test"},
            )
        self.assertEqual(resp.status_code, 404)

    def test_restore_reactivates_source(self):
        conn = _conn(self.db_path)
        _seed_work(conn, parse_status="succeeded")
        _seed_source(conn, "SF1", status="active", source_path=str(self.pdf1))
        _seed_source(conn, "SF2", status="archived", original_name="supplement.pdf",
                     source_path=str(self.root / "_archive" / "W1" / "supplement.pdf"))
        _seed_run(conn, "R1", "SF1", status="succeeded", content_md_path="/md/c.md")
        _seed_run(conn, "R2", "SF2", status="succeeded", content_md_path="/md/c2.md")
        # Move SF2 file to archive dir
        archive_dir = self.root / "_archive" / "W1"
        archive_dir.mkdir(parents=True)
        shutil.move(str(self.pdf2), str(archive_dir / "supplement.pdf"))
        conn.commit()
        conn.close()

        client, get_conn_fn = self._make_client()
        with patch("api.routes.works.get_conn", get_conn_fn), \
             patch("api.routes.works.LIBRARY_ROOT", self.root):
            resp = client.post("/api/works/W1/sources/SF2/restore")
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["parse_status"], "succeeded")

        conn = _conn(self.db_path)
        sf2 = conn.execute("SELECT status, archived_at, archive_path, archive_reason FROM source_files WHERE id='SF2'").fetchone()
        self.assertEqual(sf2["status"], "active")
        self.assertIsNone(sf2["archived_at"])
        self.assertIsNone(sf2["archive_path"])
        self.assertIsNone(sf2["archive_reason"])
        conn.close()

    def test_archive_path_traversal_rejected(self):
        conn = _conn(self.db_path)
        _seed_work(conn)
        _seed_source(conn, "SF1", original_name="../evil.pdf", source_path=str(self.pdf1))
        conn.commit()
        conn.close()

        client, get_conn_fn = self._make_client()
        with patch("api.routes.works.get_conn", get_conn_fn), \
             patch("api.routes.works.LIBRARY_ROOT", self.root):
            resp = client.post(
                "/api/works/W1/sources/SF1/archive",
                json={"reason": "test"},
            )
        self.assertEqual(resp.status_code, 422, resp.text)
        self.assertIn("Invalid filename", resp.text)
        # File should NOT be moved
        self.assertTrue(self.pdf1.exists())


if __name__ == "__main__":
    unittest.main()
