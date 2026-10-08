# collector/fetch.py
"""Conservative PDF download (single file; reuse arxiv.pdf_url)."""
from __future__ import annotations
import urllib.request
from pathlib import Path

def download_pdf(url: str, dest: Path) -> Path | None:
    """Download to dest, return dest or None on failure. Short timeout, conservative."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "literature-library-collector/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
            f.write(r.read())
        return dest
    except Exception:
        return None
