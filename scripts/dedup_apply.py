"""Apply dedup review decisions to the literature library database.

Reads a dedup_reviews.json file (downloaded from the dedup dashboard) and
updates work_relations, marks duplicate_candidates as reviewed, and optionally
archives redundant source files.

This script is conservative: no irreversible deletions. Archived files
are moved to _archive/ rather than deleted.

Usage:
    python scripts/dedup_apply.py [--library-root DIR] [--reviews FILE] [--dry-run] [--archive]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VALID_DECISION_TYPES = {"same_work", "not_duplicate", "version_of", "translation_of", "supersedes", "part_of", "quarantine"}

# For exact_sha256 groups: same_work means all source files map to the same work.
# For title_candidate groups: the directional relation types need clear semantics.
# supersedes: work_id_a is the newer/better version, work_id_b is superseded.
# part_of: work_id_a is a part of work_id_b.
# version_of: mutual (bidirectional), stored both ways.


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def load_reviews(reviews_path: Path) -> dict[str, Any]:
    text = reviews_path.read_text(encoding="utf-8")
    data = json.loads(text)
    if "decisions" not in data:
        raise ValueError(f"Invalid reviews file: missing 'decisions' key in {reviews_path}")
    return data


def apply_decisions(
    library_root: Path,
    reviews: dict[str, Any],
    dry_run: bool = False,
    archive: bool = False,
) -> dict[str, Any]:
    db_path = library_root / "literature.sqlite"
    archive_dir = library_root / "_archive"
    report: dict[str, Any] = {
        "applied_at": utc_now(),
        "relations_inserted": 0,
        "relations_skipped": 0,
        "candidates_reviewed": 0,
        "works_quarantined": 0,
        "files_archived": 0,
        "errors": [],
    }

    conn = connect_db(db_path)
    try:
        # Load existing groups for resolving group_id to work_ids
        groups_rows = conn.execute("SELECT * FROM duplicate_groups").fetchall()
        groups_by_id: dict[str, dict[str, Any]] = {}
        for g in groups_rows:
            groups_by_id[g["id"]] = dict(g)

        # Load candidates for marking as reviewed
        candidates_rows = conn.execute("SELECT * FROM duplicate_candidates").fetchall()
        candidates_by_id: dict[str, dict[str, Any]] = {c["id"]: dict(c) for c in candidates_rows}

        # Build a mapping from group_id to work_ids
        group_work_ids: dict[str, list[str]] = {}
        for c in candidates_rows:
            gid = c["group_id"]
            wid = c["work_id"]
            if gid not in group_work_ids:
                group_work_ids[gid] = []
            if wid and wid not in group_work_ids[gid]:
                group_work_ids[gid].append(wid)

        for decision in reviews["decisions"]:
            dtype = decision.get("decision_type", "")
            if dtype == "skip":
                # Skip means "not now, come back later" — don't apply anything
                continue

            if dtype not in VALID_DECISION_TYPES:
                report["errors"].append(f"Unknown decision type: {dtype} for key {decision.get('key')}")
                continue

            group_id = decision.get("group_id", "")
            work_id_a = decision.get("work_id_a", "")
            work_id_b = decision.get("work_id_b", "")
            note = decision.get("note", "")

            if not work_id_a or not work_id_b:
                report["errors"].append(f"Missing work_id for key {decision.get('key')}")
                continue

            # Insert into work_relations
            # For directional types (supersedes, part_of), store as-is.
            # For symmetric types (same_work, not_duplicate, version_of, translation_of),
            # we store one row (work_id_a, work_id_b) — the order is alphabetical for consistency.
            if dtype in ("same_work", "not_duplicate", "version_of", "translation_of"):
                # Symmetric: store with alphabetically smaller id first
                a, b = sorted([work_id_a, work_id_b])
            else:
                # Directional: supersedes (A supersedes B), part_of (A is part of B)
                a, b = work_id_a, work_id_b

            try:
                if dry_run:
                    print(f"  [DRY RUN] Would insert relation: {a} --{dtype}--> {b} (confirmed=1)")
                    report["relations_skipped"] += 1
                else:
                    conn.execute(
                        "INSERT OR REPLACE INTO work_relations (work_id_a, work_id_b, relation_type, confirmed, note) VALUES (?, ?, ?, 1, ?)",
                        (a, b, dtype, note or f"dedup review {decision.get('key', '')}"),
                    )
                    report["relations_inserted"] += 1
            except Exception as e:
                report["errors"].append(f"DB error inserting relation {a}-{b}-{dtype}: {e}")

            # Mark the duplicate candidates in this group as reviewed
            if group_id:
                try:
                    if dry_run:
                        print(f"  [DRY RUN] Would mark group {group_id} candidates as reviewed")
                    else:
                        # We add a 'reviewed' column if it doesn't exist
                        try:
                            conn.execute("ALTER TABLE duplicate_candidates ADD COLUMN reviewed INTEGER DEFAULT 0")
                        except sqlite3.OperationalError:
                            pass  # Column already exists
                        conn.execute(
                            "UPDATE duplicate_candidates SET reviewed = 1 WHERE group_id = ?",
                            (group_id,),
                        )
                        report["candidates_reviewed"] += 1
                except Exception as e:
                    report["errors"].append(f"DB error marking group {group_id} reviewed: {e}")

            # Archive redundant files for same_work decisions
            if archive and dtype == "same_work" and group_id:
                group_info = groups_by_id.get(group_id, {})
                group_type = group_info.get("duplicate_type", "")

                # For exact_sha256 same_work: archive all but the first source file
                if group_type == "exact_sha256":
                    source_files = conn.execute(
                        "SELECT source_file_id, source_path, work_id FROM duplicate_candidates WHERE group_id = ? ORDER BY id",
                        (group_id,),
                    ).fetchall()

                    if len(source_files) > 1:
                        # Keep the first file, archive the rest
                        for sf in source_files[1:]:
                            src_path = sf["source_path"]
                            if src_path and Path(src_path).exists():
                                if dry_run:
                                    print(f"  [DRY RUN] Would archive: {src_path}")
                                else:
                                    rel = Path(src_path).relative_to(library_root) if str(library_root) in str(src_path) else Path(sf["source_file_id"])
                                    dest = archive_dir / "dedup" / rel
                                    dest.parent.mkdir(parents=True, exist_ok=True)
                                    shutil.move(str(src_path), str(dest))
                                    report["files_archived"] += 1

            # Handle quarantine decisions: mark works and optionally move files
            if dtype == "quarantine":
                quarantine_work_ids = set()
                if group_id:
                    # For group-level quarantine, all works in the group get quarantined
                    cands_in_group = conn.execute(
                        "SELECT DISTINCT work_id FROM duplicate_candidates WHERE group_id = ?",
                        (group_id,),
                    ).fetchall()
                    for c in cands_in_group:
                        quarantine_work_ids.add(c["work_id"])
                else:
                    # For pair-level quarantine, quarantine both works
                    quarantine_work_ids.add(work_id_a)
                    quarantine_work_ids.add(work_id_b)

                for qid in quarantine_work_ids:
                    try:
                        if dry_run:
                            print(f"  [DRY RUN] Would quarantine work: {qid}")
                        else:
                            conn.execute(
                                "UPDATE works SET read_status = 'quarantined' WHERE id = ?",
                                (qid,),
                            )
                            # Add work_code for bad_source
                            try:
                                conn.execute(
                                    "INSERT INTO work_codes (work_id, source_file_id, code, reason) VALUES (?, '', 'bad_source', ?)",
                                    (qid, note or f"quarantined: dedup review {decision.get('key', '')}"),
                                )
                            except sqlite3.IntegrityError:
                                # work_id + source_file_id + code combo exists
                                pass
                            report.setdefault("works_quarantined", 0)
                            report["works_quarantined"] += 1

                        # Move source files to _quarantine if archive flag is set
                        if archive:
                            q_sources = conn.execute(
                                "SELECT id, source_path FROM source_files WHERE work_id = ?",
                                (qid,),
                            ).fetchall()
                            for qs in q_sources:
                                src = qs["source_path"]
                                if src and Path(src).exists():
                                    if dry_run:
                                        print(f"  [DRY RUN] Would quarantine file: {src}")
                                    else:
                                        rel = Path(src).relative_to(library_root) if str(library_root) in str(src) else Path(qs["id"])
                                        dest = archive_dir / "quarantine" / rel
                                        dest.parent.mkdir(parents=True, exist_ok=True)
                                        shutil.move(str(src), str(dest))
                                        report["files_archived"] += 1
                    except Exception as e:
                        report["errors"].append(f"Error quarantining {qid}: {e}")

        if not dry_run:
            conn.commit()

    finally:
        conn.close()

    return report


def main() -> None:
    default_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Apply dedup review decisions to the database.")
    parser.add_argument("--library-root", type=Path, default=default_root)
    parser.add_argument("--reviews", type=Path, default=None,
                        help="Path to dedup_reviews.json (default: views/dedup_reviews.json)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be done without making changes")
    parser.add_argument("--archive", action="store_true",
                        help="Archive redundant source files for same_work decisions")
    args = parser.parse_args()

    library_root = args.library_root.resolve()
    reviews_path = args.reviews or library_root / "views" / "dedup_reviews.json"

    if not reviews_path.exists():
        print(f"Reviews file not found: {reviews_path}")
        print("Download dedup_reviews.json from the dedup dashboard first.")
        return

    reviews = load_reviews(reviews_path)
    total = reviews.get("total_decisions", 0)
    non_skip = sum(1 for d in reviews["decisions"] if d.get("decision_type") != "skip")
    print(f"Loaded {total} decisions ({non_skip} non-skip) from {reviews_path}")

    report = apply_decisions(library_root, reviews, dry_run=args.dry_run, archive=args.archive)

    print(f"\nResults:")
    print(f"  Relations inserted: {report['relations_inserted']}")
    print(f"  Relations skipped (dry run): {report['relations_skipped']}")
    print(f"  Candidate groups reviewed: {report['candidates_reviewed']}")
    print(f"  Works quarantined: {report.get('works_quarantined', 0)}")
    print(f"  Files archived: {report['files_archived']}")
    if report["errors"]:
        print(f"  Errors: {len(report['errors'])}")
        for err in report["errors"]:
            print(f"    - {err}")

    # Write a log of what was applied
    log_path = library_root / "views" / f"dedup_apply_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nLog written: {log_path}")


if __name__ == "__main__":
    main()