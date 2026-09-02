"""合并旁路资产生成：detail.json（合并诊断）+ content.merged.md（合并版 markdown）。

定位（UX-007 方案C）：**旁路资产，不替换任何原始产物**。content.md（MinerU
full.md）/content.json/images/_raw 一律原样保留；本模块产出的两个新文件用于
前端"合并版"阅读视图与问题溯源对照。

重建规则（以 MinerU 结构为主体，PyMuPDF 结果塞入）：
- heading/paragraph：取合并节点载荷；段落按 content_fragments 重建（保留行内
  公式为 $...$）；无行内公式且带 style_spans 时应用 PyMuPDF 字形样式
  （bold/italic → **/*/​***）。
- list：用合并节点自带的 markdown。
- table：table_body_html 转管道表格 + 题注。
- equation_interline/chart(image)/algorithm/page_footnote：合并模块映射为
  unknown（载荷为空），从 v2 原始节点回填（公式 $$..$$、图片 ![](images/..)、
  算法代码块、脚注段落），保证图表与公式不丢。
- page_number/page_footer/page_header/aside_text 等页面装饰节点跳过。
"""
from __future__ import annotations

import html as _html
import json
import re
from pathlib import Path
from typing import Any

# 页面装饰节点：不进入合并版 markdown
_NOISE_TYPES = {"page_number", "page_footer", "page_header", "aside_text",
                "page_aside_text"}

# <sub> 失控判定阈值：MinerU vlm 偶发把全文字母逐个包进 <sub>（如 SkillSentry
# 的 logo 下标风格诱导，实测单篇 7754 处）。正常论文的合法下标通常几十处以内；
# 超过阈值判定为模型伪影，整篇剥离 <sub> 标签（保留内文）。<sup> 不受影响。
_SUB_RUNAWAY_LIMIT = 100


def _strip_runaway_sub_tags(md: str) -> str:
    """剥离失控的 <sub></sub> 标签（保留内文）。仅对超阈值文档调用。"""
    return re.sub(r"</?sub>", "", md)


# 标签形态（<sub>/<sup>/<em> 等短标签）——用于检测 PyMuPDF 样式 span 是否
# 会把标签从中间劈开（如 "C<su**b>ontr**olled"）：劈碎的标签既无法被剥离
# 正则识别，也无法被前端渲染器还原，会以字面 "<su"+"b>" 形式漏出。
_TAG_RE = re.compile(r"<[A-Za-z/][^<>]{0,20}>")


def _span_shreds_tag(text: str, start: int, end: int) -> bool:
    """样式 span [start,end) 是否切开文本中的某个标签（部分重叠）。"""
    for m in _TAG_RE.finditer(text):
        ts, te = m.start(), m.end()
        if ts < start < te or ts < end < te:
            return True
    return False


def _strip_sub_in_node(node: dict) -> dict:
    """失控文档的节点预处理：剥离 <sub> 并**弃用 style_spans**。

    spans 的偏移基于含标签的原文；剥离后偏移必然错位（且正是 span 劈开
    标签导致了碎片泄漏），故整篇放弃 PyMuPDF 字形样式，换取干净文本。
    """
    out = dict(node)
    payload = out.get("content_payload")
    if isinstance(payload, dict):
        p2 = {}
        for k, v in payload.items():
            if isinstance(v, str):
                p2[k] = re.sub(r"</?sub>", "", v)
            elif isinstance(v, list):
                p2[k] = [
                    {**f, "content": re.sub(r"</?sub>", "", f["content"])}
                    if isinstance(f, dict) and isinstance(f.get("content"), str) else f
                    for f in v
                ]
            else:
                p2[k] = v
        out["content_payload"] = p2
    out["style_spans"] = None
    return out


def _fragments_to_md(fragments: list[dict] | None) -> str:
    """text/equation_inline 片段流 → markdown，行内公式保留为 $...$。"""
    if not fragments:
        return ""
    parts: list[str] = []
    for f in fragments:
        if not isinstance(f, dict):
            continue
        if f.get("type") == "equation_inline":
            content = str(f.get("content") or "").strip()
            parts.append(f"${content}$" if content else "")
        else:
            parts.append(str(f.get("content") or ""))
    return "".join(parts)


def _apply_style_spans(text: str, spans: list[dict] | None) -> str:
    """把 PyMuPDF 字形样式 spans（start/end/style）转成 **/*/​*** 标记。

    仅接受有效且互不重叠的 spans；异常情况原样返回（宁缺样式不破坏文本）。
    """
    if not spans or not text:
        return text
    valid = []
    for s in spans:
        start, end = s.get("start"), s.get("end")
        if not (isinstance(start, int) and isinstance(end, int)):
            continue
        if not (0 <= start < end <= len(text)):
            continue
        if _span_shreds_tag(text, start, end):
            continue  # 会切开 <sub>/<sup> 等标签 → 弃用该 span（宁缺样式不碎标签）
        valid.append((start, end, s.get("style") or {}))
    if not valid:
        return text
    valid.sort(key=lambda x: (x[0], -(x[1])))
    out: list[str] = []
    pos = 0
    for start, end, style in valid:
        if start < pos:  # 重叠/嵌套：跳过，避免标记错乱
            continue
        seg = text[start:end]
        if not seg.strip():
            continue
        bold, italic = bool(style.get("bold")), bool(style.get("italic"))
        mark = "***" if bold and italic else "**" if bold else "*" if italic else ""
        out.append(text[pos:start])
        out.append(f"{mark}{seg}{mark}" if mark else seg)
        pos = end
    out.append(text[pos:])
    return "".join(out)


def _paragraph_md(node: dict) -> str:
    payload = node.get("content_payload") or {}
    fragments = payload.get("content_fragments")
    has_inline_eq = any(
        isinstance(f, dict) and f.get("type") == "equation_inline"
        for f in (fragments or [])
    )
    if has_inline_eq or not fragments:
        # 行内公式使片段串与 text 长度不一致，style_spans 偏移失效 → 不套样式
        return _fragments_to_md(fragments) or payload.get("markdown") or payload.get("text") or ""
    text = payload.get("text") or payload.get("markdown") or ""
    return _apply_style_spans(text, node.get("style_spans"))


def _heading_md(node: dict) -> str:
    payload = node.get("content_payload") or {}
    level = payload.get("heading_level") or 1
    try:
        level = max(1, min(int(level), 6))
    except (TypeError, ValueError):
        level = 2
    text = _fragments_to_md(payload.get("content_fragments")) or payload.get("text") or ""
    return f"{'#' * level} {text.strip()}"


def _html_table_rows(table_html: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table_html or "", re.S | re.I):
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S | re.I)
        cleaned = []
        for c in cells:
            text = re.sub(r"<[^>]+>", "", c)
            text = _html.unescape(text).strip().replace("|", "\\|")
            cleaned.append(text)
        if cleaned:
            rows.append(cleaned)
    return rows


def _table_md(node: dict) -> str:
    payload = node.get("content_payload") or {}
    rows = _html_table_rows(payload.get("table_body_html") or "")
    parts: list[str] = []
    caption = payload.get("table_caption")
    caption_text = ""
    if isinstance(caption, str):
        caption_text = caption.strip()
    elif isinstance(caption, list):
        caption_text = _fragments_to_md(caption).strip()
    if caption_text:
        parts.append(f"**{caption_text}**")
    if rows:
        width = max(len(r) for r in rows)
        norm = [r + [""] * (width - len(r)) for r in rows]
        head = norm[0]
        parts.append("| " + " | ".join(head) + " |")
        parts.append("|" + "|".join(["---"] * width) + "|")
        for r in norm[1:]:
            parts.append("| " + " | ".join(r) + " |")
    return "\n".join(parts)


def _caption_fragments_to_text(fragments: Any) -> str:
    if isinstance(fragments, str):
        return fragments.strip()
    if isinstance(fragments, list):
        return _fragments_to_md(fragments).strip()
    return ""


def _v2_node_md(v2_node: dict) -> str | None:
    """unknown 语义节点的 v2 原始内容回填；返回 None 表示跳过。"""
    vtype = v2_node.get("type")
    content = v2_node.get("content") or {}
    if vtype in ("chart", "image"):
        src = (content.get("image_source") or {}).get("path") or ""
        caption = _caption_fragments_to_text(
            content.get("chart_caption") or content.get("image_caption")
        )
        if src:
            md = f"![{caption}]({src})"
            return md
        return None
    if vtype == "equation_interline":
        math = str(content.get("math_content") or "").strip()
        if math:
            return f"$$\n{math}\n$$"
        src = (content.get("image_source") or {}).get("path")
        return f"![]({src})" if src else None
    if vtype == "algorithm":
        body = _fragments_to_md(content.get("algorithm_content")).strip()
        if not body:
            return None
        cap = _caption_fragments_to_text(content.get("algorithm_caption"))
        inner = (f"{cap}\n{body}" if cap else body)
        return f"```\n{inner}\n```"
    if vtype == "page_footnote":
        body = _fragments_to_md(content.get("page_footnote_content")).strip()
        return body or None
    return None


def build_merged_markdown(detail_result: dict, v2_data: list) -> str:
    """合并结果（unified_merge_schema v4）+ MinerU v2 原始节点 → 合并版 markdown。

    文档级失控检测：v2 数据中 <sub> 超过 _SUB_RUNAWAY_LIMIT 时，最终产物整篇
    剥离 <sub> 标签（MinerU vlm 伪影；合法下标为主的文档不受影响）。
    """
    merged_nodes = detail_result.get("merged_nodes") or []
    v2_flat: list[dict] = [nd for page in (v2_data or []) for nd in (page or [])]
    aligned = len(merged_nodes) == len(v2_flat)
    sub_runaway = json.dumps(v2_data, ensure_ascii=False).count("<sub>") > _SUB_RUNAWAY_LIMIT

    blocks: list[str] = []
    for i, node in enumerate(merged_nodes):
        if sub_runaway:
            node = _strip_sub_in_node(node)  # 先剥离再应用样式，避免 span 劈碎标签
        semantic = node.get("semantic_type")
        if semantic in _NOISE_TYPES:
            continue
        v2_node = v2_flat[i] if aligned else {}
        if semantic == "heading":
            md = _heading_md(node)
        elif semantic == "paragraph":
            md = _paragraph_md(node)
        elif semantic == "list":
            payload = node.get("content_payload") or {}
            md = payload.get("markdown") or _fragments_to_md(
                payload.get("content_fragments"))
        elif semantic == "table":
            md = _table_md(node)
        else:
            # unknown（公式/图表/算法/脚注等）：从 v2 原始节点回填
            md = _v2_node_md(v2_node) if v2_node else None
        if md and str(md).strip():
            blocks.append(str(md).strip())
    out = "\n\n".join(blocks) + ("\n" if blocks else "")
    if sub_runaway:
        out = _strip_runaway_sub_tags(out)
    return out


def _find_one(raw_dir: Path, pattern: str) -> Path:
    matches = sorted(raw_dir.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"{raw_dir} 中找不到 {pattern}")
    return matches[0]


def build_detail_assets(pdf_path: str | Path, raw_dir: str | Path,
                        out_dir: str | Path) -> dict:
    """从 MinerU 云包 _raw 三件套 + 源 PDF 生成旁路合并资产。

    产出（写入 out_dir，不触碰任何既有文件）：
    - detail.json：unified_merge_schema v4 完整合并结果（溯源/诊断用）
    - content.merged.md：合并版 markdown（前端"合并版"视图数据源）

    三件套不全时抛 FileNotFoundError；调用方应容错（合并失败不影响解析结果）。
    """
    from .get_layout import extract_pdf_content_layout  # noqa: PLC0415（惰性，触发 fitz）
    from .merge import merged  # noqa: PLC0415

    pdf_path = Path(pdf_path)
    raw_dir = Path(raw_dir)
    out_dir = Path(out_dir)

    v1_path = _find_one(raw_dir, "*_content_list.json")
    v2_path = _find_one(raw_dir, "*_content_list_v2.json")
    model_path = _find_one(raw_dir, "*_model.json")

    pdf_blocks = extract_pdf_content_layout(str(pdf_path))
    detail = merged(str(pdf_path), str(v2_path), str(v1_path), str(model_path),
                    pdf_blocks)
    v2_data = json.loads(v2_path.read_text(encoding="utf-8"))
    merged_md = build_merged_markdown(detail, v2_data)

    detail_path = out_dir / "detail.json"
    merged_md_path = out_dir / "content.merged.md"
    detail_path.write_text(json.dumps(detail, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    merged_md_path.write_text(merged_md, encoding="utf-8")
    return {
        "detail_path": str(detail_path),
        "merged_md_path": str(merged_md_path),
        "nodes": len(detail.get("merged_nodes") or []),
        "pages": len(detail.get("pages") or []),
    }
