"""route_and_parse backend 覆盖与产物清理测试。

用假 client 验证（不触达 fitz/网络）：
- backend="vlm"/"pymupdf" 强制指定后端；
- 显式 pymupdf 质检不合格**不**回退 vlm（用户明确选择）；
- auto 保持 D13 原行为（文本层→pymupdf，质检不合格→回退 vlm）；
- 解析前清理已知产物、保留未知文件；output_dir 与 PDF 同目录时不清理。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PARSER_ROOT = Path(__file__).resolve().parents[1]
if str(PARSER_ROOT) not in sys.path:
    sys.path.insert(0, str(PARSER_ROOT))

from core.mineru import pymupdf_client as pypdf_mod  # noqa: E402
from core.mineru.router import route_and_parse  # noqa: E402


class FakeCloud:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = 0
        self.last_batch_id = "BATCH-1"

    def parse_pdf(self, req):
        self.calls += 1
        return self.ok, "cloud ok"


class FakePyMuPDF:
    def __init__(self, ok=True, quality_ok=True):
        self.ok = ok
        self.quality = quality_ok
        self.calls = 0
        self.last_metrics = {
            "ok": True,
            "garble_ratio": 0.0 if quality_ok else 0.9,
            "avg_chars_per_page": 500,
            "reading_order_ok": True,
        }

    def parse_pdf(self, req):
        self.calls += 1
        return self.ok, "pymupdf ok"


@pytest.fixture()
def stub_text_layer(monkeypatch):
    """has_text_layer 恒 True（不触达 fitz）。"""
    monkeypatch.setattr(pypdf_mod, "has_text_layer", lambda pdf_path, **kw: True)


def test_backend_vlm_forces_cloud(stub_text_layer, tmp_path):
    cloud, pymupdf = FakeCloud(), FakePyMuPDF()
    ok, _, used = route_and_parse(cloud, pymupdf, "x.pdf", tmp_path / "out", "en", backend="vlm")
    assert ok and used == "vlm"
    assert cloud.calls == 1 and pymupdf.calls == 0


def test_backend_pymupdf_no_fallback_on_bad_quality(stub_text_layer, tmp_path):
    cloud, pymupdf = FakeCloud(), FakePyMuPDF(quality_ok=False)
    ok, _, used = route_and_parse(cloud, pymupdf, "x.pdf", tmp_path / "out", "en", backend="pymupdf")
    assert ok and used == "pymupdf"
    assert pymupdf.calls == 1 and cloud.calls == 0  # 显式指定不回退


def test_backend_pymupdf_failure_reported_not_fallback(stub_text_layer, tmp_path):
    cloud, pymupdf = FakeCloud(), FakePyMuPDF(ok=False)
    ok, _, used = route_and_parse(cloud, pymupdf, "x.pdf", tmp_path / "out", "en", backend="pymupdf")
    assert not ok and used == "pymupdf"
    assert cloud.calls == 0


def test_auto_vlm_first_no_pymupdf(stub_text_layer, tmp_path):
    """auto（默认=双路合并）：vlm 成功时不碰本地 pymupdf。"""
    cloud, pymupdf = FakeCloud(), FakePyMuPDF()
    ok, _, used = route_and_parse(cloud, pymupdf, "x.pdf", tmp_path / "out", "en", backend=None)
    assert ok and used == "vlm"
    assert cloud.calls == 1 and pymupdf.calls == 0


def test_auto_vlm_failure_falls_back_pymupdf(stub_text_layer, tmp_path):
    cloud, pymupdf = FakeCloud(ok=False), FakePyMuPDF()
    ok, _, used = route_and_parse(cloud, pymupdf, "x.pdf", tmp_path / "out", "en", backend="auto")
    assert ok and used == "pymupdf"
    assert cloud.calls == 1 and pymupdf.calls == 1


def test_auto_vlm_fail_pymupdf_bad_quality_fails(stub_text_layer, tmp_path):
    """vlm 失败 + pymupdf 质检不合格（如扫描件）→ 整体失败。"""
    cloud, pymupdf = FakeCloud(ok=False), FakePyMuPDF(quality_ok=False)
    ok, _, used = route_and_parse(cloud, pymupdf, "x.pdf", tmp_path / "out", "en", backend=None)
    assert not ok


def test_auto_both_fail(stub_text_layer, tmp_path):
    cloud, pymupdf = FakeCloud(ok=False), FakePyMuPDF(ok=False)
    ok, _, _ = route_and_parse(cloud, pymupdf, "x.pdf", tmp_path / "out", "en", backend=None)
    assert not ok


def test_invalid_backend_raises(stub_text_layer, tmp_path):
    with pytest.raises(ValueError):
        route_and_parse(FakeCloud(), FakePyMuPDF(), "x.pdf", tmp_path / "out", "en", backend="pipeline")


def test_cleans_known_artifacts_keeps_unknown(stub_text_layer, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "content.md").write_text("stale", encoding="utf-8")
    (out / "images").mkdir()
    (out / "images" / "old.png").write_bytes(b"x")
    (out / "unknown.txt").write_text("keep me", encoding="utf-8")
    route_and_parse(FakeCloud(), FakePyMuPDF(), "x.pdf", out, "en", backend="pymupdf")
    assert not (out / "content.md").exists()
    assert not (out / "images").exists()
    assert (out / "unknown.txt").read_text(encoding="utf-8") == "keep me"


def test_no_cleanup_when_output_dir_is_pdf_parent(stub_text_layer, tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    (tmp_path / "content.md").write_text("stale", encoding="utf-8")
    route_and_parse(FakeCloud(), FakePyMuPDF(), str(pdf), tmp_path, "en", backend="pymupdf")
    # output_dir == PDF 所在目录 → 不清理（防误删源文件）
    assert (tmp_path / "content.md").exists()
