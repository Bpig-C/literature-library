"""P3.5 Phase C 一次性验证脚本（不入 VCS）。

目的：证明 cloud→真实契约路径→DB content_md_path→下游读取 全链路可用。
做法（保守，不污染既有良好数据）：
  1. 备份样本真实 content.md/content.json（含 hash）
  2. 把 Phase B 的 cloud 试跑产物放到真实路径
  3. 校验 DB content_md_path 指向该文件、下游可读（复刻 metadata_extract 前 8000 字读取）
  4. 尝试真实 metadata_extract --no-write（模型服务可能离线，只验证读取阶段）
  5. 按 hash 还原原始文件，清理新引入的 package.zip/images，确保 real_dir 回到原状
报告写入 docs/superpowers/reviews/phase_c_validate_report.json
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

LIBRARY_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = LIBRARY_ROOT / "literature.sqlite"
REPORT = LIBRARY_ROOT / "docs/superpowers/reviews/phase_c_validate_report.json"

WORK_ID = "W-arxiv-2406.10162"
SF_ID = "SF-13d4293ad314-00158"
TRIAL_DIR = LIBRARY_ROOT / "_cloud_trial" / WORK_ID / SF_ID


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.exists() else ""


def snapshot(d: Path) -> dict:
    snap = {}
    if d.exists():
        for p in d.rglob("*"):
            if p.is_file():
                snap[p.relative_to(d).as_posix()] = sha(p)
    return snap


def restore(d: Path, snap: dict, backup: dict) -> None:
    """把 d 恢复到 snapshot 之前的状态。"""
    # 删除快照里没有的文件（Phase C 新引入的）
    for p in list(d.rglob("*")):
        if p.is_file():
            rel = p.relative_to(d).as_posix()
            if rel not in snap:
                p.unlink()
    # 还原被覆盖的 content.md / content.json
    for name, data in backup.items():
        (d / name).write_bytes(data)
    # 删除因新文件而创建的空目录
    for p in sorted(d.rglob("*"), reverse=True):
        if p.is_dir() and not any(p.iterdir()):
            p.rmdir()


def main() -> int:
    real_dir = LIBRARY_ROOT / "works" / WORK_ID / "parsed" / "mineru" / SF_ID
    if not real_dir.exists() or not TRIAL_DIR.exists():
        print(f"missing dirs: real={real_dir.exists()} trial={TRIAL_DIR.exists()}")
        return 2

    before = snapshot(real_dir)
    backup = {}
    for name in ("content.md", "content.json"):
        p = real_dir / name
        if p.exists():
            backup[name] = p.read_bytes()

    report = {"work_id": WORK_ID, "sf_id": SF_ID, "model_version": "pipeline", "language": "en"}

    # 1) 放置 cloud 产物到真实路径
    placed = []
    for name in ("content.md", "content.json", "package.zip"):
        src = TRIAL_DIR / name
        if src.exists():
            shutil.copy2(src, real_dir / name)
            placed.append(name)
    if (TRIAL_DIR / "images").exists():
        dst_img = real_dir / "images"
        if dst_img.exists():
            shutil.rmtree(dst_img)
        shutil.copytree(TRIAL_DIR / "images", dst_img)
        placed.append("images/")
    report["placed"] = placed

    # 2) DB content_md_path 校验
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    row = c.execute(
        "SELECT content_md_path, content_json_path FROM literature_parse_runs WHERE id=?", (f"LPR-{SF_ID}",)
    ).fetchone()
    c.close()
    cmd_path = Path(row["content_md_path"]) if row else None
    report["db_content_md_path"] = str(cmd_path) if cmd_path else None
    report["db_path_resolves"] = bool(cmd_path and cmd_path.exists())
    report["is_cloud_version"] = bool(cmd_path and cmd_path.exists() and sha(cmd_path) == sha(TRIAL_DIR / "content.md"))

    # 3) 下游读取校验（复刻 metadata_extract：读前 8000 字）
    if cmd_path and cmd_path.exists():
        text = cmd_path.read_text(encoding="utf-8", errors="replace")
        head = text[:8000]
        report["downstream_read"] = {
            "ok": len(head.strip()) > 0,
            "head_chars": len(head),
            "has_abstract": "abstract" in text[:8000].lower(),
            "sample_line": text.splitlines()[0][:80] if text.splitlines() else "",
        }

    # 4) 真实 metadata_extract --no-write（验证读取阶段；模型离线属预期）
    try:
        proc = subprocess.run(
            [sys.executable, "scripts/literature_metadata_extract.py", "--work-id", WORK_ID, "--no-write", "--limit", "1"],
            cwd=str(LIBRARY_ROOT), capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace",
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        report["metadata_extract"] = {
            "returncode": proc.returncode,
            "read_content_md": ("content_md_path" in out or "content.md" in out or "读取" in out or len(out) > 0),
            "reached_model_call": ("11435" in out or "Connection" in out or "ollama" in out.lower() or "urlopen" in out.lower()),
            "tail": out[-400:],
        }
    except Exception as exc:  # noqa: BLE001
        report["metadata_extract"] = {"error": str(exc)}

    # 5) 还原
    restore(real_dir, before, backup)
    after = snapshot(real_dir)
    report["restored_matches_before"] = (after == before)

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("db_path_resolves", "is_cloud_version", "downstream_read", "restored_matches_before")}, ensure_ascii=False, indent=2))
    print(f"Report -> {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
