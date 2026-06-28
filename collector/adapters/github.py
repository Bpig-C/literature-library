"""GitHub adapter (v1): collect paper/report PDFs only.
Cross-source alignment to existing arXiv works is by STRONG KEYS (arXiv ID/DOI) via light_gate,
NEVER SHA256 (different hosts => different bytes).
Reuses machine gh auth via `gh api` (no separate token). Code repos: URL -> raw_meta only, no work.
"""
from __future__ import annotations
import re, subprocess
from api.db import get_conn
from collector.normalize import normalize_arxiv_id, normalize_github_url
from collector.candidate_store import insert_candidate
from collector.gate import light_gate

_ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5})", re.IGNORECASE)


def fetch_repo_readme(repo_url):
    """Fetch README text via gh api (reuses local gh auth). Returns '' on failure."""
    repo = normalize_github_url(repo_url)  # owner/name
    if not repo:
        return ""
    try:
        out = subprocess.run(
            ["gh", "api", f"repos/{repo}/readme", "-H", "Accept: application/vnd.github.raw"],
            capture_output=True, text=True, timeout=20, check=True)
        return out.stdout
    except Exception:
        return ""


def extract_arxiv_id(text):
    """Pull first arXiv id (abs/pdf URL) out of free text. Returns versionless id or None."""
    if not text:
        return None
    m = _ARXIV_RE.search(text)
    return normalize_arxiv_id(m.group(1)) if m else None


def collect_repo_paper(repo_url, *, collection_topic_id=None):
    """Collect a GitHub paper source. Extract strong key (arxiv_id) from README;
    insert candidate via insert_candidate; run light_gate for cross-source alignment;
    persist resolution + matched_work_id.

    Alignment is by STRONG KEY (arxiv_id) — never SHA256 (different hosts => different bytes).
    A code-only repo (no arxiv_id) still creates a candidate (resolution=new); repo_url goes
    into raw_meta and no work is created here.
    Returns dict with id/arxiv_id/resolution/matched_work_id."""
    readme = fetch_repo_readme(repo_url)
    aid = extract_arxiv_id(readme)
    canonical = normalize_github_url(repo_url) or repo_url
    raw = {"repo_url": repo_url, "extracted_arxiv_id": aid, "readme_excerpt": (readme or "")[:500]}
    cid, _status = insert_candidate(
        source_type="github", url_canonical=canonical,
        arxiv_id=aid, raw_meta=raw, collection_topic_id=collection_topic_id)
    resolution, matched = light_gate({"arxiv_id": aid, "doi": None, "title": None})
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE intake_candidates SET resolution=?, matched_work_id=? WHERE id=?",
            (resolution, matched, cid))
        conn.commit()
    finally:
        conn.close()
    return {"id": cid, "arxiv_id": aid, "resolution": resolution, "matched_work_id": matched}
