"""Template management API routes.

Provides unified read/write access to three core template assets:
  1. Metadata extraction field definitions (editable)
  2. Classification vocabulary tables (read-only, write endpoint reserved)
  3. Discovery search protocol (read-only, write endpoint reserved)

All customizations are persisted in templates/templates.json.
Missing sections fall back to built-in defaults.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import LIBRARY_ROOT
from ..metadata_template import (
    BUILTIN_INTERNAL_FIELDS,
    BUILTIN_METADATA_FIELDS,
    BUILTIN_METADATA_KEYS,
    TEMPLATES_FILE,
    VALID_FIELD_TYPES,
    backup_template_section,
    deep_merge,
    get_metadata_template,
    load_custom_templates,
    save_custom_templates,
    validate_metadata_fields,
)

router = APIRouter()

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

# ---------------------------------------------------------------------------
# Endpoints: Read
# ---------------------------------------------------------------------------


@router.get("/templates")
async def get_templates():
    """Return all three template sections, merging user customizations with defaults."""
    custom = load_custom_templates()

    # --- Metadata ---
    metadata = get_metadata_template()

    # --- Classification ---
    cls_custom = custom.get("classification", {})
    cls_data = _get_classification_vocab()
    classification = deep_merge(cls_data, cls_custom)

    # --- Discovery ---
    disc_custom = custom.get("discovery", {})
    disc_data = _get_discovery_protocol()
    discovery = deep_merge(disc_data, disc_custom)

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
    errors = validate_metadata_fields(body.fields)
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})

    # Backup current
    backup_path = backup_template_section("metadata")

    # Load existing custom, update metadata section
    custom = load_custom_templates()
    custom["metadata"] = {
        "version": body.version,
        "modified_at": datetime.now(timezone.utc).isoformat(),
        "fields": body.fields,
    }

    # Validate written JSON is parseable
    try:
        save_custom_templates(custom)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"写入失败: {e}")

    # Verify
    verify = load_custom_templates()
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
    backup_path = backup_template_section("metadata")

    custom = load_custom_templates()
    if "metadata" in custom:
        del custom["metadata"]
        save_custom_templates(custom)

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

    backup_path = backup_template_section("classification")

    custom = load_custom_templates()
    custom["classification"] = {
        "version": "1.0",
        "modified_at": datetime.now(timezone.utc).isoformat(),
        "vocab_overrides": body,
    }
    save_custom_templates(custom)

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

    backup_path = backup_template_section("discovery")

    custom = load_custom_templates()
    custom["discovery"] = {
        "version": body.get("protocol_version", "1.0"),
        "modified_at": datetime.now(timezone.utc).isoformat(),
        **body,
    }
    save_custom_templates(custom)

    return {
        "ok": True,
        "saved_at": custom["discovery"]["modified_at"],
        "backup": backup_path,
    }
