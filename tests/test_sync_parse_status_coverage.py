"""Tests for sync_work_parse_status coverage-aware semantics.

Each case uses a temp DB with works/source_files/literature_parse_runs tables.
"""
from __future__ import annotations

import sqlite3
import unittest


def _make_temp_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE works (
            id TEXT PRIMARY KEY, title TEXT, parse_status TEXT DEFAULT 'pending',
            read_status TEXT DEFAULT 'unread', created_at TEXT, updated_at TEXT
        );
        CREATE TABLE source_files (
            id TEXT PRIMARY KEY, work_id TEXT NOT NULL,
            content_sha256 TEXT NOT NULL, original_name TEXT,
            source_path TEXT NOT NULL, relative_source_path TEXT NOT NULL,
            file_size INTEGER, file_ext TEXT, import_time TEXT, mtime TEXT,
            status TEXT DEFAULT 'active',
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
    """)
    return conn


def _add_work(conn, work_id="W1"):
    conn.execute("INSERT INTO works (id, title) VALUES (?, ?)", (work_id, "Test"))


def _add_source(conn, sf_id, work_id="W1", status="active"):
    conn.execute(
        "INSERT INTO source_files (id, work_id, content_sha256, original_name, "
        "source_path, relative_source_path, file_size, file_ext, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (sf_id, work_id, f"sha_{sf_id}", f"{sf_id}.pdf",
         f"/fake/{sf_id}.pdf", f"works/{work_id}/source/{sf_id}.pdf",
         100, ".pdf", status),
    )


def _add_run(conn, run_id, sf_id, work_id="W1", status="succeeded",
             content_md_path="/fake/content.md"):
    conn.execute(
        "INSERT INTO literature_parse_runs "
        "(id, work_id, source_file_id, source_path, status, content_md_path) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, work_id, sf_id, f"/fake/{sf_id}.pdf", status, content_md_path),
    )


class TestSyncParseStatusCoverage(unittest.TestCase):

    def test_single_source_succeeded(self):
        conn = _make_temp_conn()
        _add_work(conn)
        _add_source(conn, "SF1")
        _add_run(conn, "R1", "SF1", status="succeeded", content_md_path="/md/c.md")
        from scripts.migrate_sync_parse_status import sync_work_parse_status
        result = sync_work_parse_status(conn, "W1")
        self.assertEqual(result, "succeeded")
        row = conn.execute("SELECT parse_status FROM works WHERE id='W1'").fetchone()
        self.assertEqual(row["parse_status"], "succeeded")
        conn.close()

    def test_single_source_failed(self):
        conn = _make_temp_conn()
        _add_work(conn)
        _add_source(conn, "SF1")
        _add_run(conn, "R1", "SF1", status="failed", content_md_path="")
        from scripts.migrate_sync_parse_status import sync_work_parse_status
        result = sync_work_parse_status(conn, "W1")
        self.assertEqual(result, "failed")
        row = conn.execute("SELECT parse_status FROM works WHERE id='W1'").fetchone()
        self.assertEqual(row["parse_status"], "failed")
        conn.close()

    def test_single_source_no_run(self):
        conn = _make_temp_conn()
        _add_work(conn)
        _add_source(conn, "SF1")
        from scripts.migrate_sync_parse_status import sync_work_parse_status
        result = sync_work_parse_status(conn, "W1")
        self.assertEqual(result, "pending")
        row = conn.execute("SELECT parse_status FROM works WHERE id='W1'").fetchone()
        self.assertEqual(row["parse_status"], "pending")
        conn.close()

    def test_dual_active_one_succeeded_one_pending(self):
        conn = _make_temp_conn()
        _add_work(conn)
        _add_source(conn, "SF1")
        _add_source(conn, "SF2")
        _add_run(conn, "R1", "SF1", status="succeeded", content_md_path="/md/c.md")
        # SF2 has no runs → pending
        from scripts.migrate_sync_parse_status import sync_work_parse_status
        result = sync_work_parse_status(conn, "W1")
        self.assertEqual(result, "partial",
                         "One succeeded + one pending active source should yield partial")
        row = conn.execute("SELECT parse_status FROM works WHERE id='W1'").fetchone()
        self.assertEqual(row["parse_status"], "partial")
        conn.close()

    def test_dual_active_both_succeeded(self):
        conn = _make_temp_conn()
        _add_work(conn)
        _add_source(conn, "SF1")
        _add_source(conn, "SF2")
        _add_run(conn, "R1", "SF1", status="succeeded", content_md_path="/md/c1.md")
        _add_run(conn, "R2", "SF2", status="succeeded", content_md_path="/md/c2.md")
        from scripts.migrate_sync_parse_status import sync_work_parse_status
        result = sync_work_parse_status(conn, "W1")
        self.assertEqual(result, "succeeded")
        row = conn.execute("SELECT parse_status FROM works WHERE id='W1'").fetchone()
        self.assertEqual(row["parse_status"], "succeeded")
        conn.close()

    def test_dual_active_one_succeeded_one_failed(self):
        conn = _make_temp_conn()
        _add_work(conn)
        _add_source(conn, "SF1")
        _add_source(conn, "SF2")
        _add_run(conn, "R1", "SF1", status="succeeded", content_md_path="/md/c.md")
        _add_run(conn, "R2", "SF2", status="failed", content_md_path="")
        from scripts.migrate_sync_parse_status import sync_work_parse_status
        result = sync_work_parse_status(conn, "W1")
        self.assertEqual(result, "partial")
        row = conn.execute("SELECT parse_status FROM works WHERE id='W1'").fetchone()
        self.assertEqual(row["parse_status"], "partial")
        conn.close()

    def test_active_succeeded_plus_archived_failed(self):
        conn = _make_temp_conn()
        _add_work(conn)
        _add_source(conn, "SF1", status="active")
        _add_source(conn, "SF2", status="archived")
        _add_run(conn, "R1", "SF1", status="succeeded", content_md_path="/md/c.md")
        _add_run(conn, "R2", "SF2", status="failed", content_md_path="")
        from scripts.migrate_sync_parse_status import sync_work_parse_status
        result = sync_work_parse_status(conn, "W1")
        self.assertEqual(result, "succeeded",
                         "Archived source should not affect parse_status")
        row = conn.execute("SELECT parse_status FROM works WHERE id='W1'").fetchone()
        self.assertEqual(row["parse_status"], "succeeded")
        conn.close()

    def test_all_active_failed(self):
        conn = _make_temp_conn()
        _add_work(conn)
        _add_source(conn, "SF1")
        _add_source(conn, "SF2")
        _add_run(conn, "R1", "SF1", status="failed", content_md_path="")
        _add_run(conn, "R2", "SF2", status="failed", content_md_path="")
        from scripts.migrate_sync_parse_status import sync_work_parse_status
        result = sync_work_parse_status(conn, "W1")
        self.assertEqual(result, "failed")
        row = conn.execute("SELECT parse_status FROM works WHERE id='W1'").fetchone()
        self.assertEqual(row["parse_status"], "failed")
        conn.close()


if __name__ == "__main__":
    unittest.main()
