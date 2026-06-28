# collector/gate.py
"""Two-stage pre-ingest dedup gate. Reuses literature_ingest normalization + jaccard.

light_gate: metadata-only, decides whether to download. No file IO.
heavy_gate: download (if needed) + SHA256 against source_files.
"""
from __future__ import annotations
import api.db                                       # 惰性读 LIBRARY_ROOT（测试可 patch，避免 import 期绑定真实库目录）
from api.db import get_conn
from collector.fetch import download_pdf
from collector.adapters import arxiv as arxiv_adapter
from collector.normalize import normalize_arxiv_id, normalize_doi
from collector.paths import resolve_pdf_path        # 共享：local_pdf_path 绝对/相对统一解析（gate + ingest_bridge）
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
    """Download-bound SHA256 check. If the candidate has no local PDF yet, derive a PDF URL
    by source and download it (arXiv only in v1) before hashing. Persists local_pdf_path,
    fetched_sha256, resolution, resolved_at. Returns resolution in
    {new, sha256_duplicate, fetch_failed}."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM intake_candidates WHERE id=?", (candidate_id,)).fetchone()
        if not row:
            return "fetch_failed"
        pdf_path = row["local_pdf_path"]

        # —— 补：缺 PDF 先下载（让 download-bound 名副其实）——
        if not pdf_path:
            url = _pdf_url_for(row)
            if not url:
                _set_resolution(conn, candidate_id, "fetch_failed")   # 无可用 PDF 源（如 github v1）
                return "fetch_failed"
            cache_dir = api.db.LIBRARY_ROOT / "_collector_cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            dest = cache_dir / f"{candidate_id}.pdf"
            if not download_pdf(url, dest):
                _set_resolution(conn, candidate_id, "fetch_failed")   # 下载失败要落库
                return "fetch_failed"
            pdf_path = dest.relative_to(api.db.LIBRARY_ROOT).as_posix()  # schema 约定：相对 library root，POSIX 分隔符可移植
            conn.execute("UPDATE intake_candidates SET local_pdf_path=? WHERE id=?",
                         (pdf_path, candidate_id))
            conn.commit()

        # —— SHA256 查 source_files（原逻辑，路径统一经 resolve_pdf_path）——
        resolved = resolve_pdf_path(pdf_path)
        if not resolved.exists():
            _set_resolution(conn, candidate_id, "fetch_failed")
            return "fetch_failed"
        digest = sha256_file(resolved)
        hit = conn.execute("SELECT 1 FROM source_files WHERE content_sha256=?", (digest,)).fetchone()
        resolution = "sha256_duplicate" if hit else "new"
        conn.execute(
            "UPDATE intake_candidates SET fetched_sha256=?, resolution=?, resolved_at=? WHERE id=?",
            (digest, resolution, utc_now(), candidate_id))
        conn.commit()
        return resolution
    finally:
        conn.close()


def _pdf_url_for(row):
    """按候选来源派生 PDF 直链。arxiv 用 arxiv.pdf_url；github v1 不支持（留 follow-up）。"""
    if row["source_type"] == "arxiv" and row["arxiv_id"]:
        return arxiv_adapter.pdf_url(row["arxiv_id"])
    return None


def _set_resolution(conn, candidate_id, resolution):
    """落库 resolution + resolved_at（修掉旧 heavy_gate 缺 PDF 时不落库、resolve 谎报的 bug）。

    fetch_failed 分支同时清掉 fetched_sha256，防止行出现 fetch_failed + 残留非空 sha
    （成功路径的 sha 由 heavy_gate 主 UPDATE 写入，不经此函数）。
    """
    conn.execute(
        "UPDATE intake_candidates SET resolution=?, resolved_at=?, fetched_sha256=NULL WHERE id=?",
        (resolution, utc_now(), candidate_id))
    conn.commit()


def resolve_pending(ids=None, limit=None):
    """Run the heavy (SHA256) gate on candidates. Returns list of (candidate_id, resolution).

    Selection (when ids is None): only candidates whose resolution is
    'new' or 'needs_better_copy' — the ones worth downloading. exact_hit /
    sha256_duplicate need no download.

    This is the single nucleus for resolve scheduling; CLI and API both
    delegate here. heavy_gate manages its own connection and commit.
    """
    conn = get_conn()
    try:
        if ids:
            placeholders = ",".join("?" * len(ids))
            rows = conn.execute(
                f"SELECT id FROM intake_candidates WHERE id IN ({placeholders})", list(ids)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id FROM intake_candidates WHERE resolution IN ('new','needs_better_copy')"
            ).fetchall()
        if limit:
            rows = rows[:limit]
        ids_to_run = [r["id"] for r in rows]
    finally:
        conn.close()
    results = []
    for cid in ids_to_run:
        results.append((cid, heavy_gate(cid)))
    return results
