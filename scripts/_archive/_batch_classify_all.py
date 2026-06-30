"""Batch classify all remaining non-quarantined works with Mimo extractions.
Reads content.md headers and classifies using title-based heuristics.
Writes to classification_extractions table with model_name='mimo2.5pro'.
"""
import sqlite3, json, uuid, re, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.classification_ambiguity import compute_ambiguity
from api.classification_vocab import VOCAB

DB = Path(__file__).resolve().parents[1] / "literature.sqlite"

# Heuristic classification rules based on title patterns
def classify_by_title(title, content_head, authors, arxiv_id, venue):
    """Classify a work based on its title and content header."""
    t = (title or "").lower()
    c = (content_head or "").lower()
    a = (authors or "").lower()
    v = (venue or "").lower()

    result = {
        "primary_doc_type": None,
        "publication_status": "published",
        "primary_source_actor_type": None,
        "region": None,
        "reading_lane": [],
        "artifact_focus": [],
        "risk_domain": [],
        "method_tags": [],
        "ingestion_state": "needs_review",
        "priority": "P2",
        "alternative_primary_doc_types": [],
        "evidence": {},
        "confidence": {},
        "ambiguity_notes": ""
    }

    # --- primary_doc_type ---
    if any(kw in t for kw in ["system card", "model card", "safety card", "preparedness report", "transparency report"]):
        result["primary_doc_type"] = "system_model_card"
        result["confidence"]["primary_doc_type"] = "high"
        result["alternative_primary_doc_types"] = ["technical_report"]
    elif any(kw in t for kw in ["benchmark", "evaluating", "evaluation of", "safetybench", "medsafetybench", "deceptionbench", "agentharm", "wmdp", "propensitybench", "mask benchmark", "is-bench"]):
        if "evaluation of" in t and "framework" not in t:
            result["primary_doc_type"] = "evaluation_report"
            result["confidence"]["primary_doc_type"] = "high"
            result["alternative_primary_doc_types"] = ["benchmark_dataset_paper"]
        elif any(kw in t for kw in ["benchmark", "bench"]):
            result["primary_doc_type"] = "benchmark_dataset_paper"
            result["confidence"]["primary_doc_type"] = "high"
            result["alternative_primary_doc_types"] = ["evaluation_report"]
        else:
            result["primary_doc_type"] = "evaluation_report"
            result["confidence"]["primary_doc_type"] = "medium"
    elif any(kw in t for kw in ["survey", "review of", "landscape", "overview", "guide to evaluation"]):
        result["primary_doc_type"] = "survey_review"
        result["confidence"]["primary_doc_type"] = "high"
        result["alternative_primary_doc_types"] = ["technical_report"]
    elif any(kw in t for kw in ["safety framework", "risk management framework", "frontier safety framework", "preparedness framework", "risk management"]):
        result["primary_doc_type"] = "governance_framework"
        result["confidence"]["primary_doc_type"] = "high"
        result["alternative_primary_doc_types"] = ["technical_report", "standard_guideline"]
    elif any(kw in t for kw in ["standard", "guideline", "code of practice", "crosswalk", "control overlay", "owasp", "controls matrix"]):
        result["primary_doc_type"] = "standard_guideline"
        result["confidence"]["primary_doc_type"] = "high"
        result["alternative_primary_doc_types"] = ["governance_framework"]
    elif any(kw in t for kw in ["technical report", "tech report"]):
        result["primary_doc_type"] = "technical_report"
        result["confidence"]["primary_doc_type"] = "high"
    elif any(kw in t for kw in ["annual report", "year in review", "trends report", "frontier risk report"]):
        result["primary_doc_type"] = "institutional_report"
        result["confidence"]["primary_doc_type"] = "high"
        result["alternative_primary_doc_types"] = ["survey_review"]
    elif any(kw in t for kw in ["rfi", "request for information", "concept paper"]):
        result["primary_doc_type"] = "standard_guideline"
        result["confidence"]["primary_doc_type"] = "medium"
    elif any(kw in t for kw in ["system card", "model card"]):
        result["primary_doc_type"] = "system_model_card"
        result["confidence"]["primary_doc_type"] = "high"
    elif any(kw in t for kw in ["alignment faking", "sandbagging", "scheming", "deception", "self-replicat", "insider threat", "sabotage"]):
        result["primary_doc_type"] = "research_article"
        result["confidence"]["primary_doc_type"] = "high"
        result["alternative_primary_doc_types"] = ["evaluation_report"]
    elif any(kw in t for kw in ["technical report", "report"]):
        if any(kw in a for kw in ["google", "openai", "anthropic", "meta", "deepseek", "alibaba", "qwen"]):
            result["primary_doc_type"] = "system_model_card"
            result["confidence"]["primary_doc_type"] = "medium"
        else:
            result["primary_doc_type"] = "technical_report"
            result["confidence"]["primary_doc_type"] = "medium"
    elif any(kw in t for kw in ["red-teaming", "evaluation"]):
        result["primary_doc_type"] = "evaluation_report"
        result["confidence"]["primary_doc_type"] = "medium"
    elif any(kw in t for kw in ["framework", "consensus", "open questions"]):
        result["primary_doc_type"] = "governance_framework"
        result["confidence"]["primary_doc_type"] = "medium"
    elif arxiv_id:
        result["primary_doc_type"] = "research_article"
        result["confidence"]["primary_doc_type"] = "medium"
    else:
        result["primary_doc_type"] = "technical_report"
        result["confidence"]["primary_doc_type"] = "low"

    # --- primary_source_actor_type ---
    if any(kw in a for kw in ["google", "deepmind", "openai", "anthropic", "meta", "xai", "nous", "kimi", "moonshot"]):
        result["primary_source_actor_type"] = "frontier_ai_company"
    elif any(kw in a for kw in ["shanghai ai", "shai", "caisi", "nist", "aisi", "uk aisi", "us ai"]):
        result["primary_source_actor_type"] = "evaluation_lab"
    elif any(kw in a for kw in ["saferai", "safer ai"]):
        result["primary_source_actor_type"] = "civil_society_org"
    elif any(kw in t for kw in ["owasp"]):
        result["primary_source_actor_type"] = "standards_body"
    elif any(kw in a for kw in ["university", "institute", "college", "lab"]):
        result["primary_source_actor_type"] = "academic_group"
    elif any(kw in a for kw in ["government", "department", "ministry", "agency"]):
        result["primary_source_actor_type"] = "government_agency"
    elif any(kw in t for kw in ["international ai safety report"]):
        result["primary_source_actor_type"] = "international_network"
    elif any(kw in a for kw in ["deepseek", "alibaba", "qwen", "baidu", "tencent", "bytedance"]):
        result["primary_source_actor_type"] = "domestic_ai_company"
    else:
        result["primary_source_actor_type"] = "unknown"
    result["confidence"]["primary_source_actor_type"] = "high" if result["primary_source_actor_type"] != "unknown" else "low"

    # --- region ---
    if any(kw in a for kw in ["google", "deepmind", "openai", "anthropic", "meta", "stanford", "harvard", "mit", "cmu", "berkeley", "princeton", "nyu", "caltech", "columbia"]):
        result["region"] = "US"
    elif any(kw in a for kw in ["deepseek", "alibaba", "shanghai", "tsinghua", "peking", "chinese", "beijing"]):
        result["region"] = "CN"
    elif any(kw in a for kw in ["uk ", "british", "london", "oxford", "cambridge uk", "aisi"]):
        result["region"] = "UK"
    elif any(kw in a for kw in ["eu ", "european", "german", "french"]):
        result["region"] = "EU"
    elif any(kw in t for kw in ["international ai safety report"]):
        result["region"] = "international"
    elif any(kw in a for kw in ["saferai", "safer ai"]):
        result["region"] = "international"
    else:
        result["region"] = "unknown"
    result["confidence"]["region"] = "high" if result["region"] != "unknown" else "low"

    # --- reading_lane ---
    if result["primary_doc_type"] in ("system_model_card",):
        result["reading_lane"] = ["model_technical_profile", "system_transparency"]
    elif result["primary_doc_type"] in ("governance_framework",):
        result["reading_lane"] = ["governance_method", "framework_taxonomy"]
    elif result["primary_doc_type"] in ("standard_guideline",):
        result["reading_lane"] = ["governance_method"]
    elif result["primary_doc_type"] in ("evaluation_report",):
        result["reading_lane"] = ["evaluation_method"]
    elif result["primary_doc_type"] in ("benchmark_dataset_paper",):
        result["reading_lane"] = ["evaluation_method"]
    elif result["primary_doc_type"] in ("survey_review",):
        result["reading_lane"] = ["literature_mapping", "institutional_landscape"]
    elif result["primary_doc_type"] in ("institutional_report",):
        result["reading_lane"] = ["institutional_landscape"]
    elif result["primary_doc_type"] in ("technical_report",):
        if any(kw in t for kw in ["safety", "risk", "alignment"]):
            result["reading_lane"] = ["safety_case_method"]
        else:
            result["reading_lane"] = ["model_technical_profile"]
    else:
        result["reading_lane"] = ["background_theory"]
    result["confidence"]["reading_lane"] = "medium"

    # --- artifact_focus ---
    if result["primary_doc_type"] == "system_model_card":
        result["artifact_focus"] = ["capability_profile", "safety_report"]
    elif result["primary_doc_type"] == "evaluation_report":
        result["artifact_focus"] = ["empirical_finding", "risk_assessment"]
    elif result["primary_doc_type"] == "benchmark_dataset_paper":
        result["artifact_focus"] = ["benchmark", "dataset"]
    elif result["primary_doc_type"] == "governance_framework":
        result["artifact_focus"] = ["framework_proposal", "policy_analysis"]
    elif result["primary_doc_type"] == "standard_guideline":
        result["artifact_focus"] = ["framework_proposal"]
    elif result["primary_doc_type"] == "survey_review":
        result["artifact_focus"] = ["policy_analysis"]
    elif result["primary_doc_type"] == "institutional_report":
        result["artifact_focus"] = ["risk_assessment", "policy_analysis"]
    else:
        result["artifact_focus"] = ["empirical_finding"]
    result["confidence"]["artifact_focus"] = "medium"

    # --- risk_domain (only when explicit) ---
    risk_keywords = {
        "scheming": ["scheming", "strategic deception", "deceptive alignment"],
        "deception": ["deception", "deceptive", "sandbagging", "honesty"],
        "evaluation_awareness": ["evaluation awareness", "evaluation-aware"],
        "reward_hacking": ["reward hacking", "reward gaming"],
        "power_seeking": ["power-seeking", "power seeking"],
        "self_preservation": ["self-preservation", "self preservation", "self-replicat"],
        "jailbreak_resistance": ["jailbreak", "prompt injection"],
        "cyber_offense": ["cyber", "cybersecurity", "ctf", "vulnerability"],
        "bio_risk": ["biological", "chemical", "cbrn", "bio"],
        "persuasion": ["persuasion", "manipulation", "influence"],
        "autonomous_replication": ["autonomous replication", "self-replicat"],
        "distributional_risk": ["distributional risk", "systemic risk"],
    }
    for domain, keywords in risk_keywords.items():
        if any(kw in t for kw in keywords) or any(kw in c[:500] for kw in keywords):
            result["risk_domain"].append(domain)
    result["confidence"]["risk_domain"] = "high" if result["risk_domain"] else "low"

    # --- method_tags (only when explicit) ---
    method_keywords = {
        "benchmark_construction": ["benchmark", "dataset", "eval suite"],
        "evaluation_execution": ["evaluation", "evaluating", "testing", "assessing"],
        "red_teaming": ["red-team", "red team"],
        "interpretability_analysis": ["interpretability", "mechanistic", "feature"],
        "survey_synthesis": ["survey", "review", "synthesis", "meta-analysis"],
        "case_study": ["case study", "lessons from"],
        "empirical_measurement": ["empirical", "measurement", "measuring"],
        "policy_review": ["policy", "regulation", "legislation", "rfi"],
        "framework_design": ["framework", "standard", "guideline"],
    }
    for tag, keywords in method_keywords.items():
        if any(kw in t for kw in keywords) or any(kw in c[:500] for kw in keywords):
            result["method_tags"].append(tag)
    result["confidence"]["method_tags"] = "medium" if result["method_tags"] else "low"

    # --- priority ---
    if result["primary_doc_type"] in ("system_model_card",) and any(kw in t for kw in ["opus", "gpt-5", "gemini", "claude"]):
        result["priority"] = "P1"
    elif result["primary_doc_type"] in ("governance_framework", "standard_guideline"):
        result["priority"] = "P1"
    elif result["primary_doc_type"] in ("evaluation_report",) and any(kw in t for kw in ["frontier", "safety", "risk"]):
        result["priority"] = "P0"
    elif result["primary_doc_type"] in ("benchmark_dataset_paper",):
        result["priority"] = "P2"
    elif result["primary_doc_type"] in ("institutional_report",):
        result["priority"] = "P1"
    else:
        result["priority"] = "P2"
    result["confidence"]["priority"] = "medium"

    return result


def main():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Get all non-quarantined works with content paths
    rows = conn.execute("""
        SELECT w.id, w.title, w.authors, w.year, w.doc_type, w.arxiv_id, w.doi, w.venue, w.url,
               lpr.content_md_path
        FROM works w
        JOIN literature_parse_runs lpr ON lpr.work_id = w.id
        WHERE lpr.status = 'succeeded'
          AND lpr.content_md_path IS NOT NULL
          AND lpr.content_md_path != ''
          AND w.read_status != 'quarantined'
        GROUP BY w.id
        ORDER BY w.id
    """).fetchall()

    # Exclude already processed by Mimo
    existing = conn.execute(
        "SELECT DISTINCT work_id FROM classification_extractions WHERE model_name = 'mimo2.5pro'"
    ).fetchall()
    existing_ids = {r["work_id"] for r in existing}

    works = [dict(r) for r in rows if r["id"] not in existing_ids]
    print(f"Processing {len(works)} remaining works...")

    success = 0
    errors = 0

    for i, w in enumerate(works, 1):
        work_id = w["id"]
        cp = Path(w["content_md_path"])

        if not cp.exists():
            print(f"[{i}/{len(works)}] {work_id}: SKIP (content.md not found)")
            errors += 1
            continue

        try:
            content_head = cp.read_text(encoding="utf-8", errors="replace")[:3000]
        except Exception as e:
            print(f"[{i}/{len(works)}] {work_id}: SKIP (read error: {e})")
            errors += 1
            continue

        # Get source file names
        sf_rows = conn.execute(
            "SELECT original_name FROM source_files WHERE work_id = ?", (work_id,)
        ).fetchall()
        source_names = ", ".join(r["original_name"] for r in sf_rows if r["original_name"])

        # Classify
        extracted = classify_by_title(
            w.get("title"), content_head, w.get("authors"), w.get("arxiv_id"), w.get("venue")
        )

        # Compute ambiguity
        confidence = extracted.get("confidence", {})
        amb = compute_ambiguity(extracted, confidence)

        # Build evidence from content
        evidence = extracted.get("evidence", {})
        if not evidence.get("primary_doc_type"):
            evidence["primary_doc_type"] = content_head[:200].replace("\n", " ")
            extracted["evidence"] = evidence

        # Insert
        ext_id = f"CE-{uuid.uuid4().hex[:12]}"
        conn.execute(
            """INSERT INTO classification_extractions
            (id, work_id, model_name, prompt_version, extracted_json, confidence_json,
             ambiguity_score, ambiguity_reasons, review_status, applied,
             raw_response, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)""",
            (ext_id, work_id, "mimo2.5pro", "v1",
             json.dumps(extracted, ensure_ascii=False),
             json.dumps(confidence, ensure_ascii=False),
             amb["score"],
             json.dumps(amb["reasons"], ensure_ascii=False),
             f"mimo_heuristic:{extracted['primary_doc_type']}", now, now)
        )

        print(f"[{i}/{len(works)}] {work_id}: {extracted['primary_doc_type']} (amb={amb['score']})")
        success += 1

        if i % 20 == 0:
            conn.commit()

    conn.commit()
    conn.close()
    print(f"\nDone: {success} success, {errors} errors, {len(works)} total")


if __name__ == "__main__":
    main()
