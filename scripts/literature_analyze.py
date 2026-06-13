"""Literature analysis run management: plan, submit, status, review.

Usage:
    python scripts/literature_analyze.py --plan --angle digest
    python scripts/literature_analyze.py --plan --angle digest --template-version 1
    python scripts/literature_analyze.py --submit --input _analysis_outbox/digest/
    python scripts/literature_analyze.py --submit --input result.json --executor human
    python scripts/literature_analyze.py --status
    python scripts/literature_analyze.py --review AR-abc123def456 --mark approved --note "LGTM"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LIBRARY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIBRARY_ROOT))

from api.db import get_conn, table_exists

TEMPLATE_DIR = LIBRARY_ROOT / "templates" / "angles"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def gen_id() -> str:
    return f"AR-{uuid.uuid4().hex[:12]}"


def parse_template_frontmatter(text: str) -> dict[str, Any]:
    """Parse YAML-like frontmatter from a template .md file."""
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return {}
    meta: dict[str, Any] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if val.startswith("[") and val.endswith("]"):
                meta[key] = val
            elif val.isdigit():
                meta[key] = int(val)
            else:
                meta[key] = val
    return meta


def find_template(angle: str, version: int) -> Path | None:
    """Find template file for given angle and version."""
    fname = f"{angle}@v{version}.md"
    p = TEMPLATE_DIR / fname
    return p if p.exists() else None


def parse_llm_json(raw: str) -> dict | None:
    """Try to extract a JSON object from output, handling markdown fences."""
    text = raw.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last > first:
        try:
            return json.loads(text[first:last + 1])
        except json.JSONDecodeError:
            pass
    return None


def render_markdown(data: dict, angle: str, template_version: int) -> str:
    """Render extracted_json envelope into human-readable Markdown."""
    lines: list[str] = []
    lines.append(f"# Analysis: {angle} v{template_version}")
    lines.append("")
    lines.append(f"- **work_id**: {data.get('work_id', 'N/A')}")
    lines.append(f"- **confidence**: {data.get('confidence', 'N/A')}")
    if data.get("confidence_note"):
        lines.append(f"- **confidence_note**: {data['confidence_note']}")
    lines.append(f"- **not_addressed**: {data.get('not_addressed', False)}")
    if data.get("not_addressed_fields"):
        lines.append(f"- **not_addressed_fields**: {', '.join(data['not_addressed_fields'])}")
    if data.get("open_questions"):
        lines.append(f"- **open_questions**: {', '.join(data['open_questions'])}")
    lines.append("")

    fields = data.get("fields", {})
    evidence_map = data.get("evidence", {})

    lines.append("## Fields")
    lines.append("")
    for field_name, field_data in fields.items():
        lines.append(f"### {field_name}")
        lines.append("")
        if isinstance(field_data, dict):
            value = field_data.get("value")
            ev = field_data.get("evidence", {})
        else:
            value = field_data
            ev = evidence_map.get(field_name, {})

        if isinstance(value, list):
            for item in value:
                lines.append(f"- {item}")
        elif isinstance(value, dict):
            for k, v in value.items():
                lines.append(f"- **{k}**: {v}")
        else:
            lines.append(f"{value}")
        lines.append("")

        if ev:
            quote = ev.get("quote", "")
            location = ev.get("location", "")
            if quote:
                lines.append(f"> **Evidence** ({location}): {quote[:300]}")
                lines.append("")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# --plan
# ---------------------------------------------------------------------------

def cmd_plan(angle: str, template_version: int) -> None:
    conn = get_conn()
    try:
        if not table_exists(conn, "analysis_runs"):
            print(json.dumps({"error": "analysis_runs table does not exist. Run migrate_add_analysis_runs.py first."}, ensure_ascii=False))
            sys.exit(1)

        template_path = find_template(angle, template_version)
        if not template_path:
            print(json.dumps({"error": f"Template not found: {angle}@v{template_version}"}, ensure_ascii=False))
            sys.exit(1)

        # Get active works with content_md_path
        rows = conn.execute("""
            SELECT w.id AS work_id, lpr.content_md_path
            FROM works w
            JOIN literature_parse_runs lpr ON lpr.work_id = w.id
            WHERE lpr.status = 'succeeded'
              AND lpr.content_md_path IS NOT NULL
              AND lpr.content_md_path != ''
              AND w.read_status != 'quarantined'
            GROUP BY w.id
            ORDER BY w.id
        """).fetchall()

        # Get existing non-superseded runs for this angle+version
        existing = conn.execute("""
            SELECT work_id FROM analysis_runs
            WHERE angle = ? AND template_version = ? AND superseded_by IS NULL
        """, (angle, template_version)).fetchall()
        existing_ids = {r["work_id"] for r in existing}

        tasks = []
        for r in rows:
            wid = r["work_id"]
            if wid in existing_ids:
                continue
            content_md_path = r["content_md_path"]
            today = datetime.now().strftime("%Y-%m-%d")
            output_path = f"works/{wid}/analyses/{today}_{angle}@v{template_version}.md"
            tasks.append({
                "work_id": wid,
                "content_md_path": content_md_path,
                "template_path": str(template_path),
                "output_path": output_path,
            })

        result = {
            "angle": angle,
            "template_version": template_version,
            "total_eligible": len(rows),
            "already_done": len(existing_ids),
            "pending": len(tasks),
            "tasks": tasks,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# --submit
# ---------------------------------------------------------------------------

def validate_envelope(data: dict) -> list[str]:
    """Validate the public envelope structure. Returns list of errors."""
    errors = []
    if not isinstance(data.get("angle"), str) or not data["angle"]:
        errors.append("missing or invalid 'angle'")
    if not isinstance(data.get("template_version"), int):
        errors.append("missing or invalid 'template_version' (must be integer)")
    if not isinstance(data.get("work_id"), str) or not data["work_id"]:
        errors.append("missing or invalid 'work_id'")
    if "fields" not in data or not isinstance(data["fields"], dict):
        errors.append("missing or invalid 'fields' (must be object)")
    if "confidence" not in data:
        errors.append("missing 'confidence'")
    elif data["confidence"] not in ("high", "medium", "low"):
        errors.append(f"invalid confidence value: {data['confidence']}")

    # Check evidence: either top-level evidence or per-field evidence
    has_top_evidence = isinstance(data.get("evidence"), dict) and data["evidence"]
    has_field_evidence = False
    for fd in (data.get("fields") or {}).values():
        if isinstance(fd, dict) and isinstance(fd.get("evidence"), dict):
            ev = fd["evidence"]
            if ev.get("quote"):
                has_field_evidence = True
                break
    if not has_top_evidence and not has_field_evidence:
        errors.append("no evidence found: need top-level 'evidence' or per-field evidence with non-empty 'quote'")
    return errors


def validate_quotes(data: dict, content_md_path: str) -> list[str]:
    """Check that evidence quotes are substrings of the content.md.

    Returns list of warnings (soft check — does not reject, only warns).
    """
    warnings = []
    try:
        content = Path(content_md_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        warnings.append(f"cannot read content.md at {content_md_path} for quote validation")
        return warnings

    quotes_to_check: list[tuple[str, str]] = []  # (field_name, quote)

    # Top-level evidence
    ev = data.get("evidence")
    if isinstance(ev, dict):
        for field_name, field_ev in ev.items():
            if isinstance(field_ev, dict) and field_ev.get("quote"):
                quotes_to_check.append((field_name, field_ev["quote"]))

    # Per-field evidence
    for field_name, fd in (data.get("fields") or {}).items():
        if isinstance(fd, dict) and isinstance(fd.get("evidence"), dict):
            q = fd["evidence"].get("quote")
            if q:
                quotes_to_check.append((field_name, q))

    for field_name, quote in quotes_to_check:
        if quote not in content:
            # Truncate for display
            display = quote[:80] + ("..." if len(quote) > 80 else "")
            warnings.append(f"evidence quote for '{field_name}' not found in content.md: {display!r}")

    return warnings


def cmd_submit(input_path: str, executor: str, model_name: str | None, force: bool, strict: bool = False) -> None:
    conn = get_conn()
    try:
        if not table_exists(conn, "analysis_runs"):
            print(json.dumps({"error": "analysis_runs table does not exist. Run migrate_add_analysis_runs.py first."}, ensure_ascii=False))
            sys.exit(1)

        p = Path(input_path)
        files: list[Path] = []
        if p.is_dir():
            files = sorted(p.glob("*.json"))
        elif p.is_file():
            files = [p]
        else:
            print(json.dumps({"error": f"Input path not found: {input_path}"}, ensure_ascii=False))
            sys.exit(1)

        if not files:
            print(json.dumps({"error": "No JSON files found in input path"}, ensure_ascii=False))
            sys.exit(1)

        results = []
        for f in files:
            try:
                raw = f.read_text(encoding="utf-8")
                data = json.loads(raw)
            except (json.JSONDecodeError, OSError) as e:
                results.append({"file": str(f), "status": "rejected", "error": f"JSON parse error: {e}"})
                continue

            # Validate envelope
            errors = validate_envelope(data)
            if errors:
                results.append({"file": str(f), "status": "rejected", "errors": errors})
                continue

            work_id = data["work_id"]
            angle = data["angle"]
            tv = data["template_version"]

            # Check work_id exists
            wrow = conn.execute("SELECT id FROM works WHERE id = ?", (work_id,)).fetchone()
            if not wrow:
                results.append({"file": str(f), "status": "rejected", "error": f"work_id not found: {work_id}"})
                continue

            # Validate evidence quotes against content.md
            cmr = conn.execute(
                "SELECT content_md_path FROM literature_parse_runs WHERE work_id = ? AND status = 'succeeded' AND content_md_path IS NOT NULL LIMIT 1",
                (work_id,),
            ).fetchone()
            quote_warnings = []
            if cmr and cmr["content_md_path"]:
                quote_warnings = validate_quotes(data, cmr["content_md_path"])

            # In strict mode, reject if any quote not found in content.md
            if strict and quote_warnings:
                results.append({"file": str(f), "status": "rejected", "error": "strict mode: evidence quotes not found in content.md", "quote_warnings": quote_warnings})
                continue

            # Check template exists
            tpl = find_template(angle, tv)
            if not tpl:
                results.append({"file": str(f), "status": "rejected", "error": f"Template not found: {angle}@v{tv}"})
                continue

            # Check template kind
            tpl_text = tpl.read_text(encoding="utf-8")
            tpl_meta = parse_template_frontmatter(tpl_text)
            kind = tpl_meta.get("kind", "angle")

            # Duplicate check
            dup = conn.execute("""
                SELECT id FROM analysis_runs
                WHERE work_id = ? AND angle = ? AND template_version = ? AND superseded_by IS NULL
            """, (work_id, angle, tv)).fetchone()
            if dup and not force:
                results.append({
                    "file": str(f),
                    "status": "rejected",
                    "error": f"Existing run {dup['id']} for {work_id}+{angle}@v{tv} not superseded. Use --force to override.",
                })
                continue

            # If force and duplicate exists, mark old as superseded
            if dup and force:
                new_id = gen_id()
                conn.execute(
                    "UPDATE analysis_runs SET superseded_by = ?, updated_at = ? WHERE id = ?",
                    (new_id, now_iso(), dup["id"]),
                )

            run_id = gen_id() if not (dup and force) else new_id
            now = now_iso()
            today = datetime.now().strftime("%Y-%m-%d")
            md_rel_path = f"works/{work_id}/analyses/{today}_{angle}@v{tv}.md"

            # Determine not_addressed
            not_addressed = 1 if data.get("not_addressed") else 0
            confidence = data.get("confidence", "")

            conn.execute("""
                INSERT INTO analysis_runs
                (id, kind, angle, template_version, work_id, executor, model_name,
                 extracted_json, confidence, not_addressed, review_status,
                 md_path, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """, (
                run_id, kind, angle, tv, work_id, executor, model_name,
                json.dumps(data, ensure_ascii=False),
                confidence, not_addressed,
                md_rel_path, now, now,
            ))

            # Render and write Markdown
            md_content = render_markdown(data, angle, tv)
            md_abs = LIBRARY_ROOT / md_rel_path
            md_abs.parent.mkdir(parents=True, exist_ok=True)
            md_abs.write_text(md_content, encoding="utf-8")

            result_entry = {
                "file": str(f),
                "status": "accepted",
                "run_id": run_id,
                "md_path": md_rel_path,
            }
            if quote_warnings:
                result_entry["quote_warnings"] = quote_warnings
            results.append(result_entry)

        conn.commit()
        print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# --status
# ---------------------------------------------------------------------------

def cmd_status() -> None:
    conn = get_conn()
    try:
        if not table_exists(conn, "analysis_runs"):
            print(json.dumps({"error": "analysis_runs table does not exist."}, ensure_ascii=False))
            sys.exit(1)

        # Active works count
        active = conn.execute("""
            SELECT COUNT(DISTINCT w.id) FROM works w
            WHERE w.read_status != 'quarantined'
        """).fetchone()[0]

        # All angles with runs
        angles = conn.execute("""
            SELECT angle, template_version, COUNT(*) as total,
                   SUM(CASE WHEN superseded_by IS NULL THEN 1 ELSE 0 END) as active_runs
            FROM analysis_runs
            GROUP BY angle, template_version
            ORDER BY angle, template_version
        """).fetchall()

        coverage = []
        for r in angles:
            angle = r["angle"]
            tv = r["template_version"]
            active_runs = r["active_runs"]

            # Get eligible count for this angle's kind
            kind_row = conn.execute("""
                SELECT kind FROM analysis_runs WHERE angle = ? AND template_version = ? LIMIT 1
            """, (angle, tv)).fetchone()
            kind = kind_row["kind"] if kind_row else "angle"

            eligible = active  # For digest, all active works
            if kind == "angle":
                # For angle kind, check template selector (simplified: all active)
                eligible = active

            # Review status counts
            status_counts = conn.execute("""
                SELECT review_status, COUNT(*) as cnt
                FROM analysis_runs
                WHERE angle = ? AND template_version = ? AND superseded_by IS NULL
                GROUP BY review_status
            """, (angle, tv)).fetchall()
            status_map = {s["review_status"]: s["cnt"] for s in status_counts}

            coverage.append({
                "angle": angle,
                "template_version": tv,
                "kind": kind,
                "eligible_works": eligible,
                "active_runs": active_runs,
                "coverage_pct": round(active_runs / eligible * 100, 1) if eligible > 0 else 0,
                "pending": status_map.get("pending", 0),
                "approved": status_map.get("approved", 0),
                "needs_fix": status_map.get("needs_fix", 0),
                "rejected": status_map.get("rejected", 0),
            })

        # Superseded count
        superseded = conn.execute(
            "SELECT COUNT(*) FROM analysis_runs WHERE superseded_by IS NOT NULL"
        ).fetchone()[0]

        result = {
            "active_works": active,
            "total_runs": conn.execute("SELECT COUNT(*) FROM analysis_runs").fetchone()[0],
            "superseded_runs": superseded,
            "angles": coverage,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# --review
# ---------------------------------------------------------------------------

def cmd_review(run_id: str, mark: str, note: str | None, source: str) -> None:
    conn = get_conn()
    try:
        if not table_exists(conn, "analysis_runs"):
            print(json.dumps({"error": "analysis_runs table does not exist."}, ensure_ascii=False))
            sys.exit(1)

        row = conn.execute("SELECT * FROM analysis_runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            print(json.dumps({"error": f"Run not found: {run_id}"}, ensure_ascii=False))
            sys.exit(1)

        now = now_iso()
        conn.execute("""
            UPDATE analysis_runs
            SET review_status = ?, reviewed_at = ?, review_source = ?, review_note = ?, updated_at = ?
            WHERE id = ?
        """, (mark, now, source, note or "", now, run_id))
        conn.commit()

        print(json.dumps({
            "run_id": run_id,
            "review_status": mark,
            "reviewed_at": now,
            "review_source": source,
            "review_note": note or "",
        }, ensure_ascii=False, indent=2))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Literature analysis run management")
    sub = parser.add_subparsers(dest="command")

    # --plan
    p_plan = sub.add_parser("plan", help="Generate task list for analysis")
    p_plan.add_argument("--angle", default="digest", help="Angle name (default: digest)")
    p_plan.add_argument("--template-version", type=int, default=1, help="Template version (default: 1)")

    # --submit
    p_submit = sub.add_parser("submit", help="Submit analysis results")
    p_submit.add_argument("--input", required=True, help="JSON file or directory path")
    p_submit.add_argument("--executor", default="human", help="Executor identity (default: human)")
    p_submit.add_argument("--model-name", default=None, help="Model name")
    p_submit.add_argument("--force", action="store_true", help="Force submit even if existing run")
    p_submit.add_argument("--strict", action="store_true", help="Reject if evidence quotes not found in content.md")

    # --status
    sub.add_parser("status", help="Show analysis coverage status")

    # --review
    p_review = sub.add_parser("review", help="Review an analysis run")
    p_review.add_argument("run_id", help="Run ID (e.g. AR-abc123def456)")
    p_review.add_argument("--mark", required=True, choices=["approved", "needs_fix", "rejected"], help="Review status")
    p_review.add_argument("--note", default=None, help="Review note")
    p_review.add_argument("--source", default="human", help="Review source (default: human)")

    args = parser.parse_args()

    if args.command == "plan":
        cmd_plan(args.angle, args.template_version)
    elif args.command == "submit":
        cmd_submit(args.input, args.executor, args.model_name, args.force, args.strict)
    elif args.command == "status":
        cmd_status()
    elif args.command == "review":
        cmd_review(args.run_id, args.mark, args.note, args.source)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
