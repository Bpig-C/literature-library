"""Add structured bibliographic columns (volume/issue/pages) to works.

出口侧引用质量增强：BibTeX volume/number/pages 与 RIS SP/EP 字段支持。
数据由人工核录回填（2026-09-02，64 条清单优先），证据来源记录于
metadata_extractions.review_note。

Idempotent: existing columns are not recreated.

Usage:
    python scripts/migrate_add_bib_columns.py
    python scripts/migrate_add_bib_columns.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.db import get_conn

WORKS_COLUMNS = [
    ("volume", "TEXT"),
    ("issue", "TEXT"),
    ("pages", "TEXT"),
]


def get_existing_columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def run_migration(dry_run: bool = False) -> None:
    conn = get_conn()
    actions = []

    existing_works_cols = get_existing_columns(conn, "works")
    for col_name, col_type in WORKS_COLUMNS:
        if col_name not in existing_works_cols:
            sql = f"ALTER TABLE works ADD COLUMN {col_name} {col_type}"
            actions.append(sql)
            if not dry_run:
                conn.execute(sql)

    if dry_run:
        for sql in actions:
            print(f"  [dry-run] {sql}")
        print(f"dry-run：共 {len(actions)} 项待执行，未改动数据库。")
        return

    conn.commit()
    if actions:
        for sql in actions:
            print(f"  {sql}")
        print(f"完成：新增 {len(actions)} 列。")
    else:
        print("列已存在，无需迁移。")


def main() -> None:
    parser = argparse.ArgumentParser(description="works 表新增卷/期/页结构化列")
    parser.add_argument("--dry-run", action="store_true", help="只打印将执行的变更，不写库")
    args = parser.parse_args()
    run_migration(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
