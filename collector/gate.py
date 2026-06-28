# collector/gate.py
"""Two-stage pre-ingest dedup gate. Reuses literature_ingest normalization + jaccard.

light_gate: metadata-only, decides whether to download. No file IO.
heavy_gate: after download, SHA256 against source_files. (added in a later task)
"""
from __future__ import annotations
from api.db import get_conn
from collector.normalize import normalize_arxiv_id, normalize_doi
from scripts.literature_ingest import normalize_title, jaccard

TITLE_THRESHOLD = 0.9

def _find_by_strong_key(conn, arxiv_id, doi):
    """Return (work_id, read_status) for arxiv/doi match, else (None, None). Arxiv first."""
    if arxiv_id:
        row = conn.execute("SELECT id, read_status FROM works WHERE arxiv_id=?", (arxiv_id,)).fetchone()
        if row:
            return row[0], row[1]
    if doi:
        row = conn.execute("SELECT id, read_status FROM works WHERE doi=?", (doi,)).fetchone()
        if row:
            return row[0], row[1]
    return None, None

def _title_match(conn, title):
    """Return (work_id, read_status) of best jaccard>=threshold work, else (None,None)."""
    if not title:
        return None, None
    nt = normalize_title(title)
    best, best_sim, best_status = None, 0.0, None
    for wid, wtitle, wstatus in conn.execute("SELECT id, title, read_status FROM works").fetchall():
        if not wtitle:
            continue
        sim = jaccard(nt, normalize_title(wtitle))
        if sim > best_sim:
            best, best_sim, best_status = wid, sim, wstatus
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
