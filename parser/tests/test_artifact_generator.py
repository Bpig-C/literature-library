"""
单元测试 2：DocumentArtifactGenerator 逻辑
使用 fixtures/sample_content_list.json 作为假数据，不需要真实 PDF 或 MinerU。
运行：pytest tests/test_artifact_generator.py -v
"""
import json
import sys
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))

from core.document.artifact_generator import (
    DocumentArtifactGenerator,
    _sort_key,
    _try_build_content_entry,
    _is_bbox,
    _bbox_inside,
    _bbox_center_dist2,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_content_list.json"


# ---------------------------------------------------------------------------
# 辅助函数单元测试
# ---------------------------------------------------------------------------

def test_is_bbox():
    assert _is_bbox([0, 0, 100, 100])
    assert not _is_bbox([0, 0, 100])          # 长度不对
    assert not _is_bbox([0, 0, 100, "bad"])   # 类型不对


def test_bbox_inside():
    outer = [0.0, 0.0, 100.0, 100.0]
    inner = [10.0, 10.0, 90.0, 90.0]
    assert _bbox_inside(inner, outer)
    assert not _bbox_inside(outer, inner)     # 反过来不成立
    assert _bbox_inside(outer, outer)         # 相等时也成立


def test_bbox_center_dist2():
    a = [0.0, 0.0, 2.0, 2.0]   # center (1,1)
    b = [4.0, 4.0, 6.0, 6.0]   # center (5,5)
    assert abs(_bbox_center_dist2(a, b) - 32.0) < 1e-9


def test_sort_key_ordering():
    nodes = [
        {"page_idx": 1, "bbox": [72, 200, 400, 220]},
        {"page_idx": 0, "bbox": [72, 100, 400, 120]},
        {"page_idx": 0, "bbox": [72, 50, 300, 75]},
    ]
    nodes.sort(key=_sort_key)
    assert nodes[0]["page_idx"] == 0
    assert nodes[0]["bbox"][1] == 50     # top=50 先于 top=100


# ---------------------------------------------------------------------------
# _try_build_content_entry
# ---------------------------------------------------------------------------

def test_content_entry_text():
    node = {"type": "text", "text": "hello", "page_idx": 0,
            "element_id": "page0_elem0", "bbox": [0, 0, 100, 20]}
    entry = _try_build_content_entry(node)
    assert entry is not None
    assert entry["content_type"] == "text"
    assert entry["content"] == "hello"


def test_content_entry_table():
    node = {"type": "table", "table_body": "<table/>",
            "table_caption": ["cap"], "page_idx": 1,
            "element_id": "page1_elem0", "bbox": [0, 0, 100, 100]}
    entry = _try_build_content_entry(node)
    assert entry is not None
    assert entry["content"] == "<table/>"
    assert entry["table_caption"] == ["cap"]


def test_content_entry_image():
    node = {"type": "image", "img_path": "img/1.png",
            "page_idx": 0, "element_id": "page0_elem1",
            "bbox": [0, 0, 100, 100]}
    entry = _try_build_content_entry(node)
    assert entry is not None
    assert entry["content"] == "img/1.png"
    assert entry["image_caption"] == []


def test_content_entry_list():
    node = {"type": "list", "list_items": ["a", "b"],
            "page_idx": 2, "element_id": "page2_elem0",
            "bbox": [0, 0, 100, 50]}
    entry = _try_build_content_entry(node)
    assert entry["content"] == ["a", "b"]


def test_content_entry_missing_required_field():
    # table 没有 table_body → 返回 None
    node = {"type": "table", "page_idx": 0, "bbox": [0, 0, 100, 100]}
    assert _try_build_content_entry(node) is None


def test_content_entry_unknown_type_fallback():
    node = {"type": "unknown_type", "text": "fallback text",
            "page_idx": 0, "element_id": "p0e0", "bbox": [0, 0, 100, 20]}
    entry = _try_build_content_entry(node)
    assert entry is not None
    assert entry["content"] == "fallback text"


# ---------------------------------------------------------------------------
# build_content_json：用临时目录 + fixture 数据
# ---------------------------------------------------------------------------

def _make_temp_pdf_dir(stem: str = "test_doc") -> tuple[Path, Path]:
    """创建临时目录，放入 {stem}_content_list.json，返回 (pdf_path, tmpdir)。"""
    tmpdir = Path(tempfile.mkdtemp())
    content_list_path = tmpdir / f"{stem}_content_list.json"
    shutil.copy(FIXTURE, content_list_path)
    # 假的 PDF 路径（不需要真实文件，build_content_json 只读 json）
    fake_pdf = tmpdir / f"{stem}.pdf"
    fake_pdf.touch()
    return fake_pdf, tmpdir


def test_build_content_json_basic():
    fake_pdf, tmpdir = _make_temp_pdf_dir()
    try:
        result = DocumentArtifactGenerator.build_content_json(str(fake_pdf))
        assert isinstance(result, list)
        assert len(result) > 0

        types = {e["content_type"] for e in result}
        assert "text" in types
        assert "table" in types
        assert "image" in types
        assert "list" in types

        # 每个条目都有 element_id 和 page_idx
        for entry in result:
            assert "element_id" in entry
            assert "page_idx" in entry
    finally:
        shutil.rmtree(tmpdir)


def test_build_content_json_sorted():
    """结果应按 page_idx 升序。"""
    fake_pdf, tmpdir = _make_temp_pdf_dir()
    try:
        result = DocumentArtifactGenerator.build_content_json(str(fake_pdf))
        pages = [e["page_idx"] for e in result]
        assert pages == sorted(pages)
    finally:
        shutil.rmtree(tmpdir)


def test_build_content_json_unsupported_type():
    """非 PDF 文件返回空列表。"""
    result = DocumentArtifactGenerator.build_content_json("/tmp/fake.docx")
    assert result == []


# ---------------------------------------------------------------------------
# build_layout_json：layout_extractor 返回 [] (stub)，逻辑仍走完
# ---------------------------------------------------------------------------

def test_build_layout_json_stub():
    fake_pdf, tmpdir = _make_temp_pdf_dir()
    try:
        result = DocumentArtifactGenerator.build_layout_json(str(fake_pdf))
        assert isinstance(result, list)
        # stub 返回 []，所以没有 layout 节点可以 merge，结果就是原 content_tree
        assert len(result) > 0
        # layout.json 应该被写出来
        assert (tmpdir / "layout.json").exists()
    finally:
        shutil.rmtree(tmpdir)


def test_build_layout_json_cache():
    """第二次调用应命中 layout.json 缓存。"""
    fake_pdf, tmpdir = _make_temp_pdf_dir()
    try:
        r1 = DocumentArtifactGenerator.build_layout_json(str(fake_pdf))
        r2 = DocumentArtifactGenerator.build_layout_json(str(fake_pdf))
        assert r1 == r2
    finally:
        shutil.rmtree(tmpdir)


# ---------------------------------------------------------------------------
# build_annotated_file
# ---------------------------------------------------------------------------

def test_build_annotated_file_missing():
    """没有 _layout.pdf 时返回 success=False。"""
    fake_pdf, tmpdir = _make_temp_pdf_dir()
    try:
        result = DocumentArtifactGenerator.build_annotated_file(str(fake_pdf))
        assert result["success"] is False
        assert result["file_base64"] == ""
    finally:
        shutil.rmtree(tmpdir)


def test_build_annotated_file_present():
    """有 _layout.pdf 时返回 success=True + base64 内容。"""
    import base64
    fake_pdf, tmpdir = _make_temp_pdf_dir()
    try:
        # 放一个假的 layout pdf
        layout_pdf = tmpdir / "test_doc_layout.pdf"
        layout_pdf.write_bytes(b"%PDF-fake-content")

        result = DocumentArtifactGenerator.build_annotated_file(str(fake_pdf))
        assert result["success"] is True
        decoded = base64.b64decode(result["file_base64"])
        assert decoded == b"%PDF-fake-content"
    finally:
        shutil.rmtree(tmpdir)
