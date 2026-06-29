import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from api.task_manage import Task, get_task_manager, get_uploads_dir
from config import config
from core.convert.convert_to_pdf import Convert2PDF

logger = logging.getLogger(__name__)

DOC_FILE_EXTS = {".pdf", ".doc", ".docx", ".xlsx", ".xls", ".ppt", ".csv", ".pptx", ".wps"}
XML_FILE_EXTS = {".xml", ".html", ".htm", ".mhtml"}
INVALID_NAME_RE = re.compile(r"[^\u4e00-\u9fffA-Za-z0-9]+")


@dataclass
class SubmitResult:
    task_id: str
    filename: str
    file_path: str
    status: str
    task: Task | None


def sanitize_filename(name: str) -> str:
    if not name:
        raise ValueError("filename is empty")

    stem = INVALID_NAME_RE.sub("_", Path(name).stem).strip("_")
    suffix = Path(name).suffix.lower()
    if stem in (".", "..") or not stem:
        raise ValueError("invalid filename after sanitize")
    return f"{stem}{suffix}"


def extract_filename_from_extra(extra_data: str | None) -> str:
    if not extra_data:
        return ""

    try:
        extra = json.loads(extra_data)
    except Exception:
        return ""

    if not isinstance(extra, dict):
        return ""

    for key in ("filename", "file_name", "name"):
        value = extra.get(key)
        if isinstance(value, str):
            return value
    return ""


def parse_metadata(value: str | None) -> dict[str, Any]:
    if not value:
        return {}

    try:
        parsed = json.loads(value)
    except Exception:
        return {"note": value}

    if isinstance(parsed, dict):
        return parsed
    return {"value": parsed}


def _create_task(
    task_id: str,
    original_path: Path,
    file_path: Path,
    task_dir: Path,
    filename: str,
    *,
    backend: str = "",
    parse_method: str = "",
    metadata: dict[str, Any] | None = None,
) -> Task:
    return Task(
        task_id=task_id,
        original_file_path=str(original_path.resolve()),
        file_path=str(file_path.resolve()),
        dir=str(task_dir.resolve()),
        file_name=filename,
        status="pending",
        time_create=str(int(time.time_ns())),
        backend=backend or config.parse_backend,
        parse_method=parse_method or config.parse_method,
        artifact_dir=str(task_dir.resolve()),
        metadata=metadata or {},
    )


def _submit_doc_file(
    upload_dir: Path,
    original_path: Path,
    task_id: str,
    filename: str,
    content: bytes,
    *,
    backend: str = "",
    parse_method: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    manager = get_task_manager()
    try:
        upload_dir.mkdir(parents=True, exist_ok=True)
        if not original_path.exists():
            original_path.write_bytes(content)

        pdf_path = Convert2PDF.convert(original_path)
        existing = manager.get_task(task_id)
        if existing is not None:
            return

        task = _create_task(
            task_id,
            original_path,
            pdf_path,
            upload_dir,
            filename,
            backend=backend,
            parse_method=parse_method,
            metadata=metadata,
        )
        if manager.mineru_op.is_parsed(upload_dir):
            task.status = "succeeded"
            task.time_finish = str(int(time.time_ns()))
            manager.refresh_task_artifacts(task)
            manager.set_task(task_id, task)
            return

        manager.set_task(task_id, task)
        manager.mineru_op.push_task(
            1,
            pdf_path,
            lambda ok, path, msg="", tid=task_id: manager.update_task_record(ok, path, tid, msg),
            backend=backend,
            parse_method=parse_method,
        )
    except Exception as exc:
        logger.exception("submit doc error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _submit_xml_file(
    upload_dir: Path,
    original_path: Path,
    task_id: str,
    filename: str,
    content: bytes,
    *,
    backend: str = "",
    parse_method: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    manager = get_task_manager()
    try:
        file_type = original_path.suffix.lower().lstrip(".")
        upload_dir.mkdir(parents=True, exist_ok=True)
        if not original_path.exists():
            original_path.write_bytes(content)

        if manager.get_task(task_id) is not None:
            return

        task = _create_task(
            task_id,
            original_path,
            original_path,
            upload_dir,
            filename,
            backend=backend,
            parse_method=parse_method,
            metadata=metadata,
        )
        if manager.xml_op.is_parsed(upload_dir):
            task.status = "succeeded"
            task.time_finish = str(int(time.time_ns()))
            manager.refresh_task_artifacts(task)
            manager.set_task(task_id, task)
            return

        manager.set_task(task_id, task)
        manager.xml_op.push_task(
            str(original_path.resolve()),
            file_type,
            task_id,
            manager.update_task_record,
        )
    except Exception as exc:
        logger.exception("submit xml error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def submit_file(
    content: bytes,
    raw_name: str,
    *,
    extra_data: str | None = None,
    backend: str = "",
    parse_method: str = "",
    metadata: dict[str, Any] | None = None,
) -> SubmitResult:
    if not raw_name:
        raw_name = extract_filename_from_extra(extra_data)

    try:
        filename = sanitize_filename(raw_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    suffix = Path(filename).suffix.lower()
    if suffix not in DOC_FILE_EXTS and suffix not in XML_FILE_EXTS:
        raise HTTPException(status_code=400, detail=f"unsupported file type: {suffix or '<none>'}")

    manager = get_task_manager()
    task_id = manager.make_task_id(content, filename)
    upload_dir = get_uploads_dir() / task_id
    original_path = upload_dir / filename

    if suffix in DOC_FILE_EXTS:
        _submit_doc_file(
            upload_dir,
            original_path,
            task_id,
            filename,
            content,
            backend=backend,
            parse_method=parse_method,
            metadata=metadata,
        )
    else:
        _submit_xml_file(
            upload_dir,
            original_path,
            task_id,
            filename,
            content,
            backend=backend,
            parse_method=parse_method,
            metadata=metadata,
        )

    task = manager.get_task(task_id)
    return SubmitResult(
        task_id=task_id,
        filename=filename,
        file_path=task.file_path if task else "",
        status=task.status if task else "pending",
        task=task,
    )
