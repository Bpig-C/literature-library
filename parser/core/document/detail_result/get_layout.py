# -*- coding: utf-8 -*-
"""
PDF 文本样式抽取（完整版）
依赖:
    pip install PyMuPDF

说明:
1. 使用 fitz (PyMuPDF) 读取文字型 PDF。
2. 输出按“同一行内相邻内容合并”后的结果。
3. 每个结果对象包含:
   - text
   - html
   - markdown
   - runs（内部样式片段明细）
4. 支持:
   - bold / italic / bold+italic
   - superscript
   - subscript（启发式）
   - color
   - underline / overline / strikeout（尽量读取）
"""

import json
import html
import re
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF


# ========= PyMuPDF 文本字体 flags =========
TEXT_FONT_SUPERSCRIPT = 1
TEXT_FONT_ITALIC = 2
TEXT_FONT_SERIFED = 4
TEXT_FONT_MONOSPACED = 8
TEXT_FONT_BOLD = 16

# ========= MuPDF 字符级样式 flags（span.char_flags）=========
TEXT_CHAR_STRIKEOUT = 1
TEXT_CHAR_UNDERLINE = 2
TEXT_CHAR_SYNTHETIC = 4
TEXT_CHAR_BOLD = 8
TEXT_CHAR_FILLED = 16
TEXT_CHAR_STROKED = 32


def has_flag(value: int, flag: int) -> bool:
    return bool(value & flag)


def get_char_flags(span: Dict[str, Any]) -> int:
    """
    读取 MuPDF 的字符级样式位。

    说明:
    - span["flags"] 是字体属性位（italic / bold / serif ...）
    - span["char_flags"] 是字符渲染/装饰位（underline / strikeout / fake bold ...）
    """
    value = span.get("char_flags", 0)
    try:
        return int(value)
    except Exception:
        return 0


def rect_to_list(rect: Any) -> Optional[List[float]]:
    """
    尽量把 Rect / tuple / list 统一成 [x0, y0, x1, y1]。
    """
    if rect is None:
        return None
    if hasattr(rect, "x0") and hasattr(rect, "y0") and hasattr(rect, "x1") and hasattr(rect, "y1"):
        return [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)]
    if isinstance(rect, (list, tuple)) and len(rect) >= 4:
        try:
            return [float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])]
        except Exception:
            return None
    return None


def collect_horizontal_decorations(page: fitz.Page) -> List[List[float]]:
    """
    收集页面上可能作为 underline / strikeout 的细水平线。

    这里只做较保守的候选收集，真正是否作为 underline 使用，
    还要结合 span 的 bbox 位置再判断。
    """
    candidates: List[List[float]] = []
    try:
        drawings = page.get_drawings()
    except Exception:
        return candidates

    for drawing in drawings:
        rect = rect_to_list(drawing.get("rect"))
        if not rect:
            continue

        x0, y0, x1, y1 = rect
        width = max(0.0, x1 - x0)
        height = max(0.0, y1 - y0)

        # 过滤非细水平线
        if width <= 0 or height <= 0:
            continue
        if width < 4.0:
            continue
        if height > min(3.0, width * 0.2):
            continue

        candidates.append(rect)

    return candidates


def bbox_horizontal_overlap_ratio(b1: List[float], b2: List[float]) -> float:
    left = max(b1[0], b2[0])
    right = min(b1[2], b2[2])
    overlap = max(0.0, right - left)
    base = max(1.0, min(b1[2] - b1[0], b2[2] - b2[0]))
    return overlap / base


def has_visual_underline(span: Dict[str, Any], horizontal_decorations: Optional[List[List[float]]]) -> bool:
    """
    几何确认 underline。

    背景:
    - MuPDF 的 char_flags 有时会把表格边框 / 邻近横线也记成 underline。
    - 因此这里要求：必须在文字 bbox 底部附近找到与文字水平方向明显重合的细横线。
    """
    if not horizontal_decorations:
        return False

    bbox = rect_to_list(span.get("bbox"))
    if not bbox:
        return False

    x0, y0, x1, y1 = bbox
    width = max(1.0, x1 - x0)
    height = max(1.0, y1 - y0)

    # 只认靠近文字底部的线，避免把表格上边框/标题分隔线误判成下划线。
    min_center_y = y0 + height * 0.68
    max_center_y = y1 + min(2.0, height * 0.18)

    for deco in horizontal_decorations:
        dx0, dy0, dx1, dy1 = deco
        center_y = (dy0 + dy1) / 2.0
        if center_y < min_center_y or center_y > max_center_y:
            continue

        overlap_ratio = bbox_horizontal_overlap_ratio(bbox, deco)
        if overlap_ratio < 0.65:
            continue

        # 线宽允许略短于文字，但不应明显长得离谱。
        deco_width = max(1.0, dx1 - dx0)
        if deco_width > width * 1.35:
            continue

        # 下划线通常与文字左右边界接近；
        # 如果明显超出文字两端，更像表格边框/分隔线而不是 underline。
        max_edge_overhang = max(6.0, width * 0.08)
        left_overhang = max(0.0, x0 - dx0)
        right_overhang = max(0.0, dx1 - x1)
        if left_overhang > max_edge_overhang or right_overhang > max_edge_overhang:
            continue

        return True

    return False


def pdf_int_color_to_rgb_tuple(color: Optional[int]) -> Optional[Tuple[int, int, int]]:
    """
    span['color'] 常见为 0xRRGGBB 整数。
    转成 (r, g, b)。
    """
    if color is None:
        return None
    if isinstance(color, int):
        r = (color >> 16) & 0xFF
        g = (color >> 8) & 0xFF
        b = color & 0xFF
        return (r, g, b)
    return None


def rgb_to_hex(rgb: Optional[Tuple[int, int, int]]) -> Optional[str]:
    if rgb is None:
        return None
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def get_char_text(chars: List[Dict[str, Any]]) -> str:
    """
    从 rawdict 的 chars 拼接文字。
    """
    out = []
    for ch in chars:
        c = ch.get("c")
        if c is not None:
            out.append(c)
    return "".join(out)


def median(nums: List[float]) -> Optional[float]:
    if not nums:
        return None
    nums = sorted(nums)
    n = len(nums)
    if n % 2 == 1:
        return nums[n // 2]
    return (nums[n // 2 - 1] + nums[n // 2]) / 2.0


def get_line_median_size(line: Dict[str, Any]) -> Optional[float]:
    sizes = []
    for span in line.get("spans", []):
        size = span.get("size")
        if isinstance(size, (int, float)):
            sizes.append(float(size))
    return median(sizes)


def get_line_baseline(line: Dict[str, Any]) -> Optional[float]:
    """
    近似取一行的 baseline：span.origin[1] 的中位数
    """
    baselines = []
    for span in line.get("spans", []):
        origin = span.get("origin")
        if isinstance(origin, (list, tuple)) and len(origin) >= 2:
            y = origin[1]
            if isinstance(y, (int, float)):
                baselines.append(float(y))
    return median(baselines)


def infer_subscript(span: Dict[str, Any], line: Dict[str, Any]) -> bool:
    """
    下标启发式判断：
    - 当前 span 不是 superscript
    - 字号比当前行中位字号更小
    - baseline 比当前行中位 baseline 更低

    注意:
    这是启发式，不保证 100% 准确。
    """
    flags_val = int(span.get("flags", 0))
    if has_flag(flags_val, TEXT_FONT_SUPERSCRIPT):
        return False

    size = span.get("size")
    origin = span.get("origin")
    if not isinstance(size, (int, float)):
        return False
    if not (isinstance(origin, (list, tuple)) and len(origin) >= 2):
        return False

    line_median_size = get_line_median_size(line)
    line_baseline = get_line_baseline(line)
    if line_median_size is None or line_baseline is None:
        return False

    size = float(size)
    baseline_y = float(origin[1])

    # PDF 坐标系中，y 越大越靠下
    # 一些 PDF 的上下标只会比正文略小一点（例如 10pt vs 11pt），
    # 这里阈值不能卡得太死，否则会把真正的下标漏掉。
    smaller = size <= line_median_size * 0.96
    lower = baseline_y >= line_baseline + max(0.8, line_median_size * 0.08)

    return smaller and lower


def escape_html_text(text: str) -> str:
    return html.escape(text, quote=False)


def apply_html_style(
    text: str,
    bold: bool = False,
    italic: bool = False,
    sup: bool = False,
    sub: bool = False,
    underline: bool = False,
    strikeout: bool = False,
    overline: bool = False,
    color_hex: Optional[str] = None,
) -> str:
    """
    生成带样式的 HTML 片段。

    包裹顺序:
    1. 先转义
    2. sup/sub
    3. underline/strike/overline
    4. italic/bold
    5. color span
    """
    s = escape_html_text(text)

    if sup:
        s = f"<sup>{s}</sup>"
    elif sub:
        s = f"<sub>{s}</sub>"

    # 文本装饰
    if underline:
        s = f"<u>{s}</u>"
    if strikeout:
        s = f"<s>{s}</s>"
    if overline:
        s = f'<span style="text-decoration: overline;">{s}</span>'

    # 粗斜体
    if bold and italic:
        s = f"<b><i>{s}</i></b>"
    elif bold:
        s = f"<b>{s}</b>"
    elif italic:
        s = f"<i>{s}</i>"

    # 颜色
    if color_hex:
        s = f'<span style="color: {color_hex};">{s}</span>'

    return s


def apply_markdown_style(
    text: str,
    bold: bool = False,
    italic: bool = False,
    sup: bool = False,
    sub: bool = False,
    underline: bool = False,
    strikeout: bool = False,
    overline: bool = False,
) -> str:
    """
    生成 markdown 片段。

    约定:
    - superscript -> ^text
    - subscript   -> ~text~
    - bold        -> **text**
    - italic      -> *text*
    - bold+italic -> ***text***
    - strikeout   -> ~~text~~

    说明:
    - 标准 Markdown 对上标/下标/下划线/上划线没有统一规范
    - 这里采用你当前最容易消费的表达方式
    - underline / overline 在 markdown 没有统一标准，这里保留原文，不额外编码
    """
    s = text

    if sup:
        s = f"^{s}"
    elif sub:
        s = f"~{s}~"

    if strikeout:
        s = f"~~{s}~~"

    if bold and italic:
        s = f"***{s}***"
    elif bold:
        s = f"**{s}**"
    elif italic:
        s = f"*{s}*"

    # underline / overline 不做 markdown 包裹
    # 因为标准 markdown 没有统一写法
    return s


def bbox_union(b1: Optional[List[float]], b2: Optional[List[float]]) -> Optional[List[float]]:
    if not b1:
        return b2[:] if b2 else None
    if not b2:
        return b1[:]
    return [
        min(b1[0], b2[0]),
        min(b1[1], b2[1]),
        max(b1[2], b2[2]),
        max(b1[3], b2[3]),
    ]


def normalize_text_for_debug(text: str) -> str:
    return text.replace("\n", "\\n").replace("\r", "\\r")


def font_name_hints(font_name: str) -> Tuple[bool, bool]:
    """
    某些 PDF 不会把粗体 / 斜体写进 flags，只能从字体名补判。
    """
    if not font_name:
        return False, False

    f = font_name.lower()
    fn_raw = font_name

    bold = bool(
        re.search(
            r"(bold|black|heavy|demibold|demi\-|semibold|semi\-bold|[\-_]bd\b|\bbd[\-_])",
            f,
        )
    )
    if re.search(
        r"(simhei|sim\-hei|fzhei|fzht|stheit|stkaiti\-bd|dengxian.*bold|"
        r"yahei.*bold|yahei\s*bd|msyhbd|hyrun|sourcehan.*bold|noto.*bold|"
        r"思源黑体|蘭亭黑|兰亭黑)",
        f,
    ):
        bold = True
    if any(x in fn_raw for x in ("黑体", "粗体", "大黑", "中黑", "特黑")):
        bold = True

    italic = bool(re.search(r"(italic|oblique|slanted|[\-_]it\b|\bit[\-_])", f))
    if re.search(r"\b(bi|ib)\b", f):
        bold = True
        italic = True

    return bold, italic


def matrix_multiply(m1: Tuple[float, float, float, float, float, float],
                    m2: Tuple[float, float, float, float, float, float]) -> Tuple[float, float, float, float, float, float]:
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def matrix_apply_to_point(
    m: Tuple[float, float, float, float, float, float], x: float, y: float
) -> Tuple[float, float]:
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def tokenize_pdf_content_stream(text: str) -> List[str]:
    """
    轻量 tokenizer，只解析当前斜体检测所需的 PDF 操作符。
    """
    tokens: List[str] = []
    i = 0
    n = len(text)
    delimiters = set("[]<>()/{}%")

    while i < n:
        ch = text[i]

        if ch.isspace():
            i += 1
            continue

        if ch == "%":
            while i < n and text[i] not in "\r\n":
                i += 1
            continue

        if ch == "[":
            depth = 1
            j = i + 1
            while j < n and depth > 0:
                if text[j] == "[":
                    depth += 1
                elif text[j] == "]":
                    depth -= 1
                j += 1
            tokens.append(text[i:j])
            i = j
            continue

        if ch == "<":
            if i + 1 < n and text[i + 1] == "<":
                j = i + 2
                while j + 1 < n and text[j:j + 2] != ">>":
                    j += 1
                j = min(n, j + 2)
                tokens.append(text[i:j])
                i = j
                continue
            j = i + 1
            while j < n and text[j] != ">":
                j += 1
            j = min(n, j + 1)
            tokens.append(text[i:j])
            i = j
            continue

        if ch == "/":
            j = i + 1
            while j < n and (not text[j].isspace()) and text[j] not in "[]<>()/{}%":
                j += 1
            tokens.append(text[i:j])
            i = j
            continue

        j = i + 1
        while j < n and (not text[j].isspace()) and text[j] not in delimiters:
            j += 1
        tokens.append(text[i:j])
        i = j

    return tokens


def safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def collect_slanted_text_origins(page: fitz.Page) -> List[Tuple[float, float]]:
    """
    解析页面内容流，找出使用倾斜文字矩阵（Tm）的文本起点。
    这类“伪斜体”在 rawdict 里通常不会反映到 span.flags。
    """
    doc = page.parent
    if doc is None:
        return []

    content_refs = page.get_contents()
    if isinstance(content_refs, int):
        content_refs = [content_refs]

    italic_origins: List[Tuple[float, float]] = []
    ctm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    ctm_stack: List[Tuple[float, float, float, float, float, float]] = []
    text_matrix: Optional[Tuple[float, float, float, float, float, float]] = None
    operands: List[str] = []

    for xref in content_refs:
        data = doc.xref_stream(xref)
        stream = data.decode("latin1", "ignore")
        for token in tokenize_pdf_content_stream(stream):
            if token == "q":
                ctm_stack.append(ctm)
                operands.clear()
                continue
            if token == "Q":
                if ctm_stack:
                    ctm = ctm_stack.pop()
                operands.clear()
                continue
            if token == "cm":
                nums = [safe_float(v) for v in operands[-6:]]
                if len(nums) == 6 and all(v is not None for v in nums):
                    ctm = matrix_multiply(ctm, tuple(nums))  # type: ignore[arg-type]
                operands.clear()
                continue
            if token == "BT":
                text_matrix = None
                operands.clear()
                continue
            if token == "ET":
                text_matrix = None
                operands.clear()
                continue
            if token == "Tm":
                nums = [safe_float(v) for v in operands[-6:]]
                if len(nums) == 6 and all(v is not None for v in nums):
                    text_matrix = tuple(nums)  # type: ignore[assignment]
                operands.clear()
                continue
            if token in {"Td", "TD"}:
                nums = [safe_float(v) for v in operands[-2:]]
                if text_matrix is not None and len(nums) == 2 and all(v is not None for v in nums):
                    text_matrix = matrix_multiply(text_matrix, (1.0, 0.0, 0.0, 1.0, nums[0], nums[1]))  # type: ignore[arg-type]
                operands.clear()
                continue
            if token in {"Tj", "TJ"}:
                if text_matrix is not None:
                    a, b, c, d, e, f = text_matrix
                    if abs(b) > 1e-6 or abs(c) > 1e-6:
                        italic_origins.append(matrix_apply_to_point(ctm, e, f))
                operands.clear()
                continue
            if token in {"Tf", "Tc", "Tw", "Tz", "TL", "Ts", "Tr", "re", "W", "W*", "n", "f", "RG", "rg", "gs", "BDC", "EMC"}:
                operands.clear()
                continue

            operands.append(token)

    return italic_origins


def origin_matches_any(
    origin: Any,
    candidates: List[Tuple[float, float]],
    tolerance: float = 1.0,
    y_tolerance: Optional[float] = None,
) -> bool:
    if not (isinstance(origin, (list, tuple)) and len(origin) >= 2):
        return False
    ox = safe_float(origin[0])
    oy = safe_float(origin[1])
    if ox is None or oy is None:
        return False

    y_tol = tolerance if y_tolerance is None else y_tolerance
    for cx, cy in candidates:
        if abs(ox - cx) <= tolerance and abs(oy - cy) <= y_tol:
            return True
    return False


def collect_slanted_char_origins(page: fitz.Page) -> List[Tuple[float, float]]:
    """
    先从内容流里拿到倾斜文本起点，再映射到 texttrace 的字符级 origin。
    """
    slanted_origins = collect_slanted_text_origins(page)
    if not slanted_origins:
        return []

    italic_chars: List[Tuple[float, float]] = []
    for trace in page.get_texttrace():
        chars = trace.get("chars") or []
        if not chars:
            continue
        first = chars[0]
        if len(first) < 3:
            continue
        if origin_matches_any(first[2], slanted_origins, tolerance=1.0, y_tolerance=1e9):
            for ch in chars:
                if len(ch) >= 3:
                    ox, oy = ch[2]
                    italic_chars.append((float(ox), float(oy)))
    return italic_chars


def split_span_by_italic_chars(
    span: Dict[str, Any],
    italic_char_origins: List[Tuple[float, float]],
) -> List[Dict[str, Any]]:
    """
    rawdict 有时会把正常字和伪斜体字合并进一个 span，这里按字符拆开。
    """
    chars = span.get("chars", [])
    if not chars or not italic_char_origins:
        return [span]

    groups: List[Tuple[bool, List[Dict[str, Any]]]] = []
    for ch in chars:
        ch_origin = ch.get("origin")
        is_italic = origin_matches_any(ch_origin, italic_char_origins, tolerance=1.0)
        if groups and groups[-1][0] == is_italic:
            groups[-1][1].append(ch)
        else:
            groups.append((is_italic, [ch]))

    if len(groups) == 1:
        only_italic = groups[0][0]
        if only_italic:
            new_span = dict(span)
            new_span["_force_italic"] = True
            return [new_span]
        return [span]

    out: List[Dict[str, Any]] = []
    for is_italic, grouped_chars in groups:
        new_span = dict(span)
        new_span["chars"] = grouped_chars
        new_span["text"] = get_char_text(grouped_chars)
        first_origin = grouped_chars[0].get("origin")
        if first_origin is not None:
            new_span["origin"] = first_origin

        bbox: Optional[List[float]] = None
        for ch in grouped_chars:
            ch_bbox = ch.get("bbox")
            if isinstance(ch_bbox, tuple):
                ch_bbox = list(ch_bbox)
            if isinstance(ch_bbox, list) and len(ch_bbox) >= 4:
                bbox = bbox_union(bbox, [float(v) for v in ch_bbox])
        if bbox is not None:
            new_span["bbox"] = bbox

        if is_italic:
            new_span["_force_italic"] = True
        out.append(new_span)

    return out


def span_to_run(
    span: Dict[str, Any],
    line: Dict[str, Any],
    slanted_origins: Optional[List[Tuple[float, float]]] = None,
    horizontal_decorations: Optional[List[List[float]]] = None,
) -> Dict[str, Any]:
    """
    把 span 转成 run。
    run 是最小样式片段。
    """
    flags_val = int(span.get("flags", 0))
    char_flags_val = get_char_flags(span)
    chars = span.get("chars", [])
    text = get_char_text(chars) if chars else span.get("text", "")

    font_name = str(span.get("font") or "")
    font_bold, font_italic = font_name_hints(font_name)

    is_sup = has_flag(flags_val, TEXT_FONT_SUPERSCRIPT)
    is_sub = infer_subscript(span, line)
    is_bold = has_flag(flags_val, TEXT_FONT_BOLD) or has_flag(char_flags_val, TEXT_CHAR_BOLD) or font_bold

    explicit_italic = has_flag(flags_val, TEXT_FONT_ITALIC) or font_italic
    inferred_italic = bool(span.get("_force_italic")) or origin_matches_any(
        span.get("origin"), slanted_origins or []
    )

    # 上下标优先于启发式斜体，避免把化学式/同位素里的下标误判成 italic。
    is_italic = explicit_italic or (inferred_italic and not (is_sup or is_sub))

    color_rgb = pdf_int_color_to_rgb_tuple(span.get("color"))
    color_hex = rgb_to_hex(color_rgb)

    explicit_underline = bool(span.get("underline", False) or span.get("underlined", False))
    underline = bool(
        explicit_underline
        or (
            has_flag(char_flags_val, TEXT_CHAR_UNDERLINE)
            and has_visual_underline(span, horizontal_decorations)
        )
    )
    overline = bool(span.get("overline", False))
    strikeout = bool(
        span.get("strikeout", False)
        or span.get("strikethrough", False)
        or span.get("strike-through", False)
        or has_flag(char_flags_val, TEXT_CHAR_STRIKEOUT)
    )

    run = {
        "text": text,
        "html": apply_html_style(
            text=text,
            bold=is_bold,
            italic=is_italic,
            sup=is_sup,
            sub=is_sub,
            underline=underline,
            strikeout=strikeout,
            overline=overline,
            color_hex=color_hex,
        ),
        "markdown": apply_markdown_style(
            text=text,
            bold=is_bold,
            italic=is_italic,
            sup=is_sup,
            sub=is_sub,
            underline=underline,
            strikeout=strikeout,
            overline=overline,
        ),
        "font": font_name,
        "size": span.get("size"),
        "font_flags": flags_val,
        "char_flags": char_flags_val,
        "bold": is_bold,
        "italic": is_italic,
        "serif": has_flag(flags_val, TEXT_FONT_SERIFED),
        "monospaced": has_flag(flags_val, TEXT_FONT_MONOSPACED),
        "superscript": is_sup,
        "subscript": is_sub,
        "color_rgb": color_rgb,
        "color_hex": color_hex,
        "underline": underline,
        "overline": overline,
        "strikeout": strikeout,
        "bbox": span.get("bbox"),
        "origin": span.get("origin"),
        "ascender": span.get("ascender"),
        "descender": span.get("descender"),
        "raw_span": span,
    }
    return run


def should_insert_space_between(prev_run: Dict[str, Any], curr_run: Dict[str, Any]) -> bool:
    """
    是否需要在两个 run 之间自动补空格。
    当前默认保守处理：不主动补空格。

    你后续如果发现英文场景经常丢空格，可以把这里打开。
    """
    _ = prev_run, curr_run
    return False


def is_same_visual_line(prev_item: Dict[str, Any], curr_run: Dict[str, Any]) -> bool:
    """
    判断是否还在同一视觉行。
    """
    prev_bbox = prev_item.get("bbox")
    curr_bbox = curr_run.get("bbox")
    if not prev_bbox or not curr_bbox:
        return True

    prev_y0, prev_y1 = prev_bbox[1], prev_bbox[3]
    curr_y0, curr_y1 = curr_bbox[1], curr_bbox[3]

    prev_h = max(1.0, prev_y1 - prev_y0)
    curr_h = max(1.0, curr_y1 - curr_y0)
    avg_h = (prev_h + curr_h) / 2.0

    prev_cy = (prev_y0 + prev_y1) / 2.0
    curr_cy = (curr_y0 + curr_y1) / 2.0

    return abs(prev_cy - curr_cy) <= avg_h * 0.8


def should_merge_run(prev_item: Dict[str, Any], curr_run: Dict[str, Any]) -> bool:
    """
    判断当前 run 是否应并入当前 item。

    合并策略:
    1. 必须是同一视觉行
    2. 水平距离不能太大
    3. 上标/下标允许和正文合并
    """
    prev_bbox = prev_item.get("bbox")
    curr_bbox = curr_run.get("bbox")

    if not is_same_visual_line(prev_item, curr_run):
        return False

    if not prev_bbox or not curr_bbox:
        return True

    prev_x1 = prev_bbox[2]
    curr_x0 = curr_bbox[0]

    prev_h = max(1.0, prev_bbox[3] - prev_bbox[1])
    curr_h = max(1.0, curr_bbox[3] - curr_bbox[1])
    avg_h = (prev_h + curr_h) / 2.0

    gap = curr_x0 - prev_x1

    # gap <= 负值: bbox 有重叠，允许合并
    # gap 较小: 相邻内容，允许合并
    if gap <= avg_h * 1.2:
        return True

    return False


def create_item_from_run(run: Dict[str, Any], page: int, block_no: int, line_no: int) -> Dict[str, Any]:
    return {
        "page": page,
        "block_no": block_no,
        "line_no": line_no,
        "text": run["text"],
        "html": run["html"],
        "markdown": run["markdown"],
        "bbox": run["bbox"][:] if isinstance(run.get("bbox"), list) else run.get("bbox"),
        "runs": [run],
    }


def append_run_to_item(item: Dict[str, Any], run: Dict[str, Any]) -> None:
    if should_insert_space_between(item["runs"][-1], run):
        item["text"] += " "
        item["html"] += " "
        item["markdown"] += " "

    item["text"] += run["text"]
    item["html"] += run["html"]
    item["markdown"] += run["markdown"]
    item["bbox"] = bbox_union(item.get("bbox"), run.get("bbox"))
    item["runs"].append(run)


def merge_runs_into_items(runs: List[Dict[str, Any]], page: int, block_no: int, line_no: int) -> List[Dict[str, Any]]:
    """
    将同一行中的 runs 合并成 item。
    """
    if not runs:
        return []

    items: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    for run in runs:
        if current is None:
            current = create_item_from_run(run, page, block_no, line_no)
            continue

        if should_merge_run(current, run):
            append_run_to_item(current, run)
        else:
            items.append(current)
            current = create_item_from_run(run, page, block_no, line_no)

    if current is not None:
        items.append(current)

    return items


def extract_pdf_content_layout(pdf_path: str) -> List[Dict[str, Any]]:
    """
    提取 PDF 内容布局。
    返回合并后的 item 列表。
    """
    doc = fitz.open(pdf_path)
    all_results: List[Dict[str, Any]] = []

    # RAWDICT 最适合做细粒度文本样式分析
    flags = fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_PRESERVE_IMAGES
    try:
        flags |= fitz.TEXT_COLLECT_STYLES
    except Exception:
        # 某些版本可能没有这个常量
        pass

    for page_index, page in enumerate(doc):
        raw = page.get_text("rawdict", flags=flags)
        slanted_origins = collect_slanted_text_origins(page)
        italic_char_origins = collect_slanted_char_origins(page)
        horizontal_decorations = collect_horizontal_decorations(page)

        for block_no, block in enumerate(raw.get("blocks", [])):
            if block.get("type") != 0:
                continue

            for line_no, line in enumerate(block.get("lines", [])):
                runs: List[Dict[str, Any]] = []

                for span in line.get("spans", []):
                    split_spans = split_span_by_italic_chars(span, italic_char_origins)
                    for split_span in split_spans:
                        run = span_to_run(
                            split_span,
                            line,
                            slanted_origins=slanted_origins,
                            horizontal_decorations=horizontal_decorations,
                        )
                        if run["text"] == "":
                            continue
                        runs.append(run)

                line_items = merge_runs_into_items(
                    runs=runs,
                    page=page_index + 1,
                    block_no=block_no,
                    line_no=line_no,
                )
                all_results.extend(line_items)

    doc.close()
    return all_results


def save_json(data: Any, out_path: str) -> None:
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def print_preview(items: List[Dict[str, Any]], limit: int = 20) -> None:
    print(f"共提取 {len(items)} 个对象，预览前 {min(limit, len(items))} 个：")
    for i, item in enumerate(items[:limit], start=1):
        preview = {
            "index": i,
            "page": item.get("page"),
            "block_no": item.get("block_no"),
            "line_no": item.get("line_no"),
            "text": item.get("text"),
            "html": item.get("html"),
            "markdown": item.get("markdown"),
            "bbox": item.get("bbox"),
            "runs_count": len(item.get("runs", [])),
        }
        print(json.dumps(preview, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    pdf_path = "./Datas/uploads/16065370903852373932/测试文档_创世纪.pdf"   # 改成你的 PDF 路径
    out_json = "pdf_content_layout.json"

    results = extract_pdf_content_layout(pdf_path)
    save_json(results, out_json)
    print_preview(results, limit=20)

    print(f"\n结果已保存到: {out_json}")
