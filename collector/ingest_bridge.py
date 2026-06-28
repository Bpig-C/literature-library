# collector/ingest_bridge.py
"""Candidate -> work promotion bridge. REUSES literature_ingest full pipeline.
Collector NEVER writes works directly; it stages the candidate PDF into a temp inbox
and runs build_ingest_plan + execute_plan, then backfills ingested_work_id.
"""
from __future__ import annotations
import shutil
import secrets
from pathlib import Path
from api.db import get_conn
import scripts.literature_ingest as ingest

def promote(candidate_id: str, *, library_root: Path) -> str:
    """Promote an approved candidate. Returns the new work_id."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT local_pdf_path, arxiv_id, title FROM intake_candidates WHERE id=?",
            (candidate_id,)).fetchone()
        if not row:
            raise KeyError(candidate_id)
        local_pdf, arxiv_id, title = row["local_pdf_path"], row["arxiv_id"], row["title"]
        if not local_pdf or not Path(local_pdf).exists():
            raise FileNotFoundError(f"candidate pdf missing: {local_pdf}")
    finally:
        conn.close()

    # 暂存到 library_root 下的临时 inbox，让 ingest 全链路接管
    inbox = Path(library_root) / "_inbox" / f"promote-{candidate_id}-{secrets.token_hex(2)}"
    inbox.mkdir(parents=True, exist_ok=True)
    fname = f"{arxiv_id or candidate_id}.pdf"
    staged = inbox / fname
    shutil.copy2(local_pdf, staged)

    plan = ingest.build_ingest_plan(library_root, inbox_dir=inbox, dry_run=False)
    ingest.execute_plan(plan, no_backup=False, leave_inbox=False)

    work_id = plan.ingests[0].work_id if plan.ingests else None
    if not work_id:
        raise RuntimeError(f"promote produced no work for {candidate_id}")

    conn = get_conn()
    try:
        conn.execute(
            "UPDATE intake_candidates SET status='ingested', ingested_work_id=? WHERE id=?",
            (work_id, candidate_id))
        conn.commit()
    finally:
        conn.close()
    try:
        shutil.rmtree(inbox, ignore_errors=True)
    except Exception:
        pass
    return work_id
