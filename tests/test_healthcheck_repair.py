"""Tests for P2-POST-03 (repair quarantine status) and P2-POST-04 (phantom detection fix).

Uses temp DB + temp file system. Never touches real literature.sqlite.
"""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.healthcheck_library import run_healthcheck


def _make_temp_library():
    """Create a minimal temp library with DB + works dir."""
    root = Path(tempfile.mkdtemp(prefix="litlib_hc_test_"))
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
    """)
    conn.close()
    return root, db_path


class TestPhantomDetection(unittest.TestCase):
    """P2-POST-04: phantom detection should use Path.exists(), not set comparison."""

    def setUp(self):
        self.root, self.db_path = _make_temp_library()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_quarantine_file_not_phantom(self):
        """DB source_path pointing to existing _quarantine file → NOT phantom."""
        quarantine_dir = self.root / "_quarantine" / "W-test-001"
        quarantine_dir.mkdir(parents=True)
        qfile = quarantine_dir / "paper.pdf"
        qfile.write_bytes(b"%PDF fake")

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("INSERT INTO works (id, title, read_status) VALUES ('W-test-001', 'T', 'quarantined')")
        conn.execute(
            "INSERT INTO source_files (id, work_id, content_sha256, original_name, source_path, "
            "relative_source_path, file_size, file_ext, status) "
            "VALUES ('SF-1', 'W-test-001', 'sha', 'paper.pdf', ?, ?, 100, '.pdf', 'quarantined')",
            (str(qfile), "_quarantine/W-test-001/paper.pdf"),
        )
        conn.commit()
        conn.close()

        result = run_healthcheck(self.root)
        self.assertEqual(result.phantom_db_entries, [],
                         "Existing quarantine file should NOT be phantom")

    def test_missing_file_is_phantom(self):
        """DB source_path pointing to non-existent file → IS phantom."""
        work_dir = self.root / "works" / "W-test-001" / "source"
        work_dir.mkdir(parents=True)
        fake_path = work_dir / "gone.pdf"
        # Don't create the file

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("INSERT INTO works (id, title, read_status) VALUES ('W-test-001', 'T', 'unread')")
        conn.execute(
            "INSERT INTO source_files (id, work_id, content_sha256, original_name, source_path, "
            "relative_source_path, file_size, file_ext, status) "
            "VALUES ('SF-1', 'W-test-001', 'sha', 'gone.pdf', ?, ?, 100, '.pdf', 'active')",
            (str(fake_path), "works/W-test-001/source/gone.pdf"),
        )
        conn.commit()
        conn.close()

        result = run_healthcheck(self.root)
        self.assertEqual(len(result.phantom_db_entries), 1)
        self.assertIn("gone.pdf", result.phantom_db_entries[0])


class TestStatusInconsistency(unittest.TestCase):
    """P2-POST-04: new status inconsistency categories."""

    def setUp(self):
        self.root, self.db_path = _make_temp_library()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_active_source_in_quarantine_detected(self):
        """active source pointing to _quarantine → status inconsistency."""
        quarantine_dir = self.root / "_quarantine" / "W-test-001"
        quarantine_dir.mkdir(parents=True)
        qfile = quarantine_dir / "paper.pdf"
        qfile.write_bytes(b"%PDF fake")

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("INSERT INTO works (id, title, read_status) VALUES ('W-test-001', 'T', 'quarantined')")
        conn.execute(
            "INSERT INTO source_files (id, work_id, content_sha256, original_name, source_path, "
            "relative_source_path, file_size, file_ext, status) "
            "VALUES ('SF-1', 'W-test-001', 'sha', 'paper.pdf', ?, ?, 100, '.pdf', 'active')",
            (str(qfile), "_quarantine/W-test-001/paper.pdf"),
        )
        conn.commit()
        conn.close()

        result = run_healthcheck(self.root)
        types = {inc["type"] for inc in result.status_inconsistencies}
        self.assertIn("active_source_in_quarantine", types)
        self.assertIn("quarantined_work_active_source", types)

    def test_quarantine_path_status_mismatch(self):
        """Path in _quarantine but status != 'quarantined' → mismatch."""
        quarantine_dir = self.root / "_quarantine" / "W-test-001"
        quarantine_dir.mkdir(parents=True)
        qfile = quarantine_dir / "paper.pdf"
        qfile.write_bytes(b"%PDF fake")

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("INSERT INTO works (id, title, read_status) VALUES ('W-test-001', 'T', 'quarantined')")
        conn.execute(
            "INSERT INTO source_files (id, work_id, content_sha256, original_name, source_path, "
            "relative_source_path, file_size, file_ext, status) "
            "VALUES ('SF-1', 'W-test-001', 'sha', 'paper.pdf', ?, ?, 100, '.pdf', 'archived')",
            (str(qfile), "_quarantine/W-test-001/paper.pdf"),
        )
        conn.commit()
        conn.close()

        result = run_healthcheck(self.root)
        types = {inc["type"] for inc in result.status_inconsistencies}
        self.assertIn("quarantine_path_status_mismatch", types)

    def test_active_source_outside_works_detected(self):
        """active source with path not under works/ or _quarantine/ → outside works."""
        other_dir = self.root / "somewhere" / "else"
        other_dir.mkdir(parents=True)
        f = other_dir / "paper.pdf"
        f.write_bytes(b"%PDF fake")

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("INSERT INTO works (id, title, read_status) VALUES ('W-test-001', 'T', 'unread')")
        conn.execute(
            "INSERT INTO source_files (id, work_id, content_sha256, original_name, source_path, "
            "relative_source_path, file_size, file_ext, status) "
            "VALUES ('SF-1', 'W-test-001', 'sha', 'paper.pdf', ?, ?, 100, '.pdf', 'active')",
            (str(f), "somewhere/else/paper.pdf"),
        )
        conn.commit()
        conn.close()

        result = run_healthcheck(self.root)
        types = {inc["type"] for inc in result.status_inconsistencies}
        self.assertIn("active_source_outside_works", types)

    def test_orphan_still_detected(self):
        """works/*/source/orphan.pdf not in DB → still reported as orphan."""
        work_dir = self.root / "works" / "W-test-001" / "source"
        work_dir.mkdir(parents=True)
        orphan = work_dir / "orphan.pdf"
        orphan.write_bytes(b"%PDF fake")

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("INSERT INTO works (id, title, read_status) VALUES ('W-test-001', 'T', 'unread')")
        conn.commit()
        conn.close()

        result = run_healthcheck(self.root)
        self.assertEqual(len(result.orphan_files), 1)
        self.assertIn("orphan.pdf", result.orphan_files[0])


class TestRepairQuarantineStatus(unittest.TestCase):
    """P2-POST-03: --repair-quarantine-status flag."""

    def setUp(self):
        self.root, self.db_path = _make_temp_library()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _seed_quarantined_work_with_active_source(self):
        work_dir = self.root / "works" / "W-test-001" / "source"
        work_dir.mkdir(parents=True)
        pdf = work_dir / "paper.pdf"
        pdf.write_bytes(b"%PDF fake")

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute(
            "INSERT INTO works (id, title, read_status) VALUES ('W-test-001', 'T', 'quarantined')"
        )
        conn.execute(
            "INSERT INTO source_files (id, work_id, content_sha256, original_name, source_path, "
            "relative_source_path, file_size, file_ext, status) "
            "VALUES ('SF-1', 'W-test-001', 'sha', 'paper.pdf', ?, ?, 100, '.pdf', 'active')",
            (str(pdf), "works/W-test-001/source/paper.pdf"),
        )
        conn.commit()
        conn.close()

    def test_healthcheck_detects_quarantined_active(self):
        """Healthcheck detects quarantined work with active source_files."""
        self._seed_quarantined_work_with_active_source()
        result = run_healthcheck(self.root)
        types = {inc["type"] for inc in result.status_inconsistencies}
        self.assertIn("quarantined_work_active_source", types)

    def test_repair_dry_run_shows_plan(self):
        """Repair dry-run shows plan without modifying DB."""
        self._seed_quarantined_work_with_active_source()
        result = run_healthcheck(self.root, repair_quarantine_status=True, dry_run=True)

        self.assertEqual(len(result.repair_plan), 1)
        plan = result.repair_plan[0]
        self.assertEqual(plan["source_file_id"], "SF-1")
        self.assertEqual(plan["current_status"], "active")
        self.assertEqual(plan["proposed_status"], "quarantined")
        self.assertEqual(result.applied_fixes, [], "Dry-run should NOT apply fixes")

        # Verify DB unchanged
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        sf = conn.execute("SELECT status FROM source_files WHERE id = 'SF-1'").fetchone()
        conn.close()
        self.assertEqual(sf["status"], "active")

    def test_repair_apply_updates_status(self):
        """Repair with --apply actually updates source_files.status."""
        self._seed_quarantined_work_with_active_source()
        result = run_healthcheck(
            self.root, repair_quarantine_status=True, dry_run=False
        )

        self.assertEqual(len(result.applied_fixes), 1)
        self.assertIn("active -> quarantined", result.applied_fixes[0])

        # Verify DB updated
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        sf = conn.execute(
            "SELECT status, archive_reason FROM source_files WHERE id = 'SF-1'"
        ).fetchone()
        conn.close()
        self.assertEqual(sf["status"], "quarantined")
        self.assertIn("auto-repair", sf["archive_reason"])

    def test_no_repair_needed(self):
        """When no quarantined+active mismatch, repair plan is empty."""
        # Insert a properly quarantined source
        work_dir = self.root / "works" / "W-test-001" / "source"
        work_dir.mkdir(parents=True)
        pdf = work_dir / "paper.pdf"
        pdf.write_bytes(b"%PDF fake")

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute(
            "INSERT INTO works (id, title, read_status) VALUES ('W-test-001', 'T', 'quarantined')"
        )
        conn.execute(
            "INSERT INTO source_files (id, work_id, content_sha256, original_name, source_path, "
            "relative_source_path, file_size, file_ext, status) "
            "VALUES ('SF-1', 'W-test-001', 'sha', 'paper.pdf', ?, ?, 100, '.pdf', 'quarantined')",
            (str(pdf), "works/W-test-001/source/paper.pdf"),
        )
        conn.commit()
        conn.close()

        result = run_healthcheck(self.root, repair_quarantine_status=True)
        self.assertEqual(result.repair_plan, [])


if __name__ == "__main__":
    unittest.main()
