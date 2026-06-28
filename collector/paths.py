"""Shared path resolution for collector candidate PDFs.

local_pdf_path may be absolute (old candidates / legacy tests) or relative to
the library root (newly downloaded by heavy_gate). This module resolves either
form to an absolute, readable Path. LIBRARY_ROOT is read lazily so tests can
patch api.db.LIBRARY_ROOT.
"""
from __future__ import annotations
from pathlib import Path
import api.db


def resolve_pdf_path(pdf_path):
    """Resolve a stored local_pdf_path to an absolute Path.

    Absolute paths returned as-is; relative paths resolved against api.db.LIBRARY_ROOT.
    """
    p = Path(pdf_path)
    if p.is_absolute():
        return p
    return api.db.LIBRARY_ROOT / p
