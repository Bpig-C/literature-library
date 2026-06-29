"""同步 works.parse_status 与 literature_parse_runs.status。

只统计 source_files.status='active' 的源。对每个 active 源取其"最好成绩"：
- 有任意一条 status='succeeded' 且 content_md_path 非空的 run → succeeded
- 否则若它有 run 且全部 failed → failed
- 否则 → pending（含"还没有任何 run"）

work 的 parse_status：
- 无 active 源 → pending
- 全部 succeeded → succeeded
- 全部 failed → failed
- 其它（混合 / 有 pending） → partial

注意：允许 succeeded→partial 的回退（这是预期行为，非回归）。

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


def sync_work_parse_status(conn: sqlite3.Connection, work_id: str) -> str:
    """按 literature_parse_runs 重算单个 work 的 works.parse_status。

    只统计 active 源：对每个 active source_file 取其最好成绩，再聚合。
    允许 succeeded→partial 回退（多源场景下部分源未完成时属预期行为）。
    """
    active_sources = conn.execute(
        "SELECT id FROM source_files WHERE work_id=? AND status='active'",
        (work_id,),
    ).fetchall()
    if not active_sources:
        conn.execute(
            "UPDATE works SET parse_status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            ("pending", work_id),
        )
        return "pending"

    source_statuses: list[str] = []
    for (sf_id,) in active_sources:
        runs = conn.execute(
            "SELECT status, content_md_path FROM literature_parse_runs "
            "WHERE work_id=? AND source_file_id=?",
            (work_id, sf_id),
        ).fetchall()
        if not runs:
            source_statuses.append("pending")
        elif any(r[0] == "succeeded" and (r[1] or "") for r in runs):
            source_statuses.append("succeeded")
        elif all(r[0] == "failed" for r in runs):
            source_statuses.append("failed")
        else:
            source_statuses.append("pending")

    if all(s == "succeeded" for s in source_statuses):
        new = "succeeded"
    elif all(s == "failed" for s in source_statuses):
        new = "failed"
    elif all(s == "pending" for s in source_statuses):
        new = "pending"
    else:
        new = "partial"

    conn.execute(
        "UPDATE works SET parse_status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (new, work_id),
    )
    return new


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
            sync_work_parse_status(conn, wid)
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
