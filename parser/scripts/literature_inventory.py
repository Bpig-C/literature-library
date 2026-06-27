"""Read-only literature inventory scanner.

Scans a literature directory, records PDF files into SQLite, and writes a
Markdown report with duplicate and metadata coverage summaries. The source
directory is never modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sqlite3
import warnings
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from pypdf import PdfReader

try:
    from pypdf.errors import PdfReadWarning

    warnings.filterwarnings("ignore", category=PdfReadWarning)
except Exception:
    pass

logging.getLogger("pypdf").setLevel(logging.ERROR)


DEFAULT_SOURCE_ROOT = Path(r"D:\02_academic\doctoral\literature_read")
DEFAULT_OUTPUT_ROOT = Path(r"D:\02_academic\doctoral\literature_library")

ARXIV_RE = re.compile(r"(?i)(?:arxiv[:\-_ ]*)?(\d{4}\.\d{4,5})(v\d+)?")
DOI_RE = re.compile(r"(?i)\b(10\.\d{4,9}/[^\s<>()\[\]{}\"']+)")
CODE_RE = re.compile(r"(?i)(?:^|[\[_\-\s])([A-Z]\d{1,3}[a-z]?(?:-\d+)?|[A-Z]\d{1,3}[a-z]?-dup)(?:\]|_|-|\s|$)")
STOPWORDS = {"a", "an", "the", "in", "of", "for", "on", "to", "and", "with", "by"}

# Structured filename convention regexes
_R_FORMAT_RE = re.compile(r"^【R】(.+)$")
_CODE_BRACKET_RE = re.compile(r"^\[([A-Za-z]\d+[a-z]?(?:-[A-Za-z\d]+)?)\]_(.+)$")
_CODE_BARE_RE = re.compile(r"^([A-Z]{1,2}\d+[a-z]?)_(.+)$")


@dataclass
class PdfRecord:
    id: str
    work_id: str
    content_sha256: str
    original_name: str
    source_path: str
    relative_source_path: str
    file_size: int
    file_ext: str
    mtime: str
    arxiv_id: str
    doi: str
    title: str
    authors: str
    year: int | None
    metadata_status: str
    associated_md: list[str]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def file_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


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


def jaccard(a: str, b: str) -> float:
    left = set(a.split())
    right = set(b.split())
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def parse_structured_filename(stem: str) -> dict[str, str | int]:
    """Extract metadata from structured filename conventions.

    Handles three formats:
    - 【R】YYYYMM(R,机构)-...-title  (technical reports)
    - [Code]_Title_with_underscores  (coded papers/cards with brackets)
    - Code_Title                     (bare codes, e.g. E17_, G2_, X2_)
    """
    result: dict[str, str | int] = {}

    r_match = _R_FORMAT_RE.match(stem)
    if r_match:
        content = r_match.group(1)
        arxiv_match = ARXIV_RE.search(content)
        if arxiv_match:
            result["arxiv_id"] = f"{arxiv_match.group(1)}{arxiv_match.group(2) or ''}"
        year_match = re.match(r"^(\d{4})", content)
        if year_match:
            result["year"] = int(year_match.group(1))
        inst_match = re.search(r"\(R?,\s*([^)]+)\)", content)
        if inst_match:
            result["institution"] = inst_match.group(1).strip()
        # Title: strip leading date/arXiv tokens and parenthetical groups, take last segment
        clean = re.sub(r"^(?:\d{6}|arXiv[-_]\S+)\s*", "", content, flags=re.IGNORECASE)
        clean = re.sub(r"\([^)]*\)", "", clean)
        parts = [p.strip() for p in re.split(r"\s*-\s*", clean) if p.strip() and len(p.strip()) > 3]
        if parts:
            result["title"] = parts[-1]
        result["metadata_status"] = "auto"
        return result

    bracket_match = _CODE_BRACKET_RE.match(stem)
    if bracket_match:
        result["code"] = bracket_match.group(1)
        result["title"] = bracket_match.group(2).replace("_", " ")
        result["metadata_status"] = "auto"
        return result

    bare_match = _CODE_BARE_RE.match(stem)
    if bare_match:
        result["code"] = bare_match.group(1)
        result["title"] = bare_match.group(2).replace("_", " ")
        result["metadata_status"] = "auto"
        return result

    return result


def guess_year(text: str) -> int | None:
    years = [int(match.group(0)) for match in re.finditer(r"\b(?:19|20)\d{2}\b", text)]
    plausible = [year for year in years if 1900 <= year <= 2100]
    return min(plausible) if plausible else None


def safe_pdf_metadata(path: Path) -> dict[str, str]:
    try:
        reader = PdfReader(str(path))
        metadata = reader.metadata or {}
    except Exception:
        return {}

    result: dict[str, str] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        normalized_key = str(key).lstrip("/").lower()
        result[normalized_key] = str(value).strip()
    return result


def candidate_text_for_metadata(path: Path, metadata: dict[str, str]) -> str:
    return " ".join(
        [
            path.name,
            path.stem,
            metadata.get("title", ""),
            metadata.get("author", ""),
            metadata.get("subject", ""),
        ]
    )


def extract_literature_code(text: str) -> str:
    match = CODE_RE.search(text)
    return match.group(1).lower() if match else ""


def build_markdown_index(source_root: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = defaultdict(list)
    for md_path in source_root.rglob("*.md"):
        if not md_path.is_file():
            continue
        code = extract_literature_code(md_path.stem)
        if code:
            index[code].append(md_path)
    return index


def find_associated_md(pdf_path: Path, source_root: Path, markdown_index: dict[str, list[Path]]) -> list[str]:
    candidates: list[Path] = []
    stem_norm = normalize_title(pdf_path.stem)
    parent = pdf_path.parent
    code = extract_literature_code(pdf_path.stem)

    for md_path in parent.glob("*.md"):
        md_norm = normalize_title(md_path.stem)
        if pdf_path.stem in md_path.stem or md_path.stem in pdf_path.stem:
            candidates.append(md_path)
            continue
        if stem_norm and md_norm and (stem_norm in md_norm or md_norm in stem_norm):
            candidates.append(md_path)

    mineru_prefixes = ("MinerU_markdown_", "MinerU_")
    for md_path in parent.glob("*.md"):
        if md_path.name.startswith(mineru_prefixes) and md_path not in candidates:
            if normalize_title(pdf_path.stem)[:24] in normalize_title(md_path.stem):
                candidates.append(md_path)

    if code:
        candidates.extend(markdown_index.get(code, []))

    unique = []
    seen = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        unique.append(str(path.relative_to(source_root)))
    return unique


def make_work_id(arxiv_id: str, doi: str, sha256: str) -> str:
    if arxiv_id:
        return f"W-arxiv-{arxiv_id.lower()}"
    if doi:
        return doi_to_work_id(doi)
    return f"W-sha-{sha256[:12]}"


def scan_pdfs(source_root: Path) -> list[PdfRecord]:
    records: list[PdfRecord] = []
    markdown_index = build_markdown_index(source_root)
    for pdf_path in sorted(source_root.rglob("*.pdf")):
        if not pdf_path.is_file():
            continue

        sha256 = sha256_file(pdf_path)
        metadata = safe_pdf_metadata(pdf_path)
        metadata_text = candidate_text_for_metadata(pdf_path, metadata)
        arxiv_id = extract_arxiv_id(metadata_text)
        doi = extract_doi(metadata_text)
        title = metadata.get("title", "").strip()
        if not title:
            title = pdf_path.stem
        authors = metadata.get("author", "").strip()
        year = guess_year(metadata_text)

        # Enrich from structured filename conventions (overrides empty/stem-only metadata)
        structured = parse_structured_filename(pdf_path.stem)
        if not arxiv_id and structured.get("arxiv_id"):
            arxiv_id = str(structured["arxiv_id"])
        if title == pdf_path.stem and structured.get("title"):
            title = str(structured["title"])
        if year is None and structured.get("year"):
            year = int(str(structured["year"]))

        if structured:
            metadata_status = "auto"
        elif arxiv_id or doi:
            metadata_status = "auto"
        elif title and title != pdf_path.stem:
            metadata_status = "needs_review"
        else:
            metadata_status = "missing"

        work_id = make_work_id(arxiv_id, doi, sha256)
        relative_path = str(pdf_path.relative_to(source_root))

        records.append(
            PdfRecord(
                id=f"SF-{sha256[:12]}-{len(records) + 1:05d}",
                work_id=work_id,
                content_sha256=sha256,
                original_name=pdf_path.name,
                source_path=str(pdf_path),
                relative_source_path=relative_path,
                file_size=pdf_path.stat().st_size,
                file_ext=pdf_path.suffix.lower(),
                mtime=file_mtime(pdf_path),
                arxiv_id=arxiv_id,
                doi=doi,
                title=title,
                authors=authors,
                year=year,
                metadata_status=metadata_status,
                associated_md=find_associated_md(pdf_path, source_root, markdown_index),
            )
        )
    reconcile_exact_duplicate_work_ids(records)
    return records


def reconcile_exact_duplicate_work_ids(records: list[PdfRecord]) -> None:
    by_hash: dict[str, list[PdfRecord]] = defaultdict(list)
    for record in records:
        by_hash[record.content_sha256].append(record)

    for items in by_hash.values():
        if len(items) <= 1:
            continue

        canonical = sorted(
            items,
            key=lambda item: (
                0 if item.arxiv_id else 1,
                0 if item.doi else 1,
                len(item.relative_source_path),
            ),
        )[0]
        for item in items:
            if not item.arxiv_id and canonical.arxiv_id:
                item.arxiv_id = canonical.arxiv_id
            if not item.doi and canonical.doi:
                item.doi = canonical.doi
            item.work_id = canonical.work_id


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS source_files;
        DROP TABLE IF EXISTS works;
        DROP TABLE IF EXISTS parse_artifacts;
        DROP TABLE IF EXISTS duplicate_groups;
        DROP TABLE IF EXISTS duplicate_candidates;
        DROP TABLE IF EXISTS inventory_meta;

        CREATE TABLE inventory_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE source_files (
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

        CREATE TABLE works (
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

        CREATE TABLE parse_artifacts (
            id TEXT PRIMARY KEY,
            work_id TEXT NOT NULL,
            source_file_id TEXT NOT NULL,
            type TEXT,
            file_path TEXT,
            parser TEXT,
            parse_time TEXT,
            task_id TEXT
        );

        CREATE TABLE duplicate_groups (
            id TEXT PRIMARY KEY,
            duplicate_type TEXT NOT NULL,
            key TEXT NOT NULL,
            count INTEGER NOT NULL
        );

        CREATE TABLE duplicate_candidates (
            id TEXT PRIMARY KEY,
            group_id TEXT,
            source_file_id TEXT,
            work_id TEXT,
            source_path TEXT,
            score REAL,
            reason TEXT
        );
        """
    )


def write_sqlite(db_path: Path, source_root: Path, records: list[PdfRecord]) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        ensure_schema(conn)
        now = utc_now()
        conn.executemany(
            "INSERT INTO inventory_meta(key, value) VALUES (?, ?)",
            [
                ("source_root", str(source_root)),
                ("generated_at", now),
                ("pdf_count", str(len(records))),
            ],
        )

        seen_works = {}
        for record in records:
            if record.work_id not in seen_works:
                seen_works[record.work_id] = record

        conn.executemany(
            """
            INSERT INTO works(
                id, title, authors, year, arxiv_id, doi, doc_type, language,
                metadata_status, parse_status, read_status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    record.work_id,
                    record.title,
                    json.dumps([record.authors], ensure_ascii=False) if record.authors else "[]",
                    record.year,
                    record.arxiv_id,
                    record.doi,
                    guess_doc_type(record),
                    guess_language(record),
                    record.metadata_status,
                    "unknown",
                    "unread",
                    now,
                    now,
                )
                for record in seen_works.values()
            ],
        )

        conn.executemany(
            """
            INSERT INTO source_files(
                id, work_id, content_sha256, original_name, source_path,
                relative_source_path, file_size, file_ext, import_time, mtime
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    record.id,
                    record.work_id,
                    record.content_sha256,
                    record.original_name,
                    record.source_path,
                    record.relative_source_path,
                    record.file_size,
                    record.file_ext,
                    now,
                    record.mtime,
                )
                for record in records
            ],
        )

        artifact_rows = []
        for record in records:
            for index, md_path in enumerate(record.associated_md, start=1):
                artifact_rows.append(
                    (
                        f"PA-{record.id}-{index:03d}",
                        record.work_id,
                        record.id,
                        "template_extract",
                        md_path,
                        "local_agent_template",
                        "",
                        "",
                    )
                )

        conn.executemany(
            """
            INSERT INTO parse_artifacts(
                id, work_id, source_file_id, type, file_path, parser, parse_time, task_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            artifact_rows,
        )

        for group in exact_duplicate_groups(records):
            conn.execute(
                "INSERT INTO duplicate_groups(id, duplicate_type, key, count) VALUES (?, ?, ?, ?)",
                (group["id"], "exact_sha256", group["key"], len(group["records"])),
            )
            for record in group["records"]:
                conn.execute(
                    """
                    INSERT INTO duplicate_candidates(
                        id, group_id, source_file_id, work_id, source_path, score, reason
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"DC-{group['id']}-{record.id}",
                        group["id"],
                        record.id,
                        record.work_id,
                        record.source_path,
                        1.0,
                        "same content sha256",
                    ),
                )

        for group in title_duplicate_groups(records):
            conn.execute(
                "INSERT INTO duplicate_groups(id, duplicate_type, key, count) VALUES (?, ?, ?, ?)",
                (group["id"], "title_candidate", group["key"], len(group["records"])),
            )
            for record in group["records"]:
                conn.execute(
                    """
                    INSERT INTO duplicate_candidates(
                        id, group_id, source_file_id, work_id, source_path, score, reason
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"DC-{group['id']}-{record.id}",
                        group["id"],
                        record.id,
                        record.work_id,
                        record.source_path,
                        group["score"],
                        "similar normalized title",
                    ),
                )

        conn.commit()
    finally:
        conn.close()


def guess_doc_type(record: PdfRecord) -> str:
    text = f"{record.relative_source_path} {record.title}".lower()
    if "system_card" in text or "system card" in text:
        return "system_card"
    if "benchmark" in text or "bench" in text:
        return "benchmark"
    if "report" in text or "报告" in text:
        return "report"
    if record.arxiv_id:
        return "preprint"
    return "paper"


def guess_language(record: PdfRecord) -> str:
    text = f"{record.original_name} {record.title}"
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    return "en"


def exact_duplicate_groups(records: list[PdfRecord]) -> list[dict]:
    by_hash: dict[str, list[PdfRecord]] = defaultdict(list)
    for record in records:
        by_hash[record.content_sha256].append(record)
    groups = []
    for index, (digest, items) in enumerate(sorted(by_hash.items()), start=1):
        if len(items) <= 1:
            continue
        groups.append({"id": f"DG-sha-{index:04d}", "key": digest, "records": items})
    return groups


def title_duplicate_groups(records: list[PdfRecord]) -> list[dict]:
    by_title: dict[str, list[PdfRecord]] = defaultdict(list)
    for record in records:
        title_key = normalize_title(record.title or record.original_name)
        if len(title_key) >= 12:
            by_title[title_key].append(record)

    groups = []
    index = 1
    for title_key, items in sorted(by_title.items()):
        if len(items) <= 1:
            continue
        hashes = {item.content_sha256 for item in items}
        if len(hashes) <= 1:
            continue
        groups.append({"id": f"DG-title-{index:04d}", "key": title_key, "score": 1.0, "records": items})
        index += 1
    return groups


def metadata_summary(records: list[PdfRecord]) -> dict[str, int]:
    return {
        "with_arxiv": sum(1 for item in records if item.arxiv_id),
        "with_doi": sum(1 for item in records if item.doi),
        "with_pdf_title": sum(1 for item in records if item.title and item.title != item.original_name),
        "needs_review": sum(1 for item in records if item.metadata_status == "needs_review"),
        "with_associated_md": sum(1 for item in records if item.associated_md),
    }


def write_report(report_path: Path, source_root: Path, db_path: Path, records: list[PdfRecord]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    exact_groups = exact_duplicate_groups(records)
    title_groups = title_duplicate_groups(records)
    meta = metadata_summary(records)
    total_size = sum(item.file_size for item in records)
    now = utc_now()

    lines = [
        "# Literature Inventory Report",
        "",
        f"> Generated: {now}",
        f"> Source root: `{source_root}`",
        f"> SQLite: `{db_path}`",
        "",
        "## Summary",
        "",
        f"- PDF files: {len(records)}",
        f"- Total PDF size: {total_size / 1024 / 1024:.2f} MB",
        f"- Exact duplicate groups: {len(exact_groups)}",
        f"- Title duplicate candidate groups: {len(title_groups)}",
        f"- PDFs with associated Markdown/template extracts: {meta['with_associated_md']}",
        f"- PDFs with arXiv ID: {meta['with_arxiv']}",
        f"- PDFs with DOI: {meta['with_doi']}",
        f"- PDFs needing metadata review: {meta['needs_review']}",
        "",
        "## Exact Duplicates",
        "",
    ]

    if exact_groups:
        for group in exact_groups:
            lines.append(f"### {group['id']} ({len(group['records'])} files)")
            lines.append("")
            lines.append(f"- sha256: `{group['key']}`")
            for record in group["records"]:
                lines.append(f"- `{record.relative_source_path}`")
            lines.append("")
    else:
        lines.append("No exact duplicates found.")
        lines.append("")

    lines.extend(["## Title Duplicate Candidates", ""])
    if title_groups:
        for group in title_groups:
            lines.append(f"### {group['id']} ({len(group['records'])} files)")
            lines.append("")
            lines.append(f"- normalized title: `{group['key']}`")
            for record in group["records"]:
                lines.append(f"- `{record.relative_source_path}`")
            lines.append("")
    else:
        lines.append("No title duplicate candidates found.")
        lines.append("")

    lines.extend(["## Metadata Needs Review", ""])
    needs_review = [record for record in records if record.metadata_status == "needs_review"]
    for record in needs_review[:50]:
        lines.append(f"- `{record.relative_source_path}`")
    if len(needs_review) > 50:
        lines.append(f"- ... {len(needs_review) - 50} more")
    if not needs_review:
        lines.append("No files need metadata review.")
    lines.append("")

    lines.extend(["## Existing Template Extracts", ""])
    with_md = [record for record in records if record.associated_md]
    for record in with_md[:80]:
        lines.append(f"- `{record.relative_source_path}`")
        for md_path in record.associated_md[:5]:
            lines.append(f"  - md: `{md_path}`")
    if len(with_md) > 80:
        lines.append(f"- ... {len(with_md) - 80} more")
    if not with_md:
        lines.append("No associated Markdown files found.")
    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")


def iter_records_json(records: Iterable[PdfRecord]) -> list[dict]:
    return [
        {
            "id": record.id,
            "work_id": record.work_id,
            "content_sha256": record.content_sha256,
            "original_name": record.original_name,
            "source_path": record.source_path,
            "relative_source_path": record.relative_source_path,
            "file_size": record.file_size,
            "file_ext": record.file_ext,
            "mtime": record.mtime,
            "arxiv_id": record.arxiv_id,
            "doi": record.doi,
            "title": record.title,
            "authors": record.authors,
            "year": record.year,
            "metadata_status": record.metadata_status,
            "associated_md": record.associated_md,
        }
        for record in records
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a read-only inventory for literature PDFs.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE_ROOT, help="Source literature directory.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_ROOT, help="Output literature library directory.")
    parser.add_argument("--db-name", default="literature.sqlite", help="SQLite filename under output directory.")
    parser.add_argument("--report-name", default="literature_report.md", help="Markdown report filename under output directory.")
    parser.add_argument("--json-name", default="literature_inventory.json", help="JSON inventory filename under output directory.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_root = args.source.resolve()
    output_root = args.output.resolve()
    if not source_root.exists() or not source_root.is_dir():
        raise SystemExit(f"source directory not found: {source_root}")

    output_root.mkdir(parents=True, exist_ok=True)
    db_path = output_root / args.db_name
    report_path = output_root / args.report_name
    json_path = output_root / args.json_name

    records = scan_pdfs(source_root)
    write_sqlite(db_path, source_root, records)
    write_report(report_path, source_root, db_path, records)
    json_path.write_text(json.dumps(iter_records_json(records), ensure_ascii=False, indent=2), encoding="utf-8")

    exact_count = len(exact_duplicate_groups(records))
    title_count = len(title_duplicate_groups(records))
    print(f"Scanned PDFs: {len(records)}")
    print(f"Exact duplicate groups: {exact_count}")
    print(f"Title duplicate candidate groups: {title_count}")
    print(f"SQLite: {db_path}")
    print(f"Report: {report_path}")
    print(f"JSON: {json_path}")


if __name__ == "__main__":
    main()
