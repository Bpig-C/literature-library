"""Batch parse pending PDFs via MinerU 官网精准解析 API (cloud_client).

P3.5 后默认走 parser/ 子项目的 CloudClient（官网 API，token 从根目录 .env 的
MinerU_API_KEY 读取）。max_workers=1 串行，保守并发。

Usage:
    python scripts/literature_batch_parse.py              # dry-run: list pending
    python scripts/literature_batch_parse.py --execute    # parse all pending
    python scripts/literature_batch_parse.py --execute --limit 2  # parse first 2

切回自部署 MinerU：设置环境变量 MINERU_BACKEND=selfdeploy（并配置 MINERU_SERVER_URL），
parser/core/mineru/mineru_op 会改用 WebClient/LocalClient。
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LIBRARY_ROOT = Path(__file__).resolve().parents[1]
PARSER_ROOT = LIBRARY_ROOT / "parser"
if str(PARSER_ROOT) not in sys.path:
    sys.path.insert(0, str(PARSER_ROOT))

LEDGER_PATH = LIBRARY_ROOT / "parse_ledger.json"
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


def load_ledger() -> dict[str, Any]:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def save_ledger(ledger: dict[str, Any]) -> None:
    tmp = LEDGER_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(LEDGER_PATH)


def get_pending(ledger: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [
        (sf_id, run)
        for sf_id, run in ledger.get("runs", {}).items()
        if run.get("status") == "pending"
    ]


def work_language(work_id: str) -> str:
    """从 works 表取文献语言，供官网 API language 参数使用；缺失回落 en。"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        try:
            row = conn.execute(
                "SELECT language FROM works WHERE id=?", (work_id,)
            ).fetchone()
            lang = (row[0] if row else "") or ""
            lang = lang.strip().lower()
            # MinerU language 取值是 ch/en/...；映射常见值
            if lang in ("", "unknown"):
                return "en"
            if lang.startswith("zh") or lang in ("chinese", "中文"):
                return "ch"
            if lang.startswith("en") or lang in ("english",):
                return "en"
            return lang[:2]
        finally:
            conn.close()
    except Exception:
        return "en"


def parse_one(client: Any, source_path: str, output_dir: Path, backend: str, language: str) -> tuple[bool, str]:
    """调用 CloudClient 解析单个 PDF；成功后 output_dir 下产出 content.md/content.json/package.zip。"""
    from core.mineru.base_client import ParseRequest  # noqa: PLC0415

    req = ParseRequest(
        pdf_path=Path(source_path),
        output_dir=Path(output_dir),
        backend=backend or "pipeline",
        lang_list=language or "en",
        formula_enable=True,
        table_enable=True,
    )
    return client.parse_pdf(req)


def update_db(
    sf_id: str,
    status: str,
    task_id: str,
    now: str,
    error: str = "",
    content_md_path: str = "",
    content_json_path: str = "",
    package_path: str = "",
) -> None:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute(
            """UPDATE literature_parse_runs
               SET status=?, task_id=?, finished_at=?, error=?,
                   content_md_path=?, content_json_path=?, package_path=?
               WHERE id=?""",
            (status, task_id, now, error, content_md_path, content_json_path, package_path, f"LPR-{sf_id}"),
        )
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch parse pending PDFs via MinerU cloud API.")
    parser.add_argument("--execute", action="store_true", help="Actually parse. Default is dry-run.")
    parser.add_argument("--limit", type=int, default=None, help="Max number of files to parse.")
    args = parser.parse_args()

    load_env_file()

    # 延迟导入：确保 .env 已载入（token 进入 os.environ）后再构造 client
    from core.mineru.cloud_client import CloudClient  # noqa: PLC0415

    token_present = bool(os.getenv("MinerU_API_KEY") or os.getenv("MINERU_API_TOKEN"))
    if args.execute and not token_present:
        print("ERROR: MinerU_API_KEY 未在环境/根目录 .env 中找到，无法执行 cloud 解析。")
        return 2

    client = CloudClient()

    ledger = load_ledger()
    pending = get_pending(ledger)
    if args.limit:
        pending = pending[: args.limit]

    if not pending:
        print("No pending parse tasks.")
        return 0

    backend_default = os.getenv("MINERU_MODEL_VERSION", "pipeline")
    print(f"{'[DRY-RUN] ' if not args.execute else ''}Pending: {len(pending)} files (backend=cloud)")
    for sf_id, run in pending:
        print(f"  {sf_id}: {run['source_path']}")

    if not args.execute:
        return 0

    success = 0
    failed = 0
    for sf_id, run in pending:
        source_path = run["source_path"]
        output_dir = Path(run["output_dir"])
        backend = run.get("backend") or backend_default
        language = work_language(run.get("work_id", ""))
        print(f"\n[{sf_id}] cloud parse: {Path(source_path).name} (model={backend}, lang={language})")
        try:
            ok, msg = parse_one(client, source_path, output_dir, backend, language)
            now = utc_now()
            if ok:
                content_md = output_dir / "content.md"
                content_json = output_dir / "content.json"
                package = output_dir / "package.zip"
                md_text = content_md.read_text(encoding="utf-8") if content_md.exists() else ""
                run["status"] = "succeeded"
                run["task_id"] = run.get("task_id", "")
                run["finished_at"] = now
                run["updated_at"] = now
                run["error"] = ""
                run["content_md_path"] = str(content_md)
                run["content_json_path"] = str(content_json)
                run["package_path"] = str(package) if package.exists() else ""
                update_db(
                    sf_id, "succeeded", run["task_id"], now,
                    content_md_path=str(content_md),
                    content_json_path=str(content_json),
                    package_path=run["package_path"],
                )
                success += 1
                print(f"  OK ({len(md_text)} chars md)")
            else:
                run["status"] = "failed"
                run["finished_at"] = now
                run["updated_at"] = now
                run["error"] = msg
                update_db(sf_id, "failed", run.get("task_id", ""), now, msg)
                failed += 1
                print(f"  FAILED: {msg}")
        except Exception as exc:  # noqa: BLE001
            now = utc_now()
            run["status"] = "failed"
            run["finished_at"] = now
            run["updated_at"] = now
            run["error"] = str(exc)
            update_db(sf_id, "failed", run.get("task_id", ""), now, str(exc))
            failed += 1
            print(f"  ERROR: {exc}")

    save_ledger(ledger)
    print(f"\nDone: {success} succeeded, {failed} failed")
    return 0 if failed == 0 else 1


# ---- LEGACY: 自部署 MinerU :18200 /tasks 异步 API（降级参考，cloud 模式不使用）----
# 以下函数保留作 MINERU_BACKEND=selfdeploy 降级或回滚参考，不在 cloud 主路径调用。
def _legacy_submit_task(pdf_path: str, backend: str = "pipeline", parse_method: str = "auto") -> str:  # pragma: no cover
    raise NotImplementedError("legacy self-deploy /tasks API; set MINERU_BACKEND=selfdeploy and use WebClient instead")


if __name__ == "__main__":
    raise SystemExit(main())
