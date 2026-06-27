"""同步 works.parse_status 与 literature_parse_runs.status。

修正滞后状态：若某 work 存在 status='succeeded' 且 content_md_path 非空的 parse_run，
但 works.parse_status 仍为非 succeeded（如 pending），则更正为 succeeded。

幂等、保守：只做 pending/其他 -> succeeded 的单向修正，绝不回退已 succeeded 的状态。

用法：
    python scripts/migrate_sync_parse_status.py            # dry-run，仅列出
    python scripts/migrate_sync_parse_status.py --apply    # 实际写 DB
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "literature.sqlite"


def find_desynced(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """返回 (work_id, current_parse_status) 列表，这些 work 有成功的 parse_run 但 parse_status 非 succeeded。"""
    rows = conn.execute(
        """
        SELECT w.id, w.parse_status
        FROM works w
        WHERE EXISTS (
            SELECT 1 FROM literature_parse_runs pr
            WHERE pr.work_id = w.id
              AND pr.status = 'succeeded'
              AND pr.content_md_path IS NOT NULL
              AND pr.content_md_path <> ''
        )
        AND w.parse_status <> 'succeeded'
        """
    ).fetchall()
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="同步 works.parse_status 与 parse_runs.status")
    ap.add_argument("--apply", action="store_true", help="实际写 DB（默认 dry-run）")
    args = ap.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    try:
        rows = find_desynced(conn)
        print(f"需同步的 work 数：{len(rows)}（{['DRY-RUN','APPLY'][args.apply]}）")
        for wid, cur in rows:
            print(f"  {wid}: parse_status {cur} -> succeeded")

        if not args.apply:
            print("\n(dry-run，未写 DB。加 --apply 执行。)")
            return 0

        if not rows:
            return 0

        changed = 0
        for wid, _ in rows:
            conn.execute(
                "UPDATE works SET parse_status='succeeded', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (wid,),
            )
            changed += 1
        conn.commit()
        print(f"\n已更新 {changed} 条。")
        # 复核
        left = find_desynced(conn)
        print(f"复核：剩余不同步 {len(left)} 条")
        return 0 if not left else 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
