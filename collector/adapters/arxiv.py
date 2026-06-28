# collector/adapters/arxiv.py
"""arXiv adapter: metadata via arXiv API (Atom), PDF via direct URL.
New network code (repo had no arXiv HTTP client). Reuses normalize for arxiv_id stripping.
"""
from __future__ import annotations
import urllib.request
import xml.etree.ElementTree as ET
from collector.normalize import normalize_arxiv_id

ARXIV_API = "http://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "literature-library-collector/0.1"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()

def _text_or_none(elem):
    return elem.text.strip() if elem is not None and elem.text else None

def fetch_metadata(arxiv_id: str) -> dict:
    """Query arXiv API for one id. Return dict with arxiv_id(versionless), title, authors, doi, abstract."""
    aid = normalize_arxiv_id(arxiv_id) or arxiv_id
    url = f"{ARXIV_API}?id_list={aid}&max_results=1"
    data = _http_get(url)
    root = ET.fromstring(data)
    entry = root.find("a:entry", NS)
    if entry is None:
        return {"arxiv_id": aid, "title": None, "authors": [], "doi": None, "abstract": None}
    title = _text_or_none(entry.find("a:title", NS))
    authors = [a.find("a:name", NS).text for a in entry.findall("a:author", NS)
               if a.find("a:name", NS) is not None]
    doi_el = entry.find("arxiv:doi", NS)
    summary = _text_or_none(entry.find("a:summary", NS))
    return {
        "arxiv_id": aid,
        "title": title,
        "authors": authors,
        "doi": _text_or_none(doi_el) if doi_el is not None else None,
        "abstract": summary,
    }

def pdf_url(arxiv_id: str) -> str:
    aid = normalize_arxiv_id(arxiv_id) or arxiv_id
    return f"https://arxiv.org/pdf/{aid}"
