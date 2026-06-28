# scripts/literature_intake.py
"""collector intake CLI (foundation: list / promote).
Retrieval layer will EXTEND this file with topic/collect/resolve.
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.db import get_conn
from collector import candidate_store
from collector import topics
# collect 编排已提取为 collector.collect.collect_once（§2 单核）；
# heavy_gate/resolve_pending 仍由本模块的 resolve 路径直接用。
from collector.gate import heavy_gate, resolve_pending

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
    """A2 审核：批量 approve/reject 候选（委托 candidate_store 单一 nucleus）。"""
    for cid in (approve or []):
        candidate_store.set_review_status(cid, "approved")
    for cid in (reject or []):
        candidate_store.set_review_status(cid, "rejected")


def collect(args):
    """跑发现 + 轻量闸门，不下载（委托 collector.collect.collect_once 单一 nucleus）。

    若中途 fetch_metadata 网络失败，已写入的候选保持 resolution=pending，需重跑 collect 补闸门。
    """
    from collector.collect import collect_once
    topic_id = getattr(args, "topic", None)
    if topic_id:
        if topics.get(topic_id) is None:
            print(f"error: unknown topic {topic_id}", file=sys.stderr)
            sys.exit(1)
    ids = ([s.strip() for s in args.ids.split(",") if s.strip()]
           if getattr(args, "ids", None) else None)
    gh = ([s.strip() for s in args.github.split(",") if s.strip()]
          if getattr(args, "github", None) else None)
    result = collect_once(topic_id=topic_id, explicit_ids=ids, github_urls=gh)
    print(f"collected {result['created']} candidates")
    if getattr(args, "auto_resolve", False):
        resolve()


def resolve_one(cid):
    """下载 + SHA256 重量闸门（heavy_gate 自管连接）。"""
    return heavy_gate(cid)   # 注意：heavy_gate(cid) 无 conn 参数


def resolve(args=None):
    """默认只对 resolution in {new, needs_better_copy} 的候选下载+SHA256（委托 gate.resolve_pending）。"""
    results = resolve_pending()
    print(f"resolved {len(results)} candidates")


def topic(args):
    if args.action == "add":
        t = topics.create(
            name=args.name, description=args.description or "",
            seed_paper_ids=[s.strip() for s in args.seeds.split(",")] if args.seeds else None,
            explicit_ids=[s.strip() for s in args.explicit_ids.split(",")] if getattr(args, "explicit_ids", None) else None,
            axis_hint=args.axis, map_status=args.map_status or "seedling")
        print(t["id"])
    elif args.action == "list":
        for t in topics.list_topics(map_status=args.map_status):
            print(f"{t['id']}\t{t['map_status']}\t{t['lifecycle']}\t{t['name']}")
    elif args.action == "propose":
        topics.transition(args.id, to_map_status="proposed", proposed_note=args.note or "")
        print("proposed")

def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p = sub.add_parser("promote")
    p.add_argument("--approve", help="comma-separated IC ids")
    p.add_argument("--reject", help="comma-separated IC ids")
    # 新增：topic / collect / resolve
    t = sub.add_parser("topic")
    t.add_argument("action", choices=["add", "list", "propose"])
    t.add_argument("--name"); t.add_argument("--description"); t.add_argument("--seeds")
    t.add_argument("--axis"); t.add_argument("--map-status"); t.add_argument("--id"); t.add_argument("--note")
    t.add_argument("--explicit-ids")
    c = sub.add_parser("collect")
    c.add_argument("--topic"); c.add_argument("--ids"); c.add_argument("--github")
    c.add_argument("--auto-resolve", action="store_true")
    sub.add_parser("resolve")
    args = ap.parse_args(argv)
    if args.cmd == "list":
        list_cmd(args)
    elif args.cmd == "promote":
        promote_review(approve=args.approve.split(",") if args.approve else None,
                       reject=args.reject.split(",") if args.reject else None)
    elif args.cmd == "topic":
        topic(args)
    elif args.cmd == "collect":
        collect(args)
    elif args.cmd == "resolve":
        resolve(args)

if __name__ == "__main__":
    main()
