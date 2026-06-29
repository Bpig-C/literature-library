"""Read-only healthcheck for library consistency.

Detects:
  - Orphan files: files on disk not tracked in source_files.source_path.
  - Phantom DB entries: source_files.source_path pointing to missing files.
  - Work dirs without DB works.
  - Status inconsistencies (P2-06): quarantined works with active source files,
    intake_candidates with inconsistent status/review_status/ingested_work_id.
  - P2-POST-04: active source outside works/, quarantine path/status mismatch.

Default mode is read-only. Use --apply to quarantine orphan files.
Use --repair-quarantine-status to fix source_files.status for quarantined works.

Usage:
    python scripts/healthcheck_library.py [--library-root PATH] [--apply] [--repair-quarantine-status] [--json]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

# Ensure repo root is on sys.path so scripts.literature_ingest can be imported
_REPO_ROOT = str(Path(__file__).resolve().parents[1])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

REQUIRED_TABLES = {"works", "source_files"}
REQUIRED_SOURCE_FILE_COLUMNS = {"id", "work_id", "source_path", "original_name", "content_sha256",
                                "status", "archived_at", "archive_path", "archive_reason"}


def _check_schema(conn: sqlite3.Connection) -> list[dict[str, str]]:
    """Return list of schema inconsistencies (missing tables/columns). Read-only."""
    issues: list[dict[str, str]] = []
    existing_tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    for t in REQUIRED_TABLES:
        if t not in existing_tables:
            issues.append({"type": "missing_table", "table": t})
    if "source_files" in existing_tables:
        existing_cols = {r[1] for r in conn.execute("PRAGMA table_info(source_files)").fetchall()}
        for col in REQUIRED_SOURCE_FILE_COLUMNS:
            if col not in existing_cols:
                issues.append({"type": "missing_column", "table": "source_files", "column": col})
    return issues


@dataclass
class HealthcheckResult:
    orphan_files: list[str] = field(default_factory=list)
    phantom_db_entries: list[str] = field(default_factory=list)
    work_dirs_without_db: list[str] = field(default_factory=list)
    status_inconsistencies: list[dict[str, str]] = field(default_factory=list)
    applied_fixes: list[str] = field(default_factory=list)
    repair_plan: list[dict[str, str]] = field(default_factory=list)

    def has_issues(self) -> bool:
        return bool(
            self.orphan_files
            or self.phantom_db_entries
            or self.work_dirs_without_db
            or self.status_inconsistencies
        )

    def summary(self) -> dict[str, int]:
        return {
            "orphan_files": len(self.orphan_files),
            "phantom_db_entries": len(self.phantom_db_entries),
            "work_dirs_without_db": len(self.work_dirs_without_db),
            "status_inconsistencies": len(self.status_inconsistencies),
            "applied_fixes": len(self.applied_fixes),
            "repair_plan": len(self.repair_plan),
        }


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def run_healthcheck(library_root: Path, *, apply: bool = False,
                    repair_quarantine_status: bool = False,
                    dry_run: bool = True) -> HealthcheckResult:
    library_root = library_root.resolve()
    db_path = library_root / "literature.sqlite"
    result = HealthcheckResult()

    if not db_path.exists():
        result.status_inconsistencies.append({"type": "missing_db", "path": str(db_path)})
        return result

    conn = _connect(db_path)
    try:
        # Read-only schema check: report missing tables/columns without modifying DB
        schema_issues = _check_schema(conn)
        if schema_issues:
            result.status_inconsistencies.extend(schema_issues)
            # If core tables are missing, we can't do further checks
            if any(i["type"] == "missing_table" for i in schema_issues):
                return result

        # 1. Collect all source_paths from DB (for phantom check — P2-POST-04)
        db_source_paths_raw: list[tuple[str, str, str]] = []  # (id, source_path, status)
        for row in conn.execute(
            "SELECT id, source_path, status FROM source_files"
        ).fetchall():
            p = row["source_path"]
            if p:
                db_source_paths_raw.append((row["id"], p, row["status"] or "active"))

        # 2. Collect all work IDs from DB
        db_work_ids: set[str] = {
            row["id"] for row in conn.execute("SELECT id FROM works").fetchall()
        }

        # 3. Scan works/*/source/* for files on disk
        works_dir = library_root / "works"
        disk_source_paths: set[str] = set()
        disk_work_ids: set[str] = set()
        if works_dir.exists():
            for work_dir in works_dir.iterdir():
                if not work_dir.is_dir():
                    continue
                wid = work_dir.name
                disk_work_ids.add(wid)
                source_dir = work_dir / "source"
                if source_dir.exists():
                    for f in source_dir.rglob("*"):
                        if f.is_file():
                            disk_source_paths.add(str(f.resolve()))

        # Also collect quarantine dir for path checks
        quarantine_dir = library_root / "_quarantine"

        # 4. Detect orphan files (on disk under works/*/source/* but not in DB)
        db_resolved_paths: set[str] = set()
        for _, p, _ in db_source_paths_raw:
            db_resolved_paths.add(str(Path(p).resolve()))
        for disk_path in sorted(disk_source_paths):
            if disk_path not in db_resolved_paths:
                result.orphan_files.append(disk_path)

        # 5. P2-POST-04: Detect phantom DB entries — check actual file existence
        for sf_id, p, status in db_source_paths_raw:
            resolved = Path(p).resolve()
            if not resolved.exists():
                result.phantom_db_entries.append(p)

        # 6. Detect work dirs without DB works
        for wid in sorted(disk_work_ids):
            if wid not in db_work_ids:
                result.work_dirs_without_db.append(wid)

        # 7. Status inconsistencies
        has_status_col = "status" in {r[1] for r in conn.execute("PRAGMA table_info(source_files)").fetchall()}

        if has_status_col:
            # 7a. quarantined works with active source files
            for row in conn.execute(
                "SELECT sf.id, sf.source_path, sf.work_id "
                "FROM source_files sf "
                "JOIN works w ON w.id = sf.work_id "
                "WHERE w.read_status = 'quarantined' AND sf.status = 'active'"
            ).fetchall():
                result.status_inconsistencies.append({
                    "type": "quarantined_work_active_source",
                    "source_file_id": row["id"],
                    "work_id": row["work_id"],
                    "source_path": row["source_path"],
                })

            # 7d. P2-POST-04: active source pointing to _quarantine path
            quarantine_prefix = str(quarantine_dir.resolve())
            for row in conn.execute(
                "SELECT id, source_path, work_id, status FROM source_files WHERE status = 'active'"
            ).fetchall():
                resolved = str(Path(row["source_path"]).resolve())
                if resolved.startswith(quarantine_prefix):
                    result.status_inconsistencies.append({
                        "type": "active_source_in_quarantine",
                        "source_file_id": row["id"],
                        "work_id": row["work_id"],
                        "source_path": row["source_path"],
                    })

            # 7e. P2-POST-04: source in _quarantine but status != 'quarantined'
            for row in conn.execute(
                "SELECT id, source_path, work_id, status FROM source_files WHERE status != 'quarantined'"
            ).fetchall():
                resolved = str(Path(row["source_path"]).resolve())
                if resolved.startswith(quarantine_prefix):
                    result.status_inconsistencies.append({
                        "type": "quarantine_path_status_mismatch",
                        "source_file_id": row["id"],
                        "work_id": row["work_id"],
                        "source_path": row["source_path"],
                        "current_status": row["status"],
                    })

            # 7f. P2-POST-04: active source outside works/ (not in quarantine either)
            works_prefix = str(works_dir.resolve())
            for row in conn.execute(
                "SELECT id, source_path, work_id, status FROM source_files WHERE status = 'active'"
            ).fetchall():
                resolved = str(Path(row["source_path"]).resolve())
                if not resolved.startswith(works_prefix) and not resolved.startswith(quarantine_prefix):
                    result.status_inconsistencies.append({
                        "type": "active_source_outside_works",
                        "source_file_id": row["id"],
                        "work_id": row["work_id"],
                        "source_path": row["source_path"],
                    })

        # 7b/7c: intake_candidates checks (table may not exist in all DBs)
        has_ic = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='intake_candidates'"
        ).fetchone() is not None
        if has_ic:
            # 7b. intake_candidates: status=ingested but no ingested_work_id
            for row in conn.execute(
                "SELECT id, title, status, review_status, ingested_work_id "
                "FROM intake_candidates "
                "WHERE status = 'ingested' AND (ingested_work_id IS NULL OR ingested_work_id = '')"
            ).fetchall():
                result.status_inconsistencies.append({
                    "type": "ingested_no_work_id",
                    "candidate_id": row["id"],
                    "title": row["title"] or "",
                })

            # 7c. intake_candidates: ingested_work_id set but status != ingested
            for row in conn.execute(
                "SELECT id, title, status, review_status, ingested_work_id "
                "FROM intake_candidates "
                "WHERE ingested_work_id IS NOT NULL AND ingested_work_id != '' AND status != 'ingested'"
            ).fetchall():
                result.status_inconsistencies.append({
                    "type": "work_id_but_not_ingested",
                    "candidate_id": row["id"],
                    "status": row["status"],
                    "ingested_work_id": row["ingested_work_id"],
                })

        # 8. P2-POST-03: Build repair plan for quarantined works with non-quarantined source_files
        if has_status_col and repair_quarantine_status:
            for row in conn.execute(
                "SELECT sf.id, sf.source_path, sf.work_id, sf.status, sf.archive_reason "
                "FROM source_files sf "
                "JOIN works w ON w.id = sf.work_id "
                "WHERE w.read_status = 'quarantined' AND sf.status != 'quarantined'"
            ).fetchall():
                plan_entry = {
                    "source_file_id": row["id"],
                    "work_id": row["work_id"],
                    "source_path": row["source_path"],
                    "current_status": row["status"],
                    "proposed_status": "quarantined",
                    "current_archive_reason": row["archive_reason"] or "",
                    "proposed_archive_reason": "auto-repair: work is quarantined",
                }
                result.repair_plan.append(plan_entry)

                if not dry_run:
                    conn.execute(
                        "UPDATE source_files SET status = 'quarantined', "
                        "archive_reason = ? WHERE id = ?",
                        ("auto-repair: work is quarantined", row["id"]),
                    )
                    result.applied_fixes.append(
                        f"source_files[{row['id']}]: status {row['status']} -> quarantined"
                    )
            if not dry_run and result.applied_fixes:
                conn.commit()

    finally:
        conn.close()

    # 9. Apply fixes if requested (--apply is the only mode that moves files)
    if apply:
        from scripts.literature_ingest import ensure_core_schema
        conn = _connect(db_path)
        try:
            ensure_core_schema(conn)
            quarantine_dir = library_root / "_quarantine" / "_healthcheck_orphans"
            for orphan in result.orphan_files:
                src = Path(orphan)
                if not src.exists():
                    continue
                quarantine_dir.mkdir(parents=True, exist_ok=True)
                dest = quarantine_dir / src.name
                # unique name
                counter = 2
                while dest.exists():
                    dest = quarantine_dir / f"{src.stem}__{counter}{src.suffix}"
                    counter += 1
                src.rename(dest)
                result.applied_fixes.append(f"moved {orphan} -> {dest}")
            conn.commit()
        finally:
            conn.close()

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Library consistency healthcheck.")
    parser.add_argument("--library-root", type=Path, default=None)
    parser.add_argument("--apply", action="store_true", help="Fix orphan files by moving to quarantine.")
    parser.add_argument("--repair-quarantine-status", action="store_true",
                        help="Repair source_files.status for quarantined works (dry-run unless --apply).")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Output as JSON.")
    args = parser.parse_args(argv)

    if args.library_root:
        library_root = args.library_root
    else:
        library_root = Path(__file__).resolve().parents[1]

    repair = args.repair_quarantine_status
    dry_run = not args.apply

    result = run_healthcheck(library_root, apply=args.apply,
                             repair_quarantine_status=repair, dry_run=dry_run)

    if args.json_output:
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    else:
        print(f"Healthcheck results for: {library_root}")
        print(f"  Orphan files (on disk, not in DB): {len(result.orphan_files)}")
        for f in result.orphan_files:
            print(f"    - {f}")
        print(f"  Phantom DB entries (in DB, not on disk): {len(result.phantom_db_entries)}")
        for f in result.phantom_db_entries:
            print(f"    - {f}")
        print(f"  Work dirs without DB work: {len(result.work_dirs_without_db)}")
        for w in result.work_dirs_without_db:
            print(f"    - {w}")
        print(f"  Status inconsistencies: {len(result.status_inconsistencies)}")
        for inc in result.status_inconsistencies:
            print(f"    - {inc}")
        if result.repair_plan:
            label = "Repair plan" if dry_run else "Applied repairs"
            print(f"  {label}: {len(result.repair_plan)}")
            for entry in result.repair_plan:
                print(f"    - {entry['source_file_id']}: {entry['current_status']} -> {entry['proposed_status']}")
        if result.applied_fixes:
            print(f"  Applied fixes: {len(result.applied_fixes)}")
            for fix in result.applied_fixes:
                print(f"    - {fix}")
        if result.has_issues():
            print("\nIssues detected. Run with --apply to fix orphan files.")
        else:
            print("\nNo issues detected.")

    return 1 if result.has_issues() else 0


if __name__ == "__main__":
    raise SystemExit(main())
