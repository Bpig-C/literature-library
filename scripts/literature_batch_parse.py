"""Batch parse pending PDFs via 二元路由（P3.5 Phase E）。

路由策略（pipeline 弃用）：
- **文本层 PDF（born-digital）** → `parser/core/mineru/pymupdf_client.py` 本地直抽
  （精准公式/免费/快）；轻量质检不合格则回退 cloud。
- **扫描型 PDF（无文本层）** → `parser/core/mineru/cloud_client.py` 走 MinerU 官网精准 API（vlm）。
  token 从根目录 .env 的 MinerU_API_KEY 读取。max_workers=1 串行。

Usage:
    python scripts/literature_batch_parse.py              # dry-run: list pending
    python scripts/literature_batch_parse.py --execute    # parse all pending
    python scripts/literature_batch_parse.py --execute --limit 2  # parse first 2

切回自部署 MinerU：设置环境变量 MINERU_BACKEND=selfdeploy（并配置 MINERU_SERVER_URL），
parser/core/mineru/mineru_op 会改用 WebClient/LocalClient。
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

LIBRARY_ROOT = Path(__file__).resolve().parents[1]
# 直接当脚本跑时（python scripts/literature_batch_parse.py），sys.path[0] 是 scripts/
# 目录而非 repo root——需显式把 repo root 与 parser 子项目加入，否则
# `scripts.migrate_sync_parse_status` 与 `core.mineru.router` 都 import 不到。
if str(LIBRARY_ROOT) not in sys.path:
    sys.path.insert(0, str(LIBRARY_ROOT))
PARSER_ROOT = LIBRARY_ROOT / "parser"
if str(PARSER_ROOT) not in sys.path:
    sys.path.insert(0, str(PARSER_ROOT))

from core.mineru.router import route_and_parse  # noqa: E402  (language 映射在 nucleus 内)
from scripts.migrate_sync_parse_status import sync_work_parse_status  # noqa: E402

DB_PATH = LIBRARY_ROOT / "literature.sqlite"
ENV_PATH = LIBRARY_ROOT / ".env"

# 保守并发：官网提交限 50 文件/分钟，解析串行
POLL_OBSERVE = False  # 占位，cloud_client 内部自管轮询


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_env_file() -> None:
    """把根目录 .env 的键载入 os.environ（不覆盖已存在的环境变量）。"""
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def get_pending_db(limit: int | None = None) -> list[dict]:
    """从 literature_parse_runs 读 status='pending' 的待解析任务（DB 唯一源）。"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT pr.source_file_id, pr.work_id, pr.source_path, pr.output_dir,
                      w.language AS language
               FROM literature_parse_runs pr
               LEFT JOIN works w ON w.id = pr.work_id
               WHERE pr.status = 'pending'
               ORDER BY pr.id"""
        ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["output_dir"] = d["output_dir"] or ""
        d["language"] = d.get("language") or ""
        out.append(d)
    if limit:
        out = out[:limit]
    return out


def work_language(work_id: str) -> str:
    """从 works 表取 literature 语言原值（映射由 router.map_mineru_language 负责）。"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        try:
            row = conn.execute("SELECT language FROM works WHERE id=?", (work_id,)).fetchone()
            return (row[0] if row else "") or ""
        finally:
            conn.close()
    except Exception:
        return ""


def _open_conn() -> sqlite3.Connection:
    return sqlite3.connect(str(DB_PATH))


def _update_run_db(conn, sf_id, status, task_id, now, error="", content_md_path="",
                   content_json_path="", package_path="", backend="") -> None:
    """写 parse_runs 单行。"""
    if backend:
        conn.execute(
            """UPDATE literature_parse_runs
               SET status=?, task_id=?, finished_at=?, error=?,
                   content_md_path=?, content_json_path=?, package_path=?, backend=?
               WHERE id=?""",
            (status, task_id, now, error, content_md_path, content_json_path,
             package_path, backend, f"LPR-{sf_id}"),
        )
    else:
        conn.execute(
            """UPDATE literature_parse_runs
               SET status=?, task_id=?, finished_at=?, error=?,
                   content_md_path=?, content_json_path=?, package_path=?
               WHERE id=?""",
            (status, task_id, now, error, content_md_path, content_json_path,
             package_path, f"LPR-{sf_id}"),
        )


def run_pending(execute: bool, limit: int | None = None) -> int:
    """解析所有 status='pending' 的 parse_run。DB 唯一状态源。

    execute=False → dry-run 仅列出；execute=True → 串行 route_and_parse，
    逐条 UPDATE parse_runs + sync_work_parse_status。
    """
    load_env_file()
    from core.mineru.cloud_client import CloudClient  # noqa: PLC0415
    from core.mineru.pymupdf_client import PyMuPDFClient  # noqa: PLC0415

    pending = get_pending_db(limit=limit)
    if not pending:
        print("No pending parse tasks.")
        return 0

    print(f"{'[DRY-RUN] ' if not execute else ''}Pending: {len(pending)} files "
          f"(route: 文本层→PyMuPDF / 扫描型→cloud vlm)")
    for p in pending:
        print(f"  {p['source_file_id']}: {p['source_path']}")

    if not execute:
        return 0

    token_present = bool(os.getenv("MinerU_API_KEY") or os.getenv("MINERU_API_TOKEN"))
    if not token_present:
        print("ERROR: MinerU_API_KEY 未在环境/根目录 .env 中找到，无法执行 cloud 解析。")
        return 2

    client = CloudClient()
    pymupdf_client = PyMuPDFClient()
    success = failed = 0
    for p in pending:
        source_path = p["source_path"]
        output_dir = Path(p["output_dir"])
        language = p.get("language") or work_language(p.get("work_id", ""))
        print(f"\n[{p['source_file_id']}] route+parse: {Path(source_path).name} (lang={language})")
        conn = _open_conn()
        try:
            try:
                ok, msg, backend_used = route_and_parse(
                    client, pymupdf_client, source_path, output_dir, language
                )
                now = utc_now()
                if ok:
                    content_md = output_dir / "content.md"
                    content_json = output_dir / "content.json"
                    package = output_dir / "package.zip"
                    md_text = content_md.read_text(encoding="utf-8") if content_md.exists() else ""
                    batch_id = getattr(client, "last_batch_id", "") or ""
                    _update_run_db(
                        conn, p["source_file_id"], "succeeded", batch_id, now,
                        content_md_path=str(content_md),
                        content_json_path=str(content_json),
                        package_path=str(package) if package.exists() else "",
                        backend=backend_used,
                    )
                    success += 1
                    print(f"  OK ({len(md_text)} chars md) backend={backend_used} batch_id={batch_id}")
                else:
                    batch_id = getattr(client, "last_batch_id", "") or ""
                    _update_run_db(
                        conn, p["source_file_id"], "failed", batch_id, now,
                        error=msg, backend="vlm",
                    )
                    failed += 1
                    print(f"  FAILED: {msg}")
            except Exception as exc:  # noqa: BLE001
                now = utc_now()
                _update_run_db(conn, p["source_file_id"], "failed", "", now, error=str(exc))
                failed += 1
                print(f"  ERROR: {exc}")
            # 同步 works.parse_status（复用既有 helper，状态源统一）。
            # sync 失败不得回滚 parse_runs——parse_runs 已是权威源；
            # work 状态以既有 migrate_sync 脚本兜底。
            try:
                sync_work_parse_status(conn, p["work_id"])
            except Exception as exc:  # noqa: BLE001 — work 状态同步失败不得回滚 parse_runs
                print(f"  WARN: sync_work_parse_status failed for {p['work_id']}: {exc}")
            conn.commit()
        finally:
            conn.close()

    print(f"\nDone: {success} succeeded, {failed} failed")
    return 0 if failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch parse pending PDFs via MinerU cloud API.")
    parser.add_argument("--execute", action="store_true", help="Actually parse. Default is dry-run.")
    parser.add_argument("--limit", type=int, default=None, help="Max number of files to parse.")
    args = parser.parse_args()
    return run_pending(execute=args.execute, limit=args.limit)


# ---- LEGACY: 自部署 MinerU :18200 /tasks 异步 API（降级参考，cloud 模式不使用）----
# 以下函数保留作 MINERU_BACKEND=selfdeploy 降级或回滚参考，不在 cloud 主路径调用。
def _legacy_submit_task(pdf_path: str, backend: str = "pipeline", parse_method: str = "auto") -> str:  # pragma: no cover
    raise NotImplementedError("legacy self-deploy /tasks API; set MINERU_BACKEND=selfdeploy and use WebClient instead")


if __name__ == "__main__":
    raise SystemExit(main())
