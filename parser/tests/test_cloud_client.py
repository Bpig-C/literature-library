"""CloudClient 单元测试：mock 官网 API 全流程，不真实联网。

覆盖：申请上传链接 → 上传 → 轮询 → 下载 zip → 解压 → 产出 content.md/content.json/package.zip。
"""
import io
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

# 让 tests 能 import parser 包
PARSER_ROOT = Path(__file__).resolve().parents[1]
if str(PARSER_ROOT) not in sys.path:
    sys.path.insert(0, str(PARSER_ROOT))

os.environ.setdefault("MinerU_API_KEY", "test-token-for-unit-test")

from core.mineru import cloud_client as cc  # noqa: E402
from core.mineru.base_client import ParseRequest  # noqa: E402


class _FakeResp:
    def __init__(self, status_code=200, json_data=None, content=b""):
        self.status_code = status_code
        self._json = json_data
        self.content = content
        self.text = (content or b"").decode("utf-8", "replace") if isinstance(content, (bytes, bytearray)) else str(content)

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


def _make_result_zip() -> bytes:
    """构造一个仿 MinerU 结果 zip：full.md / content_list.json / images/a.jpg。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("full.md", "# Title\n\nAbstract body.\n\n## References\n[1] foo")
        zf.writestr("content_list.json", json.dumps([{"type": "text", "text": "Abstract body."}]))
        zf.writestr("images/a.jpg", b"\xff\xd8\xffimgdata")
    return buf.getvalue()


def test_parse_pdf_full_flow(monkeypatch, tmp_path):
    pdf = tmp_path / "demo.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    out_dir = tmp_path / "out"
    zip_bytes = _make_result_zip()

    call_log = {"uploaded": False, "polled_states": []}

    def fake_request(method, url, **kwargs):
        if url.endswith("/api/v4/file-urls/batch"):
            assert kwargs["headers"]["Authorization"] == "Bearer test-token-for-unit-test"
            body = kwargs["json"]
            assert body["files"][0]["name"] == "demo.pdf"
            assert body["model_version"] in cc._VALID_MODEL_VERSIONS
            return _FakeResp(200, {"code": 0, "data": {"batch_id": "bid-1", "file_urls": ["https://upload/mock"]}})
        if "/api/v4/extract-results/batch/" in url:
            state = "running" if not call_log["polled_states"] else "done"
            call_log["polled_states"].append(state)
            entry = {"file_name": "demo.pdf", "state": state}
            if state == "done":
                entry["full_zip_url"] = "https://cdn/mock.zip"
            return _FakeResp(200, {"code": 0, "data": {"extract_result": [entry]}})
        raise AssertionError(f"unexpected request {method} {url}")

    def fake_put(url, data=None, **kwargs):
        assert "Content-Type" not in (kwargs.get("headers") or {})
        call_log["uploaded"] = True
        return _FakeResp(200)

    def fake_get(url, **kwargs):
        assert url.endswith(".zip")
        return _FakeResp(200, content=zip_bytes)

    monkeypatch.setattr(cc.requests, "request", fake_request)
    monkeypatch.setattr(cc.requests, "put", fake_put)
    monkeypatch.setattr(cc.requests, "get", fake_get)
    # 关掉 OCR 自动探测对 PDF 的依赖（fake pdf 无文本层，fitz 可能打不开）
    monkeypatch.setattr(cc, "_detect_is_ocr", lambda p, **kw: False)

    client = cc.CloudClient()
    client.poll_interval = 0  # 测试里立即轮询
    ok, msg = client.parse_pdf(ParseRequest(pdf_path=pdf, output_dir=out_dir, backend="pipeline", lang_list="en"))

    assert ok, msg
    assert call_log["uploaded"] is True
    assert (out_dir / "content.md").read_text(encoding="utf-8").startswith("# Title")
    cj = json.loads((out_dir / "content.json").read_text(encoding="utf-8"))
    assert isinstance(cj, list) or cj.get("source") == "mineru_cloud"
    assert (out_dir / "package.zip").exists()
    assert (out_dir / "images" / "a.jpg").exists()


def test_daily_limit_not_retried(monkeypatch, tmp_path):
    """code=-60018 每日上限：不重试，直接失败。"""
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    def fake_request(method, url, **kwargs):
        return _FakeResp(200, {"code": -60018, "msg": "每日解析任务数量已达上限", "trace_id": "t"})

    monkeypatch.setattr(cc.requests, "request", fake_request)
    monkeypatch.setattr(cc, "_detect_is_ocr", lambda p, **kw: False)

    client = cc.CloudClient()
    client.poll_interval = 0
    ok, msg = client.parse_pdf(ParseRequest(pdf_path=pdf, output_dir=tmp_path / "o"))
    assert not ok
    assert "-60018" in msg or "每日" in msg


def test_queue_full_retried(monkeypatch, tmp_path):
    """code=-60009 队列已满：应退避重试，最终成功。"""
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    attempts = {"n": 0}

    def fake_request(method, url, **kwargs):
        attempts["n"] += 1
        if attempts["n"] < 2 and url.endswith("/api/v4/file-urls/batch"):
            return _FakeResp(200, {"code": -60009, "msg": "队列已满"})
        if url.endswith("/api/v4/file-urls/batch"):
            return _FakeResp(200, {"code": 0, "data": {"batch_id": "b", "file_urls": ["u"]}})
        entry = {"file_name": "x.pdf", "state": "done", "full_zip_url": "https://x.zip"}
        return _FakeResp(200, {"code": 0, "data": {"extract_result": [entry]}})

    monkeypatch.setattr(cc.requests, "request", fake_request)
    monkeypatch.setattr(cc.requests, "put", lambda url, **kw: _FakeResp(200))
    monkeypatch.setattr(cc.requests, "get", lambda url, **kw: _FakeResp(200, content=_make_result_zip()))
    monkeypatch.setattr(cc, "_detect_is_ocr", lambda p, **kw: False)
    monkeypatch.setattr(cc.time, "sleep", lambda *_: None)

    client = cc.CloudClient()
    client.poll_interval = 0
    ok, msg = client.parse_pdf(ParseRequest(pdf_path=pdf, output_dir=tmp_path / "o"))
    assert ok, msg
    assert attempts["n"] >= 2  # 至少重试过一次


def test_helpers():
    assert cc._sanitize_data_id("2406.10162v3 / foo:bar") == "2406.10162v3---foo-bar"
    assert cc._normalize_language(["en", "ch"]) == "en"
    assert cc._normalize_language("") == "ch"
    assert cc._extract_json_from_text('noise ```json\n{"a":1}\n``` end') == {"a": 1}
    assert cc._extract_json_from_text('{"b":2}') == {"b": 2}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
