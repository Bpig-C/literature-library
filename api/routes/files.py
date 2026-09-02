"""Files API routes - serve PDFs, content.md and parsed images."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse

from ..db import get_conn

router = APIRouter()
LIBRARY_ROOT = Path(__file__).resolve().parents[2]
_WORKS_ROOT = (LIBRARY_ROOT / "works").resolve()

# 解析产物可被 force reparse 同路径覆盖重写，响应必须每次回源校验，
# 否则浏览器 HTTP 启发式缓存会在重解析后继续展示旧 content/图片。
# no-cache 允许协商缓存（304），不等于 no-store。
_NO_CACHE = {"Cache-Control": "no-cache"}

# 解析产物图片文件名白名单（MinerU 哈希名 / PyMuPDF p001-x123.ext）
_IMAGE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,150}$")
_IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".svg": "image/svg+xml",
}


def _validate_library_path(path_str: str) -> Path:
    """Ensure a DB-sourced path resolves inside LIBRARY_ROOT/works.

    Prevents path traversal and poisoned-DB arbitrary file reads.
    """
    resolved = Path(path_str).resolve()
    if not resolved.is_relative_to(_WORKS_ROOT):
        raise HTTPException(status_code=403, detail="Path outside library boundary")
    return resolved


@router.get("/files/{work_id}/content")
def get_content(work_id: str):
    conn = get_conn()
    try:
        run = conn.execute(
            """SELECT content_md_path FROM literature_parse_runs
               WHERE work_id = ? AND status = 'succeeded'
               ORDER BY finished_at DESC, id DESC LIMIT 1""",
            (work_id,),
        ).fetchone()
        if not run or not run["content_md_path"]:
            raise HTTPException(status_code=404, detail="No parsed content found")

        md_path = _validate_library_path(run["content_md_path"])
        if not md_path.exists():
            raise HTTPException(status_code=404, detail="Content file not found")

        return PlainTextResponse(md_path.read_text(encoding="utf-8"),
                            headers=_NO_CACHE)
    finally:
        conn.close()


@router.get("/files/{work_id}/images/{image_name}")
def get_work_image(work_id: str, image_name: str):
    """解析产物图片（works/{wid}/parsed/mineru/{sfid}/images/{name}）。

    文件名白名单校验 + works 边界校验（防 DB 投毒路径穿越）。
    """
    if not image_name or ".." in image_name or not _IMAGE_NAME_RE.match(image_name):
        raise HTTPException(status_code=404, detail="Invalid image name")
    conn = get_conn()
    try:
        row = conn.execute(
            """SELECT output_dir, content_md_path FROM literature_parse_runs
               WHERE work_id = ? AND status = 'succeeded'
               ORDER BY finished_at DESC, id DESC LIMIT 1""",
            (work_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="No parsed content found")
    base = row["output_dir"] or (
        str(Path(row["content_md_path"]).parent) if row["content_md_path"] else ""
    )
    if not base:
        raise HTTPException(status_code=404, detail="No parse output dir recorded")
    image_path = _validate_library_path(str(Path(base) / "images" / image_name))
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    media = _IMAGE_MEDIA_TYPES.get(image_path.suffix.lower(), "application/octet-stream")
    return FileResponse(str(image_path), media_type=media, headers=_NO_CACHE)


def _latest_parse_output_dir(conn, work_id: str) -> Path:
    """最新一次 succeeded 解析的产物目录；无记录/无目录信息时抛 404。"""
    row = conn.execute(
        """SELECT output_dir, content_md_path FROM literature_parse_runs
           WHERE work_id = ? AND status = 'succeeded'
           ORDER BY finished_at DESC, id DESC LIMIT 1""",
        (work_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No parsed content found")
    base = row["output_dir"] or (
        str(Path(row["content_md_path"]).parent) if row["content_md_path"] else ""
    )
    if not base:
        raise HTTPException(status_code=404, detail="No parse output dir recorded")
    return Path(base)


@router.get("/files/{work_id}/merged")
def get_merged_content(work_id: str):
    """合并版 markdown（旁路资产 content.merged.md；仅 cloud vlm 解析有）。"""
    conn = get_conn()
    try:
        out_dir = _latest_parse_output_dir(conn, work_id)
    finally:
        conn.close()
    md_path = _validate_library_path(str(out_dir / "content.merged.md"))
    if not md_path.is_file():
        raise HTTPException(status_code=404, detail="No merged content (cloud VLM parse only)")
    return PlainTextResponse(md_path.read_text(encoding="utf-8"), headers=_NO_CACHE)


@router.get("/files/{work_id}/detail")
def get_detail_json(work_id: str):
    """合并诊断 JSON（旁路资产 detail.json，unified_merge_schema v4；溯源用）。"""
    conn = get_conn()
    try:
        out_dir = _latest_parse_output_dir(conn, work_id)
    finally:
        conn.close()
    detail_path = _validate_library_path(str(out_dir / "detail.json"))
    if not detail_path.is_file():
        raise HTTPException(status_code=404, detail="No detail json (cloud VLM parse only)")
    return FileResponse(str(detail_path), media_type="application/json",
                          headers=_NO_CACHE)


@router.get("/files/{work_id}/pdf")
def get_pdf(work_id: str):
    conn = get_conn()
    try:
        source = conn.execute(
            "SELECT source_path FROM source_files WHERE work_id = ? LIMIT 1",
            (work_id,),
        ).fetchone()
        if not source or not source["source_path"]:
            raise HTTPException(status_code=404, detail="No source file found")

        pdf_path = _validate_library_path(source["source_path"])
        if not pdf_path.exists():
            raise HTTPException(status_code=404, detail="PDF file not found on disk")

        return FileResponse(
            str(pdf_path),
            media_type="application/pdf",
            content_disposition_type="inline",
            headers=_NO_CACHE,
        )
    finally:
        conn.close()
