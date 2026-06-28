# scripts/migrate_add_collection_topics.py
"""Add collection_topics table (collector retrieval layer). Idempotent.

Creates the collection_topics table (topics that drive retrieval) and adds the
forward-looking collection_topic_id column on intake_candidates if missing
(guarded no-op on real DB where the foundation already added it).

Usage:
    python scripts/migrate_add_collection_topics.py
    python scripts/migrate_add_collection_topics.py --dry-run
"""
from __future__ import annotations
import argparse, sqlite3
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.db import table_exists

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS collection_topics (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    description   TEXT,
    query_def     TEXT,            -- JSON: {explicit_ids, seed_paper_ids, ...}
    map_status    TEXT NOT NULL DEFAULT 'seedling',  -- seedling|proposed|mapped
    lifecycle     TEXT NOT NULL DEFAULT 'active',     -- active|paused|retired
    mapped_tags   TEXT,            -- JSON [{group,value}]
    proposed_note TEXT,
    axis_hint     TEXT,            -- risk_domain|reading_lane
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
)
"""
INDEXES = [
    ("idx_ct_map_status", "collection_topics", "map_status"),
    ("idx_ct_lifecycle",  "collection_topics", "lifecycle"),
]

def _index_exists(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (name,)).fetchone() is not None

def _column_exists(conn, table, col):
    return any(r[1] == col for r in conn.execute(f"PRAGMA table_info({table})").fetchall())

def run(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        if not table_exists(conn, "collection_topics"):
            conn.execute(CREATE_TABLE)
        # 前瞻列：地基已为 intake_candidates 建过 collection_topic_id；仅当表存在且缺列时补
        if table_exists(conn, "intake_candidates") and not _column_exists(conn, "intake_candidates", "collection_topic_id"):
            conn.execute("ALTER TABLE intake_candidates ADD COLUMN collection_topic_id TEXT")
        for name, tbl, col in INDEXES:
            if not _index_exists(conn, name):
                conn.execute(f"CREATE INDEX {name} ON {tbl}({col})")
        conn.commit()
    finally:
        conn.close()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.dry_run:
        print("DRY-RUN: would create collection_topics + 2 indexes (and topic_id column if missing)"); return
    from api.db import DB_PATH
    run(DB_PATH)
    print("OK: collection_topics migration applied")

if __name__ == "__main__":
    main()
