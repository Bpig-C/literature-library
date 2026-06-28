"""Phase 1 inbox ingestion for the local literature library.

The runner is conservative by default: it only prints a plan unless
``--execute`` is passed. Executed ingests copy PDFs from ``_inbox`` into
``works/{work_id}/source/``, archive the inbox copy, update SQLite, append
pending parse jobs to ``literature_parse_runs`` (DB), and refresh ``index.json``.
Exact sha256 duplicates are archived under ``_duplicates/exact_sha256``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import shutil
import sqlite3
import sys
import warnings
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadWarning

    warnings.filterwarnings("ignore", category=PdfReadWarning)
except Exception:  # pragma: no cover - optional dependency
    PdfReader = None  # type: ignore[assignment]
logging.getLogger("pypdf").setLevel(logging.ERROR)


INGEST_VERSION = "literature_phase1_ingest_v1"
DEFAULT_BACKEND = "pipeline"
DEFAULT_PARSE_METHOD = "auto"
ARXIV_RE = re.compile(r"(?i)(?:arxiv[:\-_ ]*)?(\d{4}\.\d{4,5})(v\d+)?")
DOI_RE = re.compile(r"(?i)\b(10\.\d{4,9}/[^\s<>()\[\]{}\"']+)")
STOPWORDS = {"a", "an", "the", "in", "of", "for", "on", "to", "and", "with", "by"}
SF_ID_RE = re.compile(r"^SF-[0-9a-f]{12}-(\d{5})$")


@dataclass
class Metadata:
    title: str
    authors: list[str]
    year: int | None
    arxiv_id: str
    doi: str
    doc_type: str
    language: str
    metadata_status: str


@dataclass
class DuplicateAction:
    inbox_path: str
    archive_path: str
    content_sha256: str
    existing_work_id: str
    existing_source_file_id: str
    original_name: str
    file_size: int


@dataclass
class IngestAction:
    inbox_path: str
    library_path: str
    archive_path: str
    content_sha256: str
    source_file_id: str
    work_id: str
    existing_work: bool
    original_name: str
    file_size: int
    metadata: Metadata
    title_duplicate_candidates: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class IngestPlan:
    generated_at: str
    library_root: str
    inbox_dir: str
    dry_run: bool
    ingests: list[IngestAction] = field(default_factory=list)
    exact_duplicates: list[DuplicateAction] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        return {
            "ingests": len(self.ingests),
            "exact_duplicates": len(self.exact_duplicates),
            "skipped": len(self.skipped),
            "title_duplicate_candidates": sum(
                len(item.title_duplicate_candidates) for item in self.ingests
            ),
            "warnings": len(self.warnings),
        }

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ingest_version"] = INGEST_VERSION
        data["summary"] = self.summary()
        return data


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def file_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(
        timespec="seconds"
    )


def normalize_doi(value: str) -> str:
    value = value.strip().rstrip(".,;:)")
    value = re.sub(r"(?i)^https?://(?:dx\.)?doi\.org/", "", value)
    return value.lower()


def doi_to_work_id(doi: str) -> str:
    safe = re.sub(r"[^a-z0-9]+", "-", doi.lower()).strip("-")
    return f"W-doi-{safe}"


def extract_arxiv_id(text: str) -> str:
    match = ARXIV_RE.search(text)
    if not match:
        return ""
    return f"{match.group(1)}{match.group(2) or ''}"


def arxiv_work_key(arxiv_id: str) -> str:
    return re.sub(r"(?i)v\d+$", "", arxiv_id)


def extract_doi(text: str) -> str:
    match = DOI_RE.search(text)
    return normalize_doi(match.group(1)) if match else ""


def normalize_title(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\[[^\]]+\]", " ", text)
    text = re.sub(r"【[^】]+】", " ", text)
    text = re.sub(r"arxiv[-_: ]*\d{4}\.\d{4,5}(v\d+)?", " ", text)
    text = re.sub(r"\b\d{4,8}\b", " ", text)
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
    tokens = [token for token in text.split() if token not in STOPWORDS]
    return " ".join(tokens)


def jaccard(left_text: str, right_text: str) -> float:
    left = set(left_text.split())
    right = set(right_text.split())
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def guess_year(text: str) -> int | None:
    years = [int(match.group(0)) for match in re.finditer(r"\b(?:19|20)\d{2}\b", text)]
    plausible = [year for year in years if 1900 <= year <= 2100]
    return min(plausible) if plausible else None


def guess_language(text: str) -> str:
    return "zh" if re.search(r"[\u4e00-\u9fff]", text) else "en"


def guess_doc_type(text: str, arxiv_id: str) -> str:
    lower = text.lower()
    if "benchmark" in lower or "eval" in lower:
        return "benchmark"
    if "system card" in lower or "model card" in lower:
        return "system_card"
    if "report" in lower or "framework" in lower or "standard" in lower:
        return "report"
    if arxiv_id:
        return "preprint"
    return "paper"


def safe_pdf_metadata(path: Path) -> dict[str, str]:
    if PdfReader is None:
        return {}
    try:
        reader = PdfReader(str(path))
        raw = reader.metadata or {}
    except Exception:
        return {}

    metadata: dict[str, str] = {}
    for key, value in raw.items():
        if value is None:
            continue
        metadata[str(key).lstrip("/").lower()] = str(value).strip()
    return metadata


def clean_title_from_filename(path: Path) -> str:
    stem = path.stem
    stem = re.sub(r"^\[[A-Za-z]\d+[a-z]?(?:-[A-Za-z\d]+)?\]_", "", stem)
    stem = re.sub(r"^[A-Z]{1,2}\d+[a-z]?_", "", stem)
    stem = re.sub(r"^【R】", "", stem)
    stem = re.sub(r"arxiv[-_: ]*\d{4}\.\d{4,5}(v\d+)?", "", stem, flags=re.I)
    stem = re.sub(r"\([^)]*\)", " ", stem)
    stem = stem.replace("_", " ")
    stem = re.sub(r"\s*-\s*", " - ", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" -_")
    return stem or path.stem


def extract_metadata(path: Path) -> Metadata:
    pdf_metadata = safe_pdf_metadata(path)
    candidate_text = " ".join(
        [
            path.name,
            path.stem,
            pdf_metadata.get("title", ""),
            pdf_metadata.get("author", ""),
            pdf_metadata.get("subject", ""),
        ]
    )
    arxiv_id = extract_arxiv_id(candidate_text)
    doi = extract_doi(candidate_text)
    title = pdf_metadata.get("title") or clean_title_from_filename(path)
    authors = []
    if pdf_metadata.get("author"):
        authors = [item.strip() for item in re.split(r";|,|\band\b", pdf_metadata["author"]) if item.strip()]
    year = guess_year(candidate_text)
    status = "auto" if (arxiv_id or doi) else ("needs_review" if pdf_metadata.get("title") else "missing")
    return Metadata(
        title=title,
        authors=authors,
        year=year,
        arxiv_id=arxiv_id,
        doi=doi,
        doc_type=guess_doc_type(candidate_text, arxiv_id),
        language=guess_language(candidate_text),
        metadata_status=status,
    )


def connect_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_core_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS works (
            id TEXT PRIMARY KEY,
            title TEXT,
            authors TEXT,
            year INTEGER,
            arxiv_id TEXT,
            doi TEXT,
            doc_type TEXT,
            language TEXT DEFAULT 'unknown',
            metadata_status TEXT DEFAULT 'auto',
            parse_status TEXT DEFAULT 'unknown',
            read_status TEXT DEFAULT 'unread',
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS source_files (
            id TEXT PRIMARY KEY,
            work_id TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            original_name TEXT,
            source_path TEXT NOT NULL,
            relative_source_path TEXT NOT NULL,
            file_size INTEGER,
            file_ext TEXT,
            import_time TEXT,
            mtime TEXT
        );
        CREATE TABLE IF NOT EXISTS literature_parse_runs (
            id TEXT PRIMARY KEY,
            work_id TEXT NOT NULL,
            source_file_id TEXT NOT NULL,
            source_path TEXT NOT NULL,
            task_id TEXT,
            status TEXT NOT NULL,
            backend TEXT,
            parse_method TEXT,
            file_size INTEGER,
            started_at TEXT,
            finished_at TEXT,
            output_dir TEXT,
            error TEXT,
            content_json_path TEXT,
            content_md_path TEXT,
            package_path TEXT
        );
        CREATE TABLE IF NOT EXISTS duplicate_groups (
            id TEXT PRIMARY KEY,
            duplicate_type TEXT NOT NULL,
            key TEXT NOT NULL,
            count INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS duplicate_candidates (
            id TEXT PRIMARY KEY,
            group_id TEXT,
            source_file_id TEXT,
            work_id TEXT,
            source_path TEXT,
            score REAL,
            reason TEXT
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
        """
    )


def fetch_existing_state(conn: sqlite3.Connection) -> dict[str, Any]:
    ensure_core_schema(conn)
    sources = [dict(row) for row in conn.execute("SELECT * FROM source_files").fetchall()]
    works = [dict(row) for row in conn.execute("SELECT * FROM works").fetchall()]

    digest_map: dict[str, dict[str, Any]] = {}
    for row in sources:
        digest_map.setdefault(row["content_sha256"], row)

    arxiv_map: dict[str, str] = {}
    doi_map: dict[str, str] = {}
    work_map: dict[str, dict[str, Any]] = {}
    for row in works:
        work_map[row["id"]] = row
        if row.get("arxiv_id"):
            arxiv_map[arxiv_work_key(row["arxiv_id"])] = row["id"]
        if row.get("doi"):
            doi_map[normalize_doi(row["doi"])] = row["id"]

    max_source_seq = 0
    for row in sources:
        match = SF_ID_RE.match(row["id"] or "")
        if match:
            max_source_seq = max(max_source_seq, int(match.group(1)))

    source_by_work: dict[str, list[dict[str, Any]]] = {}
    for row in sources:
        source_by_work.setdefault(row["work_id"], []).append(row)

    return {
        "sources": sources,
        "works": works,
        "digest_map": digest_map,
        "arxiv_map": arxiv_map,
        "doi_map": doi_map,
        "work_map": work_map,
        "source_by_work": source_by_work,
        "max_source_seq": max_source_seq,
    }


def choose_work_id(metadata: Metadata, digest: str, state: dict[str, Any]) -> tuple[str, bool]:
    if metadata.arxiv_id:
        key = arxiv_work_key(metadata.arxiv_id)
        if key in state["arxiv_map"]:
            return state["arxiv_map"][key], True
        return f"W-arxiv-{key}", False

    if metadata.doi:
        doi = normalize_doi(metadata.doi)
        if doi in state["doi_map"]:
            return state["doi_map"][doi], True
        return doi_to_work_id(doi), False

    base = f"W-sha-{digest[:12]}"
    if base not in state["work_map"]:
        return base, False
    # Extremely unlikely sha-prefix collision. Extend until unique.
    for length in (16, 20, 24, 32, 64):
        candidate = f"W-sha-{digest[:length]}"
        if candidate not in state["work_map"]:
            return candidate, False
    raise ValueError(f"unable to create unique work id for sha256={digest}")


def next_source_file_id(digest: str, sequence: int, used: set[str]) -> str:
    while True:
        candidate = f"SF-{digest[:12]}-{sequence:05d}"
        sequence += 1
        if candidate not in used:
            used.add(candidate)
            return candidate


def unique_destination(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 2
    while True:
        candidate = parent / f"{stem}__{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def title_candidates_for(metadata: Metadata, work_id: str, state: dict[str, Any]) -> list[dict[str, Any]]:
    title_key = normalize_title(metadata.title)
    if not title_key:
        return []

    candidates: list[dict[str, Any]] = []
    for work in state["works"]:
        if work["id"] == work_id:
            continue
        existing_title = work.get("title") or ""
        score = jaccard(title_key, normalize_title(existing_title))
        if score >= 0.9:
            sources = state["source_by_work"].get(work["id"], [])
            candidates.append(
                {
                    "work_id": work["id"],
                    "title": existing_title,
                    "score": round(score, 4),
                    "source_path": sources[0]["source_path"] if sources else "",
                    "reason": "title_jaccard>=0.90",
                }
            )
    return candidates


def scan_inbox(inbox_dir: Path) -> list[Path]:
    if not inbox_dir.exists():
        return []
    return sorted(path for path in inbox_dir.rglob("*.pdf") if path.is_file())


def build_ingest_plan(
    library_root: Path,
    *,
    inbox_dir: Path | None = None,
    limit: int | None = None,
    dry_run: bool = True,
) -> IngestPlan:
    library_root = library_root.resolve()
    inbox_dir = (inbox_dir or library_root / "_inbox").resolve()
    db_path = library_root / "literature.sqlite"

    plan = IngestPlan(
        generated_at=utc_now(),
        library_root=str(library_root),
        inbox_dir=str(inbox_dir),
        dry_run=dry_run,
    )

    with connect_db(db_path) as conn:
        state = fetch_existing_state(conn)

    pdfs = scan_inbox(inbox_dir)
    if limit is not None:
        pdfs = pdfs[:limit]

    used_source_ids = {row["id"] for row in state["sources"]}
    source_sequence = int(state["max_source_seq"]) + 1
    planned_digests: set[str] = set()
    archive_stamp = timestamp_slug()

    for pdf_path in pdfs:
        try:
            stat = pdf_path.stat()
            digest = sha256_file(pdf_path)
        except OSError as exc:
            plan.skipped.append({"path": str(pdf_path), "reason": str(exc)})
            continue

        duplicate = state["digest_map"].get(digest)
        if duplicate or digest in planned_digests:
            existing = duplicate or {"work_id": "", "id": ""}
            duplicate_dir = library_root / "_duplicates" / "exact_sha256" / archive_stamp / digest[:12]
            archive_path = unique_destination(duplicate_dir / pdf_path.name)
            plan.exact_duplicates.append(
                DuplicateAction(
                    inbox_path=str(pdf_path),
                    archive_path=str(archive_path),
                    content_sha256=digest,
                    existing_work_id=existing.get("work_id", ""),
                    existing_source_file_id=existing.get("id", ""),
                    original_name=pdf_path.name,
                    file_size=stat.st_size,
                )
            )
            continue

        metadata = extract_metadata(pdf_path)
        work_id, existing_work = choose_work_id(metadata, digest, state)
        source_file_id = next_source_file_id(digest, source_sequence, used_source_ids)
        source_sequence += 1
        source_dir = library_root / "works" / work_id / "source"
        library_path = unique_destination(source_dir / pdf_path.name)
        archive_path = unique_destination(
            library_root / "_archive" / "ingested_inbox" / archive_stamp / safe_relative(pdf_path, inbox_dir)
        )
        candidates = title_candidates_for(metadata, work_id, state)
        plan.ingests.append(
            IngestAction(
                inbox_path=str(pdf_path),
                library_path=str(library_path),
                archive_path=str(archive_path),
                content_sha256=digest,
                source_file_id=source_file_id,
                work_id=work_id,
                existing_work=existing_work,
                original_name=pdf_path.name,
                file_size=stat.st_size,
                metadata=metadata,
                title_duplicate_candidates=candidates,
            )
        )
        planned_digests.add(digest)
        state["digest_map"][digest] = {
            "id": source_file_id,
            "work_id": work_id,
            "content_sha256": digest,
            "source_path": str(library_path),
        }
        # Update source_by_work so title_candidates_for can find source_path
        # for works planned in the same batch
        state["source_by_work"].setdefault(work_id, []).append({
            "id": source_file_id,
            "work_id": work_id,
            "source_path": str(library_path),
        })
        if not existing_work:
            state["work_map"][work_id] = {
                "id": work_id,
                "title": metadata.title,
                "authors": json.dumps(metadata.authors, ensure_ascii=False),
                "year": metadata.year,
                "arxiv_id": metadata.arxiv_id,
                "doi": metadata.doi,
            }
            state["works"].append(state["work_map"][work_id])

    return plan


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def backup_state_files(library_root: Path, stamp: str) -> Path:
    backup_dir = library_root / "_archive" / f"ingest_backups_{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    for name in ("literature.sqlite", "index.json"):
        source = library_root / name
        if source.exists():
            shutil.copy2(source, backup_dir / name)
    return backup_dir


def update_index(library_root: Path, plan: IngestPlan, now: str) -> None:
    index_path = library_root / "index.json"
    index = load_json(
        index_path,
        {
            "migration_version": "literature_phase2_v1",
            "generated_at": now,
            "library_root": str(library_root),
            "summary": {},
            "works": [],
            "relations": [],
            "title_duplicate_groups": [],
            "warnings": [],
        },
    )
    works = index.setdefault("works", [])
    by_work = {work.get("work_id"): work for work in works}

    for action in plan.ingests:
        metadata = action.metadata
        work = by_work.get(action.work_id)
        if work is None:
            work = {
                "work_id": action.work_id,
                "title": metadata.title,
                "authors": metadata.authors,
                "year": metadata.year,
                "arxiv_id": metadata.arxiv_id,
                "doi": metadata.doi,
                "doc_type": metadata.doc_type,
                "language": metadata.language,
                "metadata_status": metadata.metadata_status,
                "parse_status": "pending",
                "read_status": "unread",
                "work_relative_dir": str(Path("works") / action.work_id),
                "source_files": [],
                "codes": [],
                "exact_duplicate_count": 0,
                "template_extract_count": 0,
            }
            works.append(work)
            by_work[action.work_id] = work
        else:
            if work.get("parse_status") == "succeeded":
                work["parse_status"] = "partial"
            elif not work.get("parse_status") or work.get("parse_status") == "unknown":
                work["parse_status"] = "pending"

        sources = work.setdefault("source_files", [])
        if not any(item.get("source_file_id") == action.source_file_id for item in sources):
            sources.append(
                {
                    "source_file_id": action.source_file_id,
                    "original_name": action.original_name,
                    "library_relative_path": safe_relative(Path(action.library_path), library_root),
                    "content_sha256": action.content_sha256,
                }
            )

    total_sources = sum(len(work.get("source_files", [])) for work in works)
    summary = index.setdefault("summary", {})
    summary["works"] = len(works)
    summary["active_source_pdfs"] = total_sources
    summary["last_ingest_count"] = len(plan.ingests)
    summary["last_exact_duplicate_count"] = len(plan.exact_duplicates)
    summary["last_ingest_at"] = now
    index["generated_at"] = now
    index["library_root"] = str(library_root)
    index["ingest_version"] = INGEST_VERSION
    write_json_atomic(index_path, index)


def insert_db_rows(library_root: Path, plan: IngestPlan, now: str) -> None:
    db_path = library_root / "literature.sqlite"
    with connect_db(db_path) as conn:
        ensure_core_schema(conn)
        for action in plan.ingests:
            metadata = action.metadata
            existing = conn.execute(
                "SELECT parse_status FROM works WHERE id = ?", (action.work_id,)
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO works (
                        id, title, authors, year, arxiv_id, doi, doc_type, language,
                        metadata_status, parse_status, read_status, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        action.work_id,
                        metadata.title,
                        json.dumps(metadata.authors, ensure_ascii=False),
                        metadata.year,
                        metadata.arxiv_id,
                        metadata.doi,
                        metadata.doc_type,
                        metadata.language,
                        metadata.metadata_status,
                        "pending",
                        "unread",
                        now,
                        now,
                    ),
                )
            else:
                next_status = "partial" if existing["parse_status"] == "succeeded" else "pending"
                conn.execute(
                    "UPDATE works SET parse_status = ?, updated_at = ? WHERE id = ?",
                    (next_status, now, action.work_id),
                )

            library_path = Path(action.library_path)
            conn.execute(
                """
                INSERT INTO source_files (
                    id, work_id, content_sha256, original_name, source_path,
                    relative_source_path, file_size, file_ext, import_time, mtime
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action.source_file_id,
                    action.work_id,
                    action.content_sha256,
                    action.original_name,
                    action.library_path,
                    safe_relative(library_path, library_root),
                    action.file_size,
                    library_path.suffix.lower(),
                    now,
                    file_mtime(library_path),
                ),
            )
            output_dir = library_root / "works" / action.work_id / "parsed" / "mineru" / action.source_file_id
            conn.execute(
                """
                INSERT OR REPLACE INTO literature_parse_runs (
                    id, work_id, source_file_id, source_path, task_id, status, backend,
                    parse_method, file_size, started_at, finished_at, output_dir, error,
                    content_json_path, content_md_path, package_path
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"LPR-{action.source_file_id}",
                    action.work_id,
                    action.source_file_id,
                    action.library_path,
                    "",
                    "pending",
                    DEFAULT_BACKEND,
                    DEFAULT_PARSE_METHOD,
                    action.file_size,
                    now,
                    "",
                    str(output_dir),
                    "",
                    str(output_dir / "content.json"),
                    str(output_dir / "content.md"),
                    str(output_dir / "package.zip"),
                ),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO library_migration_files (
                    id, source_file_id, artifact_id, work_id, role, original_source_path,
                    library_path, content_sha256, migrated_at, migration_version, note
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"MF-{action.source_file_id}",
                    action.source_file_id,
                    "",
                    action.work_id,
                    "ingested_source",
                    action.inbox_path,
                    action.library_path,
                    action.content_sha256,
                    now,
                    INGEST_VERSION,
                    "",
                ),
            )

            for index, candidate in enumerate(action.title_duplicate_candidates, start=1):
                group_id = f"DG-ingest-title-{action.source_file_id}-{index:02d}"
                conn.execute(
                    """
                    INSERT OR IGNORE INTO duplicate_groups (id, duplicate_type, key, count)
                    VALUES (?, ?, ?, ?)
                    """,
                    (group_id, "title_candidate", normalize_title(metadata.title), 2),
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO duplicate_candidates (
                        id, group_id, source_file_id, work_id, source_path, score, reason
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"DC-{group_id}-new",
                        group_id,
                        action.source_file_id,
                        action.work_id,
                        action.library_path,
                        candidate["score"],
                        candidate["reason"],
                    ),
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO duplicate_candidates (
                        id, group_id, source_file_id, work_id, source_path, score, reason
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"DC-{group_id}-existing",
                        group_id,
                        "",
                        candidate["work_id"],
                        candidate.get("source_path", ""),
                        candidate["score"],
                        candidate["reason"],
                    ),
                )

        conn.commit()


def copy_planned_files(plan: IngestPlan) -> None:
    for action in plan.ingests:
        source = Path(action.inbox_path)
        destination = Path(action.library_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def archive_inputs(plan: IngestPlan, *, leave_inbox: bool) -> None:
    if leave_inbox:
        return
    for action in plan.ingests:
        source = Path(action.inbox_path)
        archive = Path(action.archive_path)
        if not source.exists():
            continue
        archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(archive))


def archive_exact_duplicates(plan: IngestPlan) -> None:
    for action in plan.exact_duplicates:
        source = Path(action.inbox_path)
        archive = Path(action.archive_path)
        if not source.exists():
            continue
        archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(archive))


def execute_plan(
    plan: IngestPlan,
    *,
    no_backup: bool = False,
    leave_inbox: bool = False,
) -> Path | None:
    library_root = Path(plan.library_root)
    now = utc_now()
    backup_dir = None if no_backup else backup_state_files(library_root, timestamp_slug())
    copy_planned_files(plan)
    insert_db_rows(library_root, plan, now)
    update_index(library_root, plan, now)
    archive_exact_duplicates(plan)
    archive_inputs(plan, leave_inbox=leave_inbox)
    return backup_dir


def print_plan(plan: IngestPlan) -> None:
    print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    default_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Ingest new PDFs from _inbox into the literature library.")
    parser.add_argument("--library-root", type=Path, default=default_root)
    parser.add_argument("--inbox", type=Path, default=None, help="Defaults to <library-root>/_inbox.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--execute", action="store_true", help="Apply the planned ingest. Default is dry-run.")
    parser.add_argument("--no-backup", action="store_true", help="Do not backup DB/index before executing.")
    parser.add_argument("--leave-inbox", action="store_true", help="Keep ingested originals in _inbox.")
    parser.add_argument("--plan-out", type=Path, default=None, help="Optional JSON path for the generated plan.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    plan = build_ingest_plan(
        args.library_root,
        inbox_dir=args.inbox,
        limit=args.limit,
        dry_run=not args.execute,
    )

    if args.plan_out:
        write_json_atomic(args.plan_out, plan.as_dict())

    print_plan(plan)
    if not args.execute:
        return 0

    backup_dir = execute_plan(plan, no_backup=args.no_backup, leave_inbox=args.leave_inbox)
    if backup_dir:
        print(f"Backed up state files to: {backup_dir}")
    print("Ingest execution complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
