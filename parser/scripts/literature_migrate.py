"""Phase 2 migration for the local literature library.

The script is intentionally conservative:
- dry-run by default
- never deletes or moves files from the original literature_read directory
- copies only the canonical file for exact sha256 duplicates into works/
- optionally archives non-canonical exact duplicates under _duplicates/
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.literature_inventory import DEFAULT_OUTPUT_ROOT, DEFAULT_SOURCE_ROOT, sha256_file
from scripts.migration_decisions import CANONICAL_MAP, CODE_OVERRIDES, SKIP_TEMPLATE_EXTRACTS


MIGRATION_VERSION = "literature_phase2_v1"


@dataclass
class MigrationPlan:
    generated_at: str
    db_path: str
    source_root: str
    library_root: str
    options: dict[str, Any]
    works: list[dict[str, Any]] = field(default_factory=list)
    copied_sources: list[dict[str, Any]] = field(default_factory=list)
    duplicate_sources: list[dict[str, Any]] = field(default_factory=list)
    template_extracts: list[dict[str, Any]] = field(default_factory=list)
    code_overrides: list[dict[str, Any]] = field(default_factory=list)
    relations: list[dict[str, Any]] = field(default_factory=list)
    title_duplicate_groups: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "migration_version": MIGRATION_VERSION,
            "generated_at": self.generated_at,
            "db_path": self.db_path,
            "source_root": self.source_root,
            "library_root": self.library_root,
            "options": self.options,
            "summary": self.summary(),
            "works": self.works,
            "copied_sources": self.copied_sources,
            "duplicate_sources": self.duplicate_sources,
            "template_extracts": self.template_extracts,
            "code_overrides": self.code_overrides,
            "relations": self.relations,
            "title_duplicate_groups": self.title_duplicate_groups,
            "warnings": self.warnings,
        }

    def summary(self) -> dict[str, int]:
        copied_templates = sum(1 for item in self.template_extracts if item["action"] == "copy")
        skipped_templates = sum(1 for item in self.template_extracts if item["action"] == "skip")
        archived_duplicates = sum(1 for item in self.duplicate_sources if item["action"] == "archive")
        skipped_duplicates = sum(1 for item in self.duplicate_sources if item["action"] == "skip")
        return {
            "works": len(self.works),
            "source_pdfs_to_copy": len(self.copied_sources),
            "exact_duplicates_to_archive": archived_duplicates,
            "exact_duplicates_to_skip": skipped_duplicates,
            "template_extracts_to_copy": copied_templates,
            "template_extracts_to_skip": skipped_templates,
            "code_overrides": len(self.code_overrides),
            "relations": len(self.relations),
            "title_duplicate_groups_for_review": len(self.title_duplicate_groups),
            "warnings": len(self.warnings),
        }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_rows(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def normalize_authors(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return [value]
    if isinstance(parsed, list):
        return [str(item) for item in parsed if str(item).strip()]
    if isinstance(parsed, str) and parsed.strip():
        return [parsed]
    return []


def relative_depth(relative_path: str) -> int:
    return len(PureWindowsPath(relative_path).parts)


def informativeness_score(original_name: str) -> int:
    stem = Path(original_name).stem
    lower = stem.lower()
    score = min(len(stem), 100)
    if re.match(r"^\[[A-Za-z]\d", stem):
        score += 120
    if "arxiv" in lower:
        score += 90
    if re.match(r"^[A-Za-z]{1,2}\d+[a-z]?$", stem):
        score -= 80
    if len(stem.split("_")) >= 3 or len(stem.split("-")) >= 3:
        score += 40
    return score


def canonical_sort_key(row: dict[str, Any]) -> tuple[int, int, int, str]:
    return (
        relative_depth(row["relative_source_path"]),
        -informativeness_score(row["original_name"] or ""),
        len(row["relative_source_path"]),
        row["relative_source_path"],
    )


def choose_duplicate_canonical(
    digest: str,
    rows: list[dict[str, Any]],
    warnings: list[str],
    strict_decisions: bool,
) -> dict[str, Any]:
    decision_name = CANONICAL_MAP.get(digest)
    if decision_name:
        matches = [row for row in rows if row["original_name"] == decision_name]
        if matches:
            return sorted(matches, key=canonical_sort_key)[0]
        message = f"canonical decision for sha {digest[:12]} not found: {decision_name}"
        if strict_decisions:
            raise ValueError(message)
        warnings.append(message)

    chosen = sorted(rows, key=canonical_sort_key)[0]
    warnings.append(
        "no canonical decision for exact duplicate sha "
        f"{digest[:12]}; chose {chosen['relative_source_path']}"
    )
    return chosen


def destination_filename(row: dict[str, Any], used_names: set[str]) -> str:
    name = row["original_name"] or f"{row['id']}.pdf"
    if name not in used_names:
        used_names.add(name)
        return name
    prefixed = f"{row['id']}_{name}"
    used_names.add(prefixed)
    return prefixed


def source_path_for(row: dict[str, Any], source_root: Path) -> Path:
    source_path = Path(row["source_path"])
    if source_path.is_absolute():
        return source_path
    return source_root / row["relative_source_path"]


def artifact_source_path(artifact: dict[str, Any], source_root: Path) -> Path:
    raw_path = Path(artifact["file_path"])
    if raw_path.is_absolute():
        return raw_path
    return source_root / artifact["file_path"]


def relative_to_library(path: Path, library_root: Path) -> str:
    try:
        return str(path.relative_to(library_root))
    except ValueError:
        return str(path)


def build_migration_plan(
    db_path: Path,
    source_root: Path,
    library_root: Path,
    *,
    archive_duplicates: bool = True,
    include_template_extracts: bool = False,
    strict_decisions: bool = True,
) -> MigrationPlan:
    plan = MigrationPlan(
        generated_at=utc_now(),
        db_path=str(db_path),
        source_root=str(source_root),
        library_root=str(library_root),
        options={
            "archive_duplicates": archive_duplicates,
            "include_template_extracts": include_template_extracts,
            "skip_template_extracts_decision": SKIP_TEMPLATE_EXTRACTS,
            "strict_decisions": strict_decisions,
        },
    )

    conn = connect_db(db_path)
    try:
        works = {
            row["id"]: row
            for row in fetch_rows(
                conn,
                """
                SELECT id, title, authors, year, arxiv_id, doi, doc_type, language,
                       metadata_status, parse_status, read_status, created_at, updated_at
                FROM works
                ORDER BY id
                """,
            )
        }
        sources = fetch_rows(
            conn,
            """
            SELECT id, work_id, content_sha256, original_name, source_path,
                   relative_source_path, file_size, file_ext, import_time, mtime
            FROM source_files
            ORDER BY work_id, relative_source_path, id
            """,
        )
        artifacts = fetch_rows(
            conn,
            """
            SELECT id, work_id, source_file_id, type, file_path, parser, parse_time, task_id
            FROM parse_artifacts
            ORDER BY work_id, source_file_id, id
            """,
        )
        title_groups = fetch_rows(
            conn,
            """
            SELECT id, duplicate_type, key, count
            FROM duplicate_groups
            WHERE duplicate_type = 'title_candidate'
            ORDER BY id
            """,
        )
        title_candidates = fetch_rows(
            conn,
            """
            SELECT id, group_id, source_file_id, work_id, source_path, score, reason
            FROM duplicate_candidates
            WHERE group_id IN (
                SELECT id FROM duplicate_groups WHERE duplicate_type = 'title_candidate'
            )
            ORDER BY group_id, id
            """,
        )
    finally:
        conn.close()

    for row in sources:
        if not source_path_for(row, source_root).exists():
            plan.warnings.append(f"source file missing: {row['source_path']}")

    by_hash: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_work: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_by_id = {row["id"]: row for row in sources}
    source_by_original_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sources:
        by_hash[row["content_sha256"]].append(row)
        by_work[row["work_id"]].append(row)
        source_by_original_name[row["original_name"]].append(row)

    canonical_source_by_hash: dict[str, str] = {}
    duplicate_source_ids: set[str] = set()
    for digest, rows in sorted(by_hash.items()):
        if len(rows) <= 1:
            continue
        canonical = choose_duplicate_canonical(digest, rows, plan.warnings, strict_decisions)
        canonical_source_by_hash[digest] = canonical["id"]
        duplicate_source_ids.update(row["id"] for row in rows if row["id"] != canonical["id"])

    copied_by_work: dict[str, list[dict[str, Any]]] = defaultdict(list)
    duplicate_by_work: dict[str, list[dict[str, Any]]] = defaultdict(list)
    used_names_by_work: dict[str, set[str]] = defaultdict(set)

    for work_id, rows in sorted(by_work.items()):
        for row in sorted(rows, key=canonical_sort_key):
            src = source_path_for(row, source_root)
            if row["id"] in duplicate_source_ids:
                archive_path = (
                    library_root
                    / "_duplicates"
                    / "exact_sha256"
                    / row["content_sha256"][:12]
                    / f"{row['id']}_{row['original_name']}"
                )
                item = {
                    "source_file_id": row["id"],
                    "work_id": row["work_id"],
                    "content_sha256": row["content_sha256"],
                    "original_name": row["original_name"],
                    "source_path": str(src),
                    "relative_source_path": row["relative_source_path"],
                    "canonical_source_file_id": canonical_source_by_hash.get(row["content_sha256"], ""),
                    "action": "archive" if archive_duplicates else "skip",
                    "archive_path": str(archive_path) if archive_duplicates else "",
                    "archive_relative_path": relative_to_library(archive_path, library_root) if archive_duplicates else "",
                }
                plan.duplicate_sources.append(item)
                duplicate_by_work[work_id].append(item)
                continue

            filename = destination_filename(row, used_names_by_work[work_id])
            dest = library_root / "works" / work_id / "source" / filename
            item = {
                "source_file_id": row["id"],
                "work_id": row["work_id"],
                "content_sha256": row["content_sha256"],
                "original_name": row["original_name"],
                "source_path": str(src),
                "relative_source_path": row["relative_source_path"],
                "file_size": row["file_size"],
                "file_ext": row["file_ext"],
                "library_path": str(dest),
                "library_relative_path": relative_to_library(dest, library_root),
                "role": "canonical_source",
            }
            plan.copied_sources.append(item)
            copied_by_work[work_id].append(item)

    artifacts_by_work: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for artifact in artifacts:
        if artifact["type"] != "template_extract":
            continue
        src = artifact_source_path(artifact, source_root)
        action = "copy" if include_template_extracts else "skip"
        dest = (
            library_root
            / "works"
            / artifact["work_id"]
            / "parsed"
            / "template_extracts"
            / Path(artifact["file_path"]).name
        )
        item = {
            "artifact_id": artifact["id"],
            "work_id": artifact["work_id"],
            "source_file_id": artifact["source_file_id"],
            "type": artifact["type"],
            "parser": artifact["parser"],
            "source_path": str(src),
            "file_path": artifact["file_path"],
            "action": action,
            "library_path": str(dest) if action == "copy" else "",
            "library_relative_path": relative_to_library(dest, library_root) if action == "copy" else "",
        }
        plan.template_extracts.append(item)
        artifacts_by_work[artifact["work_id"]].append(item)

    for row in sources:
        override = CODE_OVERRIDES.get(row["original_name"])
        if not override:
            continue
        code_item = {
            "work_id": row["work_id"],
            "source_file_id": row["id"],
            "original_name": row["original_name"],
            "code": override["code"],
            "reason": "migration_decisions.CODE_OVERRIDES",
        }
        plan.code_overrides.append(code_item)

        relation = override.get("relation")
        if relation:
            target_rows = source_by_original_name.get(relation["target_original_name"], [])
            if target_rows:
                target = sorted(target_rows, key=canonical_sort_key)[0]
                plan.relations.append(
                    {
                        "work_id_a": row["work_id"],
                        "work_id_b": target["work_id"],
                        "relation_type": relation["type"],
                        "confirmed": 1,
                        "note": (
                            f"{row['original_name']} {relation['type']} "
                            f"{relation['target_original_name']} (migration decision)"
                        ),
                    }
                )
            else:
                plan.warnings.append(
                    "relation target not found for "
                    f"{row['original_name']}: {relation['target_original_name']}"
                )

    candidates_by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in title_candidates:
        candidates_by_group[candidate["group_id"]].append(candidate)
    for group in title_groups:
        plan.title_duplicate_groups.append(
            {
                "id": group["id"],
                "key": group["key"],
                "count": group["count"],
                "action": "review_only",
                "candidates": candidates_by_group.get(group["id"], []),
            }
        )

    codes_by_work: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in plan.code_overrides:
        codes_by_work[item["work_id"]].append(item)

    for work_id, work in sorted(works.items()):
        copied = copied_by_work.get(work_id, [])
        duplicates = duplicate_by_work.get(work_id, [])
        templates = artifacts_by_work.get(work_id, [])
        work_dir = library_root / "works" / work_id
        plan.works.append(
            {
                "work_id": work_id,
                "title": work["title"],
                "authors": normalize_authors(work["authors"]),
                "year": work["year"],
                "arxiv_id": work["arxiv_id"],
                "doi": work["doi"],
                "doc_type": work["doc_type"],
                "language": work["language"],
                "metadata_status": work["metadata_status"],
                "parse_status": work["parse_status"],
                "read_status": work["read_status"],
                "work_dir": str(work_dir),
                "work_relative_dir": relative_to_library(work_dir, library_root),
                "metadata_path": str(work_dir / "metadata.json"),
                "source_files": copied,
                "exact_duplicates": duplicates,
                "template_extracts": templates,
                "codes": codes_by_work.get(work_id, []),
            }
        )

    return plan


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def copy_file(source: Path, destination: Path, expected_sha256: str = "", overwrite: bool = False) -> bool:
    if not source.exists():
        raise FileNotFoundError(source)
    ensure_parent(destination)
    if destination.exists():
        if expected_sha256 and sha256_file(destination) == expected_sha256:
            return False
        if not overwrite:
            raise FileExistsError(f"destination exists with different content: {destination}")
    shutil.copy2(source, destination)
    return True


def write_json(path: Path, payload: dict[str, Any]) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text_if_missing(path: Path, content: str) -> None:
    ensure_parent(path)
    if not path.exists():
        path.write_text(content, encoding="utf-8")


def metadata_for_work(work: dict[str, Any], plan: MigrationPlan) -> dict[str, Any]:
    return {
        "migration_version": MIGRATION_VERSION,
        "generated_at": plan.generated_at,
        "work_id": work["work_id"],
        "title": work["title"],
        "authors": work["authors"],
        "year": work["year"],
        "arxiv_id": work["arxiv_id"],
        "doi": work["doi"],
        "doc_type": work["doc_type"],
        "language": work["language"],
        "metadata_status": work["metadata_status"],
        "parse_status": work["parse_status"],
        "read_status": work["read_status"],
        "codes": work["codes"],
        "source_files": work["source_files"],
        "exact_duplicates": work["exact_duplicates"],
        "template_extracts": work["template_extracts"],
    }


def frontend_index(plan: MigrationPlan) -> dict[str, Any]:
    return {
        "migration_version": MIGRATION_VERSION,
        "generated_at": plan.generated_at,
        "library_root": plan.library_root,
        "summary": plan.summary(),
        "works": [
            {
                "work_id": work["work_id"],
                "title": work["title"],
                "authors": work["authors"],
                "year": work["year"],
                "arxiv_id": work["arxiv_id"],
                "doi": work["doi"],
                "doc_type": work["doc_type"],
                "language": work["language"],
                "metadata_status": work["metadata_status"],
                "parse_status": work["parse_status"],
                "read_status": work["read_status"],
                "work_relative_dir": work["work_relative_dir"],
                "source_files": [
                    {
                        "source_file_id": item["source_file_id"],
                        "original_name": item["original_name"],
                        "library_relative_path": item["library_relative_path"],
                        "content_sha256": item["content_sha256"],
                    }
                    for item in work["source_files"]
                ],
                "codes": work["codes"],
                "exact_duplicate_count": len(work["exact_duplicates"]),
                "template_extract_count": len(work["template_extracts"]),
            }
            for work in plan.works
        ],
        "relations": plan.relations,
        "title_duplicate_groups": plan.title_duplicate_groups,
        "warnings": plan.warnings,
    }


def migration_report(plan: MigrationPlan) -> str:
    summary = plan.summary()
    lines = [
        "# Literature Migration Report",
        "",
        f"> Generated: {plan.generated_at}",
        f"> Source root: `{plan.source_root}`",
        f"> Library root: `{plan.library_root}`",
        f"> SQLite: `{plan.db_path}`",
        "",
        "## Summary",
        "",
    ]
    for key, value in summary.items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Exact Duplicates", ""])
    duplicates = plan.duplicate_sources
    if duplicates:
        for item in duplicates:
            lines.append(
                f"- {item['action']}: `{item['relative_source_path']}` "
                f"-> `{item['archive_relative_path'] or item['canonical_source_file_id']}`"
            )
    else:
        lines.append("No exact duplicates outside canonical sources.")

    lines.extend(["", "## Code Overrides", ""])
    if plan.code_overrides:
        for item in plan.code_overrides:
            lines.append(f"- `{item['original_name']}` -> `{item['code']}`")
    else:
        lines.append("No code overrides.")

    lines.extend(["", "## Title Duplicate Review Queue", ""])
    if plan.title_duplicate_groups:
        for group in plan.title_duplicate_groups:
            lines.append(f"- `{group['id']}` ({group['count']}): {group['key']}")
    else:
        lines.append("No title duplicate candidates.")

    if plan.warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in plan.warnings:
            lines.append(f"- {warning}")

    lines.append("")
    return "\n".join(lines)


def ensure_migration_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS migration_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS library_migration_files (
            id TEXT PRIMARY KEY,
            source_file_id TEXT,
            artifact_id TEXT,
            work_id TEXT NOT NULL,
            role TEXT NOT NULL,
            original_source_path TEXT,
            library_path TEXT,
            content_sha256 TEXT,
            migrated_at TEXT,
            migration_version TEXT,
            note TEXT
        );

        CREATE TABLE IF NOT EXISTS work_codes (
            work_id TEXT NOT NULL,
            source_file_id TEXT NOT NULL,
            code TEXT NOT NULL,
            reason TEXT,
            created_at TEXT,
            PRIMARY KEY (work_id, source_file_id, code)
        );

        CREATE TABLE IF NOT EXISTS work_relations (
            work_id_a TEXT NOT NULL,
            work_id_b TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            confirmed INTEGER DEFAULT 0,
            note TEXT,
            PRIMARY KEY (work_id_a, work_id_b, relation_type)
        );
        """
    )


def update_database(plan: MigrationPlan, db_path: Path) -> None:
    conn = connect_db(db_path)
    try:
        ensure_migration_schema(conn)
        now = utc_now()
        conn.executemany(
            """
            INSERT OR REPLACE INTO migration_meta(key, value)
            VALUES (?, ?)
            """,
            [
                ("migration_version", MIGRATION_VERSION),
                ("migrated_at", now),
                ("source_root", plan.source_root),
                ("library_root", plan.library_root),
                ("summary", json.dumps(plan.summary(), ensure_ascii=False)),
            ],
        )

        file_rows = []
        for item in plan.copied_sources:
            file_rows.append(
                (
                    f"MF-{item['source_file_id']}",
                    item["source_file_id"],
                    "",
                    item["work_id"],
                    "canonical_source",
                    item["source_path"],
                    item["library_path"],
                    item["content_sha256"],
                    now,
                    MIGRATION_VERSION,
                    "",
                )
            )
        for item in plan.duplicate_sources:
            role = "exact_duplicate_archived" if item["action"] == "archive" else "exact_duplicate_skipped"
            file_rows.append(
                (
                    f"MF-{item['source_file_id']}",
                    item["source_file_id"],
                    "",
                    item["work_id"],
                    role,
                    item["source_path"],
                    item["archive_path"],
                    item["content_sha256"],
                    now,
                    MIGRATION_VERSION,
                    f"canonical_source_file_id={item['canonical_source_file_id']}",
                )
            )
        for item in plan.template_extracts:
            role = "template_extract_copied" if item["action"] == "copy" else "template_extract_skipped"
            file_rows.append(
                (
                    f"MF-{item['artifact_id']}",
                    item["source_file_id"],
                    item["artifact_id"],
                    item["work_id"],
                    role,
                    item["source_path"],
                    item["library_path"],
                    "",
                    now,
                    MIGRATION_VERSION,
                    f"parser={item['parser']}",
                )
            )

        conn.executemany(
            """
            INSERT OR REPLACE INTO library_migration_files(
                id, source_file_id, artifact_id, work_id, role, original_source_path,
                library_path, content_sha256, migrated_at, migration_version, note
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            file_rows,
        )

        conn.executemany(
            """
            INSERT OR REPLACE INTO work_codes(work_id, source_file_id, code, reason, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (item["work_id"], item["source_file_id"], item["code"], item["reason"], now)
                for item in plan.code_overrides
            ],
        )

        conn.executemany(
            """
            INSERT OR REPLACE INTO work_relations(work_id_a, work_id_b, relation_type, confirmed, note)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    item["work_id_a"],
                    item["work_id_b"],
                    item["relation_type"],
                    item["confirmed"],
                    item["note"],
                )
                for item in plan.relations
            ],
        )
        conn.commit()
    finally:
        conn.close()


def execute_plan(
    plan: MigrationPlan,
    db_path: Path,
    library_root: Path,
    *,
    overwrite: bool = False,
    update_db: bool = True,
) -> None:
    source_root = Path(plan.source_root).resolve()
    resolved_library_root = library_root.resolve()
    if source_root == resolved_library_root:
        raise ValueError("library root must be different from source root")

    for dirname in ["_inbox", "_duplicates", "_quarantine", "views", "works"]:
        (library_root / dirname).mkdir(parents=True, exist_ok=True)

    for work in plan.works:
        work_dir = Path(work["work_dir"])
        for dirname in ["source", "parsed", "notes", "analyses"]:
            (work_dir / dirname).mkdir(parents=True, exist_ok=True)
        write_json(Path(work["metadata_path"]), metadata_for_work(work, plan))
        write_text_if_missing(
            work_dir / "notes" / "reading.md",
            f"# Reading Notes\n\n- Work: {work['work_id']}\n",
        )

    for item in plan.copied_sources:
        copy_file(
            Path(item["source_path"]),
            Path(item["library_path"]),
            expected_sha256=item["content_sha256"],
            overwrite=overwrite,
        )

    for item in plan.duplicate_sources:
        if item["action"] != "archive":
            continue
        copy_file(
            Path(item["source_path"]),
            Path(item["archive_path"]),
            expected_sha256=item["content_sha256"],
            overwrite=overwrite,
        )

    for item in plan.template_extracts:
        if item["action"] != "copy":
            continue
        copy_file(Path(item["source_path"]), Path(item["library_path"]), overwrite=overwrite)

    write_json(library_root / "index.json", frontend_index(plan))
    (library_root / "migration_report.md").write_text(migration_report(plan), encoding="utf-8")
    write_json(library_root / "migration_plan.json", plan.as_dict())

    if update_db:
        update_database(plan, db_path)


def print_summary(plan: MigrationPlan, *, executed: bool) -> None:
    mode = "executed" if executed else "dry-run"
    print(f"Migration mode: {mode}")
    for key, value in plan.summary().items():
        print(f"{key}: {value}")
    if plan.warnings:
        print("warnings:")
        for warning in plan.warnings[:20]:
            print(f"- {warning}")
        if len(plan.warnings) > 20:
            print(f"- ... {len(plan.warnings) - 20} more")
    if not executed:
        print("No files were changed. Re-run with --execute to copy files and update the database.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate Phase 0 literature inventory into works/ layout.")
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT, help="Original literature_read root.")
    parser.add_argument("--library-root", type=Path, default=DEFAULT_OUTPUT_ROOT, help="Target literature_library root.")
    parser.add_argument("--db", type=Path, default=None, help="Inventory SQLite path. Defaults to library_root/literature.sqlite.")
    parser.add_argument("--execute", action="store_true", help="Actually copy files and update SQLite.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite generated files if destination differs.")
    parser.add_argument("--no-db-update", action="store_true", help="Do not update migration tables in SQLite.")
    parser.add_argument("--no-archive-duplicates", action="store_true", help="Do not copy exact duplicates into _duplicates/.")
    parser.add_argument(
        "--include-template-extracts",
        action="store_true",
        help="Copy legacy template-extract Markdown files despite the default skip decision.",
    )
    parser.add_argument(
        "--no-strict-decisions",
        action="store_true",
        help="Warn instead of failing if a canonical decision no longer matches the inventory.",
    )
    parser.add_argument("--write-plan", type=Path, default=None, help="Optional path to write dry-run plan JSON.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_root = args.source_root.resolve()
    library_root = args.library_root.resolve()
    db_path = (args.db or library_root / "literature.sqlite").resolve()

    if not db_path.exists():
        raise SystemExit(f"inventory database not found: {db_path}")
    if not source_root.exists():
        raise SystemExit(f"source root not found: {source_root}")

    plan = build_migration_plan(
        db_path,
        source_root,
        library_root,
        archive_duplicates=not args.no_archive_duplicates,
        include_template_extracts=args.include_template_extracts,
        strict_decisions=not args.no_strict_decisions,
    )

    if args.write_plan:
        write_json(args.write_plan, plan.as_dict())

    if args.execute:
        execute_plan(
            plan,
            db_path,
            library_root,
            overwrite=args.overwrite,
            update_db=not args.no_db_update,
        )
        print_summary(plan, executed=True)
    else:
        print_summary(plan, executed=False)


if __name__ == "__main__":
    main()
