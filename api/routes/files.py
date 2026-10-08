"""Files API routes - serve PDFs, content.md and parsed images."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse

from ..db import LIBRARY_ROOT, get_conn
from ..storage.runtime import enabled, configured_service
from ..storage.response import PinnedFileResponse

router = APIRouter()
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
def get_content(work_id: str, parse_run_id: str | None = None, source_file_id: str | None = None, version: int | None = None):
    if enabled(): return _stored_parse(work_id,'md','text/plain; charset=utf-8',parse_run_id,source_file_id,version)
    conn = get_conn()
    try:
        run = _selected_local_parse(conn,work_id,parse_run_id,source_file_id,version)
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
def get_work_image(work_id: str, image_name: str, parse_run_id: str | None = None, source_file_id: str | None = None, version: int | None = None):
    """解析产物图片（works/{wid}/parsed/mineru/{sfid}/images/{name}）。

    文件名白名单校验 + works 边界校验（防 DB 投毒路径穿越）。
    """
    if not image_name or ".." in image_name or not _IMAGE_NAME_RE.match(image_name):
        raise HTTPException(status_code=404, detail="Invalid image name")
    if enabled(): return _stored_parse(work_id,'image:'+image_name,_IMAGE_MEDIA_TYPES.get(Path(image_name).suffix.lower(),'application/octet-stream'),parse_run_id,source_file_id,version)
    conn = get_conn()
    try:
        row = _selected_local_parse(conn,work_id,parse_run_id,source_file_id,version)
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


def _latest_parse_output_dir(conn, work_id: str, parse_run_id=None,source_file_id=None,version=None) -> Path:
    """最新一次 succeeded 解析的产物目录；无记录/无目录信息时抛 404。"""
    row = _selected_local_parse(conn,work_id,parse_run_id,source_file_id,version)
    if not row:
        raise HTTPException(status_code=404, detail="No parsed content found")
    base = row["output_dir"] or (
        str(Path(row["content_md_path"]).parent) if row["content_md_path"] else ""
    )
    if not base:
        raise HTTPException(status_code=404, detail="No parse output dir recorded")
    return Path(base)


@router.get("/files/{work_id}/merged")
def get_merged_content(work_id: str, parse_run_id: str | None = None, source_file_id: str | None = None, version: int | None = None):
    """合并版 markdown（旁路资产 content.merged.md；仅 cloud vlm 解析有）。"""
    if enabled(): return _stored_parse(work_id,'merged','text/plain; charset=utf-8',parse_run_id,source_file_id,version)
    conn = get_conn()
    try:
        out_dir = _latest_parse_output_dir(conn, work_id,parse_run_id,source_file_id,version)
    finally:
        conn.close()
    md_path = _validate_library_path(str(out_dir / "content.merged.md"))
    if not md_path.is_file():
        raise HTTPException(status_code=404, detail="No merged content (cloud VLM parse only)")
    return PlainTextResponse(md_path.read_text(encoding="utf-8"), headers=_NO_CACHE)


@router.get("/files/{work_id}/detail")
def get_detail_json(work_id: str, parse_run_id: str | None = None, source_file_id: str | None = None, version: int | None = None):
    """合并诊断 JSON（旁路资产 detail.json，unified_merge_schema v4；溯源用）。"""
    if enabled(): return _stored_parse(work_id,'detail','application/json',parse_run_id,source_file_id,version)
    conn = get_conn()
    try:
        out_dir = _latest_parse_output_dir(conn, work_id,parse_run_id,source_file_id,version)
    finally:
        conn.close()
    detail_path = _validate_library_path(str(out_dir / "detail.json"))
    if not detail_path.is_file():
        raise HTTPException(status_code=404, detail="No detail json (cloud VLM parse only)")
    return FileResponse(str(detail_path), media_type="application/json",
                          headers=_NO_CACHE)


@router.get("/files/{work_id}/pdf")
def get_pdf(work_id: str, source_file_id: str | None = None, version: int | None = None):
    conn = get_conn()
    try:
        if enabled():
            rows=conn.execute('SELECT id FROM source_files WHERE work_id=?'+(' AND id=?' if source_file_id else ''),(work_id,source_file_id) if source_file_id else (work_id,)).fetchall()
            if not rows: raise HTTPException(404,'Source unavailable for this work')
            if len(rows)!=1: raise HTTPException(409,'Select source_file_id for a work with multiple sources')
            service=configured_service();asset=service.registry.binding(rows[0]['id'],'pdf',version)
            return PinnedFileResponse(service.read(rows[0]['id'],'pdf',asset['version']),'application/pdf',_NO_CACHE)
        if version not in {None,1}: raise HTTPException(409,'Immutable storage required for requested asset version')
        source = conn.execute('SELECT source_path FROM source_files WHERE work_id=?'+(' AND id=?' if source_file_id else '')+' LIMIT 1',(work_id,source_file_id) if source_file_id else (work_id,)).fetchone()
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


def _selected_local_parse(conn,work_id,parse_run_id=None,source_file_id=None,version=None):
    if version not in {None,1}:raise HTTPException(409,'Immutable storage required for requested asset version')
    query="SELECT * FROM literature_parse_runs WHERE work_id=? AND status='succeeded'";values=[work_id]
    if parse_run_id:query+=' AND id=?';values.append(parse_run_id)
    if source_file_id:query+=' AND source_file_id=?';values.append(source_file_id)
    return conn.execute(query+' ORDER BY finished_at DESC,id DESC LIMIT 1',values).fetchone()


def _stored_parse(work_id,role,media,parse_run_id=None,source_file_id=None,version=None):
    conn=get_conn()
    try:
        query="SELECT id FROM literature_parse_runs WHERE work_id=? AND status='succeeded'";values=[work_id]
        if parse_run_id:query+=' AND id=?';values.append(parse_run_id)
        if source_file_id:query+=' AND source_file_id=?';values.append(source_file_id)
        query+=' ORDER BY finished_at DESC,id DESC'
        rows=conn.execute(query,values).fetchall()
        if not rows:raise HTTPException(404,'Selected parse version unavailable for this work/source')
        if not parse_run_id and not source_file_id:
            sources=conn.execute("SELECT DISTINCT source_file_id FROM literature_parse_runs WHERE work_id=? AND status='succeeded'",(work_id,)).fetchall()
            if len(sources)>1:raise HTTPException(409,'Select parse_run_id or source_file_id for multiple parsed sources')
        identity=rows[0]['id'];service=configured_service();asset=service.registry.binding(identity,role,version)
        return PinnedFileResponse(service.read(identity,role,asset['version']),media,_NO_CACHE)
    finally:conn.close()

@router.get('/files/{work_id}/selection')
def select_materials(work_id: str,parse_run_id: str | None=None,source_file_id: str | None=None,version: int | None=None):
    """Freeze one explicit run/version before the page fetches MD/images/JSON."""
    conn=get_conn()
    try:
        row=_selected_local_parse(conn,work_id,parse_run_id,source_file_id,None)
        if not row:raise HTTPException(404,'Selected parse record unavailable')
        if not parse_run_id and not source_file_id:
            count=conn.execute("SELECT COUNT(DISTINCT source_file_id) FROM literature_parse_runs WHERE work_id=? AND status='succeeded'",(work_id,)).fetchone()[0]
            if count>1:raise HTTPException(409,'Select a parse_run_id for multiple sources')
        if enabled():actual=configured_service().registry.binding(row['id'],'md',version)['version']
        else:
            if version not in {None,1}:raise HTTPException(409,'Immutable storage required for requested version')
            actual=1
        return {'work_id':work_id,'parse_run_id':row['id'],'source_file_id':row['source_file_id'],'version':actual,'storage_mode':'immutable' if enabled() else 'local'}
    finally:conn.close()

@router.get('/files/{work_id}/pdf-selection')
def select_pdf(work_id: str,source_file_id: str | None=None,version: int | None=None):
    """PDF revision is independent of the selected parse package revision."""
    conn=get_conn()
    try:
        rows=conn.execute('SELECT id FROM source_files WHERE work_id=?'+(' AND id=?' if source_file_id else '')+' ORDER BY id',(work_id,source_file_id) if source_file_id else (work_id,)).fetchall()
        if not rows:raise HTTPException(404,'Source unavailable for this work')
        if len(rows)!=1:raise HTTPException(409,'Select source_file_id for multiple PDF sources')
        if enabled():actual=configured_service().registry.binding(rows[0]['id'],'pdf',version)['version']
        else:
            if version not in {None,1}:raise HTTPException(409,'Immutable storage required for requested PDF version')
            actual=1
        return {'work_id':work_id,'source_file_id':rows[0]['id'],'pdf_version':actual}
    finally:conn.close()
