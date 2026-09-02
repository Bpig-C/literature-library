"""route_and_parse 合并旁路资产触发测试（UX-007 方案C）。

- vlm 解析成功且 _raw 三件套齐全 → 自动产出 detail.json + content.merged.md；
- 三件套损坏 → 合并失败仅告警，解析结果不受影响（ok=True）；
- 重解析前清理会同时清掉旧的 detail.json / content.merged.md。
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

from core.mineru import pymupdf_client as pypdf_mod  # noqa: E402
from core.mineru.router import route_and_parse  # noqa: E402
from parser.tests.test_merged_md import make_fixture_pdf, make_mineru_package  # noqa: E402


class FakeCloud:
    """写出一个带三件套的迷你云包 + full.md/content.md。"""

    def __init__(self, corrupt_v2: bool = False):
        self.calls = 0
        self.corrupt_v2 = corrupt_v2
        self.last_batch_id = "BATCH-1"

    def parse_pdf(self, req):
        self.calls += 1
        out = Path(req.output_dir)
        raw = out / "_raw"
        make_mineru_package(raw)
        if self.corrupt_v2:
            next(raw.glob("*_content_list_v2.json")).write_text("{broken", encoding="utf-8")
        (out / "content.md").write_text("# fake full.md", encoding="utf-8")
        (out / "content.json").write_text("{}", encoding="utf-8")
        return True, "cloud ok"


class FakePyMuPDF:
    def __init__(self):
        self.calls = 0
        self.last_metrics = {"ok": True, "garble_ratio": 0.0,
                             "avg_chars_per_page": 500, "reading_order_ok": True}

    def parse_pdf(self, req):
        self.calls += 1
        return True, "pymupdf ok"


@pytest.fixture()
def stub_text_layer(monkeypatch):
    monkeypatch.setattr(pypdf_mod, "has_text_layer", lambda pdf_path, **kw: True)


def test_vlm_success_generates_detail_assets(stub_text_layer, tmp_path):
    pdf = tmp_path / "paper.pdf"
    make_fixture_pdf(pdf)
    out = tmp_path / "out"
    cloud = FakeCloud()
    ok, _, used = route_and_parse(cloud, FakePyMuPDF(), str(pdf), out, "en", backend="vlm")
    assert ok and used == "vlm"
    assert (out / "detail.json").is_file()
    merged_md = (out / "content.merged.md").read_text(encoding="utf-8")
    assert "# Test Title" in merged_md
    # 原始产物不被合并触碰
    assert (out / "content.md").read_text(encoding="utf-8") == "# fake full.md"


def test_corrupt_package_does_not_fail_parse(stub_text_layer, tmp_path):
    pdf = tmp_path / "paper.pdf"
    make_fixture_pdf(pdf)
    out = tmp_path / "out"
    ok, _, used = route_and_parse(FakeCloud(corrupt_v2=True), FakePyMuPDF(),
                                  str(pdf), out, "en", backend="vlm")
    assert ok and used == "vlm"  # 解析本身成功
    assert not (out / "detail.json").exists()  # 合并失败仅跳过


def test_cleanup_removes_stale_detail_assets(stub_text_layer, tmp_path):
    pdf = tmp_path / "paper.pdf"
    make_fixture_pdf(pdf)
    out = tmp_path / "out"
    out.mkdir()
    (out / "detail.json").write_text("{}", encoding="utf-8")
    (out / "content.merged.md").write_text("stale", encoding="utf-8")
    route_and_parse(FakeCloud(), FakePyMuPDF(), str(pdf), out, "en", backend="pymupdf")
    assert not (out / "detail.json").exists()
    assert not (out / "content.merged.md").exists()
