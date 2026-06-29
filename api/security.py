"""Shared security helpers for API routes."""

from __future__ import annotations

from typing import Sequence

from fastapi import HTTPException


def validate_status(status: str, allowed: Sequence[str] = ("all", "pending", "approved", "rejected", "needs_fix", "superseded")) -> None:
    """Reject invalid status values to prevent SQL injection via query params."""
    if status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{status}'. Must be one of: {', '.join(allowed)}",
        )


def build_status_filter(status: str, column: str, *, allow_all: bool = True) -> tuple[str, list]:
    """Return (sql_fragment, params) for a parameterized status filter.

    Args:
        status: The status value (may be "all" if allow_all=True).
        column: Fully qualified column name, e.g. "me.review_status".
        allow_all: If True, "all" returns an empty filter. Otherwise "all" is invalid.

    Returns:
        (sql_fragment, params) tuple. sql_fragment is either "" or "AND <column> = ?".
    """
    if status == "all":
        if allow_all:
            return "", []
        raise HTTPException(status_code=400, detail="status='all' is not allowed here")
    validate_status(status)
    return f"AND {column} = ?", [status]
