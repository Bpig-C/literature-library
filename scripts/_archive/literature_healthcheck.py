"""Read-only health check for the literature library.

Checks consistency between DB, PDF files, content_md_path, parse ledger,
index.json, _inbox, _quarantine, reviewed duplicates, and orphan records.

Usage:
    python scripts/literature_healthcheck.py
    python scripts/literature_healthcheck.py --json
    python scripts/literature_healthcheck.py --output views/healthcheck.md
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LIBRARY_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = LIBRARY_ROOT / "literature.sqlite"


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def check_db_tables(conn: sqlite3.Connection) -> dict[str, Any]:
    """Check that expected tables exist and count rows."""
    expected = {
        "works", "source_files", "parse_artifacts", "literature_parse_runs",
        "duplicate_groups", "duplicate_candidates", "work_relations",
        "work_codes", "migration_meta", "library_migration_files", "inventory_meta",
        "metadata_extractions",
        "analysis_runs", "classification_extractions", "work_classification_tags",
    }
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    actual = {r["name"] for r in rows}
    missing = expected - actual

    counts = {}
    for table in sorted(expected & actual):
        counts[table] = conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]

    return {
        "missing_tables": sorted(missing),
        "counts": counts,
        "ok": len(missing) == 0,
    }


def check_works_vs_source_files(conn: sqlite3.Connection) -> list[dict]:
    """Find works with no source_files, or source_files pointing to missing works."""
    issues = []

    # Works without source files
    rows = conn.execute("""
        SELECT w.id, w.title FROM works w
        WHERE NOT EXISTS (SELECT 1 FROM source_files sf WHERE sf.work_id = w.id)
    """).fetchall()
    for r in rows:
        issues.append({"type": "work_no_source", "work_id": r["id"], "title": r["title"]})

    # Source files referencing non-existent works
    rows = conn.execute("""
        SELECT sf.id, sf.work_id FROM source_files sf
        WHERE NOT EXISTS (SELECT 1 FROM works w WHERE w.id = sf.work_id)
    """).fetchall()
    for r in rows:
        issues.append({"type": "orphan_source", "source_id": r["id"], "work_id": r["work_id"]})

    return issues


def check_pdf_files(conn: sqlite3.Connection) -> list[dict]:
    """Check that source_files point to existing PDF files."""
    issues = []
    rows = conn.execute("SELECT id, work_id, source_path, original_name FROM source_files").fetchall()
    for r in rows:
        p = Path(r["source_path"])
        if not p.exists():
            issues.append({
                "type": "missing_pdf",
                "source_id": r["id"],
                "work_id": r["work_id"],
                "path": str(p),
            })
    return issues


def check_content_md(conn: sqlite3.Connection) -> list[dict]:
    """Check that content_md_path in parse_runs points to existing files."""
    issues = []
    rows = conn.execute(
        "SELECT id, work_id, content_md_path FROM literature_parse_runs WHERE content_md_path IS NOT NULL"
    ).fetchall()
    for r in rows:
        p = Path(r["content_md_path"])
        if not p.exists():
            issues.append({
                "type": "missing_content_md",
                "run_id": r["id"],
                "work_id": r["work_id"],
                "path": str(p),
            })
    return issues


def check_index_json() -> dict[str, Any]:
    """Check index.json consistency."""
    index_path = LIBRARY_ROOT / "index.json"
    if not index_path.exists():
        return {"ok": False, "error": "index.json not found"}

    data = json.loads(index_path.read_text(encoding="utf-8"))
    works = data.get("works", [])
    return {
        "ok": True,
        "total_works": len(works),
        "summary": data.get("summary", {}),
    }


def check_inbox() -> dict[str, Any]:
    """Check _inbox for pending PDFs."""
    inbox = LIBRARY_ROOT / "_inbox"
    if not inbox.exists():
        return {"ok": True, "pending": 0, "files": []}

    pdfs = list(inbox.rglob("*.pdf"))
    return {
        "ok": len(pdfs) == 0,
        "pending": len(pdfs),
        "files": [str(p.relative_to(LIBRARY_ROOT)) for p in pdfs],
    }


def check_quarantine() -> dict[str, Any]:
    """Check _quarantine contents.

    Separates category directories (like bad_source/) from actual work directories.
    Work directories follow the pattern W-* or match a work_id.
    """
    qdir = LIBRARY_ROOT / "_quarantine"
    if not qdir.exists():
        return {"ok": True, "count": 0, "works": [], "categories": []}

    work_dirs = []
    category_dirs = []
    for d in qdir.iterdir():
        if not d.is_dir():
            continue
        if d.name.startswith("W-"):
            work_dirs.append(d.name)
        else:
            category_dirs.append(d.name)

    return {
        "ok": True,
        "count": len(work_dirs),
        "works": work_dirs,
        "categories": category_dirs,
    }


def check_quarantine_db_consistency(conn: sqlite3.Connection) -> list[dict]:
    """Check that DB quarantine status matches filesystem."""
    issues = []

    # Works marked quarantined in DB
    db_quarantined = {
        r["id"] for r in conn.execute(
            "SELECT id FROM works WHERE read_status = 'quarantined'"
        ).fetchall()
    }

    # Works with quarantine-related code (bad_source or quarantined)
    code_works = {
        r["work_id"] for r in conn.execute(
            "SELECT DISTINCT work_id FROM work_codes WHERE code IN ('bad_source', 'quarantined')"
        ).fetchall()
    }

    # DB says quarantined but no quarantine code
    for wid in db_quarantined - code_works:
        issues.append({"type": "quarantine_no_code", "work_id": wid})

    # Has quarantine code but not quarantined
    for wid in code_works - db_quarantined:
        issues.append({"type": "code_no_quarantine", "work_id": wid})

    # Check file location: quarantined works should have _quarantine/{work_id}/ with actual files
    quarantine_dir = LIBRARY_ROOT / "_quarantine"
    for wid in db_quarantined:
        q_path = quarantine_dir / wid
        sources = conn.execute(
            "SELECT id, source_path, original_name FROM source_files WHERE work_id = ? AND status = 'active'",
            (wid,),
        ).fetchall()
        for s in sources:
            sp = s["source_path"]
            if not sp:
                continue
            sp_path = Path(sp)
            # source_path should point to _quarantine/{work_id}/
            if not sp_path.parent.resolve().samefile(q_path.resolve()) if q_path.exists() else True:
                issues.append({"type": "quarantine_path_mismatch", "work_id": wid, "source_id": s["id"], "source_path": sp})
            # File should actually exist at that path
            elif not sp_path.exists():
                issues.append({"type": "quarantine_file_missing", "work_id": wid, "source_id": s["id"], "source_path": sp})

    return issues


def check_duplicate_review(conn: sqlite3.Connection) -> dict[str, Any]:
    """Check duplicate review status."""
    groups = conn.execute("SELECT * FROM duplicate_groups").fetchall()
    candidates = conn.execute("SELECT * FROM duplicate_candidates").fetchall()

    total_groups = len(groups)
    total_candidates = len(candidates)
    reviewed = sum(1 for c in candidates if c["reviewed"])
    unreviewed = total_candidates - reviewed

    auto_confirmed = sum(1 for g in groups if g["duplicate_type"] == "exact_sha256")

    return {
        "ok": True,
        "total_groups": total_groups,
        "total_candidates": total_candidates,
        "reviewed": reviewed,
        "unreviewed": unreviewed,
        "auto_confirmed_groups": auto_confirmed,
    }


def check_orphan_artifacts(conn: sqlite3.Connection) -> list[dict]:
    """Find parse artifacts referencing non-existent works."""
    issues = []
    rows = conn.execute("""
        SELECT pa.id, pa.work_id, pa.file_path FROM parse_artifacts pa
        WHERE NOT EXISTS (SELECT 1 FROM works w WHERE w.id = pa.work_id)
    """).fetchall()
    for r in rows:
        issues.append({
            "type": "orphan_artifact",
            "artifact_id": r["id"],
            "work_id": r["work_id"],
            "path": r["file_path"],
        })
    return issues


def check_work_codes_orphan(conn: sqlite3.Connection) -> list[dict]:
    """Find work_codes referencing non-existent works."""
    issues = []
    rows = conn.execute("""
        SELECT wc.work_id, wc.code FROM work_codes wc
        WHERE NOT EXISTS (SELECT 1 FROM works w WHERE w.id = wc.work_id)
    """).fetchall()
    for r in rows:
        issues.append({"type": "orphan_code", "work_id": r["work_id"], "code": r["code"]})
    return issues


def check_source_file_id_orphans(conn: sqlite3.Connection) -> list[dict]:
    """Find references to non-existent source_files in duplicate_candidates, parse_artifacts, parse_runs."""
    issues = []

    # duplicate_candidates referencing non-existent source_files
    rows = conn.execute("""
        SELECT dc.id, dc.source_file_id, dc.work_id, dc.group_id
        FROM duplicate_candidates dc
        WHERE dc.source_file_id IS NOT NULL AND dc.source_file_id != ''
        AND NOT EXISTS (SELECT 1 FROM source_files sf WHERE sf.id = dc.source_file_id)
    """).fetchall()
    for r in rows:
        issues.append({
            "type": "orphan_source_file_ref",
            "table": "duplicate_candidates",
            "row_id": r["id"],
            "source_file_id": r["source_file_id"],
            "work_id": r["work_id"],
        })

    # parse_artifacts referencing non-existent source_files
    rows = conn.execute("""
        SELECT pa.id, pa.source_file_id, pa.work_id
        FROM parse_artifacts pa
        WHERE pa.source_file_id IS NOT NULL AND pa.source_file_id != ''
        AND NOT EXISTS (SELECT 1 FROM source_files sf WHERE sf.id = pa.source_file_id)
    """).fetchall()
    for r in rows:
        issues.append({
            "type": "orphan_source_file_ref",
            "table": "parse_artifacts",
            "row_id": r["id"],
            "source_file_id": r["source_file_id"],
            "work_id": r["work_id"],
        })

    # literature_parse_runs referencing non-existent source_files
    rows = conn.execute("""
        SELECT lr.id, lr.source_file_id, lr.work_id
        FROM literature_parse_runs lr
        WHERE lr.source_file_id IS NOT NULL AND lr.source_file_id != ''
        AND NOT EXISTS (SELECT 1 FROM source_files sf WHERE sf.id = lr.source_file_id)
    """).fetchall()
    for r in rows:
        issues.append({
            "type": "orphan_source_file_ref",
            "table": "literature_parse_runs",
            "row_id": r["id"],
            "source_file_id": r["source_file_id"],
            "work_id": r["work_id"],
        })

    return issues


def check_metadata_extractions(conn: sqlite3.Connection) -> dict[str, Any]:
    """Check metadata extraction status."""
    try:
        total = conn.execute("SELECT COUNT(*) FROM metadata_extractions").fetchone()[0]
        applied = conn.execute("SELECT COUNT(*) FROM metadata_extractions WHERE applied = 1").fetchone()[0]
        works_with_ext = conn.execute("SELECT COUNT(DISTINCT work_id) FROM metadata_extractions").fetchone()[0]
        works_total = conn.execute("SELECT COUNT(*) FROM works").fetchone()[0]
    except sqlite3.OperationalError:
        return {"ok": False, "error": "metadata_extractions table not found"}

    return {
        "ok": True,
        "total_extractions": total,
        "applied": applied,
        "unapplied": total - applied,
        "works_with_extractions": works_with_ext,
        "works_total": works_total,
        "coverage": f"{works_with_ext}/{works_total}",
    }


def check_analysis_runs(conn: sqlite3.Connection) -> dict[str, Any]:
    """Check analysis_runs table consistency (§9.4).

    Returns dict with 'ok', 'total', 'issues', and 'summary' keys.
    If the table doesn't exist, returns ok=True with a status message.
    """
    try:
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='analysis_runs'"
        ).fetchone()
    except sqlite3.OperationalError:
        exists = None

    if not exists:
        return {"ok": True, "status": "table_absent", "total": 0, "issues": []}

    issues: list[dict] = []
    rows = conn.execute("SELECT * FROM analysis_runs").fetchall()

    # Collect quarantined work_ids for cross-check
    quarantined_works = set()
    try:
        quarantined_works = {
            r["id"] for r in conn.execute(
                "SELECT id FROM works WHERE read_status = 'quarantined'"
            ).fetchall()
        }
    except sqlite3.OperationalError:
        pass

    all_work_ids = {r["id"] for r in conn.execute("SELECT id FROM works").fetchall()}

    # Allowed review_status values
    allowed_statuses = {"pending", "approved", "needs_fix", "rejected"}

    # Track active (non-superseded) runs per (work_id, angle, template_version)
    active_runs: dict[tuple, list[int]] = {}

    for r in rows:
        rid = r["id"]
        work_id = r["work_id"]
        md_path = r["md_path"]
        review_status = r["review_status"]
        extracted_json = r["extracted_json"]
        superseded_by = r["superseded_by"]
        angle = r["angle"]
        template_version = r["template_version"]

        # 1. work_id must exist in works table
        if work_id not in all_work_ids:
            issues.append({"type": "ar_orphan_work", "run_id": rid, "work_id": work_id})

        # 2. md_path must exist and be non-empty
        if md_path:
            p = Path(md_path)
            if not p.exists():
                issues.append({"type": "ar_missing_md", "run_id": rid, "work_id": work_id, "path": md_path})
            elif p.stat().st_size == 0:
                issues.append({"type": "ar_empty_md", "run_id": rid, "work_id": work_id, "path": md_path})
        else:
            issues.append({"type": "ar_no_md_path", "run_id": rid, "work_id": work_id})

        # 3. review_status must be valid
        if review_status and review_status not in allowed_statuses:
            issues.append({
                "type": "ar_invalid_status",
                "run_id": rid,
                "work_id": work_id,
                "review_status": review_status,
            })

        # 4. extracted_json must be valid JSON
        if extracted_json:
            try:
                json.loads(extracted_json)
            except (json.JSONDecodeError, TypeError):
                issues.append({"type": "ar_invalid_json", "run_id": rid, "work_id": work_id})

        # 5. Track active runs for uniqueness check
        if not superseded_by:
            key = (work_id, angle, template_version)
            active_runs.setdefault(key, []).append(rid)

    # 6. Uniqueness: at most one active run per (work_id, angle, template_version)
    for key, run_ids in active_runs.items():
        if len(run_ids) > 1:
            issues.append({
                "type": "ar_duplicate_active",
                "work_id": key[0],
                "angle": key[1],
                "template_version": key[2],
                "run_ids": run_ids,
            })

    # 7. Quarantined works should not have pending analysis runs
    if quarantined_works:
        pending_quarantined = conn.execute(
            "SELECT id, work_id FROM analysis_runs WHERE review_status = 'pending' AND superseded_by IS NULL"
        ).fetchall()
        for r in pending_quarantined:
            if r["work_id"] in quarantined_works:
                issues.append({
                    "type": "ar_quarantined_pending",
                    "run_id": r["id"],
                    "work_id": r["work_id"],
                })

    summary = {
        "total": len(rows),
        "active": sum(1 for r in rows if not r["superseded_by"]),
        "superseded": sum(1 for r in rows if r["superseded_by"]),
        "pending": sum(1 for r in rows if r["review_status"] == "pending" and not r["superseded_by"]),
    }

    return {
        "ok": len(issues) == 0,
        "status": "present",
        "issues": issues,
        "summary": summary,
    }


def run_all_checks() -> dict[str, Any]:
    """Run all health checks and return structured results."""
    conn = connect_db()
    try:
        db = check_db_tables(conn)
        works_source = check_works_vs_source_files(conn)
        missing_pdfs = check_pdf_files(conn)
        missing_content = check_content_md(conn)
        index = check_index_json()
        inbox = check_inbox()
        quarantine = check_quarantine()
        quarantine_db = check_quarantine_db_consistency(conn)
        dup_review = check_duplicate_review(conn)
        orphan_artifacts = check_orphan_artifacts(conn)
        orphan_codes = check_work_codes_orphan(conn)
        orphan_source_refs = check_source_file_id_orphans(conn)
        metadata_ext = check_metadata_extractions(conn)
        analysis_runs_result = check_analysis_runs(conn)
    finally:
        conn.close()

    all_issues = (
        works_source + missing_pdfs + missing_content
        + quarantine_db + orphan_artifacts + orphan_codes + orphan_source_refs
        + analysis_runs_result.get("issues", [])
    )

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "library_root": str(LIBRARY_ROOT),
        "db_tables": db,
        "works_source": works_source,
        "missing_pdfs": missing_pdfs,
        "missing_content_md": missing_content,
        "index_json": index,
        "inbox": inbox,
        "quarantine": quarantine,
        "quarantine_consistency": quarantine_db,
        "duplicate_review": dup_review,
        "orphan_artifacts": orphan_artifacts,
        "orphan_codes": orphan_codes,
        "orphan_source_file_refs": orphan_source_refs,
        "metadata_extractions": metadata_ext,
        "analysis_runs": analysis_runs_result,
        "total_issues": len(all_issues),
        "healthy": len(all_issues) == 0 and db["ok"],
    }


def format_markdown(result: dict[str, Any]) -> str:
    """Format check results as Markdown report."""
    lines = []
    lines.append("# 文献库健康检查报告")
    lines.append("")
    lines.append(f"检查时间：{result['checked_at']}")
    lines.append(f"库根目录：`{result['library_root']}`")
    lines.append("")

    status = "全部通过" if result["healthy"] else f"发现 {result['total_issues']} 个问题"
    lines.append(f"**状态：{status}**")
    lines.append("")

    # DB tables
    db = result["db_tables"]
    lines.append("## 数据库表")
    lines.append("")
    if db["missing_tables"]:
        lines.append(f"缺失表：{', '.join(db['missing_tables'])}")
    else:
        lines.append("所有预期表均存在。")
    lines.append("")
    for table, count in sorted(db["counts"].items()):
        lines.append(f"- `{table}`：{count} 条")
    lines.append("")

    # Works vs source files
    if result["works_source"]:
        lines.append("## 文献-源文件问题")
        lines.append("")
        for item in result["works_source"]:
            if item["type"] == "work_no_source":
                lines.append(f"- {item['work_id']} 无源文件：{item.get('title', '')}")
            elif item["type"] == "orphan_source":
                lines.append(f"- 孤儿源文件 {item['source_id']}（引用不存在的 work {item['work_id']}）")
        lines.append("")

    # Missing PDFs
    if result["missing_pdfs"]:
        lines.append("## 缺失 PDF")
        lines.append("")
        for item in result["missing_pdfs"]:
            lines.append(f"- {item['work_id']}：`{item['path']}`")
        lines.append("")

    # Missing content.md
    if result["missing_content_md"]:
        lines.append("## 缺失 content.md")
        lines.append("")
        for item in result["missing_content_md"]:
            lines.append(f"- {item['work_id']}：`{item['path']}`")
        lines.append("")

    # Index
    index = result["index_json"]
    lines.append("## 索引文件")
    lines.append("")
    if index.get("ok"):
        lines.append(f"总计 {index['total_works']} 篇文献")
    else:
        lines.append(f"错误：{index.get('error', 'unknown')}")
    lines.append("")

    # Inbox
    inbox = result["inbox"]
    lines.append("## 投递箱")
    lines.append("")
    if inbox["pending"] > 0:
        lines.append(f"有 {inbox['pending']} 个 PDF 待摄入：")
        for f in inbox["files"]:
            lines.append(f"- `{f}`")
    else:
        lines.append("投递箱为空。")
    lines.append("")

    # Quarantine
    q = result["quarantine"]
    lines.append("## 隔离区")
    lines.append("")
    if q["categories"]:
        lines.append(f"分类目录：{', '.join(q['categories'])}")
    lines.append(f"共 {q['count']} 个作品在隔离区")
    if q["works"]:
        for w in q["works"]:
            lines.append(f"- `{w}`")
    lines.append("")

    # Quarantine consistency
    qc = result["quarantine_consistency"]
    if qc:
        lines.append("## 隔离一致性问题")
        lines.append("")
        for item in qc:
            if item["type"] == "quarantine_no_code":
                lines.append(f"- {item['work_id']}：已隔离但无隔离标签")
            elif item["type"] == "code_no_quarantine":
                lines.append(f"- {item['work_id']}：有隔离标签但未标记隔离")
            elif item["type"] == "quarantine_no_files":
                lines.append(f"- {item['work_id']}：已隔离但隔离目录不存在")
            elif item["type"] == "quarantine_path_mismatch":
                lines.append(f"- {item['work_id']}：source_path 未指向隔离目录 (source_id={item.get('source_id')})")
            elif item["type"] == "quarantine_file_missing":
                lines.append(f"- {item['work_id']}：隔离目录中源文件缺失 (source_id={item.get('source_id')})")
        lines.append("")

    # Duplicate review
    dr = result["duplicate_review"]
    lines.append("## 去重审查")
    lines.append("")
    lines.append(f"- 重复组：{dr['total_groups']}")
    lines.append(f"- 候选项：{dr['total_candidates']}")
    lines.append(f"- 已审查：{dr['reviewed']}")
    lines.append(f"- 未审查：{dr['unreviewed']}")
    lines.append(f"- 自动确认组：{dr['auto_confirmed_groups']}")
    lines.append("")

    # Orphan artifacts
    if result["orphan_artifacts"]:
        lines.append("## 孤儿解析产物")
        lines.append("")
        for item in result["orphan_artifacts"]:
            lines.append(f"- {item['artifact_id']}（引用不存在的 work {item['work_id']}）")
        lines.append("")

    # Orphan codes
    if result["orphan_codes"]:
        lines.append("## 孤儿标签")
        lines.append("")
        for item in result["orphan_codes"]:
            lines.append(f"- {item['work_id']}：{item['code']}")
        lines.append("")

    # Orphan source_file_id references
    if result["orphan_source_file_refs"]:
        lines.append("## 孤儿源文件引用")
        lines.append("")
        for item in result["orphan_source_file_refs"]:
            lines.append(f"- {item['table']}.{item['row_id']}：引用不存在的 source_file {item['source_file_id']}")
        lines.append("")

    # Metadata extractions
    me = result["metadata_extractions"]
    lines.append("## 元数据抽取")
    lines.append("")
    if me.get("ok"):
        lines.append(f"- 抽取记录：{me['total_extractions']} 条（已应用 {me['applied']}，未应用 {me['unapplied']}）")
        lines.append(f"- 覆盖文献：{me['coverage']}")
    else:
        lines.append(f"错误：{me.get('error', 'unknown')}")
    lines.append("")

    # Analysis runs
    ar = result["analysis_runs"]
    lines.append("## 分析任务 (analysis_runs)")
    lines.append("")
    if ar.get("status") == "table_absent":
        lines.append("表不存在，跳过。")
    else:
        s = ar.get("summary", {})
        lines.append(f"- 总记录：{s.get('total', 0)}（活跃 {s.get('active', 0)}，已取代 {s.get('superseded', 0)}，待审 {s.get('pending', 0)}）")
        if ar.get("issues"):
            lines.append("")
            for item in ar["issues"]:
                t = item["type"]
                if t == "ar_orphan_work":
                    lines.append(f"- 孤儿 run {item['run_id']}：work_id={item['work_id']} 不存在于 works 表")
                elif t == "ar_missing_md":
                    lines.append(f"- run {item['run_id']}：md_path 不存在 `{item['path']}`")
                elif t == "ar_empty_md":
                    lines.append(f"- run {item['run_id']}：md_path 文件为空 `{item['path']}`")
                elif t == "ar_no_md_path":
                    lines.append(f"- run {item['run_id']}：md_path 为空")
                elif t == "ar_invalid_status":
                    lines.append(f"- run {item['run_id']}：非法 review_status=`{item['review_status']}`")
                elif t == "ar_invalid_json":
                    lines.append(f"- run {item['run_id']}：extracted_json 非合法 JSON")
                elif t == "ar_duplicate_active":
                    lines.append(f"- 重复活跃 run：work={item['work_id']} angle={item['angle']} ver={item['template_version']} ids={item['run_ids']}")
                elif t == "ar_quarantined_pending":
                    lines.append(f"- 隔离中 work {item['work_id']} 有待审 run {item['run_id']}")
                else:
                    lines.append(f"- {t}：{item}")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="文献库健康检查")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    parser.add_argument("--output", type=Path, default=None, help="输出文件路径")
    args = parser.parse_args()

    result = run_all_checks()

    if args.json:
        text = json.dumps(result, indent=2, ensure_ascii=False)
    else:
        text = format_markdown(result)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"报告已写入：{args.output}")
        status = "健康" if result["healthy"] else f"{result['total_issues']} 个问题"
        print(f"状态：{status}")
    else:
        print(text)


if __name__ == "__main__":
    main()
