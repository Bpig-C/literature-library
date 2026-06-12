"""Extract classification candidates from literature via local Ollama model.

Reads the front portion of each work's content.md, sends it to a local LLM,
and saves structured classification (primary_doc_type, publication_status,
reading_lane, etc.) with field-level confidence scores and ambiguity scoring.

Usage:
    python scripts/literature_classification_extract.py --limit 5 --no-write
    python scripts/literature_classification_extract.py --limit 10
    python scripts/literature_classification_extract.py --limit 10 --apply
    python scripts/literature_classification_extract.py --work-id W-arxiv-2512.01166 --force
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
import urllib.error
import urllib.request


LIBRARY_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = LIBRARY_ROOT / "literature.sqlite"

sys.path.insert(0, str(LIBRARY_ROOT))
from api.classification_ambiguity import compute_ambiguity  # noqa: E402
from api.classification_vocab import VOCAB, validate_tag_value  # noqa: E402

DEFAULT_MODEL = "qwen3:4b-instruct-2507-q4_K_M"
DEFAULT_URL = "http://localhost:11435"
INPUT_CHAR_BUDGET = 8000


# ---------------------------------------------------------------------------
# Token estimation
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

def _get_opener(url: str):
    """Return an opener that bypasses proxy for localhost URLs."""
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ""
    if host in ("localhost", "127.0.0.1", "::1"):
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def http_post_json(url: str, payload: dict, timeout: int) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    opener = _get_opener(url)
    try:
        with opener.open(req, timeout=timeout) as resp:
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
    """Find works that need classification extraction."""
    rows = conn.execute("""
        SELECT w.id, w.title, w.authors, w.year, w.doc_type, w.arxiv_id,
               w.doi, w.venue, w.url, lpr.content_md_path
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

    # Skip works that already have a recent extraction unless --force
    if not force:
        recent = conn.execute("""
            SELECT work_id FROM classification_extractions
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
You classify literature records for a local AI safety literature library.
Use only the provided vocabulary and rules.
Do not invent tag values.
If evidence is insufficient, use null for scalar fields and [] for list fields.
Output only valid JSON. No markdown, no explanations, no thinking traces.

Core rule:
- primary_doc_type is the document identity, single-choice, with three-tier priority:
  Tier 1 (functional types, prefer): system_model_card, governance_framework, standard_guideline, benchmark_dataset_paper, evaluation_report
  Tier 2 (form types, fallback): technical_report, institutional_report, research_article, survey_review, platform_snapshot, thesis, book_chapter, webpage_blog, other_literature
  Tier 3 (existence markers): not_literature, workflow_artifact
- If a document matches a Tier 1 type, use it as primary_doc_type even if it also has Tier 2 form attributes.
- Use secondary_doc_type to record the次要形态属性 when a document spans two tiers (e.g., evaluation_report that is also technically a technical_report).
- publication_status is release status, not document type.
- reading_lane means why we read it.
- artifact_focus means what it contributes or discusses.
- risk_domain and method_tags are optional; fill only when explicit.

For each scalar field, give confidence (high/medium/low).
For reading_lane and artifact_focus, give evidence snippets.
Always include "evidence" and "confidence" objects.
Always include "alternative_primary_doc_types" (list of other plausible types, can be [])."""

USER_PROMPT_TEMPLATE = """Classify this literature record.
Output ONLY a JSON object.

Vocabulary (use ONLY these values):

primary_doc_type: {primary_doc_types}

publication_status: {publication_statuses}

primary_source_actor_type: {actor_types}

region: {regions}

reading_lane: {reading_lanes}

artifact_focus: {artifact_focuses}

ingestion_state: {ingestion_states}

priority: {priorities}

risk_domain (optional, fill only when explicit): {risk_domains}

method_tags (optional, fill only when explicit): {method_tags_list}

Primary doc type decision order (three-tier hierarchy):

Tier 1 — Functional types (prefer if document matches):
1. system/model/safety card / transparency report -> system_model_card
2. standard/guideline/code of practice -> standard_guideline
3. safety/risk/governance/deployment framework -> governance_framework
4. reusable benchmark/dataset/eval suite as main contribution -> benchmark_dataset_paper
5. third-party structural evaluation of a model/system/framework -> evaluation_report

Tier 2 — Form types (use only when no Tier 1 match):
5.5 leaderboard/dashboard/platform snapshot -> platform_snapshot
6. thesis -> thesis
7. technical object centered report -> technical_report
8. institutional trend/landscape/annual/capacity report -> institutional_report
9. survey/review/position paper -> survey_review
10. ordinary research article -> research_article
11. webpage/blog -> webpage_blog
12. other related literature -> other_literature

Tier 3 — Existence markers (not document form):
13. workflow artifact -> workflow_artifact
14. not literature / invalid -> not_literature

If a document matches Tier 1, use that as primary_doc_type even if it also has Tier 2 form attributes.
Use secondary_doc_type to record the form attribute when a document spans tiers (e.g., evaluation_report that is also technically a technical_report). secondary_doc_type is optional, use only when the secondary attribute adds classification value.

Ambiguity rules:
- A system/model card written by the model developer -> system_model_card (not evaluation_report)
- A benchmark paper that introduces a new benchmark -> benchmark_dataset_paper
- A paper that runs existing benchmarks on a model -> evaluation_report
- A framework document proposing governance mechanisms -> governance_framework
- A report surveying the AI safety landscape -> survey_review
- An annual report from an institution -> institutional_report
- A technical report describing a system's architecture -> technical_report

Existing local context:
id: {work_id}
title: {title}
old_doc_type: {doc_type}
source_file_names: {source_file_names}
arxiv_id: {arxiv_id}
doi: {doi}
venue: {venue}
url: {url}

Document excerpt:
{text}

Return JSON:
{{
  "primary_doc_type": "one of the vocabulary values or null",
  "secondary_doc_type": "optional, one of the vocabulary values or null — use when document spans two tiers",
  "publication_status": "one of the vocabulary values or null",
  "primary_source_actor_type": "one of the vocabulary values or null",
  "region": "one of the vocabulary values or null",
  "reading_lane": ["list of vocabulary values"],
  "artifact_focus": ["list of vocabulary values"],
  "risk_domain": ["list of vocabulary values, empty if not explicit"],
  "method_tags": ["list of vocabulary values, empty if not explicit"],
  "ingestion_state": "one of the vocabulary values or null",
  "priority": "one of the vocabulary values or null",
  "alternative_primary_doc_types": ["other plausible types"],
  "evidence": {{
    "primary_doc_type": "snippet from text supporting this choice",
    "publication_status": "snippet",
    "reading_lane": "snippet",
    "artifact_focus": "snippet"
  }},
  "confidence": {{
    "primary_doc_type": "high|medium|low",
    "publication_status": "high|medium|low",
    "primary_source_actor_type": "high|medium|low",
    "reading_lane": "high|medium|low",
    "artifact_focus": "high|medium|low",
    "risk_domain": "high|medium|low",
    "method_tags": "high|medium|low",
    "ingestion_state": "high|medium|low",
    "priority": "high|medium|low"
  }},
  "ambiguity_notes": "brief explanation if classification is uncertain"
}}"""


# ---------------------------------------------------------------------------
# JSON parsing with fallback
# ---------------------------------------------------------------------------

def parse_llm_json(raw: str) -> dict | None:
    """Try to extract a JSON object from LLM output, handling markdown fences."""
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


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_extraction(data: dict) -> tuple[dict, list[str]]:
    """Validate extracted classification. Returns (cleaned_data, warnings)."""
    warnings = []
    valid_levels = {"high", "medium", "low"}

    # Validate scalar fields against vocabulary
    SCALAR_FIELDS = {
        "primary_doc_type": "primary_doc_type",
        "secondary_doc_type": "primary_doc_type",  # uses same vocab as primary_doc_type
        "publication_status": "publication_status",
        "primary_source_actor_type": "primary_source_actor_type",
        "region": "region",
        "ingestion_state": "ingestion_state",
        "priority": "priority",
    }
    for field, vocab_key in SCALAR_FIELDS.items():
        val = data.get(field)
        if val is not None:
            if not validate_tag_value(vocab_key, val):
                warnings.append(f"{field}={val!r} not in vocabulary, set to null")
                data[field] = None

    # Validate list fields against vocabulary
    LIST_FIELDS = {
        "reading_lane": "reading_lane",
        "artifact_focus": "artifact_focus",
        "risk_domain": "risk_domain",
        "method_tags": "method_tags",
    }
    for field, vocab_key in LIST_FIELDS.items():
        vals = data.get(field)
        if vals is not None and not isinstance(vals, list):
            warnings.append(f"{field} not a list, set to []")
            data[field] = []
            vals = []
        if vals:
            cleaned = []
            for v in vals:
                if validate_tag_value(vocab_key, v):
                    cleaned.append(v)
                else:
                    warnings.append(f"{field} contains invalid value {v!r}, removed")
            data[field] = cleaned

    # Validate confidence
    confidence = data.get("confidence", {})
    if not isinstance(confidence, dict):
        warnings.append("confidence not an object, set to {}")
        confidence = {}
    for key in list(confidence.keys()):
        value = confidence[key]
        if not isinstance(value, str) or value not in valid_levels:
            warnings.append(f"confidence.{key}={value!r} invalid, removed")
            del confidence[key]
    data["confidence"] = confidence

    # Validate alternative_primary_doc_types
    alts = data.get("alternative_primary_doc_types")
    if alts is not None:
        if not isinstance(alts, list):
            data["alternative_primary_doc_types"] = []
        else:
            data["alternative_primary_doc_types"] = [
                a for a in alts if isinstance(a, str) and validate_tag_value("primary_doc_type", a)
            ]

    return data, warnings


# ---------------------------------------------------------------------------
# Apply low-ambiguity results to works
# ---------------------------------------------------------------------------

CLASSIFICATION_FIELDS = {
    "primary_doc_type": "primary_doc_type",
    "secondary_doc_type": "secondary_doc_type",
    "publication_status": "publication_status",
    "ingestion_state": "ingestion_state",
    "priority": "priority",
    "primary_source_actor_type": "primary_source_actor_type",
    "region": "region",
}


def apply_to_works(conn: sqlite3.Connection, extractions: list[dict],
                    ambiguity_threshold: int = 20) -> int:
    """Apply low-ambiguity classification results to works and tags.

    Only applies when:
    - ambiguity_score <= ambiguity_threshold
    - primary_doc_type evidence is non-empty
    - extraction not yet applied

    Returns count of updates.
    """
    updated = 0
    for ext in extractions:
        if ext.get("applied"):
            continue

        extracted = json.loads(ext["extracted_json"]) if ext["extracted_json"] else {}
        confidence = json.loads(ext["confidence_json"]) if ext["confidence_json"] else {}
        ambiguity_score = ext.get("ambiguity_score", 100)
        work_id = ext["work_id"]

        if ambiguity_score > ambiguity_threshold:
            continue

        # Check evidence for primary_doc_type
        evidence = extracted.get("evidence") or {}
        if not evidence.get("primary_doc_type"):
            continue

        # Merge dual-source confidence (D1 read-side fix)
        embedded_confidence = extracted.get("confidence", {})
        merged_confidence = {**embedded_confidence, **confidence}

        # Update works table scalar fields (fill-empty only)
        current = conn.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
        if not current:
            continue

        sets = []
        params = []
        for field, col in CLASSIFICATION_FIELDS.items():
            if col not in {d[0] for d in conn.execute("PRAGMA table_info(works)").fetchall()}:
                continue
            value = extracted.get(field)
            if value is None:
                continue
            existing = current[col] if col in current.keys() else None
            if existing:
                continue
            sets.append(f"{col} = ?")
            params.append(value)

        if sets:
            params.append(work_id)
            conn.execute(
                f"UPDATE works SET {', '.join(sets)} WHERE id = ?",
                params,
            )

        # Write multi-value tags (reading_lane, artifact_focus, risk_domain, method_tags)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        TAG_GROUPS = ["reading_lane", "artifact_focus", "risk_domain", "method_tags"]
        for group in TAG_GROUPS:
            values = extracted.get(group) or []
            for v in values:
                # Check if tag already exists
                existing = conn.execute(
                    "SELECT 1 FROM work_classification_tags WHERE work_id = ? AND tag_group = ? AND tag_value = ?",
                    (work_id, group, v),
                ).fetchone()
                if not existing:
                    tag_id = f"CT-{uuid.uuid4().hex[:12]}"
                    conn.execute(
                        "INSERT INTO work_classification_tags "
                        "(id, work_id, tag_group, tag_value, source, confidence, evidence, "
                        "review_status, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, 'model', ?, ?, 'pending', ?, ?)",
                        (tag_id, work_id, group, v,
                         merged_confidence.get(group, "low"),
                         evidence.get(group, ""),
                         now, now),
                    )

        # Mark as applied
        conn.execute(
            "UPDATE classification_extractions SET applied = 1, applied_at = datetime('now') WHERE id = ?",
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
        # Phase 1: Apply existing unapplied low-ambiguity extractions
        if args.apply and not args.no_write:
            print("=== 应用已有未应用的分类结果 ===")
            exts = conn.execute(
                "SELECT * FROM classification_extractions WHERE applied = 0 AND review_status = 'pending'"
            ).fetchall()
            if exts:
                n = apply_to_works(conn, [dict(e) for e in exts], args.ambiguity_threshold)
                print(f"更新了 {n} 篇文献的分类")
            else:
                print("没有未应用的分类结果。")
            print()

        # Phase 2: Extract new classifications
        if args.apply_only:
            works = []
        else:
            works = get_works_to_process(conn, args.limit, args.work_id, force=args.force)
        if not works:
            print("没有需要处理的文献。")
            return

        # Supersede old pending extractions for works about to be re-extracted
        work_ids_to_extract = [w["id"] for w in works]
        if work_ids_to_extract and not args.no_write:
            placeholders = ",".join("?" * len(work_ids_to_extract))
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            result = conn.execute(
                f"UPDATE classification_extractions SET "
                f"review_status = 'rejected', "
                f"fix_action = 'superseded', "
                f"review_note = 'superseded by new extraction run', "
                f"reviewed_at = ? "
                f"WHERE work_id IN ({placeholders}) AND review_status = 'pending'",
                [now] + work_ids_to_extract,
            )
            superseded_count = result.rowcount
            if superseded_count > 0:
                conn.commit()
                print(f"已废掉 {superseded_count} 条旧 pending extractions")

        print(f"待处理：{len(works)} 篇文献")
        print(f"模型：{args.model}")
        print(f"Ollama：{args.url}")
        print()

        # Build vocabulary strings for prompt
        vocab_strs = {
            "primary_doc_types": ", ".join(VOCAB["primary_doc_type"]),
            "publication_statuses": ", ".join(VOCAB["publication_status"]),
            "actor_types": ", ".join(VOCAB["primary_source_actor_type"]),
            "regions": ", ".join(VOCAB["region"]),
            "reading_lanes": ", ".join(VOCAB["reading_lane"]),
            "artifact_focuses": ", ".join(VOCAB["artifact_focus"]),
            "ingestion_states": ", ".join(VOCAB["ingestion_state"]),
            "priorities": ", ".join(VOCAB["priority"]),
            "risk_domains": ", ".join(VOCAB["risk_domain"]),
            "method_tags_list": ", ".join(VOCAB["method_tags"]),
        }

        results = []
        for i, w in enumerate(works, 1):
            work_id = w["id"]
            content_path = Path(w["content_md_path"])

            print(f"[{i}/{len(works)}] {work_id}")

            if not content_path.exists():
                print(f"  SKIP: content.md not found at {content_path}")
                continue

            try:
                raw_text = content_path.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                print(f"  SKIP: cannot read {content_path}: {e}")
                continue

            text = raw_text[:INPUT_CHAR_BUDGET]
            input_tokens = rough_token_count(text)
            print(f"  输入：{len(text)} 字符 ≈ {input_tokens} tokens")

            # Build source file names string
            source_names = ""
            try:
                sf_rows = conn.execute(
                    "SELECT original_name FROM source_files WHERE work_id = ?", (work_id,)
                ).fetchall()
                source_names = ", ".join(r["original_name"] for r in sf_rows if r["original_name"])
            except Exception:
                pass

            user_msg = USER_PROMPT_TEMPLATE.format(
                text=text,
                work_id=work_id,
                title=w.get("title") or "",
                doc_type=w.get("doc_type") or "",
                source_file_names=source_names,
                arxiv_id=w.get("arxiv_id") or "",
                doi=w.get("doi") or "",
                venue=w.get("venue") or "",
                url=w.get("url") or "",
                **vocab_strs,
            )
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
                results.append({"work_id": work_id, "status": "error", "error": str(e)})
                continue

            # Parse JSON
            extracted = parse_llm_json(raw_response)
            if not extracted:
                print(f"  WARN: 无法解析 JSON 响应")
                results.append({"work_id": work_id, "status": "parse_error", "raw_response": raw_response[:500]})
                continue

            # Validate
            try:
                extracted, validation_warnings = validate_extraction(extracted)
            except Exception as e:
                print(f"  ERROR: validation failed: {e}")
                results.append({"work_id": work_id, "status": "validation_error", "error": str(e)})
                continue

            confidence = extracted.get("confidence", {})

            # Compute ambiguity
            amb = compute_ambiguity(extracted, confidence)

            pdt = extracted.get("primary_doc_type") or "N/A"
            sdt = extracted.get("secondary_doc_type") or ""
            ps = extracted.get("publication_status") or "N/A"
            rl = extracted.get("reading_lane") or []
            af = extracted.get("artifact_focus") or []
            print(f"  primary_doc_type: {pdt} (conf={confidence.get('primary_doc_type', '?')})")
            if sdt:
                print(f"  secondary_doc_type: {sdt}")
            print(f"  publication_status: {ps}")
            print(f"  reading_lane: {rl}")
            print(f"  artifact_focus: {af}")
            print(f"  ambiguity_score: {amb['score']}")
            if amb["reasons"]:
                print(f"  ambiguity_reasons: {'; '.join(amb['reasons'][:3])}")
            if validation_warnings:
                for w_msg in validation_warnings:
                    print(f"  校验：{w_msg}")

            # Save to DB
            if not args.no_write:
                ext_id = f"CE-{uuid.uuid4().hex[:12]}"
                now = datetime.now(timezone.utc).isoformat(timespec="seconds")

                conn.execute("""
                    INSERT INTO classification_extractions
                    (id, work_id, model_name, prompt_version, extracted_json, confidence_json,
                     ambiguity_score, ambiguity_reasons, review_status, applied,
                     raw_response, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)
                """, (
                    ext_id, work_id, args.model, "v1",
                    json.dumps(extracted, ensure_ascii=False),
                    json.dumps(confidence, ensure_ascii=False),
                    amb["score"],
                    json.dumps(amb["reasons"], ensure_ascii=False),
                    raw_response, now, now,
                ))
                conn.commit()
                print(f"  已保存：{ext_id} (ambiguity={amb['score']})")

            results.append({
                "work_id": work_id,
                "status": "ok",
                "primary_doc_type": extracted.get("primary_doc_type"),
                "secondary_doc_type": extracted.get("secondary_doc_type"),
                "publication_status": extracted.get("publication_status"),
                "reading_lane": extracted.get("reading_lane"),
                "artifact_focus": extracted.get("artifact_focus"),
                "confidence": confidence,
                "ambiguity_score": amb["score"],
                "ambiguity_reasons": amb["reasons"],
                "validation_warnings": validation_warnings,
            })
            print()

        # Phase 3: Apply newly extracted results
        if args.apply and not args.no_write and not args.apply_only and results:
            new_exts = conn.execute(
                "SELECT * FROM classification_extractions WHERE applied = 0 AND review_status = 'pending'"
            ).fetchall()
            if new_exts:
                print("=== 应用本轮新抽取结果 ===")
                n = apply_to_works(conn, [dict(e) for e in new_exts], args.ambiguity_threshold)
                print(f"更新了 {n} 篇文献的分类")

        # Summary
        ok = sum(1 for r in results if r.get("status") == "ok")
        err = sum(1 for r in results if r.get("status") in ("error", "parse_error", "validation_error"))
        print(f"\n完成：{ok} 成功，{err} 失败，共 {len(results)} 篇")

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


def main():
    parser = argparse.ArgumentParser(description="Extract classification candidates via Ollama")
    parser.add_argument("--limit", type=int, default=None, help="Max works to process")
    parser.add_argument("--work-id", type=str, default=None, help="Process specific work")
    parser.add_argument("--force", action="store_true", help="Re-extract even if recent extraction exists")
    parser.add_argument("--no-write", action="store_true", help="Print only, don't write to DB")
    parser.add_argument("--apply", action="store_true", help="Apply low-ambiguity results to works")
    parser.add_argument("--apply-only", action="store_true", help="Only apply, don't extract")
    parser.add_argument("--ambiguity-threshold", type=int, default=20,
                        help="Max ambiguity score for auto-apply (default: 20)")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL)
    parser.add_argument("--url", type=str, default=DEFAULT_URL)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--output", type=str, default=None, help="Write JSON report to file")
    args = parser.parse_args()
    run_extraction(args)


if __name__ == "__main__":
    main()
