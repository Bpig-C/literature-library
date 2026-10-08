"""Classification ambiguity scoring module.

Computes a 0-100 ambiguity score for classification extractions.
Higher score = more ambiguous = needs more human review.

Rules:
- primary_doc_type with high confidence + evidence = low ambiguity
- primary_doc_type with medium/low confidence = medium ambiguity
- No primary_doc_type at all = high ambiguity
- Multiple alternative_primary_doc_types = higher ambiguity
- risk_domain/method_tags being empty does NOT increase ambiguity
"""

from __future__ import annotations

import json


def compute_ambiguity(extracted: dict, confidence: dict) -> dict:
    """Compute ambiguity score and reasons for a classification extraction.

    Args:
        extracted: The extracted classification JSON (parsed).
        confidence: The confidence dict from the extraction.

    Returns:
        dict with keys: score (0-100), reasons (list[str])
    """
    score = 0
    reasons = []

    # --- primary_doc_type ---
    pdt = extracted.get("primary_doc_type")
    pdt_conf = confidence.get("primary_doc_type", "low")
    alternatives = extracted.get("alternative_primary_doc_types") or []

    if pdt is None:
        score += 60
        reasons.append("primary_doc_type is null — cannot determine document identity")
    elif pdt_conf == "low":
        score += 30
        reasons.append(f"primary_doc_type={pdt} but confidence is low")
    elif pdt_conf == "medium":
        score += 15
        reasons.append(f"primary_doc_type={pdt} but confidence is medium")

    if len(alternatives) >= 2:
        score += 15
        reasons.append(f"{len(alternatives)} alternative primary_doc_types proposed")
    elif len(alternatives) == 1:
        score += 5
        reasons.append(f"1 alternative primary_doc_type proposed: {alternatives[0]}")

    # --- publication_status ---
    ps = extracted.get("publication_status")
    ps_conf = confidence.get("publication_status", "low")
    if ps is None:
        score += 5
        reasons.append("publication_status is null")
    elif ps_conf == "low":
        score += 5
        reasons.append(f"publication_status={ps} but confidence is low")

    # --- reading_lane ---
    rl = extracted.get("reading_lane") or []
    rl_conf = confidence.get("reading_lane", "low")
    if not rl:
        score += 5
        reasons.append("reading_lane is empty")
    elif rl_conf == "low":
        score += 3
        reasons.append("reading_lane confidence is low")

    # --- artifact_focus ---
    af = extracted.get("artifact_focus") or []
    af_conf = confidence.get("artifact_focus", "low")
    if not af:
        score += 5
        reasons.append("artifact_focus is empty")
    elif af_conf == "low":
        score += 3
        reasons.append("artifact_focus confidence is low")

    # --- evidence completeness ---
    evidence = extracted.get("evidence") or {}
    if not evidence.get("primary_doc_type"):
        score += 10
        reasons.append("no evidence provided for primary_doc_type")

    # Cap at 100
    score = min(100, max(0, score))

    return {"score": score, "reasons": reasons}
