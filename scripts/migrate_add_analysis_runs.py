"""Create analysis_runs table for reading methodology analysis.

Idempotent: existing table and indexes are not recreated.

Usage:
    python scripts/migrate_add_analysis_runs.py
    python scripts/migrate_add_analysis_runs.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.db import get_conn


ANALYSIS_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS analysis_runs (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  angle TEXT NOT NULL,
  template_version INTEGER NOT NULL,
  work_id TEXT,
  input_work_ids TEXT,
  selector_snapshot TEXT,
  executor TEXT,
  model_name TEXT,
  input_scope TEXT,
  input_chars INTEGER,
  extracted_json TEXT NOT NULL,
  confidence TEXT,
  not_addressed INTEGER DEFAULT 0,
  review_status TEXT DEFAULT 'pending',
  review_note TEXT,
  reviewed_at TEXT,
  review_source TEXT,
  superseded_by TEXT,
  md_path TEXT,
  raw_response TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)
"""

ANALYSIS_RUNS_INDEXES = [
    ("idx_analysis_runs_work", "analysis_runs", "work_id"),
    ("idx_analysis_runs_angle", "analysis_runs", "angle, template_version"),
    ("idx_analysis_runs_status", "analysis_runs", "review_status"),
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

    # 1. Create analysis_runs table
    if not table_exists(conn, "analysis_runs"):
        actions.append(ANALYSIS_RUNS_TABLE.strip())
        if not dry_run:
            conn.execute(ANALYSIS_RUNS_TABLE)
    else:
        actions.append("-- analysis_runs table already exists, skipping CREATE TABLE")

    # 2. Add indexes for analysis_runs
    for idx_name, table, col in ANALYSIS_RUNS_INDEXES:
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
    exists = table_exists(conn, "analysis_runs")
    print(f"\n--- analysis_runs: {'EXISTS' if exists else 'WOULD CREATE'} ---")

    if exists:
        cols = get_existing_columns(conn, "analysis_runs")
        print("Columns:")
        for c in sorted(cols):
            print(f"  {c}")

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Create analysis_runs table")
    parser.add_argument("--dry-run", action="store_true", help="Print SQL without executing")
    args = parser.parse_args()
    run_migration(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
