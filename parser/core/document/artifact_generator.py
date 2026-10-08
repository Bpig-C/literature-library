"""
DocumentArtifactGenerator - 文档产物生成器。
按结果接口分发到各自独立模块，便于后续维护。
"""
import base64
import json
from pathlib import Path

from core.document.annotated_pdf import build_annotated_file_for_pdf
from core.document.content_result import (
    _is_bbox,
    _sort_key,
    _try_build_content_entry,
    build_content_json_for_pdf,
)
from core.document.detail_result import build_detail_pdf_for_pdf
from core.document.layout_result import _bbox_center_dist2, _bbox_inside, build_layout_json_for_pdf
from core.xml.content_json import read_content_result

_PDF_EXT = {".pdf"}
_HTML_EXT = {".html", ".htm", ".mhtml"}


def _artifact_path(source_file_path: str, filename: str) -> Path:
    return Path(source_file_path).with_suffix("") / filename


def _legacy_cache_path(source_file_path: str, filename: str) -> Path:
    return Path(source_file_path).parent / filename


def _load_cached_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_cached_json(path: Path, content) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(content, handle, ensure_ascii=False, indent=2)


def _is_html_result_source(path: Path) -> bool:
    if path.suffix.lower() in _HTML_EXT:
        return True
    if path.suffix.lower() != ".json":
        return False
    return any(path.with_suffix(ext).exists() for ext in _HTML_EXT)


def _unwrap_result(result):
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], bool):
        return result[1]
    return result


def _annotated_fallback(path: Path) -> dict:
    return {
        "file_name": f"{path.stem}_layout.pdf" if path.stem else "",
        "file_type": "pdf",
        "success": False,
        "file_base64": "",
    }


class DocumentArtifactGenerator:
    @staticmethod
    def build_layout_json(source_file_path: str) -> list:
        source_path = Path(source_file_path)
        ext = source_path.suffix.lower()
        content_path = _artifact_path(source_file_path, "file_doc_layout.json")
        legacy_path = _legacy_cache_path(source_file_path, "layout.json")
        for path in (content_path, legacy_path):
            if path.exists():
                return _load_cached_json(path)

        if ext in _PDF_EXT:
            content = build_layout_json_for_pdf(source_path)
            _write_cached_json(content_path, content)
            if not legacy_path.exists():
                _write_cached_json(legacy_path, content)
            return content
        if _is_html_result_source(source_path):
            content = read_content_result(source_file_path)
            _write_cached_json(content_path, content)
            return content
        return []

    @staticmethod
    def build_content_json(source_file_path: str) -> list:
        source_path = Path(source_file_path)
        ext = source_path.suffix.lower()
        content_path = _artifact_path(source_file_path, "file__doc_content_extraction.json")
        if content_path.exists():
            return _load_cached_json(content_path)

        if ext in _PDF_EXT:
            content = build_content_json_for_pdf(source_path)
            _write_cached_json(content_path, content)
            return content
        if _is_html_result_source(source_path):
            content = read_content_result(source_file_path)
            _write_cached_json(content_path, content)
            return content
        return []

    @staticmethod
    def build_annotated_file(source_file_path: str) -> dict:
        path = Path(source_file_path)
        if path.suffix.lower() not in _PDF_EXT:
            return _annotated_fallback(path)

        annotated_name = f"{path.stem}_layout.pdf"
        annotated_path = next(path.parent.rglob(annotated_name), None) if path.parent.exists() else None
        if annotated_path is None:
            return _annotated_fallback(path)

        result = _unwrap_result(build_annotated_file_for_pdf(path))
        if isinstance(result, dict):
            return result

        return {
            "file_name": path.name,
            "annotated_file_name": annotated_path.name,
            "file_type": "pdf",
            "success": True,
            "file_base64": base64.b64encode(annotated_path.read_bytes()).decode(),
        }

    @staticmethod
    def build_detail_pdf(source_file_path: str) -> dict | list:
        path = Path(source_file_path)
        content_path = _artifact_path(source_file_path, "file__doc_detail.json")
        if content_path.exists():
            return _load_cached_json(content_path)
        if path.suffix.lower() in _PDF_EXT:
            content = _unwrap_result(build_detail_pdf_for_pdf(path))
            _write_cached_json(content_path, content)
            return content
        if _is_html_result_source(path):
            content = read_content_result(source_file_path)
            _write_cached_json(content_path, content)
            return content
        return []
