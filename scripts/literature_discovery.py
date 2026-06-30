# scripts/literature_discovery.py
"""V1.1 Constrained Discovery CLI — plan / run / runs / hits / accept / reject.

V1.1 scope: name / title / url / topic plan only.
DOI / arxiv_id / github_url discovery are NOT supported — use existing collect.

Usage:
    python scripts/literature_discovery.py plan --name "GPT-5.6 system card"
    python scripts/literature_discovery.py plan --title "Exact Paper Title" --type research_article
    python scripts/literature_discovery.py plan --url "https://example.com/paper.pdf"
    python scripts/literature_discovery.py plan --topic CT-xxxx
    python scripts/literature_discovery.py run --mode name --input '{"name":"GPT-5.6 system card"}'
    python scripts/literature_discovery.py runs
    python scripts/literature_discovery.py hits --run DR-xxxx
    python scripts/literature_discovery.py accept --hits DH-1,DH-2
    python scripts/literature_discovery.py reject --hit DH-1 --note "not relevant"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collector import discovery


def plan_cmd(args):
    """Generate a search plan and print as JSON."""
    if args.doi or args.arxiv or args.github_url:
        print(
            "error: --doi / --arxiv / --github-url discovery is not supported in V1.1. "
            "Use existing literature_intake.py collect for arxiv/github.",
            file=sys.stderr,
        )
        sys.exit(1)

    mode = args.mode
    if not mode:
        if args.name:
            mode = "name"
        elif args.title:
            mode = "title"
        elif args.url:
            mode = "url"
        elif args.topic:
            mode = "topic"
        else:
            print("error: specify --name, --title, --url, or --topic", file=sys.stderr)
            sys.exit(1)

    try:
        p = discovery.draft_search_plan(
            mode=mode,
            name=args.name,
            title=args.title,
            known_url=args.url,
            topic_id=args.topic,
            artifact_type_hint=args.artifact_type_hint,
        )
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(p, indent=2, ensure_ascii=False))


def run_cmd(args):
    """Create a discovery run."""
    try:
        input_data = json.loads(args.input) if args.input else {}
    except json.JSONDecodeError as e:
        print(f"error: invalid JSON for --input: {e}", file=sys.stderr)
        sys.exit(1)

    plan_data = None
    if args.plan:
        try:
            plan_data = json.loads(args.plan)
        except json.JSONDecodeError as e:
            print(f"error: invalid JSON for --plan: {e}", file=sys.stderr)
            sys.exit(1)

    mode = args.mode or input_data.get("mode", "name")
    executor = args.executor or "python"

    try:
        r = discovery.create_discovery_run(
            mode=mode,
            input_json=input_data,
            search_plan_json=plan_data or {},
            executor=executor,
            collection_topic_id=args.topic,
        )
    except (ValueError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(r, indent=2, ensure_ascii=False))


def runs_cmd(args):
    """List discovery runs."""
    result = discovery.list_discovery_runs(
        status=args.status,
        topic_id=args.topic,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


def hits_cmd(args):
    """List discovery hits."""
    result = discovery.list_discovery_hits(
        run_id=args.run,
        review_status=args.review_status,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


def accept_cmd(args):
    """Accept one or more hits into intake."""
    ids = [h.strip() for h in args.hits.split(",") if h.strip()]
    if not ids:
        print("error: --hits must contain at least one hit id", file=sys.stderr)
        sys.exit(1)

    result = discovery.batch_accept_hits(ids, review_note=args.note or "")
    print(json.dumps(result, indent=2, ensure_ascii=False))


def reject_cmd(args):
    """Reject a single hit."""
    result = discovery.reject_hit(args.hit, review_note=args.note)
    print(json.dumps(result, indent=2, ensure_ascii=False))


def main(argv=None):
    ap = argparse.ArgumentParser(description="V1.1 Constrained Discovery CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    # plan
    p = sub.add_parser("plan", help="Generate a search plan")
    p.add_argument("--mode", choices=["name", "title", "url", "topic"])
    p.add_argument("--name", help="Name to search for")
    p.add_argument("--title", help="Title to search for")
    p.add_argument("--url", help="URL to search for")
    p.add_argument("--topic", help="Topic ID for topic-based discovery")
    p.add_argument("--type", dest="artifact_type_hint", help="Artifact type hint")
    p.add_argument("--max-results", type=int, default=20)
    p.add_argument("--doi", action="store_true", help="(unsupported in V1.1)")
    p.add_argument("--arxiv", action="store_true", help="(unsupported in V1.1)")
    p.add_argument("--github-url", dest="github_url", action="store_true", help="(unsupported in V1.1)")

    # run
    r = sub.add_parser("run", help="Create a discovery run")
    r.add_argument("--mode", choices=["name", "title", "url", "topic"])
    r.add_argument("--input", required=True, help="JSON input data")
    r.add_argument("--plan", help="JSON search plan")
    r.add_argument("--executor", default="python", choices=["python", "agent:web-access", "manual"])
    r.add_argument("--topic", help="Topic ID")

    # runs
    rs = sub.add_parser("runs", help="List discovery runs")
    rs.add_argument("--topic", help="Filter by topic ID")
    rs.add_argument("--status", help="Filter by status")

    # hits
    h = sub.add_parser("hits", help="List discovery hits")
    h.add_argument("--run", help="Filter by run ID")
    h.add_argument("--review-status", dest="review_status", help="Filter by review status")

    # accept
    a = sub.add_parser("accept", help="Accept hits into intake")
    a.add_argument("--hits", required=True, help="Comma-separated hit IDs")
    a.add_argument("--note", help="Review note")

    # reject
    rej = sub.add_parser("reject", help="Reject a hit")
    rej.add_argument("--hit", required=True, help="Hit ID to reject")
    rej.add_argument("--note", help="Review note")

    args = ap.parse_args(argv)
    if args.cmd == "plan":
        plan_cmd(args)
    elif args.cmd == "run":
        run_cmd(args)
    elif args.cmd == "runs":
        runs_cmd(args)
    elif args.cmd == "hits":
        hits_cmd(args)
    elif args.cmd == "accept":
        accept_cmd(args)
    elif args.cmd == "reject":
        reject_cmd(args)


if __name__ == "__main__":
    main()
