#!/usr/bin/env python3
"""Print a reproducible SHA-256 manifest for a skill package."""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORED_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", "test-results", "coverage", "dist", "build"}
IGNORED_FILES = {".DS_Store"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}


def package_files() -> list[Path]:
    files = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(ROOT).parts
        if any(part in IGNORED_DIRS for part in relative_parts[:-1]):
            continue
        if path.name in IGNORED_FILES or path.suffix in IGNORED_SUFFIXES:
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(ROOT).as_posix())


def main() -> None:
    files = package_files()
    package_digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        contents = path.read_bytes()
        file_digest = hashlib.sha256(contents).hexdigest()
        print(f"{file_digest}  {relative}")
        package_digest.update(relative.encode("utf-8"))
        package_digest.update(b"\0")
        package_digest.update(contents)
        package_digest.update(b"\0")
    print(f"package-sha256  {package_digest.hexdigest()}")


if __name__ == "__main__":
    main()
