"""Shared metadata extraction template loader and prompt builder.

The template management page persists user edits in ``templates/templates.json``.
This module is the runtime bridge: extraction scripts, API routes, and tests all
load the same merged metadata template instead of keeping separate hard-coded
field lists.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import LIBRARY_ROOT

TEMPLATES_DIR = LIBRARY_ROOT / "templates"
TEMPLATES_FILE = TEMPLATES_DIR / "templates.json"
BACKUPS_DIR = TEMPLATES_DIR / "backups"
MAX_BACKUPS = 5

VALID_FIELD_TYPES = {"text", "date-object", "author-list", "contributor-list", "textarea", "list"}

BUILTIN_METADATA_FIELDS = [
    {
        "key": "title",
        "label": "标题",
        "type": "text",
        "rules": "非空字符串，去除首尾空白",
        "description": "文献主标题（通常来自 PDF 首页或元数据区）",
    },
    {
        "key": "title_zh",
        "label": "中文标题",
        "type": "text",
        "rules": "可为空；存在则优先用于中文检索索引",
        "description": "中文译名或并列中文标题；原文不是中文时给出中文翻译，专名不要硬翻译",
    },
    {
        "key": "publication_date",
        "label": "发布日期",
        "type": "date-object",
        "rules": "{year, month, day, raw, kind} 或 null; year 为 4 位数字; kind ∈ {exact, inferred}",
        "description": "出版、发布或提交日期；至少抽取 year，month/day 未找到时为 null",
    },
    {
        "key": "authors",
        "label": "作者",
        "type": "author-list",
        "rules": "个人作者字符串列表，最多 5 个；超过 5 个时前 5 个写 authors，完整列表可写 all_authors",
        "description": "只记录个人姓名，不要把机构、团队、出版社放进 authors",
    },
    {
        "key": "contributors",
        "label": "贡献方",
        "type": "contributor-list",
        "rules": "列表；每项 {name, type, role}; type ∈ {university, company, government, lab, team, standards_body, unknown}; role ∈ {author, publisher, issuer, funder, collaborator}",
        "description": "机构、团队、出版方、资助方等非个人贡献者；技术报告和标准尤其重要",
    },
    {
        "key": "doi",
        "label": "DOI",
        "type": "text",
        "rules": "正则 ^10\\.\\d{4,}/.+ 或 null",
        "description": "数字对象标识符。格式不符或只看到 DOI URL 但无法确认时置 null",
    },
    {
        "key": "arxiv_id",
        "label": "arXiv ID",
        "type": "text",
        "rules": "正则 ^\\d{4}\\.\\d{4,5}(v\\d+)?$ 或 null",
        "description": "arXiv 论文编号，如 2212.08073 或 2212.08073v2",
    },
    {
        "key": "venue",
        "label": "发表 venue",
        "type": "text",
        "rules": "自由文本或 null",
        "description": "会议、期刊、机构、网站或发布平台；技术报告可填发布机构/报告系列",
    },
    {
        "key": "url",
        "label": "主页 URL",
        "type": "text",
        "rules": "合法 http(s) URL 或 null；优先官方页面、arXiv abs、DOI landing、publisher page",
        "description": "不要使用 license、GitHub/GitLab、ORCID、补充材料等非文献主页链接",
    },
    {
        "key": "abstract",
        "label": "摘要",
        "type": "textarea",
        "rules": "多行文本，建议 ≤ 2000 字；没有正式摘要时可写简短 summary",
        "description": "论文摘要或报告概要，必须来自文档内容，不要编造",
    },
]

BUILTIN_INTERNAL_FIELDS = [
    {"key": "evidence", "description": "抽取证据片段（从 content.md 定位到的原文）"},
    {"key": "confidence", "description": "字段级置信度 high/medium/low（模型自评）"},
    {"key": "missing", "description": "无法抽取的字段名列表"},
    {"key": "all_authors", "description": "完整作者列表（可能 > 5 人）"},
]

BUILTIN_METADATA_KEYS = {f["key"] for f in BUILTIN_METADATA_FIELDS}
RERUN_FIELD_ALIASES = {
    "date": "publication_date",
    "institutions": "contributors",
}
APPLY_TO_WORKS_FIELDS = {
    "title": "title",
    "doi": "doi",
    "arxiv_id": "arxiv_id",
    "venue": "venue",
    "url": "url",
    "abstract": "abstract",
    "title_zh": "title_zh",
}


def ensure_template_dirs() -> None:
    TEMPLATES_DIR.mkdir(exist_ok=True)
    BACKUPS_DIR.mkdir(exist_ok=True)


def load_custom_templates() -> dict[str, Any]:
    if TEMPLATES_FILE.exists():
        try:
            return json.loads(TEMPLATES_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_custom_templates(data: dict[str, Any]) -> None:
    ensure_template_dirs()
    tmp = TEMPLATES_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(TEMPLATES_FILE)


def backup_template_section(section: str, keep: int = MAX_BACKUPS) -> str | None:
    ensure_template_dirs()
    custom = load_custom_templates()
    section_data = custom.get(section)
    if not section_data:
        return None
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = BACKUPS_DIR / f"{section}-{ts}.json"
    path.write_text(json.dumps(section_data, ensure_ascii=False, indent=2), encoding="utf-8")
    for old in sorted(BACKUPS_DIR.glob(f"{section}-*.json"))[:-keep]:
        old.unlink()
    return str(path)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def validate_metadata_fields(fields: list[Any]) -> list[str]:
    errors: list[str] = []
    keys_seen: set[str] = set()
    for i, field in enumerate(fields):
        if not isinstance(field, dict):
            errors.append(f"[{i}] 不是对象")
            continue
        for req in ("key", "label", "type"):
            if not field.get(req):
                errors.append(f"[{i}] 缺少必填字段 '{req}'")
        key = str(field.get("key", "")).strip()
        if key in keys_seen:
            errors.append(f"[{i}] 重复的 key: {key}")
        keys_seen.add(key)
        if field.get("type") and field["type"] not in VALID_FIELD_TYPES:
            errors.append(f"[{i}] 无效类型: {field['type']}")
    return errors


def get_metadata_template() -> dict[str, Any]:
    custom = load_custom_templates()
    meta_custom = custom.get("metadata", {})
    meta_default = {
        "version": "1.0",
        "fields": list(BUILTIN_METADATA_FIELDS),
        "internal_fields": list(BUILTIN_INTERNAL_FIELDS),
    }
    metadata = deep_merge(meta_default, meta_custom)

    fields = list(metadata.get("fields") or [])
    existing_keys = {f.get("key") for f in fields if isinstance(f, dict)}
    for index, builtin in enumerate(BUILTIN_METADATA_FIELDS):
        if builtin["key"] not in existing_keys:
            fields.insert(index, builtin)
    metadata["fields"] = fields
    return metadata


def get_metadata_field_keys(template: dict[str, Any] | None = None) -> list[str]:
    metadata = template or get_metadata_template()
    keys: list[str] = []
    for field in metadata.get("fields", []):
        if isinstance(field, dict) and field.get("key"):
            keys.append(str(field["key"]))
    return keys


def normalize_metadata_field_key(field: str) -> str:
    return RERUN_FIELD_ALIASES.get(field, field)


def normalize_metadata_fields(fields: list[str]) -> list[str]:
    normalized: list[str] = []
    for field in fields:
        key = normalize_metadata_field_key(field)
        if key not in normalized:
            normalized.append(key)
    return normalized


def valid_rerun_fields(template: dict[str, Any] | None = None) -> set[str]:
    keys = set(get_metadata_field_keys(template))
    return keys | set(RERUN_FIELD_ALIASES)


def _example_for_field(field: dict[str, Any]) -> Any:
    key = field.get("key")
    field_type = field.get("type")
    if key == "publication_date" or field_type == "date-object":
        return {"year": 2025, "month": None, "day": None, "raw": "2025", "kind": "exact"}
    if key == "authors" or field_type == "author-list":
        return ["Personal Author Name"]
    if key == "contributors" or field_type == "contributor-list":
        return [{"name": "Org Name", "type": "company", "role": "publisher"}]
    if field_type in ("list",):
        return []
    if field_type == "textarea":
        return "full abstract/summary text or null"
    return f"{field.get('label') or key} or null"


def _field_instruction_lines(fields: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for field in fields:
        key = field.get("key")
        if not key:
            continue
        label = field.get("label") or key
        field_type = field.get("type") or "text"
        rules = field.get("rules") or "无额外规则"
        desc = field.get("description") or ""
        lines.append(f"- {key} ({label}, {field_type}): {desc} Rules: {rules}")
    return "\n".join(lines)


def _schema_example(fields: list[dict[str, Any]]) -> dict[str, Any]:
    example = {field["key"]: _example_for_field(field) for field in fields if field.get("key")}
    example["evidence"] = {field["key"]: "snippet from document" for field in fields if field.get("key")}
    example["confidence"] = {field["key"]: "high|medium|low" for field in fields if field.get("key")}
    example["missing"] = []
    return example


def build_metadata_system_prompt(template: dict[str, Any] | None = None) -> str:
    keys = ", ".join(get_metadata_field_keys(template))
    return (
        "/no_think\n"
        "You extract structured metadata from documents (papers, reports, standards, webpages, etc.).\n"
        "Output ONLY valid JSON. No explanations, no markdown, no <think> tags.\n"
        "If information is not found, use null for scalars and [] for arrays.\n"
        'Always include "evidence", "confidence", and "missing" objects.\n'
        'Confidence: "high" = explicitly stated, "medium" = inferred, "low" = guessed.\n'
        f"For missing, list field names that could not be filled from: {keys}."
    )


def build_metadata_user_prompt(text: str, template: dict[str, Any] | None = None) -> str:
    metadata = template or get_metadata_template()
    fields = [f for f in metadata.get("fields", []) if isinstance(f, dict)]
    field_lines = _field_instruction_lines(fields)
    example_json = json.dumps(_schema_example(fields), ensure_ascii=False, indent=2)

    return f"""Extract metadata from this document.

Template version: {metadata.get("version", "1.0")}

Step 1 — Identify the document type (for your reference, do NOT output it):
- research_article: academic paper with authors, abstract, venue
- technical_report: report from a company/lab/team, may have no personal authors
- standard_guideline: published by standards body or government
- webpage_blog: online content, blog post, news article
- survey_review: literature review or meta-analysis
- other: anything else

Step 2 — Apply the active metadata template.

Active fields:
{field_lines}

Common interpretation rules:
- title_zh: Chinese translation if original is not Chinese. Keep proper nouns untranslated. null if uncertain.
- url priority: paper homepage, arXiv abs, DOI landing, publisher page. Never use license URLs, GitHub/GitLab links, ORCID, or supplementary links.
- publication_date: extract year at minimum. Add month/day if found. "raw" is original text, "kind" is "exact" or "inferred".
- authors are personal names only. Put organizations, publishers, labs, teams, funders, and standards bodies in contributors.
- contributors.type must be one of: university, company, government, lab, team, standards_body, unknown.
- contributors.role must be one of: author, publisher, issuer, funder, collaborator.
- Return all active fields even when null/empty; do not invent values.

Output JSON shape:
{example_json}

Document:

{text}"""


def _format_template_for_str_format(prompt: str) -> str:
    escaped = prompt.replace("{", "{{").replace("}", "}}")
    return escaped.replace("{{text}}", "{text}")


USER_PROMPT_TEMPLATE = _format_template_for_str_format(build_metadata_user_prompt("{text}"))
SYSTEM_PROMPT = build_metadata_system_prompt()
