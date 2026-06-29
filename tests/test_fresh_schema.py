"""Tests for P1-03: fresh schema initialization includes source_files.status column.

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

from scripts.literature_ingest import ensure_core_schema


def _make_temp_db():
    root = Path(tempfile.mkdtemp(prefix="litlib_schema_test_"))
    db_path = root / "literature.sqlite"
    return root, db_path


class TestFreshSchemaHasStatusColumn(unittest.TestCase):
    """P1-03: Fresh DB from ensure_core_schema() must have status column on source_files."""

    def test_fresh_schema_has_status_column(self):
        root, db_path = _make_temp_db()
        try:
            conn = sqlite3.connect(str(db_path))
            ensure_core_schema(conn)
            conn.commit()

            # Verify status column exists
            cols = {r[1] for r in conn.execute("PRAGMA table_info(source_files)").fetchall()}
            self.assertIn("status", cols, "source_files should have 'status' column")
            self.assertIn("archived_at", cols, "source_files should have 'archived_at' column")
            self.assertIn("archive_path", cols, "source_files should have 'archive_path' column")
            self.assertIn("archive_reason", cols, "source_files should have 'archive_reason' column")
            conn.close()
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_fresh_schema_status_default_is_active(self):
        root, db_path = _make_temp_db()
        try:
            conn = sqlite3.connect(str(db_path))
            ensure_core_schema(conn)
            conn.commit()

            # Insert a work and source file
            conn.execute(
                "INSERT INTO works (id, title, read_status) VALUES (?, ?, ?)",
                ("W-test-001", "Test", "unread"),
            )
            conn.execute(
                """INSERT INTO source_files
                   (id, work_id, content_sha256, original_name, source_path,
                    relative_source_path, file_size, file_ext)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                ("SF-test-00001", "W-test-001", "abc", "test.pdf",
                 "/tmp/test.pdf", "tmp/test.pdf", 100, ".pdf"),
            )
            conn.commit()

            row = conn.execute("SELECT status FROM source_files WHERE id = 'SF-test-00001'").fetchone()
            self.assertEqual(row[0], "active")
            conn.close()
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_old_schema_migration_adds_status(self):
        """Old schema missing status → migration adds it → existing rows get 'active'."""
        root, db_path = _make_temp_db()
        try:
            conn = sqlite3.connect(str(db_path))
            # Create old schema (without status column)
            conn.executescript("""
                CREATE TABLE works (
                    id TEXT PRIMARY KEY, title TEXT, read_status TEXT DEFAULT 'unread'
                );
                CREATE TABLE source_files (
                    id TEXT PRIMARY KEY, work_id TEXT NOT NULL, content_sha256 TEXT NOT NULL,
                    original_name TEXT, source_path TEXT NOT NULL,
                    relative_source_path TEXT NOT NULL, file_size INTEGER, file_ext TEXT,
                    import_time TEXT, mtime TEXT
                );
            """)
            # Insert a row WITHOUT status
            conn.execute(
                "INSERT INTO works (id, title, read_status) VALUES (?, ?, ?)",
                ("W-test-001", "Test", "unread"),
            )
            conn.execute(
                """INSERT INTO source_files
                   (id, work_id, content_sha256, original_name, source_path,
                    relative_source_path, file_size, file_ext)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                ("SF-test-00001", "W-test-001", "abc", "test.pdf",
                 "/tmp/test.pdf", "tmp/test.pdf", 100, ".pdf"),
            )
            conn.commit()

            # Now run ensure_core_schema (should migrate)
            ensure_core_schema(conn)
            conn.commit()

            # Verify column exists and row has default value
            cols = {r[1] for r in conn.execute("PRAGMA table_info(source_files)").fetchall()}
            self.assertIn("status", cols)

            row = conn.execute("SELECT status FROM source_files WHERE id = 'SF-test-00001'").fetchone()
            self.assertEqual(row[0], "active",
                             "Existing rows should get status='active' after migration")
            conn.close()
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_fresh_db_api_works_returns_200(self):
        """Fresh empty DB + ensure_core_schema() → GET /api/works returns 200."""
        root, db_path = _make_temp_db()
        try:
            conn = sqlite3.connect(str(db_path))
            ensure_core_schema(conn)
            conn.commit()
            conn.close()

            # Also create work_codes table that the API may need
            conn = sqlite3.connect(str(db_path))
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS work_codes (
                    work_id TEXT, source_file_id TEXT, code TEXT, reason TEXT,
                    created_at TEXT, UNIQUE(work_id, code)
                );
                CREATE TABLE IF NOT EXISTS work_relations (
                    work_id_a TEXT, work_id_b TEXT, relation_type TEXT,
                    note TEXT, relation_category TEXT, source TEXT,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS work_classification_tags (
                    work_id TEXT, tag_group TEXT, tag_value TEXT,
                    confidence REAL, evidence TEXT, review_status TEXT,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS literature_parse_runs (
                    id TEXT PRIMARY KEY, work_id TEXT NOT NULL,
                    source_file_id TEXT NOT NULL, source_path TEXT NOT NULL,
                    task_id TEXT, status TEXT NOT NULL, backend TEXT,
                    parse_method TEXT, file_size INTEGER, started_at TEXT,
                    finished_at TEXT, output_dir TEXT, error TEXT,
                    content_json_path TEXT, content_md_path TEXT,
                    package_path TEXT
                );
                CREATE TABLE IF NOT EXISTS duplicate_candidates (
                    id TEXT PRIMARY KEY, group_id TEXT, source_file_id TEXT,
                    work_id TEXT, source_path TEXT, score REAL, reason TEXT
                );
            """)
            conn.commit()
            conn.close()

            def _test_get_conn():
                c = sqlite3.connect(str(db_path))
                c.row_factory = sqlite3.Row
                c.execute("PRAGMA journal_mode=WAL")
                return c

            with patch("api.routes.works.get_conn", _test_get_conn), \
                 patch("api.db.DB_PATH", db_path):
                from api.main import app
                client = TestClient(app)
                resp = client.get("/api/works")

            self.assertEqual(resp.status_code, 200, resp.text)
            data = resp.json()
            self.assertEqual(data["total"], 0)
            self.assertEqual(data["works"], [])
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
