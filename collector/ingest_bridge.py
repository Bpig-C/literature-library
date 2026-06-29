# collector/ingest_bridge.py
"""Candidate -> work promotion bridge. REUSES literature_ingest full pipeline.
Collector NEVER writes works directly; it stages the candidate PDF into a temp inbox
and runs build_ingest_plan + execute_plan, then backfills ingested_work_id.

晋升时若候选所属主题配置了 mapped_tags，把这些标签作为「建议标签」
写入 classification_extractions（source=collector, pending, applied=0）。
这只是建议，不绕过分类审核门禁——人审仍需决定是否应用。
"""
from __future__ import annotations
import json
import shutil
import secrets
from pathlib import Path
from api.db import get_conn
from collector.paths import resolve_pdf_path     # local_pdf_path 可能相对 library root（heavy_gate 现在这么写）
import scripts.literature_ingest as ingest


def _do_ingest(candidate_id: str, library_root: Path) -> str:
    """地基晋升逻辑：暂存候选 PDF 到临时 inbox，跑 ingest 全链路，清理 inbox。
    返回新 work_id。不更新候选状态——那是 promote 的职责。

    （原 promote 的 read+stage+build_ingest_plan+execute_plan+cleanup 逻辑原样保留。）
    """
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
    ingest.execute_plan(plan, no_backup=False, leave_inbox=False)

    work_id = plan.ingests[0].work_id if plan.ingests else None
    if not work_id:
        raise RuntimeError(f"promote produced no work for {candidate_id}")

    try:
        shutil.rmtree(inbox, ignore_errors=True)
    except Exception:
        pass
    return work_id


def _write_suggested_tags(conn, work_id: str, topic_id: str) -> None:
    """把主题的 mapped_tags 作为建议标签写入 classification_extractions。

    边界：只记录建议（review_status=pending, applied=0），不绕过分类审核门禁。
    使用真实表的列：model_name 记来源标识 'collector'，extracted_json 装 suggested_tags。
    """
    row = conn.execute(
        "SELECT mapped_tags FROM collection_topics WHERE id=?", (topic_id,)).fetchone()
    if not row or not row[0]:
        return
    try:
        tags = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return
    if not isinstance(tags, list):
        return
    if not tags:
        return

    eid = "CE-" + secrets.token_hex(6)
    now = ingest.utc_now()
    conn.execute(
        """INSERT INTO classification_extractions
           (id, work_id, model_name, prompt_version, extracted_json,
            review_status, applied, created_at, updated_at)
           VALUES (?, ?, 'collector', NULL, ?, 'pending', 0, ?, ?)""",
        (eid, work_id, json.dumps({"suggested_tags": tags}, ensure_ascii=False), now, now))


def promote(candidate_id: str, *, library_root: Path) -> str:
    """晋升候选；若其主题有 mapped_tags，作为建议标签落 classification_extractions(人审)。
    建议标签写入是 best-effort：绝不阻断晋升。"""
    work_id = _do_ingest(candidate_id, library_root)
    conn = get_conn()
    try:
        # 主效果先落：候选翻 ingested
        conn.execute(
            "UPDATE intake_candidates SET status='ingested', ingested_work_id=? WHERE id=?",
            (work_id, candidate_id))
        conn.commit()
        # 次要效果：建议标签 best-effort，失败不影响晋升
        try:
            topic_row = conn.execute(
                "SELECT collection_topic_id FROM intake_candidates WHERE id=?",
                (candidate_id,)).fetchone()
            if topic_row and topic_row[0]:
                _write_suggested_tags(conn, work_id, topic_row[0])
                conn.commit()
        except Exception:
            pass   # 建议标签写入失败：吞掉，晋升已完成
    finally:
        conn.close()
    return work_id
