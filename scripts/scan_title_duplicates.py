"""Scan for title-based duplicate candidates and write to DB.

Finds works with similar titles (Jaccard >= 0.9) that are not yet in
duplicate_candidates. Writes new groups/candidates for human review.

Usage:
    uv run python scripts/scan_title_duplicates.py [--dry-run]
"""
import sys
import re
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.db import get_conn
from datetime import datetime, timezone

STOPWORDS = {"a", "an", "the", "of", "and", "or", "in", "on", "to", "for", "with", "by", "from", "is", "are", "was", "were"}


def normalize_title(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\[[^\]]+\]", " ", text)
    text = re.sub(r"【[^】]+】", " ", text)
    text = re.sub(r"arxiv[-_: ]*\d{4}\.\d{4,5}(v\d+)?", " ", text)
    text = re.sub(r"\b\d{4,8}\b", " ", text)
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
    tokens = [t for t in text.split() if t not in STOPWORDS]
    return " ".join(tokens)


def jaccard(a: str, b: str) -> float:
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def scan(dry_run: bool = False):
    conn = get_conn()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Load all works (exclude quarantined)
    works = conn.execute(
        "SELECT id, title, arxiv_id, doi FROM works WHERE read_status != 'quarantined'"
    ).fetchall()

    # Load existing duplicate_candidates to avoid re-creating
    existing_pairs = set()
    for r in conn.execute("SELECT group_id, work_id FROM duplicate_candidates").fetchall():
        existing_pairs.add((r["group_id"], r["work_id"]))

    # Load existing group keys
    existing_keys = set()
    for r in conn.execute("SELECT key FROM duplicate_groups WHERE duplicate_type='title_candidate'").fetchall():
        existing_keys.add(r["key"])

    # Normalize all titles
    work_data = []
    for w in works:
        norm = normalize_title(w["title"] or "")
        if norm:
            work_data.append({
                "id": w["id"],
                "title": w["title"],
                "norm": norm,
                "arxiv_id": w["arxiv_id"],
                "doi": w["doi"],
            })

    # Find pairs with Jaccard >= 0.9
    candidates_found = []
    n = len(work_data)
    for i in range(n):
        for j in range(i + 1, n):
            wi, wj = work_data[i], work_data[j]
            score = jaccard(wi["norm"], wj["norm"])
            if score >= 0.9:
                # Check if already exists
                key = wi["norm"][:100]
                group_id = f"DG-title-scan-{wi['id'][-8:]}-{wj['id'][-8:]}"
                if group_id in existing_keys:
                    continue
                candidates_found.append({
                    "work_a": wi,
                    "work_b": wj,
                    "score": round(score, 4),
                    "key": key,
                    "group_id": group_id,
                })

    print(f"Found {len(candidates_found)} new title-candidate pairs")

    if not dry_run:
        for c in candidates_found:
            wa, wb = c["work_a"], c["work_b"]
            group_id = c["group_id"]

            conn.execute(
                "INSERT OR IGNORE INTO duplicate_groups (id, duplicate_type, key, count) VALUES (?, ?, ?, ?)",
                (group_id, "title_candidate", c["key"], 2)
            )
            conn.execute(
                "INSERT OR IGNORE INTO duplicate_candidates "
                "(id, group_id, source_file_id, work_id, source_path, score, reason, reviewed) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
                (f"DC-{group_id}-A", group_id, "", wa["id"], "", c["score"], "title_jaccard>=0.90")
            )
            conn.execute(
                "INSERT OR IGNORE INTO duplicate_candidates "
                "(id, group_id, source_file_id, work_id, source_path, score, reason, reviewed) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
                (f"DC-{group_id}-B", group_id, "", wb["id"], "", c["score"], "title_jaccard>=0.90")
            )
            print(f"  {wa['id']} <-> {wb['id']} (score={c['score']})")

        conn.commit()
        print(f"\nWrote {len(candidates_found)} new duplicate groups to DB")
    else:
        for c in candidates_found[:20]:
            wa, wb = c["work_a"], c["work_b"]
            print(f"  [DRY] {wa['id']} ({wa['title'][:40]}) <-> {wb['id']} ({wb['title'][:40]}) score={c['score']}")
        if len(candidates_found) > 20:
            print(f"  ... and {len(candidates_found) - 20} more")

    conn.close()


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    scan(dry_run=dry_run)
