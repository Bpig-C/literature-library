"""
PyMuPDF 文本层直抽客户端（P3.5 Phase E 路由：文本层 PDF 走本地抽取，扫描型走 cloud vlm）。

对**有文本层**的 born-digital PDF，直接用 PyMuPDF 抽取嵌入文本，产出 content.md/content.json：
- 精准：公式/符号按嵌入字形，无 pipeline 间距伪影；
- 本地/免费/快：不耗 cloud 额度；
- 同步抽取页面实际绘制的栅格图片到 images/，并在 content.md 按页追加 `![](images/...)`
  引用（与 cloud vlm 产物契约一致）。矢量图表不在此路径覆盖，需要时可用
  backend=vlm 强制重解析（见 router.route_and_parse 的 backend 参数）。
代价：丢版面结构（双栏阅读顺序可能错乱、表格变平文本）——故路由层在抽取后做轻量质检，
不合格则回退 cloud vlm。

实现 PdfParseClient.parse_pdf(req)->(bool,msg) 接口；质检指标挂在 self.last_metrics。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from .base_client import ParseRequest, PdfParseClient

logger = logging.getLogger(__name__)

# 文本层判定阈值（与 cloud_client._detect_is_ocr 的阈值保持一致量级）
TEXT_LAYER_AVG_CHARS_PER_PAGE = 50
# 质检：乱码/不可读字符占比超过此比例视为抽取质量差 → 回退
GARBLE_RATIO_LIMIT = 0.15
# 质检：平均每页字符过低也视为差
MIN_AVG_CHARS_PER_PAGE = 200

# 视为“乱码/不可读”的字符（控制字符、替换符等；不含常见空白）
_GARBLE_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f�]")

# 双栏阅读顺序检测：单页列切换次数超过此值视为“列交错”（阅读顺序乱）
_COLUMN_SWITCH_LIMIT = 6
# 双栏页中“顺序乱”页占比超过此值 → 整篇视为阅读顺序不可接受
_BAD_2COL_PAGE_RATIO = 0.5

# 图片抽取阈值：短于该像素边长的图视为图标/装饰（跳过）
_IMAGE_MIN_PIXEL = 64
# 图片放置 bbox 短边小于该 pt 值视为不可见细线（跳过）
_IMAGE_MIN_BBOX_PT = 8.0
# extract_image 的 jpeg 扩展名归一为 jpg（浏览器/一致性）
_JPEG_EXT = "jpg"


def column_switch_count(blocks: list[tuple], width: float) -> int:
    """统计一页文本块的列切换次数（纯函数，便于测试）。

    blocks: [(x0,y0,x1,y1,text), ...]，按 PyMuPDF 给出的阅读顺序。
    列归属：x1<width*0.55 → L；x0>width*0.45 → R；跨中线 → M(忽略)。
    列交错(L,R,L,R...)会产生大量切换；正常双栏(L...L,R...R)约 1 次。
    """
    seq = []
    for b in blocks:
        x0, y0, x1, y1 = b[0], b[1], b[2], b[3]
        txt = b[4] if len(b) > 4 else ""
        if not (str(txt).strip()) or len(str(txt).strip()) < 2:
            continue
        if x1 < width * 0.55:
            seq.append("L")
        elif x0 > width * 0.45:
            seq.append("R")
        # else: 跨中线 M，忽略
    return sum(1 for i in range(1, len(seq)) if seq[i] != seq[i - 1])


def reading_order_ok(pages_blocks: list[tuple[list, float]]) -> tuple[bool, dict]:
    """判断全文双栏阅读顺序是否可接受。

    pages_blocks: [(blocks, width), ...] 每页一块列表 + 页宽。
    返回 (ok, {two_col_pages, bad_pages, max_switches})。
    只对“同时有左右栏块”的双栏页判别；单栏页不参与。
    """
    two_col = 0
    bad = 0
    max_sw = 0
    for blocks, width in pages_blocks:
        cols = []
        for b in blocks:
            txt = b[4] if len(b) > 4 else ""
            if not str(txt).strip() or len(str(txt).strip()) < 2:
                continue
            if b[2] < width * 0.55:
                cols.append("L")
            elif b[0] > width * 0.45:
                cols.append("R")
        if not (cols.count("L") >= 2 and cols.count("R") >= 2):
            continue  # 非双栏页
        two_col += 1
        sw = column_switch_count(blocks, width)
        max_sw = max(max_sw, sw)
        if sw > _COLUMN_SWITCH_LIMIT:
            bad += 1
    if two_col == 0:
        return True, {"two_col_pages": 0, "bad_pages": 0, "max_switches": max_sw}
    ok = (bad / two_col) < _BAD_2COL_PAGE_RATIO
    return ok, {"two_col_pages": two_col, "bad_pages": bad, "max_switches": max_sw}


def avg_chars_per_page(pdf_path: Path) -> tuple[int, float]:
    """返回 (页数, 平均每页可提取字符数)。打不开/无文本层返回 (0, 0.0)。"""
    try:
        import fitz  # PyMuPDF
    except Exception as exc:
        logger.debug("PyMuPDF 不可用：%s", exc)
        return 0, 0.0
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:
        logger.debug("打开 PDF 失败 %s: %s", pdf_path.name, exc)
        return 0, 0.0
    try:
        pages = doc.page_count or 1
        total = sum(len(page.get_text() or "") for page in doc)  # type: ignore[attr-defined]
        return pages, total / max(pages, 1)
    except Exception as exc:
        logger.debug("抽取失败 %s: %s", pdf_path.name, exc)
        return 0, 0.0
    finally:
        try:
            doc.close()
        except Exception:
            pass


def has_text_layer(pdf_path: Path, threshold: float = TEXT_LAYER_AVG_CHARS_PER_PAGE) -> bool:
    """是否为有文本层的 born-digital PDF（非扫描件）。"""
    _, avg = avg_chars_per_page(pdf_path)
    return avg >= threshold


def page_image_xrefs(page: Any) -> list[int]:
    """一页**实际绘制**的栅格图 xref 列表（页内去重 + 过滤图标/细线）。

    优先 get_image_info(xrefs=True)：基于显示列表，能覆盖 Form XObject 内嵌图，
    并带放置 bbox（可滤掉不可见细线）；不可用/失败回落 get_images(full=True)
    （仅资源字典，无 bbox，只按像素尺寸过滤）。
    """
    try:
        infos = page.get_image_info(xrefs=True)
    except Exception:  # noqa: BLE001 — 老版本/异常页兜底
        try:
            return sorted(
                {
                    int(img[0])
                    for img in page.get_images(full=True)
                    if max(int(img[2] or 0), int(img[3] or 0)) >= _IMAGE_MIN_PIXEL
                }
            )
        except Exception:  # noqa: BLE001
            return []
    seen: set[int] = set()
    out: list[int] = []
    for info in infos:
        try:
            xref = int(info.get("xref") or 0)
        except (TypeError, ValueError):
            continue
        if xref <= 0 or xref in seen:
            continue
        try:
            w = int(info.get("width") or 0)
            h = int(info.get("height") or 0)
            bbox = info.get("bbox") or (0, 0, 0, 0)
            bw = abs(float(bbox[2]) - float(bbox[0]))
            bh = abs(float(bbox[3]) - float(bbox[1]))
        except (TypeError, ValueError):
            continue
        if max(w, h) < _IMAGE_MIN_PIXEL:
            continue  # 图标/装饰
        if min(bw, bh) < _IMAGE_MIN_BBOX_PT:
            continue  # 不可见细线
        seen.add(xref)
        out.append(xref)
    return out


def extract_image_data(doc: Any, xref: int) -> tuple[bytes, str]:
    """按 xref 提取图片，返回 (字节, 扩展名)。

    带 SMask（透明通道）的图合成 alpha 后转 PNG；其余保留原始编码字节
    （无损、体积小）。CMYK 等异常编码走 Pixmap 兜底转 RGB PNG。
    """
    import fitz  # noqa: PLC0415（惰性，与模块约定一致）

    info = doc.extract_image(xref)
    smask = int(info.get("smask") or 0)
    if smask > 0:
        base = fitz.Pixmap(doc, xref)
        mask = fitz.Pixmap(doc, smask)
        pix = fitz.Pixmap(base, mask)  # 合成透明通道
        try:
            return pix.tobytes("png"), "png"
        finally:
            pix = None
    ext = (info.get("ext") or "png").lower()
    ext = _JPEG_EXT if ext in ("jpeg", "jpg") else ext
    return info["image"], ext


def _extract_image_fallback(doc: Any, xref: int) -> tuple[bytes, str]:
    """extract_image 失败时的 Pixmap 兜底（CMYK→RGB，统一 PNG）。"""
    import fitz  # noqa: PLC0415

    pix = fitz.Pixmap(doc, xref)
    try:
        if pix.n - pix.alpha > 3:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        return pix.tobytes("png"), "png"
    finally:
        pix = None


class PyMuPDFClient(PdfParseClient):
    """文本层 PDF 本地直抽。仅适用于有文本层的 PDF；扫描型由路由层转交 cloud vlm。"""

    def __init__(self):
        self.last_metrics: dict[str, Any] = {}

    def parse_pdf(self, req: ParseRequest) -> tuple[bool, str]:
        output_dir = (req.output_dir if req.output_dir else req.pdf_path.parent).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        pages, avg = avg_chars_per_page(req.pdf_path)
        if pages == 0:
            self.last_metrics = {"ok": False, "reason": "无法打开/读取 PDF"}
            return False, "PyMuPDF 无法打开 PDF（可能损坏或非 PDF）"

        try:
            import fitz
        except Exception as exc:
            self.last_metrics = {"ok": False, "reason": f"PyMuPDF 未安装: {exc}"}
            return False, f"PyMuPDF 未安装: {exc}"

        doc = fitz.open(str(req.pdf_path))
        page_texts: list[tuple[int, str]] = []
        pages_blocks: list[tuple[list, float]] = []
        page_images: dict[int, list[str]] = {}  # 页码(0基) -> 图片文件名列表
        images_dir = output_dir / "images"
        images_saved = 0
        images_failed = 0
        seen_xrefs: set[int] = set()  # 跨页去重：同一图只在首次出现的页面落盘
        try:
            for i, page in enumerate(doc):
                page_texts.append((i + 1, page.get_text() or ""))
                width = page.rect.width
                raw_blocks = [tuple(b) for b in page.get_text("blocks") if b[6] == 0]
                pages_blocks.append((raw_blocks, width))
                names: list[str] = []
                for xref in page_image_xrefs(page):
                    if xref in seen_xrefs:
                        continue
                    seen_xrefs.add(xref)
                    try:
                        try:
                            data, ext = extract_image_data(doc, xref)
                        except Exception:  # noqa: BLE001 — 单图失败不中断整篇
                            data, ext = _extract_image_fallback(doc, xref)
                    except Exception:  # noqa: BLE001
                        images_failed += 1
                        continue
                    images_dir.mkdir(parents=True, exist_ok=True)
                    name = f"p{i + 1:03d}-x{xref}.{ext}"
                    (images_dir / name).write_bytes(data)
                    names.append(name)
                    images_saved += 1
                if names:
                    page_images[i] = names
        finally:
            doc.close()

        parts: list[str] = []
        for pg, txt in page_texts:
            chunk = txt.rstrip()
            for name in page_images.get(pg - 1, []):
                chunk += f"\n\n![{name}](images/{name})"
            parts.append(chunk)
        full_text = "\n\n".join(parts) + ("\n" if parts else "")

        total_chars = len(full_text)
        garble = len(_GARBLE_RE.findall(full_text))
        garble_ratio = garble / max(total_chars, 1)
        avg_now = total_chars / max(pages, 1)

        # 双栏阅读顺序检测（方案 B）
        order_ok, order_info = reading_order_ok(pages_blocks)

        metrics = {
            "ok": True,
            "pages": pages,
            "chars": total_chars,
            "avg_chars_per_page": round(avg_now, 1),
            "garble_ratio": round(garble_ratio, 4),
            "reading_order_ok": order_ok,
            "two_col_pages": order_info["two_col_pages"],
            "two_col_bad_pages": order_info["bad_pages"],
            "max_column_switches": order_info["max_switches"],
            "images": images_saved,
            "images_failed": images_failed,
        }
        self.last_metrics = metrics

        # 产出 content.md / content.json（契约位置 output_dir 根）
        (output_dir / "content.md").write_text(full_text, encoding="utf-8")
        (output_dir / "content.json").write_text(
            json.dumps({"source": "pymupdf", **metrics}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        msg = (f"✅ PyMuPDF 文本层抽取完成：{pages} 页 / {total_chars} 字符 / "
               f"imgs={images_saved} / garble={garble_ratio:.3f}")
        logger.info(msg)
        return True, msg

    @staticmethod
    def quality_ok(metrics: dict[str, Any]) -> bool:
        """根据抽取指标判断质量是否可接受（供路由层决定是否回退 vlm）。

        三重门：乱码率、字符率、双栏阅读顺序。任一不合格 → 回退 cloud vlm。
        """
        if not metrics.get("ok"):
            return False
        if metrics.get("garble_ratio", 1) > GARBLE_RATIO_LIMIT:
            return False
        if metrics.get("avg_chars_per_page", 0) < MIN_AVG_CHARS_PER_PAGE:
            return False
        # 双栏阅读顺序（仅当文档含双栏页时才判；reading_order_ok 缺省 True 容错旧指标）
        if metrics.get("reading_order_ok", True) is False:
            return False
        return True

    def is_parsed(self, folder_path: Path) -> bool:
        return self._check_parsed(folder_path)
