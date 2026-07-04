"""Lightweight documentation governance checks.

This script checks the current documentation entry points, role-based manuals,
and deprecated documentation directories. It intentionally avoids touching
project data or the SQLite library.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "README.md",
    "docs/README.md",
    "docs/manuals/README.md",
    "docs/manuals/user-manual.md",
    "docs/manuals/cli-manual.md",
    "docs/manuals/agent-manual.md",
    "docs/DOCUMENT_GOVERNANCE.md",
    "docs/HANDOVER_GUIDE.md",
    "FUTURE_WORK_PLAN.md",
    "USER_ISSUES.md",
    "docs/PROJECT_HISTORY.md",
]

REQUIRED_LINKS = {
    "README.md": [
        "docs/README.md",
        "docs/manuals/user-manual.md",
        "docs/manuals/cli-manual.md",
        "docs/manuals/agent-manual.md",
        "FUTURE_WORK_PLAN.md",
        "USER_ISSUES.md",
        "docs/PROJECT_HISTORY.md",
    ],
    "docs/README.md": [
        "manuals/user-manual.md",
        "manuals/cli-manual.md",
        "manuals/agent-manual.md",
        "../FUTURE_WORK_PLAN.md",
        "../USER_ISSUES.md",
        "PROJECT_HISTORY.md",
        "DOCUMENT_GOVERNANCE.md",
    ],
    "docs/manuals/README.md": [
        "user-manual.md",
        "cli-manual.md",
        "agent-manual.md",
        "../README.md",
    ],
    "docs/DOCUMENT_GOVERNANCE.md": [
        "docs/README.md",
        "docs/manuals/user-manual.md",
        "docs/manuals/cli-manual.md",
        "docs/manuals/agent-manual.md",
    ],
    "docs/HANDOVER_GUIDE.md": [
        "docs/README.md",
        "docs/manuals/user-manual.md",
        "docs/manuals/cli-manual.md",
        "docs/manuals/agent-manual.md",
    ],
}

DEPRECATED_DOC_DIRS = [
    Path("docs/plans"),
    Path("docs/reviews"),
    Path("docs/uperpowers"),
]

FORBIDDEN_ACTIVE_PATTERNS = [
    ("literature_healthcheck.py", "Use scripts/healthcheck_library.py instead."),
    ("D:\\\\06_tools\\\\document-parser", "Old external parser path must not be a current default."),
    ("D:\\06_tools\\document-parser", "Old external parser path must not be a current default."),
]

ALLOWED_LEGACY_CONTEXT = [
    "旧",
    "历史",
    "废弃",
    "归档",
    "不要",
    "不再",
    "不允许",
    "禁止",
    "回退",
    "替换",
    "检查",
    "当作默认",
    "legacy",
    "fallback",
    "archive",
]

ACTIVE_DOC_GLOBS = [
    "README.md",
    "TECHNICAL_OVERVIEW.md",
    "FUTURE_WORK_PLAN.md",
    "USER_ISSUES.md",
    "docs/*.md",
    "docs/manuals/*.md",
    "docs/architecture/*.md",
    "docs/workflows/*.md",
    "scripts/README.md",
    "web/README.md",
]


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def git_tracked_files(paths: list[Path]) -> list[str]:
    args = ["git", "ls-files", *[p.as_posix() for p in paths]]
    proc = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def iter_active_docs() -> list[Path]:
    docs: list[Path] = []
    for pattern in ACTIVE_DOC_GLOBS:
        docs.extend(ROOT.glob(pattern))
    return sorted({p for p in docs if p.is_file() and "_archive" not in p.parts})


def check_required_files(errors: list[str]) -> None:
    for item in REQUIRED_FILES:
        path = ROOT / item
        if not path.is_file():
            errors.append(f"missing required documentation file: {item}")


def check_required_links(errors: list[str]) -> None:
    for file_name, needles in REQUIRED_LINKS.items():
        path = ROOT / file_name
        if not path.is_file():
            continue
        text = read_text(path)
        for needle in needles:
            if needle not in text:
                errors.append(f"{file_name} does not reference {needle}")


def check_deprecated_dirs(errors: list[str], warnings: list[str]) -> None:
    tracked = git_tracked_files(DEPRECATED_DOC_DIRS)
    if tracked:
        errors.append(
            "tracked files remain in deprecated doc dirs: " + ", ".join(sorted(tracked))
        )

    for directory in DEPRECATED_DOC_DIRS:
        path = ROOT / directory
        if not path.exists():
            continue
        children = [p for p in path.rglob("*")]
        file_children = [p for p in children if p.is_file()]
        if file_children:
            errors.append(
                f"deprecated doc dir {directory.as_posix()} contains files: "
                + ", ".join(rel(p) for p in file_children[:10])
            )
        else:
            warnings.append(
                f"deprecated empty directory exists locally: {directory.as_posix()}"
            )


def check_forbidden_patterns(errors: list[str]) -> None:
    for path in iter_active_docs():
        lines = read_text(path).splitlines()
        for pattern, message in FORBIDDEN_ACTIVE_PATTERNS:
            for line_number, line in enumerate(lines, start=1):
                if pattern not in line:
                    continue
                if any(token in line for token in ALLOWED_LEGACY_CONTEXT):
                    continue
                errors.append(
                    f"{rel(path)}:{line_number} contains forbidden pattern "
                    f"{pattern!r}: {message}"
                )


def run_checks() -> dict[str, list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    check_required_files(errors)
    check_required_links(errors)
    check_deprecated_dirs(errors, warnings)
    check_forbidden_patterns(errors)
    return {"errors": errors, "warnings": warnings}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check documentation governance rules.")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    args = parser.parse_args()

    result = run_checks()
    ok = not result["errors"]

    if args.json:
        print(json.dumps({"ok": ok, **result}, ensure_ascii=False, indent=2))
    else:
        print("documentation checks:", "PASS" if ok else "FAIL")
        for warning in result["warnings"]:
            print(f"WARN: {warning}")
        for error in result["errors"]:
            print(f"ERROR: {error}")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
