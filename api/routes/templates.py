"""Template management API routes.

Provides unified read/write access to three core template assets:
  1. Metadata extraction field definitions (editable)
  2. Classification vocabulary tables (read-only, write endpoint reserved)
  3. Discovery search protocol (read-only, write endpoint reserved)

All customizations are persisted in templates/templates.json.
Missing sections fall back to built-in defaults.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import LIBRARY_ROOT

router = APIRouter()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

TEMPLATES_DIR = LIBRARY_ROOT / "templates"
TEMPLATES_FILE = TEMPLATES_DIR / "templates.json"
BACKUPS_DIR = TEMPLATES_DIR / "backups"
MAX_BACKUPS = 5

# ---------------------------------------------------------------------------
# Built-in defaults (source of truth when no customization exists)
# ---------------------------------------------------------------------------

BUILTIN_METADATA_FIELDS = [
    {
        "key": "title",
        "label": "标题",
        "type": "text",
        "rules": "非空字符串，去除首尾空白",
        "description": "文献主标题（通常来自 PDF 首页或元数据区）"
    },
    {
        "key": "title_zh",
        "label": "中文标题",
        "type": "text",
        "rules": "可为空；存在则优先用于中文检索索引",
        "description": "中文译名或并列中文标题"
    },
    {
        "key": "publication_date",
        "label": "发布日期",
        "type": "date-object",
        "rules": "{year, month, day, raw, kind} 或 null; year 为 4 位数字",
        "description": "出版/发布日期，含原始字符串和结构化分量"
    },
    {
        "key": "authors",
        "label": "作者",
        "type": "author-list",
        "rules": "列表，最多 5 个；每项 {name, affiliations?}",
        "description": "主要作者列表（按原文顺序）"
    },
    {
        "key": "contributors",
        "label": "贡献方",
        "type": "contributor-list",
        "rules": "列表；每项 {name, type, role?}; type ∈ {company, lab, org, other}",
        "description": "机构/团队贡献者（公司、实验室等）"
    },
    {
        "key": "doi",
        "label": "DOI",
        "type": "text",
        "rules": "正则 ^10\\.\\d{4,}/.+ 或 null",
        "description": "数字对象标识符。格式不符则置 null"
    },
    {
        "key": "arxiv_id",
        "label": "arXiv ID",
        "type": "text",
        "rules": "正则 ^\\d{4}\\.\\d{4,5}(v\\d+)?$ 或 null",
        "description": "arXiv 论文编号（如 2212.08073）"
    },
    {
        "key": "venue",
        "label": "发表 venue",
        "type": "text",
        "rules": "自由文本或 null",
        "description": "会议/期刊名称（如 NeurIPS 2023, JMLR）"
    },
    {
        "key": "url",
        "label": "主页 URL",
        "type": "text",
        "rules": "合法 http(s) URL 或 null",
        "description": "文献官方页面或 PDF 直链"
    },
    {
        "key": "abstract",
        "label": "摘要",
        "type": "textarea",
        "rules": "多行文本，建议 ≤ 2000 字",
        "description": "论文摘要全文"
    },
]

BUILTIN_INTERNAL_FIELDS = [
    {"key": "evidence", "description": "抽取证据片段（从 content.md 定位到的原文）"},
    {"key": "confidence", "description": "置信度 high/medium/low（模型自评）"},
    {"key": "missing", "description": "无法抽取的字段名列表及原因"},
    {"key": "all_authors", "description": "完整作者列表（可能 > 5 人）"},
]

VALID_FIELD_TYPES = {"text", "date-object", "author-list", "contributor-list", "textarea", "list"}
BUILTIN_METADATA_KEYS = {f["key"] for f in BUILTIN_METADATA_FIELDS}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_dirs() -> None:
    """Create templates directories if missing."""
    TEMPLATES_DIR.mkdir(exist_ok=True)
    BACKUPS_DIR.mkdir(exist_ok=True)


def _load_custom() -> dict:
    """Load templates.json or return empty dict."""
    if TEMPLATES_FILE.exists():
        try:
            with open(TEMPLATES_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_custom(data: dict) -> None:
    """Atomically write templates.json."""
    _ensure_dirs()
    tmp = TEMPLATES_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(TEMPLATES_FILE)  # atomic on most OS


def _backup_section(section: str) -> str | None:
    """Backup current section before overwriting. Returns backup path."""
    _ensure_dirs()
    custom = _load_custom()
    section_data = custom.get(section)
    if not section_data:
        return None
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    fname = f"{section}-{ts}.json"
    path = BACKUPS_DIR / fname
    with open(path, "w", encoding="utf-8") as f:
        json.dump(section_data, f, ensure_ascii=False, indent=2)
    # Prune old backups
    existing = sorted(BACKUPS_DIR.glob(f"{section}-*.json"))
    for old in existing[:-MAX_BACKUPS]:
        old.unlink()
    return str(path)


def _cleanup_backups(section: str, keep: int = MAX_BACKUPS) -> None:
    """Remove oldest backups beyond keep limit."""
    existing = sorted(BACKUPS_DIR.glob(f"{section}-*.json"))
    for old in existing[:-keep]:
        old.unlink()


def _get_classification_vocab() -> dict:
    """Load classification vocab from the canonical source."""
    try:
        from ..classification_vocab import VOCAB, VOCAB_VERSIONS
        return {
            "vocab": dict(VOCAB),
            "versions": dict(VOCAB_VERSIONS),
        }
    except ImportError:
        return {"vocab": {}, "versions": {}}


def _get_discovery_protocol() -> dict:
    """Extract discovery protocol summary from the markdown doc."""
    proto_file = LIBRARY_ROOT / "docs" / "discovery-agent-protocol.md"
    if not proto_file.exists():
        return {"raw": "", "error": "Protocol file not found"}
    stat = proto_file.stat()
    text = proto_file.read_text(encoding="utf-8")
    # Return structured summary + raw text (trimmed for payload size)
    return {
        "filename": proto_file.name,
        "path": str(proto_file.relative_to(LIBRARY_ROOT)),
        "size_bytes": stat.st_size,
        "lines": text.count("\n"),
        "modified_iso": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "raw": text[:15000],  # first ~15KB — enough for preview
        "truncated": len(text) > 15000,
    }


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base. Lists are replaced, dicts merged recursively."""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _validate_metadata_fields(fields: list) -> list[str]:
    """Validate metadata fields. Returns list of error messages."""
    errors = []
    keys_seen = set()
    for i, f in enumerate(fields):
        if not isinstance(f, dict):
            errors.append(f"[{i}] 不是对象")
            continue
        for req in ("key", "label", "type"):
            if req not in f or not f[req]:
                errors.append(f"[{i}] 缺少必填字段 '{req}'")
        key = f.get("key", "")
        if key in keys_seen:
            errors.append(f"[{i}] 重复的 key: {key}")
        keys_seen.add(key)
        if f.get("type") and f["type"] not in VALID_FIELD_TYPES:
            errors.append(f"[{i}] 无效类型: {f['type']}")
    return errors


# ---------------------------------------------------------------------------
# Endpoints: Read
# ---------------------------------------------------------------------------


@router.get("/templates")
async def get_templates():
    """Return all three template sections, merging user customizations with defaults."""
    custom = _load_custom()

    # --- Metadata ---
    meta_custom = custom.get("metadata", {})
    meta_default = {
        "version": "1.0",
        "fields": list(BUILTIN_METADATA_FIELDS),
        "internal_fields": list(BUILTIN_INTERNAL_FIELDS),
    }
    metadata = _deep_merge(meta_default, meta_custom)

    # Ensure fields still contains all builtin keys (user can't delete them, only hide)
    existing_keys = {f["key"] for f in metadata.get("fields", [])}
    for bf in BUILTIN_METADATA_FIELDS:
        if bf["key"] not in existing_keys:
            metadata.setdefault("fields", []).insert(
                list(BUILTIN_METADATA_FIELDS).index(bf), bf
            )

    # --- Classification ---
    cls_custom = custom.get("classification", {})
    cls_data = _get_classification_vocab()
    classification = _deep_merge(cls_data, cls_custom)

    # --- Discovery ---
    disc_custom = custom.get("discovery", {})
    disc_data = _get_discovery_protocol()
    discovery = _deep_merge(disc_data, disc_custom)

    # --- Meta info ---
    customized = [k for k in ("metadata", "classification", "discovery") if k in custom]
    last_mod = None
    if TEMPLATES_FILE.exists():
        last_mod = datetime.fromtimestamp(
            TEMPLATES_FILE.stat().st_mtime, tz=timezone.utc
        ).isoformat()

    return {
        "_meta": {
            "has_customizations": bool(custom),
            "last_modified": last_mod,
            "customized_sections": customized,
        },
        "metadata": metadata,
        "classification": classification,
        "discovery": discovery,
    }


@router.get("/templates/metadata/schema")
async def get_metadata_schema():
    """Return pure built-in schema (no user customizations applied)."""
    return {
        "version": "1.0",
        "valid_types": list(VALID_FIELD_TYPES),
        "builtin_keys": list(BUILTIN_METADATA_KEYS),
        "fields": list(BUILTIN_METADATA_FIELDS),
        "internal_fields": list(BUILTIN_INTERNAL_FIELDS),
    }


@router.get("/templates/classification/raw")
async def get_classification_raw():
    """Return raw classification vocab dictionary."""
    return _get_classification_vocab()


# ---------------------------------------------------------------------------
# Endpoints: Write — Metadata (active)
# ---------------------------------------------------------------------------


class MetadataSaveBody(BaseModel):
    version: str = "1.1"
    fields: list[dict]
    _note: str = ""


@router.post("/templates/metadata")
async def save_metadata_template(body: MetadataSaveBody):
    """Save modified metadata field definitions.

    Validates structure, creates backup, writes to templates.json.
    """
    errors = _validate_metadata_fields(body.fields)
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})

    # Backup current
    backup_path = _backup_section("metadata")

    # Load existing custom, update metadata section
    custom = _load_custom()
    custom["metadata"] = {
        "version": body.version,
        "modified_at": datetime.now(timezone.utc).isoformat(),
        "fields": body.fields,
    }

    # Validate written JSON is parseable
    try:
        _save_custom(custom)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"写入失败: {e}")

    # Verify
    verify = _load_custom()
    if not verify.get("metadata"):
        raise HTTPException(status_code=500, detail="写入后验证失败")

    return {
        "ok": True,
        "saved_at": custom["metadata"]["modified_at"],
        "field_count": len(body.fields),
        "backup": backup_path,
    }


@router.post("/templates/metadata/reset")
async def reset_metadata_template():
    """Reset metadata to built-in defaults (removes customization)."""
    # Backup before reset
    backup_path = _backup_section("metadata")

    custom = _load_custom()
    if "metadata" in custom:
        del custom["metadata"]
        _save_custom(custom)

    return {
        "ok": True,
        "reset_at": datetime.now(timezone.utc).isoformat(),
        "note": "已恢复为内置默认值",
        "backup": backup_path,
    }


# ---------------------------------------------------------------------------
# Endpoints: Write — Classification (reserved, implemented but not exposed in UI)
# ---------------------------------------------------------------------------


@router.post("/templates/classification")
async def save_classification_template(body: dict):
    """Save modified classification vocabulary. Reserved for future use."""

    # Basic validation: must be a dict of string → list[string]
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="必须是 JSON 对象")

    # Load valid keys from classification_vocab
    try:
        from ..classification_vocab import VOCAB as VALID_VOCAB
        valid_keys = set(VALID_VOCAB.keys())
    except (ImportError, AttributeError):
        valid_keys = set()

    for k, v in body.items():
        if valid_keys and k not in valid_keys:
            raise HTTPException(
                status_code=422,
                detail=f"未知的词汇分组: {k}。允许的键: {sorted(valid_keys)}",
            )
        if not isinstance(v, list) or not all(isinstance(item, str) for item in v):
            raise HTTPException(
                status_code=422,
                detail=f"'{k}' 必须是字符串列表",
            )

    backup_path = _backup_section("classification")

    custom = _load_custom()
    custom["classification"] = {
        "version": "1.0",
        "modified_at": datetime.now(timezone.utc).isoformat(),
        "vocab_overrides": body,
    }
    _save_custom(custom)

    return {
        "ok": True,
        "saved_at": custom["classification"]["modified_at"],
        "groups_updated": list(body.keys()),
        "backup": backup_path,
        "warning": (
            "⚠️ 前端 labels.js 需要同步更新。"
            "请确认后检查分类审核页面的标签显示是否一致。"
        ),
    }


# ---------------------------------------------------------------------------
# Endpoints: Write — Discovery (reserved, implemented but not exposed in UI)
# ---------------------------------------------------------------------------


@router.post("/templates/discovery")
async def save_discovery_template(body: dict):
    """Save modified discovery protocol overrides. Reserved for future use."""

    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="必须是 JSON 对象")

    backup_path = _backup_section("discovery")

    custom = _load_custom()
    custom["discovery"] = {
        "version": body.get("protocol_version", "1.0"),
        "modified_at": datetime.now(timezone.utc).isoformat(),
        **body,
    }
    _save_custom(custom)

    return {
        "ok": True,
        "saved_at": custom["discovery"]["modified_at"],
        "backup": backup_path,
    }
