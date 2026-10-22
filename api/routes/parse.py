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

from ..db import CODE_ROOT, get_conn, LIBRARY_ROOT

# 让 parser 子项目（core.mineru.*）可导入。与 scripts/ 约定一致。
_PARSER_ROOT = CODE_ROOT / "parser"
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


def list_runs_for_reparse(conn, work_ids: list[str]) -> list[dict]:
    """force 重解析：取指定 work 的 parse_run（**不限状态**），供强制重解析。"""
    if not work_ids:
        return []
    rows = conn.execute(
        """SELECT pr.id, pr.work_id, pr.source_file_id, pr.source_path, pr.output_dir,
                  w.language AS language
           FROM literature_parse_runs pr
           LEFT JOIN works w ON w.id = pr.work_id
           WHERE pr.work_id IN ({})
           ORDER BY pr.id""".format(",".join("?" * len(work_ids))),
        work_ids,
    ).fetchall()
    return [_row_to_pending(dict(r)) for r in rows]


@router.get("/parse/status")
def parse_status(work_id: str | None = None):
    conn = get_conn()
    try:
        if work_id:
            row = conn.execute(
                """SELECT pr.work_id, pr.status, pr.content_md_path, pr.backend,
                          pr.error, pr.finished_at, pr.id AS parse_run_id
                   FROM literature_parse_runs pr
                   WHERE pr.work_id=?
                   ORDER BY CASE WHEN pr.status='succeeded' THEN 0 ELSE 1 END,
                            pr.finished_at DESC, pr.id DESC
                   LIMIT 1""",
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
    work_ids: list[str] | None = None  # select all sources of these works
    source_file_ids: list[str] | None = None  # S2: select exact source files (SF-… IDs)
    all_pending: bool = False
    backend: str | None = None  # auto/pymupdf/vlm；None=默认双路合并（vlm优先+合并，失败回退pymupdf）
    force: bool = False  # True=对指定 work 的已 succeeded/failed run 强制重解析（需 work_ids）


_BACKEND_CHOICES = {"auto", "pymupdf", "vlm"}


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


def _run_parse(source_path: str, output_dir, language: str,
               backend: str | None = None) -> tuple[bool, str, str, str]:
    """单点委托 nucleus：惰性构造 client + 调 route_and_parse。

    生产路径：.env 已载入 → CloudClient/PyMuPDFClient 真构造（此处才触达 fitz/网络）。
    测试通过 patch api.routes.parse._run_parse 替换整段，永不触达 fitz/网络。

    backend: None/"auto" → D13 自动路由；"pymupdf"/"vlm" → 强制后端（不回退）。
    返回 (ok, msg, backend_used, task_id)：task_id 取 cloud 的 last_batch_id
    （cloud vlm 路径有 MinerU batch_id 用于溯源；PyMuPDF 本地路径为空）。
    """
    _load_env_file()
    from core.mineru.cloud_client import CloudClient  # noqa: PLC0415（惰性）
    from core.mineru.pymupdf_client import PyMuPDFClient  # noqa: PLC0415（惰性）
    cloud = CloudClient()
    from ..producer_events import emit
    cloud.on_progress = emit
    pymupdf = PyMuPDFClient()
    ok, msg, backend_used = route_and_parse(cloud, pymupdf, source_path, Path(output_dir),
                                            language, backend=backend)
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


@router.get("/parse/jobs")
def parse_jobs(work_id: str | None = None, source_file_id: str | None = None,
               job_id: str | None = None, limit: int = 50):
    """S3: query producer parse jobs and their durable operation states.

    Returns job_id, source_file_id, work_id, parse_run_id, version, state
    (preparing/artifacts_ready/registered/failed), backend, error_code, and
    the associated storage_operations state when a binding was registered.
    """
    from ..db import get_read_conn as _get_lib_conn
    conn = _get_lib_conn()
    try:
        where, params = ["1=1"], []
        if job_id:
            where.append("j.id=?"); params.append(job_id)
        if source_file_id:
            where.append("j.source_file_id=?"); params.append(source_file_id)
        if work_id:
            where.append("pr.work_id=?"); params.append(work_id)
        rows = conn.execute(
            f"""SELECT j.id AS job_id, j.kind, j.source_file_id, j.parse_run_id,
                       j.version, j.state, j.backend, j.task_id, j.error_code,
                       pr.work_id, pr.status AS parse_status, pr.output_dir
                FROM storage_producer_jobs j
                LEFT JOIN literature_parse_runs pr ON pr.id = j.parse_run_id
                WHERE {' AND '.join(where)}
                ORDER BY j.rowid DESC
                LIMIT ?""",
            [*params, min(limit, 200)],
        ).fetchall()
        jobs = []
        for r in rows:
            d = dict(r)
            from ..producer_events import read as read_diagnostics
            d['diagnostics'] = read_diagnostics(conn, d['job_id'])
            from ..producer_recovery import read as read_recovery
            d['recovery'] = read_recovery(conn, d['job_id'])
            d.pop('output_dir', None)
            # look up durable operation state for the binding if registered
            if d.get("parse_run_id"):
                op = conn.execute(
                    """SELECT state, error_code FROM storage_operations
                       WHERE request LIKE ? ORDER BY rowid DESC LIMIT 1""",
                    (f'%{d["parse_run_id"]}%',),
                ).fetchone()
                if op:
                    d["operation_state"] = op["state"]
                    d["operation_error"] = op["error_code"]
            jobs.append(d)
        return {"jobs": jobs, "count": len(jobs)}
    finally:
        conn.close()


class ResumeBody(BaseModel):
    job_id: str  # the parse producer job to resume (state=artifacts_ready)
    force: bool = False  # must be true to signal explicit operator intent


def _recover_parse(source_path, output_dir, task_id):
    _load_env_file()
    from core.mineru.cloud_client import CloudClient
    from core.mineru.base_client import ParseRequest
    from core.mineru.router import _maybe_build_detail_assets
    from ..producer_events import emit
    cloud=CloudClient();cloud.on_progress=emit
    ok,msg=cloud.recover_pdf(ParseRequest(pdf_path=Path(source_path),output_dir=Path(output_dir)),task_id)
    if ok:_maybe_build_detail_assets(Path(source_path),Path(output_dir))
    return ok,msg,'vlm',task_id


@router.post('/parse/recover')
def parse_recover(body: ResumeBody):
    from ..storage.producers import recover_cloud_producer
    from ..storage.runtime import enabled
    from ..storage.core import StorageError
    if not body.force: raise HTTPException(400,'recover requires force=true (query existing cloud task only)')
    if not enabled(): raise HTTPException(400,'immutable storage required')
    try:job=recover_cloud_producer(body.job_id,_recover_parse)
    except StorageError as error:
        raise HTTPException(409 if error.code in ('producer_incomplete','revision_conflict') else 422, error.code)
    return {'job_id':job['id'],'state':job['state'],'parse_run_id':job['parse_run_id'],'task_id':job['task_id'],'version':job['version']}


@router.post("/parse/resume")
def parse_resume(body: ResumeBody):
    """S3: finish an artifacts_ready job that already has durable local output.

    The internal pipeline (producers._finish) resumes any interrupted
    storage_operations by the same operation ID; failed jobs with incomplete
    output are refused. This does not create a new parse version.
    """
    if not body.force:
        raise HTTPException(400, "resume requires force=true (explicit operator intent)")
    from ..storage.producers import resume_producer
    from ..storage.runtime import enabled
    from ..storage.core import StorageError
    if not enabled():
        raise HTTPException(400, "resume requires the immutable storage service")
    try:
        job = resume_producer(body.job_id)
    except StorageError as e:
        raise HTTPException(409 if e.code in {"producer_incomplete", "revision_conflict"} else 422,
                            f"{e.code}: {e}")
    return {"job_id": body.job_id, "state": job["state"],
            "parse_run_id": job.get("parse_run_id"), "version": job.get("version"),
            "backend": job.get("backend") or ""}


@router.post("/parse/trigger")
def parse_trigger(body: TriggerBody):
    if not body.work_ids and not body.source_file_ids and not body.all_pending:
        raise HTTPException(400, "provide work_ids, source_file_ids, or set all_pending=true")
    if body.backend and body.backend not in _BACKEND_CHOICES:
        raise HTTPException(400, f"backend must be one of {sorted(_BACKEND_CHOICES)}")
    if body.force and not (body.work_ids or body.source_file_ids):
        raise HTTPException(400, "force re-parse requires explicit work_ids or source_file_ids")
    from ..storage.runtime import enabled
    if enabled():
        from ..storage.producers import trigger_production
        return trigger_production(body,_run_parse)
    conn = get_conn()
    try:
        if body.force:
            pending = list_runs_for_reparse(conn, body.work_ids or [])
        else:
            pending = list_pending_runs(conn, body.work_ids if body.work_ids else None)
        if not pending:
            raise HTTPException(400, "no parse runs for the given selector")
        results, succ, fail = [], 0, 0
        for run in pending:  # 同步串行（与 CLI nucleus 一致）
            try:
                ok, msg, backend_used, task_id = _run_parse(
                    run["source_path"], run["output_dir"], run["language"],
                    backend=body.backend or None,
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
