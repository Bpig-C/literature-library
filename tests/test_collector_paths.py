"""P2-02 regression tests: collector resolve_pdf_path boundary enforcement.

Verifies that resolve_pdf_path rejects paths outside allowed library
subdirectories (_collector_cache, _inbox, works).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import api.db
from collector.paths import resolve_pdf_path


@pytest.fixture
def lib_root(tmp_path):
    """Set up a temporary library root with allowed subdirectories."""
    (tmp_path / "_collector_cache").mkdir()
    (tmp_path / "_inbox").mkdir()
    (tmp_path / "works").mkdir()
    # Create a test PDF in _collector_cache
    (tmp_path / "_collector_cache" / "test.pdf").write_bytes(b"%PDF-1.4 test")
    # Create a file outside allowed dirs
    (tmp_path / "other_dir").mkdir()
    (tmp_path / "other_dir" / "outside.pdf").write_bytes(b"%PDF-1.4 outside")
    return tmp_path


class TestResolvePdfPathBoundary:
    """P2-02: resolve_pdf_path must reject out-of-bounds paths."""

    def test_relative_path_in_collector_cache_succeeds(self, lib_root, monkeypatch):
        monkeypatch.setattr(api.db, "LIBRARY_ROOT", lib_root)
        result = resolve_pdf_path("_collector_cache/test.pdf")
        assert result == (lib_root / "_collector_cache" / "test.pdf").resolve()

    def test_relative_path_in_inbox_succeeds(self, lib_root, monkeypatch):
        monkeypatch.setattr(api.db, "LIBRARY_ROOT", lib_root)
        (lib_root / "_inbox" / "doc.pdf").write_bytes(b"%PDF")
        result = resolve_pdf_path("_inbox/doc.pdf")
        assert result == (lib_root / "_inbox" / "doc.pdf").resolve()

    def test_relative_path_in_works_succeeds(self, lib_root, monkeypatch):
        monkeypatch.setattr(api.db, "LIBRARY_ROOT", lib_root)
        (lib_root / "works" / "W-1" / "paper.pdf").parent.mkdir(parents=True)
        (lib_root / "works" / "W-1" / "paper.pdf").write_bytes(b"%PDF")
        result = resolve_pdf_path("works/W-1/paper.pdf")
        assert result == (lib_root / "works" / "W-1" / "paper.pdf").resolve()

    def test_relative_dotdot_traversal_raises(self, lib_root, monkeypatch):
        monkeypatch.setattr(api.db, "LIBRARY_ROOT", lib_root)
        with pytest.raises(ValueError, match="(outside library boundary|allowed subdirectory)"):
            resolve_pdf_path("../outside/secret.pdf")

    def test_relative_dotdot_escape_raises(self, lib_root, monkeypatch):
        monkeypatch.setattr(api.db, "LIBRARY_ROOT", lib_root)
        with pytest.raises(ValueError, match="(outside library boundary|allowed subdirectory)"):
            resolve_pdf_path("_collector_cache/../../etc/passwd")

    def test_absolute_path_outside_library_raises(self, lib_root, monkeypatch):
        monkeypatch.setattr(api.db, "LIBRARY_ROOT", lib_root)
        with pytest.raises(ValueError, match="outside library boundary"):
            resolve_pdf_path("/tmp/evil.pdf")

    def test_absolute_path_inside_collector_cache_succeeds(self, lib_root, monkeypatch):
        monkeypatch.setattr(api.db, "LIBRARY_ROOT", lib_root)
        abs_path = str((lib_root / "_collector_cache" / "test.pdf").resolve())
        result = resolve_pdf_path(abs_path)
        assert result == (lib_root / "_collector_cache" / "test.pdf").resolve()

    def test_absolute_path_inside_inbox_succeeds(self, lib_root, monkeypatch):
        monkeypatch.setattr(api.db, "LIBRARY_ROOT", lib_root)
        (lib_root / "_inbox" / "doc.pdf").write_bytes(b"%PDF")
        abs_path = str((lib_root / "_inbox" / "doc.pdf").resolve())
        result = resolve_pdf_path(abs_path)
        assert result == (lib_root / "_inbox" / "doc.pdf").resolve()

    def test_relative_path_in_disallowed_dir_raises(self, lib_root, monkeypatch):
        monkeypatch.setattr(api.db, "LIBRARY_ROOT", lib_root)
        with pytest.raises(ValueError, match="allowed subdirectory"):
            resolve_pdf_path("other_dir/outside.pdf")

    def test_absolute_path_in_disallowed_dir_raises(self, lib_root, monkeypatch):
        monkeypatch.setattr(api.db, "LIBRARY_ROOT", lib_root)
        abs_path = str((lib_root / "other_dir" / "outside.pdf").resolve())
        with pytest.raises(ValueError, match="allowed subdirectory"):
            resolve_pdf_path(abs_path)
