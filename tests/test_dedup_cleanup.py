"""Smoke test: dedup_cleanup.py compiles without SyntaxError."""

import py_compile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dedup_cleanup.py"


def test_dedup_cleanup_compiles():
    py_compile.compile(str(SCRIPT), doraise=True)
