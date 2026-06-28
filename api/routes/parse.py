"""Parse trigger/status API routes. Thin adapter over the parser nucleus.

单核：本模块不写解析路由逻辑——触发委托 core.mineru.router.route_and_parse（经
_run_parse 单点）；works.parse_status 同步委托 scripts.migrate_sync_parse_status。
状态读写键控 literature_parse_runs（DB，非 ledger 文件）。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import get_conn, LIBRARY_ROOT

# 让 parser 子项目（core.mineru.*）可导入。与 scripts/ 约定一致。
_PARSER_ROOT = LIBRARY_ROOT / "parser"
if str(_PARSER_ROOT) not in sys.path:
    sys.path.insert(0, str(_PARSER_ROOT))

from core.mineru.router import route_and_parse  # noqa: E402（惰性 import，不触发 fitz）

# works.parse_status 同步 helper（Flag 4：复用既有同步逻辑，不造第三套）
from scripts.migrate_sync_parse_status import sync_work_parse_status  # noqa: E402

router = APIRouter()


def _run_output_dir(run_work_id: str, source_file_id: str) -> Path:
    """契约输出目录（绝对）：{LIBRARY_ROOT}/works/{work_id}/parsed/mineru/{sfid}。"""
    return Path(LIBRARY_ROOT) / "works" / run_work_id / "parsed" / "mineru" / source_file_id


def _row_to_pending(d: dict) -> dict:
    """规整一行 parse_run → 触发所需的字段集；output_dir 缺失则按契约重算。"""
    sf_id = (d.get("id") or "").replace("LPR-", "") or d.get("source_file_id", "")
    out_dir = d.get("output_dir") or str(_run_output_dir(d["work_id"], sf_id))
    return {
        "run_id": d.get("id"),
        "source_file_id": sf_id,
        "work_id": d["work_id"],
        "source_path": d["source_path"],
        "output_dir": out_dir,
        "language": d.get("language") or "",  # works.language 原值（LEFT JOIN 带出）
    }


def list_pending_runs(conn, work_ids: list[str] | None = None) -> list[dict]:
    where = ["pr.status = 'pending'"]
    params: list = []
    if work_ids:
        where.append(f"pr.work_id IN ({','.join('?' * len(work_ids))})")
        params.extend(work_ids)
    rows = conn.execute(
        f"""SELECT pr.id, pr.work_id, pr.source_file_id, pr.source_path, pr.output_dir,
                  w.language AS language
           FROM literature_parse_runs pr
           LEFT JOIN works w ON w.id = pr.work_id
           WHERE {' AND '.join(where)}
           ORDER BY pr.id""",
        params,
    ).fetchall()
    return [_row_to_pending(dict(r)) for r in rows]


@router.get("/parse/status")
def parse_status(work_id: str | None = None):
    conn = get_conn()
    try:
        if work_id:
            row = conn.execute(
                """SELECT pr.work_id, pr.status, pr.content_md_path, pr.backend,
                          pr.error, pr.finished_at
                   FROM literature_parse_runs pr
                   WHERE pr.work_id=? ORDER BY pr.id LIMIT 1""",
                (work_id,),
            ).fetchone()
            if not row:
                raise HTTPException(404, f"no parse_run for work {work_id}")
            d = dict(row)
            return {"work": d}
        # 汇总
        counts = {"pending": 0, "succeeded": 0, "failed": 0}
        total = 0
        for r in conn.execute(
            "SELECT status, COUNT(*) n FROM literature_parse_runs GROUP BY status"
        ).fetchall():
            counts[r["status"]] = counts.get(r["status"], 0) + r["n"]
            total += r["n"]
        return {"total": total, **counts}
    finally:
        conn.close()
