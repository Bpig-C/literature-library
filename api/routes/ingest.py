"""Inbox 手动摄入 API。薄适配器——零业务逻辑，全委托 scripts.literature_ingest nucleus。

边界：ingest 直接写 works（源可信，不经候选闸门）；dry-run 预览即人工关。
与 collector 摄入（经 ingest_bridge/候选闸门）入口不同、互不混用。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import LIBRARY_ROOT

from scripts.literature_ingest import build_ingest_plan, execute_plan

router = APIRouter()


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
