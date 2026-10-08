# collector/candidate_store.py
"""Candidate-layer dedup. Collector's own responsibility to avoid candidate-vs-candidate dups
(esp. cross-source: arXiv + GitHub same paper). Discovery adapters MUST route inserts through here.

Tiered backstop: strong key (arxiv_id/doi) -> url_canonical -> else create
(no title auto-skip; rely on gate title_candidate + work_id + SHA256 downstream).
Only dedups against status IN ('pending','resolved'); ingested ones are left to the gate vs works.
"""
from __future__ import annotations
import json, secrets
from datetime import datetime, timezone
from api.db import get_conn

def _existing(conn, *, arxiv_id=None, doi=None, url_canonical=None):
    """Return id of an active candidate matching strong key or url, else None."""
    if arxiv_id:
        row = conn.execute(
            "SELECT id FROM intake_candidates WHERE arxiv_id=? AND status IN ('pending','resolved')",
            (arxiv_id,)).fetchone()
        if row:
            return row[0]
    if doi:
        row = conn.execute(
            "SELECT id FROM intake_candidates WHERE doi=? AND status IN ('pending','resolved')",
            (doi,)).fetchone()
        if row:
            return row[0]
    if url_canonical:
        row = conn.execute(
            "SELECT id FROM intake_candidates WHERE url_canonical=? AND status IN ('pending','resolved')",
            (url_canonical,)).fetchone()
        if row:
            return row[0]
    return None

def insert_candidate(*, source_type, url_canonical, arxiv_id=None, doi=None, title=None,
                     raw_meta=None, collection_topic_id=None):
    """Insert a candidate with tiered dedup. Returns (candidate_id, status in {created, skipped_dup})."""
    conn = get_conn()
    try:
        existing = _existing(conn, arxiv_id=arxiv_id, doi=doi, url_canonical=url_canonical)
        if existing:
            return existing, "skipped_dup"
        cid = "IC-" + secrets.token_hex(4)
        conn.execute(
            """INSERT INTO intake_candidates
               (id, source_type, url_canonical, arxiv_id, doi, title, resolution,
                status, review_status, raw_meta, collection_topic_id, collected_at)
               VALUES (?,?,?,?,?,?, 'pending','pending','pending',?,?,?)""",
            (cid, source_type, url_canonical, arxiv_id, doi, title,
             json.dumps(raw_meta, ensure_ascii=False) if raw_meta else None,
             collection_topic_id, datetime.now(timezone.utc).isoformat()))
        conn.commit()
        return cid, "created"
    finally:
        conn.close()


VALID_REVIEW = {"pending", "approved", "rejected"}


def set_review_status(candidate_id, status, note=None):
    """Set a candidate's A2 review_status (pending|approved|rejected). Optional note.

    This is the single nucleus for review-status writes; both the CLI and the
    intake API delegate here (no duplicate UPDATE logic).
    """
    if status not in VALID_REVIEW:
        raise ValueError(f"bad review_status {status}")
    conn = get_conn()
    try:
        cur = conn.execute("SELECT 1 FROM intake_candidates WHERE id=?", (candidate_id,)).fetchone()
        if not cur:
            raise KeyError(candidate_id)
        if note is not None:
            conn.execute("UPDATE intake_candidates SET review_status=?, review_note=? WHERE id=?",
                         (status, note, candidate_id))
        else:
            conn.execute("UPDATE intake_candidates SET review_status=? WHERE id=?",
                         (status, candidate_id))
        conn.commit()
    finally:
        conn.close()
