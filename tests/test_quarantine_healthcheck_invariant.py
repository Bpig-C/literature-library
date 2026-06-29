"""P1-01/P1-02 invariant: every quarantine/restore operation must leave the
library healthcheck clean (no status inconsistency, no phantom).

The drift bug: quarantine endpoints moved files into _quarantine/ and updated
source_path but never set source_files.status='quarantined'; restore never set
it back to 'active'. healthcheck treats "quarantined work + active source" and
"source in _quarantine but status != quarantined" as inconsistencies — so a
supported UI action could make a clean library unhealthy.

These tests drive the real routes (works / metadata / classification quarantine,
works restore) end-to-end on a temp library and assert run_healthcheck stays
clean afterward. They also pin the strict policy: a missing source file must 409
before any DB/filesystem change (no half-isolation).
"""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from scripts.healthcheck_library import run_healthcheck


def _make_temp_library():
    root = Path(tempfile.mkdtemp(prefix="litlib_qinv_"))
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
            content_md_path TEXT, extracted_json TEXT DEFAULT '{}',
            confidence_json TEXT DEFAULT '{}', applied INTEGER DEFAULT 0,
            review_status TEXT DEFAULT 'pending', review_note TEXT DEFAULT '',
            reviewed_at TEXT, review_source TEXT DEFAULT 'human',
            fix_action TEXT DEFAULT '', risk_level TEXT DEFAULT 'low',
            created_at TEXT
        );
        CREATE TABLE classification_extractions (
            id TEXT PRIMARY KEY, work_id TEXT, model_name TEXT,
            extracted_json TEXT DEFAULT '{}', confidence_json TEXT DEFAULT '{}',
            ambiguity_score INTEGER DEFAULT 0, review_status TEXT DEFAULT 'pending',
            review_note TEXT, reviewed_at TEXT, fix_action TEXT,
            applied INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT
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


def _seed(conn, root, work_id="W1", sf_id="SF1", with_disk_file=True):
    conn.execute("INSERT INTO works (id, title, read_status) VALUES (?, 'T', 'unread')", (work_id,))
    pdf = root / "works" / work_id / "source" / "paper.pdf"
    if with_disk_file:
        pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf.write_bytes(b"%PDF content")
    conn.execute(
        "INSERT INTO source_files (id, work_id, content_sha256, original_name, source_path, "
        "relative_source_path, file_size, file_ext, status) VALUES (?, ?, 'sha', 'paper.pdf', ?, ?, 100, '.pdf', 'active')",
        (sf_id, work_id, str(pdf), f"works/{work_id}/source/paper.pdf"),
    )
    conn.commit()
    return pdf


class TestQuarantineHealthcheckInvariant(unittest.TestCase):

    def setUp(self):
        self.root, self.db_path = _make_temp_library()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _client_and_conn(self):
        def _gc():
            return _conn(self.db_path)
        from api.main import app
        return TestClient(app), _gc

    def _assert_healthcheck_clean(self):
        hc = run_healthcheck(self.root, dry_run=True)
        self.assertFalse(hc.has_issues(),
                         f"healthcheck dirty after quarantine: status={hc.status_inconsistencies} "
                         f"phantom={hc.phantom_db_entries} orphan={hc.orphan_files}")

    def test_works_quarantine_keeps_healthcheck_clean(self):
        conn = _conn(self.db_path)
        _seed(conn, self.root)
        conn.close()
        client, gc = self._client_and_conn()
        with patch("api.routes.works.get_conn", gc), patch("api.routes.works.LIBRARY_ROOT", self.root):
            resp = client.post("/api/works/W1/quarantine", json={"reason": "bad_source"})
        self.assertEqual(resp.status_code, 200, resp.text)
        # source_files.status must be quarantined, not active
        conn = _conn(self.db_path)
        sf = conn.execute("SELECT status FROM source_files WHERE id='SF1'").fetchone()
        conn.close()
        self.assertEqual(sf["status"], "quarantined")
        self._assert_healthcheck_clean()

    def test_works_restore_keeps_healthcheck_clean(self):
        conn = _conn(self.db_path)
        _seed(conn, self.root)
        conn.close()
        client, gc = self._client_and_conn()
        with patch("api.routes.works.get_conn", gc), patch("api.routes.works.LIBRARY_ROOT", self.root):
            r1 = client.post("/api/works/W1/quarantine", json={"reason": "bad_source"})
            self.assertEqual(r1.status_code, 200, r1.text)
            r2 = client.post("/api/works/W1/restore")
            self.assertEqual(r2.status_code, 200, r2.text)
        conn = _conn(self.db_path)
        sf = conn.execute("SELECT status FROM source_files WHERE id='SF1'").fetchone()
        conn.close()
        self.assertEqual(sf["status"], "active")
        self._assert_healthcheck_clean()

    def test_metadata_quarantine_keeps_healthcheck_clean(self):
        conn = _conn(self.db_path)
        _seed(conn, self.root)
        conn.execute("INSERT INTO metadata_extractions (id, work_id, model_name, review_status) "
                     "VALUES ('ME1', 'W1', 'm', 'pending')")
        conn.commit()
        conn.close()
        client, gc = self._client_and_conn()
        with patch("api.routes.metadata.get_conn", gc), patch("api.routes.metadata.LIBRARY_ROOT", self.root):
            resp = client.post("/api/metadata/ME1/quarantine", json={"reason": "bad_source"})
        self.assertEqual(resp.status_code, 200, resp.text)
        conn = _conn(self.db_path)
        sf = conn.execute("SELECT status FROM source_files WHERE id='SF1'").fetchone()
        conn.close()
        self.assertEqual(sf["status"], "quarantined")
        self._assert_healthcheck_clean()

    def test_classification_quarantine_keeps_healthcheck_clean(self):
        conn = _conn(self.db_path)
        _seed(conn, self.root)
        conn.execute("INSERT INTO classification_extractions (id, work_id, model_name, review_status) "
                     "VALUES ('CE1', 'W1', 'm', 'pending')")
        conn.commit()
        conn.close()
        client, gc = self._client_and_conn()
        with patch("api.routes.classification.get_conn", gc), patch("api.routes.classification.LIBRARY_ROOT", self.root):
            resp = client.post("/api/classification/extractions/CE1/quarantine",
                               json={"reason": "bad_source"})
        self.assertEqual(resp.status_code, 200, resp.text)
        conn = _conn(self.db_path)
        sf = conn.execute("SELECT status FROM source_files WHERE id='SF1'").fetchone()
        conn.close()
        self.assertEqual(sf["status"], "quarantined")
        self._assert_healthcheck_clean()

    def test_works_quarantine_strict_409_on_missing_source(self):
        """Missing source file → 409 before any change (no half-isolation)."""
        conn = _conn(self.db_path)
        _seed(conn, self.root, with_disk_file=False)  # DB row but no file on disk
        conn.close()
        client, gc = self._client_and_conn()
        with patch("api.routes.works.get_conn", gc), patch("api.routes.works.LIBRARY_ROOT", self.root):
            resp = client.post("/api/works/W1/quarantine", json={"reason": "bad_source"})
        self.assertEqual(resp.status_code, 409, resp.text)
        # DB unchanged: work still unread, source still active (no half-isolation)
        conn = _conn(self.db_path)
        w = conn.execute("SELECT read_status FROM works WHERE id='W1'").fetchone()
        sf = conn.execute("SELECT status FROM source_files WHERE id='SF1'").fetchone()
        conn.close()
        self.assertEqual(w["read_status"], "unread")
        self.assertEqual(sf["status"], "active")


if __name__ == "__main__":
    unittest.main()
