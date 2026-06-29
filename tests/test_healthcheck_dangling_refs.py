"""Tests for D3: dangling-reference detection in healthcheck.

No FK constraints exist on most tables, so a deleted ``works`` row can leave
child rows (source_files, literature_parse_runs, intake_candidates, ...) pointing
at a now-nonexistent work. The healthcheck must surface these dangling references
so they don't accumulate silently. Read-only — never writes the DB.
"""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.healthcheck_library import run_healthcheck


def _make_temp_library():
    root = Path(tempfile.mkdtemp(prefix="litlib_dangling_test_"))
    db_path = root / "literature.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE works (
            id TEXT PRIMARY KEY, title TEXT, read_status TEXT DEFAULT 'unread',
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE source_files (
            id TEXT PRIMARY KEY, work_id TEXT NOT NULL, content_sha256 TEXT NOT NULL,
            original_name TEXT, source_path TEXT NOT NULL,
            relative_source_path TEXT NOT NULL, file_size INTEGER, file_ext TEXT,
            import_time TEXT, status TEXT DEFAULT 'active',
            archived_at TEXT, archive_path TEXT, archive_reason TEXT
        );
        CREATE TABLE literature_parse_runs (
            id TEXT PRIMARY KEY, work_id TEXT, source_file_id TEXT,
            status TEXT, content_md_path TEXT, started_at TEXT, finished_at TEXT
        );
        CREATE TABLE intake_candidates (
            id TEXT PRIMARY KEY, title TEXT, status TEXT, review_status TEXT,
            ingested_work_id TEXT, matched_work_id TEXT, collection_topic_id TEXT
        );
        CREATE TABLE collection_topics (
            id TEXT PRIMARY KEY, label TEXT
        );
    """)
    # An empty works/ dir so disk scans find nothing (no orphans/phantoms noise).
    (root / "works").mkdir()
    conn.commit()
    conn.close()
    return root, db_path


class TestDanglingReferenceDetection(unittest.TestCase):

    def setUp(self):
        self.root, self.db_path = _make_temp_library()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _run(self):
        return run_healthcheck(self.root, dry_run=True)

    def test_dangling_source_files_work_id_detected(self):
        """source_files row whose work_id has no matching works row → flagged."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            "INSERT INTO source_files (id, work_id, content_sha256, source_path, "
            "relative_source_path) VALUES ('SF-1', 'W-GONE', 'sha', ?, ?)",
            (str(self.root / "x.pdf"), "works/W-GONE/source/x.pdf"),
        )
        conn.commit()
        conn.close()
        result = self._run()
        types = [d["type"] for d in result.dangling_references]
        self.assertIn("source_files.work_id", types)
        # Verify it's read-only: no applied fixes
        self.assertEqual(result.applied_fixes, [])

    def test_dangling_parse_runs_work_id_detected(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            "INSERT INTO literature_parse_runs (id, work_id, status) "
            "VALUES ('LPR-1', 'W-GONE', 'succeeded')"
        )
        conn.commit()
        conn.close()
        result = self._run()
        types = [d["type"] for d in result.dangling_references]
        self.assertIn("literature_parse_runs.work_id", types)

    def test_dangling_intake_candidate_ingested_work_id_detected(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            "INSERT INTO intake_candidates (id, title, status, ingested_work_id) "
            "VALUES ('C-1', 't', 'ingested', 'W-GONE')"
        )
        conn.commit()
        conn.close()
        result = self._run()
        types = [d["type"] for d in result.dangling_references]
        self.assertIn("intake_candidates.ingested_work_id", types)

    def test_dangling_topic_reference_detected(self):
        """intake_candidates.collection_topic_id pointing at missing topic → flagged."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            "INSERT INTO works (id, title) VALUES ('W-OK', 't')"
        )
        conn.execute(
            "INSERT INTO intake_candidates (id, title, status, ingested_work_id, collection_topic_id) "
            "VALUES ('C-1', 't', 'ingested', 'W-OK', 'TOPIC-GONE')"
        )
        conn.commit()
        conn.close()
        result = self._run()
        types = [d["type"] for d in result.dangling_references]
        self.assertIn("intake_candidates.collection_topic_id", types)

    def test_clean_db_has_no_dangling_references(self):
        """A consistent DB (child → existing parent) → no dangling refs."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("INSERT INTO works (id, title) VALUES ('W-OK', 't')")
        conn.execute("INSERT INTO collection_topics (id, label) VALUES ('T-OK', 'lbl')")
        conn.execute(
            "INSERT INTO source_files (id, work_id, content_sha256, source_path, "
            "relative_source_path) VALUES ('SF-1', 'W-OK', 'sha', ?, ?)",
            (str(self.root / "x.pdf"), "works/W-OK/source/x.pdf"),
        )
        conn.execute(
            "INSERT INTO intake_candidates (id, title, status, ingested_work_id, collection_topic_id) "
            "VALUES ('C-1', 't', 'ingested', 'W-OK', 'T-OK')"
        )
        conn.commit()
        conn.close()
        result = self._run()
        self.assertEqual(result.dangling_references, [])

    def test_dangling_flags_has_issues_and_summary(self):
        """Dangling refs should make has_issues() True and appear in summary()."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            "INSERT INTO source_files (id, work_id, content_sha256, source_path, "
            "relative_source_path) VALUES ('SF-1', 'W-GONE', 'sha', ?, ?)",
            (str(self.root / "x.pdf"), "works/W-GONE/source/x.pdf"),
        )
        conn.commit()
        conn.close()
        result = self._run()
        self.assertTrue(result.has_issues())
        self.assertEqual(result.summary()["dangling_references"], 1)


if __name__ == "__main__":
    unittest.main()
