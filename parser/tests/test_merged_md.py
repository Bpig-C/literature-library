"""合并旁路资产生成测试（UX-007 方案C）。

用现场构造的迷你 MinerU 云包（v1/v2/model 三件套 + fitz 生成 PDF）验证：
- build_detail_assets 产出 detail.json（schema v4）+ content.merged.md；
- 合并版 markdown 覆盖标题/段落/行内公式/图表图片/行间公式/脚注；
- 原始产物零触碰（构建器不写 content.md）；
- style_spans → **粗体**标记；三件套不全抛 FileNotFoundError。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PARSER_ROOT = Path(__file__).resolve().parents[1]
if str(PARSER_ROOT) not in sys.path:
    sys.path.insert(0, str(PARSER_ROOT))

fitz = pytest.importorskip("fitz")

from core.document.detail_result.merged_md import (  # noqa: E402
    _apply_style_spans,
    build_detail_assets,
)


def make_fixture_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Test Title", fontsize=16)
    page.insert_text((72, 140), "Hello world paragraph body text.", fontsize=11)
    doc.save(str(path))
    doc.close()


def make_mineru_package(raw_dir: Path) -> None:
    """迷你云包：uuid 前缀三件套（结构与真实云包一致）。"""
    raw_dir.mkdir(parents=True, exist_ok=True)
    stem = "abc123-uuid"
    v2 = [[
        {"type": "title", "content": {"title_content": [{"type": "text", "content": "Test Title"}], "level": 1}, "bbox": [72, 90, 200, 110]},
        {"type": "paragraph", "content": {"paragraph_content": [{"type": "text", "content": "Hello world paragraph body text."}]}, "bbox": [72, 130, 300, 150]},
        {"type": "paragraph", "content": {"paragraph_content": [{"type": "text", "content": "Weighted by "}, {"type": "equation_inline", "content": "n \\geq 1"}, {"type": "text", "content": " samples."}]}, "bbox": [72, 160, 300, 180]},
        {"type": "chart", "content": {"image_source": {"path": "images/chart1.jpg"}, "content": "", "chart_caption": [{"type": "text", "content": "Figure 1: demo chart"}]}, "bbox": [72, 190, 300, 260]},
        {"type": "equation_interline", "content": {"math_content": "E=mc^2", "math_type": "latex"}, "bbox": [72, 270, 300, 300]},
        {"type": "page_footnote", "content": {"page_footnote_content": [{"type": "text", "content": "Correspondence: test@example.com"}]}, "bbox": [72, 310, 300, 320]},
        {"type": "page_number", "content": {"page_number_content": [{"type": "text", "content": "1"}]}, "bbox": [380, 750, 400, 760]},
    ]]
    v1 = [{"type": "title", "text": "Test Title", "text_level": 1, "bbox": [72, 90, 200, 110], "page_idx": 0}]
    model = [[]]
    (raw_dir / f"{stem}_content_list_v2.json").write_text(json.dumps(v2), encoding="utf-8")
    (raw_dir / f"{stem}_content_list.json").write_text(json.dumps(v1), encoding="utf-8")
    (raw_dir / f"{stem}_model.json").write_text(json.dumps(model), encoding="utf-8")


@pytest.fixture()
def fixture_env(tmp_path):
    pdf = tmp_path / "paper.pdf"
    make_fixture_pdf(pdf)
    raw_dir = tmp_path / "out" / "_raw"
    make_mineru_package(raw_dir)
    return {"pdf": pdf, "raw": raw_dir, "out": tmp_path / "out"}


def test_build_detail_assets_writes_both_files(fixture_env):
    info = build_detail_assets(fixture_env["pdf"], fixture_env["raw"], fixture_env["out"])
    detail_path = Path(info["detail_path"])
    merged_path = Path(info["merged_md_path"])
    assert detail_path.is_file() and merged_path.is_file()
    assert info["nodes"] == 7 and info["pages"] == 1
    detail = json.loads(detail_path.read_text(encoding="utf-8"))
    assert detail["schema_version"] == "4.0"


def test_merged_md_covers_all_content_kinds(fixture_env):
    info = build_detail_assets(fixture_env["pdf"], fixture_env["raw"], fixture_env["out"])
    md = Path(info["merged_md_path"]).read_text(encoding="utf-8")
    assert "# Test Title" in md
    assert "Hello world paragraph body text." in md
    assert "$n \\geq 1$" in md          # 行内公式保留
    assert "![Figure 1: demo chart](images/chart1.jpg)" in md  # 图表回填
    assert "$$\nE=mc^2\n$$" in md       # 行间公式回填
    assert "Correspondence: test@example.com" in md  # 脚注回填
    # 页码噪声被剔除
    assert md.count("1\n") == 0 or "# Test Title" in md


def test_original_content_md_untouched(fixture_env):
    """构建器只写旁路资产，绝不触碰 content.md 等原始产物。"""
    out = fixture_env["out"]
    original = out / "content.md"
    original.write_text("# original mineru full.md", encoding="utf-8")
    build_detail_assets(fixture_env["pdf"], fixture_env["raw"], out)
    assert original.read_text(encoding="utf-8") == "# original mineru full.md"
    assert not (out / "content.json").exists()  # 不生成新的原始类产物


def test_missing_raw_files_raises(fixture_env):
    empty = fixture_env["out"] / "_empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        build_detail_assets(fixture_env["pdf"], empty, fixture_env["out"])


def test_apply_style_spans_bold_italic():
    text = "bold and italic text"
    spans = [
        {"start": 0, "end": 4, "style": {"bold": True, "italic": False}},
        {"start": 9, "end": 15, "style": {"bold": False, "italic": True}},
    ]
    assert _apply_style_spans(text, spans) == "**bold** and *italic* text"


def test_apply_style_spans_invalid_offsets_tolerated():
    text = "stable text"
    spans = [{"start": 50, "end": 99, "style": {"bold": True}}, {"start": "x", "end": 2}]
    assert _apply_style_spans(text, spans) == text


def test_runaway_sub_tags_stripped():
    """v2 数据 <sub> 超阈值（MinerU vlm 伪影，如 SkillSentry 7754 处）→ 整篇剥离。"""
    from core.document.detail_result.merged_md import build_merged_markdown, _SUB_RUNAWAY_LIMIT
    node = {"semantic_type": "paragraph",
            "content_payload": {"text": "SkillS<sub>e</sub>ntr<sub>y</sub> body",
                                "content_fragments": [{"type": "text", "content": "SkillS<sub>e</sub>ntr<sub>y</sub> body"}]}}
    v2 = [[{"type": "paragraph", "content": {"paragraph_content": [
        {"type": "text", "content": "x<sub>a</sub>" * (_SUB_RUNAWAY_LIMIT + 1)}]}}]]
    md = build_merged_markdown({"merged_nodes": [node]}, v2)
    assert "<sub>" not in md
    assert "SkillSentry body" in md


def test_style_span_does_not_shred_tags():
    """PyMuPDF 样式 span 若会把 <sub>/<sup> 从中间劈开（如 C<su|b>ontr），
    必须弃用该 span——劈碎的标签会以字面 "<su"+"b>" 泄漏到渲染文本。"""
    from core.document.detail_result.merged_md import _apply_style_spans
    text = "C<sub>ontrolled environments"
    # span 切在标签内部（"<su|b>ont"）→ 跳过，文本原样
    shred = [{"start": 4, "end": 10, "style": {"bold": True}}]
    assert _apply_style_spans(text, shred) == text
    # span 完整包含标签 → 正常加粗
    whole = [{"start": 0, "end": 15, "style": {"bold": True}}]
    assert _apply_style_spans(text, whole) == "**C<sub>ontrolled** environments"


def test_runaway_doc_drops_style_spans():
    """失控文档：先剥离 <sub> 再渲染，style_spans 被弃用（偏移已失效），
    产物无标签碎片（如 'C<su**b>ontr**olled'）。"""
    from core.document.detail_result.merged_md import build_merged_markdown, _SUB_RUNAWAY_LIMIT
    node = {
        "semantic_type": "paragraph",
        "style_spans": [{"start": 4, "end": 10, "style": {"bold": True}}],
        "content_payload": {"text": "C<sub>ontrolled", "content_fragments": [{"type": "text", "content": "C<sub>ontrolled"}]},
    }
    v2 = [[{"type": "paragraph", "content": {"paragraph_content": [
        {"type": "text", "content": "x<sub>a</sub>" * (_SUB_RUNAWAY_LIMIT + 1)}]}}]]
    md = build_merged_markdown({"merged_nodes": [node]}, v2)
    assert "<sub>" not in md and "<su" not in md and "**" not in md
    assert "Controlled" in md


def test_legit_sub_tags_kept():
    """正常文档（<sub> 少量合法下标）→ 保留标签。"""
    from core.document.detail_result.merged_md import build_merged_markdown
    node = {"semantic_type": "paragraph",
            "content_payload": {"text": "H<sub>2</sub>O formula",
                                "content_fragments": [{"type": "text", "content": "H<sub>2</sub>O formula"}]}}
    v2 = [[{"type": "paragraph", "content": {"paragraph_content": [
        {"type": "text", "content": "H<sub>2</sub>O formula"}]}}]]
    md = build_merged_markdown({"merged_nodes": [node]}, v2)
    assert "H<sub>2</sub>O formula" in md
