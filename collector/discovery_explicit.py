# collector/discovery_explicit.py
"""(a) Explicit-ID discovery: turn a list of arXiv IDs into pending intake_candidates.
No download. Routes inserts through candidate_store.insert_candidate (tiered candidate-layer dedup).
Idempotent: re-collecting the same IDs yields no new candidates.
"""
from __future__ import annotations
from typing import Iterable, Optional

from collector.normalize import normalize_arxiv_id
from collector.adapters import arxiv
from collector.candidate_store import insert_candidate

# module-level alias so tests can monkeypatch de.fetch_metadata
fetch_metadata = arxiv.fetch_metadata


def collect_explicit(
    arxiv_ids: Iterable[str],
    *,
    source_type: str = "arxiv",
    collection_topic_id: Optional[str] = None,
) -> list[dict]:
    """Turn raw arXiv ids into pending intake_candidates.

    - normalize each id; skip if None
    - fetch metadata (title + doi) via fetch_metadata
    - route through insert_candidate (tiered dedup)
    - return only newly-created candidates as dicts suitable for light_gate input:
      {"id", "arxiv_id", "url_canonical", "title", "resolution"}
    """
    created: list[dict] = []
    for raw in arxiv_ids:
        aid = normalize_arxiv_id(raw)
        if aid is None:
            continue
        url = f"https://arxiv.org/abs/{aid}"
        meta = fetch_metadata(aid)
        cid, status = insert_candidate(
            source_type=source_type,
            url_canonical=url,
            arxiv_id=aid,
            doi=meta.get("doi"),
            title=meta.get("title"),
            raw_meta=meta,
            collection_topic_id=collection_topic_id,
        )
        if status == "created":
            created.append({
                "id": cid,
                "arxiv_id": aid,
                "url_canonical": url,
                "title": meta.get("title"),
                "resolution": "pending",
            })
    return created
