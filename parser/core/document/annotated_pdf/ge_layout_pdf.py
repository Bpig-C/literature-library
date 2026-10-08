from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

from pypdf import PdfReader, PdfWriter
from pypdf.annotations import FreeText, Rectangle
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    IndirectObject,
    NameObject,
    NumberObject,
    TextStringObject,
)


DEFAULT_COLORS = {
    "text": "FF4D4F",
    "title": "1677FF",
    "table": "2F9E44",
    "image": "F08C00",
    "figure": "F08C00",
    "default": "FF4D4F",
}

DEFAULT_LABEL_BG = "FFF2F0"


def _is_bbox(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(item, (int, float)) for item in value)
    )


def _load_content_list(content_list_path: Path) -> list[dict[str, Any]]:
    if not content_list_path.is_file():
        raise FileNotFoundError(f"content_list 文件不存在: {content_list_path}")

    with content_list_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError("content_list 根节点必须是数组")

    return [item for item in data if isinstance(item, dict)]


def _sorted_nodes(nodes: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(node: dict[str, Any]) -> tuple[int, float, float, float, float]:
        page_idx = node.get("page_idx")
        bbox = node.get("bbox")
        if not isinstance(page_idx, int) or not _is_bbox(bbox):
            return (10**9, float("inf"), float("inf"), float("inf"), float("inf"))
        x0, y0, x1, y1 = bbox
        return (
            page_idx,
            min(float(y0), float(y1)),
            min(float(x0), float(x1)),
            max(float(y0), float(y1)),
            max(float(x0), float(x1)),
        )

    return sorted(nodes, key=sort_key)


def _pick_color(node: dict[str, Any]) -> str:
    content_type = str(node.get("type") or node.get("content_type") or "").lower()
    return DEFAULT_COLORS.get(content_type, DEFAULT_COLORS["default"])


def _annotation_title(node: dict[str, Any], index: int) -> str:
    content_type = str(node.get("type") or node.get("content_type") or "unknown")
    page_idx = node.get("page_idx")
    element_id = node.get("element_id")
    if element_id:
        return f"{content_type} | p{page_idx} | {element_id}"
    return f"{content_type} | p{page_idx} | #{index}"


def _should_keep_node(
    node: dict[str, Any],
    include_types: set[str] | None,
    exclude_types: set[str] | None,
) -> bool:
    content_type = str(node.get("type") or node.get("content_type") or "").lower()
    if include_types is not None and content_type not in include_types:
        return False
    if exclude_types is not None and content_type in exclude_types:
        return False
    return True


def _apply_rectangle_style(annotation: Rectangle, color_hex: str, width: float) -> None:
    rgb = ArrayObject(
        [FloatObject(int(color_hex[i : i + 2], 16) / 255.0) for i in range(0, 6, 2)]
    )
    annotation[NameObject("/C")] = rgb
    annotation[NameObject("/BS")] = DictionaryObject(
        {NameObject("/W"): FloatObject(width)}
    )


def _hex_to_rgb01(color_hex: str) -> tuple[float, float, float]:
    return tuple(int(color_hex[i : i + 2], 16) / 255.0 for i in range(0, 6, 2))


def _append_page_commands(
    writer: PdfWriter,
    page: Any,
    commands: str,
) -> None:
    stream = DecodedStreamObject()
    stream.set_data(commands.encode("ascii"))
    stream_ref = writer._add_object(stream)

    contents = page.get("/Contents")
    if contents is None:
        page[NameObject("/Contents")] = stream_ref
        return

    if isinstance(contents, IndirectObject):
        contents = contents.get_object()

    if isinstance(contents, ArrayObject):
        contents.append(stream_ref)
        return

    page[NameObject("/Contents")] = ArrayObject([page["/Contents"], stream_ref])


def _build_rect_draw_command(
    rect: tuple[float, float, float, float],
    color_hex: str,
    border_width: float,
) -> str:
    left, bottom, right, top = rect
    width = right - left
    height = top - bottom
    r, g, b = _hex_to_rgb01(color_hex)
    return (
        "q\n"
        f"{r:.4f} {g:.4f} {b:.4f} RG\n"
        f"{border_width:.3f} w\n"
        f"{left:.3f} {bottom:.3f} {width:.3f} {height:.3f} re\n"
        "S\n"
        "Q\n"
    )


def _resolve_page_box(page: Any) -> tuple[float, float, float, float]:
    box = page.cropbox if page.cropbox is not None else page.mediabox
    return (
        float(box.left),
        float(box.bottom),
        float(box.right),
        float(box.top),
    )


def _mineru_bbox_to_pdf_rect(
    bbox: list[float],
    page_left: float,
    page_bottom: float,
    page_right: float,
    page_top: float,
    coord_origin: str,
) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = [float(v) for v in bbox]
    page_width = page_right - page_left
    page_height = page_top - page_bottom

    # MinerU content_list.json 的 bbox 使用 0-1000 normalized coordinate mapping。
    # 先缩放回当前页面真实尺寸，再转换到 PDF 坐标空间。
    left = min(x0, x1) * page_width / 1000.0 + page_left
    right = max(x0, x1) * page_width / 1000.0 + page_left

    if coord_origin == "bottom-left":
        bottom = min(y0, y1) * page_height / 1000.0 + page_bottom
        top = max(y0, y1) * page_height / 1000.0 + page_bottom
    else:
        # 官方文档说明 content_list bbox 仍使用归一化坐标映射，
        # 同时 middle.json 对齐结果表明其原点按页面左上角理解。
        bottom = page_top - (max(y0, y1) * page_height / 1000.0)
        top = page_top - (min(y0, y1) * page_height / 1000.0)

    return (left, bottom, right, top)


def _clip_rect_to_page(
    rect: tuple[float, float, float, float],
    page_left: float,
    page_bottom: float,
    page_right: float,
    page_top: float,
) -> tuple[float, float, float, float] | None:
    left, bottom, right, top = rect
    left = max(page_left, min(left, page_right))
    right = max(page_left, min(right, page_right))
    bottom = max(page_bottom, min(bottom, page_top))
    top = max(page_bottom, min(top, page_top))

    if right <= left or top <= bottom:
        return None
    return (left, bottom, right, top)


def _label_rect(
    rect: tuple[float, float, float, float],
    page_left: float,
    page_bottom: float,
    page_right: float,
    page_top: float,
) -> tuple[float, float, float, float] | None:
    left, _, right, top = rect
    label_height = 18.0
    label_width = max(72.0, min(240.0, right - left))

    preferred_bottom = top + 2.0
    preferred_top = preferred_bottom + label_height
    if preferred_top <= page_top:
        return (left, preferred_bottom, min(left + label_width, page_right), preferred_top)

    fallback_top = max(page_bottom, top - 2.0)
    fallback_bottom = fallback_top - label_height
    if fallback_bottom >= page_bottom:
        return (left, fallback_bottom, min(left + label_width, page_right), fallback_top)

    return None


def build_annotated_pdf(
    pdf_path: str | Path,
    content_list_path: str | Path,
    output_pdf_path: str | Path | None = None,
    *,
    border_width: float = 1.4,
    add_label: bool = False,
    include_types: set[str] | None = None,
    exclude_types: set[str] | None = None,
    coord_origin: str = "top-left",
    draw_on_page: bool = False,
    draw_annotation: bool = False,
    debug: bool = False,
) -> str:
    """
    依据 PDF 与 MinerU content_list.json 生成带标注框的新 PDF。

    参数:
        pdf_path: 原始 PDF 路径，必填
        content_list_path: MinerU 的 content_list.json 路径，必填
        output_pdf_path: 输出 PDF 路径，默认生成到原 PDF 同目录
        border_width: 边框宽度
        add_label: 是否绘制标签
        include_types: 仅保留这些类型
        exclude_types: 排除这些类型
        coord_origin: bbox 原点，可选 top-left / bottom-left
        draw_on_page: 是否直接把方框画进页面内容层
        draw_annotation: 是否额外保留 PDF 注释对象
        debug: 是否打印调试信息
    """
    if coord_origin not in {"top-left", "bottom-left"}:
        raise ValueError("coord_origin 只支持 'top-left' 或 'bottom-left'")

    source_pdf = Path(pdf_path)
    source_content_list = Path(content_list_path)

    if not source_pdf.is_file():
        raise FileNotFoundError(f"PDF 文件不存在: {source_pdf}")

    nodes = _sorted_nodes(_load_content_list(source_content_list))

    if output_pdf_path is None:
        output_path = source_pdf.with_name(f"{source_pdf.stem}_annotated.pdf")
    else:
        output_path = Path(output_pdf_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    reader = PdfReader(str(source_pdf))
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)

    drawn_count = 0

    for index, node in enumerate(nodes, start=1):
        page_idx = node.get("page_idx")
        bbox = node.get("bbox")

        if not isinstance(page_idx, int) or not _is_bbox(bbox):
            continue
        if page_idx < 0 or page_idx >= len(writer.pages):
            continue
        if not _should_keep_node(node, include_types, exclude_types):
            continue

        page = writer.pages[page_idx]
        page_left, page_bottom, page_right, page_top = _resolve_page_box(page)
        rect = _mineru_bbox_to_pdf_rect(
            bbox=bbox,
            page_left=page_left,
            page_bottom=page_bottom,
            page_right=page_right,
            page_top=page_top,
            coord_origin=coord_origin,
        )
        rect = _clip_rect_to_page(rect, page_left, page_bottom, page_right, page_top)
        if rect is None:
            continue

        title = _annotation_title(node, index)
        color = _pick_color(node)

        if debug and drawn_count < 8:
            print(
                f"[DEBUG] page={page_idx} type={node.get('type')} "
                f"bbox={bbox} -> rect={tuple(round(v, 2) for v in rect)}"
            )

        if draw_on_page:
            _append_page_commands(
                writer=writer,
                page=page,
                commands=_build_rect_draw_command(rect, color, border_width),
            )

        if draw_annotation:
            rectangle = Rectangle(rect=rect)
            _apply_rectangle_style(rectangle, color, border_width)
            rectangle[NameObject("/Contents")] = TextStringObject(title)
            writer.add_annotation(page_idx, rectangle)

        if add_label:
            text_rect = _label_rect(rect, page_left, page_bottom, page_right, page_top)
            if text_rect is not None:
                label = FreeText(
                    text=title,
                    rect=text_rect,
                    font="Helvetica",
                    font_size="8pt",
                    font_color=color,
                    border_color=color,
                    background_color=DEFAULT_LABEL_BG,
                )
                writer.add_annotation(page_idx, label)

        drawn_count += 1

    with output_path.open("wb") as file:
        writer.write(file)

    if debug:
        print(f"[DEBUG] drawn_boxes={drawn_count}")
        print(f"[DEBUG] output={output_path}")

    return str(output_path)


def _parse_types(value: str | None) -> set[str] | None:
    if not value:
        return None
    items = [item.strip().lower() for item in value.split(",") if item.strip()]
    return set(items) if items else None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="依据 PDF 与 MinerU content_list.json 生成带标注框的新 PDF"
    )
    parser.add_argument("pdf_path", help="原始 PDF 路径")
    parser.add_argument("content_list_path", help="MinerU content_list.json 路径")
    parser.add_argument(
        "-o",
        "--output",
        dest="output_pdf_path",
        help="输出 PDF 路径，默认在原 PDF 同目录生成 *_annotated.pdf",
    )
    parser.add_argument(
        "--border-width",
        type=float,
        default=1.4,
        help="边框宽度，默认 1.4",
    )
    parser.add_argument(
        "--add-label",
        action="store_true",
        help="绘制标签文本",
    )
    parser.add_argument(
        "--include-types",
        type=str,
        default=None,
        help="只保留这些类型，逗号分隔，例如 text,table,title",
    )
    parser.add_argument(
        "--exclude-types",
        type=str,
        default=None,
        help="排除这些类型，逗号分隔，例如 image,figure",
    )
    parser.add_argument(
        "--coord-origin",
        type=str,
        default="top-left",
        choices=["top-left", "bottom-left"],
        help="bbox 原点坐标系，MinerU 默认是 top-left",
    )
    parser.add_argument(
        "--draw-annotation",
        action="store_true",
        help="额外保留 PDF 注释对象，默认只直接绘制到页面内容层",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="打印调试信息",
    )
    return parser


def ge_layout_pdf(pdf_path,content_list_path) -> None:
    content_list_path = str(content_list_path)
    pdf_filename =str( pdf_path).split(".")[0].split("/")[-1]
    output_pdf_path = str( pdf_path).split(".")[0]+f"/{pdf_filename}_layout.pdf"
    # output_pdf_path =str( pdf_path).replace(".pdf", "_layout.pdf")
    no_label = False
    border_width = 0.1
    add_label = False
    draw_annotation = True
    include_types = None
    exclude_types = None
    coord_origin = "top-left"
    debug = False
    output = build_annotated_pdf(
        pdf_path=pdf_path,
        content_list_path=content_list_path,
        output_pdf_path=output_pdf_path,
        border_width=border_width,
        add_label=add_label,
        include_types=_parse_types(include_types),
        exclude_types=_parse_types(exclude_types),
        coord_origin=coord_origin,
        draw_annotation=draw_annotation,
        debug=debug,
    )
    print(output)


