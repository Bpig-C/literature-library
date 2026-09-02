"""PyMuPDF 图片抽取测试（UX-002 方案C）。

用 fitz 现场生成带栅格图的 PDF，验证：
- 图片落盘到 output_dir/images/，content.md 按页追加 ![](images/..) 引用；
- 同一图跨页引用只落盘一次（xref 去重）；
- 图标级小图被过滤；
- 纯文本 PDF 不产生 images 目录、无图片引用。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PARSER_ROOT = Path(__file__).resolve().parents[1]
if str(PARSER_ROOT) not in sys.path:
    sys.path.insert(0, str(PARSER_ROOT))

fitz = pytest.importorskip("fitz")

from core.mineru.base_client import ParseRequest  # noqa: E402
from core.mineru.pymupdf_client import PyMuPDFClient  # noqa: E402


def _make_png(width: int = 200, height: int = 120, gray: int = 90) -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height))
    pix.clear_with(gray)
    data = pix.tobytes("png")
    pix = None
    return data


def _make_pdf(path: Path, pages: int = 1, img_bytes: bytes | None = None,
              img_rect=(72, 120, 272, 240)) -> None:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 100), f"Page {i + 1} text. " * 8, fontsize=11)
        if img_bytes:
            page.insert_image(fitz.Rect(*img_rect), stream=img_bytes)
    doc.save(str(path))
    doc.close()


def _parse(pdf_path: Path, out_dir: Path) -> tuple[bool, str, dict]:
    client = PyMuPDFClient()
    ok, msg = client.parse_pdf(ParseRequest(pdf_path=pdf_path, output_dir=out_dir))
    return ok, msg, client.last_metrics


def _md_refs(md_text: str) -> list[str]:
    return [ln for ln in md_text.splitlines() if "](images/" in ln]


def test_raster_image_extracted_to_images_dir(tmp_path):
    pdf = tmp_path / "with_img.pdf"
    _make_pdf(pdf, img_bytes=_make_png())
    out = tmp_path / "out"
    ok, msg, metrics = _parse(pdf, out)
    assert ok
    assert metrics["images"] == 1
    img_dir = out / "images"
    assert img_dir.is_dir() and list(img_dir.iterdir())
    md = (out / "content.md").read_text(encoding="utf-8")
    refs = _md_refs(md)
    assert len(refs) == 1
    # 引用指向的文件确实存在
    name = refs[0].split("](images/")[1].rstrip(")")
    assert (img_dir / name).is_file()


def test_same_image_across_pages_saved_once(tmp_path):
    pdf = tmp_path / "dup_img.pdf"
    _make_pdf(pdf, pages=2, img_bytes=_make_png())
    out = tmp_path / "out"
    ok, _, metrics = _parse(pdf, out)
    assert ok
    assert metrics["images"] == 1  # 跨页去重：只落盘一次
    refs = _md_refs((out / "content.md").read_text(encoding="utf-8"))
    assert len(refs) == 1  # 引用出现在首次出现的页面


def test_tiny_icon_image_filtered(tmp_path):
    pdf = tmp_path / "icon.pdf"
    _make_pdf(pdf, img_bytes=_make_png(width=20, height=20))
    out = tmp_path / "out"
    ok, _, metrics = _parse(pdf, out)
    assert ok
    assert metrics["images"] == 0  # 图标级小图被过滤
    assert not (out / "images").exists()
    assert _md_refs((out / "content.md").read_text(encoding="utf-8")) == []


def test_text_only_pdf_has_no_images_dir(tmp_path):
    pdf = tmp_path / "text_only.pdf"
    _make_pdf(pdf, pages=3)
    out = tmp_path / "out"
    ok, _, metrics = _parse(pdf, out)
    assert ok
    assert metrics["images"] == 0
    assert not (out / "images").exists()
    md = (out / "content.md").read_text(encoding="utf-8")
    assert "](images/" not in md
    # 文本仍在（回归：图片逻辑不破坏原文本抽取）
    assert "Page 3 text." in md
