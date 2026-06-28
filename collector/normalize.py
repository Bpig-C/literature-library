# collector/normalize.py
"""Normalization helpers. Reuses literature_ingest logic (DRY); adds URL normalization."""
from __future__ import annotations
import re
# 别名导入避免与下方同名 wrapper 递归遮蔽
from scripts.literature_ingest import (
    extract_arxiv_id,
    arxiv_work_key,
    normalize_doi as _ingest_normalize_doi,
)

_GH_RE = re.compile(r"github\.com/([^/]+)/([^/#?]+?)(?:\.git|/)?$")

def normalize_arxiv_id(value: str):
    """Return versionless arXiv id (e.g. '2406.10162') or None."""
    if not value:
        return None
    raw = extract_arxiv_id(value)
    if not raw:
        return None
    return arxiv_work_key(raw)  # strips trailing v\d+

def normalize_doi(value: str):
    """Delegate to literature_ingest.normalize_doi (strips scheme/dx.doi.org, lowercases)."""
    return _ingest_normalize_doi(value)

def normalize_github_url(url: str):
    """Return 'owner/repo' canonical or None."""
    if not url:
        return None
    m = _GH_RE.search(url.strip())
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)
    if owner in {"search"}:
        return None
    return f"{owner}/{repo}"
