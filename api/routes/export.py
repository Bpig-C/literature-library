"""Export API routes: BibTeX / RIS / 综述矩阵 CSV。

阶段一出口侧最小闭环（docs/superpowers/plans/2026-07-18-export-minimal-loop.md）。
统一过滤规则：read_status != 'quarantined' 且存在 approved 的 metadata_extractions。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Response

from ..db import get_conn
from ..export_format import work_to_bibtex, work_to_ris, works_to_matrix_csv

router = APIRouter()


def _select_works(conn, search, doc_type, tag, work_ids):
    """统一过滤。work_ids 显式指定时优先于 search/doc_type/tag（后者被忽略），
    但任何情况下都不能突破"approved 元数据 + 未隔离"门禁。"""
    sql = [
        "SELECT w.* FROM works w"
        " WHERE w.read_status != 'quarantined'"
        " AND EXISTS (SELECT 1 FROM metadata_extractions m"
        "             WHERE m.work_id = w.id AND m.review_status = 'approved')"
    ]
    params: list = []
    ids = [i.strip() for i in (work_ids or "").split(",") if i.strip()]
    if ids:
        sql.append(f" AND w.id IN ({','.join('?' * len(ids))})")
        params.extend(ids)
    else:
        if search:
            # 去掉 LIKE 通配符，按字面匹配
            literal = search.replace("%", "").replace("_", "")
            like = f"%{literal}%"
            sql.append(" AND (w.title LIKE ? OR w.title_zh LIKE ? OR w.id LIKE ? OR w.arxiv_id LIKE ?)")
            params.extend([like, like, like, like])
        if doc_type:
            sql.append(" AND (w.primary_doc_type = ? OR w.doc_type = ?)")
            params.extend([doc_type, doc_type])
        if tag:
            sql.append(
                " AND EXISTS (SELECT 1 FROM work_classification_tags t"
                "             WHERE t.work_id = w.id AND t.tag_value = ? AND t.review_status = 'approved')"
            )
            params.append(tag)
    sql.append(" ORDER BY w.year DESC, w.id")
    return conn.execute("".join(sql), params).fetchall()


def _load_tags(conn, ids: list[str]) -> dict:
    if not ids:
        return {}
    rows = conn.execute(
        f"SELECT work_id, tag_group, tag_value FROM work_classification_tags"
        f" WHERE work_id IN ({','.join('?' * len(ids))}) AND review_status = 'approved'"
        f" ORDER BY tag_group, tag_value",
        ids,
    ).fetchall()
    tags: dict = {}
    for r in rows:
        tags.setdefault(r["work_id"], {}).setdefault(r["tag_group"], []).append(r["tag_value"])
    return tags


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
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="literature-{stamp}.{ext}"'},
    )


def _gather(search, doc_type, tag, work_ids):
    conn = get_conn()
    try:
        works = [dict(r) for r in _select_works(conn, search, doc_type, tag, work_ids)]
        ids = [w["id"] for w in works]
        return works, _load_tags(conn, ids), _load_digests(conn, ids)
    finally:
        conn.close()


@router.get("/export/bibtex")
def export_bibtex(
    search: str | None = Query(default=None),
    doc_type: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    work_ids: str | None = Query(default=None),
):
    works, tags, _ = _gather(search, doc_type, tag, work_ids)
    body = "\n\n".join(work_to_bibtex(w) for w in works)
    return _download(body + "\n", "bib", "text/plain; charset=utf-8")


@router.get("/export/ris")
def export_ris(
    search: str | None = Query(default=None),
    doc_type: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    work_ids: str | None = Query(default=None),
):
    works, tags, _ = _gather(search, doc_type, tag, work_ids)
    body = "\n\n".join(work_to_ris(w, tags.get(w["id"], {})) for w in works)
    return _download(body + "\n", "ris", "text/plain; charset=utf-8")


@router.get("/export/matrix.csv")
def export_matrix(
    search: str | None = Query(default=None),
    doc_type: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    work_ids: str | None = Query(default=None),
):
    works, tags, digests = _gather(search, doc_type, tag, work_ids)
    rows = []
    for w in works:
        rows.append({
            **w,
            "tags": tags.get(w["id"], {}),
            "one_sentence_positioning": digests.get(w["id"], ""),
        })
    return _download(works_to_matrix_csv(rows), "csv", "text/csv; charset=utf-8")
