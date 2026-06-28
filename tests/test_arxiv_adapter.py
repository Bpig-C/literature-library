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
