# collector/discovery.py
"""V1.1 Constrained Discovery core: plan generation, run/hit lifecycle, accept-to-intake.

BOUNDARY: discovery hits never write to `works`. The only bridge to intake is
`accept_hit_to_intake`, which creates an intake_candidate with resolution='pending'.
No PDF download. No promote. No ingest_bridge call.

V1.1 scope: name / title / url / topic plan only.
doi / arxiv_id / github_url discovery are explicitly unsupported.
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from urllib.parse import urlparse

from api.db import get_conn

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_MODES = {"name", "title", "url", "topic"}
UNSUPPORTED_MODES = {"doi", "arxiv_id", "github_url", "arxiv", "github"}
VALID_EXECUTORS = {"python", "agent:web-access", "manual"}
VALID_RUN_STATUSES = {"planned", "running", "succeeded", "failed"}
VALID_REVIEW_STATUSES = {"pending", "accepted", "rejected"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row) -> dict:
    """Convert a sqlite3.Row to a dict reliably."""
    if row is None:
        return None
    return {col: row[col] for col in row.keys()}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(4)}"


def _canonicalize_url(url: str) -> str:
    if not url:
        return ""
    try:
        p = urlparse(url)
        scheme = (p.scheme or "").lower()
        netloc = (p.netloc or "").lower()
        path = (p.path or "").rstrip("/")
        return f"{scheme}://{netloc}{path}"
    except Exception:
        return url.rstrip("/")


def _make_dedup_key(*, url: str = "", title: str = "", doi: str = "", arxiv_id: str = "") -> str:
    """Build a dedup key from available identifiers. Prefers strong IDs."""
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    if doi:
        return f"doi:{doi.lower()}"
    if url:
        return f"url:{_canonicalize_url(url)}"
    if title:
        return f"title:{title.strip().lower()}"
    return ""


# ---------------------------------------------------------------------------
# Plan generation
# ---------------------------------------------------------------------------

def draft_search_plan(
    *,
    mode: str,
    name: str = "",
    title: str = "",
    known_url: str = "",
    topic_id: str | None = None,
    topic_name: str = "",
    topic_keywords: list[str] | None = None,
    topic_known_names: list[str] | None = None,
    topic_known_titles: list[str] | None = None,
    artifact_type_hint: str = "unknown",
    max_results: int = 20,
    prefer_official: bool = True,
    allow_general_web: bool = True,
) -> dict:
    """Generate a search plan from user input. Pure rule-based, no network.

    Returns a plan dict with: mode, queries, sources, domains, exclude_terms,
    max_results, acceptance_criteria.

    Raises ValueError for unsupported modes (doi/arxiv/github).
    """
    if mode in UNSUPPORTED_MODES:
        raise ValueError(
            f"mode '{mode}' discovery is not supported in V1.1. "
            f"Use existing /intake/collect for arxiv/github, or wait for V1.2 doi support."
        )
    if mode not in VALID_MODES:
        raise ValueError(f"invalid mode '{mode}'; allowed: {sorted(VALID_MODES)}")

    if mode == "topic" and topic_id and not (
        topic_name or topic_keywords or topic_known_names or topic_known_titles
    ):
        from collector import topics
        topic = topics.get(topic_id)
        if topic is None:
            raise KeyError(f"topic not found: {topic_id}")
        topic_name = topic.get("name", "")
        query_def = topic.get("query_def") or {}
        topic_keywords = query_def.get("keywords") or []
        topic_known_names = query_def.get("known_names") or []
        topic_known_titles = query_def.get("known_titles") or []

    plan: dict = {
        "mode": mode,
        "queries": [],
        "sources": [],
        "domains": [],
        "exclude_terms": ["reddit", "forum", "news"],
        "max_results": max(1, min(max_results, 100)),
        "acceptance_criteria": [
            "official or primary source preferred",
            "document-like artifact required",
            "must preserve source URL and reason",
        ],
    }

    if mode == "name":
        q = f'"{name.strip()}"' if name.strip() else name.strip()
        plan["queries"] = [q] if q else []
        plan["sources"] = ["official_domain", "web"]
        if artifact_type_hint in ("system_card", "model_card", "technical_report"):
            plan["sources"] = ["official_domain", "web", "github", "huggingface"]
        if allow_general_web:
            if "web" not in plan["sources"]:
                plan["sources"].append("web")

    elif mode == "title":
        q = f'"{title.strip()}"' if title.strip() else title.strip()
        plan["queries"] = [q] if q else []
        plan["sources"] = ["openalex", "crossref", "semantic_scholar", "web"]
        if prefer_official:
            plan["sources"] = ["openalex", "crossref", "semantic_scholar", "official_domain", "web"]

    elif mode == "url":
        plan["queries"] = [known_url.strip()] if known_url.strip() else []
        plan["sources"] = ["manual_url"]

    elif mode == "topic":
        queries = []
        if topic_name:
            queries.append(topic_name)
        for kw in (topic_keywords or []):
            if kw and kw not in queries:
                queries.append(kw)
        for kn in (topic_known_names or []):
            if kn and kn not in queries:
                queries.append(kn)
        for kt in (topic_known_titles or []):
            if kt and kt not in queries:
                queries.append(f'"{kt}"')
        plan["queries"] = queries
        plan["sources"] = ["web", "official_domain"]
        if topic_known_titles:
            plan["sources"] = ["openalex", "crossref", "semantic_scholar", "web", "official_domain"]

    return plan


# ---------------------------------------------------------------------------
# Run management
# ---------------------------------------------------------------------------

def create_discovery_run(
    *,
    mode: str,
    input_json: dict,
    search_plan_json: dict,
    executor: str = "python",
    collection_topic_id: str | None = None,
) -> dict:
    """Create a new discovery run. Returns the run dict.

    When executor='agent:web-access', status='planned' (agent backfills later).
    When executor='manual' and mode='url', caller should separately insert_hit.
    """
    if mode in UNSUPPORTED_MODES:
        raise ValueError(
            f"mode '{mode}' discovery is not supported in V1.1. "
            f"Use existing /intake/collect for arxiv/github."
        )
    if mode not in VALID_MODES:
        raise ValueError(f"invalid mode '{mode}'")
    if executor not in VALID_EXECUTORS:
        raise ValueError(f"invalid executor '{executor}'; allowed: {sorted(VALID_EXECUTORS)}")

    run_id = _new_id("DR")
    now = _now()
    status = "planned"

    run = {
        "id": run_id,
        "collection_topic_id": collection_topic_id,
        "mode": mode,
        "input_json": input_json,
        "search_plan_json": search_plan_json,
        "executor": executor,
        "status": status,
        "error": None,
        "hits_created": 0,
        "created_at": now,
        "updated_at": now,
    }

    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO discovery_runs
               (id, collection_topic_id, mode, input_json, search_plan_json,
                executor, status, error, hits_created, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (run["id"], run["collection_topic_id"], run["mode"],
             json.dumps(run["input_json"], ensure_ascii=False),
             json.dumps(run["search_plan_json"], ensure_ascii=False),
             run["executor"], run["status"], run["error"], run["hits_created"],
             run["created_at"], run["updated_at"]),
        )
        conn.commit()
    finally:
        conn.close()

    return run


def update_run_status(run_id: str, *, status: str, error: str | None = None) -> None:
    """Update run status. Raises KeyError if run not found."""
    if status not in VALID_RUN_STATUSES:
        raise ValueError(f"invalid status '{status}'")
    conn = get_conn()
    try:
        cur = conn.execute("SELECT id FROM discovery_runs WHERE id=?", (run_id,))
        if not cur.fetchone():
            raise KeyError(f"run not found: {run_id}")
        conn.execute(
            "UPDATE discovery_runs SET status=?, error=?, updated_at=? WHERE id=?",
            (status, error, _now(), run_id),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Hit insertion
# ---------------------------------------------------------------------------

def insert_discovery_hit(
    *,
    run_id: str,
    url: str = "",
    title: str = "",
    query: str = "",
    source_type: str = "web",
    snippet: str = "",
    artifact_type_hint: str = "unknown",
    confidence: str = "medium",
    reason: str = "",
    raw_json: dict | None = None,
    collection_topic_id: str | None = None,
    primary_source: str = "unknown",
    content_type: str = "unknown",
    verification_status: str = "unverified",
    doi: str = "",
    arxiv_id: str = "",
) -> dict:
    """Insert a single discovery hit. Dedup by run_id + dedup_key.

    Returns {id, status} where status is 'created' or 'skipped_dup'.
    """
    if not url and not title:
        raise ValueError("hit must have at least url or title")

    canonical_url = _canonicalize_url(url) if url else ""
    dedup_key = _make_dedup_key(url=url, title=title, doi=doi, arxiv_id=arxiv_id)

    conn = get_conn()
    try:
        # Check run exists
        run_row = conn.execute(
            "SELECT collection_topic_id FROM discovery_runs WHERE id=?", (run_id,)
        ).fetchone()
        if not run_row:
            raise KeyError(f"run not found: {run_id}")

        if collection_topic_id is None and run_row[0]:
            collection_topic_id = run_row[0]

        # Dedup within same run
        if dedup_key:
            existing = conn.execute(
                "SELECT id FROM discovery_hits WHERE run_id=? AND dedup_key=?",
                (run_id, dedup_key),
            ).fetchone()
            if existing:
                return {"id": existing[0], "status": "skipped_dup"}

        hit_id = _new_id("DH")
        now = _now()

        conn.execute(
            """INSERT INTO discovery_hits
               (id, run_id, collection_topic_id, query, source_type, url, canonical_url,
                title, snippet, artifact_type_hint, confidence, reason, raw_json,
                dedup_key, candidate_id, review_status, review_note, primary_source,
                content_type, verification_status, observed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (hit_id, run_id, collection_topic_id, query, source_type, url, canonical_url,
             title, snippet, artifact_type_hint, confidence, reason,
             json.dumps(raw_json, ensure_ascii=False) if raw_json else None,
             dedup_key, None, "pending", None, primary_source,
             content_type, verification_status, now),
        )

        # Update run's hits_created count
        conn.execute(
            "UPDATE discovery_runs SET hits_created = hits_created + 1, updated_at=? WHERE id=?",
            (now, run_id),
        )
        conn.commit()
        return {"id": hit_id, "status": "created"}
    finally:
        conn.close()


def batch_insert_hits(
    *,
    run_id: str,
    hits: list[dict],
) -> list[dict]:
    """Insert multiple hits for a run. Returns list of {id, status} per hit.

    Each hit dict should have at minimum: url or title.
    Optional: query, source_type, snippet, artifact_type_hint, confidence, reason,
    raw_json, primary_source, content_type, verification_status.
    """
    results = []
    for h in hits:
        try:
            r = insert_discovery_hit(
                run_id=run_id,
                url=h.get("url", ""),
                title=h.get("title", ""),
                query=h.get("query", ""),
                source_type=h.get("source_type", "web"),
                snippet=h.get("snippet", ""),
                artifact_type_hint=h.get("artifact_type_hint", "unknown"),
                confidence=h.get("confidence", "medium"),
                reason=h.get("reason", ""),
                raw_json=h.get("raw_json"),
                primary_source=h.get("primary_source", "unknown"),
                content_type=h.get("content_type", "unknown"),
                verification_status=h.get("verification_status", "unverified"),
            )
            results.append(r)
        except (ValueError, KeyError) as e:
            results.append({"id": None, "status": "error", "error": str(e)})
    return results


# ---------------------------------------------------------------------------
# Query functions
# ---------------------------------------------------------------------------

def list_discovery_runs(
    *,
    topic_id: str | None = None,
    status: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> dict:
    """List discovery runs with optional filters. Returns {runs, total, page, per_page}."""
    conn = get_conn()
    try:
        where, params = [], []
        if topic_id:
            where.append("collection_topic_id=?"); params.append(topic_id)
        if status:
            where.append("status=?"); params.append(status)
        where_clause = ("WHERE " + " AND ".join(where)) if where else ""

        total = conn.execute(
            f"SELECT COUNT(*) FROM discovery_runs {where_clause}", params
        ).fetchone()[0]

        offset = (page - 1) * per_page
        rows = conn.execute(
            f"SELECT * FROM discovery_runs {where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()

        runs = []
        for r in rows:
            d = _row_to_dict(r)
            for field in ("input_json", "search_plan_json"):
                if d.get(field):
                    try:
                        d[field] = json.loads(d[field])
                    except (json.JSONDecodeError, TypeError):
                        pass
            runs.append(d)

        return {"runs": runs, "total": total, "page": page, "per_page": per_page}
    finally:
        conn.close()


def get_discovery_run(run_id: str) -> dict | None:
    """Get a single run by id, or None."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM discovery_runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            return None
        d = _row_to_dict(row)
        for field in ("input_json", "search_plan_json"):
            if d.get(field):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d
    finally:
        conn.close()


def list_discovery_hits(
    *,
    run_id: str | None = None,
    review_status: str | None = None,
    source_type: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """List discovery hits with optional filters. Returns {hits, total, page, per_page}."""
    conn = get_conn()
    try:
        where, params = [], []
        if run_id:
            where.append("run_id=?"); params.append(run_id)
        if review_status:
            where.append("review_status=?"); params.append(review_status)
        if source_type:
            where.append("source_type=?"); params.append(source_type)
        where_clause = ("WHERE " + " AND ".join(where)) if where else ""

        total = conn.execute(
            f"SELECT COUNT(*) FROM discovery_hits {where_clause}", params
        ).fetchone()[0]

        offset = (page - 1) * per_page
        rows = conn.execute(
            f"SELECT * FROM discovery_hits {where_clause} ORDER BY observed_at DESC LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()

        hits = []
        for r in rows:
            d = _row_to_dict(r)
            if d.get("raw_json"):
                try:
                    d["raw_json"] = json.loads(d["raw_json"])
                except (json.JSONDecodeError, TypeError):
                    pass
            hits.append(d)

        return {"hits": hits, "total": total, "page": page, "per_page": per_page}
    finally:
        conn.close()


def get_discovery_hit(hit_id: str) -> dict | None:
    """Get a single hit by id, or None."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM discovery_hits WHERE id=?", (hit_id,)).fetchone()
        if not row:
            return None
        d = _row_to_dict(row)
        if d.get("raw_json"):
            try:
                d["raw_json"] = json.loads(d["raw_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        return d
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Accept hit to intake
# ---------------------------------------------------------------------------

def accept_hit_to_intake(
    hit_id: str,
    *,
    review_note: str = "",
) -> dict:
    """Accept a discovery hit into intake_candidates.

    - Creates or reuses an intake_candidate (via candidate_store.insert_candidate).
    - Sets resolution='pending' (not auto-promoted).
    - Does NOT download PDF. Does NOT call ingest_bridge.promote.
    - Backfills hit.candidate_id and sets hit.review_status='accepted'.

    Returns {candidate_id, hit_id, status} where status is 'created' or 'skipped_dup'.

    Raises KeyError if hit not found.
    """
    from collector.candidate_store import insert_candidate

    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM discovery_hits WHERE id=?", (hit_id,)).fetchone()
        if not row:
            raise KeyError(f"hit not found: {hit_id}")

        hit = _row_to_dict(row)

        if hit.get("review_status") == "accepted" and hit.get("candidate_id"):
            return {
                "candidate_id": hit["candidate_id"],
                "hit_id": hit_id,
                "status": "already_accepted",
            }

        # Build raw_meta for the intake candidate
        raw_meta = {
            "discovery_hit_id": hit["id"],
            "discovery_run_id": hit["run_id"],
            "query": hit.get("query", ""),
            "source_type": hit.get("source_type", ""),
            "artifact_type_hint": hit.get("artifact_type_hint", ""),
            "primary_source": hit.get("primary_source", ""),
            "content_type": hit.get("content_type", ""),
            "verification_status": hit.get("verification_status", ""),
            "reason": hit.get("reason", ""),
            "snippet": hit.get("snippet", ""),
        }

        # Determine source_type for intake
        intake_source_type = hit.get("source_type", "web")
        if intake_source_type in ("official_domain", "manual_url"):
            intake_source_type = "web"

        cid, status = insert_candidate(
            source_type=intake_source_type,
            url_canonical=hit.get("canonical_url") or hit.get("url", ""),
            arxiv_id=None,  # V1.1 discovery hits don't carry arxiv_id
            doi=None,       # V1.1 discovery hits don't carry doi
            title=hit.get("title"),
            raw_meta=raw_meta,
            collection_topic_id=hit.get("collection_topic_id"),
        )

        now = _now()
        # Backfill hit
        conn.execute(
            """UPDATE discovery_hits
               SET candidate_id=?, review_status='accepted', review_note=?, observed_at=?
               WHERE id=?""",
            (cid, review_note or None, now, hit_id),
        )
        conn.commit()

        return {"candidate_id": cid, "hit_id": hit_id, "status": status}
    finally:
        conn.close()


def reject_hit(hit_id: str, *, review_note: str = "") -> dict:
    """Reject a discovery hit. Sets review_status='rejected'.

    Returns {ok, hit_id, review_status}.
    Raises KeyError if hit not found.
    """
    conn = get_conn()
    try:
        row = conn.execute("SELECT id FROM discovery_hits WHERE id=?", (hit_id,)).fetchone()
        if not row:
            raise KeyError(f"hit not found: {hit_id}")
        conn.execute(
            "UPDATE discovery_hits SET review_status='rejected', review_note=? WHERE id=?",
            (review_note or None, hit_id),
        )
        conn.commit()
        return {"ok": True, "hit_id": hit_id, "review_status": "rejected"}
    finally:
        conn.close()


def batch_accept_hits(hit_ids: list[str], *, review_note: str = "") -> dict:
    """Batch accept hits. Returns {accepted, failed} lists."""
    accepted, failed = [], []
    for hid in hit_ids:
        try:
            hit = get_discovery_hit(hid)
            if not hit:
                raise KeyError(f"hit not found: {hid}")
            if not hit.get("url"):
                failed.append({
                    "hit_id": hid,
                    "error": "title-only hits cannot be batch accepted in V1.1",
                })
                continue
            r = accept_hit_to_intake(hid, review_note=review_note)
            accepted.append(r)
        except KeyError as e:
            failed.append({"hit_id": hid, "error": str(e)})
        except Exception as e:  # noqa: BLE001
            failed.append({"hit_id": hid, "error": str(e)})
    return {"accepted": accepted, "failed": failed}
