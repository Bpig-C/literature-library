"""Works API routes."""

from __future__ import annotations

import json
import logging
import shutil
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from ..db import get_conn, LIBRARY_ROOT
from ..models import WorkUpdate, QuarantineAction, SourceFileArchiveAction
from ..path_safety import _sanitize_filename, _safe_dest_name, _unique_dest
from ..quarantine import quarantine_work_sources, restore_work_sources, get_restore_read_state, RESTORE_STATE_CODE
from .. import bibliographic_projection as projection

from scripts.migrate_sync_parse_status import sync_work_parse_status

router = APIRouter()

_PROJECTION_ORIGINS = {
    "v5_metadata": "v5 元数据（已核查传播）",
    "legacy_migration": "旧批准书目（legacy migration）",
    "catalog_edit": "目录人工修订",
}


def _work_research_summary(work_id: str) -> dict:
    """v5 research-layer status for one work (read-only, absence-safe)."""
    try:
        from contextlib import closing

        from ..research_context import get_research_context
        ctx = get_research_context()
        if not ctx.db_path.is_file():
            return {"available": False}
        with closing(ctx.connect(read_only=True)) as conn:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "research_sources" not in tables:
                return {"available": False}
            sources = conn.execute(
                "SELECT id, work_id FROM research_sources WHERE work_id=?",
                (work_id,)).fetchall()
            if not sources:
                return {"available": True, "staged": False}
            summary = {"available": True, "staged": True,
                       "source_ids": [s["id"] for s in sources]}
            if "research_metadata_records" in tables:
                head = conn.execute(
                    """SELECT id, version, agent_review_status, content_state,
                              validity_status FROM research_metadata_records
                       WHERE work_id=? AND validity_status='active'
                       ORDER BY version DESC LIMIT 1""", (work_id,)).fetchone()
                summary["metadata_head"] = dict(head) if head else None
            if "research_interpretations" in tables:
                rows = conn.execute(
                    """SELECT i.id, i.batch_id, i.validity_status,
                              i.agent_review_status, i.content_state, i.payload_json
                       FROM research_interpretations i
                       JOIN research_sources s ON s.id=i.source_id
                       WHERE s.work_id=? ORDER BY i.updated_at DESC""", (work_id,)).fetchall()
                interpretations = []
                for r in rows:
                    item = {k: r[k] for k in
                            ("id", "batch_id", "validity_status",
                             "agent_review_status", "content_state")}
                    try:
                        payload = json.loads(r["payload_json"] or "{}")
                        item["risk_phenomena"] = list(
                            payload.get("risk_phenomena") or [])
                    except (json.JSONDecodeError, TypeError):
                        item["risk_phenomena"] = []
                    interpretations.append(item)
                summary["interpretations"] = interpretations
            return summary
    except Exception as error:  # noqa: BLE001 — surfaced with cause, logged
        logging.getLogger(__name__).warning(
            "research summary unavailable for %s: %s", work_id, error)
        return {"available": False, "error": str(error)}


def _safe_json(value: str | None, default=None):
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _work_catalog_metadata_payload(row, head_payload: dict | None = None) -> dict:
    """Catalog row + previous approved payload → next metadata revision payload.

    B9 无损继承: the new revision starts from the current head payload so
    standard fields (citation_year, resources, …) and every named extension
    survive the round-trip; only the catalog-edited bibliographic fields are
    overwritten, and the catalog-sync extension is updated in place.  Without
    a head payload (first revision) the definition minimal is built directly.
    """
    keys = set(row.keys())
    payload: dict = dict(head_payload or {})
    authors = row["authors"] if "authors" in keys else None
    if isinstance(authors, str):
        authors = _safe_json(authors, default=[authors])
    if not isinstance(authors, list):
        authors = []
    catalog_names = [str(a if not isinstance(a, dict) else a.get("display_name") or "").strip()
                     for a in authors]
    catalog_names = [n for n in catalog_names if n]
    # B9 无损继承（作者属性）：目录侧只保存显示名，party_roles/ORCID 等
    # 属性仅存于研究元数据。 先按显示名匹配既有身份，因而重排时属性跟随
    # 作者、替换/新增作者不继承被替换位置的 ORCID。重复同名按既有顺序消费，
    # 不臆造一个更强的身份解析平台。
    head_authors = [a for a in (payload.get("authors") or [])
                    if isinstance(a, dict) and str(a.get("display_name") or "").strip()]
    author_items = []
    remaining = list(head_authors)
    for name in catalog_names:
        kept = next((a for a in remaining
                     if str(a.get("display_name")).strip() == name), None)
        if kept is not None:
            remaining.remove(kept)
            merged = dict(kept)
            merged["display_name"] = name
            author_items.append(merged)
        else:
            author_items.append({"display_name": name})
    language = row["language"] if "language" in keys and row["language"] else "unknown"
    payload["original_title"] = {"text": row["title"] or "", "language": language}
    payload["authors"] = author_items
    if "year" in keys and row["year"] is not None:
        payload["citation_year"] = str(row["year"])
    if "doi" in keys and row["doi"]:
        payload["doi"] = row["doi"]
    else:
        payload.pop("doi", None)
    watched = ("title", "authors", "year", "arxiv_id", "doi", "doc_type", "language",
               "venue", "abstract", "publication_date_json", "is_core_literature")
    changed = {key: row[key] for key in watched if key in keys and row[key] is not None}
    extensions = [e for e in (payload.get("extensions") or [])
                  if isinstance(e, dict) and e.get("name") != "catalog-sync"]
    extensions.append({
        "name": "catalog-sync",
        "content": {"changed_fields": sorted(changed), "current_values": changed},
        "source": "PATCH /works/{work_id} 目录便捷修改",
        "scope": "record",
        "needs_verification": True,
    })
    payload["extensions"] = extensions
    return payload


def _bridge_work_metadata_revision(work_id: str) -> dict | None:
    """v5 stores: a catalog metadata edit must enter the unified revision
    mechanism as a metadata revision — otherwise the research layer keeps a
    second, divergent "current value" (contract v5 B9).  v4/legacy stores are
    left untouched: catalog-only edit, reported as legacy_catalog_update."""
    try:
        from contextlib import closing

        from ..research_context import get_research_context
        from ..research_catalog import catalog_available, catalog_conn
        from ..research_errors import ResearchOperationError
        from ..research_next import ResearchNextService
        from ..research_service import research_v5_available
        ctx = get_research_context()
        with closing(ctx.connect(read_only=True)) as rconn:
            if not research_v5_available(rconn):
                return {"metadata_bridge": "legacy_catalog_update"}
            head = rconn.execute(
                """SELECT id, payload_json FROM research_metadata_records
                   WHERE work_id=? AND validity_status='active'
                   ORDER BY version DESC LIMIT 1""", (work_id,)
            ).fetchone()
        row = None
        if catalog_available(ctx):
            with closing(catalog_conn(ctx, read_only=True)) as cconn:
                row = cconn.execute("SELECT * FROM works WHERE id=?", (work_id,)).fetchone()
        if row is None:
            return None
        head_payload = json.loads(head["payload_json"]) if head else None
        payload = _work_catalog_metadata_payload(row, head_payload)
        nxt = ResearchNextService(ctx)
        env_id = nxt.environment_id()
        try:
            result = nxt.submit_metadata_record(work_id=work_id, payload=payload,
                                                submitted_by="catalog-bridge",
                                                environment_id=env_id)
        except ResearchOperationError as error:
            if error.category != "revision_conflict" or not head:
                raise
            result = nxt.submit_metadata_record(work_id=work_id, payload=payload,
                                                supersedes_id=head["id"],
                                                submitted_by="catalog-bridge",
                                                environment_id=env_id)
        result["metadata_bridge"] = ("unified_revision_current"
                                     if result.get("created") is False
                                     else "unified_revision_created")
        return result
    except Exception as error:  # never block the catalog edit itself
        return {"metadata_bridge": "failed", "detail": str(error)}


def _work_metadata_propagation(work_id: str) -> dict | None:
    """Persisted propagation state of the work's current metadata revision."""
    try:
        from contextlib import closing

        from ..research_context import get_research_context
        from ..research_service import research_v5_available
        ctx = get_research_context()
        with closing(ctx.connect(read_only=True)) as rconn:
            if not research_v5_available(rconn):
                return None
            cols = {r[1] for r in rconn.execute(
                "PRAGMA table_info(research_metadata_records)").fetchall()}
            if "propagation_state_json" not in cols:
                return None
            row = rconn.execute(
                """SELECT id, version, propagation_state_json FROM research_metadata_records
                   WHERE work_id=? AND validity_status='active'
                   ORDER BY version DESC LIMIT 1""", (work_id,)).fetchone()
        if not row:
            return None
        return {"record_id": row["id"], "version": row["version"],
                "state": json.loads(row["propagation_state_json"] or "null")}
    except Exception:
        return None


def _bridge_type_metadata_revision(work_id: str, type_changes: dict) -> dict | None:
    """B9(R6): carry document_type/publication_status into a metadata revision.

    The catalog row is NOT touched here; the revision enters the unified
    mechanism and only an approved revision propagates the projection.
    """
    try:
        from contextlib import closing

        from ..research_context import get_research_context
        from ..research_catalog import catalog_available, catalog_conn
        from ..research_errors import ResearchOperationError
        from ..research_next import ResearchNextService
        from ..research_service import research_v5_available
        ctx = get_research_context()
        with closing(ctx.connect(read_only=True)) as rconn:
            if not research_v5_available(rconn):
                return {"type_bridge": "legacy_catalog_update"}
            head = rconn.execute(
                """SELECT id, payload_json FROM research_metadata_records
                   WHERE work_id=? AND validity_status='active'
                   ORDER BY version DESC LIMIT 1""", (work_id,)).fetchone()
        row = None
        if catalog_available(ctx):
            with closing(catalog_conn(ctx, read_only=True)) as cconn:
                row = cconn.execute("SELECT * FROM works WHERE id=?", (work_id,)).fetchone()
        if row is None:
            return None
        head_payload = json.loads(head["payload_json"]) if head else None
        payload = _work_catalog_metadata_payload(row, head_payload)
        if type_changes.get("doc_type") is not None:
            payload["document_type"] = str(type_changes["doc_type"])
        if type_changes.get("publication_status") is not None:
            payload["publication_status"] = str(type_changes["publication_status"])
        nxt = ResearchNextService(ctx)
        env_id = nxt.environment_id()
        try:
            result = nxt.submit_metadata_record(work_id=work_id, payload=payload,
                                                submitted_by="catalog-bridge",
                                                environment_id=env_id)
        except ResearchOperationError as error:
            if error.category != "revision_conflict" or not head:
                raise
            result = nxt.submit_metadata_record(work_id=work_id, payload=payload,
                                                supersedes_id=head["id"],
                                                submitted_by="catalog-bridge",
                                                environment_id=env_id)
        result["type_bridge"] = "metadata_revision_created"
        return result
    except Exception as error:  # never block the catalog edit itself
        return {"type_bridge": "failed", "detail": str(error)}


@router.get("/works")
def list_works(
    status: str = "all",
    doc_type: str = "all",
    language: str = "all",
    search: str = "",
    sort: str = "id",
    order: str = "asc",
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    include_quarantined: bool = Query(False),
    # Classification v0.2 filters
    primary_doc_type: str | None = Query(None),
    publication_status: str | None = Query(None),
    ingestion_state: str | None = Query(None),
    priority: str | None = Query(None),
    # v5 risk association filter (LL-DECOUPLE-20260920 §4.5): reads current
    # research interpretations, not the retired legacy tag tables.
    risk: list[str] | None = Query(default=None),
    risk_scope: str = Query("usable"),
    # Classified-only filter
    classified_only: bool = Query(False),
):
    conn = get_conn()
    try:
        where = []
        params = []

        # Exclude quarantined by default
        if not include_quarantined and status == "all":
            where.append("w.read_status != 'quarantined'")

        if status != "all":
            where.append("w.read_status = ?")
            params.append(status)
        if doc_type != "all":
            where.append("w.doc_type = ?")
            params.append(doc_type)
        if language != "all":
            where.append("w.language = ?")
            params.append(language)
        if primary_doc_type is not None:
            where.append("w.primary_doc_type = ?")
            params.append(primary_doc_type)
        if publication_status is not None:
            where.append("w.publication_status = ?")
            params.append(publication_status)
        if ingestion_state is not None:
            where.append("w.ingestion_state = ?")
            params.append(ingestion_state)
        if priority is not None:
            where.append("w.priority = ?")
            params.append(priority)

        # Classified-only filter
        if classified_only:
            where.append("w.primary_doc_type IS NOT NULL AND w.primary_doc_type != ''")

        risk_filter_note = None
        risk_values = [v for v in (risk or []) if str(v).strip()]
        try:
            from ..research_context import get_research_context
            from ..bibliographic_projection import (resolve_risk_filter,
                                                    RiskFilterUnavailable)
            matched_ids = resolve_risk_filter(
                get_research_context(), risk_values, risk_scope)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        except RiskFilterUnavailable as error:
            # R1 B2 fail-closed：用户显式要求风险筛选而研究库无法回答时，
            # 拒绝返回未筛选全集。
            raise HTTPException(status_code=503, detail={
                "error": "research_store_unavailable",
                "message": ("研究库不可用，风险筛选无法执行；已拒绝返回"
                            "未筛选结果（fail-closed）。请恢复研究库或清空"
                            "风险筛选后重试。"),
                "reason": str(error),
                "risk_scope": risk_scope})
        if matched_ids is not None:
            if matched_ids:
                placeholders = ",".join("?" * len(matched_ids))
                where.append(f"w.id IN ({placeholders})")
                params.extend(sorted(matched_ids))
            else:
                where.append("0")
            risk_filter_note = (
                f"v5 风险关联筛选（口径={('可用基线' if risk_scope == 'usable' else '当前候选')}，"
                f"命中 {len(matched_ids)} 篇）")
        if search:
            where.append(
                "(w.title LIKE ? OR w.id LIKE ? OR w.arxiv_id LIKE ? OR w.doi LIKE ?)"
            )
            like = f"%{search}%"
            params.extend([like, like, like, like])

        where_clause = (" WHERE " + " AND ".join(where)) if where else ""

        # Summary stats
        stats = {}
        for row in conn.execute(
            "SELECT read_status, COUNT(*) as cnt FROM works GROUP BY read_status"
        ):
            stats[row["read_status"]] = row["cnt"]
        total = sum(stats.values())

        doc_type_counts = {}
        for row in conn.execute(
            "SELECT doc_type, COUNT(*) as cnt FROM works GROUP BY doc_type"
        ):
            doc_type_counts[row["doc_type"] or "unknown"] = row["cnt"]

        lang_counts = {}
        for row in conn.execute(
            "SELECT language, COUNT(*) as cnt FROM works GROUP BY language"
        ):
            lang_counts[row["language"] or "unknown"] = row["cnt"]

        relation_count = conn.execute("SELECT COUNT(*) FROM work_relations").fetchone()[
            0
        ]

        # Total matching (for pagination)
        count_row = conn.execute(
            f"SELECT COUNT(*) FROM works w{where_clause}", params
        ).fetchone()
        total_matching = count_row[0]

        # Valid sort columns
        sort_col = {
            "id": "w.id",
            "title": "w.title",
            "year": "w.year",
            "created_at": "w.created_at",
            "read_status": "w.read_status",
        }.get(sort, "w.id")
        sort_dir = "DESC" if order.lower() == "desc" else "ASC"

        offset = (page - 1) * per_page
        rows = conn.execute(
            f"SELECT w.* FROM works w{where_clause} ORDER BY {sort_col} {sort_dir} LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()

        works = []
        projection_summaries = projection.active_projection_summary(
            conn, [row["id"] for row in rows])
        for row in rows:
            d = dict(row)
            d["authors"] = _safe_json(d.get("authors"), [])
            # Source count (active only)
            sc = conn.execute(
                "SELECT COUNT(*) FROM source_files WHERE work_id = ? AND status = 'active'", (d["id"],)
            ).fetchone()
            d["source_count"] = sc[0]
            # Unique source count (distinct SHA256 among active)
            uc = conn.execute(
                "SELECT COUNT(DISTINCT content_sha256) FROM source_files WHERE work_id = ? AND status = 'active'",
                (d["id"],),
            ).fetchone()
            d["unique_source_count"] = uc[0]
            # Total source count (including archived)
            tc = conn.execute(
                "SELECT COUNT(*) FROM source_files WHERE work_id = ?", (d["id"],)
            ).fetchone()
            d["total_source_count"] = tc[0]
            d["bibliographic_projection"] = projection_summaries.get(d["id"])
            works.append(d)

        return {
            "works": works,
            "total": total,
            "total_matching": total_matching,
            "page": page,
            "per_page": per_page,
            "risk_filter_note": risk_filter_note,
            "summary": {
                "total": total,
                "statuses": stats,
                "doc_types": doc_type_counts,
                "languages": lang_counts,
                "relations": relation_count,
            },
        }
    finally:
        conn.close()


@router.get("/works/{work_id}")
def get_work(work_id: str):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Work not found")

        work = dict(row)
        work["authors"] = _safe_json(work.get("authors"), [])
        work["contributors"] = _safe_json(work.get("contributors"), [])

        # B9(R6): the current metadata revision's persisted propagation state
        # (failed/pending retry) is surfaced so it stays visible across
        # refresh/restart instead of living only in one response.
        work["metadata_propagation"] = _work_metadata_propagation(work_id)

        # Source files (active and archived separately)
        sources = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM source_files WHERE work_id = ? AND status = 'active'", (work_id,)
            ).fetchall()
        ]
        archived_sources = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM source_files WHERE work_id = ? AND status = 'archived'", (work_id,)
            ).fetchall()
        ]

        # Relations
        relations = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM work_relations WHERE work_id_a = ? OR work_id_b = ?",
                (work_id, work_id),
            ).fetchall()
        ]
        # Enrich relations with partner titles
        for rel in relations:
            partner_id = (
                rel["work_id_b"] if rel["work_id_a"] == work_id else rel["work_id_a"]
            )
            partner = conn.execute(
                "SELECT title FROM works WHERE id = ?", (partner_id,)
            ).fetchone()
            rel["partner_title"] = partner["title"] if partner else partner_id

        # Work codes
        codes = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM work_codes WHERE work_id = ? AND code != ?", (work_id, RESTORE_STATE_CODE)
            ).fetchall()
        ]

        # Duplicate candidates
        duplicates = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM duplicate_candidates WHERE work_id = ?", (work_id,)
            ).fetchall()
        ]

        # Parse runs
        runs = []
        if work.get("parse_status") != "unknown":
            runs = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM literature_parse_runs WHERE work_id = ?",
                    (work_id,),
                ).fetchall()
            ]

        # Bibliographic projection: the exportable current-value view and its
        # auditable origin (v5 record / legacy migration / catalog edit).
        # Retired with LL-DECOUPLE-20260920: legacy classification tags and
        # extraction statuses are no longer part of the active detail view.
        work["bibliographic_projection"] = projection.get_active_projection(conn, work_id)
        if work["bibliographic_projection"] is not None:
            work["bibliographic_projection"]["origin_label"] = _PROJECTION_ORIGINS.get(
                work["bibliographic_projection"]["source_kind"],
                work["bibliographic_projection"]["source_kind"])

        # v5 research status summary (read from the research store; absent
        # store simply reports unavailable instead of faking legacy states).
        work["research_summary"] = _work_research_summary(work_id)

        work["source_files"] = sources
        work["archived_source_files"] = archived_sources
        work["relations"] = relations
        work["codes"] = codes
        work["duplicates"] = duplicates
        work["parse_runs"] = runs

        return work
    finally:
        conn.close()


@router.patch("/works/{work_id}")
def update_work(work_id: str, body: WorkUpdate):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Work not found")

        # B9(R6): 文献类型/发表状态经**元数据修订**贯通（doc_type →
        # document_type、publication_status），目录值在独立核查通过后才投影，
        # 响应如实说明“当前书目未变”。其余分类轴（研究分类）保持只读。
        _CLASSIFICATION_FIELDS = ("primary_doc_type", "secondary_doc_type",
                                  "ingestion_state", "priority",
                                  "is_core_literature", "primary_source_actor_type",
                                  "region", "canonical_file_format")
        body_data_gate = body.model_dump(exclude_unset=True)
        metadata_type_changes = {
            field: body_data_gate[field] for field in ("doc_type", "publication_status")
            if field in body_data_gate and body_data_gate[field] is not None
            and field in row.keys() and row[field] != body_data_gate[field]
        }
        classification_changes = {
            field: body_data_gate[field] for field in _CLASSIFICATION_FIELDS
            if field in body_data_gate and body_data_gate[field] is not None
            and field in row.keys() and row[field] != body_data_gate[field]
        }
        if classification_changes:
            from .classification import _legacy_classification_readonly_reason
            reason = _legacy_classification_readonly_reason()
            if reason:
                raise HTTPException(status_code=409, detail={
                    "error": "classification_readonly",
                    "message": reason + " 文献详情页的分类字段修改（"
                               + ", ".join(sorted(classification_changes))
                               + "）同样被拒绝；书目信息（题名/作者/年份等）仍可正常修订。",
                    "classification_fields": sorted(classification_changes),
                })
        # 类型/发表状态不直接写目录：从书目字段更新中剔除，改为携带进元数据
        # 修订（document_type/publication_status），独立核查通过后才投影。
        for _type_field in metadata_type_changes:
            body_data_gate.pop(_type_field, None)

        updates = []
        params = []
        # Handle month -> publication_date_json sync
        body_data = body_data_gate
        month_val = body_data.pop("month", None)
        if month_val is not None:
            # Update publication_date_json with month
            date_json = json.loads(row["publication_date_json"] or "{}") if row["publication_date_json"] else {}
            date_json["month"] = month_val
            if "year" not in date_json and row["year"]:
                date_json["year"] = row["year"]
            updates.append("publication_date_json = ?")
            params.append(json.dumps(date_json, ensure_ascii=False))
        for field, value in body_data.items():
            if field == "authors":
                updates.append("authors = ?")
                params.append(json.dumps(value, ensure_ascii=False))
            elif field == "is_core_literature" and value is not None:
                updates.append("is_core_literature = ?")
                params.append(1 if value else 0)
            elif field == "publication_date_json" and value is not None:
                # Direct update of publication_date_json
                updates.append("publication_date_json = ?")
                params.append(value)
            elif value is not None:
                updates.append(f"{field} = ?")
                params.append(value)

        if updates:
            from datetime import datetime, timezone

            updates.append("updated_at = ?")
            params.append(datetime.now(timezone.utc).isoformat(timespec="seconds"))
            params.append(work_id)
            conn.execute(
                f"UPDATE works SET {', '.join(updates)} WHERE id = ?", params
            )
            # LL-DECOUPLE-20260920: keep the active bibliographic projection in
            # step with the edited catalog row (origin flips to catalog_edit;
            # a work without a projection gains none — the export gate is not
            # lowered by a bare-row edit).
            refreshed = conn.execute(
                "SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
            projection_sync = projection.sync_projection_for_work_edit(
                conn, work_id, refreshed)
            conn.commit()
            # v5: the same change must exist as a metadata revision in the
            # unified mechanism — otherwise the research layer keeps a second
            # "current value" (contract v5 B9). Never blocks the catalog edit.
            bridge = _bridge_work_metadata_revision(work_id)
        else:
            projection_sync = None
            bridge = None

        # B9(R6): 类型/发表状态修改不写目录——作为元数据修订（document_type/
        # publication_status）进入统一机制，独立核查通过后由传播投影。
        type_bridge = None
        if metadata_type_changes:
            type_bridge = _bridge_type_metadata_revision(work_id, metadata_type_changes)

        return {"ok": True, "work_id": work_id, "metadata_bridge": bridge,
                "projection_sync": projection_sync,
                "type_revision": type_bridge,
                "type_note": ("文献类型/发表状态修改已作为元数据修订提交（待独立核查）；"
                              "当前书目值未变，核查通过后自动投影。")
                              if metadata_type_changes else None}
    finally:
        conn.close()


@router.post("/works/{work_id}/quarantine")
def quarantine_work(work_id: str, body: QuarantineAction = QuarantineAction()):
    """Quarantine a work: move sources to _quarantine/, mark work + sources
    quarantined. Delegates to the shared nucleus (single policy + status sync)."""
    conn = get_conn()
    try:
        conn.execute('BEGIN IMMEDIATE')  # Serialize state reads and file moves across workers.
        moved_files = quarantine_work_sources(
            conn, LIBRARY_ROOT, work_id, reason=body.reason, code="bad_source"
        )
        conn.commit()
        return {"ok": True, "work_id": work_id, "moved_files": moved_files}
    finally:
        conn.close()


@router.post("/works/{work_id}/restore")
def restore_work(work_id: str):
    """Restore a quarantined work: move sources back, mark work + sources active.
    Delegates to the shared nucleus."""
    conn = get_conn()
    try:
        conn.execute('BEGIN IMMEDIATE')
        read_status, basis = get_restore_read_state(conn, work_id)
        moved_files = restore_work_sources(conn, LIBRARY_ROOT, work_id)
        conn.commit()
        return {"ok": True, "work_id": work_id, "moved_files": moved_files,
                "read_status": read_status, "read_status_basis": basis,
                "warning": "Historical reading state was not recorded; restored as unread." if basis == 'legacy_default_unread' else None}
    finally:
        conn.close()


@router.post("/works/{work_id}/sources/{source_file_id}/archive")
def archive_source_file(work_id: str, source_file_id: str, body: SourceFileArchiveAction):
    """Archive a single source file: move to _archive, mark archived, recalc parse_status."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Work not found")

        sf = conn.execute(
            "SELECT * FROM source_files WHERE id = ? AND work_id = ?",
            (source_file_id, work_id),
        ).fetchone()
        if not sf:
            raise HTTPException(status_code=404, detail="Source file not found")

        src = Path(sf["source_path"])
        if not src.exists():
            raise HTTPException(
                status_code=409,
                detail={"error": "source_file_missing", "path": str(src)},
            )

        dest_name = _safe_dest_name(dict(sf), sf["source_path"])
        archive_dir = LIBRARY_ROOT / "_archive" / work_id
        archive_dir.mkdir(parents=True, exist_ok=True)
        dest = _unique_dest(archive_dir / dest_name)

        shutil.move(str(src), str(dest))

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn.execute(
            "UPDATE source_files SET status='archived', archived_at=?, "
            "archive_path=?, archive_reason=?, source_path=? WHERE id=?",
            (now, str(dest), body.reason, str(dest), source_file_id),
        )

        parse_status = sync_work_parse_status(conn, work_id)
        conn.commit()
        return {
            "ok": True,
            "work_id": work_id,
            "source_file_id": source_file_id,
            "parse_status": parse_status,
        }
    finally:
        conn.close()


@router.post("/works/{work_id}/sources/{source_file_id}/restore")
def restore_source_file(work_id: str, source_file_id: str):
    """Restore an archived source file: move back to works/{work_id}/source/, mark active, recalc parse_status."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Work not found")

        sf = conn.execute(
            "SELECT * FROM source_files WHERE id = ? AND work_id = ?",
            (source_file_id, work_id),
        ).fetchone()
        if not sf:
            raise HTTPException(status_code=404, detail="Source file not found")

        src = Path(sf["archive_path"] or sf["source_path"])
        if not src.exists():
            raise HTTPException(
                status_code=409,
                detail={"error": "archived_file_missing", "path": str(src)},
            )

        dest_name = _safe_dest_name(dict(sf), sf["source_path"])
        work_dir = LIBRARY_ROOT / "works" / work_id / "source"
        work_dir.mkdir(parents=True, exist_ok=True)
        dest = _unique_dest(work_dir / dest_name)

        shutil.move(str(src), str(dest))

        conn.execute(
            "UPDATE source_files SET status='active', "
            "archived_at=NULL, archive_path=NULL, archive_reason=NULL, "
            "source_path=? WHERE id=?",
            (str(dest), source_file_id),
        )

        parse_status = sync_work_parse_status(conn, work_id)
        conn.commit()

        # Clean up empty archive directory
        archive_dir = LIBRARY_ROOT / "_archive" / work_id
        if archive_dir.exists():
            try:
                archive_dir.rmdir()
            except OSError:
                pass

        return {
            "ok": True,
            "work_id": work_id,
            "source_file_id": source_file_id,
            "parse_status": parse_status,
        }
    finally:
        conn.close()
