"""Backfill classification fields from existing doc_type and filename heuristics.

Maps old doc_type values and filename/title keywords to new classification fields.
High-confidence rules write directly to works; medium/low only set ingestion_state.

Usage:
    python scripts/migrate_backfill_doc_type.py
    python scripts/migrate_backfill_doc_type.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.db import get_conn

# ---------------------------------------------------------------------------
# Mapping from old doc_type to new classification fields
# ---------------------------------------------------------------------------

DOC_TYPE_MAP = {
    "system_card": {
        "primary_doc_type": "system_model_card",
        "publication_status": "institutional_release",
        "ingestion_state": "verified",
        "confidence": "high",
    },
    "benchmark": {
        "primary_doc_type": None,  # needs filename/title confirmation
        "publication_status": None,
        "ingestion_state": "needs_review",
        "confidence": "medium",
    },
    "preprint": {
        "primary_doc_type": None,
        "publication_status": "preprint",
        "ingestion_state": "needs_review",
        "confidence": "low",
    },
    "paper": {
        "primary_doc_type": None,
        "ingestion_state": "needs_review",
        "confidence": "low",
    },
    "report": {
        "primary_doc_type": None,
        "ingestion_state": "needs_review",
        "confidence": "low",
    },
}

# ---------------------------------------------------------------------------
# Filename/title keyword heuristics (applied after doc_type mapping)
# Each rule: (regex, overrides_dict)
# Only applied if the regex matches title or original_name.
# ---------------------------------------------------------------------------

FILENAME_HINTS = [
    (r"system[_ -]?card|model[_ -]?card|safety[_ -]?card|transparency[_ -]?report",
     {"primary_doc_type": "system_model_card", "publication_status": "institutional_release", "confidence": "high"}),
    (r"technical[_ -]?report",
     {"primary_doc_type": "technical_report", "confidence": "high"}),
    (r"benchmark|bench[\W_]|dataset|eval[_ -]?suite|leaderboard\s*paper",
     {"primary_doc_type": "benchmark_dataset_paper", "confidence": "medium"}),
    (r"leaderboard|dashboard|scorecard",
     {"primary_doc_type": "platform_snapshot", "publication_status": "webpage_release", "confidence": "medium"}),
    (r"guide|guideline|sp[_ -]?\d+|iso|code[_ -]?of[_ -]?practice|standard",
     {"primary_doc_type": "standard_guideline", "confidence": "medium"}),
    (r"framework|rmf|preparedness|responsible[_ -]?scaling|rsp|frontier[_ -]?safety",
     {"primary_doc_type": "governance_framework", "confidence": "medium"}),
    (r"year[_ -]?in[_ -]?review|trend|landscape|annual[_ -]?report",
     {"primary_doc_type": "institutional_report", "confidence": "medium"}),
    (r"survey|review\s*paper|position\s*paper",
     {"primary_doc_type": "survey_review", "confidence": "medium"}),
]

# Prefix heuristics from filename patterns
# Returns a dict of overrides or None
PREFIX_RULES = [
    # 【R】 or R_ prefix → report-like
    (r"^【R】|^R\d|^[Rr]_",
     {"primary_doc_type": None, "ingestion_state": "needs_review", "prefix_hint": "report_like"}),
    # I* prefix → company/system related
    (r"^\[?I\d",
     {"primary_doc_type": None, "ingestion_state": "needs_review", "prefix_hint": "institutional"}),
    # E* prefix → evaluation
    (r"^E\d|^\[?E\d",
     {"primary_doc_type": None, "ingestion_state": "needs_review", "prefix_hint": "evaluation"}),
    # G* prefix → governance/guideline
    (r"^G\d|^\[?G\d",
     {"primary_doc_type": None, "ingestion_state": "needs_review", "prefix_hint": "governance"}),
    # C* prefix → company technical
    (r"^C\d|^\[?C\d",
     {"primary_doc_type": None, "ingestion_state": "needs_review", "prefix_hint": "company"}),
]


def _regex_match(patterns, text):
    """Return True if any pattern matches text."""
    if not text:
        return False
    for p in patterns:
        if re.search(p, text, re.IGNORECASE):
            return True
    return False


def classify_work(row, source_names):
    """Classify a single work row based on doc_type, title, and source filenames.

    Returns a dict of field overrides to write to works table.
    Returns None if nothing should be written.
    """
    old_doc_type = row["doc_type"]
    title = row["title"] or ""
    arxiv_id = row["arxiv_id"] or ""

    # Combine all text for heuristic matching
    all_names = " ".join(source_names)
    combined_text = f"{title} {all_names}"

    result = {}
    notes_parts = []

    # Step 1: Apply doc_type base mapping
    base = DOC_TYPE_MAP.get(old_doc_type, {})
    if base.get("primary_doc_type"):
        result["primary_doc_type"] = base["primary_doc_type"]
        notes_parts.append(f"doc_type={old_doc_type} -> {base['primary_doc_type']}")
    if base.get("publication_status"):
        result["publication_status"] = base["publication_status"]
    if base.get("ingestion_state"):
        result["ingestion_state"] = base["ingestion_state"]
    confidence = base.get("confidence", "low")

    # Step 2: Apply filename/title keyword heuristics (can override)
    for pattern, overrides in FILENAME_HINTS:
        if re.search(pattern, combined_text, re.IGNORECASE):
            # Only upgrade confidence, never downgrade
            new_conf = overrides.get("confidence", "medium")
            conf_order = {"low": 0, "medium": 1, "high": 2}
            if conf_order.get(new_conf, 0) >= conf_order.get(confidence, 0):
                if overrides.get("primary_doc_type"):
                    result["primary_doc_type"] = overrides["primary_doc_type"]
                    notes_parts.append(f"filename_hint: {pattern} -> {overrides['primary_doc_type']}")
                if overrides.get("publication_status"):
                    result["publication_status"] = overrides["publication_status"]
                confidence = new_conf

    # Step 3: For benchmark doc_type, check if title strongly confirms
    # But exclude papers that merely discuss/evaluate benchmarks rather than introduce them
    if old_doc_type == "benchmark":
        NEGATIVE_BENCHMARK = re.compile(
            r"evaluat|limitations|comparative|survey|on the|toward|critique|analysis of",
            re.IGNORECASE,
        )
        if re.search(r"benchmark|bench|dataset|eval[_ -]?suite", combined_text, re.IGNORECASE):
            if NEGATIVE_BENCHMARK.search(combined_text):
                # Discusses benchmarks, doesn't introduce one
                notes_parts.append("benchmark keyword found but title suggests discussion, not introduction")
            else:
                result["primary_doc_type"] = "benchmark_dataset_paper"
                confidence = "medium"
                notes_parts.append("benchmark confirmed by title/filename keywords")

    # Step 4: Prefix heuristics (add evidence, don't override high-confidence)
    for pattern, overrides in PREFIX_RULES:
        if re.search(pattern, all_names, re.IGNORECASE):
            prefix_hint = overrides.get("prefix_hint", "")
            notes_parts.append(f"prefix_hint: {prefix_hint}")
            # Prefix alone doesn't determine type, just adds evidence

    # Step 5: arXiv papers — do NOT unconditionally set preprint
    # Many arXiv papers are published conference papers; leave publication_status NULL
    # for human verification when ingestion_state=needs_review

    if not result and not notes_parts:
        return None

    return {
        "fields": result,
        "confidence": confidence,
        "notes": "; ".join(notes_parts),
    }


def run_backfill(dry_run=False):
    conn = get_conn()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Find works that haven't been classified yet
    rows = conn.execute(
        "SELECT id, doc_type, title, arxiv_id, doi, venue, url FROM works WHERE primary_doc_type IS NULL OR ingestion_state IS NULL"
    ).fetchall()

    stats = {"auto_mapped": 0, "needs_review": 0, "skipped": 0, "total": len(rows)}
    by_old_type = {}
    by_new_type = {}

    for row in rows:
        d = dict(row)
        work_id = d["id"]
        old_type = d["doc_type"] or "unknown"

        # Get source file names
        sources = conn.execute(
            "SELECT original_name FROM source_files WHERE work_id = ? AND status = 'active'",
            (work_id,),
        ).fetchall()
        source_names = [s["original_name"] for s in sources if s["original_name"]]

        by_old_type.setdefault(old_type, {"total": 0, "auto": 0, "review": 0})
        by_old_type[old_type]["total"] += 1

        result = classify_work(d, source_names)
        if not result:
            stats["skipped"] += 1
            continue

        fields = result["fields"]
        confidence = result["confidence"]
        notes = result["notes"]

        # Determine if we should auto-map or just mark for review
        should_auto_write = (
            confidence == "high"
            and fields.get("primary_doc_type") is not None
        )

        if should_auto_write:
            stats["auto_mapped"] += 1
            by_old_type[old_type]["auto"] += 1
            new_type = fields.get("primary_doc_type", "unknown")
            by_new_type.setdefault(new_type, 0)
            by_new_type[new_type] += 1
        else:
            stats["needs_review"] += 1
            by_old_type[old_type]["review"] += 1

        if not dry_run:
            # Always set ingestion_state if not set
            ingestion = fields.get("ingestion_state", "needs_review")
            if should_auto_write:
                ingestion = "verified"

            update_fields = {}
            if "primary_doc_type" in fields:
                update_fields["primary_doc_type"] = fields["primary_doc_type"]
            if "publication_status" in fields:
                update_fields["publication_status"] = fields["publication_status"]
            update_fields["ingestion_state"] = ingestion

            set_clauses = []
            params = []
            for k, v in update_fields.items():
                set_clauses.append(f"{k} = ?")
                params.append(v)
            set_clauses.append("updated_at = ?")
            params.append(now)
            params.append(work_id)

            conn.execute(
                f"UPDATE works SET {', '.join(set_clauses)} WHERE id = ?",
                params,
            )

    if not dry_run:
        conn.commit()

    conn.close()

    # Print report
    print(f"=== Backfill {'DRY RUN' if dry_run else 'COMPLETE'} ===")
    print(f"Total works checked: {stats['total']}")
    print(f"Auto-mapped (high confidence): {stats['auto_mapped']}")
    print(f"Needs review: {stats['needs_review']}")
    print(f"Skipped (already classified): {stats['skipped']}")
    print()

    print("--- By old doc_type ---")
    for old_type, counts in sorted(by_old_type.items()):
        print(f"  {old_type}: total={counts['total']}, auto={counts['auto']}, review={counts['review']}")

    if by_new_type:
        print()
        print("--- Auto-mapped to new primary_doc_type ---")
        for new_type, count in sorted(by_new_type.items()):
            print(f"  {new_type}: {count}")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Backfill classification from old doc_type")
    parser.add_argument("--dry-run", action="store_true", help="Print without writing")
    args = parser.parse_args()
    run_backfill(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
