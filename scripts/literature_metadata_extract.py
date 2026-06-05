"""Extract structured metadata from MinerU content.md via local Ollama model.

Reads the front portion of each work's content.md, sends it to a local LLM,
and saves structured metadata (title, authors, year, abstract, etc.) with
field-level confidence scores.

Usage:
    python scripts/literature_metadata_extract.py --limit 3 --no-write
    python scripts/literature_metadata_extract.py --limit 10
    python scripts/literature_metadata_extract.py --limit 10 --apply
    python scripts/literature_metadata_extract.py --limit 10 --apply --overwrite
    python scripts/literature_metadata_extract.py --work-id W-arxiv-2512.01166 --force
"""

from __future__ import annotations

import argparse
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
                          work_id: str | None, force: bool = False) -> list[dict]:
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

    # Skip works that already have a recent extraction (within 7 days) unless --force
    if not force:
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
# Schema validation
# ---------------------------------------------------------------------------

CURRENT_YEAR = datetime.now().year


def validate_extraction(data: dict) -> tuple[dict, list[str]]:
    """Validate extracted metadata. Returns (cleaned_data, list_of_warnings).

    Invalid fields are set to None; warnings explain what was wrong.
    """
    warnings = []

    # year: must be integer in reasonable range
    year = data.get("year")
    if year is not None:
        try:
            year = int(year)
            if year < 1900 or year > CURRENT_YEAR + 1:
                warnings.append(f"year={year} out of range, set to null")
                year = None
        except (TypeError, ValueError):
            warnings.append(f"year={year!r} not integer, set to null")
            year = None
    data["year"] = year

    # authors: must be list
    authors = data.get("authors")
    if authors is not None and not isinstance(authors, list):
        warnings.append(f"authors not a list, set to []")
        authors = []
    data["authors"] = authors or []

    # confidence: must be object with valid values
    valid_levels = {"high", "medium", "low"}
    confidence = data.get("confidence", {})
    if not isinstance(confidence, dict):
        confidence = {}
    for key in list(confidence.keys()):
        if confidence[key] not in valid_levels:
            warnings.append(f"confidence.{key}={confidence[key]!r} invalid, removed")
            del confidence[key]
    data["confidence"] = confidence

    # doi: basic format check
    doi = data.get("doi")
    if doi is not None and doi != "" and not re.match(r"^10\.\d{4,}/", str(doi)):
        warnings.append(f"doi={doi!r} format suspect, set to null")
        data["doi"] = None

    # arxiv_id: basic format check
    arxiv = data.get("arxiv_id")
    if arxiv is not None and arxiv != "" and not re.match(r"^\d{4}\.\d{4,5}", str(arxiv)):
        warnings.append(f"arxiv_id={arxiv!r} format suspect, set to null")
        data["arxiv_id"] = None

    # url: basic format check
    url = data.get("url")
    if url is not None and url != "" and not url.startswith(("http://", "https://")):
        warnings.append(f"url={url!r} not a URL, set to null")
        data["url"] = None

    # title: must be non-empty string
    title = data.get("title")
    if title is not None and not isinstance(title, str):
        title = str(title) if title else None
    data["title"] = title

    # abstract: must be string
    abstract = data.get("abstract")
    if abstract is not None and not isinstance(abstract, str):
        abstract = None
    data["abstract"] = abstract

    return data, warnings


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


def apply_to_works(conn: sqlite3.Connection, extractions: list[dict],
                    overwrite: bool = False) -> int:
    """Apply high-confidence extracted fields to works table.

    Default: only fill empty fields (safe). With overwrite=True: also replace existing values.
    Returns count of updates.
    """
    updated = 0
    for ext in extractions:
        # Skip already-applied extractions (fixed: was inverted before)
        if ext.get("applied"):
            continue

        extracted = json.loads(ext["extracted_json"]) if ext["extracted_json"] else {}
        confidence = json.loads(ext["confidence_json"]) if ext["confidence_json"] else {}
        work_id = ext["work_id"]

        # Get current work data to check existing fields
        current = conn.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
        if not current:
            continue

        sets = []
        params = []
        for field, col in HIGH_CONFIDENCE_FIELDS.items():
            if confidence.get(field) != "high":
                continue
            value = extracted.get(field)
            if value is None or value == "":
                continue
            # Default: only fill empty fields. With --overwrite: replace existing.
            existing = current[col] if col in current.keys() else None
            if existing and not overwrite:
                continue
            if field == "authors":
                value = json.dumps(value, ensure_ascii=False)
            sets.append(f"{col} = ?")
            params.append(value)

        # Also apply medium/high-confidence authors
        if "authors" not in [s.split(" =")[0] for s in sets]:
            if confidence.get("authors") in ("high", "medium") and extracted.get("authors"):
                authors_raw = extracted["authors"]
                if isinstance(authors_raw, list):
                    names = [a for a in authors_raw if isinstance(a, str)]
                    if not names:
                        names = [a["name"] for a in authors_raw if isinstance(a, dict) and a.get("name")]
                    if names:
                        existing_authors = current["authors"] if "authors" in current.keys() else None
                        if not existing_authors or overwrite:
                            sets.append("authors = ?")
                            params.append(json.dumps(names, ensure_ascii=False))

        if sets:
            params.append(work_id)
            conn.execute(
                f"UPDATE works SET {', '.join(sets)}, updated_at = datetime('now') WHERE id = ?",
                params,
            )
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
        # Phase 1: Apply existing unapplied extractions (runs independently of extraction)
        if (args.apply or args.apply_only) and not args.no_write:
            print("=== 应用已有未应用的抽取结果 ===")
            exts = conn.execute(
                "SELECT * FROM metadata_extractions WHERE applied = 0"
            ).fetchall()
            if exts:
                n = apply_to_works(conn, [dict(e) for e in exts], overwrite=args.overwrite)
                mode = "覆盖" if args.overwrite else "仅填空"
                print(f"更新了 {n} 篇文献的元数据（{mode}模式）")
            else:
                print("没有未应用的抽取结果。")
            print()

        # Phase 2: Extract new metadata (skip if --apply-only or no works to process)
        if args.apply_only:
            works = []
        else:
            works = get_works_to_process(conn, args.limit, args.work_id, force=args.force)
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

            # Validate extracted fields
            extracted, validation_warnings = validate_extraction(extracted)
            if validation_warnings:
                for w in validation_warnings:
                    print(f"  校验：{w}")

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
            if not args.no_write:
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

        # Phase 3: Apply newly extracted results (not needed for --apply-only)
        if args.apply and not args.no_write and not args.apply_only and results:
            new_exts = conn.execute(
                "SELECT * FROM metadata_extractions WHERE applied = 0"
            ).fetchall()
            if new_exts:
                print("=== 应用本轮新抽取结果 ===")
                n = apply_to_works(conn, [dict(e) for e in new_exts], overwrite=args.overwrite)
                mode = "覆盖" if args.overwrite else "仅填空"
                print(f"更新了 {n} 篇文献的元数据（{mode}模式）")

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
    parser.add_argument("--no-write", action="store_true", help="调用模型但不写 DB（仍消耗 Ollama 资源）")
    parser.add_argument("--apply", action="store_true", help="将高置信字段写入 works 表（可与抽取同时运行）")
    parser.add_argument("--apply-only", action="store_true", help="只应用已有未应用的抽取结果，不调用模型")
    parser.add_argument("--overwrite", action="store_true", help="配合 --apply/--apply-only 使用，覆盖已有字段（默认只填空字段）")
    parser.add_argument("--force", action="store_true", help="跳过 7 天去重检查，强制重新抽取")
    parser.add_argument("--output", type=str, default=None, help="输出 JSON 路径")
    parser.add_argument("--url", type=str, default=DEFAULT_URL, help="Ollama URL")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="模型名")
    parser.add_argument("--timeout", type=int, default=300, help="HTTP 超时（秒）")
    args = parser.parse_args()

    run_extraction(args)


if __name__ == "__main__":
    main()
