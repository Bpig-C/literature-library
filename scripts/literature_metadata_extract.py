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

# Import risk computation from api package
sys.path.insert(0, str(LIBRARY_ROOT))
from api.risk import compute_risk  # noqa: E402
from scripts import llm_judge  # noqa: E402  opencode→MiMo；scripts 是包，勿裸 import（pytest 包导入会 ModuleNotFoundError）

DEFAULT_MODEL = llm_judge.DEFAULT_MODEL  # mimo/mimo-v2.5-pro
DEFAULT_URL = "opencode→MiMo（经 llm_judge；--url 仅作占位，不再使用）"
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
You extract structured metadata from documents (papers, reports, standards, webpages, etc.).
Output ONLY valid JSON. No explanations, no markdown, no <think> tags.
If information is not found, use null for scalars and [] for arrays.
Always include "evidence" and "confidence" objects.
Confidence: "high" = explicitly stated, "medium" = inferred, "low" = guessed.
For "missing", list field names that could not be filled from: title, title_zh, publication_date, authors, contributors, doi, arxiv_id, venue, url, abstract."""

USER_PROMPT_TEMPLATE = """Extract metadata from this document.

Step 1 — Identify the document type (for your reference, do NOT output it):
- research_article: academic paper with authors, abstract, venue
- technical_report: report from a company/lab/team, may have no personal authors
- standard_guideline: published by standards body or government
- webpage_blog: online content, blog post, news article
- survey_review: literature review or meta-analysis
- other: anything else

Step 2 — Apply rules based on document type:

COMMON RULES:
- title_zh: Chinese translation if original is not Chinese. Keep proper nouns untranslated. null if uncertain.
- url: Priority: (1) paper homepage, (2) arXiv abs, (3) DOI landing, (4) publisher page.
  NEVER use license URLs, GitHub/GitLab links, or news articles.
- publication_date: extract year at minimum. Add month/day if found. "raw" is original text, "kind" is "exact" or "inferred".

AUTHORS — personal names only:
- research_article: list key authors (first, last, corresponding). Max 5. String format.
- technical_report: personal authors IF present. If only institution/team authored it, authors = [].
- standard_guideline: usually no personal authors, authors = [].
- webpage_blog: author name if present, otherwise [].

CONTRIBUTORS — non-personal entities (institution, team, publisher, funder):
- Always include the publishing/releasing entity.
- type MUST be one of: university, company, government, lab, team, standards_body, unknown.
  - lab = stable research unit (Google DeepMind, MIT Media Lab)
  - team = project/temporary team (Anthropic Red Team, Meta FAIR Team)
- role MUST be one of: author, publisher, issuer, funder, collaborator.
  - author = entity credited as author (e.g. "Anthropic Red Team")
  - publisher = entity that published/released the document
  - issuer = entity that formally issued/certified (standards body, government)
  - funder = funding organization
  - collaborator = contributing organization

TYPE-SPECIFIC RULES:
- research_article: doi, arxiv_id, venue are important. institutions from author affiliations.
- technical_report: contributors (publisher/team) is key. No doi/venue expected.
- standard_guideline: issuer is the standards body. version/number if present.
- webpage_blog: url is primary identifier. site name in venue.

{{
  "title": "exact document title",
  "title_zh": "Chinese title or null",
  "publication_date": {{"year": 2025, "month": null, "day": null, "raw": "2025", "kind": "exact"}},
  "authors": ["Personal Author Name"],
  "contributors": [{{"name": "Org Name", "type": "company", "role": "publisher"}}],
  "doi": "10.xxxx/... or null",
  "arxiv_id": "2512.01166 or null",
  "venue": "journal/conference/institution or null",
  "url": "primary URL or null",
  "abstract": "full abstract/summary text or null",
  "evidence": {{"title": "snippet", "publication_date": "snippet", "authors": "snippet", "contributors": "snippet", "abstract": "snippet"}},
  "confidence": {{"title": "high|medium|low", "publication_date": "high|medium|low", "authors": "high|medium|low", "contributors": "high|medium|low", "abstract": "high|medium|low"}},
  "missing": []
}}

Document:

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
    """Validate extracted metadata. Returns (cleaned_data, list_of_warnings)."""
    warnings = []
    valid_levels = {"high", "medium", "low"}

    VALID_CONTRIB_TYPES = {"university", "company", "government", "lab", "team", "standards_body", "unknown"}
    VALID_CONTRIB_ROLES = {"author", "publisher", "issuer", "funder", "collaborator"}
    CONTRIB_TYPE_MAP = {
        "research institute": "lab", "research lab": "lab", "institute": "lab",
        "organization": "company", "org": "company", "nonprofit": "lab",
        "non-profit": "lab", "think tank": "lab", "consortium": "lab",
    }
    COMPANY_KEYWORDS = (
        "google", "deepmind", "microsoft", "openai", "anthropic", "meta",
        "apple", "amazon", "nvidia", "ibm", "samsung", "huawei", "baidu",
        "alibaba", "tencent", "bytedance", "xai", "inflection",
    )
    GOV_KEYWORDS = ("nist", " nasa ", "esa ", " nsf ", "nih ", " government")
    LAB_KEYWORDS = (
        "ai lab", "ai laboratory", "人工智能实验室", "mila", "allen institute",
        "salk institute", "iisc", "csiro",
    )
    UNIV_KEYWORDS = ("university", "université", "universität", "大学", "college", "institute of technology")
    TEAM_KEYWORDS = ("red team", "safety team", "alignment team", "research team")

    # --- publication_date (replaces old "date") ---
    pub_date = data.get("publication_date") or data.get("date")
    if pub_date is None:
        year = data.get("year")
        if year is not None:
            try:
                year = int(year)
                if 1900 <= year <= CURRENT_YEAR + 1:
                    pub_date = {"year": year, "month": None, "day": None,
                                "raw": str(year), "kind": "inferred"}
                    warnings.append("publication_date missing, promoted top-level year")
                else:
                    warnings.append(f"year={year} out of range, set to null")
            except (TypeError, ValueError):
                warnings.append(f"year={year!r} not integer, set to null")
    if isinstance(pub_date, dict):
        y = pub_date.get("year")
        if y is not None:
            try:
                y = int(y)
                if y < 1900 or y > CURRENT_YEAR + 1:
                    warnings.append(f"publication_date.year={y} out of range, set to null")
                    y = None
            except (TypeError, ValueError):
                warnings.append(f"publication_date.year={y!r} not integer, set to null")
                y = None
        pub_date["year"] = y
        for k in ("month", "day"):
            v = pub_date.get(k)
            if v is not None:
                try:
                    pub_date[k] = int(v)
                except (TypeError, ValueError):
                    pub_date[k] = None
        if pub_date.get("kind") not in ("exact", "inferred", None):
            warnings.append(f"publication_date.kind={pub_date['kind']!r} invalid, set to null")
            pub_date["kind"] = None
    elif pub_date is not None:
        warnings.append("publication_date not an object, set to null")
        pub_date = None
    data["publication_date"] = pub_date
    data["year"] = pub_date["year"] if isinstance(pub_date, dict) else None
    # Remove legacy fields
    data.pop("date", None)

    # --- authors: list of strings (personal names only) ---
    authors = data.get("authors")
    if authors is not None and not isinstance(authors, list):
        warnings.append("authors not a list, set to []")
        authors = []
    cleaned_authors = []
    for a in (authors or []):
        if isinstance(a, str) and a.strip():
            cleaned_authors.append(a.strip())
        elif isinstance(a, dict) and a.get("name"):
            cleaned_authors.append(str(a["name"]).strip())
    if len(cleaned_authors) > 5:
        data["all_authors"] = cleaned_authors
        data["authors"] = cleaned_authors[:5]
        warnings.append(f"authors truncated from {len(cleaned_authors)} to 5, full list in all_authors")
    else:
        data["authors"] = cleaned_authors

    # --- contributors: list of objects ---
    contributors = data.get("contributors")
    if contributors is not None and not isinstance(contributors, list):
        warnings.append("contributors not a list, set to []")
        contributors = []
    cleaned_contribs = []
    for c in (contributors or []):
        if not isinstance(c, dict) or not c.get("name"):
            continue
        name = str(c["name"]).strip()
        ctype = str(c.get("type") or "").lower().strip()
        role = str(c.get("role") or "").lower().strip()
        # Normalize type
        if ctype in CONTRIB_TYPE_MAP:
            ctype = CONTRIB_TYPE_MAP[ctype]
        elif ctype not in VALID_CONTRIB_TYPES:
            ctype = "unknown"
        # Name-based type override
        name_lower = name.lower()
        if any(k in name_lower for k in COMPANY_KEYWORDS):
            ctype = "company"
        elif any(k in name_lower for k in GOV_KEYWORDS):
            ctype = "government"
        elif any(k in name_lower for k in LAB_KEYWORDS):
            ctype = "lab"
        elif any(k in name_lower for k in UNIV_KEYWORDS):
            ctype = "university"
        elif any(k in name_lower for k in TEAM_KEYWORDS):
            ctype = "team"
        # Normalize role
        if role not in VALID_CONTRIB_ROLES:
            role = "publisher"
        cleaned_contribs.append({"name": name, "type": ctype, "role": role})
    data["contributors"] = cleaned_contribs
    # Remove legacy institutions field
    data.pop("institutions", None)
    data.pop("author_count", None)

    # --- confidence ---
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

    # --- doi ---
    doi = data.get("doi")
    if doi is not None and doi != "" and not re.match(r"^10\.\d{4,}/", str(doi)):
        warnings.append(f"doi={doi!r} format suspect, set to null")
        data["doi"] = None

    # --- arxiv_id ---
    arxiv = data.get("arxiv_id")
    if arxiv is not None and arxiv != "" and not re.match(r"^\d{4}\.\d{4,5}", str(arxiv)):
        warnings.append(f"arxiv_id={arxiv!r} format suspect, set to null")
        data["arxiv_id"] = None

    # --- url ---
    url = data.get("url")
    if url is not None and url != "":
        if not url.startswith(("http://", "https://")):
            warnings.append(f"url={url!r} not a URL, set to null")
            data["url"] = None
        else:
            url_lower = url.lower()
            URL_BLOCKLIST = (
                "open-governmentlicence", "creativecommons", "license",
                "softwareheritage", "orcid.org", "github.com", "gitlab.com",
                "supplementary", "supplement",
            )
            for pat in URL_BLOCKLIST:
                if pat in url_lower:
                    warnings.append(f"url contains '{pat}', blocked, set to null")
                    data["url"] = None
                    break

    # --- title ---
    title = data.get("title")
    if title is not None and not isinstance(title, str):
        title = str(title) if title else None
    data["title"] = title

    # --- abstract ---
    abstract = data.get("abstract")
    if abstract is not None and not isinstance(abstract, str):
        abstract = None
    data["abstract"] = abstract

    # --- missing ---
    _absent = lambda v: v is None or v == "" or v == []
    data["missing"] = sorted([
        k for k in ("title", "title_zh", "publication_date", "authors", "contributors",
                     "doi", "arxiv_id", "venue", "url", "abstract")
        if _absent(data.get(k))
    ])

    return data, warnings


# ---------------------------------------------------------------------------
# Apply high-confidence fields to works
# ---------------------------------------------------------------------------

HIGH_CONFIDENCE_FIELDS = {
    "title": "title",
    # year intentionally excluded: arXiv headers contain submission dates
    # that model extracts as date.year — auto-applying corrupts works.year.
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

        # Also apply medium/high-confidence authors (as list of name strings)
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

        # Apply contributors (JSON)
        if confidence.get("contributors") in ("high", "medium") and extracted.get("contributors"):
            existing_contrib = current["contributors"] if "contributors" in current.keys() else None
            if not existing_contrib or overwrite:
                sets.append("contributors = ?")
                params.append(json.dumps(extracted["contributors"], ensure_ascii=False))

        # Apply publication_date_json
        if confidence.get("publication_date") in ("high", "medium") and extracted.get("publication_date"):
            existing_pdj = current["publication_date_json"] if "publication_date_json" in current.keys() else None
            if not existing_pdj or overwrite:
                sets.append("publication_date_json = ?")
                params.append(json.dumps(extracted["publication_date"], ensure_ascii=False))

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

            # Call opencode→MiMo（经 llm_judge；原 ollama:11435 已弃用）
            try:
                resp = llm_judge.chat(messages, model=args.model, timeout=args.timeout)
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
            try:
                extracted, validation_warnings = validate_extraction(extracted)
            except Exception as e:
                print(f"  ERROR: validation failed: {e}")
                results.append({
                    "work_id": work_id,
                    "status": "validation_error",
                    "error": str(e),
                    "raw_response": raw_response[:500],
                })
                continue

            confidence = extracted.get("confidence", {})
            missing = extracted.get("missing", [])
            authors = extracted.get("authors", [])
            contribs = extracted.get("contributors", [])
            pub_date = extracted.get("publication_date") or {}
            title_text = extracted.get("title") or "N/A"
            print(f"  标题：{title_text[:60]}")
            print(f"  日期：{pub_date.get('year', 'N/A')} (kind={pub_date.get('kind', '?')})")
            print(f"  作者({len(authors)}): {authors}")
            print(f"  贡献方：{[c.get('name','?') for c in contribs]}")
            print(f"  置信度：{json.dumps(confidence, ensure_ascii=False)}")
            if missing:
                print(f"  缺失：{', '.join(missing)}")
            if validation_warnings:
                for w in validation_warnings:
                    print(f"  校验：{w}")

            # Save to DB
            if not args.no_write:
                ext_id = f"ME-{uuid.uuid4().hex[:12]}"
                now = datetime.now(timezone.utc).isoformat(timespec="seconds")

                # Compute risk
                risk = compute_risk(extracted, confidence, validation_warnings, w.get("title"))
                risk_reasons_json = json.dumps(risk["risk_reasons"], ensure_ascii=False)

                conn.execute("""
                    INSERT INTO metadata_extractions
                    (id, work_id, model_name, content_md_path, input_chars, input_tokens_est,
                     raw_response, extracted_json, confidence_json, applied,
                     risk_level, risk_score, risk_reasons, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                """, (
                    ext_id, work_id, args.model, str(content_path),
                    len(text), input_tokens,
                    raw_response, json.dumps(extracted, ensure_ascii=False),
                    json.dumps(confidence, ensure_ascii=False),
                    risk["risk_level"], risk["risk_score"], risk_reasons_json, now,
                ))
                conn.commit()
                print(f"  已保存：{ext_id} (risk={risk['risk_level']}, score={risk['risk_score']})")

            results.append({
                "work_id": work_id,
                "status": "ok",
                "title": extracted.get("title"),
                "year": extracted.get("year"),
                "publication_date": extracted.get("publication_date"),
                "authors": extracted.get("authors"),
                "all_authors": extracted.get("all_authors"),
                "contributors": extracted.get("contributors"),
                "doi": extracted.get("doi"),
                "arxiv_id": extracted.get("arxiv_id"),
                "venue": extracted.get("venue"),
                "url": extracted.get("url"),
                "abstract": extracted.get("abstract"),
                "title_zh": extracted.get("title_zh"),
                "evidence": extracted.get("evidence"),
                "confidence": confidence,
                "missing": missing,
                "validation_warnings": validation_warnings,
                "content_md_path": str(content_path),
                "input_chars": len(text),
                "input_tokens_est": input_tokens,
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
        err = sum(1 for r in results if r.get("status") in ("error", "parse_error", "validation_error"))
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
