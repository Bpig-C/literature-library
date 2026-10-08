"""Positive isolation preparation for retired legacy-flow tooling."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ISOLATION_MARKER = ".litlib-isolation.json"
ISOLATION_SCHEMA = "litlib-isolation-v2"
FIXED_TARGETS = {"catalog": Path("literature.sqlite"),
                 "research": Path("research.sqlite")}

RETIRED_NOTICE = (
    "该工具所属的旧抽取/旧分类流程已退役（LL-DECOUPLE-20260920）。"
    "目标未通过正向隔离授权：必须显式提供由 authorize 创建的隔离根、"
    "固定路径副本和路径绑定标记。"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return path != root
    except ValueError:
        return False


def _validate_empty_isolation_root(root: Path) -> bool:
    """Validate a new/empty root and return whether this call created it."""
    if root.exists():
        if not root.is_dir():
            raise ValueError("isolation root must be a directory")
        # Repositories and managed worktrees have a .git directory or file.
        if (root / ".git").exists():
            raise ValueError("isolation root must not be a Git repository/worktree root")
        entries = list(root.iterdir())
        if entries:
            if (root / ISOLATION_MARKER).is_file():
                raise ValueError(
                    "isolation root is already prepared; refusing to overwrite it")
            raise ValueError(
                "existing isolation root must be empty and have no unbound content")
        return False
    root.mkdir(parents=True)
    return True


def prepare_isolation_copy(
        isolation_root: Path, *, catalog_source: Path,
        research_source: Path | None = None) -> dict:
    """Copy read-only sources to fixed targets and bind a fresh marker.

    Callers cannot nominate targets. Sources must resolve outside the root.
    Non-empty roots, including an earlier drill, are never overwritten.
    """
    root = Path(isolation_root).resolve()
    if (root / ".git").exists():
        raise ValueError("isolation root must not be a Git repository/worktree root")
    sources = {"catalog": Path(catalog_source).resolve()}
    if research_source is not None:
        sources["research"] = Path(research_source).resolve()

    for kind, source in sources.items():
        if not source.is_file():
            raise ValueError(f"{kind} source must be an existing file")
        if source == root or _inside(source, root):
            raise ValueError(f"{kind} source must be outside isolation root")
    if len(set(sources.values())) != len(sources):
        raise ValueError("catalog and research sources must be different files")

    created_root = _validate_empty_isolation_root(root)
    copied: list[Path] = []
    try:
        targets = {}
        for kind, source in sources.items():
            target = root / FIXED_TARGETS[kind]
            temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
            try:
                # This is always an independent byte copy, never a link.
                shutil.copyfile(source, temporary)
                source_hash = _sha256(source)
                target_hash = _sha256(temporary)
                if source_hash != target_hash:
                    raise ValueError(f"{kind} copied bytes do not match source")
                temporary.replace(target)
            finally:
                if temporary.exists():
                    temporary.unlink()
            copied.append(target)
            targets[kind] = {
                "target_path": str(target),
                "source_path": str(source),
                "source_sha256": source_hash,
                "initial_target_sha256": target_hash,
            }
        marker = {
            "schema": ISOLATION_SCHEMA,
            "authorization_id": str(uuid.uuid4()),
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "isolation_root": str(root),
            "targets": targets,
        }
        (root / ISOLATION_MARKER).write_text(
            json.dumps(marker, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        return marker
    except BaseException:
        for target in copied:
            target.unlink(missing_ok=True)
        if created_root:
            try:
                root.rmdir()
            except OSError:
                pass
        raise


def require_isolated_target(tool: str, db_path: Path, *, kind: str,
                            isolation_root: Path | None = None) -> Path:
    target = Path(db_path).resolve()
    root_value = isolation_root or os.environ.get("LITLIB_ISOLATION_ROOT")
    try:
        if not root_value:
            raise ValueError("LITLIB_ISOLATION_ROOT/--isolation-root is required")
        root = Path(root_value).resolve()
        if not _inside(target, root):
            raise ValueError("target is outside the explicit isolation root")
        marker = json.loads((root / ISOLATION_MARKER).read_text(encoding="utf-8"))
        if marker.get("schema") != ISOLATION_SCHEMA:
            raise ValueError("unsupported isolation marker schema")
        if Path(marker.get("isolation_root", "")).resolve() != root:
            raise ValueError("isolation marker root mismatch")
        entry = marker.get("targets", {}).get(kind) or {}
        fixed_target = (root / FIXED_TARGETS[kind]).resolve()
        if target != fixed_target:
            raise ValueError(f"{kind} target is not the fixed prepared path")
        if Path(entry.get("target_path", "")).resolve() != target:
            raise ValueError(f"isolation marker {kind} target mismatch")
        source = Path(entry.get("source_path", "")).resolve()
        if source == root or _inside(source, root):
            raise ValueError(f"isolation marker {kind} source is inside root")
        source_hash = entry.get("source_sha256")
        initial_hash = entry.get("initial_target_sha256")
        if (not isinstance(source_hash, str) or len(source_hash) != 64 or
                source_hash != initial_hash):
            raise ValueError("marker does not prove an identical source copy")
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        print(f"[{tool}] {RETIRED_NOTICE} reason={error}", file=sys.stderr)
        raise SystemExit(2) from error
    return target


def _default_catalog_path() -> Path:
    root = Path(os.environ.get("LITLIB_LIBRARY_ROOT") or Path.cwd()).resolve()
    return (Path(os.environ.get("LITLIB_DB_PATH") or root / "literature.sqlite")).resolve()


def refuse_production_default(tool: str, db_path: Path | None = None) -> Path:
    """Compatibility entrypoint; safety comes from prepared authorization."""
    return require_isolated_target(
        tool, Path(db_path or _default_catalog_path()), kind="catalog")
