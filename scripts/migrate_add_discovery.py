# scripts/migrate_add_discovery.py
"""Add discovery_runs and discovery_hits tables (V1.1 constrained discovery). Idempotent.

Usage:
    python scripts/migrate_add_discovery.py
    python scripts/migrate_add_discovery.py --dry-run
"""
from __future__ import annotations
import argparse, sqlite3
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.db import table_exists

CREATE_DISCOVERY_RUNS = """
CREATE TABLE IF NOT EXISTS discovery_runs (
    id                  TEXT PRIMARY KEY,         -- DR-{hex}
    collection_topic_id TEXT,                     -- nullable FK -> collection_topics
    mode                TEXT NOT NULL,             -- topic|name|title|url|doi|arxiv
    input_json          TEXT,                      -- user input snapshot
    search_plan_json    TEXT,                      -- pre-execution plan
    executor            TEXT NOT NULL,             -- python|agent:web-access|manual
    status              TEXT NOT NULL DEFAULT 'planned',  -- planned|running|succeeded|failed
    error               TEXT,                      -- failure reason
    hits_created        INTEGER DEFAULT 0,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
)
"""

CREATE_DISCOVERY_HITS = """
CREATE TABLE IF NOT EXISTS discovery_hits (
    id                  TEXT PRIMARY KEY,         -- DH-{hex}
    run_id              TEXT NOT NULL,             -- FK -> discovery_runs
    collection_topic_id TEXT,                     -- nullable
    query               TEXT,
    source_type         TEXT,                      -- web|official_domain|github|huggingface|
                                                   -- openalex|crossref|semantic_scholar|manual_url
    url                 TEXT,
    canonical_url       TEXT,
    title               TEXT,
    snippet             TEXT,
    artifact_type_hint  TEXT,                      -- system_card|model_card|technical_report|
                                                   -- research_article|unknown
    confidence          TEXT,                      -- high|medium|low
    reason              TEXT,
    raw_json            TEXT,
    dedup_key           TEXT,
    candidate_id        TEXT,                      -- backfill after intake_candidates accept
    review_status       TEXT DEFAULT 'pending',    -- pending|accepted|rejected
    review_note         TEXT,
    primary_source      TEXT,                      -- true|false|unknown
    content_type        TEXT,                      -- html|pdf|metadata|repo|model_card|unknown
    verification_status TEXT DEFAULT 'unverified', -- unverified|url_verified|content_checked|failed
    observed_at         TEXT
)
"""

INDEXES = [
    ("idx_dr_topic_id",     "discovery_runs", "collection_topic_id"),
    ("idx_dr_status",       "discovery_runs", "status"),
    ("idx_dh_run_id",       "discovery_hits", "run_id"),
    ("idx_dh_canonical_url","discovery_hits", "canonical_url"),
    ("idx_dh_dedup_key",    "discovery_hits", "dedup_key"),
    ("idx_dh_review_status","discovery_hits", "review_status"),
]


def _index_exists(conn, name):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (name,)
    ).fetchone() is not None


def run(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        if not table_exists(conn, "discovery_runs"):
            conn.execute(CREATE_DISCOVERY_RUNS)
        if not table_exists(conn, "discovery_hits"):
            conn.execute(CREATE_DISCOVERY_HITS)
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
        print("DRY-RUN: would create discovery_runs + discovery_hits + 6 indexes")
        return
    from api.db import DB_PATH
    run(DB_PATH)
    print("OK: discovery migration applied")


if __name__ == "__main__":
    main()
