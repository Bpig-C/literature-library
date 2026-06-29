"""P2-01 regression tests: files API path boundary enforcement.

Verifies that the /api/files endpoints reject paths outside LIBRARY_ROOT/works,
even when the database contains poisoned paths. Uses sample_db fixture.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.main import app


def _make_conn_factory(db_path):
    def _conn():
        c = sqlite3.connect(str(db_path))
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        return c
    return _conn


@pytest.fixture(autouse=True)
def _setup(sample_db, tmp_path):
    """Set up temp dir with works/ structure and patch routes + LIBRARY_ROOT."""
    works_dir = tmp_path / "works"
    works_dir.mkdir(parents=True, exist_ok=True)

    # Create test files
    (works_dir / "test_content.md").write_text("# Test Content", encoding="utf-8")
    (works_dir / "test.pdf").write_bytes(b"%PDF-1.4 test")

    # Create a file outside works/ for the attack vector
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir(parents=True, exist_ok=True)
    (outside_dir / "secret.txt").write_text("SECRET DATA", encoding="utf-8")

    # Write actual content_md_path and source_path into the sample DB
    conn = sqlite3.connect(str(sample_db))
    conn.row_factory = sqlite3.Row
    conn.execute(
        "UPDATE literature_parse_runs SET content_md_path = ?, status = 'succeeded' WHERE id = 'PR-001'",
        (str(works_dir / "test_content.md"),),
    )
    conn.execute(
        "UPDATE source_files SET source_path = ? WHERE id = 'SF-001'",
        (str(works_dir / "test.pdf"),),
    )
    # Reset content for re-runs
    conn.commit()
    conn.close()

    # Patch routes and LIBRARY_ROOT
    import api.routes.files as files_mod
    files_mod.LIBRARY_ROOT = tmp_path
    files_mod._WORKS_ROOT = (tmp_path / "works").resolve()

    factory = _make_conn_factory(sample_db)
    patches = [
        patch("api.routes.works.get_conn", factory),
        patch("api.routes.relations.get_conn", factory),
        patch("api.routes.duplicates.get_conn", factory),
        patch("api.routes.files.get_conn", factory),
        patch("api.routes.metadata.get_conn", factory),
        patch("api.routes.classification.get_conn", factory),
    ]
    for p in patches:
        p.start()
    yield {"outside_dir": outside_dir, "works_dir": works_dir, "sample_db": sample_db}
    for p in patches:
        p.stop()


client = TestClient(app)


def _set_parse_run_path(db_path, work_id: str, content_md_path: str):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(
        "UPDATE literature_parse_runs SET content_md_path = ?, status = 'succeeded' WHERE work_id = ?",
        (content_md_path, work_id),
    )
    conn.commit()
    conn.close()


def _set_source_file_path(db_path, work_id: str, source_path: str):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(
        "UPDATE source_files SET source_path = ? WHERE work_id = ?",
        (source_path, work_id),
    )
    conn.commit()
    conn.close()


class TestContentPathBoundary:
    """P2-01: /api/files/{work_id}/content must reject out-of-bounds paths."""

    def test_path_outside_library_returns_403(self, _setup):
        db_path = _setup["sample_db"]
        outside_path = str(_setup["outside_dir"] / "secret.txt")
        _set_parse_run_path(db_path, "W-sample-001", outside_path)
        resp = client.get("/api/files/W-sample-001/content")
        assert resp.status_code == 403
        assert "boundary" in resp.json().get("detail", "").lower()

    def test_path_with_dotdot_traversal_returns_403(self, _setup):
        db_path = _setup["sample_db"]
        works_dir = _setup["works_dir"]
        traversal_path = str((works_dir / ".." / "outside" / "secret.txt").resolve())
        _set_parse_run_path(db_path, "W-sample-001", traversal_path)
        resp = client.get("/api/files/W-sample-001/content")
        assert resp.status_code == 403

    def test_path_inside_works_returns_200(self, _setup):
        db_path = _setup["sample_db"]
        valid_path = str(_setup["works_dir"] / "test_content.md")
        _set_parse_run_path(db_path, "W-sample-001", valid_path)
        resp = client.get("/api/files/W-sample-001/content")
        assert resp.status_code == 200
        assert "Test Content" in resp.text

    def test_symlink_traversal_returns_403(self, _setup):
        db_path = _setup["sample_db"]
        works_dir = _setup["works_dir"]
        outside_dir = _setup["outside_dir"]
        link = works_dir / "evil_link.md"
        target = outside_dir / "secret.txt"
        if link.exists() or link.is_symlink():
            link.unlink()
        try:
            link.symlink_to(target)
            _set_parse_run_path(db_path, "W-sample-001", str(link))
            resp = client.get("/api/files/W-sample-001/content")
            assert resp.status_code == 403
        except OSError:
            pytest.skip("Symlink creation not supported on this platform")
        finally:
            if link.is_symlink():
                link.unlink()


class TestPdfPathBoundary:
    """P2-01: /api/files/{work_id}/pdf must reject out-of-bounds paths."""

    def test_path_outside_library_returns_403(self, _setup):
        db_path = _setup["sample_db"]
        outside_path = str(_setup["outside_dir"] / "secret.txt")
        _set_source_file_path(db_path, "W-sample-001", outside_path)
        resp = client.get("/api/files/W-sample-001/pdf")
        assert resp.status_code == 403
        assert "boundary" in resp.json().get("detail", "").lower()

    def test_path_with_dotdot_traversal_returns_403(self, _setup):
        db_path = _setup["sample_db"]
        works_dir = _setup["works_dir"]
        traversal_path = str((works_dir / ".." / "outside" / "secret.txt").resolve())
        _set_source_file_path(db_path, "W-sample-001", traversal_path)
        resp = client.get("/api/files/W-sample-001/pdf")
        assert resp.status_code == 403

    def test_path_inside_works_returns_200(self, _setup):
        db_path = _setup["sample_db"]
        valid_path = str(_setup["works_dir"] / "test.pdf")
        _set_source_file_path(db_path, "W-sample-001", valid_path)
        resp = client.get("/api/files/W-sample-001/pdf")
        assert resp.status_code == 200
