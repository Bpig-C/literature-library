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


class TriggerBody(BaseModel):
    work_ids: list[str] | None = None
    all_pending: bool = False
    backend: str | None = None  # 可选覆盖；v1 不接线（YAGNI），route_and_parse 已做 D13 自动路由


def _load_env_file() -> None:
    """从 LIBRARY_ROOT/.env 读环境变量（已存在则不覆盖）。生产路径用；测试不触达。"""
    env = Path(LIBRARY_ROOT) / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def _run_parse(source_path: str, output_dir, language: str) -> tuple[bool, str, str, str]:
    """单点委托 nucleus：惰性构造 client + 调 route_and_parse。

    生产路径：.env 已载入 → CloudClient/PyMuPDFClient 真构造（此处才触达 fitz/网络）。
    测试通过 patch api.routes.parse._run_parse 替换整段，永不触达 fitz/网络。

    返回 (ok, msg, backend_used, task_id)：task_id 取 cloud 的 last_batch_id
    （cloud vlm 路径有 MinerU batch_id 用于溯源；PyMuPDF 本地路径为空）。
    """
    _load_env_file()
    from core.mineru.cloud_client import CloudClient  # noqa: PLC0415（惰性）
    from core.mineru.pymupdf_client import PyMuPDFClient  # noqa: PLC0415（惰性）
    cloud = CloudClient()
    pymupdf = PyMuPDFClient()
    ok, msg, backend_used = route_and_parse(cloud, pymupdf, source_path, Path(output_dir), language)
    task_id = getattr(cloud, "last_batch_id", "") or ""
    return ok, msg, backend_used, task_id


def _update_run(conn, run: dict, status: str, *, content_md_path: str = "",
                backend: str = "", task_id: str = "", error: str = "") -> None:
    """写 literature_parse_runs 单行 + 同步 works.parse_status（Flag 4：委托既有 helper）。"""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """UPDATE literature_parse_runs
           SET status=?, task_id=?, finished_at=?, error=?,
               content_md_path=?, backend=? WHERE id=?""",
        (status, task_id, now, error, content_md_path, backend, run["run_id"]),
    )
    sync_work_parse_status(conn, run["work_id"])


@router.post("/parse/trigger")
def parse_trigger(body: TriggerBody):
    if not body.work_ids and not body.all_pending:
        raise HTTPException(400, "provide work_ids or set all_pending=true")
    conn = get_conn()
    try:
        pending = list_pending_runs(conn, body.work_ids if body.work_ids else None)
        if not pending:
            raise HTTPException(400, "no pending parse runs for the given selector")
        results, succ, fail = [], 0, 0
        for run in pending:  # 同步串行（与 CLI nucleus 一致）
            try:
                ok, msg, backend_used, task_id = _run_parse(
                    run["source_path"], run["output_dir"], run["language"]
                )
                content_md = str(Path(run["output_dir"]) / "content.md")
                if ok:
                    _update_run(conn, run, "succeeded",
                                content_md_path=content_md, backend=backend_used,
                                task_id=task_id)
                    results.append({"work_id": run["work_id"], "source_file_id": run["source_file_id"],
                                    "status": "succeeded", "backend": backend_used,
                                    "content_md_path": content_md, "error": ""})
                    succ += 1
                else:
                    _update_run(conn, run, "failed", backend=backend_used,
                                task_id=task_id, error=msg)
                    results.append({"work_id": run["work_id"], "source_file_id": run["source_file_id"],
                                    "status": "failed", "backend": backend_used,
                                    "content_md_path": "", "error": msg})
                    fail += 1
            except Exception as e:  # noqa: BLE001 — 批次不中断
                _update_run(conn, run, "failed", error=str(e))
                results.append({"work_id": run["work_id"], "source_file_id": run["source_file_id"],
                                "status": "failed", "backend": "", "content_md_path": "",
                                "error": str(e)})
                fail += 1
        # 单次事务提交（区别于 CLI 的逐条提交）：API 触发为交互式小批量，
        # 失败由客户端重试 + list_pending_runs 只返回 pending 行兜底，无需逐条落盘。
        conn.commit()
        return {"triggered": len(results), "succeeded": succ, "failed": fail, "results": results}
    finally:
        conn.close()
