"""Archive known bad literature source works from the active library.

This removes repair-workspace residue from the active literature library while
keeping a traceable archive and backups under the library root.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.literature_inventory import DEFAULT_OUTPUT_ROOT


BAD_SOURCES = {
    "SF-35d21c463bd4-00144": "E13.full.pdf repair-workspace residue; canonical E13 exists separately.",
    "SF-4bcab5f51805-00145": "E13.pdf repair-workspace residue; canonical E13 exists separately.",
    "SF-d120b950a221-00146": "E14.full.pdf repair-workspace residue; canonical E14 exists separately.",
    "SF-8abc0ebe8052-00147": "E14.pdf repair-workspace residue; canonical E14 exists separately.",
    "SF-4f2e55f96d6b-00148": "E20.full.pdf repair-workspace residue; canonical E20 exists separately.",
    "SF-d8686f26f6d1-00149": "E20.pdf repair-workspace residue; canonical E20 exists separately.",
}


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def source_ids_for_work(work: dict[str, Any]) -> set[str]:
    return {source.get("source_file_id", "") for source in work.get("source_files", [])}


def build_cleanup_plan(library_root: Path) -> dict[str, Any]:
    index_path = library_root / "index.json"
    ledger_path = library_root / "parse_ledger.json"
    db_path = library_root / "literature.sqlite"
    index = read_json(index_path)
    ledger = read_json(ledger_path)

    bad_source_ids = set(BAD_SOURCES)
    bad_works = []
    for work in index.get("works", []):
        matched = source_ids_for_work(work) & bad_source_ids
        if matched:
            if source_ids_for_work(work) - bad_source_ids:
                raise RuntimeError(f"refuse mixed work cleanup: {work.get('work_id')}")
            bad_works.append(work)

    found_source_ids = {source_id for work in bad_works for source_id in source_ids_for_work(work)}
    missing = bad_source_ids - found_source_ids
    if missing:
        raise RuntimeError(f"bad sources not found in index: {sorted(missing)}")

    archive_dir = library_root / "_archive" / f"bad_sources_{utc_stamp()}"
    return {
        "library_root": str(library_root),
        "index_path": str(index_path),
        "ledger_path": str(ledger_path),
        "db_path": str(db_path),
        "archive_dir": str(archive_dir),
        "bad_source_ids": sorted(bad_source_ids),
        "bad_work_ids": [work["work_id"] for work in bad_works],
        "bad_works": bad_works,
        "ledger_entries_to_remove": sorted(source_id for source_id in bad_source_ids if source_id in ledger.get("runs", {})),
    }


def backup_inputs(library_root: Path, archive_dir: Path) -> None:
    backups_dir = archive_dir / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    for name in ("index.json", "parse_ledger.json", "literature.sqlite"):
        source = library_root / name
        if source.exists():
            shutil.copy2(source, backups_dir / f"{name}.before")


def update_index(index_path: Path, bad_work_ids: set[str], bad_source_ids: set[str]) -> dict[str, Any]:
    index = read_json(index_path)
    removed = [work for work in index.get("works", []) if work.get("work_id") in bad_work_ids]
    index["works"] = [work for work in index.get("works", []) if work.get("work_id") not in bad_work_ids]
    index["relations"] = [
        relation
        for relation in index.get("relations", [])
        if relation.get("work_id_a") not in bad_work_ids and relation.get("work_id_b") not in bad_work_ids
    ]

    cleaned_groups = []
    for group in index.get("title_duplicate_groups", []):
        candidates = [
            candidate
            for candidate in group.get("candidates", [])
            if candidate.get("work_id") not in bad_work_ids and candidate.get("source_file_id") not in bad_source_ids
        ]
        if len(candidates) >= 2:
            updated_group = dict(group)
            updated_group["candidates"] = candidates
            updated_group["count"] = len(candidates)
            cleaned_groups.append(updated_group)
    index["title_duplicate_groups"] = cleaned_groups

    summary = dict(index.get("summary", {}))
    summary["works"] = len(index.get("works", []))
    summary["source_pdfs_to_copy"] = sum(len(work.get("source_files", [])) for work in index.get("works", []))
    index["summary"] = summary
    write_json(index_path, index)
    return {"removed_works": removed, "remaining_works": len(index.get("works", []))}


def update_ledger(ledger_path: Path, bad_source_ids: set[str]) -> dict[str, Any]:
    ledger = read_json(ledger_path)
    runs = ledger.setdefault("runs", {})
    removed = {source_id: runs.pop(source_id) for source_id in list(runs) if source_id in bad_source_ids}
    write_json(ledger_path, ledger)
    return {"removed_runs": removed, "remaining_runs": len(runs)}


def update_database(db_path: Path, bad_work_ids: set[str], bad_source_ids: set[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("BEGIN")

        def delete(table: str, column: str, values: set[str]) -> None:
            if not values:
                counts[f"{table}.{column}"] = 0
                return
            placeholders = ",".join("?" for _ in values)
            cursor = conn.execute(f"DELETE FROM {table} WHERE {column} IN ({placeholders})", tuple(sorted(values)))
            counts[f"{table}.{column}"] = cursor.rowcount

        delete("literature_parse_runs", "source_file_id", bad_source_ids)
        delete("parse_artifacts", "source_file_id", bad_source_ids)
        delete("library_migration_files", "source_file_id", bad_source_ids)
        delete("source_files", "id", bad_source_ids)
        delete("work_codes", "source_file_id", bad_source_ids)
        delete("duplicate_candidates", "source_file_id", bad_source_ids)
        delete("work_relations", "work_id_a", bad_work_ids)
        delete("work_relations", "work_id_b", bad_work_ids)
        delete("works", "id", bad_work_ids)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return counts


def archive_work_dirs(library_root: Path, archive_dir: Path, bad_work_ids: set[str]) -> list[dict[str, str]]:
    archived = []
    works_archive = archive_dir / "works"
    works_archive.mkdir(parents=True, exist_ok=True)
    for work_id in sorted(bad_work_ids):
        source = library_root / "works" / work_id
        destination = works_archive / work_id
        if not source.exists():
            archived.append({"work_id": work_id, "status": "missing", "from": str(source), "to": str(destination)})
            continue
        if destination.exists():
            raise RuntimeError(f"archive destination already exists: {destination}")
        shutil.move(str(source), str(destination))
        archived.append({"work_id": work_id, "status": "archived", "from": str(source), "to": str(destination)})
    return archived


def execute_cleanup(plan: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    library_root = Path(plan["library_root"])
    archive_dir = Path(plan["archive_dir"])
    bad_work_ids = set(plan["bad_work_ids"])
    bad_source_ids = set(plan["bad_source_ids"])

    result = dict(plan)
    result["dry_run"] = dry_run
    result["cleaned_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if dry_run:
        return result

    archive_dir.mkdir(parents=True, exist_ok=False)
    backup_inputs(library_root, archive_dir)
    result["index_update"] = update_index(Path(plan["index_path"]), bad_work_ids, bad_source_ids)
    result["ledger_update"] = update_ledger(Path(plan["ledger_path"]), bad_source_ids)
    result["database_update"] = update_database(Path(plan["db_path"]), bad_work_ids, bad_source_ids)
    result["archived_work_dirs"] = archive_work_dirs(library_root, archive_dir, bad_work_ids)
    write_json(archive_dir / "manifest.json", result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Archive known bad repair-workspace source works.")
    parser.add_argument("--library-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    plan = build_cleanup_plan(args.library_root.resolve())
    result = execute_cleanup(plan, dry_run=not args.execute)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
