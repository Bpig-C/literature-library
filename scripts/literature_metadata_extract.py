"""Extract structured metadata from MinerU content.md via local Ollama model.

Reads the front portion of each work's content.md, sends it to a local LLM,
and saves structured metadata (title, authors, year, abstract, etc.) with
field-level confidence scores.

Usage:
    python scripts/literature_metadata_extract.py --limit 3 --dry-run
    python scripts/literature_metadata_extract.py --limit 10
    python scripts/literature_metadata_extract.py --limit 10 --apply
    python scripts/literature_metadata_extract.py --work-id W-arxiv-2512.01166
"""

from __future__ import annotations

import argparse
import sys
import json
import re
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import urllib.error
import urllib.request


LIBRARY_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = LIBRARY_ROOT / "literature.sqlite"

DEFAULT_MODEL = "qwen3:4b-instruct-2507-q4_K_M"
DEFAULT_URL = "http://localhost:11435"
INPUT_CHAR_BUDGET = 8000


# ---------------------------------------------------------------------------
# Token estimation (simplified from meeting_ollama_eval.py)
# ---------------------------------------------------------------------------

def rough_token_count(text: str) -> int:
    if not text:
        return 0
    cjk = len(re.findall(r"[一-鿿぀-ヿ가-힯]", text))
    words = len(re.findall(r"[A-Za-z0-9_]+(?:[-'][A-Za-z0-9_]+)?", text))
    other = max(len(text) - cjk, 0)
    estimate = cjk * 1.05 + words * 1.3 + other * 0.18
    return max(1, int(estimate))


# ---------------------------------------------------------------------------
# Ollama HTTP helpers (stdlib only)
# ---------------------------------------------------------------------------

def http_post_json(url: str, payload: dict, timeout: int) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Cannot connect to Ollama: {e}") from e
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON response: {e}") from e


def ollama_chat(base_url: str, model: str, messages: list[dict],
                options: dict, timeout: int) -> dict:
    payload = {
        "model": model,
        "stream": False,
        "messages": messages,
        "options": options,
    }
    return http_post_json(f"{base_url.rstrip('/')}/api/chat", payload, timeout)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def get_works_to_process(conn: sqlite3.Connection, limit: int | None,
                          work_id: str | None) -> list[dict]:
    """Find works that need metadata extraction."""
    rows = conn.execute("""
        SELECT w.id, w.title, w.authors, w.year, w.arxiv_id, w.doi,
               lpr.content_md_path
        FROM works w
        JOIN literature_parse_runs lpr ON lpr.work_id = w.id
        WHERE lpr.status = 'succeeded'
          AND lpr.content_md_path IS NOT NULL
          AND lpr.content_md_path != ''
        GROUP BY w.id
        ORDER BY w.id
    """).fetchall()

    works = [dict(r) for r in rows]

    if work_id:
        works = [w for w in works if w["id"] == work_id]

    # Skip works that already have a recent extraction (within 7 days)
    recent = conn.execute("""
        SELECT work_id FROM metadata_extractions
        WHERE created_at > datetime('now', '-7 days')
    """).fetchall()
    recent_ids = {r["work_id"] for r in recent}
    works = [w for w in works if w["id"] not in recent_ids]

    if limit:
        works = works[:limit]

    return works


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """/no_think
You are a metadata extraction assistant for academic papers.
You extract structured bibliographic metadata from the beginning of a paper.
Output ONLY valid JSON. No explanations, no markdown, no <think> tags.
If information is not found in the text, use null for scalar fields and [] for arrays.
Always include the "evidence" and "confidence" objects.
For confidence, use "high" if the value is explicitly stated, "medium" if inferred, "low" if guessed."""

USER_PROMPT_TEMPLATE = """Extract metadata from this academic paper.
Output ONLY a JSON object. Be concise.

Rules for authors: list ONLY key authors (first author, last author, corresponding author,
project lead). Max 5 names. Use "et al." if there are more.

{{
  "title": "exact paper title",
  "title_zh": "Chinese title or null",
  "year": 2025,
  "authors": ["First Author", "Corresponding Author", "et al."],
  "author_count": 96,
  "institutions": ["Top 3 institutions only"],
  "doi": "10.xxxx/... or null",
  "arxiv_id": "2512.01166 or null",
  "venue": "journal/conference or null",
  "url": "URL or null",
  "abstract": "full abstract text or null",
  "evidence": {{"title": "snippet", "year": "snippet", "authors": "snippet"}},
  "confidence": {{"title": "high|medium|low", "year": "high|medium|low", "authors": "high|medium|low", "abstract": "high|medium|low"}},
  "missing": []
}}

Paper:

{text}"""


# ---------------------------------------------------------------------------
# JSON parsing with fallback
# ---------------------------------------------------------------------------

def parse_llm_json(raw: str) -> dict | None:
    """Try to extract a JSON object from LLM output, handling markdown fences."""
    text = raw.strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from ```json ... ``` block
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding first { ... last }
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last > first:
        try:
            return json.loads(text[first:last + 1])
        except json.JSONDecodeError:
            pass

    return None


# ---------------------------------------------------------------------------
# Apply high-confidence fields to works
# ---------------------------------------------------------------------------

HIGH_CONFIDENCE_FIELDS = {
    "title": "title",
    "year": "year",
    "doi": "doi",
    "arxiv_id": "arxiv_id",
    "venue": "venue",
    "url": "url",
    "abstract": "abstract",
    "title_zh": "title_zh",
}


def apply_to_works(conn: sqlite3.Connection, extractions: list[dict]) -> int:
    """Apply high-confidence extracted fields to works table. Returns count of updates."""
    updated = 0
    for ext in extractions:
        if not ext.get("applied"):
            continue
        extracted = json.loads(ext["extracted_json"]) if ext["extracted_json"] else {}
        confidence = json.loads(ext["confidence_json"]) if ext["confidence_json"] else {}
        work_id = ext["work_id"]

        sets = []
        params = []
        for field, col in HIGH_CONFIDENCE_FIELDS.items():
            if confidence.get(field) == "high" and extracted.get(field) is not None:
                value = extracted[field]
                if field == "authors":
                    value = json.dumps(value, ensure_ascii=False)
                sets.append(f"{col} = ?")
                params.append(value)

        # Also apply medium-confidence authors if high-confidence not available
        if "authors" not in [s.split(" =")[0] for s in sets]:
            if confidence.get("authors") in ("high", "medium") and extracted.get("authors"):
                authors_raw = extracted["authors"]
                if isinstance(authors_raw, list):
                    # Handle both string and object formats
                    names = []
                    for a in authors_raw:
                        if isinstance(a, str):
                            names.append(a)
                        elif isinstance(a, dict) and a.get("name"):
                            names.append(a["name"])
                    if names:
                        sets.append("authors = ?")
                        params.append(json.dumps(names, ensure_ascii=False))

        if sets:
            params.append(work_id)
            conn.execute(
                f"UPDATE works SET {', '.join(sets)}, updated_at = datetime('now') WHERE id = ?",
                params,
            )
            # Mark extraction as applied
            conn.execute(
                "UPDATE metadata_extractions SET applied = 1, applied_at = datetime('now') WHERE id = ?",
                (ext["id"],),
            )
            updated += 1

    conn.commit()
    return updated


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_extraction(args: argparse.Namespace) -> None:
    conn = connect_db()
    try:
        works = get_works_to_process(conn, args.limit, args.work_id)
        if not works:
            print("没有需要处理的文献。")
            return

        print(f"待处理：{len(works)} 篇文献")
        print(f"模型：{args.model}")
        print(f"Ollama：{args.url}")
        print()

        results = []
        for i, w in enumerate(works, 1):
            work_id = w["id"]
            content_path = Path(w["content_md_path"])

            print(f"[{i}/{len(works)}] {work_id} — {content_path.name}")

            if not content_path.exists():
                print(f"  SKIP: content.md not found at {content_path}")
                continue

            # Read front portion
            try:
                raw_text = content_path.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                print(f"  SKIP: cannot read {content_path}: {e}")
                continue

            text = raw_text[:INPUT_CHAR_BUDGET]
            input_tokens = rough_token_count(text)
            print(f"  输入：{len(text)} 字符 ≈ {input_tokens} tokens")

            # Build prompt
            user_msg = USER_PROMPT_TEMPLATE.format(text=text)
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ]
            options = {
                "num_ctx": 16384,
                "num_predict": 4096,
                "temperature": 0.2,
            }

            # Call Ollama
            try:
                resp = ollama_chat(args.url, args.model, messages, options, args.timeout)
                raw_response = resp.get("message", {}).get("content", "")
            except Exception as e:
                print(f"  ERROR: {e}")
                results.append({
                    "work_id": work_id,
                    "status": "error",
                    "error": str(e),
                })
                continue

            # Parse JSON
            extracted = parse_llm_json(raw_response)
            if not extracted:
                print(f"  WARN: 无法解析 JSON 响应")
                results.append({
                    "work_id": work_id,
                    "status": "parse_error",
                    "raw_response": raw_response[:500],
                })
                continue

            confidence = extracted.get("confidence", {})
            missing = extracted.get("missing", [])
            print(f"  标题：{extracted.get('title', 'N/A')[:60]}")
            print(f"  年份：{extracted.get('year', 'N/A')}")
            print(f"  关键作者：{extracted.get('authors', [])}")
            print(f"  总作者数：{extracted.get('author_count', 'N/A')}")
            print(f"  置信度：{json.dumps(confidence, ensure_ascii=False)}")
            if missing:
                print(f"  缺失：{', '.join(missing)}")

            # Save to DB
            if not args.dry_run:
                ext_id = f"ME-{uuid.uuid4().hex[:12]}"
                now = datetime.now(timezone.utc).isoformat(timespec="seconds")
                conn.execute("""
                    INSERT INTO metadata_extractions
                    (id, work_id, model_name, content_md_path, input_chars, input_tokens_est,
                     raw_response, extracted_json, confidence_json, applied, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """, (
                    ext_id, work_id, args.model, str(content_path),
                    len(text), input_tokens,
                    raw_response, json.dumps(extracted, ensure_ascii=False),
                    json.dumps(confidence, ensure_ascii=False), now,
                ))
                conn.commit()
                print(f"  已保存：{ext_id}")

            results.append({
                "work_id": work_id,
                "status": "ok",
                "title": extracted.get("title"),
                "year": extracted.get("year"),
                "authors_count": len(extracted.get("authors", [])),
                "confidence": confidence,
                "missing": missing,
            })
            print()

        # Apply high-confidence fields
        if args.apply and not args.dry_run:
            print("=== 应用高置信字段到 works 表 ===")
            exts = conn.execute(
                "SELECT * FROM metadata_extractions WHERE applied = 0"
            ).fetchall()
            n = apply_to_works(conn, [dict(e) for e in exts])
            print(f"更新了 {n} 篇文献的元数据")

        # Summary
        ok = sum(1 for r in results if r.get("status") == "ok")
        err = sum(1 for r in results if r.get("status") in ("error", "parse_error"))
        print(f"\n完成：{ok} 成功，{err} 失败，共 {len(results)} 篇")

        # Output JSON
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(results, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"报告已写入：{output_path}")

    finally:
        conn.close()


def main() -> None:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="基于 content.md 的元数据增强")
    parser.add_argument("--limit", type=int, default=None, help="最多处理 N 篇")
    parser.add_argument("--work-id", type=str, default=None, help="只处理指定 work ID")
    parser.add_argument("--dry-run", action="store_true", help="只抽取不写 DB")
    parser.add_argument("--apply", action="store_true", help="将高置信字段写入 works 表")
    parser.add_argument("--output", type=str, default=None, help="输出 JSON 路径")
    parser.add_argument("--url", type=str, default=DEFAULT_URL, help="Ollama URL")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="模型名")
    parser.add_argument("--timeout", type=int, default=300, help="HTTP 超时（秒）")
    args = parser.parse_args()

    run_extraction(args)


if __name__ == "__main__":
    main()
