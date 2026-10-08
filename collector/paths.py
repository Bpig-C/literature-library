"""Shared path resolution for collector candidate PDFs.

local_pdf_path may be absolute (old candidates / legacy tests) or relative to
the library root (newly downloaded by heavy_gate). This module resolves either
form to an absolute, readable Path. LIBRARY_ROOT is read lazily so tests can
patch api.db.LIBRARY_ROOT.
"""
from __future__ import annotations
from pathlib import Path
import api.db

_ALLOWED_SUBDIRS = ("_collector_cache", "_inbox", "works")


def resolve_pdf_path(pdf_path):
    """Resolve a stored local_pdf_path to an absolute Path.

    Absolute paths returned as-is; relative paths resolved against api.db.LIBRARY_ROOT.
    Raises ValueError if resolved path is outside allowed library subdirectories.
    """
    p = Path(pdf_path)
    if p.is_absolute():
        resolved = p.resolve()
    else:
        resolved = (api.db.LIBRARY_ROOT / p).resolve()

    library_root = api.db.LIBRARY_ROOT.resolve()
    if not resolved.is_relative_to(library_root):
        raise ValueError(f"Path outside library boundary: {pdf_path}")

    # Check that path is within an allowed subdirectory (or is the library root itself for edge cases)
    relative = resolved.relative_to(library_root)
    top_dir = relative.parts[0] if relative.parts else ""
    if top_dir not in _ALLOWED_SUBDIRS:
        raise ValueError(f"Path not in allowed subdirectory ({', '.join(_ALLOWED_SUBDIRS)}): {pdf_path}")

    return resolved
