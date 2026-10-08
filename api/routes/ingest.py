"""Inbox 手动摄入 API。薄适配器——零业务逻辑，全委托 scripts.literature_ingest nucleus。

边界：ingest 直接写 works（源可信，不经候选闸门）；dry-run 预览即人工关。
与 collector 摄入（经 ingest_bridge/候选闸门）入口不同、互不混用。
"""
from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel

from ..db import LIBRARY_ROOT, get_conn

from scripts.literature_ingest import build_ingest_plan, execute_plan

router = APIRouter()

# 允许上传的文件类型
ALLOWED_EXTENSIONS = {'.pdf', '.PDF'}
MAX_FILE_SIZE = 200 * 1024 * 1024  # 200MB


def _is_allowed(filename: str) -> bool:
    """检查文件扩展名是否允许"""
    ext = os.path.splitext(filename)[1]
    return ext in ALLOWED_EXTENSIONS


async def _save_upload(upload_file: UploadFile, inbox_dir: str) -> str:
    """Publish complete uploads exclusively; cleanup owns only staging.

    Hard-link creation is atomic and cannot replace an existing destination,
    including across processes. Non-PDF staging is invisible to PDF scanning.
    Unsupported publication fails safely, without an overwrite fallback.
    """
    filename = os.path.basename(upload_file.filename)
    fd, staging = tempfile.mkstemp(prefix='.upload-', suffix='.part', dir=inbox_dir)
    try:
        with os.fdopen(fd, 'wb') as stream:
            while chunk := await upload_file.read(1024 * 64):
                stream.write(chunk)
        destination = os.path.join(inbox_dir, filename)
        while True:
            try:
                os.link(staging, destination)
                return destination
            except FileExistsError:
                name = Path(filename)
                destination = os.path.join(inbox_dir, f'{name.stem}__{uuid.uuid4().hex}{name.suffix}')
    finally:
        os.unlink(staging)


def _research_staging_snapshot() -> dict:
    """Research-store staging view for the pipeline page (read-only).

    Returns which parsed works already entered the research store
    (``research_sources``) and which are still waiting, plus a compact batch
    status summary.  An absent/unreadable research store is reported as such —
    never faked with legacy numbers.
    """
    from contextlib import closing

    from ..research_context import get_research_context
    ctx = get_research_context()
    # staged_works=None 表示"研究库不可读"（未知），前端不得显示为 0
    snapshot = {"available": False, "parsed_not_staged": 0, "staged_works": None,
                "batches": []}
    conn = get_conn()
    try:
        parsed_ids = [r["id"] for r in conn.execute(
            """SELECT DISTINCT w.id FROM works w
               WHERE EXISTS (SELECT 1 FROM literature_parse_runs pr
                             WHERE pr.work_id = w.id AND pr.status = 'succeeded')
                 AND w.read_status != 'quarantined'""")]
    finally:
        conn.close()
    if not ctx.db_path.is_file():
        snapshot["parsed_not_staged"] = len(parsed_ids)
        snapshot["error"] = "研究库未配置：无法判断材料是否已进入研究流程"
        return snapshot
    try:
        with closing(ctx.connect(read_only=True)) as rconn:
            tables = {r[0] for r in rconn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "research_sources" not in tables:
                snapshot["parsed_not_staged"] = len(parsed_ids)
                snapshot["error"] = "研究库缺少 research_sources 表"
                return snapshot
            staged = {r["work_id"] for r in rconn.execute(
                "SELECT DISTINCT work_id FROM research_sources")}
            snapshot["available"] = True
            snapshot["staged_works"] = len({w for w in parsed_ids if w in staged})
            snapshot["parsed_not_staged"] = len([w for w in parsed_ids if w not in staged])
            if "research_batches" in tables:
                for row in rconn.execute(
                    "SELECT id, name, status FROM research_batches "
                    "ORDER BY created_at DESC LIMIT 8"):
                    snapshot["batches"].append(dict(row))
    except Exception as error:  # noqa: BLE001 — surfaced, not faked
        snapshot["parsed_not_staged"] = len(parsed_ids)
        snapshot["error"] = f"研究库读取失败：{error}"
    return snapshot


@router.get("/pipeline/stats")
def pipeline_stats():
    """Pipeline 流程管理页专用：返回各阶段真实的待处理数量。

    LL-DECOUPLE-20260920：旧元数据/旧分类"待抽取/待审核"口径退役。
    当前流程 = 摄入 → 解析 → 进入研究批次（v5 元数据/原文/解释与分类、
    独立核查、人的反馈采纳）→ 书目投影/导出。统计只报告这些真实状态：
    - inbox: _inbox/ 待摄入 PDF
    - parse: 解析运行状态
    - intake: 采集候选待审
    - research: 解析成功后是否已进入研究库（staged / parsed_not_staged）
    - projection: 当前书目投影（可导出门槛）计数
    """
    conn = get_conn()
    try:
        # 1. 收件箱摄入：_inbox/ 中的 PDF 数（递归，与 scripts/literature_ingest.py 的扫描口径一致）
        inbox_dir = LIBRARY_ROOT / '_inbox'
        inbox_count = len([p for p in inbox_dir.rglob('*.pdf') if p.is_file()]) if inbox_dir.exists() else 0

        # 2. 文档解析：parse_run 状态
        parse_row = conn.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END), 0) as pending,
                COALESCE(SUM(CASE WHEN status='succeeded' THEN 1 ELSE 0 END), 0) as succeeded,
                COALESCE(SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END), 0) as failed,
                COALESCE(SUM(CASE WHEN status='running' THEN 1 ELSE 0 END), 0) as running
            FROM literature_parse_runs
        """).fetchone()

        # 3. 采集候选待审：等待人工审核的 intake 候选（approved 未晋升的不计入）
        intake_pending = conn.execute("""
            SELECT COUNT(*) FROM intake_candidates
            WHERE review_status = 'pending' AND status != 'ingested'
        """).fetchone()[0]

        # 4. 书目投影：可导出门槛计数（v5 传播 / legacy 迁移 / 目录人工修订）
        from .. import bibliographic_projection as projection
        projection_counts = projection.projection_stats(conn)
    finally:
        conn.close()

    research = _research_staging_snapshot()

    return {
        "inbox": {"count": inbox_count},
        "parse": {
            "pending": parse_row["pending"],
            "running": parse_row["running"] or 0,
            "succeeded": parse_row["succeeded"],
        },
        "intake": {"pending": intake_pending},
        "research": research,
        "projection": projection_counts,
    }


_LEGACY_STAGE_RETIRED = {
    "detail": ("旧元数据/旧分类抽取阶段已退役（LL-DECOUPLE-20260920）。"
               "解析成功的材料经 /api/pipeline/unstaged-works 进入研究批次，"
               "由 v5 流程产出元数据、原文记录与解释分类。"),
}


@router.get("/pipeline/pending-metadata", deprecated=True)
def pending_metadata_works(per_page: int = 100, page: int = 1):
    """已退役的旧"待元数据抽取"列表。保留路径返回明确的退役说明。"""
    from fastapi import HTTPException
    raise HTTPException(status_code=410, detail=_LEGACY_STAGE_RETIRED["detail"])


@router.get("/pipeline/pending-classification", deprecated=True)
def pending_classification_works(per_page: int = 100, page: int = 1):
    """已退役的旧"待分类抽取"列表。保留路径返回明确的退役说明。"""
    from fastapi import HTTPException
    raise HTTPException(status_code=410, detail=_LEGACY_STAGE_RETIRED["detail"])


@router.get("/pipeline/unstaged-works")
def unstaged_works(per_page: int = Query(100, ge=1, le=200), page: int = Query(1, ge=1)):
    """解析成功但尚未进入研究库的 works 列表（新材料接力入口数据源）。

    这取代了旧的 pending-metadata / pending-classification 列表：不需要
    任何旧抽取记录，解析成功即可进入所选研究批次（v5 Agent 流程）。
    """
    from contextlib import closing

    from ..research_context import get_research_context
    conn = get_conn()
    try:
        ctx = get_research_context()
        staged: set[str] = set()
        research_available = False
        research_note = None
        if ctx.db_path.is_file():
            try:
                with closing(ctx.connect(read_only=True)) as rconn:
                    tables = {r[0] for r in rconn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'")}
                    if "research_sources" in tables:
                        staged = {r["work_id"] for r in rconn.execute(
                            "SELECT DISTINCT work_id FROM research_sources")}
                        research_available = True
                    else:
                        research_note = "研究库缺少 research_sources 表，无法判断是否已进入"
            except Exception as error:  # noqa: BLE001
                research_note = f"研究库读取失败：{error}"
        else:
            research_note = "研究库未配置"

        where = ""
        params: list = []
        if staged:
            placeholders = ",".join("?" * len(staged))
            where = f" WHERE w.id NOT IN ({placeholders})"
            params = sorted(staged)
        offset = (page - 1) * per_page
        rows = conn.execute(
            f"""SELECT w.id, w.title, w.created_at,
                   (SELECT pr.status FROM literature_parse_runs pr
                    WHERE pr.work_id = w.id AND pr.status = 'succeeded'
                    ORDER BY pr.finished_at DESC LIMIT 1) AS parse_status
                FROM works w{where}
                {' AND' if where else ' WHERE'} EXISTS (
                    SELECT 1 FROM literature_parse_runs pr
                    WHERE pr.work_id = w.id AND pr.status = 'succeeded')
                  AND w.read_status != 'quarantined'
                ORDER BY w.created_at DESC
                LIMIT ? OFFSET ?""",
            params + [per_page, offset]).fetchall()
        total = conn.execute(
            f"""SELECT COUNT(*) FROM works w{where}
                {' AND' if where else ' WHERE'} EXISTS (
                    SELECT 1 FROM literature_parse_runs pr
                    WHERE pr.work_id = w.id AND pr.status = 'succeeded')
                  AND w.read_status != 'quarantined'""",
            params).fetchone()[0]

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "research_available": research_available,
            "research_note": research_note,
            "items": [
                {
                    "work_id": r["id"],
                    "title": r["title"] or "",
                    "created_at": r["created_at"],
                    "parse_status": r["parse_status"] or "succeeded",
                }
                for r in rows
            ],
        }
    finally:
        conn.close()


@router.post("/ingest/upload")
async def ingest_upload(files: list[UploadFile] = File(...)):
    """接收前端上传的 PDF 文件，保存到 _inbox/ 并自动执行摄入。

    流程：接收 multipart 文件 → 保存到 _inbox/ → 调用 execute_plan 完成摄入
    返回：{ ok: true, uploaded: N, ingested: M, summary: {...} }
    """
    inbox_dir = os.path.join(LIBRARY_ROOT, '_inbox')
    os.makedirs(inbox_dir, exist_ok=True)

    saved_paths = []
    skipped = []

    for upload_file in files:
        # 校验文件类型
        if not _is_allowed(upload_file.filename or ''):
            skipped.append({'filename': upload_file.filename, 'reason': '不支持的文件格式（仅支持 PDF）'})
            continue

        # 写入文件
        try:
            dest_path = await _save_upload(upload_file, inbox_dir)
            saved_paths.append(dest_path)
        except Exception as e:
            skipped.append({'filename': upload_file.filename, 'reason': str(e)})

    if not saved_paths:
        raise HTTPException(400, f'没有有效的文件可上传: {skipped}')

    # 自动执行摄入计划
    try:
        plan = build_ingest_plan(LIBRARY_ROOT, dry_run=True, selected_paths=[Path(path) for path in saved_paths])
        if plan.summary()['ingests'] == 0:
            return {
                'ok': True,
                'uploaded': len(saved_paths),
                'ingested': 0,
                'skipped': skipped,
                'message': f'已上传 {len(saved_paths)} 个文件到 _inbox/，但无新文件需要摄入',
                'summary': plan.summary(),
            }
        backup_dir = execute_plan(plan, no_backup=True, leave_inbox=False)
        summary = plan.summary()
        return {
            'ok': True,
            'uploaded': len(saved_paths),
            'ingested': summary['ingests'],
            'skipped': skipped,
            'summary': summary,
        }
    except Exception as e:
        raise HTTPException(500, f'文件已上传但摄入失败: {str(e)}')


@router.get("/ingest/plan")
def ingest_plan(limit: int | None = None):
    """dry-run：扫 _inbox/ 预览摄入计划，不写盘。"""
    plan = build_ingest_plan(LIBRARY_ROOT, limit=limit, dry_run=True)
    d = plan.as_dict()
    return {"dry_run": True, "summary": d["summary"], "ingests": d["ingests"],
            "exact_duplicates": d["exact_duplicates"], "skipped": d["skipped"],
            "warnings": d["warnings"]}


class ExecuteBody(BaseModel):
    leave_inbox: bool = False  # True=保留 inbox 原文件；默认移走到 _archive/ingested_inbox/


@router.post("/ingest/execute")
def ingest_execute(body: ExecuteBody):
    """执行摄入：_inbox/ → works/{id}/source/，直写 works + 建 parse_runs pending 行。
    执行前先 dry-run 取计划（无新文件则 400）。"""
    plan = build_ingest_plan(LIBRARY_ROOT, dry_run=True)
    if plan.summary()["ingests"] == 0:
        raise HTTPException(400, "no new files in _inbox/ to ingest")
    backup_dir = execute_plan(plan, no_backup=True, leave_inbox=body.leave_inbox)
    s = plan.summary()
    return {"ok": True, "summary": s, "backup_dir": str(backup_dir) if backup_dir else None}
