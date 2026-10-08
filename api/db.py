"""SQLite database connection helper."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[1]
LIBRARY_ROOT = Path(os.environ.get("LITLIB_LIBRARY_ROOT", CODE_ROOT)).resolve()
DB_PATH = Path(os.environ.get("LITLIB_DB_PATH", LIBRARY_ROOT / "literature.sqlite")).resolve()


def get_conn() -> sqlite3.Connection:
    if os.environ.get('LITLIB_STORAGE_MODE')=='immutable':
        from .storage.runtime import configured_registry
        configured_registry().validate()
        if not DB_PATH.is_file():raise RuntimeError('explicit catalog absent; no creation or fallback')
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


# LL-DECOUPLE-20260920: ``ensure_metadata_review_columns`` (which ALTERed the
# legacy ``metadata_extractions`` table on connect) was removed together with
# every active writer of that table.  Historical archives stay untouched.
