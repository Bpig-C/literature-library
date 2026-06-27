"""route_and_parse 二元路由单测（P3.5 Phase E）。

锁定三条不变量：
  1. 文本层 + 质检合格 → PyMuPDF，cloud 不被调用。
  2. 文本层 + 质检不合格 → cloud vlm 恰好调用一次，且覆盖 content.md。
  3. 无文本层(扫描型) → cloud vlm。
"""
import os
import sys
from pathlib import Path

LIBRARY_ROOT = Path(__file__).resolve().parents[2]
for sub in ("parser", "scripts"):
    p = LIBRARY_ROOT / sub
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import literature_batch_parse as L  # noqa: E402
import core.mineru.pymupdf_client as pmc  # noqa: E402


class FakePdf:
    """占位 PDF 路径（路由不真打开文件，has_text_layer 被 monkeypatch）。"""
    def __init__(self, tmp_path):
        self.path = tmp_path / "fake.pdf"
        self.path.write_bytes(b"%PDF-1.4 fake")


class FakePyMuPDF:
    def __init__(self, *, ok, metrics):
        self._ok = ok
        self.last_metrics = metrics

    def parse_pdf(self, req):
        # 模拟写一份 content.md（质检不合格场景下会被 cloud 覆盖）
        out = Path(req.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "content.md").write_text("PYMUPDF OUTPUT", encoding="utf-8")
        return self._ok, "pymupdf-fake"


class FakeCloud:
    def __init__(self):
        self.calls = 0
        self.last_batch_id = ""

    def parse_pdf(self, req):
        self.calls += 1
        out = Path(req.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "content.md").write_text("VLM OUTPUT", encoding="utf-8")  # 覆盖
        return True, "vlm-fake"


def test_text_layer_good_uses_pymupdf(monkeypatch, tmp_path):
    monkeypatch.setattr(pmc, "has_text_layer", lambda p: True)
    pdf = FakePdf(tmp_path)
    pymupdf = FakePyMuPDF(ok=True, metrics={"ok": True, "garble_ratio": 0.0, "avg_chars_per_page": 3000})
    cloud = FakeCloud()
    out = tmp_path / "out"
    ok, msg, backend = L.route_and_parse(cloud, pymupdf, str(pdf.path), out, "en")
    assert ok and backend == "pymupdf"
    assert cloud.calls == 0
    assert (out / "content.md").read_text() == "PYMUPDF OUTPUT"


def test_text_layer_bad_quality_falls_back_to_vlm_once(monkeypatch, tmp_path):
    monkeypatch.setattr(pmc, "has_text_layer", lambda p: True)
    pdf = FakePdf(tmp_path)
    # 质检不合格：garble 高
    pymupdf = FakePyMuPDF(ok=True, metrics={"ok": True, "garble_ratio": 0.9, "avg_chars_per_page": 3000})
    cloud = FakeCloud()
    out = tmp_path / "out"
    ok, msg, backend = L.route_and_parse(cloud, pymupdf, str(pdf.path), out, "en")
    assert ok and backend == "vlm"
    assert cloud.calls == 1  # 恰好一次，不得两次
    # content.md 被 cloud 覆盖
    assert (out / "content.md").read_text() == "VLM OUTPUT"


def test_scanned_uses_vlm(monkeypatch, tmp_path):
    monkeypatch.setattr(pmc, "has_text_layer", lambda p: False)
    pdf = FakePdf(tmp_path)
    pymupdf = FakePyMuPDF(ok=True, metrics={"ok": True, "garble_ratio": 0.0, "avg_chars_per_page": 3000})
    cloud = FakeCloud()
    out = tmp_path / "out"
    ok, msg, backend = L.route_and_parse(cloud, pymupdf, str(pdf.path), out, "en")
    assert ok and backend == "vlm"
    assert cloud.calls == 1
    assert (out / "content.md").read_text() == "VLM OUTPUT"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
