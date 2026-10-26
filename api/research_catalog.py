"""Catalog bridge for the research v5 store (controller A6).

The research store (research.sqlite) and the bibliographic catalog
(literature.sqlite) are separate SQLite files.  This module resolves the
catalog exactly like ``api.db`` (LITLIB_DB_PATH → library_root/literature.sqlite
→ CODE_ROOT), checks work existence before research writes, and propagates an
approved metadata record into ``works`` + the bibliographic projection
(``bibliographic_projections``) so BibTeX / RIS / matrix exports reflect
research-approved metadata immediately — with the author list kept complete
and ordered (never truncated for display).

LL-DECOUPLE-20260920: the legacy extraction compatibility bridge is retired;
the projection table is now the single exportable current-value view.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from . import bibliographic_projection as projection
from .db import CODE_ROOT
from .research_context import ResearchContext
from .research_stability import clean_identifier, official_publication_url, select_catalog_abstract


def catalog_db_path(context: ResearchContext) -> Path:
    if os.environ.get('LITLIB_STORAGE_MODE')=='immutable':
        from .storage.runtime import configured_registry
        return configured_registry().catalog
    env = os.environ.get("LITLIB_DB_PATH")
    if env:
        return Path(env).resolve()
    candidate = Path(context.library_root).resolve() / "literature.sqlite"
    if candidate.exists():
        return candidate
    return (CODE_ROOT / "literature.sqlite").resolve()


def catalog_conn(context: ResearchContext, *, read_only: bool = True) -> sqlite3.Connection:
    path = catalog_db_path(context)
    if read_only:
        conn = sqlite3.connect(Path(path).absolute().as_uri() + "?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def catalog_available(context: ResearchContext) -> bool:
    """True when the resolved catalog file exists and has a works table."""
    path = catalog_db_path(context)
    if not path.exists():
        return False
    try:
        with closing(catalog_conn(context, read_only=True)) as conn:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='works'"
            ).fetchone()
            return row is not None
    except sqlite3.OperationalError:
        return False


def work_exists(context: ResearchContext, work_id: str) -> bool:
    """Work identity check: catalog first, research sources as fallback.

    A research store can legitimately hold sources for a work whose catalog
    row was deleted; research-layer writes must not be silently blocked by
    catalog bookkeeping, but they must also not invent identities.
    """
    if not work_id or not str(work_id).strip():
        return False
    work_id = str(work_id).strip()
    if catalog_available(context):
        try:
            with closing(catalog_conn(context, read_only=True)) as conn:
                return conn.execute("SELECT 1 FROM works WHERE id=?", (work_id,)).fetchone() is not None
        except sqlite3.OperationalError:
            pass
    with closing(context.connect(read_only=True)) as conn:
        return conn.execute(
            "SELECT 1 FROM research_sources WHERE work_id=? LIMIT 1", (work_id,)
        ).fetchone() is not None


def catalog_work_identity(context: ResearchContext, work_id: str) -> dict | None:
    """Bibliographic identity of a catalog work, for identity-based matching.

    Returns ``None`` when the catalog is unavailable or the work is absent —
    callers must fail closed on identity verification rather than fall back to
    fuzzy title matching (PLATFORM-005).
    """
    if not catalog_available(context):
        return None
    try:
        with closing(catalog_conn(context, read_only=True)) as conn:
            row = conn.execute(
                "SELECT id,title,authors,year,doi,arxiv_id,title_zh FROM works WHERE id=?",
                (work_id,)).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row:
        return None
    try:
        authors = json.loads(row["authors"] or "[]")
    except (TypeError, ValueError):
        authors = []
    return {"id": row["id"], "title": row["title"], "title_zh": row["title_zh"],
            "authors": [str(a) for a in authors if a], "year": row["year"],
            "doi": row["doi"], "arxiv_id": row["arxiv_id"]}


def _year_from_payload(payload: dict) -> int | None:
    citation_year = str(payload.get("citation_year") or "").strip()
    if citation_year[:4].isdigit():
        return int(citation_year[:4])
    for event in payload.get("date_events") or []:
        date = str((event or {}).get("date") or "")
        if date[:4].isdigit():
            return int(date[:4])
    return None


def _chinese_title(payload: dict) -> str | None:
    for translation in payload.get("title_translations") or []:
        language = str((translation or {}).get("language") or "").lower()
        text = str((translation or {}).get("text") or "").strip()
        if language.startswith("zh") and text:
            return text
    return None


def propagate_metadata(context: ResearchContext, work_id: str, payload: dict, *,
                       record_id: str, reviewed_at: str | None = None) -> dict:
    """Write an agent-approved metadata record into the catalog (A6).

    Updates the works row (complete ordered author list, original title, dual
    IDs, year, language, Chinese title) and replaces the active bibliographic
    projection so the export gate (active exportable projection) sees research
    approvals.  Empty/absent fields never blank out existing catalog values;
    the author list is stored complete and ordered.
    """
    original = payload.get("original_title") or {}
    title = str(original.get("text") or "").strip()
    authors = [str((author or {}).get("display_name") or "").strip()
               for author in (payload.get("authors") or [])]
    authors = [name for name in authors if name]
    if not title or not authors:
        raise ValueError(
            f"metadata record {record_id} lacks original_title.text or authors; nothing to propagate")
    year = _year_from_payload(payload)
    title_zh = _chinese_title(payload)
    doi = clean_identifier(payload.get("doi"), kind="doi")
    arxiv = clean_identifier(payload.get("arxiv"), kind="arxiv")
    publication_url = official_publication_url(payload)
    language = str(payload.get("language") or "").strip() or None
    # issue #17：正式 original_abstracts 按共享选择规则进入目录摘要；无摘要
    # 时保持缺失语义（不写不造），works 行与投影用同一选择保证一致。
    abstract = select_catalog_abstract(payload)
    # B9: 文献类型/发表状态经元数据修订贯通书目投影（旧研究分类写入口保持只读）
    document_type = str(payload.get("document_type") or "").strip() or None
    publication_status = str(payload.get("publication_status") or "").strip() or None
    stamp = reviewed_at or datetime.now(timezone.utc).isoformat(timespec="seconds")

    conn = catalog_conn(context, read_only=False)
    try:
        conn.execute("BEGIN IMMEDIATE")
        # Coordinate every projection path with the authoritative research
        # head at the point the catalog write lock is held.  This closes the
        # A-check / B-project / A-project interleaving that could restore an
        # older year after a newer metadata revision was already approved.
        with closing(context.connect(read_only=True)) as research_conn:
            authoritative = research_conn.execute(
                """SELECT id,agent_review_status,content_state,validity_status
                   FROM research_metadata_records
                   WHERE work_id=? AND validity_status='active'
                   ORDER BY version DESC LIMIT 1""", (work_id,)).fetchone()
        if (not authoritative or authoritative["id"] != record_id or
                authoritative["agent_review_status"] != "approved" or
                authoritative["content_state"] != "stable" or
                authoritative["validity_status"] != "active"):
            raise ValueError(
                f"metadata record {record_id} is no longer the approved active head; "
                "catalog projection refused to prevent an interleaved rollback")
        row = conn.execute("SELECT * FROM works WHERE id=?", (work_id,)).fetchone()
        if not row:
            raise ValueError(f"catalog has no work {work_id}; metadata propagation refused")
        works_keys = {r[1] for r in conn.execute("PRAGMA table_info(works)").fetchall()}
        assignments = ["title=?", "authors=?", "title_zh=?", "year=?", "language=?",
                       "doi=?", "arxiv_id=?", "updated_at=?"]
        values = [title, json.dumps(authors, ensure_ascii=False),
                  title_zh or row["title_zh"], year or row["year"],
                  language or row["language"], doi or row["doi"], arxiv or row["arxiv_id"],
                  stamp]
        if abstract and "abstract" in works_keys:
            # 仅当本次记录选择了摘要时写入；选择规则见 select_catalog_abstract。
            assignments.append("abstract=?")
            values.append(abstract)
        if document_type and "doc_type" in works_keys:
            assignments.append("doc_type=?")
            values.append(document_type)
        if publication_status and "publication_status" in works_keys:
            assignments.append("publication_status=?")
            values.append(publication_status)
        for field, value in (
            ("url", publication_url), ("venue", str(payload.get("venue") or "").strip() or None),
            ("volume", str(payload.get("volume") or "").strip() or None),
            ("issue", str(payload.get("issue") or "").strip() or None),
            ("pages", str(payload.get("pages") or "").strip() or None),
        ):
            if value and field in works_keys:
                assignments.append(f"{field}=?")
                values.append(value)
        values.append(work_id)
        conn.execute(
            f"""UPDATE works SET {', '.join(assignments)} WHERE id=?""", values)
        refreshed = conn.execute("SELECT * FROM works WHERE id=?", (work_id,)).fetchone()
        snapshot = projection.payload_from_works_row(refreshed)
        snapshot = projection.merge_v5_payload(snapshot, payload)
        projected = projection.upsert_projection(
            conn, work_id, source_kind="v5_metadata", source_ref=record_id,
            payload=snapshot, exportable=True,
            note=f"research metadata record {record_id} approved (contract v5 A6 propagation)")
        conn.commit()
        return {"catalog": str(catalog_db_path(context)), "work_id": work_id,
                "projection_id": projected["projection_id"],
                "superseded_projection": projected["superseded_projection"],
                "authors_count": len(authors), "propagated_at": stamp}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
