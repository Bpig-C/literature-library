"""Bibliographic projection: the single exportable current-value view per work.

Contract (legacy-decoupling round, LL-DECOUPLE-20260920 §4.4):

- One active projection per work (partial unique index enforces it).
- Every projection carries an auditable origin: a v5 metadata record, a
  migrated legacy approved extraction, or an explicit catalog edit.
- ``exportable`` is the export gate: BibTeX/RIS/matrix exports only include
  works with an active exportable projection.  A bare ``works`` row never
  leaks into the formal bibliography on its own.
- Superseded projections are kept (never deleted) so history stays
  traceable; the active row is the only "current" value.

The projection payload is a full bibliographic snapshot compatible with the
keys ``api.export_format`` reads from a ``works`` row, so exports format the
projection itself rather than guessing which catalog row is current.
"""
from __future__ import annotations

import json
import uuid
from contextlib import closing
from datetime import datetime, timezone
from .research_stability import (clean_identifier, official_publication_url,
                                 catalog_abstract_statement)
from typing import Any

from .db import table_exists

PROJECTION_TABLE = "bibliographic_projections"

# Fields captured in a projection payload snapshot.  Same names as the
# ``works`` columns so export formatting needs no translation.
PAYLOAD_FIELDS = (
    "title", "title_zh", "authors", "year", "language", "doi", "arxiv_id",
    "doc_type", "primary_doc_type", "publication_status", "venue", "volume",
    "issue", "pages", "url", "abstract", "publication_date_json",
)

SOURCE_KINDS = ("v5_metadata", "legacy_migration", "catalog_edit")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_projection_table(conn) -> None:
    """Create the projection table if missing (idempotent, WAL-safe)."""
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {PROJECTION_TABLE} (
            id TEXT PRIMARY KEY,
            work_id TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{{}}',
            exportable INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'active',
            superseded_by TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute(
        f"""CREATE UNIQUE INDEX IF NOT EXISTS uq_bib_projection_active
            ON {PROJECTION_TABLE}(work_id) WHERE status='active'"""
    )
    conn.execute(
        f"""CREATE INDEX IF NOT EXISTS idx_bib_projection_work
            ON {PROJECTION_TABLE}(work_id, status)"""
    )


def payload_from_works_row(row) -> dict:
    """Snapshot the bibliographic fields of a ``works`` row."""
    keys = set(row.keys())
    payload: dict[str, Any] = {}
    for field in PAYLOAD_FIELDS:
        if field in keys:
            payload[field] = row[field]
    authors = payload.get("authors")
    if isinstance(authors, str):
        try:
            authors = json.loads(authors)
        except (json.JSONDecodeError, TypeError):
            authors = [authors] if authors else []
    payload["authors"] = authors or []
    return payload


def merge_v5_payload(base: dict, v5_payload: dict) -> dict:
    """Overlay an approved v5 metadata payload onto a projection snapshot.

    Empty/absent v5 fields never blank the existing projection values — the
    same rule the catalog-side propagation applies to ``works``.
    """
    def display_names(items) -> list[str]:
        names = []
        for item in items or []:
            name = str(item.get("display_name") or "").strip() if isinstance(item, dict) else ""
            if name:
                names.append(name)
        return names

    overlay: dict[str, Any] = {}
    original = (v5_payload.get("original_title") or {})
    title = str(original.get("text") or "").strip()
    if title:
        overlay["title"] = title
    authors = display_names(v5_payload.get("authors"))
    if authors:
        overlay["authors"] = authors
    year = None
    citation_year = str(v5_payload.get("citation_year") or "").strip()
    if citation_year[:4].isdigit():
        year = int(citation_year[:4])
    else:
        for event in v5_payload.get("date_events") or []:
            date = str((event or {}).get("date") or "")
            if date[:4].isdigit():
                year = int(date[:4])
                break
    if year:
        overlay["year"] = year
    identifiers = {
        "doi": clean_identifier(v5_payload.get("doi"), kind="doi"),
        "arxiv_id": clean_identifier(v5_payload.get("arxiv"), kind="arxiv"),
    }
    overlay.update({key: value for key, value in identifiers.items() if value})
    publication_url = official_publication_url(v5_payload)
    if publication_url:
        overlay["url"] = publication_url
    for src, dst in (("language", "language"), ("venue", "venue"),
                     ("volume", "volume"), ("issue", "issue"),
                     ("pages", "pages")):
        value = str(v5_payload.get(src) or "").strip()
        if value:
            overlay[dst] = value
    # issue #17 / 审计 F2-F3：摘要与目录行同一条状态机——selected 才覆盖；
    # explicit_missing（换版后显式无摘要）清除 base 里与旧版本绑定的摘要并留
    # 缺失说明（历史在被取代投影中保留）；歧义时也清除当前摘要，避免旧值冒充。
    # 字段缺失仅在引用身份不变时保留原值。兼容旧顶层 abstract。
    abstract, abstract_state = catalog_abstract_statement(v5_payload)
    if abstract_state == "selected" and abstract:
        overlay["abstract"] = abstract
    elif abstract_state == "explicit_missing":
        overlay["abstract_note"] = "该版本未提供作者原始摘要；此前版本的摘要不再作为当前投影值（历史见被取代投影）。"
    elif abstract_state == "version_ambiguous":
        overlay["abstract_note"] = "原始摘要的版本范围与当前引用无法确认一致，摘要待确认；历史摘要不作为当前值。"
    for src, dst in (("document_type", "doc_type"),
                     ("publication_status", "publication_status")):
        value = str(v5_payload.get(src) or "").strip()
        if value:
            overlay[dst] = value
    merged = dict(base)
    merged.update({k: v for k, v in overlay.items() if v})
    if (abstract_state in {"explicit_missing", "version_ambiguous"} or
            (abstract_state == "absent" and identifiers["arxiv_id"] and
             identifiers["arxiv_id"] != base.get("arxiv_id"))):
        # 换版缺摘要：base 携带的旧版本摘要（如从 works 行快照带入）不与
        # 新版本身份混用（audit F3）。
        merged.pop("abstract", None)
        merged.setdefault("abstract_note", "当前引用版本的原始摘要未确认；历史摘要保留在旧投影中。")
    elif abstract_state == "selected":
        merged.pop("abstract_note", None)
    return merged


def upsert_projection(
    conn,
    work_id: str,
    *,
    source_kind: str,
    source_ref: str,
    payload: dict,
    exportable: bool = True,
    note: str = "",
) -> dict:
    """Write the new active projection for a work, superseding the previous one.

    Must be called inside the caller's transaction.  Returns a dict describing
    what happened (created vs replaced, superseded id).
    """
    if source_kind not in SOURCE_KINDS:
        raise ValueError(f"unknown projection source_kind: {source_kind}")
    ensure_projection_table(conn)
    now = _now()
    projection_id = f"BP-{uuid.uuid4().hex[:12]}"
    previous = conn.execute(
        f"""SELECT id, source_kind, source_ref FROM {PROJECTION_TABLE}
            WHERE work_id=? AND status='active'""", (work_id,)).fetchone()
    superseded_id = ""
    if previous:
        superseded_id = previous["id"]
        conn.execute(
            f"""UPDATE {PROJECTION_TABLE} SET status='superseded', superseded_by=?,
                updated_at=? WHERE id=?""",
            (projection_id, now, previous["id"]))
    conn.execute(
        f"""INSERT INTO {PROJECTION_TABLE}
            (id, work_id, source_kind, source_ref, payload_json, exportable,
             status, superseded_by, note, created_at, updated_at)
            VALUES (?,?,?,?,?,?, 'active', '', ?, ?, ?)""",
        (projection_id, work_id, source_kind, source_ref,
         json.dumps(payload, ensure_ascii=False), int(bool(exportable)),
         note, now, now))
    return {"projection_id": projection_id, "work_id": work_id,
            "source_kind": source_kind, "source_ref": source_ref,
            "exportable": bool(exportable),
            "superseded_projection": superseded_id or None}


def get_active_projection(conn, work_id: str) -> dict | None:
    """Return the active projection row as a dict (payload decoded), or None."""
    if not table_exists(conn, PROJECTION_TABLE):
        return None
    row = conn.execute(
        f"""SELECT * FROM {PROJECTION_TABLE}
            WHERE work_id=? AND status='active'""", (work_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    item["payload"] = json.loads(item.pop("payload_json") or "{}")
    return item


def active_projection_summary(conn, work_ids: list[str]) -> dict[str, dict]:
    """Active projection metadata for a batch of works (no payloads)."""
    out: dict[str, dict] = {}
    if not work_ids or not table_exists(conn, PROJECTION_TABLE):
        return out
    placeholders = ",".join("?" * len(work_ids))
    for row in conn.execute(
        f"""SELECT work_id, source_kind, source_ref, exportable, updated_at
            FROM {PROJECTION_TABLE}
            WHERE status='active' AND work_id IN ({placeholders})""",
        work_ids):
        out[row["work_id"]] = dict(row)
    return out


def exportable_work_ids(conn) -> set[str] | None:
    """Works that pass the export gate.  None when the table does not exist."""
    if not table_exists(conn, PROJECTION_TABLE):
        return None
    return {row[0] for row in conn.execute(
        f"""SELECT work_id FROM {PROJECTION_TABLE}
            WHERE status='active' AND exportable=1""")}


def load_exportable_payloads(conn) -> dict[str, dict]:
    """work_id → payload snapshot for every active exportable projection."""
    out: dict[str, dict] = {}
    if not table_exists(conn, PROJECTION_TABLE):
        return out
    for row in conn.execute(
        f"""SELECT work_id, payload_json FROM {PROJECTION_TABLE}
            WHERE status='active' AND exportable=1"""):
        payload = json.loads(row["payload_json"] or "{}")
        payload["id"] = row["work_id"]
        out[row["work_id"]] = payload
    return out


def sync_projection_for_work_edit(conn, work_id: str, row) -> dict | None:
    """Keep the active projection consistent after a direct catalog edit.

    A catalog edit is an explicit human origin: the payload snapshot is
    rebuilt from the ``works`` row and the origin flips to ``catalog_edit``.
    The export gate is never lowered by an edit, and a work without a
    projection gains none (an unvetted bare row must not become exportable).
    Returns the upsert result, or None when there was nothing to sync.
    """
    if not table_exists(conn, PROJECTION_TABLE):
        return None
    current = conn.execute(
        f"""SELECT id, exportable FROM {PROJECTION_TABLE}
            WHERE work_id=? AND status='active'""", (work_id,)).fetchone()
    if not current:
        return None
    payload = payload_from_works_row(row)
    return upsert_projection(
        conn, work_id, source_kind="catalog_edit",
        source_ref=f"works-patch-{_now()}", payload=payload,
        exportable=bool(current["exportable"]),
        note="catalog edit; v5 propagation will re-anchor the origin after review")


def projection_stats(conn) -> dict:
    """Counts by source kind / status for stats and drill reports."""
    stats = {"total": 0, "active": 0, "exportable": 0, "by_source_kind": {},
             "table_exists": table_exists(conn, PROJECTION_TABLE)}
    if not stats["table_exists"]:
        return stats
    stats["total"] = conn.execute(
        f"SELECT COUNT(*) FROM {PROJECTION_TABLE}").fetchone()[0]
    stats["active"] = conn.execute(
        f"SELECT COUNT(*) FROM {PROJECTION_TABLE} WHERE status='active'").fetchone()[0]
    stats["exportable"] = conn.execute(
        f"SELECT COUNT(*) FROM {PROJECTION_TABLE} WHERE status='active' AND exportable=1"
    ).fetchone()[0]
    for row in conn.execute(
        f"""SELECT source_kind, COUNT(*) AS n FROM {PROJECTION_TABLE}
            WHERE status='active' GROUP BY source_kind"""):
        stats["by_source_kind"][row["source_kind"]] = row["n"]
    return stats


class RiskFilterUnavailable(Exception):
    """Raised when a risk filter was explicitly requested but the research
    store cannot answer (missing file/table, unreadable, query failure).

    Callers must fail closed: returning the unfiltered set instead would
    present "everything" as if it were the filtered result (R1 B2).
    """


RISK_SCOPES = ("usable", "candidate")


def resolve_risk_filter(context, risk_values, scope: str) -> set[str] | None:
    """Validate the scope and resolve the v5 risk association.

    Returns the matched work-id set, or ``None`` when no risk values were
    requested (no filtering applies).  Raises:

    - ``ValueError`` for an unknown ``risk_scope`` (checked even with no risk
      values — a garbage enum is a client bug, and export keyword enrichment
      consumes the scope regardless);
    - ``RiskFilterUnavailable`` when risk values were requested and the
      research store cannot answer.  The error string carries the cause.
    """
    if scope not in RISK_SCOPES:
        raise ValueError(
            f"risk_scope must be one of {RISK_SCOPES} "
            f"(可用基线=approved+stable；当前候选=any active); got {scope!r}")
    values = [str(v).strip() for v in (risk_values or []) if str(v or "").strip()]
    if not values:
        return None
    association = v5_risk_association(context, values, scope=scope)
    if not association["available"]:
        raise RiskFilterUnavailable(association.get("error") or "unknown cause")
    return association["work_ids"]


def supersede_active_projection(conn, work_id: str, superseded_by: str) -> int:
    """Mark a work's active projection superseded (history kept). Returns 0/1."""
    if not table_exists(conn, PROJECTION_TABLE):
        return 0
    cursor = conn.execute(
        f"""UPDATE {PROJECTION_TABLE} SET status='superseded', superseded_by=?,
            updated_at=? WHERE work_id=? AND status='active'""",
        (superseded_by, _now(), work_id))
    return cursor.rowcount


def v5_risk_association(context, risk_values: list[str], *, scope: str = "usable") -> dict:
    """Which works carry a v5 interpretation associating them with risk values.

    Scope follows the research store's dual reading (contract v5):
    - ``usable``: active + agent-approved + stable content (usable baseline)
    - ``candidate``: any active interpretation (current candidates, unreviewed
      ones included — explicitly labeled, never silently mixed)

    Returns ``{"available": bool, "work_ids": set, "error": str|None}``; an
    unreadable research store is reported, not faked.
    """
    result = {"available": False, "work_ids": set(), "error": None,
              "scope": scope}
    if not risk_values:
        result["available"] = True
        return result
    if not context.db_path.is_file():
        result["error"] = "research store not configured"
        return result
    wanted = [str(v).strip() for v in risk_values if str(v).strip()]
    if not wanted:
        result["available"] = True
        return result
    try:
        with closing(context.connect(read_only=True)) as conn:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "research_interpretations" not in tables:
                result["error"] = "research store has no interpretation table"
                return result
            if scope == "usable":
                gate = ("validity_status='active' AND agent_review_status='approved' "
                        "AND content_state='stable'")
            else:
                gate = "validity_status='active'"
            placeholders = ",".join("?" * len(wanted))
            rows = conn.execute(
                f"""SELECT DISTINCT s.work_id
                    FROM research_interpretations i
                    JOIN research_sources s ON s.id = i.source_id
                    WHERE i.{gate}
                      AND EXISTS (
                          SELECT 1 FROM json_each(i.payload_json, '$.risk_phenomena') je
                          WHERE je.value IN ({placeholders}))""",
                wanted).fetchall()
            result["work_ids"] = {r["work_id"] for r in rows}
            result["available"] = True
    except Exception as error:  # noqa: BLE001 — surfaced to the caller
        result["error"] = str(error)
    return result
