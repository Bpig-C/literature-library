"""One-time cleanup: fix broken source_paths, archive duplicate source_files,
create missing relations for reviewed title_candidate groups.

This script is idempotent — safe to re-run.

Usage:
    python scripts/dedup_cleanup.py --dry-run
    python scripts/dedup_cleanup.py --execute
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

LIBRARY_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = LIBRARY_ROOT / "literature.sqlite"


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def fix_broken_source_paths(conn: sqlite3.Connection, dry_run: bool) -> int:
    """Update source_path for files whose old path doesn't exist but new path does."""
    fixed = 0
    rows = conn.execute("SELECT id, work_id, source_path, original_name FROM source_files").fetchall()
    for r in rows:
        old_path = Path(r["source_path"])
        if old_path.exists():
            continue  # Path is valid, skip

        # Try to find the file in works/{id}/source/
        work_source = LIBRARY_ROOT / "works" / r["work_id"] / "source"
        if not work_source.exists():
            print(f"  SKIP {r['work_id']}: no works dir and old path broken")
            continue

        # Find matching file by name
        candidates = list(work_source.glob("*"))
        match = None
        for c in candidates:
            if c.name == r["original_name"]:
                match = c
                break
        if not match and candidates:
            match = candidates[0]  # Fallback to first file

        if match:
            new_path = str(match)
            if dry_run:
                print(f"  [DRY] {r['work_id']}: {old_path.name} -> {new_path}")
            else:
                conn.execute(
                    "UPDATE source_files SET source_path = ? WHERE id = ?",
                    (new_path, r["id"]),
                )
            fixed += 1
        else:
            print(f"  WARN {r['work_id']}: no matching file in works dir")

    if not dry_run and fixed:
        conn.commit()
    return fixed


def fix_all_source_paths(conn: sqlite3.Connection, dry_run: bool) -> int:
    """Update ALL source_path to point to works/{id}/source/ (canonical location)."""
    fixed = 0
    rows = conn.execute("SELECT id, work_id, source_path, original_name FROM source_files").fetchall()
    for r in rows:
        current = Path(r["source_path"])
        canonical = LIBRARY_ROOT / "works" / r["work_id"] / "source" / r["original_name"]

        if current == canonical:
            continue  # Already correct

        if canonical.exists():
            if dry_run:
                print(f"  [DRY] {r['work_id']}: -> {canonical}")
            else:
                conn.execute(
                    "UPDATE source_files SET source_path = ?, relative_source_path = ? WHERE id = ?",
                    (str(canonical), str(canonical.relative_to(LIBRARY_ROOT)), r["id"]),
                )
            fixed += 1
        elif current.exists():
            # File exists at old location but not at canonical — move it
            if dry_run:
                print(f"  [DRY] {r['work_id']}: MOVE {current} -> {canonical}")
            else:
                canonical.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(current), str(canonical))
                conn.execute(
                    "UPDATE source_files SET source_path = ?, relative_source_path = ? WHERE id = ?",
                    (str(canonical), str(canonical.relative_to(LIBRARY_ROOT)), r["id"]),
                )
            fixed += 1
        else:
            # Neither location exists — just update the path
            if dry_run:
                print(f"  [DRY] {r['work_id']}: PATH-ONLY -> {canonical}")
            else:
                conn.execute(
                    "UPDATE source_files SET source_path = ?, relative_source_path = ? WHERE id = ?",
                    (str(canonical), str(canonical.relative_to(LIBRARY_ROOT)), r["id"]),
                )
            fixed += 1

    if not dry_run and fixed:
        conn.commit()
    return fixed


def archive_duplicate_sources(conn: sqlite3.Connection, dry_run: bool) -> int:
    """For exact_sha256 groups, keep one source_file per SHA256 per work, archive the rest."""
    removed = 0
    archive_dir = LIBRARY_ROOT / "_archive" / "dedup"

    # Find all works with multiple source_files sharing the same SHA256
    rows = conn.execute("""
        SELECT work_id, content_sha256, GROUP_CONCAT(id) as ids, COUNT(*) as cnt
        FROM source_files
        GROUP BY work_id, content_sha256
        HAVING COUNT(*) > 1
    """).fetchall()

    for r in rows:
        ids = r["ids"].split(",")
        work_id = r["work_id"]

        # Get full records for these source_files
        placeholders = ",".join("?" * len(ids))
        files = conn.execute(
            f"SELECT id, source_path, original_name FROM source_files WHERE id IN ({placeholders})",
            ids,
        ).fetchall()

        # Sort by original_name length descending (prefer descriptive names)
        files.sort(key=lambda f: len(f["original_name"] or ""), reverse=True)
        keep = files[0]

        for f in files[1:]:
            src_path = Path(f["source_path"])
            archive_path = None
            if src_path.exists():
                dest = archive_dir / work_id / src_path.name
                if dry_run:
                    print(f"  [DRY] ARCHIVE {src_path.name} -> {dest}")
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src_path), str(dest))
                    archive_path = str(dest)

            if not dry_run:
                conn.execute(
                    "UPDATE source_files SET status = 'archived', archived_at = ?, archive_path = ?, archive_reason = ? WHERE id = ?",
                    (
                        datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        archive_path,
                        f"dedup cleanup: same SHA256 as {keep['id']}",
                        f["id"],
                    ),
                )
            removed += 1

    if not dry_run and removed:
        conn.commit()
    return removed


def create_missing_relations(conn: sqlite3.Connection, dry_run: bool) -> int:
    """Create work_relations for title_candidate groups that are reviewed but have no relations."""
    created = 0

    # Find title_candidate groups where candidates are reviewed but no relation exists
    groups = conn.execute("""
        SELECT dg.id FROM duplicate_groups dg
        WHERE dg.duplicate_type = 'title_candidate'
        AND EXISTS (SELECT 1 FROM duplicate_candidates dc WHERE dc.group_id = dg.id AND dc.reviewed = 1)
    """).fetchall()

    for g in groups:
        group_id = g["id"]
        # Get work_ids in this group
        cands = conn.execute(
            "SELECT DISTINCT work_id FROM duplicate_candidates WHERE group_id = ?",
            (group_id,),
        ).fetchall()
        work_ids = [c["work_id"] for c in cands]

        # Check if any relation already exists between these works
        for i in range(len(work_ids)):
            for j in range(i + 1, len(work_ids)):
                exists = conn.execute("""
                    SELECT 1 FROM work_relations
                    WHERE (work_id_a = ? AND work_id_b = ?) OR (work_id_a = ? AND work_id_b = ?)
                """, (work_ids[i], work_ids[j], work_ids[j], work_ids[i])).fetchone()

                if not exists:
                    # Check if both works have bad_source code — these are quarantined screenshots
                    a_bad = conn.execute(
                        "SELECT 1 FROM work_codes WHERE work_id = ? AND code = 'bad_source'",
                        (work_ids[i],),
                    ).fetchone()
                    b_bad = conn.execute(
                        "SELECT 1 FROM work_codes WHERE work_id = ? AND code = 'bad_source'",
                        (work_ids[j],),
                    ).fetchone()

                    if a_bad and b_bad:
                        rel_type = "not_duplicate"
                        note = f"both quarantined (bad_source), reviewed in {group_id}"
                    else:
                        rel_type = "not_duplicate"
                        note = f"dedup review {group_id}"

                    a, b = sorted([work_ids[i], work_ids[j]])
                    if dry_run:
                        print(f"  [DRY] RELATION {a} --{rel_type}--> {b}")
                    else:
                        conn.execute(
                            "INSERT OR IGNORE INTO work_relations (work_id_a, work_id_b, relation_type, confirmed, note) VALUES (?, ?, ?, 1, ?)",
                            (a, b, rel_type, note),
                        )
                    created += 1

    if not dry_run and created:
        conn.commit()
    return created


def main():
    parser = argparse.ArgumentParser(description="去重清理：修复路径、归档重复、补建关系")
    parser.add_argument("--dry-run", action="store_true", help="只显示计划，不执行")
    parser.add_argument("--execute", action="store_true", help="实际执行清理")
    parser.add_argument("--fix-all-paths", action="store_true",
                        help="修复所有 source_path 指向 works/ 目录（不仅是断裂路径）")
    args = parser.parse_args()

    if not args.execute and not args.dry_run:
        print("请指定 --dry-run 或 --execute")
        return

    dry_run = not args.execute
    conn = connect_db()

    try:
        print("=== 1. 修复断裂的 source_path ===")
        if args.fix_all_paths:
            n = fix_all_source_paths(conn, dry_run)
        else:
            n = fix_broken_source_paths(conn, dry_run)
        print(f"  修复了 {n} 条路径\n")

        print("=== 2. 归档 exact_sha256 重复源文件 ===")
        n = archive_duplicate_sources(conn, dry_run)
        print(f"  归档了 {n} 个冗余文件\n")

        print("=== 3. 补建 title_candidate 缺失关系 ===")
        n = create_missing_relations(conn, dry_run)
        print(f"  创建了 {n} 条关系\n")

        print("完成。")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
