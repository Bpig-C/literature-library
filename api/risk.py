"""Risk scoring for metadata extractions.

Computes a risk_level (low/medium/high), risk_score (0-100), and risk_reasons
for each metadata extraction to prioritize human review.

Scoring rules:
- 0-20: low (safe to batch approve)
- 21-60: medium (sample review)
- 61-100: high (must review individually)
"""

from __future__ import annotations

import json
import re
from typing import Any

# URL patterns that indicate low-risk sources
SAFE_URL_PATTERNS = (
    "arxiv.org", "doi.org", "dx.doi.org",
    "ieee.org", "acm.org", "springer.com", "elsevier.com",
    "wiley.com", "nature.com", "science.org",
    "aaai.org", "neurips.cc", "icml.cc", "openreview.net",
)

# URL patterns that indicate high-risk sources
BAD_URL_PATTERNS = (
    "open-governmentlicence", "creativecommons", "license",
    "softwareheritage", "github.com", "gitlab.com",
    "supplementary", "news", "blog", "medium.com",
)

# Core fields whose absence is high risk
CORE_FIELDS = {"title", "date", "authors", "abstract"}

# Fields whose absence is low risk
LOW_RISK_MISSING = {"doi", "venue", "title_zh", "arxiv_id"}


def compute_risk(extracted: dict, confidence: dict, validation_warnings: list,
                 current_title: str | None = None) -> dict:
    """Compute risk level, score, and reasons for an extraction.

    Returns {"risk_level": str, "risk_score": int, "risk_reasons": list[str]}.
    """
    score = 0
    reasons = []

    # --- Validation warnings (each adds 15 points) ---
    if validation_warnings:
        for w in validation_warnings:
            score += 15
            reasons.append(f"validation: {w}")

    # --- Missing core fields ---
    missing = extracted.get("missing", [])
    for f in missing:
        if f in CORE_FIELDS:
            score += 20
            reasons.append(f"missing core field: {f}")
        elif f not in LOW_RISK_MISSING:
            score += 10
            reasons.append(f"missing field: {f}")

    # --- Confidence checks ---
    for field in ("title", "date", "authors", "abstract"):
        conf = confidence.get(field)
        if conf == "low":
            score += 15
            reasons.append(f"low confidence: {field}")
        elif conf == "medium" and field in ("title", "date"):
            score += 5
            reasons.append(f"medium confidence: {field}")

    # --- Date checks ---
    date_obj = extracted.get("date")
    if isinstance(date_obj, dict):
        year = date_obj.get("year")
        raw = (date_obj.get("raw") or "").lower()
        kind = date_obj.get("kind")

        # Year in the future or too old
        if year and (year > 2030 or year < 1990):
            score += 20
            reasons.append(f"suspicious year: {year}")

        # Kind is inferred (not explicitly stated)
        if kind == "inferred":
            score += 5
            reasons.append("date inferred, not explicit")

        # Raw text looks like an arXiv header date (not publication date)
        if "arxiv" in raw or re.match(r"^\d{1,2} \w+ \d{4}$", raw.strip()):
            score += 10
            reasons.append(f"date may be arXiv/submission date: {date_obj.get('raw')}")

    # --- URL checks ---
    url = extracted.get("url")
    if url:
        url_lower = url.lower()
        is_bad = any(p in url_lower for p in BAD_URL_PATTERNS)
        is_safe = any(p in url_lower for p in SAFE_URL_PATTERNS)
        if is_bad:
            score += 25
            reasons.append(f"blocked URL pattern: {url}")
        elif not is_safe:
            score += 10
            reasons.append(f"URL not from known publisher: {url}")

    # --- Title mismatch check ---
    if current_title:
        ext_title = (extracted.get("title") or "").strip().lower()
        cur_title = current_title.strip().lower()
        if ext_title and cur_title:
            # Simple overlap check
            common = len(set(ext_title.split()) & set(cur_title.split()))
            total = max(len(set(ext_title.split())), len(set(cur_title.split())), 1)
            if common / total < 0.3:
                score += 20
                reasons.append(f"title mismatch: extracted='{extracted.get('title', '')[:40]}' vs current='{current_title[:40]}'")

    # --- Institution type unknown ---
    for inst in extracted.get("institutions", []):
        if isinstance(inst, dict) and inst.get("type") == "unknown":
            score += 5
            reasons.append(f"institution type unknown: {inst.get('name', '?')}")
            break  # only count once

    # --- Team/group author (not individual) ---
    authors = extracted.get("authors", [])
    if authors and isinstance(authors[0], dict):
        first = authors[0].get("name", "")
        if any(kw in first.lower() for kw in ("team", "group", "consortium", "collaboration")):
            score += 5
            reasons.append(f"group author: {first}")

    # Clamp and classify
    score = max(0, min(100, score))
    if score <= 20:
        level = "low"
    elif score <= 60:
        level = "medium"
    else:
        level = "high"

    return {"risk_level": level, "risk_score": score, "risk_reasons": reasons}
