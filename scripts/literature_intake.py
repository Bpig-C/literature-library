# scripts/literature_intake.py
"""collector intake CLI (foundation: list / promote).
Retrieval layer will EXTEND this file with topic/collect/resolve.
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.db import get_conn

def list_cmd(args):
    """列出待晋升候选（resolution=new, review_status=pending）。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT id, title, arxiv_id FROM intake_candidates
               WHERE resolution='new' AND review_status='pending'""").fetchall()
    finally:
        conn.close()
    for r in rows:
        print(f"{r['id']}\t{r['arxiv_id'] or ''}\t{r['title'] or ''}")

def promote_review(*, approve=None, reject=None):
    """A2 审核：批量 approve/reject 候选。"""
    conn = get_conn()
    try:
        for cid in (approve or []):
            conn.execute("UPDATE intake_candidates SET review_status='approved' WHERE id=?", (cid,))
        for cid in (reject or []):
            conn.execute("UPDATE intake_candidates SET review_status='rejected' WHERE id=?", (cid,))
        conn.commit()
    finally:
        conn.close()

def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p = sub.add_parser("promote")
    p.add_argument("--approve", help="comma-separated IC ids")
    p.add_argument("--reject", help="comma-separated IC ids")
    args = ap.parse_args(argv)
    if args.cmd == "list":
        list_cmd(args)
    elif args.cmd == "promote":
        promote_review(approve=args.approve.split(",") if args.approve else None,
                       reject=args.reject.split(",") if args.reject else None)

if __name__ == "__main__":
    main()
