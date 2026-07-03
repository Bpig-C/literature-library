"""Inbox 手动摄入 API。薄适配器——零业务逻辑，全委托 scripts.literature_ingest nucleus。

边界：ingest 直接写 works（源可信，不经候选闸门）；dry-run 预览即人工关。
与 collector 摄入（经 ingest_bridge/候选闸门）入口不同、互不混用。
"""
from __future__ import annotations

import os
import shutil

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
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


@router.get("/pipeline/stats")
def pipeline_stats():
    """Pipeline 流程管理页专用：返回各阶段准确的待处理数量。
    
    区分两种状态：
    - "待抽取" = 已解析成功但还没有 extraction 记录的 work
    - "待审核" = 已有 extraction 记录且 review_status='pending'
    """
    conn = get_conn()
    try:
        # 1. 收件箱摄入：_inbox/ 中的 PDF 数
        inbox_dir = LIBRARY_ROOT / '_inbox'
        inbox_count = len(list(inbox_dir.glob('*.pdf'))) if inbox_dir.exists() else 0

        # 2. 文档解析：parse_run 状态
        parse_row = conn.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END), 0) as pending,
                COALESCE(SUM(CASE WHEN status='succeeded' THEN 1 ELSE 0 END), 0) as succeeded,
                COALESCE(SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END), 0) as failed,
                COALESCE(SUM(CASE WHEN status='running' THEN 1 ELSE 0 END), 0) as running
            FROM literature_parse_runs
        """).fetchone()
        
        # 3. 元数据抽取 —— 两类
        meta_pending_review = conn.execute("""
            SELECT COUNT(*) FROM metadata_extractions me
            JOIN works w ON w.id = me.work_id
            WHERE me.review_status = 'pending' AND w.read_status != 'quarantined'
        """).fetchone()[0]

        meta_pending_extract = conn.execute("""
            SELECT COUNT(*) FROM works w
            WHERE EXISTS (SELECT 1 FROM literature_parse_runs pr 
                         WHERE pr.work_id = w.id AND pr.status = 'succeeded')
              AND NOT EXISTS (SELECT 1 FROM metadata_extractions me 
                              WHERE me.work_id = w.id)
              AND w.read_status != 'quarantined'
        """).fetchone()[0]

        # 4. 分类抽取 —— 同样两类
        class_pending_review = conn.execute("""
            SELECT COUNT(*) FROM classification_extractions ce
            JOIN works w ON w.id = ce.work_id
            WHERE ce.review_status = 'pending' AND w.read_status != 'quarantined'
        """).fetchone()[0]

        class_pending_extract = conn.execute("""
            SELECT COUNT(*) FROM works w
            WHERE EXISTS (SELECT 1 FROM literature_parse_runs pr 
                         WHERE pr.work_id = w.id AND pr.status = 'succeeded')
              AND EXISTS (SELECT 1 FROM metadata_extractions me 
                          WHERE me.work_id = w.id AND me.review_status = 'approved')
              AND NOT EXISTS (SELECT 1 FROM classification_extractions ce 
                              WHERE ce.work_id = w.id)
              AND w.read_status != 'quarantined'
        """).fetchone()[0]

        return {
            "inbox": {"count": inbox_count},
            "parse": {
                "pending": parse_row["pending"],
                "running": parse_row["running"] or 0,
                "succeeded": parse_row["succeeded"],
            },
            "metadata": {
                "pending_extract": meta_pending_extract,
                "pending_review": meta_pending_review,
            },
            "classification": {
                "pending_extract": class_pending_extract,
                "pending_review": class_pending_review,
            },
        }
    finally:
        conn.close()


@router.get("/pipeline/pending-metadata")
def pending_metadata_works(per_page: int = 100, page: int = 1):
    """返回待元数据抽取的 works 列表（解析成功但无 metadata_extraction 记录）。
    
    用于 Pipeline 页面「待抽取」标签下的文件列表展示和选择性批量抽取。
    """
    conn = get_conn()
    try:
        offset = (page - 1) * per_page
        rows = conn.execute("""
            SELECT w.id, w.title, w.created_at, pr.status as parse_status
            FROM works w
            INNER JOIN literature_parse_runs pr ON pr.work_id = w.id
            WHERE pr.status = 'succeeded'
              AND NOT EXISTS (
                  SELECT 1 FROM metadata_extractions me WHERE me.work_id = w.id
              )
              AND w.read_status != 'quarantined'
            ORDER BY w.created_at DESC
            LIMIT ? OFFSET ?
        """, (per_page, offset)).fetchall()

        total = conn.execute("""
            SELECT COUNT(*) FROM works w
            WHERE EXISTS (SELECT 1 FROM literature_parse_runs pr 
                         WHERE pr.work_id = w.id AND pr.status = 'succeeded')
              AND NOT EXISTS (SELECT 1 FROM metadata_extractions me 
                              WHERE me.work_id = w.id)
              AND w.read_status != 'quarantined'
        """).fetchone()[0]

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "items": [
                {
                    "work_id": r["id"],
                    "title": r["title"] or "",
                    "created_at": r["created_at"],
                    "parse_status": r["parse_status"],
                }
                for r in rows
            ],
        }
    finally:
        conn.close()


@router.get("/pipeline/pending-classification")
def pending_classification_works(per_page: int = 100, page: int = 1):
    """待分类抽取的 works 列表（元数据已批准但无 classification_extraction 记录）。
    
    用于 Pipeline 页面分类阶段「待抽取」标签下的文件列表。
    """
    conn = get_conn()
    try:
        offset = (page - 1) * per_page
        rows = conn.execute("""
            SELECT w.id, w.title, w.created_at,
                   me.model_name as last_meta_model,
                   me.created_at as meta_created_at
            FROM works w
            INNER JOIN literature_parse_runs pr ON pr.work_id = w.id
            INNER JOIN metadata_extractions me ON me.work_id = w.id
            WHERE pr.status = 'succeeded'
              AND me.review_status = 'approved'
              AND NOT EXISTS (
                  SELECT 1 FROM classification_extractions ce WHERE ce.work_id = w.id
              )
              AND w.read_status != 'quarantined'
            ORDER BY w.created_at DESC
            LIMIT ? OFFSET ?
        """, (per_page, offset)).fetchall()

        total = conn.execute("""
            SELECT COUNT(*) FROM works w
            WHERE EXISTS (SELECT 1 FROM literature_parse_runs pr 
                         WHERE pr.work_id = w.id AND pr.status = 'succeeded')
              AND EXISTS (SELECT 1 FROM metadata_extractions me 
                          WHERE me.work_id = w.id AND me.review_status = 'approved')
              AND NOT EXISTS (SELECT 1 FROM classification_extractions ce 
                              WHERE ce.work_id = w.id)
              AND w.read_status != 'quarantined'
        """).fetchone()[0]

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "items": [
                {
                    "work_id": r["id"],
                    "title": r["title"] or "",
                    "created_at": r["created_at"],
                    "meta_model": r["last_meta_model"] or "",
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

        dest_path = os.path.join(inbox_dir, os.path.basename(upload_file.filename))

        # 写入文件
        try:
            with open(dest_path, 'wb') as f:
                # 分块读取避免大文件内存问题
                while chunk := await upload_file.read(1024 * 64):  # 64KB chunks
                    f.write(chunk)
            saved_paths.append(dest_path)
        except Exception as e:
            skipped.append({'filename': upload_file.filename, 'reason': str(e)})
            if os.path.exists(dest_path):
                os.remove(dest_path)

    if not saved_paths:
        raise HTTPException(400, f'没有有效的文件可上传: {skipped}')

    # 自动执行摄入计划
    try:
        plan = build_ingest_plan(LIBRARY_ROOT, dry_run=True)
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
