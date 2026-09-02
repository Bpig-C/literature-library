"""为存量 cloud vlm 解析离线回填合并旁路资产（不耗云额度、不重新解析）。

UX-007 方案C：对 backend='vlm' 且 succeeded、_raw 三件套齐全的 parse_run，
生成 detail.json + content.merged.md 写入其解析输出目录。已有 detail.json 的
默认跳过（--force 重生成）。content.md 等原始产物一律不动。

Usage:
    python scripts/literature_merge_detail.py                 # dry-run: 列出可回填项
    python scripts/literature_merge_detail.py --execute       # 回填全部缺失
    python scripts/literature_merge_detail.py --execute --work-ids W-xxx --force
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

LIBRARY_ROOT = Path(__file__).resolve().parents[1]
if str(LIBRARY_ROOT) not in sys.path:
    sys.path.insert(0, str(LIBRARY_ROOT))
PARSER_ROOT = LIBRARY_ROOT / "parser"
if str(PARSER_ROOT) not in sys.path:
    sys.path.insert(0, str(PARSER_ROOT))

DB_PATH = LIBRARY_ROOT / "literature.sqlite"


def list_vlm_runs(work_ids: list[str] | None = None) -> list[dict]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        where = ["pr.status = 'succeeded'", "pr.backend = 'vlm'"]
        params: list = []
        if work_ids:
            where.append(f"pr.work_id IN ({','.join('?' * len(work_ids))})")
            params.extend(work_ids)
        rows = conn.execute(
            f"""SELECT pr.work_id, pr.source_file_id, pr.source_path, pr.output_dir
                FROM literature_parse_runs pr
                WHERE {' AND '.join(where)}
                ORDER BY pr.id""",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill detail.json + content.merged.md for vlm parses (offline).")
    parser.add_argument("--execute", action="store_true", help="Actually generate. Default is dry-run.")
    parser.add_argument("--work-ids", default=None, help="逗号分隔的 work_id 列表，仅处理这些 work。")
    parser.add_argument("--force", action="store_true", help="已有 detail.json 也重新生成。")
    args = parser.parse_args()
    work_ids = [w.strip() for w in args.work_ids.split(",") if w.strip()] if args.work_ids else None

    from core.document.detail_result.merged_md import build_detail_assets

    runs = list_vlm_runs(work_ids)
    todo, done, skipped = [], 0, 0
    for r in runs:
        out_dir = Path(r["output_dir"] or "")
        raw_dir = out_dir / "_raw"
        pdf_path = Path(r["source_path"] or "")
        if not out_dir or not raw_dir.is_dir():
            skipped += 1
            print(f"[SKIP] {r['work_id']}: 无 _raw（非云包产物）")
            continue
        if not pdf_path.is_file():
            skipped += 1
            print(f"[SKIP] {r['work_id']}: 源 PDF 缺失 {pdf_path}")
            continue
        if (out_dir / "detail.json").exists() and not args.force:
            done += 1
            print(f"[HAVE] {r['work_id']}: detail.json 已存在（--force 可重生成）")
            continue
        todo.append((r, pdf_path, raw_dir, out_dir))

    print(f"\n{'[DRY-RUN] ' if not args.execute else ''}待回填 {len(todo)} / 已有 {done} / 跳过 {skipped}")
    if not args.execute:
        for r, _, _, _ in todo:
            print(f"  [TODO] {r['work_id']}: {r['output_dir']}")
        return 0

    ok = failed = 0
    for r, pdf_path, raw_dir, out_dir in todo:
        try:
            info = build_detail_assets(pdf_path, raw_dir, out_dir)
            ok += 1
            print(f"  [OK] {r['work_id']}: {info['nodes']} 节点 / {info['pages']} 页")
        except Exception as exc:  # noqa: BLE001 — 单篇失败不中断
            failed += 1
            print(f"  [FAIL] {r['work_id']}: {exc}")
    print(f"\nDone: {ok} generated, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
