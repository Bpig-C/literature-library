"""
PyMuPDF 文本层直抽客户端（P3.5 Phase E 路由：文本层 PDF 走本地抽取，扫描型走 cloud vlm）。

对**有文本层**的 born-digital PDF，直接用 PyMuPDF 抽取嵌入文本，产出 content.md/content.json：
- 精准：公式/符号按嵌入字形，无 pipeline 间距伪影；
- 本地/免费/快：不耗 cloud 额度。
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
        try:
            page_texts = [(i + 1, (page.get_text() or "")) for i, page in enumerate(doc)]
        finally:
            doc.close()

        full_text = ""
        for _pg, txt in page_texts:
            full_text += txt.rstrip() + "\n\n"

        total_chars = len(full_text)
        garble = len(_GARBLE_RE.findall(full_text))
        garble_ratio = garble / max(total_chars, 1)
        avg_now = total_chars / max(pages, 1)

        metrics = {
            "ok": True,
            "pages": pages,
            "chars": total_chars,
            "avg_chars_per_page": round(avg_now, 1),
            "garble_ratio": round(garble_ratio, 4),
        }
        self.last_metrics = metrics

        # 产出 content.md / content.json（契约位置 output_dir 根）
        (output_dir / "content.md").write_text(full_text, encoding="utf-8")
        (output_dir / "content.json").write_text(
            json.dumps({"source": "pymupdf", **metrics}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        msg = f"✅ PyMuPDF 文本层抽取完成：{pages} 页 / {total_chars} 字符 / garble={garble_ratio:.3f}"
        logger.info(msg)
        return True, msg

    @staticmethod
    def quality_ok(metrics: dict[str, Any]) -> bool:
        """根据抽取指标判断质量是否可接受（供路由层决定是否回退 vlm）。"""
        if not metrics.get("ok"):
            return False
        if metrics.get("garble_ratio", 1) > GARBLE_RATIO_LIMIT:
            return False
        if metrics.get("avg_chars_per_page", 0) < MIN_AVG_CHARS_PER_PAGE:
            return False
        return True

    def is_parsed(self, folder_path: Path) -> bool:
        return self._check_parsed(folder_path)
