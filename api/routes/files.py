"""Files API routes - serve PDFs and content.md."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse

from ..db import get_conn

router = APIRouter()
LIBRARY_ROOT = Path(__file__).resolve().parents[2]


@router.get("/files/{work_id}/content")
def get_content(work_id: str):
    conn = get_conn()
    try:
        run = conn.execute(
            "SELECT content_md_path FROM literature_parse_runs WHERE work_id = ? AND status = 'succeeded' LIMIT 1",
            (work_id,),
        ).fetchone()
        if not run or not run["content_md_path"]:
            raise HTTPException(status_code=404, detail="No parsed content found")

        md_path = Path(run["content_md_path"])
        if not md_path.exists():
            raise HTTPException(status_code=404, detail="Content file not found")

        return PlainTextResponse(md_path.read_text(encoding="utf-8"))
    finally:
        conn.close()


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

        pdf_path = Path(source["source_path"])
        if not pdf_path.exists():
            raise HTTPException(status_code=404, detail="PDF file not found on disk")

        return FileResponse(
            str(pdf_path),
            media_type="application/pdf",
            filename=pdf_path.name,
        )
    finally:
        conn.close()
