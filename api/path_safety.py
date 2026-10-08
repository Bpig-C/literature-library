"""Shared path safety utilities for quarantine / file-move operations.

Extracted from api/routes/works.py so that metadata.py and classification.py
can reuse the same strict validation instead of reimplementing it.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException


def _sanitize_filename(name: str) -> str:
    """Sanitize a filename from DB to prevent path traversal.

    Rejects absolute paths and path components like '..'.  Returns only the
    basename portion, stripping any directory separators.
    """
    p = Path(name)
    if p.is_absolute():
        raise HTTPException(status_code=422, detail=f"Invalid filename (absolute path): {name}")
    if ".." in p.parts:
        raise HTTPException(status_code=422, detail=f"Invalid filename (path traversal): {name}")
    # Reject forward/back slash (Path.name strips them, but original_name itself is dirty)
    if "/" in name or "\\" in name:
        raise HTTPException(status_code=422, detail=f"Invalid filename (contains separator): {name}")
    clean = p.name
    if not clean or clean in (".", ".."):
        raise HTTPException(status_code=422, detail=f"Invalid filename: {name}")
    return clean


def _safe_dest_name(row: dict, fallback_path: str) -> str:
    """Return sanitized original_name if non-empty, else basename of fallback_path."""
    name = row.get("original_name")
    if name:
        return _sanitize_filename(name)
    return Path(fallback_path).name


def _unique_dest(dest: Path) -> Path:
    """If dest already exists, append __2, __3, etc. until unique."""
    if not dest.exists():
        return dest
    stem = dest.stem
    suffix = dest.suffix
    parent = dest.parent
    counter = 2
    while True:
        candidate = parent / f"{stem}__{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1
