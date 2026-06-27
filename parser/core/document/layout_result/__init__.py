import json
import math
from pathlib import Path
from typing import Any

from .extractor import PdfiumLayoutExtractor


def _is_bbox(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 4 and all(
        isinstance(item, (int, float)) for item in value
    )


def _sort_key(node: Any):
    if not isinstance(node, dict):
        return (1, 0, math.inf, math.inf, math.inf, math.inf)

    page = node.get("page_idx")
    has_page = isinstance(page, int)
    bbox = node.get("bbox")
    has_bbox = _is_bbox(bbox)
    page_value = page if has_page else math.inf

    if not has_bbox:
        return (0 if has_page else 1, page_value, math.inf, math.inf, math.inf, math.inf)

    x0, y0, x1, y1 = bbox
    return (0, page_value, y0, x0, y1, x1)


def _find_first_file(root: Path, name: str) -> Path | None:
    if not root.exists():
        return None
    for path in root.rglob(name):
        if path.is_file():
            return path
    return None


def _load_content_tree(pdf_path: Path) -> list:
    target_name = pdf_path.stem + "_content_list.json"
    found = _find_first_file(pdf_path.parent, target_name)
    if found is None:
        raise FileNotFoundError(f"Cannot locate content list JSON for: {pdf_path}")

    with found.open(encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, list):
        raise ValueError("content json root must be an array")

    data.sort(key=_sort_key)
    for index, node in enumerate(data):
        if isinstance(node, dict) and isinstance(node.get("page_idx"), int):
            node["element_id"] = f"page{node['page_idx']}_elem{index}"
    return data


def _is_text_like_node(node: Any) -> bool:
    return (
        isinstance(node, dict)
        and isinstance(node.get("text"), str)
        and _is_bbox(node.get("bbox"))
        and isinstance(node.get("page_idx"), int)
    )


def _is_text_substring_match(content_node: dict, layout_node: dict) -> bool:
    content_text = content_node.get("text", "")
    layout_text = layout_node.get("text", "")
    if not isinstance(content_text, str) or not isinstance(layout_text, str):
        return False
    return bool(layout_text) and layout_text in content_text


def _bbox_inside(inner: list, outer: list) -> bool:
    return (
        inner[0] >= outer[0]
        and inner[1] >= outer[1]
        and inner[2] <= outer[2]
        and inner[3] <= outer[3]
    )


def _bbox_center_dist2(a: list, b: list) -> float:
    ax = (a[0] + a[2]) / 2
    ay = (a[1] + a[3]) / 2
    bx = (b[0] + b[2]) / 2
    by = (b[1] + b[3]) / 2
    return (ax - bx) ** 2 + (ay - by) ** 2


def _merge_layout_props(content_node: dict, layout_node: dict) -> None:
    for key in ("style", "link", "position"):
        if key in layout_node:
            content_node[key] = layout_node[key]


def build_layout_json_for_pdf(pdf_path: Path) -> list:
    existing = _find_first_file(pdf_path.parent, "layout.json")
    if existing is not None:
        with existing.open(encoding="utf-8") as handle:
            return json.load(handle)

    content_tree = _load_content_tree(pdf_path)
    extracted_layout = PdfiumLayoutExtractor.extract_layout_json(pdf_path)

    for node in content_tree:
        if not _is_text_like_node(node):
            continue

        page_idx = node["page_idx"]
        content_bbox = node["bbox"]
        best_contained = None
        best_nearest = None
        best_distance = float("inf")

        for layout_node in extracted_layout:
            if not isinstance(layout_node, dict):
                continue
            if layout_node.get("content_type") != "text":
                continue
            if layout_node.get("page_idx") != page_idx:
                continue

            layout_bbox = layout_node.get("bbox")
            if not _is_bbox(layout_bbox):
                continue
            if not _is_text_substring_match(node, layout_node):
                continue

            if _bbox_inside(layout_bbox, content_bbox):
                best_contained = layout_node
                break

            distance = _bbox_center_dist2(layout_bbox, content_bbox)
            if distance < best_distance:
                best_distance = distance
                best_nearest = layout_node

        if best_contained is not None:
            _merge_layout_props(node, best_contained)
        elif best_nearest is not None:
            _merge_layout_props(node, best_nearest)


    return content_tree

__all__ = ["build_layout_json_for_pdf"]
