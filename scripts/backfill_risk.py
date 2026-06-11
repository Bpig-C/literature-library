"""Backfill risk_level/risk_score/risk_reasons for existing metadata_extractions.

Run once after P1.0d deployment to compute risk for extractions that were
created before risk scoring was added.

Usage:
    python scripts/backfill_risk.py
    python scripts/backfill_risk.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

LIBRARY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIBRARY_ROOT))

import sqlite3
from api.db import DB_PATH, ensure_metadata_review_columns
from api.risk import compute_risk


def main():
    parser = argparse.ArgumentParser(description="Backfill risk scores for existing extractions")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be updated without writing")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    ensure_metadata_review_columns(conn)

    rows = conn.execute(
        "SELECT me.*, w.title AS work_title FROM metadata_extractions me "
        "JOIN works w ON w.id = me.work_id "
        "WHERE me.risk_level IS NULL OR me.risk_level = 'pending'"
    ).fetchall()

    print(f"Found {len(rows)} extractions without risk scores")

    updated = 0
    for row in rows:
        ext = dict(row)
        extracted = json.loads(ext["extracted_json"]) if ext["extracted_json"] else {}
        confidence = json.loads(ext["confidence_json"]) if ext["confidence_json"] else {}
        warnings = []  # we don't store validation_warnings in DB

        risk = compute_risk(extracted, confidence, warnings, ext.get("work_title"))

        if args.dry_run:
            print(f"  {ext['id']}: risk={risk['risk_level']}, score={risk['risk_score']}, reasons={risk['risk_reasons']}")
        else:
            conn.execute(
                "UPDATE metadata_extractions SET risk_level = ?, risk_score = ?, risk_reasons = ? WHERE id = ?",
                (risk["risk_level"], risk["risk_score"],
                 json.dumps(risk["risk_reasons"], ensure_ascii=False), ext["id"]),
            )
            print(f"  {ext['id']}: {risk['risk_level']} ({risk['risk_score']})")
        updated += 1

    if not args.dry_run:
        conn.commit()
        print(f"\nUpdated {updated} extractions")
    else:
        print(f"\nDry run: would update {updated} extractions")

    conn.close()


if __name__ == "__main__":
    main()
