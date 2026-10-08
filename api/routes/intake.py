"""Intake (collector A2 review) API routes. Thin adapters over collector core.

Single-nucleus: this module writes no business logic. Candidate reads are inline
SQL (matching the metadata.py read pattern); every state change delegates to
collector.candidate_store / collector.gate / collector.ingest_bridge / collector.topics.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from pydantic import BaseModel

from ..db import get_conn, LIBRARY_ROOT
from collector import candidate_store, gate, ingest_bridge, topics
from collector.collect import collect_once

router = APIRouter()

RESOLUTIONS = (
    "pending", "new", "exact_hit", "title_candidate",
    "needs_better_copy", "sha256_duplicate", "fetch_failed",
)

DUPLICATE_RESOLUTIONS = {"exact_hit", "title_candidate", "needs_better_copy", "sha256_duplicate"}


@router.get("/intake/candidates")
def list_candidates(
    resolution: str | None = Query(None),
    review_status: str | None = Query(None),
    topic: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: str = Query(""),
):
    conn = get_conn()
    try:
        where, params = [], []
        if resolution:
            where.append("ic.resolution = ?"); params.append(resolution)
        if review_status:
            where.append("ic.review_status = ?"); params.append(review_status)
        if topic:
            where.append("ic.collection_topic_id = ?"); params.append(topic)
        if search:
            where.append("(ic.title LIKE ? OR ic.arxiv_id LIKE ? OR ic.id LIKE ?)")
            s = f"%{search}%"
            params.extend([s, s, s])
        where_clause = ("WHERE " + " AND ".join(where)) if where else ""

        total = conn.execute(
            f"SELECT COUNT(*) FROM intake_candidates ic {where_clause}", params
        ).fetchone()[0]

        offset = (page - 1) * per_page
        rows = conn.execute(
            f"""SELECT ic.*, ct.name AS topic_name
                FROM intake_candidates ic
                LEFT JOIN collection_topics ct ON ct.id = ic.collection_topic_id
                {where_clause}
                ORDER BY ic.collected_at DESC NULLS LAST
                LIMIT ? OFFSET ?""",
            params + [per_page, offset],
        ).fetchall()

        candidates = []
        for r in rows:
            d = dict(r)
            if d.get("raw_meta"):
                try:
                    d["raw_meta"] = json.loads(d["raw_meta"])
                except (json.JSONDecodeError, TypeError):
                    pass
            candidates.append(d)
        return {"candidates": candidates, "total": total, "page": page, "per_page": per_page}
    finally:
        conn.close()


@router.get("/intake/stats")
def intake_stats():
    conn = get_conn()
    try:
        resolution = {r: 0 for r in RESOLUTIONS}
        for row in conn.execute(
            "SELECT resolution, COUNT(*) n FROM intake_candidates GROUP BY resolution"
        ).fetchall():
            resolution[row["resolution"]] = row["n"]
        review = {s: 0 for s in candidate_store.VALID_REVIEW}
        for row in conn.execute(
            "SELECT review_status, COUNT(*) n FROM intake_candidates GROUP BY review_status"
        ).fetchall():
            review[row["review_status"]] = row["n"]
        return {
            "resolution": resolution,
            "review": review,
            "total": conn.execute("SELECT COUNT(*) FROM intake_candidates").fetchone()[0],
        }
    finally:
        conn.close()


class ResolveBody(BaseModel):
    ids: list[str] | None = None
    limit: int | None = None


@router.post("/intake/resolve")
def intake_resolve(body: ResolveBody):
    """Trigger the heavy (SHA256) gate. Delegates entirely to gate.resolve_pending."""
    results = gate.resolve_pending(ids=body.ids, limit=body.limit)
    return {
        "resolved": len(results),
        "results": [{"id": cid, "resolution": res} for cid, res in results],
    }


class ReviewBody(BaseModel):
    review_status: str
    note: str | None = None


@router.patch("/intake/candidates/{candidate_id}/review")
def review_candidate(candidate_id: str, body: ReviewBody):
    if body.review_status not in candidate_store.VALID_REVIEW:
        raise HTTPException(400, f"review_status must be one of {sorted(candidate_store.VALID_REVIEW)}")
    try:
        candidate_store.set_review_status(candidate_id, body.review_status, note=body.note)
    except KeyError:
        raise HTTPException(404, f"candidate not found: {candidate_id}")
    return {"ok": True, "id": candidate_id, "review_status": body.review_status}


class PromoteBody(BaseModel):
    ids: list[str]


@router.post("/intake/promote")
def promote_candidates(body: PromoteBody):
    """A2 batch promote → only review_status='approved' candidates are promoted,
    via ingest_bridge (single nucleus). Collector never writes works directly.
    Returns per-id results; a single failure does not abort the batch.

    The approved-guard enforces the human review gate: programmatic callers
    cannot bypass A2 by promoting pending/rejected candidates directly."""
    if not body.ids:
        raise HTTPException(400, "ids is required and must be non-empty")
    # A2 guard: resolve which of the requested ids are actually approved.
    conn = get_conn()
    try:
        placeholders = ",".join("?" * len(body.ids))
        rows = conn.execute(
            f"SELECT id, status, review_status, resolution, matched_work_id, "
            f"ingested_work_id, local_pdf_path "
            f"FROM intake_candidates WHERE id IN ({placeholders})",
            list(body.ids),
        ).fetchall()
        row_map = {r["id"]: dict(r) for r in rows}
    finally:
        conn.close()

    promoted, failed = [], []
    for cid in body.ids:
        info = row_map.get(cid)
        if not info:
            failed.append({"id": cid, "error": f"candidate not found: {cid}"})
            continue
        # Idempotency: if already ingested with a work_id, return it
        if info["status"] == "ingested" and info.get("ingested_work_id"):
            promoted.append({"id": cid, "work_id": info["ingested_work_id"], "already_ingested": True})
            continue
        if info["status"] == "ingested" and not info.get("ingested_work_id"):
            failed.append({"id": cid, "error": "status=ingested but no ingested_work_id (409 conflict)"})
            continue

    # Re-check: only pass truly non-ingested approved candidates to ingest_bridge
    conn = get_conn()
    try:
        non_ingested_ids = [cid for cid in body.ids
                           if cid in row_map
                           and row_map[cid]["status"] != "ingested"]
        if non_ingested_ids:
            ph = ",".join("?" * len(non_ingested_ids))
            approved = {
                r["id"] for r in conn.execute(
                    f"SELECT id FROM intake_candidates "
                    f"WHERE id IN ({ph}) AND review_status='approved'",
                    list(non_ingested_ids),
                ).fetchall()
            }
        else:
            approved = set()
    finally:
        conn.close()

    for cid in body.ids:
        if cid not in row_map:
            continue  # already handled above
        if row_map[cid]["status"] == "ingested":
            continue  # already handled above
        if cid not in approved:
            failed.append({"id": cid, "error": "not approved (review_status != 'approved')"})
            continue
        current_resolution = row_map[cid].get("resolution")
        if current_resolution == "new" and row_map[cid].get("local_pdf_path"):
            # Final safety check: the library may have changed since PDF download.
            current_resolution = gate.heavy_gate(cid)
        if current_resolution != "new":
            if current_resolution in DUPLICATE_RESOLUTIONS:
                failed.append({
                    "id": cid,
                    "error": (
                        f"duplicate candidate cannot be promoted "
                        f"(resolution={current_resolution}, "
                        f"matched_work_id={row_map[cid].get('matched_work_id')})"
                    ),
                })
            else:
                failed.append({
                    "id": cid,
                    "error": f"candidate is not ready for promotion (resolution={current_resolution})",
                })
            continue
        try:
            work_id = ingest_bridge.promote(cid, library_root=LIBRARY_ROOT)
            promoted.append({"id": cid, "work_id": work_id})
        except Exception as e:  # noqa: BLE001 — batch must not abort on one failure
            failed.append({"id": cid, "error": str(e)})
    return {"promoted": promoted, "failed": failed}


@router.get("/intake/topics")
def intake_topics(map_status: str | None = Query(None), lifecycle: str | None = Query(None)):
    return {"topics": topics.list_topics(map_status=map_status, lifecycle=lifecycle)}


class TopicTransitionBody(BaseModel):
    id: str
    to_map_status: str | None = None
    to_lifecycle: str | None = None
    mapped_tags: list | None = None
    proposed_note: str | None = None


@router.post("/intake/topics")
def intake_topics_transition(body: TopicTransitionBody):
    """Maturity transition (seedling→proposed→mapped). Delegates to topics.transition;
    collector never writes the ontology vocab — it only records intent/mapping."""
    try:
        updated = topics.transition(
            body.id,
            to_map_status=body.to_map_status,
            to_lifecycle=body.to_lifecycle,
            mapped_tags=body.mapped_tags,
            proposed_note=body.proposed_note,
        )
    except KeyError:
        raise HTTPException(404, f"topic not found: {body.id}")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "topic": updated}


class CollectBody(BaseModel):
    topic_id: str | None = None
    explicit_ids: list[str] | None = None
    seed_paper_ids: list[str] | None = None
    github_urls: list[str] | None = None


@router.post("/intake/collect")
def intake_collect(body: CollectBody):
    """按主题/显式 ID/种子/GitHub 发起一次采集（委托 collect_once 单一 nucleus）。

    触达网络。UI 的'按主题发起一次采集'入口；持续 loop 留 CLI。零编排逻辑——
    全部委托 collector.collect.collect_once（§2 单核）。
    """
    if not (body.topic_id or body.explicit_ids or body.seed_paper_ids or body.github_urls):
        raise HTTPException(400, "provide topic_id / explicit_ids / seed_paper_ids / github_urls")
    try:
        result = collect_once(topic_id=body.topic_id, explicit_ids=body.explicit_ids,
                              seed_paper_ids=body.seed_paper_ids, github_urls=body.github_urls)
    except ValueError as e:  # unknown topic 等
        raise HTTPException(400, str(e))
    return result


class TopicCreateBody(BaseModel):
    name: str
    description: str = ""
    seed_paper_ids: list[str] | None = None
    explicit_ids: list[str] | None = None
    query_def: dict | None = None  # P1-3: rich discovery clues
    axis_hint: str | None = None
    mapped_tags: list[dict] | None = None


@router.post("/intake/topics/create")
def intake_topics_create(body: TopicCreateBody):
    """Create a new collection topic. Defaults to seedling/active."""
    try:
        ct = topics.create(
            name=body.name,
            description=body.description,
            seed_paper_ids=body.seed_paper_ids,
            explicit_ids=body.explicit_ids,
            query_def=body.query_def,
            axis_hint=body.axis_hint,
            mapped_tags=body.mapped_tags,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "topic": ct}


class TopicQueryDefBody(BaseModel):
    patch: dict


@router.patch("/intake/topics/{topic_id}/query-def")
def intake_topics_patch_query_def(topic_id: str, body: TopicQueryDefBody):
    """P1-3: Merge patch keys into topic.query_def."""
    try:
        qd = topics.update_query_def(topic_id, body.patch)
    except KeyError as e:
        raise HTTPException(404, str(e))
    return {"ok": True, "topic_id": topic_id, "query_def": qd}


@router.post("/intake/candidates/{candidate_id}/upload-pdf")
async def upload_candidate_pdf(candidate_id: str, file: UploadFile = File(...)):
    """为候选记录手动绑定 PDF（用于非 arXiv 来源或 agent 上传的场景）。

    流程：
      1. 保存 PDF 到 _collector_cache/
      2. 更新 candidate.local_pdf_path
      3. 计算 SHA256 并查重（与 heavy_gate 同逻辑）
      4. 返回 resolution（new / sha256_duplicate）
    """
    from scripts.literature_ingest import sha256_file, utc_now

    # 验证候选存在
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM intake_candidates WHERE id=?", (candidate_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"candidate not found: {candidate_id}")
        candidate = dict(row)
    finally:
        conn.close()

    # 验证文件类型
    filename = file.filename or "upload.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(400, "仅支持 PDF 文件")

    # 保存到 _collector_cache
    cache_dir = os.path.join(LIBRARY_ROOT, "_collector_cache")
    os.makedirs(cache_dir, exist_ok=True)
    dest = Path(cache_dir) / f"{candidate_id}.pdf"

    try:
        with open(dest, "wb") as f:
            while chunk := await file.read(1024 * 64):
                f.write(chunk)
    except Exception as e:
        raise HTTPException(500, f"文件保存失败: {e}")

    # 计算 SHA256 并查重
    try:
        digest = sha256_file(dest) if hasattr(sha256_file, '__call__') else _sha256_fallback(dest)
    except Exception as e:
        raise HTTPException(500, f"SHA256 计算失败: {e}")

    conn = get_conn()
    try:
        hit = conn.execute("SELECT 1 FROM source_files WHERE content_sha256=?", (digest,)).fetchone()
        resolution = "sha256_duplicate" if hit else "new"

        rel_path = os.path.relpath(dest, LIBRARY_ROOT).replace("\\", "/")
        now = utc_now() if callable(utc_now) else ""
        conn.execute(
            """UPDATE intake_candidates SET local_pdf_path=?, fetched_sha256=?,
               resolution=?, resolved_at=? WHERE id=?""",
            (rel_path, digest, resolution, now, candidate_id),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "ok": True,
        "id": candidate_id,
        "local_pdf_path": rel_path,
        "fetched_sha256": digest,
        "resolution": resolution,
    }


def _sha256_fallback(path: str) -> str:
    """SHA256 计算的纯 Python fallback（不依赖 ingest 模块）。"""
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
