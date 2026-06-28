# tests/test_arxiv_adapter.py
from collector.adapters import arxiv

ATOM_ENTRY = """
<entry xmlns="http://www.w3.org/2005/Atom">
  <id>http://arxiv.org/abs/2406.10162v1</id>
  <title>Reward Hacking</title>
  <author><name>Alice</name></author>
  <arxiv:doi xmlns:arxiv="http://arxiv.org/schemas/atom">10.1000/rh</arxiv:doi>
  <link title="pdf" type="application/pdf" href="http://arxiv.org/pdf/2406.10162v1"/>
  <summary>abs</summary>
</entry>
"""

def test_parse_arxiv_atom(monkeypatch):
    monkeypatch.setattr(arxiv, "_http_get", lambda url: ('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">' + ATOM_ENTRY + '</feed>').encode())
    m = arxiv.fetch_metadata("2406.10162")
    assert m["arxiv_id"] == "2406.10162"   # 版本剥离
    assert m["title"] == "Reward Hacking"
    assert m["authors"] == ["Alice"]
    assert m["doi"] == "10.1000/rh"

def test_pdf_url():
    assert arxiv.pdf_url("2406.10162") == "https://arxiv.org/pdf/2406.10162"


# --- download_pdf (mock urlopen, no real network) ---
from pathlib import Path
from unittest.mock import patch, MagicMock
from collector import fetch as fetch_mod

def test_download_pdf_success(tmp_path):
    dest = tmp_path / "sub" / "out.pdf"
    fake_cm = MagicMock()
    fake_cm.__enter__.return_value.read.return_value = b"%PDF bytes"
    with patch("collector.fetch.urllib.request.urlopen", return_value=fake_cm):
        result = fetch_mod.download_pdf("http://x/a.pdf", dest)
    assert result == dest
    assert dest.read_bytes() == b"%PDF bytes"
    assert dest.parent.exists()  # parent dir created by mkdir

def test_download_pdf_failure_returns_none(tmp_path):
    dest = tmp_path / "out.pdf"
    with patch("collector.fetch.urllib.request.urlopen", side_effect=OSError("net fail")):
        result = fetch_mod.download_pdf("http://x/a.pdf", dest)
    assert result is None
