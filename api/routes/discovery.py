# api/routes/discovery.py
"""Discovery API routes (V1.1 constrained discovery). Thin adapters over collector.discovery.

Supports name/title/url/topic modes. doi/arxiv/github_url return 400.
executor=agent:web-access creates planned runs only (no real web search).
agent results can only be backfilled via POST /api/discovery/runs/{run_id}/hits.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from collector import discovery

router = APIRouter()


# ---- Pydantic bodies ----

class PlanBody(BaseModel):
    mode: str
    name: str = ""
    title: str = ""
    known_url: str = ""
    topic_id: str | None = None
    artifact_type_hint: str = "unknown"
    max_results: int = 20
    prefer_official: bool = True
    allow_general_web: bool = True


class RunBody(BaseModel):
    mode: str
    input: dict
    plan: dict | None = None
    executor: str = "python"
    topic_id: str | None = None


class HitBackfillItem(BaseModel):
    url: str = ""
    title: str = ""
    query: str = ""
    source_type: str = "web"
    snippet: str = ""
    artifact_type_hint: str = "unknown"
    confidence: str = "medium"
    reason: str = ""
    raw_json: dict | None = None
    primary_source: str = "unknown"
    content_type: str = "unknown"
    verification_status: str = "unverified"
    doi: str = ""
    arxiv_id: str = ""


class AcceptBody(BaseModel):
    review_note: str = ""


class RejectBody(BaseModel):
    review_note: str = ""


class BatchAcceptBody(BaseModel):
    hit_ids: list[str]
    review_note: str = ""


class CompleteBody(BaseModel):
    status: Literal["succeeded", "failed"]
    error: str | None = None


class CompositePlanBody(BaseModel):
    topic_id: str | None = None
    names: list[str] = []
    titles: list[str] = []
    authors: list[str] = []
    institutions: list[str] = []
    keywords: list[str] = []
    known_urls: list[str] = []
    preferred_domains: list[str] = []
    exclude_terms: list[str] = []
    artifact_type_hint: str = "unknown"
    max_results: int = 20
    freeform_note: str = ""


# ---- Endpoints ----

@router.post("/discovery/plan")
def plan(body: PlanBody):
    """Generate a search plan. Pure rule-based, no network."""
    try:
        # Resolve topic if topic_id given
        topic_name = ""
        topic_keywords = []
        topic_known_names = []
        topic_known_titles = []
        if body.topic_id:
            from collector import topics
            t = topics.get(body.topic_id)
            if not t:
                raise HTTPException(404, f"topic not found: {body.topic_id}")
            topic_name = t.get("name", "")
            qd = t.get("query_def") or {}
            topic_keywords = qd.get("keywords", [])
            topic_known_names = qd.get("known_names", [])
            topic_known_titles = qd.get("known_titles", [])

        plan_result = discovery.draft_search_plan(
            mode=body.mode,
            name=body.name,
            title=body.title,
            known_url=body.known_url,
            topic_id=body.topic_id,
            topic_name=topic_name,
            topic_keywords=topic_keywords,
            topic_known_names=topic_known_names,
            topic_known_titles=topic_known_titles,
            artifact_type_hint=body.artifact_type_hint,
            max_results=body.max_results,
            prefer_official=body.prefer_official,
            allow_general_web=body.allow_general_web,
        )
        return plan_result
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/discovery/composite-plan")
def composite_plan(body: CompositePlanBody):
    """Generate a composite search plan from multiple input signals.

    Combines names, titles, authors, institutions, keywords, and known_urls
    into a structured search plan with dedup guidance. Pure rule-based.
    """
    try:
        plan_result = discovery.draft_composite_plan(
            topic_id=body.topic_id,
            names=body.names if body.names else None,
            titles=body.titles if body.titles else None,
            authors=body.authors if body.authors else None,
            institutions=body.institutions if body.institutions else None,
            keywords=body.keywords if body.keywords else None,
            known_urls=body.known_urls if body.known_urls else None,
            preferred_domains=body.preferred_domains if body.preferred_domains else None,
            exclude_terms=body.exclude_terms if body.exclude_terms else None,
            artifact_type_hint=body.artifact_type_hint,
            max_results=body.max_results,
            freeform_note=body.freeform_note,
        )
        return plan_result
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/discovery/run")
def run(body: RunBody):
    """Create a discovery run. Does NOT execute search.

    When executor='agent:web-access', returns planned status with hits_created=0.
    When executor='manual' and mode='url', synchronously creates a manual_url hit.
    """
    try:
        # Validate mode
        if body.mode in discovery.UNSUPPORTED_MODES:
            raise HTTPException(
                400,
                f"mode '{body.mode}' discovery is not supported in V1.1. "
                f"Use /intake/collect for arxiv/github."
            )

        run_result = discovery.create_discovery_run(
            mode=body.mode,
            input_json=body.input,
            search_plan_json=body.plan or {},
            executor=body.executor,
            collection_topic_id=body.topic_id,
        )

        # For manual URL mode, synchronously create a hit
        hits = []
        if body.executor == "manual" and body.mode == "url":
            url = body.input.get("url", "").strip()
            if not url:
                url = body.input.get("known_url", "").strip()
            if url:
                r = discovery.insert_discovery_hit(
                    run_id=run_result["id"],
                    url=url,
                    title=body.input.get("title", ""),
                    query=url,
                    source_type="manual_url",
                    reason="manual URL submission",
                    confidence="medium",
                )
                hits.append(r)

        return {
            "run_id": run_result["id"],
            "status": run_result["status"],
            "hits_created": len([h for h in hits if h.get("status") == "created"]),
            "hits": hits,
        }
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/discovery/runs")
def list_runs(
    topic_id: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    return discovery.list_discovery_runs(
        topic_id=topic_id, status=status, page=page, per_page=per_page
    )


@router.get("/discovery/runs/{run_id}")
def get_run(run_id: str):
    run = discovery.get_discovery_run(run_id)
    if not run:
        raise HTTPException(404, f"run not found: {run_id}")
    return run


@router.get("/discovery/hits")
def list_hits(
    run_id: str | None = Query(None),
    review_status: str | None = Query(None),
    source_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    return discovery.list_discovery_hits(
        run_id=run_id, review_status=review_status, source_type=source_type,
        page=page, per_page=per_page,
    )


@router.post("/discovery/runs/{run_id}/hits")
def backfill_hits(run_id: str, hits: list[HitBackfillItem]):
    """Agent/web-access backfill endpoint. Creates hits for a run.

    Deduplicates by run_id + dedup_key.
    Each hit must have at least url or title.
    """
    run = discovery.get_discovery_run(run_id)
    if not run:
        raise HTTPException(404, f"run not found: {run_id}")

    hit_dicts = [h.model_dump() for h in hits]
    results = discovery.batch_insert_hits(run_id=run_id, hits=hit_dicts)

    created = sum(1 for r in results if r.get("status") == "created")
    skipped = sum(1 for r in results if r.get("status") == "skipped_dup")
    errors = [r for r in results if r.get("status") == "error"]

    # Any created hit ⇒ run produced results ⇒ mark succeeded (P0-1).
    # Covers both 'planned' (stale single-call) and 'running' (insert already
    # flipped it). Zero-hit backfills leave status alone; agent calls /complete.
    if created > 0:
        discovery.update_run_status(run_id, status="succeeded")

    return {
        "run_id": run_id,
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "results": results,
    }


@router.post("/discovery/runs/{run_id}/complete")
def complete_run(run_id: str, body: CompleteBody):
    """Mark a discovery run terminal (succeeded/failed).

    Use after agent backfill to signal done, or to record a run that yielded
    no hits / was aborted. Hits already inserted are preserved.
    """
    try:
        discovery.complete_run(run_id, status=body.status, error=body.error)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "run_id": run_id, "status": body.status}


@router.post("/discovery/hits/{hit_id}/accept")
def accept_hit(hit_id: str, body: AcceptBody):
    """Accept a discovery hit into intake_candidates."""
    try:
        result = discovery.accept_hit_to_intake(hit_id, review_note=body.review_note)
        return result
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.post("/discovery/hits/{hit_id}/reject")
def reject_hit_endpoint(hit_id: str, body: RejectBody):
    """Reject a discovery hit."""
    try:
        result = discovery.reject_hit(hit_id, review_note=body.review_note)
        return result
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.post("/discovery/hits/batch-accept")
def batch_accept(body: BatchAcceptBody):
    """Batch accept hits into intake_candidates."""
    if not body.hit_ids:
        raise HTTPException(400, "hit_ids is required and must be non-empty")
    return discovery.batch_accept_hits(body.hit_ids, review_note=body.review_note)
