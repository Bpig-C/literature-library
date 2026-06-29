"""Tests for P1-05: healthcheck_library.py detects orphan/phantom files.

Uses temp DB + temp file system. Never touches real literature.sqlite.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.literature_ingest import ensure_core_schema
from scripts.healthcheck_library import run_healthcheck


def _make_temp_library(*, with_works: bool = True):
    root = Path(tempfile.mkdtemp(prefix="litlib_hc_test_"))
    db_path = root / "literature.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    ensure_core_schema(conn)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS work_codes (
            work_id TEXT, source_file_id TEXT, code TEXT, reason TEXT,
            created_at TEXT, UNIQUE(work_id, code)
        );
    """)
    if with_works:
        # Add a work and source file
        conn.execute(
            "INSERT INTO works (id, title, read_status) VALUES (?, ?, ?)",
            ("W-test-001", "Test Paper", "unread"),
        )
        source_dir = root / "works" / "W-test-001" / "source"
        source_dir.mkdir(parents=True)
        pdf = source_dir / "paper.pdf"
        pdf.write_bytes(b"%PDF fake")
        conn.execute(
            """INSERT INTO source_files
               (id, work_id, content_sha256, original_name, source_path,
                relative_source_path, file_size, file_ext, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("SF-test-00001", "W-test-001", "abc123", "paper.pdf",
             str(pdf), "works/W-test-001/source/paper.pdf", 100, ".pdf", "active"),
        )
    conn.commit()
    conn.close()
    return root, db_path


class TestHealthcheckOrphanFiles(unittest.TestCase):
    """P1-05: Healthcheck detects files on disk not in DB."""

    def test_detects_orphan_file(self):
        root, db_path = _make_temp_library()
        try:
            # Add a file on disk not tracked in DB
            orphan = root / "works" / "W-test-001" / "source" / "orphan.pdf"
            orphan.write_bytes(b"%PDF orphan")

            result = run_healthcheck(root)
            self.assertTrue(result.has_issues())
            self.assertEqual(len(result.orphan_files), 1)
            self.assertIn("orphan.pdf", result.orphan_files[0])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_no_orphan_when_all_tracked(self):
        root, db_path = _make_temp_library()
        try:
            result = run_healthcheck(root)
            self.assertEqual(len(result.orphan_files), 0)
        finally:
            shutil.rmtree(root, ignore_errors=True)


class TestHealthcheckPhantomEntries(unittest.TestCase):
    """P1-05: Healthcheck detects DB entries pointing to missing files."""

    def test_detects_phantom_db_entry(self):
        root, db_path = _make_temp_library()
        try:
            # Delete the file but leave DB entry
            pdf = root / "works" / "W-test-001" / "source" / "paper.pdf"
            pdf.unlink()

            result = run_healthcheck(root)
            self.assertTrue(result.has_issues())
            self.assertEqual(len(result.phantom_db_entries), 1)
            self.assertIn("paper.pdf", result.phantom_db_entries[0])
        finally:
            shutil.rmtree(root, ignore_errors=True)


class TestHealthcheckWorkDirsWithoutDB(unittest.TestCase):
    """P1-05: Healthcheck detects work dirs without DB works."""

    def test_detects_untracked_work_dir(self):
        root, db_path = _make_temp_library()
        try:
            # Create a work dir without DB entry
            extra_dir = root / "works" / "W-orphan-001" / "source"
            extra_dir.mkdir(parents=True)
            (extra_dir / "file.pdf").write_bytes(b"%PDF")

            result = run_healthcheck(root)
            self.assertTrue(result.has_issues())
            self.assertIn("W-orphan-001", result.work_dirs_without_db)
        finally:
            shutil.rmtree(root, ignore_errors=True)


class TestHealthcheckReadOnly(unittest.TestCase):
    """P1-05: Without --apply, no files/DB modified."""

    def test_read_only_does_not_modify(self):
        root, db_path = _make_temp_library()
        try:
            orphan = root / "works" / "W-test-001" / "source" / "orphan.pdf"
            orphan.write_bytes(b"%PDF orphan")

            result = run_healthcheck(root, apply=False)

            # Orphan file should still be there
            self.assertTrue(orphan.exists(), "Orphan file should not be moved without --apply")
            self.assertEqual(len(result.applied_fixes), 0)
        finally:
            shutil.rmtree(root, ignore_errors=True)


class TestHealthcheckApplyFixes(unittest.TestCase):
    """P1-05: With --apply, orphan files are quarantined."""

    def test_apply_moves_orphan_to_quarantine(self):
        root, db_path = _make_temp_library()
        try:
            orphan = root / "works" / "W-test-001" / "source" / "orphan.pdf"
            orphan.write_bytes(b"%PDF orphan")

            result = run_healthcheck(root, apply=True)

            # Orphan should be moved
            self.assertFalse(orphan.exists(), "Orphan should be moved")
            self.assertGreater(len(result.applied_fixes), 0)

            # Should be in quarantine
            quarantine_dir = root / "_quarantine" / "_healthcheck_orphans"
            self.assertTrue(quarantine_dir.exists())
            moved = list(quarantine_dir.glob("orphan*"))
            self.assertGreater(len(moved), 0)
        finally:
            shutil.rmtree(root, ignore_errors=True)


class TestHealthcheckStatusInconsistencies(unittest.TestCase):
    """P2-06: Healthcheck detects status inconsistencies."""

    def test_quarantined_work_active_source(self):
        """quarantined work with active source_files should be flagged."""
        root, db_path = _make_temp_library()
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            conn.execute("UPDATE works SET read_status = 'quarantined' WHERE id = 'W-test-001'")
            conn.commit()
            conn.close()

            result = run_healthcheck(root)
            found = [i for i in result.status_inconsistencies
                     if i["type"] == "quarantined_work_active_source"]
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["work_id"], "W-test-001")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_ingested_no_work_id(self):
        """status=ingested but no ingested_work_id should be flagged."""
        root, db_path = _make_temp_library()
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS intake_candidates (
                    id TEXT PRIMARY KEY, source_type TEXT, url_canonical TEXT,
                    title TEXT, arxiv_id TEXT, doi TEXT, resolution TEXT,
                    status TEXT DEFAULT 'pending', review_status TEXT DEFAULT 'pending',
                    ingested_work_id TEXT, raw_meta TEXT, collection_topic_id TEXT,
                    collected_at TEXT
                );
            """)
            conn.execute(
                """INSERT INTO intake_candidates
                   (id, source_type, url_canonical, title, status, ingested_work_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                ("IC-test-01", "arxiv", "https://arxiv.org/abs/2501.00001",
                 "Test Paper", "ingested", None),
            )
            conn.commit()
            conn.close()

            result = run_healthcheck(root)
            found = [i for i in result.status_inconsistencies
                     if i["type"] == "ingested_no_work_id"]
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["candidate_id"], "IC-test-01")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_work_id_but_not_ingested(self):
        """ingested_work_id set but status != ingested should be flagged."""
        root, db_path = _make_temp_library()
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS intake_candidates (
                    id TEXT PRIMARY KEY, source_type TEXT, url_canonical TEXT,
                    title TEXT, arxiv_id TEXT, doi TEXT, resolution TEXT,
                    status TEXT DEFAULT 'pending', review_status TEXT DEFAULT 'pending',
                    ingested_work_id TEXT, raw_meta TEXT, collection_topic_id TEXT,
                    collected_at TEXT
                );
            """)
            conn.execute(
                """INSERT INTO intake_candidates
                   (id, source_type, url_canonical, title, status, ingested_work_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                ("IC-test-02", "arxiv", "https://arxiv.org/abs/2501.00002",
                 "Test Paper 2", "pending", "W-some-work"),
            )
            conn.commit()
            conn.close()

            result = run_healthcheck(root)
            found = [i for i in result.status_inconsistencies
                     if i["type"] == "work_id_but_not_ingested"]
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["candidate_id"], "IC-test-02")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_consistent_state_no_issues(self):
        """No issues when everything is consistent."""
        root, db_path = _make_temp_library()
        try:
            result = run_healthcheck(root)
            self.assertFalse(result.has_issues())
            self.assertEqual(result.summary()["orphan_files"], 0)
            self.assertEqual(result.summary()["phantom_db_entries"], 0)
            self.assertEqual(result.summary()["work_dirs_without_db"], 0)
            self.assertEqual(result.summary()["status_inconsistencies"], 0)
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
