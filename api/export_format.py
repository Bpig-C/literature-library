"""Export formatting helpers (pure functions, no DB access).

阶段一出口侧最小闭环：BibTeX / RIS / 综述矩阵 CSV。
数据源约束由调用方（api/routes/export.py）保证：只传入"元数据已批准且未隔离"的 work。
"""

from __future__ import annotations

import csv
import io
import json

# primary_doc_type（含旧 doc_type 回退）→ BibTeX entry 类型
_BIBTEX_TYPE = {
    "research_article": "article",
    "survey_review": "article",
    "paper": "article",  # 旧 doc_type 回退
    "benchmark_dataset_paper": "inproceedings",
    "evaluation_report": "techreport",
    "institutional_report": "techreport",
    "technical_report": "techreport",
    "platform_snapshot": "techreport",
    "system_model_card": "techreport",
    "thesis": "phdthesis",
    "book_chapter": "incollection",
    "governance_framework": "misc",
    "standard_guideline": "misc",
    "webpage_blog": "misc",
    "workflow_artifact": "misc",
    "other_literature": "misc",
    "not_literature": "misc",
}

# BibTeX entry 类型 → RIS TY
_RIS_TYPE = {
    "article": "JOUR",
    "inproceedings": "CONF",
    "incollection": "CHAP",
    "techreport": "RPRT",
    "phdthesis": "THES",
    "misc": "GEN",
}

# venue 字段名按 entry 类型区分
_VENUE_FIELD = {
    "article": "journal",
    "inproceedings": "booktitle",
    "incollection": "booktitle",
    "techreport": "institution",
    "phdthesis": "school",
}

# BibTeX 特殊字符转义（顺序敏感：反斜杠必须最先处理）
_BIBTEX_SPECIAL = [
    ("\\", r"\textbackslash{}"),
    ("$", r"\$"),
    ("%", r"\%"),
    ("&", r"\&"),
    ("#", r"\#"),
    ("_", r"\_"),
    ("^", r"{\textasciicircum}"),
    ("~", r"{\textasciitilde}"),
    ("{", r"\{"),
    ("}", r"\}"),
]


def _escape_bibtex(text: str) -> str:
    for k, v in _BIBTEX_SPECIAL:
        text = text.replace(k, v)
    return text


def parse_authors(raw: str | None) -> list[str]:
    """authors 字段统一解析为作者名列表。

    真实存储形态为 JSON 数组字符串（如 '["A", "B"]'）；
    兼容逗号/分号分隔的纯字符串；解析失败回退为单元素列表。
    """
    if not raw:
        return []
    raw = raw.strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            arr = json.loads(raw)
            if isinstance(arr, list):
                return [str(a).strip() for a in arr if str(a).strip()]
        except (ValueError, TypeError):
            pass
    for sep in (";", ","):
        if sep in raw:
            return [p.strip() for p in raw.split(sep) if p.strip()]
    return [raw]


def _entry_type(work: dict) -> str:
    key = (work.get("primary_doc_type") or work.get("doc_type") or "").strip()
    return _BIBTEX_TYPE.get(key, "misc")


def work_to_bibtex(work: dict) -> str:
    """单篇 work → BibTeX 条目。key = work id（稳定可追溯）。"""
    etype = _entry_type(work)
    fields: list[tuple[str, str]] = []

    title = (work.get("title") or work.get("title_zh") or "").strip()
    if title:
        fields.append(("title", "{{" + _escape_bibtex(title) + "}}"))

    authors = parse_authors(work.get("authors"))
    if authors:
        fields.append(("author", " and ".join(_escape_bibtex(a) for a in authors)))

    if work.get("year"):
        fields.append(("year", str(work["year"])))

    venue = (work.get("venue") or "").strip()
    if venue:
        venue_field = _VENUE_FIELD.get(etype, "howpublished")
        fields.append((venue_field, _escape_bibtex(venue)))

    if (work.get("doi") or "").strip():
        fields.append(("doi", work["doi"].strip()))
    if (work.get("arxiv_id") or "").strip():
        fields.append(("eprint", work["arxiv_id"].strip()))
        fields.append(("archiveprefix", "arXiv"))
    if (work.get("url") or "").strip():
        fields.append(("url", work["url"].strip()))
    if (work.get("abstract") or "").strip():
        fields.append(("abstract", _escape_bibtex(work["abstract"].strip())))

    body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields)
    return f"@{etype}{{{work['id']},\n{body}\n}}"


def work_to_ris(work: dict, tags: dict[str, list[str]] | None = None) -> str:
    """单篇 work → RIS 记录。"""
    etype = _entry_type(work)
    lines = [f"TY  - {_RIS_TYPE.get(etype, 'GEN')}"]

    title = (work.get("title") or work.get("title_zh") or "").strip()
    if title:
        lines.append(f"TI  - {title}")
    for a in parse_authors(work.get("authors")):
        lines.append(f"AU  - {a}")
    if work.get("year"):
        lines.append(f"PY  - {work['year']}")
    venue = (work.get("venue") or "").strip()
    if venue:
        lines.append(f"JO  - {venue}")
    if (work.get("doi") or "").strip():
        lines.append(f"DO  - {work['doi'].strip()}")
    if (work.get("arxiv_id") or "").strip():
        lines.append(f"EP  - {work['arxiv_id'].strip()}")
    if (work.get("url") or "").strip():
        lines.append(f"UR  - {work['url'].strip()}")
    if (work.get("abstract") or "").strip():
        lines.append(f"AB  - {work['abstract'].strip()}")
    for kw in (tags or {}).get("method_tags", []):
        lines.append(f"KW  - {kw}")
    lines.append(f"ID  - {work['id']}")
    lines.append("ER  - ")
    return "\n".join(lines)


MATRIX_COLUMNS = [
    "work_id", "标题", "中文标题", "作者", "年份", "venue", "DOI", "arXiv", "URL",
    "类型", "语言", "方法标签", "风险域", "artifact_focus", "优先级", "核心文献", "一句话定位",
]

_FORMULA_PREFIXES = ("=", "+", "-", "@")


def _cell(value) -> str:
    """CSV 单元格清洗：防 Excel 公式注入（以 = + - @ 开头的值前置单引号）。"""
    s = str(value or "")
    if s.startswith(_FORMULA_PREFIXES):
        return "'" + s
    return s


def works_to_matrix_csv(rows: list[dict]) -> str:
    """汇总行（含 tags/digest 的 work 字典）→ 综述矩阵 CSV（utf-8-sig，Excel 中文兼容）。"""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(MATRIX_COLUMNS)
    for r in rows:
        tags = r.get("tags") or {}
        writer.writerow([
            _cell(r.get("id")),
            _cell(r.get("title")),
            _cell(r.get("title_zh")),
            _cell("; ".join(parse_authors(r.get("authors")))),
            _cell(r.get("year")),
            _cell(r.get("venue")),
            _cell(r.get("doi")),
            _cell(r.get("arxiv_id")),
            _cell(r.get("url")),
            _cell(r.get("primary_doc_type") or r.get("doc_type")),
            _cell(r.get("language")),
            _cell("; ".join(tags.get("method_tags", []))),
            _cell("; ".join(tags.get("risk_domain", []))),
            _cell("; ".join(tags.get("artifact_focus", []))),
            _cell(r.get("priority")),
            "是" if r.get("is_core_literature") else "",
            _cell(r.get("one_sentence_positioning")),
        ])
    return "\ufeff" + buf.getvalue()
