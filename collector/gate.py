# collector/gate.py
"""Two-stage pre-ingest dedup gate. Reuses literature_ingest normalization + jaccard.

light_gate: metadata-only, decides whether to download. No file IO.
heavy_gate: after download, SHA256 against source_files. (added in a later task)
"""
from __future__ import annotations
from pathlib import Path
from api.db import get_conn
from collector.normalize import normalize_arxiv_id, normalize_doi
from scripts.literature_ingest import normalize_title, jaccard, sha256_file, utc_now

TITLE_THRESHOLD = 0.9

def _find_by_strong_key(conn, arxiv_id, doi):
    """Return (work_id, read_status) for arxiv/doi match, else (None, None). Arxiv first."""
    if arxiv_id:
        row = conn.execute("SELECT id, read_status FROM works WHERE arxiv_id=?", (arxiv_id,)).fetchone()
        if row:
            return row["id"], row["read_status"]
    if doi:
        row = conn.execute("SELECT id, read_status FROM works WHERE doi=?", (doi,)).fetchone()
        if row:
            return row["id"], row["read_status"]
    return None, None

def _title_match(conn, title):
    """Return (work_id, read_status) of best jaccard>=threshold work, else (None,None)."""
    if not title:
        return None, None
    nt = normalize_title(title)
    best, best_sim, best_status = None, 0.0, None
    for row in conn.execute("SELECT id, title, read_status FROM works").fetchall():
        wtitle = row["title"]
        if not wtitle:
            continue
        sim = jaccard(nt, normalize_title(wtitle))
        if sim > best_sim:
            best, best_sim, best_status = row["id"], sim, row["read_status"]
    if best_sim >= TITLE_THRESHOLD:
        return best, best_status
    return None, None

def light_gate(candidate: dict):
    """Return (resolution, matched_work_id). No download. Candidate keys: arxiv_id, doi, title.

    Four states:
      - exact_hit: strong key (arxiv/doi) match on an active work
      - needs_better_copy: any match (strong or title) on a quarantined work
      - title_candidate: title-only match (no strong key) on an active work
      - new: no match
    """
    conn = get_conn()
    try:
        aid = normalize_arxiv_id(candidate.get("arxiv_id") or "")
        doi = normalize_doi(candidate.get("doi") or "")

        # Strong-key path: arxiv before doi.
        wid, status = _find_by_strong_key(conn, aid, doi)
        if wid:
            return ("needs_better_copy" if status == "quarantined" else "exact_hit"), wid

        # Title-only fallback: distinct from exact_hit because strong keys are absent.
        wid, status = _title_match(conn, candidate.get("title") or "")
        if wid:
            return ("needs_better_copy" if status == "quarantined" else "title_candidate"), wid

        return "new", None
    finally:
        conn.close()


def heavy_gate(candidate_id: str):
    """Download-bound SHA256 check. Reads candidate.local_pdf_path, hashes, looks up source_files.
    Updates candidate.resolution + fetched_sha256. Returns resolution."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT local_pdf_path FROM intake_candidates WHERE id=?",
                           (candidate_id,)).fetchone()
        if not row or not row["local_pdf_path"]:
            return "fetch_failed"
        pdf = Path(row["local_pdf_path"])
        if not pdf.exists():
            return "fetch_failed"
        digest = sha256_file(pdf)
        hit = conn.execute("SELECT 1 FROM source_files WHERE content_sha256=?", (digest,)).fetchone()
        resolution = "sha256_duplicate" if hit else "new"
        conn.execute(
            "UPDATE intake_candidates SET fetched_sha256=?, resolution=?, resolved_at=? WHERE id=?",
            (digest, resolution, utc_now(), candidate_id))
        conn.commit()
        return resolution
    finally:
        conn.close()
