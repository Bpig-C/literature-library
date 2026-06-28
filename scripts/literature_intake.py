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
from collector.discovery_explicit import collect_explicit
from collector.discovery_citation import collect_from_seeds
from collector.adapters.github import collect_repo_paper
from collector.gate import light_gate, heavy_gate

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
    """跑发现 + 轻量闸门，不下载。

    若中途 fetch_metadata 网络失败，已写入的候选保持 resolution=pending，需重跑 collect 补闸门。
    """
    created = []
    if getattr(args, "topic", None):
        t = topics.get(args.topic)
        if t is None:
            print(f"error: unknown topic {args.topic}", file=sys.stderr)
            sys.exit(1)
        qd = t["query_def"]
        if qd.get("explicit_ids"):
            created += collect_explicit(qd["explicit_ids"], collection_topic_id=args.topic)
        if qd.get("seed_paper_ids"):
            created += collect_from_seeds(qd["seed_paper_ids"], source_type="arxiv",
                                          collection_topic_id=args.topic)
    if getattr(args, "ids", None):
        created += collect_explicit([s.strip() for s in args.ids.split(",") if s.strip()],
                                    source_type="arxiv")
    if getattr(args, "github", None):
        for url in [s.strip() for s in args.github.split(",") if s.strip()]:
            created.append(collect_repo_paper(url))
    # 轻量闸门（不下载）：只对仍是 pending 的候选（explicit/citation）跑；github 已自带 resolution
    conn = get_conn()
    try:
        for c in created:
            if c.get("resolution") == "pending":
                res, matched = light_gate({"arxiv_id": c.get("arxiv_id"),
                                           "doi": None, "title": c.get("title")})
                conn.execute("UPDATE intake_candidates SET resolution=?, matched_work_id=? WHERE id=?",
                             (res, matched, c["id"]))
        conn.commit()
    finally:
        conn.close()
    print(f"collected {len(created)} candidates")
    if getattr(args, "auto_resolve", False):
        resolve()


def resolve_one(cid):
    """下载 + SHA256 重量闸门（heavy_gate 自管连接）。"""
    return heavy_gate(cid)   # 注意：heavy_gate(cid) 无 conn 参数


def resolve(args=None):
    """默认只对 resolution in {new, needs_better_copy} 的候选下载+SHA256。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id FROM intake_candidates WHERE resolution IN ('new','needs_better_copy')").fetchall()
        n = 0
        for r in rows:
            resolve_one(r[0]); n += 1
            # 无需 commit：heavy_gate 在自己的连接上自提交 resolution/fetched_sha256
    finally:
        conn.close()
    print(f"resolved {n} candidates")


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
