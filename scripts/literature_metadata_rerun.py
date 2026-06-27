"""Agent CLI for metadata extraction rerun workflow.

The CLI can inspect review queues and create a true superseding extraction by
calling the same Ollama extraction helpers used by literature_metadata_extract.

Examples:
    python scripts/literature_metadata_rerun.py --status needs_fix --limit 10
    python scripts/literature_metadata_rerun.py --work-id W-arxiv-xxx
    python scripts/literature_metadata_rerun.py --ext-id ME-xxx --rerun
    python scripts/literature_metadata_rerun.py --ext-id ME-xxx --fields title,url --rerun
    python scripts/literature_metadata_rerun.py --status rejected --rerun --no-write --json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")

LIBRARY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIBRARY_ROOT))

from api.db import DB_PATH, ensure_metadata_review_columns  # noqa: E402
from api.risk import compute_risk  # noqa: E402
import llm_judge  # noqa: E402  本地强模型走 opencode→MiMo（P3.5，弃用 ollama:11435）
from scripts.literature_metadata_extract import (  # noqa: E402
    DEFAULT_MODEL,
    DEFAULT_URL,
    INPUT_CHAR_BUDGET,
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
    ollama_chat,
    parse_llm_json,
    rough_token_count,
    validate_extraction,
)

VALID_RERUN_FIELDS = {
    "title",
    "title_zh",
    "date",
    "authors",
    "author_count",
    "institutions",
    "doi",
    "arxiv_id",
    "venue",
    "url",
    "abstract",
}


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    ensure_metadata_review_columns(conn)
    return conn


def decode_extraction(row: sqlite3.Row | dict) -> dict:
    ext = dict(row)
    ext["extracted_json"] = json.loads(ext["extracted_json"]) if ext.get("extracted_json") else {}
    ext["confidence_json"] = json.loads(ext["confidence_json"]) if ext.get("confidence_json") else {}
    ext["risk_reasons"] = json.loads(ext["risk_reasons"]) if ext.get("risk_reasons") else []
    return ext


def list_queue(conn: sqlite3.Connection, status: str, limit: int) -> list[dict]:
    rows = conn.execute(
        "SELECT me.*, w.title AS work_title FROM metadata_extractions me "
        "JOIN works w ON w.id = me.work_id "
        "WHERE me.review_status = ? ORDER BY me.risk_score DESC LIMIT ?",
        (status, limit),
    ).fetchall()
    return [decode_extraction(row) for row in rows]


def history_for_work(conn: sqlite3.Connection, work_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT me.*, w.title AS work_title FROM metadata_extractions me "
        "JOIN works w ON w.id = me.work_id "
        "WHERE me.work_id = ? ORDER BY me.created_at DESC",
        (work_id,),
    ).fetchall()
    return [decode_extraction(row) for row in rows]


def extraction_by_id(conn: sqlite3.Connection, ext_id: str) -> dict | None:
    row = conn.execute(
        "SELECT me.*, w.title AS work_title FROM metadata_extractions me "
        "JOIN works w ON w.id = me.work_id "
        "WHERE me.id = ?",
        (ext_id,),
    ).fetchone()
    return decode_extraction(row) if row else None


def latest_extraction_for_work(conn: sqlite3.Connection, work_id: str) -> dict | None:
    rows = history_for_work(conn, work_id)
    return rows[0] if rows else None


def cluster_by_pattern(items: list[dict]) -> dict[str, list[str]]:
    clusters: dict[str, list[str]] = {}
    for item in items:
        for reason in item.get("risk_reasons", []):
            pattern = reason.split(":")[0].strip()
            clusters.setdefault(pattern, []).append(item["id"])
    return clusters


def show_queue(items: list[dict], clusters: dict[str, list[str]]) -> None:
    print(f"\nQueue: {len(items)} item(s)")
    if clusters:
        print("\nError-pattern clusters:")
        for pattern, ids in sorted(clusters.items(), key=lambda x: -len(x[1])):
            print(f"  {pattern}: {len(ids)} item(s)")
    print()
    for item in items:
        ej = item.get("extracted_json") or {}
        reasons = "; ".join((item.get("risk_reasons") or [])[:3])
        print(f"  {item['id']} | {item['work_id']} | risk={item.get('risk_level')}({item.get('risk_score')})")
        print(f"    title: {(ej.get('title') or 'N/A')[:80]}")
        print(f"    reasons: {reasons}")
        if item.get("review_note"):
            print(f"    review_note: {item['review_note']}")
        if item.get("superseded_by"):
            print(f"    superseded_by: {item['superseded_by']}")
        print()


def parse_fields(value: str | None) -> list[str]:
    if not value:
        return []
    fields = [item.strip() for item in value.split(",") if item.strip()]
    invalid = [field for field in fields if field not in VALID_RERUN_FIELDS]
    if invalid:
        raise SystemExit(f"Invalid --fields values: {', '.join(invalid)}")
    return fields


def field_focus_instruction(fields: list[str], review_note: str = "") -> str:
    if not fields and not review_note:
        return ""
    parts = []
    if fields:
        parts.append(
            "Focus especially on these fields and verify their evidence carefully: "
            + ", ".join(fields)
            + ". Still return the complete JSON schema."
        )
    if review_note:
        parts.append("Reviewer note to address: " + review_note)
    return "\n\nRerun instructions:\n" + "\n".join(f"- {part}" for part in parts)


def merge_selected_fields(old_data: dict, new_data: dict, fields: list[str]) -> dict:
    """For partial rerun, keep old fields and replace only selected ones."""
    if not fields:
        return new_data

    merged = dict(old_data)
    for field in fields:
        if field in new_data:
            merged[field] = new_data[field]

    for nested in ("evidence", "confidence"):
        old_nested = dict(old_data.get(nested) or {})
        new_nested = new_data.get(nested) or {}
        if isinstance(new_nested, dict):
            for field in fields:
                if field in new_nested:
                    old_nested[field] = new_nested[field]
        merged[nested] = old_nested
    return merged


def build_new_extraction(
    ext: dict,
    *,
    fields: list[str],
    model: str,
    url: str,
    timeout: int,
) -> dict:
    content_path = Path(ext["content_md_path"])
    if not content_path.exists():
        raise FileNotFoundError(f"content.md not found: {content_path}")

    raw_text = content_path.read_text(encoding="utf-8", errors="replace")
    text = raw_text[:INPUT_CHAR_BUDGET]
    input_tokens = rough_token_count(text)

    prompt = USER_PROMPT_TEMPLATE.format(text=text) + field_focus_instruction(
        fields, ext.get("review_note") or ""
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    options = {
        "num_ctx": 16384,
        "num_predict": 4096,
        "temperature": 0.2,
    }

    # opencode→MiMo（经 llm_judge；原 ollama:11435 已弃用；url/options 不再使用）
    response = llm_judge.chat(messages, model=model, timeout=timeout)
    raw_response = response.get("message", {}).get("content", "")
    parsed = parse_llm_json(raw_response)
    if not parsed:
        raise RuntimeError("LLM response did not contain valid JSON")

    new_extracted, validation_warnings = validate_extraction(parsed)
    final_extracted = merge_selected_fields(ext.get("extracted_json") or {}, new_extracted, fields)
    final_extracted, merge_warnings = validate_extraction(final_extracted)
    validation_warnings.extend(f"post-merge: {warning}" for warning in merge_warnings)

    confidence = final_extracted.get("confidence", {})
    risk = compute_risk(final_extracted, confidence, validation_warnings, ext.get("work_title"))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new_id = f"ME-{uuid.uuid4().hex[:12]}"

    note = [f"rerun from {ext['id']}"]
    if fields:
        note.append("fields=" + ",".join(fields))
    if ext.get("review_note"):
        note.append("review_note=" + ext["review_note"])

    return {
        "id": new_id,
        "old_id": ext["id"],
        "work_id": ext["work_id"],
        "model_name": model,
        "content_md_path": str(content_path),
        "input_chars": len(text),
        "input_tokens_est": input_tokens,
        "raw_response": raw_response,
        "extracted_json": final_extracted,
        "confidence_json": confidence,
        "risk": risk,
        "validation_warnings": validation_warnings,
        "review_note": "; ".join(note),
        "created_at": now,
        "fields": fields,
    }


def write_superseding_extraction(conn: sqlite3.Connection, new_ext: dict) -> None:
    risk = new_ext["risk"]
    conn.execute(
        """
        INSERT INTO metadata_extractions
        (id, work_id, model_name, content_md_path, input_chars, input_tokens_est,
         raw_response, extracted_json, confidence_json, applied,
         review_status, review_source, risk_level, risk_score, risk_reasons,
         review_note, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'pending', 'agent', ?, ?, ?, ?, ?)
        """,
        (
            new_ext["id"],
            new_ext["work_id"],
            new_ext["model_name"],
            new_ext["content_md_path"],
            new_ext["input_chars"],
            new_ext["input_tokens_est"],
            new_ext["raw_response"],
            json.dumps(new_ext["extracted_json"], ensure_ascii=False),
            json.dumps(new_ext["confidence_json"], ensure_ascii=False),
            risk["risk_level"],
            risk["risk_score"],
            json.dumps(risk["risk_reasons"], ensure_ascii=False),
            new_ext["review_note"],
            new_ext["created_at"],
        ),
    )
    conn.execute(
        "UPDATE metadata_extractions SET superseded_by = ?, fix_action = 'rerun_requested' WHERE id = ?",
        (new_ext["id"], new_ext["old_id"]),
    )
    conn.commit()


def select_rerun_target(conn: sqlite3.Connection, args: argparse.Namespace) -> dict:
    if args.ext_id:
        ext = extraction_by_id(conn, args.ext_id)
        if not ext:
            raise SystemExit(f"Extraction not found: {args.ext_id}")
        return ext
    if args.work_id:
        ext = latest_extraction_for_work(conn, args.work_id)
        if not ext:
            raise SystemExit(f"No extraction found for work: {args.work_id}")
        return ext
    queue = list_queue(conn, args.status, args.limit)
    if not queue:
        raise SystemExit("No queue item found to rerun")
    ext = extraction_by_id(conn, queue[0]["id"])
    if not ext:
        raise SystemExit(f"Extraction not found: {queue[0]['id']}")
    return ext


def main() -> None:
    parser = argparse.ArgumentParser(description="Metadata extraction rerun workflow")
    parser.add_argument("--status", type=str, default="needs_fix", help="Queue status filter")
    parser.add_argument("--limit", type=int, default=20, help="Maximum queue items")
    parser.add_argument("--work-id", type=str, default=None, help="Show/rerun extraction history for work ID")
    parser.add_argument("--ext-id", type=str, default=None, help="Specific extraction ID to rerun")
    parser.add_argument("--fields", type=str, default=None, help="Comma-separated fields to rerun")
    parser.add_argument("--rerun", action="store_true", help="Call Ollama and create a superseding extraction")
    parser.add_argument("--no-write", action="store_true", help="Preview rerun without writing DB")
    parser.add_argument("--cluster", action="store_true", help="Only show error-pattern clusters")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--url", type=str, default=DEFAULT_URL, help="Ollama URL")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="Ollama model")
    parser.add_argument("--timeout", type=int, default=300, help="HTTP timeout seconds")
    args = parser.parse_args()

    fields = parse_fields(args.fields)
    conn = connect_db()
    try:
        if args.rerun:
            ext = select_rerun_target(conn, args)
            new_ext = build_new_extraction(
                ext, fields=fields, model=args.model, url=args.url, timeout=args.timeout
            )
            if not args.no_write:
                write_superseding_extraction(conn, new_ext)
            if args.json:
                print(json.dumps(new_ext, ensure_ascii=False, indent=2))
            else:
                action = "Previewed" if args.no_write else "Created"
                print(f"{action}: {new_ext['old_id']} -> {new_ext['id']}")
                print(f"Work: {new_ext['work_id']}")
                if fields:
                    print(f"Fields: {', '.join(fields)}")
                print(f"Risk: {new_ext['risk']['risk_level']} ({new_ext['risk']['risk_score']})")
            return

        if args.work_id:
            items = history_for_work(conn, args.work_id)
        else:
            items = list_queue(conn, args.status, args.limit)
        clusters = cluster_by_pattern(items)

        if args.json:
            print(json.dumps({"items": items, "clusters": clusters}, ensure_ascii=False, indent=2))
        elif args.cluster:
            print(f"\nQueue: {len(items)} item(s)")
            print("\nError-pattern clusters:")
            for pattern, ids in sorted(clusters.items(), key=lambda x: -len(x[1])):
                print(f"  {pattern}: {len(ids)} item(s)")
        else:
            show_queue(items, clusters)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
