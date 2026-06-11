"""Execute classification ontology v0.2 database schema changes.

Idempotent: existing columns and tables are not recreated.

Usage:
    python scripts/migrate_add_classification_columns.py
    python scripts/migrate_add_classification_columns.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.db import get_conn

# Columns to add to works table
WORKS_COLUMNS = [
    ("primary_doc_type", "TEXT"),
    ("publication_status", "TEXT"),
    ("ingestion_state", "TEXT"),
    ("priority", "TEXT"),
    ("is_core_literature", "INTEGER"),
    ("primary_source_actor_type", "TEXT"),
    ("region", "TEXT"),
    ("canonical_file_format", "TEXT"),
    ("contributors", "TEXT"),
    ("publication_date_json", "TEXT"),
]

# Columns to add to work_relations table
RELATIONS_COLUMNS = [
    ("relation_category", "TEXT DEFAULT 'content'"),
    ("source", "TEXT DEFAULT 'human'"),
    ("created_at", "TEXT"),
]

# Indexes for works table
WORKS_INDEXES = [
    ("idx_works_primary_doc_type", "works", "primary_doc_type"),
    ("idx_works_publication_status", "works", "publication_status"),
    ("idx_works_ingestion_state", "works", "ingestion_state"),
    ("idx_works_priority", "works", "priority"),
    ("idx_works_primary_actor_type", "works", "primary_source_actor_type"),
    ("idx_works_region", "works", "region"),
]

# Indexes for work_relations
RELATIONS_INDEXES = [
    ("idx_wr_category", "work_relations", "relation_category"),
    ("idx_wr_source", "work_relations", "source"),
]

# New tables
NEW_TABLES = {
    "work_classification_tags": """
        CREATE TABLE IF NOT EXISTS work_classification_tags (
            id               TEXT PRIMARY KEY,
            work_id          TEXT NOT NULL REFERENCES works(id) ON DELETE CASCADE,
            tag_group        TEXT NOT NULL,
            tag_value        TEXT NOT NULL,
            vocab_version    TEXT NOT NULL DEFAULT 'v1',
            source           TEXT NOT NULL DEFAULT 'human',
            confidence       TEXT,
            review_status    TEXT NOT NULL DEFAULT 'pending',
            reviewed_at      TEXT,
            reviewed_by      TEXT,
            evidence         TEXT,
            notes            TEXT,
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL
        )
    """,
    "classification_extractions": """
        CREATE TABLE IF NOT EXISTS classification_extractions (
            id                  TEXT PRIMARY KEY,
            work_id             TEXT NOT NULL REFERENCES works(id) ON DELETE CASCADE,
            model_name          TEXT,
            prompt_version      TEXT,
            extracted_json      TEXT,
            confidence_json     TEXT,
            ambiguity_score     INTEGER DEFAULT 0,
            ambiguity_reasons   TEXT,
            review_status       TEXT NOT NULL DEFAULT 'pending',
            review_note         TEXT,
            reviewed_at         TEXT,
            fix_action          TEXT,
            applied             INTEGER NOT NULL DEFAULT 0,
            applied_at          TEXT,
            raw_response        TEXT,
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL
        )
    """,
}

# Indexes for new tables
NEW_TABLE_INDEXES = [
    ("idx_wct_work_id", "work_classification_tags", "work_id"),
    ("idx_wct_work_group", "work_classification_tags", "work_id, tag_group"),
    ("idx_wct_group_value", "work_classification_tags", "tag_group, tag_value"),
    ("idx_wct_review", "work_classification_tags", "review_status"),
    ("idx_ce_work_id", "classification_extractions", "work_id"),
    ("idx_ce_review", "classification_extractions", "review_status"),
    ("idx_ce_applied", "classification_extractions", "applied"),
    ("idx_ce_ambiguity", "classification_extractions", "ambiguity_score"),
]


def get_existing_columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def table_exists(conn, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def index_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def run_migration(dry_run: bool = False) -> None:
    conn = get_conn()
    actions = []

    # 1. Add columns to works table
    existing_works_cols = get_existing_columns(conn, "works")
    for col_name, col_type in WORKS_COLUMNS:
        if col_name not in existing_works_cols:
            sql = f"ALTER TABLE works ADD COLUMN {col_name} {col_type}"
            actions.append(sql)
            if not dry_run:
                conn.execute(sql)

    # 2. Add indexes for works
    for idx_name, table, col in WORKS_INDEXES:
        if not index_exists(conn, idx_name):
            sql = f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({col})"
            actions.append(sql)
            if not dry_run:
                conn.execute(sql)

    # 3. Add columns to work_relations
    existing_rel_cols = get_existing_columns(conn, "work_relations")
    for col_name, col_type in RELATIONS_COLUMNS:
        if col_name not in existing_rel_cols:
            sql = f"ALTER TABLE work_relations ADD COLUMN {col_name} {col_type}"
            actions.append(sql)
            if not dry_run:
                conn.execute(sql)

    # 4. Add indexes for work_relations
    for idx_name, table, col in RELATIONS_INDEXES:
        if not index_exists(conn, idx_name):
            sql = f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({col})"
            actions.append(sql)
            if not dry_run:
                conn.execute(sql)

    # 5. Create new tables
    for table_name, create_sql in NEW_TABLES.items():
        if not table_exists(conn, table_name):
            actions.append(create_sql.strip())
            if not dry_run:
                conn.execute(create_sql)

    # 6. Add indexes for new tables
    for idx_name, table, col in NEW_TABLE_INDEXES:
        if not index_exists(conn, idx_name):
            sql = f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({col})"
            actions.append(sql)
            if not dry_run:
                conn.execute(sql)

    if not dry_run:
        conn.commit()

    # Report
    if dry_run:
        print("=== DRY RUN ===")
        print(f"Would execute {len(actions)} statements:")
    else:
        print(f"Executed {len(actions)} statements:")

    for sql in actions:
        print(f"  {sql[:120]}")

    # Print current state
    print("\n--- Current works columns ---")
    cols = get_existing_columns(conn, "works") if not dry_run else existing_works_cols
    for c in sorted(cols):
        print(f"  {c}")

    for table_name in NEW_TABLES:
        exists = table_exists(conn, table_name)
        print(f"\n--- {table_name}: {'EXISTS' if exists else 'WOULD CREATE'} ---")

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Add classification columns and tables")
    parser.add_argument("--dry-run", action="store_true", help="Print SQL without executing")
    args = parser.parse_args()
    run_migration(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
