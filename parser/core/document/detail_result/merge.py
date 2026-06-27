import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from html import escape
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    import fitz
except ImportError:
    fitz = None


SEMANTIC_TYPE_MAP = {
    "title": "heading",
    "paragraph": "paragraph",
    "page_header": "page_header",
    "header": "page_header",
    "footer": "page_footer",
    "page_number": "page_number",
    "aside_text": "aside_text",
    "list": "list",
    "image": "image",
    "table": "table",
}

MODEL_TO_SEMANTIC = {
    "title": "heading",
    "text": "paragraph",
    "ocr_text": "paragraph",
    "header": "page_header",
    "footer": "page_footer",
    "page_number": "page_number",
    "aside_text": "aside_text",
    "list": "list",
    "image": "image",
    "table": "table",
}


@dataclass
class MineruNode:
    page_idx: int
    v2_node_idx: int
    raw_type: str
    semantic_type: str
    bbox: List[float]
    content_fragments: Optional[List[Dict[str, Any]]]
    plain_text: str
    heading_level: Optional[int] = None
    list_type: Optional[str] = None
    list_items: Optional[List[Dict[str, Any]]] = None
    raw_list_items: List[str] = field(default_factory=list)
    content_list_index: Optional[int] = None
    model_page_index: Optional[int] = None
    model_block_index: Optional[int] = None
    model_type: Optional[str] = None
    bbox_norm: Optional[List[float]] = None
    angle: Optional[float] = None
    v1_record: Optional[Dict[str, Any]] = None


@dataclass
class PymupdfElement:
    page_idx: int
    element_index: int
    block_index: Optional[int]
    plain_text: str
    html: Optional[str]
    markdown: Optional[str]
    bbox_pt: List[float]
    bbox_norm_1000: List[float]
    runs: List[Dict[str, Any]]


@dataclass
class MatchResult:
    pymupdf_elements: List[PymupdfElement]
    text_similarity: float
    bbox_iou: Optional[float]
    merge_mode: str
    flat_runs: List[Dict[str, Any]]
    warnings: List[str] = field(default_factory=list)


def merged(
    pdf_path: str,
    content_list_v2_path: str,
    content_list_path: str,
    model_path: str,
     pdf_blocks 
) -> Dict[str, Any]:
    """按文档规范合并 MinerU 与 PyMuPDF 结果，生成 unified_merge_schema v4."""
    pdf_path = Path(pdf_path)
    v2_data = load_json(Path(content_list_v2_path))
    v1_data = load_json(Path(content_list_path))
    model_data = load_json(Path(model_path))
    content_base_dir = Path(content_list_v2_path).parent
  

    mineru_nodes = build_mineru_nodes(v2_data, v1_data, model_data)
    pymupdf_pages, page_sizes = build_pymupdf_index(pdf_blocks, pdf_path)

    merged_nodes: List[Dict[str, Any]] = []
    pages: List[Dict[str, Any]] = []
    stats_counter: Counter[str] = Counter()

    for page_idx, page_nodes in enumerate(mineru_nodes):
        used_elements: set[int] = set()
        page_merged_nodes: List[Dict[str, Any]] = []

        for reading_order, node in enumerate(page_nodes):
            match = match_mineru_node(node, pymupdf_pages.get(page_idx, []), used_elements)
            style_spans, html = build_node_styles(node, match)
            node_id = f"page{page_idx}_node{reading_order}"
            merged_node = build_merged_node(
                node=node,
                match=match,
                style_spans=style_spans,
                html=html,
                node_id=node_id,
                reading_order=reading_order,
                content_base_dir=content_base_dir,
            )
            page_merged_nodes.append(merged_node)
            stats_counter[node.semantic_type] += 1

        audit_page_style_spans(page_idx, page_nodes, page_merged_nodes, pymupdf_pages)

        width, height = page_sizes.get(page_idx, (None, None))
        pages.append(
            {
                "page_idx": page_idx,
                "width": width,
                "height": height,
                "rotation": None,
                "node_ids": [item["node_id"] for item in page_merged_nodes],
            }
        )
        merged_nodes.extend(page_merged_nodes)

    result = {
        "schema_version": "4.0",
        "document_meta": {
            "source_file_name": pdf_path.name,
            "source_file_type": pdf_path.suffix.lstrip(".").lower() or "pdf",
            "page_count": len(pages),
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
        "pages": pages,
        "merged_nodes": merged_nodes,
    }

    return result


def build_mineru_nodes(
    v2_data: Sequence[Sequence[Dict[str, Any]]],
    v1_data: Sequence[Dict[str, Any]],
    model_data: Sequence[Sequence[Dict[str, Any]]],
) -> List[List[MineruNode]]:
    v1_by_page: Dict[int, List[Tuple[int, Dict[str, Any]]]] = {}
    for index, item in enumerate(v1_data):
        v1_by_page.setdefault(item.get("page_idx", 0), []).append((index, item))

    pages: List[List[MineruNode]] = []
    for page_idx, nodes in enumerate(v2_data):
        page_nodes: List[MineruNode] = []
        for node_idx, raw_node in enumerate(nodes):
            node = create_mineru_node(page_idx, node_idx, raw_node)
            supplement_from_v1(node, v1_by_page.get(page_idx, []))
            supplement_from_model(node, model_data[page_idx] if page_idx < len(model_data) else [])
            page_nodes.append(node)
        pages.append(page_nodes)
    return pages


def create_mineru_node(page_idx: int, node_idx: int, raw_node: Dict[str, Any]) -> MineruNode:
    raw_type = raw_node.get("type", "unknown")
    semantic_type = SEMANTIC_TYPE_MAP.get(raw_type, "unknown")
    bbox = [float(v) for v in raw_node.get("bbox", [0, 0, 0, 0])]
    content = raw_node.get("content", {})

    if raw_type == "title":
        fragments = clone_fragments(content.get("title_content"))
        plain_text = fragments_to_plain_text(fragments)
        return MineruNode(
            page_idx=page_idx,
            v2_node_idx=node_idx,
            raw_type=raw_type,
            semantic_type=semantic_type,
            bbox=bbox,
            content_fragments=fragments,
            plain_text=plain_text,
            heading_level=content.get("level"),
        )

    if raw_type in {"paragraph", "page_header", "page_footer", "page_number", "aside_text"}:
        key = f"{raw_type}_content"
        fragments = clone_fragments(content.get(key) or content.get("paragraph_content"))
        plain_text = fragments_to_plain_text(fragments)
        return MineruNode(
            page_idx=page_idx,
            v2_node_idx=node_idx,
            raw_type=raw_type,
            semantic_type=semantic_type,
            bbox=bbox,
            content_fragments=fragments,
            plain_text=plain_text,
        )

    if raw_type == "list":
        list_items = []
        raw_list_items = []
        flattened_texts = []
        for item_idx, item in enumerate(content.get("list_items", [])):
            fragments = clone_fragments(item.get("item_content"))
            item_text = fragments_to_plain_text(fragments)
            raw_list_items.append(item_text)
            flattened_texts.append(item_text)
            list_items.append(
                {
                    "index": item_idx,
                    "item_type": item.get("item_type"),
                    "content_fragments": fragments,
                    "text": item_text,
                }
            )
        return MineruNode(
            page_idx=page_idx,
            v2_node_idx=node_idx,
            raw_type=raw_type,
            semantic_type=semantic_type,
            bbox=bbox,
            content_fragments=None,
            plain_text="\n".join(flattened_texts),
            list_type=content.get("list_type"),
            list_items=list_items,
            raw_list_items=raw_list_items,
        )

    raw_json = raw_node.get("content") if isinstance(raw_node.get("content"), dict) else raw_node
    return MineruNode(
        page_idx=page_idx,
        v2_node_idx=node_idx,
        raw_type=raw_type,
        semantic_type=semantic_type,
        bbox=bbox,
        content_fragments=None,
        plain_text=extract_fallback_text(raw_json),
        v1_record=raw_json,
    )


def supplement_from_v1(node: MineruNode, v1_candidates: Sequence[Tuple[int, Dict[str, Any]]]) -> None:
    best_idx = None
    best_record = None
    best_score = -1.0

    for idx, record in v1_candidates:
        semantic = infer_v1_semantic_type(record)
        if semantic != node.semantic_type:
            continue
        text_sim = SequenceMatcher(
            None,
            normalize_for_compare(node.plain_text),
            normalize_for_compare(v1_record_text(record)),
        ).ratio()
        bbox_iou = compute_iou(node.bbox, [float(v) for v in record.get("bbox", [0, 0, 0, 0])])
        score = 0.7 * text_sim + 0.3 * bbox_iou
        if score > best_score:
            best_score = score
            best_idx = idx
            best_record = record

    if best_record is None:
        return

    node.content_list_index = best_idx
    node.v1_record = best_record
    if node.semantic_type == "list" and not node.raw_list_items:
        node.raw_list_items = list(best_record.get("list_items", []))
    maybe_upgrade_plain_text_from_v1(node, best_record)


def supplement_from_model(node: MineruNode, model_candidates: Sequence[Dict[str, Any]]) -> None:
    best_idx = None
    best_record = None
    best_score = -1.0
    target_norm = [value / 1000.0 for value in node.bbox]

    for idx, record in enumerate(model_candidates):
        semantic = MODEL_TO_SEMANTIC.get(record.get("type"), "unknown")
        if semantic != node.semantic_type:
            continue
        bbox_norm = [float(v) for v in record.get("bbox", [0, 0, 0, 0])]
        bbox_iou = compute_iou(target_norm, bbox_norm)
        if bbox_iou > best_score:
            best_score = bbox_iou
            best_idx = idx
            best_record = record

    if best_record is None:
        return

    node.model_page_index = node.page_idx
    node.model_block_index = best_idx
    node.model_type = best_record.get("type")
    node.bbox_norm = [float(v) for v in best_record.get("bbox", [0, 0, 0, 0])]
    node.angle = best_record.get("angle")


def maybe_upgrade_plain_text_from_v1(node: MineruNode, record: Dict[str, Any]) -> None:
    if node.semantic_type not in {"heading", "page_header", "page_footer", "page_number", "aside_text"}:
        return
    if not node.content_fragments:
        return
    if any(fragment.get("type") != "text" for fragment in node.content_fragments):
        return

    candidate = (record.get("text") or "").strip()
    current = node.plain_text.strip()
    if not candidate or not current or len(candidate) <= len(current):
        return

    current_norm = normalize_for_compare(current)
    candidate_norm = normalize_for_compare(candidate)
    if current_norm and current_norm in candidate_norm:
        node.plain_text = candidate
        if len(node.content_fragments) == 1:
            node.content_fragments[0]["content"] = candidate


def build_pymupdf_index(
    pdf_blocks: Sequence[Dict[str, Any]],
    pdf_path: Optional[Path] = None,
) -> Tuple[Dict[int, List[PymupdfElement]], Dict[int, Tuple[Optional[float], Optional[float]]]]:
    pages: Dict[int, List[Dict[str, Any]]] = {}
    page_sizes = load_page_sizes_from_pdf(pdf_path) if pdf_path else {}
    inferred_sizes = infer_page_sizes(pdf_blocks)

    for element_index, block in enumerate(pdf_blocks):
        page_idx = int(block.get("page", 1)) - 1
        bbox_pt = [float(v) for v in block.get("bbox", [0, 0, 0, 0])]
        width, height = page_sizes.get(page_idx, inferred_sizes.get(page_idx, (None, None)))
        page_sizes[page_idx] = (width, height)
        bbox_norm = bbox_pt_to_norm_1000(bbox_pt, width, height)
        runs = list(block.get("runs", []))
        pages.setdefault(page_idx, []).append(
            PymupdfElement(
                page_idx=page_idx,
                element_index=len(pages.get(page_idx, [])),
                block_index=block.get("block_no"),
                plain_text=block.get("text", "") or "",
                html=normalize_html(block.get("html")),
                markdown=block.get("markdown"),
                bbox_pt=bbox_pt,
                bbox_norm_1000=bbox_norm,
                runs=runs,
            )
        )
    return pages, page_sizes


def load_page_sizes_from_pdf(
    pdf_path: Optional[Path],
) -> Dict[int, Tuple[Optional[float], Optional[float]]]:
    if not pdf_path or not pdf_path.exists() or fitz is None:
        return {}

    sizes: Dict[int, Tuple[Optional[float], Optional[float]]] = {}
    with fitz.open(pdf_path) as doc:
        for page_idx, page in enumerate(doc):
            rect = page.rect
            sizes[page_idx] = (float(rect.width), float(rect.height))
    return sizes


def infer_page_sizes(
    pdf_blocks: Sequence[Dict[str, Any]]
) -> Dict[int, Tuple[Optional[float], Optional[float]]]:
    common_widths = [594.96, 595.0, 612.0]
    common_heights = [841.92, 842.0, 792.0]
    grouped: Dict[int, List[Dict[str, Any]]] = {}
    for block in pdf_blocks:
        grouped.setdefault(int(block.get("page", 1)) - 1, []).append(block)

    sizes: Dict[int, Tuple[Optional[float], Optional[float]]] = {}
    for page_idx, blocks in grouped.items():
        max_x = max((float(b.get("bbox", [0, 0, 0, 0])[2]) for b in blocks), default=0.0)
        max_y = max((float(b.get("bbox", [0, 0, 0, 0])[3]) for b in blocks), default=0.0)
        if max_x <= 0 or max_y <= 0:
            sizes[page_idx] = (None, None)
            continue
        width = min((c for c in common_widths if c >= max_x), default=max(common_widths))
        height = min((c for c in common_heights if c >= max_y), default=max(common_heights))
        sizes[page_idx] = (width, height)
    return sizes


def match_mineru_node(
    node: MineruNode,
    page_elements: Sequence[PymupdfElement],
    used_elements
) -> MatchResult:
    if node.semantic_type in {"image", "table"}:
        return MatchResult([], 0.0, None, "mineru_only", [])

    available = [item for item in page_elements if item.element_index not in used_elements]
    match = find_match_for_node(node, available)
    if match is not None:
        for item in match.pymupdf_elements:
            used_elements.add(item.element_index)
        return match

    if available != list(page_elements):
        fallback_match = find_match_for_node(node, page_elements, allow_reuse=True)
        if fallback_match is not None:
            return fallback_match

    return MatchResult([], 0.0, None, "mineru_only", [])


def find_match_for_node(
    node: MineruNode,
    candidate_elements: Sequence[PymupdfElement],
    allow_reuse: bool = False,
) -> Optional[MatchResult]:
    if not candidate_elements:
        return None

    overlap_group_match = try_overlap_group_match(node, candidate_elements)
    if overlap_group_match is not None and candidate_score(overlap_group_match) >= 0.45:
        return overlap_group_match

    block_match = try_block_overlap_match(node, candidate_elements)
    if block_match is not None and candidate_score(block_match) >= 0.6:
        return block_match

    best_single: Optional[PymupdfElement] = None
    best_score = -1.0
    best_text_sim = 0.0
    best_bbox_iou = 0.0

    for element in candidate_elements:
        text_sim = similarity(node.plain_text, element.plain_text)
        bbox_iou = compute_iou(node.bbox, element.bbox_norm_1000)
        score = 0.7 * text_sim + 0.3 * bbox_iou
        if allow_reuse:
            score += 0.02
        if score > best_score:
            best_score = score
            best_single = element
            best_text_sim = text_sim
            best_bbox_iou = bbox_iou

    if best_single is None:
        return None

    best_match = build_match_result([best_single], best_text_sim, best_bbox_iou, [])
    if best_score >= 0.6:
        return best_match

    multi = try_multi_element_match(node, candidate_elements, best_single)
    if multi is not None:
        return multi

    return None


def try_overlap_group_match(
    node: MineruNode,
    page_elements: Sequence[PymupdfElement],
) -> Optional[MatchResult]:
    overlap_elements = [item for item in page_elements if boxes_overlap(node.bbox, item.bbox_norm_1000)]
    if not overlap_elements:
        return None

    overlap_elements.sort(key=lambda item: (item.bbox_norm_1000[1], item.bbox_norm_1000[0], item.element_index))
    text_sim = similarity(node.plain_text, "\n".join(item.plain_text for item in overlap_elements))
    bbox_iou = compute_iou(node.bbox, union_bbox([item.bbox_norm_1000 for item in overlap_elements]))
    return build_match_result(
        overlap_elements,
        text_sim,
        bbox_iou,
        [f"overlap_group_match:{len(overlap_elements)}"],
    )


def try_block_overlap_match(
    node: MineruNode,
    page_elements: Sequence[PymupdfElement],
) -> Optional[MatchResult]:
    blocks: Dict[Optional[int], List[PymupdfElement]] = {}
    for element in page_elements:
        blocks.setdefault(element.block_index, []).append(element)

    best: Optional[MatchResult] = None
    best_score = -1.0
    for block_index, elements in blocks.items():
        if block_index is None:
            continue
        overlap_elements = [item for item in elements if boxes_overlap(node.bbox, item.bbox_norm_1000)]
        if not overlap_elements:
            continue
        text_sim = similarity(node.plain_text, "\n".join(item.plain_text for item in overlap_elements))
        bbox_iou = compute_iou(node.bbox, union_bbox([item.bbox_norm_1000 for item in overlap_elements]))
        match = build_match_result(
            overlap_elements,
            text_sim,
            bbox_iou,
            [f"block_overlap_match:{block_index}:{len(overlap_elements)}"],
        )
        score = candidate_score(match)
        if score > best_score:
            best = match
            best_score = score
    return best


def try_multi_element_match(
    node: MineruNode,
    page_elements: Sequence[PymupdfElement],
    seed: PymupdfElement,
) -> Optional[MatchResult]:
    start_pos = next((i for i, item in enumerate(page_elements) if item.element_index == seed.element_index), None)
    if start_pos is None:
        return None

    best: Optional[MatchResult] = None
    best_score = -1.0
    for take in range(2, min(8, len(page_elements) - start_pos) + 1):
        chunk = page_elements[start_pos : start_pos + take]
        if not any(boxes_overlap(node.bbox, item.bbox_norm_1000) for item in chunk):
            continue
        text_sim = similarity(node.plain_text, "\n".join(item.plain_text for item in chunk))
        bbox_iou = compute_iou(node.bbox, union_bbox([item.bbox_norm_1000 for item in chunk]))
        score = 0.7 * text_sim + 0.3 * bbox_iou
        if text_sim > 0.8 and score > best_score:
            best = build_match_result(chunk, text_sim, bbox_iou, [f"multi_element_match:{len(chunk)}"])
            best_score = score
    return best


def build_match_result(
    elements: Sequence[PymupdfElement],
    text_similarity: float,
    bbox_iou: Optional[float],
    warnings: Sequence[str],
) -> MatchResult:
    flat_runs: List[Dict[str, Any]] = []
    for item in elements:
        flat_runs.extend(item.runs)
    return MatchResult(
        pymupdf_elements=list(elements),
        text_similarity=text_similarity,
        bbox_iou=bbox_iou,
        merge_mode="full_run_match" if text_similarity >= 0.85 else "block_match",
        flat_runs=flat_runs,
        warnings=list(warnings),
    )


def candidate_score(match: MatchResult) -> float:
    return 0.7 * match.text_similarity + 0.3 * (match.bbox_iou or 0.0)


def build_node_styles(node: MineruNode, match: MatchResult) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    if match.merge_mode == "mineru_only" or not match.flat_runs:
        return [], None

    default_color = dominant_color(match.flat_runs)
    if node.semantic_type == "list" and node.list_items:
        list_payload = build_list_item_styles(node, match, default_color)
        node.list_items = list_payload
        node_style_spans = align_runs_to_text(node.plain_text, match.flat_runs, f"page{node.page_idx}_nodeTMP")
        return node_style_spans, None

    style_spans = align_runs_to_text(node.plain_text, match.flat_runs, f"page{node.page_idx}_nodeTMP")
    html = generate_html(node.plain_text, style_spans, default_color)
    return style_spans, html


def build_list_item_styles(
    node: MineruNode,
    match: MatchResult,
    default_color: str,
) -> List[Dict[str, Any]]:
    item_results: List[Dict[str, Any]] = []
    elements = match.pymupdf_elements or []
    grouped_elements = partition_list_item_elements(node.list_items or [], elements)
    for item_idx, item in enumerate(node.list_items or []):
        item_text = item["text"]
        item_elements = grouped_elements[item_idx] if item_idx < len(grouped_elements) else []
        runs: List[Dict[str, Any]] = []
        for element in item_elements:
            runs.extend(element.runs)
        style_spans = align_runs_to_text(item_text, runs, f"page{node.page_idx}_nodeTMP_item{item_idx}")
        html = generate_html(item_text, style_spans, default_color) if runs else None
        item_results.append(
            {
                "index": item_idx,
                "item_type": item.get("item_type"),
                "content_fragments": item.get("content_fragments"),
                "text": item_text,
                "html": html,
                "style_spans": style_spans,
                "confidence": calc_span_coverage(style_spans, item_text),
            }
        )
    return item_results


def partition_list_item_elements(
    list_items: Sequence[Dict[str, Any]],
    elements: Sequence[PymupdfElement],
) -> List[List[PymupdfElement]]:
    if not list_items:
        return []

    groups: List[List[PymupdfElement]] = []
    cursor = 0
    total = len(elements)
    for item_idx, item in enumerate(list_items):
        target_text = item.get("text", "") or ""
        if cursor >= total:
            groups.append([])
            continue

        if item_idx == len(list_items) - 1:
            groups.append(list(elements[cursor:]))
            cursor = total
            continue

        best_group = [elements[cursor]]
        best_score = similarity(target_text, elements[cursor].plain_text)
        combined_text = elements[cursor].plain_text
        take = cursor + 1
        while take < total:
            candidate_text = f"{combined_text}\n{elements[take].plain_text}"
            score = similarity(target_text, candidate_text)
            if score + 0.02 < best_score:
                break
            best_group = list(elements[cursor : take + 1])
            best_score = score
            combined_text = candidate_text
            take += 1

        groups.append(best_group)
        cursor += len(best_group)
    return groups


def build_merged_node(
    node: MineruNode,
    match: MatchResult,
    style_spans: List[Dict[str, Any]],
    html: Optional[str],
    node_id: str,
    reading_order: int,
    content_base_dir: Path,
) -> Dict[str, Any]:
    if node.semantic_type == "list":
        content_payload = build_list_payload(node, node_id)
    elif node.semantic_type == "image":
        content_payload = build_image_payload(node, content_base_dir)
    elif node.semantic_type == "table":
        content_payload = build_table_payload(node, content_base_dir)
    else:
        content_payload = {
            "type": "text",
            "text": node.plain_text,
            "html": html,
            "heading_level": node.heading_level if node.semantic_type == "heading" else None,
            "content_fragments": node.content_fragments,
            "language": None,
            "markdown": generate_markdown(node),
        }

    finalized_spans = rebind_span_ids(style_spans, node_id)

    return {
        "node_id": node_id,
        "semantic_type": node.semantic_type,
        "page_idx": node.page_idx,
        "content_payload": content_payload,
        "layout": {
            "bbox": round_list(node.bbox, 3),
            "bbox_norm": round_list(node.bbox_norm, 3) if node.bbox_norm is not None else None,
            "angle": node.angle,
            "reading_order": reading_order,
            "page_idx": node.page_idx,
            "link": None,
            "z_index": None,
        },
        "style_spans": finalized_spans,
    }


def audit_page_style_spans(
    page_idx: int,
    page_nodes: Sequence[MineruNode],
    merged_nodes: Sequence[Dict[str, Any]],
    pymupdf_pages: Dict[int, List[PymupdfElement]],
) -> None:
    for reading_order, (node, merged_node) in enumerate(zip(page_nodes, merged_nodes)):
        if merged_node.get("style_spans"):
            if node.semantic_type == "list":
                audit_list_payload_items(merged_node["content_payload"], page_idx, pymupdf_pages)
            continue
        if node.semantic_type in {"image", "table"}:
            continue

        fallback_match = audit_style_span_match(node, pymupdf_pages)
        if fallback_match is None:
            if node.semantic_type == "list":
                audit_list_payload_items(merged_node["content_payload"], page_idx, pymupdf_pages)
            continue

        style_spans, html = build_node_styles(node, fallback_match)
        if not style_spans:
            if node.semantic_type == "list":
                audit_list_payload_items(merged_node["content_payload"], page_idx, pymupdf_pages)
            continue

        node_id = merged_node["node_id"]
        merged_node["style_spans"] = rebind_span_ids(style_spans, node_id)
        if node.semantic_type == "list":
            merged_node["content_payload"] = build_list_payload(node, node_id)
            audit_list_payload_items(merged_node["content_payload"], page_idx, pymupdf_pages)
        elif merged_node.get("content_payload", {}).get("type") == "text":
            merged_node["content_payload"]["html"] = html


def audit_list_payload_items(
    content_payload: Dict[str, Any],
    page_idx: int,
    pymupdf_pages: Dict[int, List[PymupdfElement]],
) -> None:
    for item in content_payload.get("items", []):
        if item.get("style_spans"):
            continue
        item_text = item.get("text", "") or ""
        if not item_text.strip():
            continue

        fallback_match = audit_text_match_by_page(item_text, page_idx, pymupdf_pages)
        if fallback_match is None or not fallback_match.flat_runs:
            continue

        default_color = dominant_color(fallback_match.flat_runs)
        style_spans = align_runs_to_text(item_text, fallback_match.flat_runs, f"{item['item_id']}_tmp")
        if not style_spans:
            continue

        item["style_spans"] = rebind_span_ids(style_spans, item["item_id"])
        item["html"] = generate_html(item_text, style_spans, default_color)
        item["confidence"] = round(calc_span_coverage(style_spans, item_text), 6)


def audit_style_span_match(
    node: MineruNode,
    pymupdf_pages: Dict[int, List[PymupdfElement]],
) -> Optional[MatchResult]:
    target_text = node.plain_text.strip()
    if not target_text:
        return None
    return audit_text_match_by_page(target_text, node.page_idx, pymupdf_pages)


def audit_text_match_by_page(
    target_text: str,
    page_idx: int,
    pymupdf_pages: Dict[int, List[PymupdfElement]],
) -> Optional[MatchResult]:
    best_match: Optional[MatchResult] = None
    best_score = -1.0
    for delta in (0, -1, 1):
        candidate_page = page_idx + delta
        if candidate_page < 0:
            continue
        elements = pymupdf_pages.get(candidate_page, [])
        if not elements:
            continue

        candidate = find_text_audit_match(target_text, elements, abs(delta))
        if candidate is None:
            continue

        score = candidate_score(candidate) - 0.08 * abs(delta)
        if score > best_score:
            best_match = candidate
            best_score = score

    return best_match if best_match is not None and best_score >= 0.62 else None


def find_text_audit_match(
    target_text: str,
    elements: Sequence[PymupdfElement],
    page_delta: int,
) -> Optional[MatchResult]:
    best_match: Optional[MatchResult] = None
    best_score = -1.0
    max_take = min(8, len(elements))

    for start in range(len(elements)):
        combined_text = ""
        chunk: List[PymupdfElement] = []
        for take in range(max_take):
            idx = start + take
            if idx >= len(elements):
                break
            chunk.append(elements[idx])
            combined_text = f"{combined_text}\n{elements[idx].plain_text}".strip() if combined_text else elements[idx].plain_text
            text_sim = similarity(target_text, combined_text)
            bbox_iou = compute_iou(
                [0.0, 0.0, 1000.0, 1000.0],
                union_bbox([item.bbox_norm_1000 for item in chunk]),
            )
            match = build_match_result(
                chunk,
                text_sim,
                bbox_iou,
                [f"text_audit_match:page_delta={page_delta}:chunk={len(chunk)}"],
            )
            score = text_sim - 0.03 * max(0, len(chunk) - 1)
            if score > best_score:
                best_match = match
                best_score = score

            if text_sim >= 0.985:
                return match

    return best_match if best_match is not None and best_match.text_similarity >= 0.72 else None


def build_list_payload(node: MineruNode, node_id: str) -> Dict[str, Any]:
    items = []
    for item_idx, item in enumerate(node.list_items or []):
        raw_spans = item.get("style_spans", [])
        item_id = f"{node_id}_item{item_idx}"
        items.append(
            {
                "item_id": item_id,
                "index": item_idx,
                "text": item.get("text", ""),
                "html": item.get("html"),
                "content_fragments": item.get("content_fragments"),
                "style_spans": rebind_span_ids(raw_spans, item_id),
                "confidence": round(item.get("confidence", 0.0), 6),
            }
        )
    return {
        "type": "list",
        "list_type": node.list_type,
        "ordered": infer_list_ordered(node.raw_list_items),
        "items": items,
        "raw_list_items": node.raw_list_items,
        "markdown": generate_markdown(node),
    }


def build_image_payload(node: MineruNode, content_base_dir: Path) -> Dict[str, Any]:
    record = node.v1_record or {}
    return {
        "type": "image",
        "img_path": record.get("img_path"),
        "image_caption": list(record.get("image_caption", [])),
        "image_footnote": list(record.get("image_footnote", [])),
        "alt_text": None,
    }


def build_table_payload(node: MineruNode, content_base_dir: Path) -> Dict[str, Any]:
    record = node.v1_record or {}
    return {
        "type": "table",
        "table_body_html": record.get("table_body"),
        "table_caption": list(record.get("table_caption", [])),
        "table_footnote": list(record.get("table_footnote", [])),
        "preview_img_path": record.get("img_path"),
    }


def align_runs_to_text(plain_text: str, runs: Sequence[Dict[str, Any]], span_prefix: str) -> List[Dict[str, Any]]:
    style_spans: List[Dict[str, Any]] = []
    mi = 0
    for run_idx, run in enumerate(runs):
        run_text = run.get("text", "") or ""
        if not run_text:
            continue
        ri = 0
        match_start = -1
        skip_count = 0
        local_mi = mi
        while local_mi < len(plain_text) and ri < len(run_text):
            mc = normalize_char(plain_text[local_mi])
            rc = normalize_char(run_text[ri])
            if mc == rc:
                if match_start == -1:
                    match_start = local_mi
                local_mi += 1
                ri += 1
                continue
            if plain_text[local_mi].isspace():
                local_mi += 1
                skip_count += 1
                continue
            if run_text[ri].isspace():
                ri += 1
                skip_count += 1
                continue
            next_run_matches = ri + 1 < len(run_text) and mc == normalize_char(run_text[ri + 1])
            next_text_matches = local_mi + 1 < len(plain_text) and normalize_char(plain_text[local_mi + 1]) == rc
            if next_run_matches and not next_text_matches:
                ri += 1
                skip_count += 1
                continue
            if next_text_matches:
                local_mi += 1
                skip_count += 1
                continue
            local_mi += 1
            ri += 1
            skip_count += 1

        if match_start >= 0 and local_mi > match_start:
            style_spans.append(
                {
                    "span_id": f"{span_prefix}_s{len(style_spans)}",
                    "start": match_start,
                    "end": local_mi,
                    "text": plain_text[match_start:local_mi],
                    "style": extract_style(run),
                    "link": None,
                    "pymupdf_run_indices": [run_idx],
                    "confidence": round(ri / len(run_text), 6) if run_text else 0.0,
                    "_skip_count": skip_count,
                }
            )
            mi = local_mi
    return merge_adjacent_spans(style_spans)


def merge_adjacent_spans(style_spans: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged_spans: List[Dict[str, Any]] = []
    for span in style_spans:
        clean = {k: v for k, v in span.items() if k != "span_id"}
        if (
            merged_spans
            and merged_spans[-1]["end"] == clean["start"]
            and merged_spans[-1]["style"] == clean["style"]
        ):
            merged_spans[-1]["end"] = clean["end"]
            merged_spans[-1]["text"] += clean["text"]
            merged_spans[-1]["pymupdf_run_indices"].extend(clean["pymupdf_run_indices"])
            merged_spans[-1]["confidence"] = round(
                mean([merged_spans[-1]["confidence"], clean["confidence"]]), 6
            )
            merged_spans[-1]["_skip_count"] += clean.get("_skip_count", 0)
        else:
            merged_spans.append(clean)
    return merged_spans


def generate_html(plain_text: str, style_spans: Sequence[Dict[str, Any]], default_color: str) -> str:
    parts: List[str] = []
    last_end = 0
    for span in style_spans:
        if span["start"] > last_end:
            parts.append(escape(plain_text[last_end : span["start"]]))

        text = escape(span["text"])
        style = span["style"]
        if style.get("superscript"):
            text = f"<sup>{text}</sup>"
        elif style.get("subscript"):
            text = f"<sub>{text}</sub>"
        if style.get("color_hex") and style["color_hex"] != default_color:
            text = f'<span style="color:{style["color_hex"]}">{text}</span>'
        if style.get("underline"):
            text = f"<u>{text}</u>"
        if style.get("strikeout"):
            text = f"<s>{text}</s>"
        if style.get("italic"):
            text = f"<i>{text}</i>"
        if style.get("bold"):
            text = f"<b>{text}</b>"
        parts.append(text)
        last_end = span["end"]

    if last_end < len(plain_text):
        parts.append(escape(plain_text[last_end:]))
    return "".join(parts)


def collect_warnings(
    match: MatchResult, style_spans: Sequence[Dict[str, Any]], plain_text: str
) -> List[str]:
    warnings = list(match.warnings)
    if match.merge_mode == "mineru_only":
        return warnings
    if 0.6 <= match.text_similarity < 0.85:
        warnings.append(f"low_text_similarity:{round(match.text_similarity, 6)}")
    coverage = calc_span_coverage(style_spans, plain_text)
    if coverage < 0.8:
        warnings.append(f"partial_style_coverage:{round(coverage, 6)}")
    for span in style_spans:
        if span.get("_skip_count", 0) > 3:
            run_index = span.get("pymupdf_run_indices", [None])[0]
            warnings.append(f"char_skip_in_run:{run_index}")
    return dedupe_preserve_order(warnings)


def calc_merge_confidence(
    match: MatchResult, style_spans: Sequence[Dict[str, Any]], plain_text: str
) -> float:
    if match.merge_mode == "mineru_only":
        return 0.0
    span_avg = mean([span["confidence"] for span in style_spans]) if style_spans else 0.0
    coverage = calc_span_coverage(style_spans, plain_text)
    return round(0.4 * match.text_similarity + 0.3 * span_avg + 0.3 * coverage, 6)


def calc_span_coverage(style_spans: Sequence[Dict[str, Any]], plain_text: str) -> float:
    if not plain_text:
        return 0.0
    covered = sum(max(0, span["end"] - span["start"]) for span in style_spans)
    return min(1.0, covered / len(plain_text))


def fragments_to_plain_text(fragments: Optional[Sequence[Dict[str, Any]]]) -> str:
    if not fragments:
        return ""
    return "".join(fragment_to_plain_text(fragment) for fragment in fragments).strip()


def fragment_to_plain_text(fragment: Dict[str, Any]) -> str:
    fragment_type = fragment.get("type")
    content = fragment.get("content", "") or ""
    if fragment_type == "equation_inline":
        return latex_to_readable_text(content)
    return content


def latex_to_readable_text(content: str) -> str:
    text = content
    replacements = [
        (r"\\mathsf\s*\{([^{}]*)\}", r"\1"),
        (r"\\mathrm\s*\{([^{}]*)\}", r"\1"),
        (r"\\sf\s*\{([^{}]*)\}", r"\1"),
        (r"\^\s*\{\s*([^{}]+?)\s*\}", r"\1"),
        (r"_\s*\{\s*([^{}]+?)\s*\}", r"\1"),
        (r"\\times", "×"),
        (r"~", " "),
        (r"\\mu", "μ"),
        (r"\\mp", "天"),
        (r"\\gimel", "g"),
    ]
    for pattern, repl in replacements:
        text = re.sub(pattern, repl, text)
    text = re.sub(r"\\[a-zA-Z]+", " ", text)
    text = re.sub(r"[{}]", " ", text)
    text = re.sub(r"\s+", " ", text)
    text = text.replace("： ", "：")
    text = text.replace(" ,", ",")
    return re.sub(r"\s+", "", text).strip()


def infer_v1_semantic_type(record: Dict[str, Any]) -> str:
    if record.get("type") == "text":
        if int(record.get("text_level", 0) or 0) >= 1:
            return "heading"
        return "paragraph"
    return SEMANTIC_TYPE_MAP.get(record.get("type"), "unknown")


def v1_record_text(record: Dict[str, Any]) -> str:
    if record.get("type") == "list":
        return "\n".join(record.get("list_items", []))
    return record.get("text", "") or ""


def generate_markdown(node: MineruNode) -> Optional[str]:
    if node.semantic_type == "heading":
        level = max(1, int(node.heading_level or 1))
        return f"{'#' * min(level, 6)} {node.plain_text}".strip()
    if node.semantic_type == "list":
        return "\n".join(f"- {item}" for item in node.raw_list_items) if node.raw_list_items else None
    if node.semantic_type in {"paragraph", "page_header", "page_footer", "page_number", "aside_text"}:
        return node.plain_text or None
    return None


def bbox_pt_to_norm_1000(
    bbox_pt: Sequence[float], width: Optional[float], height: Optional[float]
) -> List[float]:
    if not width or not height:
        return [0.0, 0.0, 0.0, 0.0]
    return [
        round(float(bbox_pt[0]) / width * 1000, 3),
        round(float(bbox_pt[1]) / height * 1000, 3),
        round(float(bbox_pt[2]) / width * 1000, 3),
        round(float(bbox_pt[3]) / height * 1000, 3),
    ]


def compute_iou(box_a: Sequence[float], box_b: Sequence[float]) -> float:
    if not box_a or not box_b:
        return 0.0
    ax1, ay1, ax2, ay2 = map(float, box_a)
    bx1, by1, bx2, by2 = map(float, box_b)
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    denom = area_a + area_b - inter_area
    return inter_area / denom if denom > 0 else 0.0


def boxes_overlap(box_a: Sequence[float], box_b: Sequence[float], tolerance: float = 12.0) -> bool:
    if not box_a or not box_b:
        return False
    ax1, ay1, ax2, ay2 = map(float, box_a)
    bx1, by1, bx2, by2 = map(float, box_b)
    return (
        min(ax2, bx2) + tolerance > max(ax1, bx1)
        and min(ay2, by2) + tolerance > max(ay1, by1)
    )


def similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, normalize_for_compare(left), normalize_for_compare(right)).ratio()


def normalize_for_compare(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("：", ":")
    text = text.replace("，", ",")
    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"\$+", "", text)
    text = re.sub(r"\s+", "", text)
    return text.lower()


def normalize_char(ch: str) -> str:
    ch = unicodedata.normalize("NFKC", ch)
    if ch in {"：", ":"}:
        return ":"
    if ch in {"，", ","}:
        return ","
    return ch.lower()


def dominant_color(runs: Sequence[Dict[str, Any]]) -> str:
    colors = [run.get("color_hex") for run in runs if run.get("color_hex")]
    if not colors:
        return "#000000"
    return Counter(colors).most_common(1)[0][0]


def extract_style(run: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "bold": bool(run.get("bold")),
        "italic": bool(run.get("italic")),
        "underline": bool(run.get("underline")),
        "strikeout": bool(run.get("strikeout")),
        "superscript": bool(run.get("superscript")),
        "subscript": bool(run.get("subscript")),
        "font": run.get("font"),
        "font_size": run.get("size"),
        "color_hex": compact_color(run.get("color_hex")),
    }


def infer_list_ordered(items: Sequence[str]) -> Optional[bool]:
    if not items:
        return None
    ordered_hits = 0
    for item in items:
        if re.match(r"^\s*(\d+[\.\)]|[A-Za-z][\.\)])\s+", item):
            ordered_hits += 1
    return ordered_hits == len(items) if ordered_hits else False


def clone_fragments(fragments: Optional[Sequence[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
    if fragments is None:
        return None
    return [{"type": item.get("type"), "content": item.get("content", "")} for item in fragments]


def extract_fallback_text(raw_json: Any) -> str:
    if isinstance(raw_json, dict):
        for key in ("text", "content", "title", "caption"):
            value = raw_json.get(key)
            if isinstance(value, str):
                return value
    return ""


def union_bbox(boxes: Sequence[Sequence[float]]) -> List[float]:
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def compact_color(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return value.replace(" ", "").lower()


def normalize_html(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return re.sub(r"\s+", " ", value).strip()


def rebind_span_ids(style_spans: Sequence[Dict[str, Any]], prefix: str) -> List[Dict[str, Any]]:
    rebound = []
    for index, span in enumerate(style_spans):
        item = dict(span)
        item["span_id"] = f"{prefix}_s{index}"
        item.pop("_skip_count", None)
        rebound.append(item)
    return rebound


def round_list(values: Sequence[float], ndigits: int) -> List[float]:
    return [round(float(v), ndigits) for v in values]


def dedupe_preserve_order(items: Sequence[str]) -> List[str]:
    seen = set()
    output = []
    for item in items:
        if item not in seen:
            output.append(item)
            seen.add(item)
    return output


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


if __name__ == "__main__":
    import sys
    

    # 获取目录路径
    directory_path = Path("./Datas/uploads/16065370903852373932/测试文档_创世纪/unzipped/测试文档_创世纪/hybrid_auto")
    
    # 检查目录是否存在
    if not directory_path.exists() or not directory_path.is_dir():
        print(f"Error: Directory '{directory_path}' does not exist or is not a directory")
        sys.exit(1)
    
    # 查找PDF文件
    pdf_files = list(directory_path.glob("*.pdf"))
    if not pdf_files:
        print(f"Error: No PDF files found in directory '{directory_path}'")
        sys.exit(1)
    pdf_path = pdf_files[0]
    
    # 查找其他必需文件
    pdf_block_path = directory_path / "pdf_content_layout.json"
    
    # 查找content_list_v2.json文件（不依赖于PDF文件名）
    content_list_v2_files = list(directory_path.glob("*_content_list_v2.json"))
    if not content_list_v2_files:
        print(f"Error: No *_content_list_v2.json file found in directory '{directory_path}'")
        sys.exit(1)
    content_list_v2_path = content_list_v2_files[0]
    
    # 查找content_list.json文件
    content_list_files = list(directory_path.glob("*_content_list.json"))
    if not content_list_files:
        print(f"Error: No *_content_list.json file found in directory '{directory_path}'")
        sys.exit(1)
    content_list_path = content_list_files[0]
    
    # 查找model.json文件
    model_files = list(directory_path.glob("*_model.json"))
    if not model_files:
        print(f"Error: No *_model.json file found in directory '{directory_path}'")
        sys.exit(1)
    model_path = model_files[0]
    
    # 检查所有文件是否存在
    required_files = [
        (pdf_block_path, "pdf_content_layout.json"),
        (content_list_v2_path, content_list_v2_path.name),
        (content_list_path, content_list_path.name),
        (model_path, model_path.name)
    ]
    
    for file_path, file_name in required_files:
        if not file_path.exists():
            print(f"Error: File '{file_name}' not found in directory '{directory_path}'")
            sys.exit(1)
    
    # 加载pdf_block
    pdf_block = load_json(pdf_block_path)
    
    # 调用merged函数
    result = merged(
        str(pdf_path),
        str(content_list_v2_path),
        str(content_list_path),
        str(model_path),
        pdf_block
    )
    
    # 保存结果
    output_path = directory_path / "merged_ans.json"
    with open(output_path, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=4)
    
    print(f"Merge completed successfully! Result saved to: {output_path}")
