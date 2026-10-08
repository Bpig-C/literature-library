"""Export API routes: BibTeX / RIS / 综述矩阵 CSV。

LL-DECOUPLE-20260920：导出门禁从"旧批准抽取存在"
改为"存在活动且可导出的书目投影（``bibliographic_projections``）"。
导出内容从投影 payload 快照格式化（当前值可追溯到 v5 元数据记录、
legacy 迁移的旧批准书目或明确人工来源）；未达门槛的 work 即使有
``works`` 行也不会混入正式书目导出。
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Query, Response

from ..db import get_conn, table_exists
from ..export_format import work_to_bibtex, work_to_ris, works_to_matrix_csv
from .. import bibliographic_projection as projection
from ..bibliographic_projection import PROJECTION_TABLE

router = APIRouter()


def _select_works(conn, search, doc_type, risk, risk_scope, work_ids):
    """统一过滤。work_ids 只是候选集合，与 search/doc_type/risk 取交集；
    任何情况下都不能突破"活动可导出投影 + 未隔离"门禁。

    未建投影表（迁移前的新库）视为"无任何可导出文献"，如实返回空——
    不回退到任何旧表口径。
    """
    # R1 B2：scope 校验无条件执行（关键词增强也消费它）；非法值 400。
    if risk_scope not in projection.RISK_SCOPES:
        raise HTTPException(status_code=400, detail=(
            f"risk_scope must be one of {projection.RISK_SCOPES} "
            f"(可用基线=approved+stable；当前候选=any active); got {risk_scope!r}"))

    sql = [
        "SELECT w.* FROM works w"
        " WHERE w.read_status != 'quarantined'"
    ]
    params: list = []
    if not table_exists(conn, PROJECTION_TABLE):
        return []
    ids = [i.strip() for i in (work_ids or "").split(",") if i.strip()]
    risk_values = [v for v in (risk or []) if str(v).strip()]
    matched_ids = None
    # 只要请求携带非空 risk，就必须真正解析；研究库不可用时 fail closed。
    # 不允许 work_ids 等其他筛选条件静默覆盖风险口径。
    if risk_values:
        try:
            from ..research_context import get_research_context
            matched_ids = projection.resolve_risk_filter(
                get_research_context(), risk_values, risk_scope)
        except projection.RiskFilterUnavailable as error:
            raise HTTPException(status_code=503, detail={
                "error": "research_store_unavailable",
                "message": ("研究库不可用，风险筛选无法执行；已拒绝生成"
                            "未筛选导出（fail-closed）。请恢复研究库或清空"
                            "风险筛选后重试。"),
                "reason": str(error),
                "risk_scope": risk_scope})
    if ids:
        placeholders = ",".join("?" * len(ids))
        sql.append(f" AND w.id IN ({placeholders})")
        params.extend(ids)
    sql.append(
        " AND EXISTS (SELECT 1 FROM bibliographic_projections p"
        "             WHERE p.work_id = w.id AND p.status = 'active'"
        "               AND p.exportable = 1)")
    if search:
        # 去掉 LIKE 通配符，按字面匹配
        literal = search.replace("%", "").replace("_", "")
        like = f"%{literal}%"
        sql.append(" AND (w.title LIKE ? OR w.title_zh LIKE ? OR w.id LIKE ? OR w.arxiv_id LIKE ?)")
        params.extend([like, like, like, like])
    if doc_type:
        sql.append(" AND (w.primary_doc_type = ? OR w.doc_type = ?)")
        params.extend([doc_type, doc_type])
    if matched_ids is not None:
        if matched_ids:
            placeholders = ",".join("?" * len(matched_ids))
            sql.append(f" AND w.id IN ({placeholders})")
            params.extend(sorted(matched_ids))
        else:
            sql.append(" AND 0")
    sql.append(" ORDER BY w.year DESC, w.id")
    return conn.execute("".join(sql), params).fetchall()


def _load_v5_keywords(risk_scope: str = "usable") -> dict[str, list[str]]:
    """v5 解释关联中的风险现象 → RIS/矩阵关键词（可选信息，不作为门禁）。

    旧 method_tags/risk_domain 标签已退役；关键词来自当前研究解释的
    risk_phenomena，口径与 Works 风险筛选一致。研究库不可用时留空，
    不影响书目导出本身。
    """
    from ..research_context import get_research_context
    keywords: dict[str, list[str]] = {}
    ctx = get_research_context()
    if not ctx.db_path.is_file():
        return keywords
    try:
        from contextlib import closing

        with closing(ctx.connect(read_only=True)) as conn:
            gate = ("validity_status='active' AND agent_review_status='approved' "
                    "AND content_state='stable'" if risk_scope == "usable"
                    else "validity_status='active'")
            rows = conn.execute(
                f"""SELECT s.work_id, je.value
                    FROM research_interpretations i
                    JOIN research_sources s ON s.id = i.source_id,
                    json_each(i.payload_json, '$.risk_phenomena') je
                    WHERE i.{gate}""").fetchall()
            for row in rows:
                value = str(row["value"] or "").strip()
                if value:
                    keywords.setdefault(row["work_id"], []).append(value)
    except Exception as error:  # noqa: BLE001 — informative only, but visible
        logging.getLogger(__name__).warning(
            "v5 keyword enrichment unavailable for export: %s", error)
        return {}
    for work_id in keywords:
        keywords[work_id] = sorted(set(keywords[work_id]))
    return keywords


def _load_digests(conn, ids: list[str]) -> dict:
    """一句话定位：仅取 approved digest；无则不留键（CSV 列留空）。"""
    if not ids:
        return {}
    rows = conn.execute(
        f"SELECT work_id, extracted_json FROM analysis_runs"
        f" WHERE kind = 'digest' AND review_status = 'approved'"
        f" AND (superseded_by IS NULL OR superseded_by = '')"
        f" AND work_id IN ({','.join('?' * len(ids))})"
        f" ORDER BY created_at DESC",
        ids,
    ).fetchall()
    out: dict = {}
    for r in rows:
        if r["work_id"] in out:
            continue
        try:
            value = json.loads(r["extracted_json"])["fields"]["one_sentence_positioning"]["value"]
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            out[r["work_id"]] = str(value)
        except (ValueError, KeyError, TypeError):
            continue
    return out


def _download(body: str, ext: str, media_type: str) -> Response:
    from datetime import datetime, timezone
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="literature-{stamp}.{ext}"'},
    )


def _gather(search, doc_type, risk, risk_scope, work_ids, include_digests: bool = False):
    conn = get_conn()
    try:
        rows = _select_works(conn, search, doc_type, risk, risk_scope, work_ids)
        ids = [w["id"] for w in rows]
        # 导出内容 = 活动投影 payload 快照（含来源可追溯的当前书目值）。
        # 兜底：投影 payload 缺字段时用 works 行补齐（迁移早期边界）。
        projections = projection.load_exportable_payloads(conn)
        works = []
        for row in rows:
            snapshot = dict(projections.get(row["id"]) or {})
            for key in row.keys():
                if snapshot.get(key) in (None, "", []):
                    value = row[key]
                    if value is not None:
                        snapshot[key] = value
            snapshot["id"] = row["id"]
            # export_format 期望 authors 为 JSON 字符串（与 works 行一致）
            if isinstance(snapshot.get("authors"), list):
                snapshot["authors"] = json.dumps(snapshot["authors"], ensure_ascii=False)
            works.append(snapshot)
        # digest 只有矩阵 CSV 用得到，BibTeX/RIS 不多打这条查询
        digests = _load_digests(conn, ids) if include_digests else {}
        keywords = _load_v5_keywords(risk_scope)
        return works, keywords, digests
    finally:
        conn.close()


@router.get("/export/bibtex")
def export_bibtex(
    search: str | None = Query(default=None),
    doc_type: str | None = Query(default=None),
    risk: list[str] | None = Query(default=None),
    risk_scope: str = Query("usable"),
    work_ids: str | None = Query(default=None),
):
    works, _, _ = _gather(search, doc_type, risk, risk_scope, work_ids)
    body = "\n\n".join(work_to_bibtex(w) for w in works)
    return _download(body + "\n", "bib", "text/plain; charset=utf-8")


@router.get("/export/ris")
def export_ris(
    search: str | None = Query(default=None),
    doc_type: str | None = Query(default=None),
    risk: list[str] | None = Query(default=None),
    risk_scope: str = Query("usable"),
    work_ids: str | None = Query(default=None),
):
    works, keywords, _ = _gather(search, doc_type, risk, risk_scope, work_ids)
    body = "\n\n".join(
        work_to_ris(w, {"method_tags": keywords.get(w["id"], [])}) for w in works)
    return _download(body + "\n", "ris", "text/plain; charset=utf-8")


@router.get("/export/matrix.csv")
def export_matrix(
    search: str | None = Query(default=None),
    doc_type: str | None = Query(default=None),
    risk: list[str] | None = Query(default=None),
    risk_scope: str = Query("usable"),
    work_ids: str | None = Query(default=None),
):
    works, keywords, digests = _gather(
        search, doc_type, risk, risk_scope, work_ids, include_digests=True)
    rows = []
    for w in works:
        rows.append({
            **w,
            "tags": {"method_tags": keywords.get(w["id"], []),
                     "risk_domain": keywords.get(w["id"], [])},
            "one_sentence_positioning": digests.get(w["id"], ""),
        })
    return _download(works_to_matrix_csv(rows), "csv", "text/csv; charset=utf-8")
