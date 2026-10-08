"""Configuration and SQLite connections for the isolated research workflow.

The default deliberately points at ``_research_pilot/research.sqlite`` rather
than the legacy ``literature.sqlite``.  Production data is therefore never an
implicit write target.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ResearchContext:
    library_root: Path
    db_path: Path
    read_only: bool = False

    @classmethod
    def from_env(cls) -> "ResearchContext":
        root = Path(os.environ.get("LITLIB_RESEARCH_ROOT", REPO_ROOT / "_research_pilot"))
        db = Path(os.environ.get("LITLIB_RESEARCH_DB", root / "research.sqlite"))
        readonly = os.environ.get("LITLIB_RESEARCH_READ_ONLY", "").lower() in {"1", "true", "yes"}
        return cls(root.resolve(), db.resolve(), readonly)

    def connect(self, *, read_only: bool | None = None) -> sqlite3.Connection:
        ro = self.read_only if read_only is None else read_only
        if ro:
            # mode=ro is enforced by SQLite itself.  Do not set WAL on a source
            # library: doing so can create sidecar files and violates read-only.
            uri = f"file:{self.db_path.as_posix()}?mode=ro"
            conn = sqlite3.connect(uri, uri=True)
            conn.execute("PRAGMA query_only=ON")
        else:
            if self.read_only:
                raise PermissionError("research context is read-only")
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def require_writable(self) -> None:
        if self.read_only:
            raise PermissionError("research context is read-only")


def get_research_context() -> ResearchContext:
    """Resolve configuration per call so tests and separate API processes isolate cleanly."""
    return ResearchContext.from_env()
