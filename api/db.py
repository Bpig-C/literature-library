"""SQLite database connection helper."""

from __future__ import annotations

import sqlite3
from pathlib import Path

LIBRARY_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = LIBRARY_ROOT / "literature.sqlite"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def ensure_metadata_review_columns(conn: sqlite3.Connection) -> None:
    """Add review_status/review_note/reviewed_at + risk columns to metadata_extractions if missing."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(metadata_extractions)").fetchall()}
    if "review_status" not in cols:
        conn.execute("ALTER TABLE metadata_extractions ADD COLUMN review_status TEXT DEFAULT 'pending'")
    if "review_note" not in cols:
        conn.execute("ALTER TABLE metadata_extractions ADD COLUMN review_note TEXT DEFAULT ''")
    if "reviewed_at" not in cols:
        conn.execute("ALTER TABLE metadata_extractions ADD COLUMN reviewed_at TEXT")
    if "risk_level" not in cols:
        conn.execute("ALTER TABLE metadata_extractions ADD COLUMN risk_level TEXT DEFAULT 'pending'")
    if "risk_score" not in cols:
        conn.execute("ALTER TABLE metadata_extractions ADD COLUMN risk_score INTEGER DEFAULT 0")
    if "risk_reasons" not in cols:
        conn.execute("ALTER TABLE metadata_extractions ADD COLUMN risk_reasons TEXT DEFAULT '[]'")
    if "review_source" not in cols:
        conn.execute("ALTER TABLE metadata_extractions ADD COLUMN review_source TEXT DEFAULT 'human'")
    if "fix_action" not in cols:
        conn.execute("ALTER TABLE metadata_extractions ADD COLUMN fix_action TEXT DEFAULT ''")
    if "superseded_by" not in cols:
        conn.execute("ALTER TABLE metadata_extractions ADD COLUMN superseded_by TEXT DEFAULT ''")
    conn.commit()
