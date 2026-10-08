# collector/discovery_citation.py
"""(c) Citation-graph discovery, 1 hop, via Semantic Scholar Graph API.

For each seed paper: forward (papers that cite the seed) + backward (papers the seed cites).
Results become pending intake_candidates via collect_explicit (which dedups + writes).
No multi-hop in v1.

No get_conn import here: collect_explicit / insert_candidate own their connections.
"""
from __future__ import annotations
import json
import urllib.error
import urllib.request
from typing import Iterable, Optional

from collector.normalize import normalize_arxiv_id
from collector.discovery_explicit import collect_explicit

S2_BASE = "https://api.semanticscholar.org/graph/v1/paper"


def _s2_get(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": "literature-library-collector/0.1"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def _arxiv_to_s2paper(arxiv_id):
    """Resolve an arXiv id to a Semantic Scholar paperId via ARXIV: prefix."""
    return _s2_get(f"{S2_BASE}/ARXIV:{arxiv_id}?fields=externalIds,title")


def expand_one_hop(seed_arxiv_id):
    """Return (forward_list, backward_list); each item {arxiv_id, title}.

    forward = papers citing the seed; backward = papers the seed cites.
    Only items with a valid normalized arxiv_id are included.
    Returns ([], []) if the seed cannot be normalized.
    """
    aid = normalize_arxiv_id(seed_arxiv_id)
    if not aid:
        return [], []
    paper = _arxiv_to_s2paper(aid)
    pid = paper.get("paperId")
    if not pid:
        return [], []

    # v1 truncates at 100 edges per direction (no pagination yet).
    fwd = _s2_get(f"{S2_BASE}/{pid}/citations?fields=externalIds,title&limit=100")
    forward = []
    for row in fwd.get("data", []):
        p = row.get("citingPaper") or {}
        ext = p.get("externalIds") or {}
        nid = normalize_arxiv_id(ext["ArXiv"]) if ext.get("ArXiv") else None
        if nid:
            forward.append({"arxiv_id": nid, "title": p.get("title")})

    # v1 truncates at 100 edges per direction (no pagination yet).
    bwd = _s2_get(f"{S2_BASE}/{pid}/references?fields=externalIds,title&limit=100")
    backward = []
    for row in bwd.get("data", []):
        p = row.get("citedPaper") or {}
        ext = p.get("externalIds") or {}
        nid = normalize_arxiv_id(ext["ArXiv"]) if ext.get("ArXiv") else None
        if nid:
            backward.append({"arxiv_id": nid, "title": p.get("title")})

    return forward, backward


def collect_from_seeds(
    seed_arxiv_ids: Iterable[str],
    *,
    source_type: str = "arxiv",
    collection_topic_id: Optional[str] = None,
) -> list[dict]:
    """Expand each seed 1 hop in the citation graph, then route all found arxiv_ids
    through collect_explicit (which normalizes, fetches metadata, dedups, writes).

    Multi-hop is intentionally not supported in v1.

    v1 fail-loud per seed: a seed whose S2 lookup fails is skipped, the rest proceed
    (one dead seed must not poison the whole batch).
    """
    found: list[str] = []
    for seed in seed_arxiv_ids:
        try:
            forward, backward = expand_one_hop(seed)
        except (urllib.error.URLError, urllib.error.HTTPError,
                json.JSONDecodeError, TimeoutError):
            continue   # 单种子 S2 调用失败：跳过该种子，不毒化整批
        for p in forward + backward:
            if p.get("arxiv_id"):
                found.append(p["arxiv_id"])
    return collect_explicit(
        found,
        source_type=source_type,
        collection_topic_id=collection_topic_id,
    )
