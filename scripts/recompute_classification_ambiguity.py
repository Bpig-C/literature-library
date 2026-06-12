"""Recompute ambiguity scores for all pending classification extractions.

Fixes D1 data inconsistency: batch-imported records had hand-filled ambiguity_score
that didn't match compute_ambiguity() output. This script merges dual-source
confidence (embedded + column) and recomputes scores for pending records only.

Design decisions:
- Only updates ambiguity_score and ambiguity_reasons, NOT updated_at — preserves
  original audit timestamp semantics (last human review time, not last computation).
- Does NOT write review_note or fix_action — this is a data correction, not a review action.
- Only processes review_status='pending' records — approved/rejected records retain
  their historical snapshot (consistent with P1.0d risk-snapshot principle).

Usage:
    uv run python scripts/recompute_classification_ambiguity.py [--dry-run]
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.db import DB_PATH
from api.classification_ambiguity import compute_ambiguity


def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def recompute(dry_run: bool = False):
    conn = get_conn()
    try:
        # Fetch all pending extractions
        rows = conn.execute(
            "SELECT id, work_id, extracted_json, confidence_json, "
            "ambiguity_score, ambiguity_reasons, model_name "
            "FROM classification_extractions WHERE review_status = 'pending'"
        ).fetchall()

        print(f"Found {len(rows)} pending extractions to recompute.")

        changes = []
        for row in rows:
            ext_id = row["id"]
            extracted = json.loads(row["extracted_json"]) if row["extracted_json"] else {}
            column_confidence = json.loads(row["confidence_json"]) if row["confidence_json"] else {}
            old_score = row["ambiguity_score"]
            old_reasons = json.loads(row["ambiguity_reasons"]) if row["ambiguity_reasons"] else []

            # Merge dual-source confidence (D1 fix)
            embedded_confidence = extracted.get("confidence", {})
            merged_confidence = {**embedded_confidence, **column_confidence}

            # Recompute
            new_amb = compute_ambiguity(extracted, merged_confidence)
            new_score = new_amb["score"]
            new_reasons = new_amb["reasons"]

            if new_score != old_score or set(new_reasons) != set(old_reasons):
                changes.append({
                    "id": ext_id,
                    "work_id": row["work_id"],
                    "model": row["model_name"],
                    "old_score": old_score,
                    "new_score": new_score,
                    "old_reasons": old_reasons,
                    "new_reasons": new_reasons,
                })

                if not dry_run:
                    conn.execute(
                        "UPDATE classification_extractions SET "
                        "ambiguity_score = ?, ambiguity_reasons = ? WHERE id = ?",
                        (new_score, json.dumps(new_reasons, ensure_ascii=False), ext_id),
                    )

        if not dry_run:
            conn.commit()
            print(f"Updated {len(changes)} records.")
        else:
            print(f"[DRY RUN] Would update {len(changes)} records.")

        # Print change summary
        if changes:
            print("\n--- Change Summary ---")
            # Distribution comparison
            from collections import Counter

            def score_bucket(s):
                if s < 20:
                    return "low (0-19)"
                elif s < 50:
                    return "medium (20-49)"
                else:
                    return "high (50+)"

            old_dist = Counter(score_bucket(c["old_score"]) for c in changes)
            new_dist = Counter(score_bucket(c["new_score"]) for c in changes)

            print("\nScore distribution changes (records that changed):")
            all_buckets = ["low (0-19)", "medium (20-49)", "high (50+)"]
            for b in all_buckets:
                print(f"  {b}: {old_dist.get(b, 0)} -> {new_dist.get(b, 0)}")

            # Show Mimo batch changes specifically
            mimo_changes = [c for c in changes if c["model"] and "mimo" in c["model"]]
            if mimo_changes:
                print(f"\nMimo batch changes: {len(mimo_changes)}")
                for c in mimo_changes[:10]:
                    print(f"  {c['id']}: {c['old_score']} -> {c['new_score']}")
                    added = set(c["new_reasons"]) - set(c["old_reasons"])
                    removed = set(c["old_reasons"]) - set(c["new_reasons"])
                    if added:
                        print(f"    + {', '.join(added)}")
                    if removed:
                        print(f"    - {', '.join(removed)}")
                if len(mimo_changes) > 10:
                    print(f"  ... and {len(mimo_changes) - 10} more")

            # Detailed changes for first few
            print(f"\nDetailed changes (first 20):")
            for c in changes[:20]:
                print(f"  {c['id']} ({c['work_id']}): {c['old_score']} -> {c['new_score']}")
                added = set(c["new_reasons"]) - set(c["old_reasons"])
                removed = set(c["old_reasons"]) - set(c["new_reasons"])
                if added:
                    print(f"    + {', '.join(added)}")
                if removed:
                    print(f"    - {', '.join(removed)}")
            if len(changes) > 20:
                print(f"  ... and {len(changes) - 20} more")

    finally:
        conn.close()


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    recompute(dry_run=dry_run)
