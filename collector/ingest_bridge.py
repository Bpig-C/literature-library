# collector/ingest_bridge.py
"""Candidate -> work promotion bridge. REUSES literature_ingest full pipeline.
Collector NEVER writes works directly; it stages the candidate PDF into a temp inbox
and runs build_ingest_plan + execute_plan, then backfills ingested_work_id.

LL-DECOUPLE-20260920：晋升不再写旧分类建议标签
（旧分类流程退役）。主题的 mapped_tags 保留在 collection_topics 配置中，
后续如需复用走 v5 研究流程的候选建议，不写旧表。
"""
from __future__ import annotations
import shutil
import secrets
from pathlib import Path
from api.db import get_conn
from collector.paths import resolve_pdf_path     # local_pdf_path 可能相对 library root（heavy_gate 现在这么写）
import scripts.literature_ingest as ingest


def _do_ingest(candidate_id: str, library_root: Path, purpose: str, request_id: str) -> str:
    """地基晋升逻辑：暂存候选 PDF 到临时 inbox，跑 ingest 全链路，清理 inbox。
    返回新 work_id。不更新候选状态——那是 promote 的职责。

    （原 promote 的 read+stage+build_ingest_plan+execute_plan+cleanup 逻辑原样保留。）
    """
    purpose = ingest.validate_purpose(purpose)
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT local_pdf_path, arxiv_id, title FROM intake_candidates WHERE id=?",
            (candidate_id,)).fetchone()
        if not row:
            raise KeyError(candidate_id)
        local_pdf, arxiv_id, title = row["local_pdf_path"], row["arxiv_id"], row["title"]
        if not local_pdf:
            raise FileNotFoundError(f"candidate pdf missing: {local_pdf}")
        try:
            resolved_pdf = resolve_pdf_path(local_pdf)
        except ValueError as e:
            raise FileNotFoundError(f"candidate pdf path rejected: {e}") from e
        if not resolved_pdf.exists():
            raise FileNotFoundError(f"candidate pdf missing: {local_pdf}")
    finally:
        conn.close()

    # 暂存到 library_root 下的临时 inbox，让 ingest 全链路接管
    inbox = Path(library_root) / "_inbox" / f"promote-{candidate_id}-{secrets.token_hex(2)}"
    inbox.mkdir(parents=True, exist_ok=True)
    fname = f"{arxiv_id or candidate_id}.pdf"
    staged = inbox / fname
    shutil.copy2(resolved_pdf, staged)

    plan = ingest.build_ingest_plan(library_root, inbox_dir=inbox, dry_run=False)
    ingest.execute_plan(plan, purpose=purpose, request_id=request_id, no_backup=False, leave_inbox=False)

    work_id = plan.ingests[0].work_id if plan.ingests else next((d.existing_work_id for d in plan.exact_duplicates if d.existing_work_id),None)
    if not work_id:
        raise RuntimeError(f"promote produced no work for {candidate_id}")

    try:
        shutil.rmtree(inbox, ignore_errors=True)
    except Exception:
        pass
    return work_id


def promote(candidate_id: str, *, library_root: Path, purpose: str, request_id: str = '') -> str:
    """晋升候选为正式 work（ingest 全链路 + 候选状态回填）。

    LL-DECOUPLE-20260920：不再写旧分类建议标签；解析成功后的材料经
    Pipeline/Works 的"进入研究流程"入口交给 v5 Agent 流程。
    """
    work_id = _do_ingest(candidate_id, library_root, purpose, request_id)
    conn = get_conn()
    try:
        # 主效果先落：候选翻 ingested。review_status 表示人工审核结论，
        # 晋升生命周期由 status/ingested_work_id 表示，避免混用语义。
        conn.execute(
            "UPDATE intake_candidates SET status='ingested', ingested_work_id=? WHERE id=?",
            (work_id, candidate_id))
        conn.commit()
    finally:
        conn.close()
    return work_id
