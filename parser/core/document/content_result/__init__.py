import json
import math
from pathlib import Path
from typing import Any


_TEXTUAL_TYPES = {"text", "header", "footer", "page_number"}


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


def _try_build_content_entry(node: Any) -> dict | None:
    if not isinstance(node, dict):
        return None

    page_idx = node.get("page_idx")
    if not isinstance(page_idx, int):
        return None

    content_type = node.get("type", "unknown")
    entry: dict[str, Any] = {
        "element_id": node.get("element_id", ""),
        "content_type": content_type,
        "page_idx": page_idx,
    }

    if content_type == "list":
        if "list_items" not in node:
            return None
        entry["content"] = node["list_items"]
        return entry

    if content_type in _TEXTUAL_TYPES:
        if "text" not in node:
            return None
        entry["content"] = node["text"]
        return entry

    if content_type == "image":
        if "img_path" not in node:
            return None
        entry["content"] = node["img_path"]
        entry["image_caption"] = node.get("image_caption", [])
        entry["image_footnote"] = node.get("image_footnote", [])
        return entry

    if content_type == "table":
        if "table_body" not in node:
            return None
        entry["content"] = node["table_body"]
        entry["table_caption"] = node.get("table_caption", [])
        entry["table_footnote"] = node.get("table_footnote", [])
        entry["img_path"] = node.get("img_path", "")
        return entry

    if "text" in node:
        entry["content"] = node["text"]
        return entry
    if "list_items" in node:
        entry["content"] = node["list_items"]
        return entry
    if "table_body" in node:
        entry["content"] = node["table_body"]
        entry["table_caption"] = node.get("table_caption", [])
        entry["table_footnote"] = node.get("table_footnote", [])
        entry["img_path"] = node.get("img_path", "")
        return entry
    if "img_path" in node:
        entry["content"] = node["img_path"]
        entry["image_caption"] = node.get("image_caption", [])
        entry["image_footnote"] = node.get("image_footnote", [])
        return entry

    return None


def build_content_json_for_pdf(pdf_path: Path) -> list:
    tree = _load_content_tree(pdf_path)
    result = []
    for node in tree:
        entry = _try_build_content_entry(node)
        if entry is not None:
            result.append(entry)
    return result

__all__ = ["build_content_json_for_pdf"]
