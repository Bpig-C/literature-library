"""Tests for P1-02: quarantine/restore path handling fixes.

Uses temp DB + temp file system. Never touches real literature.sqlite.
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
from api.quarantine import RESTORE_STATE_CODE


@pytest.fixture
def restore_fixture(monkeypatch):
    root, db = _make_temp_library()
    pdf = root / 'works/W-state/source/paper.pdf'
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b'%PDF synthetic state')
    conn = _conn(db)
    conn.execute("INSERT INTO works(id,title,read_status) VALUES ('W-state','Synthetic','reading')")
    conn.execute("INSERT INTO source_files(id,work_id,content_sha256,original_name,source_path,relative_source_path,status) VALUES ('SF-state','W-state','synthetic','paper.pdf',?,'works/W-state/source/paper.pdf','active')", (str(pdf),))
    conn.commit();conn.close()
    monkeypatch.setattr('api.routes.works.get_conn', lambda: _conn(db))
    monkeypatch.setattr('api.routes.works.LIBRARY_ROOT', root)
    yield root, db, pdf, TestClient(app)
    assert root.name.startswith('litlib_qr_test_')
    shutil.rmtree(root)


@pytest.mark.parametrize('state', ['read','reading','unread'])
def test_restore_preserves_state_and_repeated_actions(restore_fixture, state):
    root, db, pdf, client = restore_fixture
    c = _conn(db);c.execute('UPDATE works SET read_status=?', (state,));c.commit();c.close()
    first = client.post('/api/works/W-state/quarantine', json={})
    assert first.status_code == 200, first.text
    c = _conn(db);saved = c.execute('SELECT reason FROM work_codes WHERE code=?', (RESTORE_STATE_CODE,)).fetchone()[0];c.close()
    second = client.post('/api/works/W-state/quarantine', json={})
    assert second.status_code == 200 and second.json()['moved_files'] == []
    c = _conn(db);assert c.execute('SELECT reason FROM work_codes WHERE code=?', (RESTORE_STATE_CODE,)).fetchone()[0] == saved;c.close()
    restored = client.post('/api/works/W-state/restore')
    assert restored.status_code == 200, restored.text
    assert restored.json()['read_status'] == state
    assert restored.json()['read_status_basis'] == 'recorded_before_quarantine'
    assert pdf.read_bytes() == b'%PDF synthetic state'
    again = client.post('/api/works/W-state/restore')
    assert again.status_code == 200 and again.json()['moved_files'] == []
    assert again.json()['read_status'] == state
    c = _conn(db);assert c.execute('SELECT status FROM source_files').fetchone()[0] == 'active';assert c.execute('SELECT COUNT(*) FROM work_codes WHERE code=?', (RESTORE_STATE_CODE,)).fetchone()[0] == 0;c.close()


def test_historical_restore_explains_unknown_state(restore_fixture):
    root, db, pdf, client = restore_fixture
    assert client.post('/api/works/W-state/quarantine', json={}).status_code == 200
    c = _conn(db);c.execute('DELETE FROM work_codes WHERE code=?', (RESTORE_STATE_CODE,));c.commit();c.close()
    response = client.post('/api/works/W-state/restore')
    assert response.status_code == 200
    assert response.json()['read_status'] == 'unread'
    assert response.json()['read_status_basis'] == 'legacy_default_unread'
    assert response.json()['warning']


def test_corrupt_saved_state_refuses_restore_without_moving(restore_fixture):
    root, db, pdf, client = restore_fixture
    assert client.post('/api/works/W-state/quarantine', json={}).status_code == 200
    c = _conn(db);c.execute('UPDATE work_codes SET reason=? WHERE code=?', ('not-json', RESTORE_STATE_CODE));c.commit();path = Path(c.execute('SELECT source_path FROM source_files').fetchone()[0]);c.close()
    assert client.post('/api/works/W-state/restore').status_code == 409
    assert path.read_bytes() == b'%PDF synthetic state'
    assert not pdf.exists()


@pytest.mark.parametrize('action', ['quarantine','restore'])
def test_simultaneous_actions_are_idempotent(restore_fixture, monkeypatch, action):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    import time
    import api.quarantine as nucleus
    root, db, pdf, client = restore_fixture
    if action == 'restore':
        assert client.post('/api/works/W-state/quarantine', json={}).status_code == 200
    original = nucleus.shutil.move
    def slow_move(*args, **kwargs):
        time.sleep(.05)
        return original(*args, **kwargs)
    monkeypatch.setattr(nucleus.shutil, 'move', slow_move)
    start = Barrier(2)
    def request(_):
        start.wait(timeout=3)
        return client.post('/api/works/W-state/'+action, json={})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(request, range(2)))
    assert [r.status_code for r in responses] == [200, 200]
    assert sorted(len(r.json()['moved_files']) for r in responses) == [0, 1]
    c = _conn(db)
    assert c.execute('SELECT read_status FROM works').fetchone()[0] == ('quarantined' if action == 'quarantine' else 'reading')
    source = c.execute('SELECT source_path,status FROM source_files').fetchone()
    assert source['status'] == ('quarantined' if action == 'quarantine' else 'active')
    assert Path(source['source_path']).read_bytes() == b'%PDF synthetic state'
    c.close()


def _make_temp_library():
    """Create a minimal temp library with DB + works dir."""
    root = Path(tempfile.mkdtemp(prefix="litlib_qr_test_"))
    db_path = root / "literature.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    # Minimal schema
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


def _conn(db_path):
    c = sqlite3.connect(str(db_path))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


class TestSafeDestName(unittest.TestCase):
    def test_original_name_present(self):
        from api.routes.works import _safe_dest_name
        row = {"original_name": "paper.pdf"}
        self.assertEqual(_safe_dest_name(row, "/some/path/file.pdf"), "paper.pdf")

    def test_original_name_none(self):
        from api.routes.works import _safe_dest_name
        row = {"original_name": None}
        self.assertEqual(_safe_dest_name(row, "/some/path/file.pdf"), "file.pdf")

    def test_original_name_empty(self):
        from api.routes.works import _safe_dest_name
        row = {"original_name": ""}
        self.assertEqual(_safe_dest_name(row, "/some/path/file.pdf"), "file.pdf")

    def test_original_name_dotdot_traversal_rejected(self):
        from api.routes.works import _safe_dest_name
        row = {"original_name": "../evil.pdf"}
        with self.assertRaises(Exception) as ctx:
            _safe_dest_name(row, "/some/path/file.pdf")
        self.assertIn("422", str(ctx.exception.status_code)
                      if hasattr(ctx.exception, 'status_code') else str(ctx.exception))

    def test_original_name_absolute_path_rejected(self):
        from api.routes.works import _safe_dest_name, HTTPException
        row = {"original_name": "C:\\tmp\\evil.pdf"}
        with self.assertRaises(HTTPException) as ctx:
            _safe_dest_name(row, "/some/path/file.pdf")
        self.assertEqual(ctx.exception.status_code, 422)

    def test_original_name_dotdot_slash_rejected(self):
        from api.routes.works import _safe_dest_name, HTTPException
        row = {"original_name": "../../etc/passwd"}
        with self.assertRaises(HTTPException) as ctx:
            _safe_dest_name(row, "/some/path/file.pdf")
        self.assertEqual(ctx.exception.status_code, 422)

    def test_original_name_backslash_traversal_rejected(self):
        from api.routes.works import _safe_dest_name, HTTPException
        row = {"original_name": "..\\..\\windows\\system32\\config\\sam"}
        with self.assertRaises(HTTPException) as ctx:
            _safe_dest_name(row, "/some/path/file.pdf")
        self.assertEqual(ctx.exception.status_code, 422)

    def test_original_name_just_dotdot_rejected(self):
        from api.routes.works import _safe_dest_name, HTTPException
        row = {"original_name": ".."}
        with self.assertRaises(HTTPException) as ctx:
            _safe_dest_name(row, "/some/path/file.pdf")
        self.assertEqual(ctx.exception.status_code, 422)


class TestQuarantinePathHandling(unittest.TestCase):
    """P1-02: Quarantine must not crash when original_name is None,
    and DB path must match actual moved file path."""

    def setUp(self):
        self.root, self.db_path = _make_temp_library()
        self.work_dir = self.root / "works" / "W-test-001" / "source"
        self.work_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _get_conn(self):
        return _conn(self.db_path)

    def test_quarantine_null_original_name(self):
        """original_name=NULL should not cause 500; DB path matches actual file."""
        # Create a source file
        pdf = self.work_dir / "arXiv-2501.12345.pdf"
        pdf.write_bytes(b"%PDF fake content")

        conn = self._get_conn()
        conn.execute(
            "INSERT INTO works (id, title, read_status) VALUES (?, ?, ?)",
            ("W-test-001", "Test Paper", "unread"),
        )
        conn.execute(
            """INSERT INTO source_files
               (id, work_id, content_sha256, original_name, source_path,
                relative_source_path, file_size, file_ext, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("SF-test-00001", "W-test-001", "abc123", None, str(pdf),
             "works/W-test-001/source/arXiv-2501.12345.pdf", 100, ".pdf", "active"),
        )
        conn.commit()
        conn.close()

        # Patch get_conn and LIBRARY_ROOT
        def _test_get_conn():
            return _conn(self.db_path)

        with patch("api.routes.works.get_conn", _test_get_conn), \
             patch("api.routes.works.LIBRARY_ROOT", self.root):
            from api.main import app
            client = TestClient(app)
            resp = client.post("/api/works/W-test-001/quarantine",
                               json={"reason": "test"})

        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertTrue(data["ok"])

        # Verify file was moved
        quarantine_dir = self.root / "_quarantine" / "W-test-001"
        moved_files = list(quarantine_dir.glob("*"))
        self.assertEqual(len(moved_files), 1)

        # Verify DB path matches actual file path
        conn = self._get_conn()
        sf = conn.execute("SELECT source_path FROM source_files WHERE id = 'SF-test-00001'").fetchone()
        conn.close()
        self.assertTrue(Path(sf["source_path"]).exists(),
                        f"DB path {sf['source_path']} does not exist on disk")
        self.assertIn("_quarantine", sf["source_path"])

    def test_quarantine_original_name_differs_from_source(self):
        """original_name != basename(source_path) → file moves correctly, DB matches."""
        pdf = self.work_dir / "some-random-filename.pdf"
        pdf.write_bytes(b"%PDF fake content")

        conn = self._get_conn()
        conn.execute(
            "INSERT INTO works (id, title, read_status) VALUES (?, ?, ?)",
            ("W-test-001", "Test Paper", "unread"),
        )
        conn.execute(
            """INSERT INTO source_files
               (id, work_id, content_sha256, original_name, source_path,
                relative_source_path, file_size, file_ext, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("SF-test-00001", "W-test-001", "abc123", "Original Paper Title.pdf",
             str(pdf), "works/W-test-001/source/some-random-filename.pdf",
             100, ".pdf", "active"),
        )
        conn.commit()
        conn.close()

        def _test_get_conn():
            return _conn(self.db_path)

        with patch("api.routes.works.get_conn", _test_get_conn), \
             patch("api.routes.works.LIBRARY_ROOT", self.root):
            from api.main import app
            client = TestClient(app)
            resp = client.post("/api/works/W-test-001/quarantine",
                               json={"reason": "test"})

        self.assertEqual(resp.status_code, 200, resp.text)

        # Verify file moved with original_name
        quarantine_dir = self.root / "_quarantine" / "W-test-001"
        moved = list(quarantine_dir.glob("*"))
        self.assertEqual(len(moved), 1)
        self.assertEqual(moved[0].name, "Original Paper Title.pdf")

        # Verify DB path matches actual file
        conn = self._get_conn()
        sf = conn.execute("SELECT source_path FROM source_files WHERE id = 'SF-test-00001'").fetchone()
        conn.close()
        self.assertTrue(Path(sf["source_path"]).exists())
        self.assertIn("Original Paper Title.pdf", sf["source_path"])

    def test_quarantine_missing_source_file_returns_error(self):
        """Missing source file → returns error, DB not partially updated."""
        pdf = self.work_dir / "nonexistent.pdf"
        # Don't create the file

        conn = self._get_conn()
        conn.execute(
            "INSERT INTO works (id, title, read_status) VALUES (?, ?, ?)",
            ("W-test-001", "Test Paper", "unread"),
        )
        conn.execute(
            """INSERT INTO source_files
               (id, work_id, content_sha256, original_name, source_path,
                relative_source_path, file_size, file_ext, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("SF-test-00001", "W-test-001", "abc123", "nonexistent.pdf",
             str(pdf), "works/W-test-001/source/nonexistent.pdf",
             100, ".pdf", "active"),
        )
        conn.commit()
        conn.close()

        def _test_get_conn():
            return _conn(self.db_path)

        with patch("api.routes.works.get_conn", _test_get_conn), \
             patch("api.routes.works.LIBRARY_ROOT", self.root):
            from api.main import app
            client = TestClient(app)
            resp = client.post("/api/works/W-test-001/quarantine",
                               json={"reason": "test"})

        self.assertEqual(resp.status_code, 409)
        self.assertIn("missing_source_files", resp.text)

        # Verify DB NOT updated (read_status still unread)
        conn = self._get_conn()
        w = conn.execute("SELECT read_status FROM works WHERE id = 'W-test-001'").fetchone()
        conn.close()
        self.assertEqual(w["read_status"], "unread")

    def test_quarantine_dotdot_original_name_rejected(self):
        """original_name with path traversal must be rejected (422), not escape quarantine dir."""
        pdf = self.work_dir / "normal.pdf"
        pdf.write_bytes(b"%PDF fake content")

        conn = self._get_conn()
        conn.execute(
            "INSERT INTO works (id, title, read_status) VALUES (?, ?, ?)",
            ("W-test-001", "Test Paper", "unread"),
        )
        conn.execute(
            """INSERT INTO source_files
               (id, work_id, content_sha256, original_name, source_path,
                relative_source_path, file_size, file_ext, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("SF-test-00001", "W-test-001", "abc123", "../evil.pdf", str(pdf),
             "works/W-test-001/source/normal.pdf", 100, ".pdf", "active"),
        )
        conn.commit()
        conn.close()

        def _test_get_conn():
            return _conn(self.db_path)

        with patch("api.routes.works.get_conn", _test_get_conn), \
             patch("api.routes.works.LIBRARY_ROOT", self.root):
            from api.main import app
            client = TestClient(app)
            resp = client.post("/api/works/W-test-001/quarantine",
                               json={"reason": "test"})

        # Should reject, not move file outside quarantine
        self.assertEqual(resp.status_code, 422, resp.text)
        self.assertIn("Invalid filename", resp.text)

        # Verify file NOT moved
        self.assertTrue(pdf.exists(), "Source file should not have been moved")

        # Verify DB NOT updated
        conn = self._get_conn()
        w = conn.execute("SELECT read_status FROM works WHERE id = 'W-test-001'").fetchone()
        conn.close()
        self.assertEqual(w["read_status"], "unread")

    def test_quarantine_absolute_original_name_rejected(self):
        """original_name that is an absolute path must be rejected."""
        pdf = self.work_dir / "normal.pdf"
        pdf.write_bytes(b"%PDF fake content")

        conn = self._get_conn()
        conn.execute(
            "INSERT INTO works (id, title, read_status) VALUES (?, ?, ?)",
            ("W-test-001", "Test Paper", "unread"),
        )
        conn.execute(
            """INSERT INTO source_files
               (id, work_id, content_sha256, original_name, source_path,
                relative_source_path, file_size, file_ext, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("SF-test-00001", "W-test-001", "abc123", "C:\\tmp\\evil.pdf", str(pdf),
             "works/W-test-001/source/normal.pdf", 100, ".pdf", "active"),
        )
        conn.commit()
        conn.close()

        def _test_get_conn():
            return _conn(self.db_path)

        with patch("api.routes.works.get_conn", _test_get_conn), \
             patch("api.routes.works.LIBRARY_ROOT", self.root):
            from api.main import app
            client = TestClient(app)
            resp = client.post("/api/works/W-test-001/quarantine",
                               json={"reason": "test"})

        self.assertEqual(resp.status_code, 422, resp.text)
        self.assertTrue(pdf.exists(), "Source file should not have been moved")


class TestRestorePathHandling(unittest.TestCase):
    """P1-02: Restore must use safe dest name, handle missing files."""

    def setUp(self):
        self.root, self.db_path = _make_temp_library()
        self.quarantine_dir = self.root / "_quarantine" / "W-test-001"
        self.quarantine_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _get_conn(self):
        return _conn(self.db_path)

    def test_restore_null_original_name(self):
        """Restore with original_name=NULL works, DB matches actual path."""
        qfile = self.quarantine_dir / "paper.pdf"
        qfile.write_bytes(b"%PDF fake")

        conn = self._get_conn()
        conn.execute(
            "INSERT INTO works (id, title, read_status) VALUES (?, ?, ?)",
            ("W-test-001", "Test Paper", "quarantined"),
        )
        conn.execute(
            """INSERT INTO source_files
               (id, work_id, content_sha256, original_name, source_path,
                relative_source_path, file_size, file_ext, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("SF-test-00001", "W-test-001", "abc123", None, str(qfile),
             "_quarantine/W-test-001/paper.pdf", 100, ".pdf", "active"),
        )
        conn.commit()
        conn.close()

        def _test_get_conn():
            return _conn(self.db_path)

        with patch("api.routes.works.get_conn", _test_get_conn), \
             patch("api.routes.works.LIBRARY_ROOT", self.root):
            from api.main import app
            client = TestClient(app)
            resp = client.post("/api/works/W-test-001/restore")

        self.assertEqual(resp.status_code, 200, resp.text)

        # Verify file moved back to works dir
        work_dir = self.root / "works" / "W-test-001" / "source"
        restored = list(work_dir.glob("*"))
        self.assertEqual(len(restored), 1)

        # Verify DB path matches
        conn = self._get_conn()
        sf = conn.execute("SELECT source_path FROM source_files WHERE id = 'SF-test-00001'").fetchone()
        conn.close()
        self.assertTrue(Path(sf["source_path"]).exists())
        self.assertIn(str(Path("works/W-test-001/source")), sf["source_path"])

    def test_restore_original_name_differs_from_source(self):
        """Restore uses original_name, not src.name, for dest path."""
        qfile = self.quarantine_dir / "Original Paper Title.pdf"
        qfile.write_bytes(b"%PDF fake")

        conn = self._get_conn()
        conn.execute(
            "INSERT INTO works (id, title, read_status) VALUES (?, ?, ?)",
            ("W-test-001", "Test Paper", "quarantined"),
        )
        conn.execute(
            """INSERT INTO source_files
               (id, work_id, content_sha256, original_name, source_path,
                relative_source_path, file_size, file_ext, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("SF-test-00001", "W-test-001", "abc123", "Original Paper Title.pdf",
             str(qfile), "_quarantine/W-test-001/Original Paper Title.pdf",
             100, ".pdf", "active"),
        )
        conn.commit()
        conn.close()

        def _test_get_conn():
            return _conn(self.db_path)

        with patch("api.routes.works.get_conn", _test_get_conn), \
             patch("api.routes.works.LIBRARY_ROOT", self.root):
            from api.main import app
            client = TestClient(app)
            resp = client.post("/api/works/W-test-001/restore")

        self.assertEqual(resp.status_code, 200, resp.text)

        work_dir = self.root / "works" / "W-test-001" / "source"
        restored = list(work_dir.glob("*"))
        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0].name, "Original Paper Title.pdf")

    def test_restore_missing_source_returns_error(self):
        """Missing quarantine file → error, DB not partially updated."""
        qfile = self.quarantine_dir / "gone.pdf"
        # Don't create file

        conn = self._get_conn()
        conn.execute(
            "INSERT INTO works (id, title, read_status) VALUES (?, ?, ?)",
            ("W-test-001", "Test Paper", "quarantined"),
        )
        conn.execute(
            """INSERT INTO source_files
               (id, work_id, content_sha256, original_name, source_path,
                relative_source_path, file_size, file_ext, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("SF-test-00001", "W-test-001", "abc123", "gone.pdf",
             str(qfile), "_quarantine/W-test-001/gone.pdf", 100, ".pdf", "active"),
        )
        conn.commit()
        conn.close()

        def _test_get_conn():
            return _conn(self.db_path)

        with patch("api.routes.works.get_conn", _test_get_conn), \
             patch("api.routes.works.LIBRARY_ROOT", self.root):
            from api.main import app
            client = TestClient(app)
            resp = client.post("/api/works/W-test-001/restore")

        self.assertEqual(resp.status_code, 409)

        # DB unchanged
        conn = self._get_conn()
        w = conn.execute("SELECT read_status FROM works WHERE id = 'W-test-001'").fetchone()
        conn.close()
        self.assertEqual(w["read_status"], "quarantined")


if __name__ == "__main__":
    unittest.main()
