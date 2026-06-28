# scripts/migrate_add_intake_candidates.py
"""Add intake_candidates table (collector candidate queue). Idempotent.

Usage:
    python scripts/migrate_add_intake_candidates.py
    python scripts/migrate_add_intake_candidates.py --dry-run
"""
from __future__ import annotations
import argparse, sqlite3
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.db import get_conn, table_exists

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS intake_candidates (
    id              TEXT PRIMARY KEY,
    source_type     TEXT NOT NULL,             -- arxiv | github
    source_url      TEXT,
    title           TEXT,
    arxiv_id        TEXT,
    doi             TEXT,
    url_canonical   TEXT NOT NULL,
    fetched_sha256  TEXT,
    local_pdf_path  TEXT,
    resolution      TEXT NOT NULL DEFAULT 'pending',
                                  -- pending|new|exact_hit|title_candidate|
                                  -- needs_better_copy|sha256_duplicate|fetch_failed
    matched_work_id TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
                                  -- pending|resolved|ingested|skipped|superseded_quarantine
    review_status   TEXT NOT NULL DEFAULT 'pending',  -- pending|approved|rejected
    review_note     TEXT,
    collected_at    TEXT,
    resolved_at     TEXT,
    ingested_work_id TEXT,
    raw_meta        TEXT,
    UNIQUE(source_type, url_canonical)
)
"""
INDEXES = [
    ("idx_ic_source_type", "intake_candidates", "source_type"),
    ("idx_ic_arxiv_id", "intake_candidates", "arxiv_id"),
    ("idx_ic_doi", "intake_candidates", "doi"),
    ("idx_ic_resolution", "intake_candidates", "resolution"),
    ("idx_ic_status", "intake_candidates", "status"),
    ("idx_ic_review", "intake_candidates", "review_status"),
]

def _index_exists(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (name,)).fetchone() is not None

def run(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        if not table_exists(conn, "intake_candidates"):
            conn.execute(CREATE_TABLE)
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
        print("DRY-RUN: would create intake_candidates + 6 indexes"); return
    from api.db import DB_PATH
    run(DB_PATH)
    print("OK: intake_candidates migration applied")

if __name__ == "__main__":
    main()
