"""Classification vocabulary module.

Centralizes all valid tag values for the classification ontology v0.2.
Used by extraction scripts for validation and by the API for vocab endpoints.
"""

from __future__ import annotations

VOCAB: dict[str, list[str]] = {
    "primary_doc_type": [
        "research_article", "survey_review", "technical_report",
        "system_model_card", "evaluation_report", "standard_guideline",
        "governance_framework", "benchmark_dataset_paper", "institutional_report",
        "webpage_blog", "platform_snapshot", "thesis", "book_chapter",
        "workflow_artifact", "other_literature", "not_literature",
    ],
    "publication_status": [
        "published", "preprint", "working_paper", "draft",
        "living_document", "institutional_release", "webpage_release", "unknown",
    ],
    "primary_source_actor_type": [
        "frontier_ai_company", "domestic_ai_company", "evaluation_lab",
        "government_agency", "standards_body", "international_network",
        "academic_group", "civil_society_org", "platform_dashboard", "unknown",
    ],
    "region": ["US", "UK", "EU", "CN", "JP", "KR", "SG", "international", "unknown"],
    "reading_lane": [
        "framework_taxonomy", "evaluation_method", "governance_method",
        "system_transparency", "model_technical_profile", "institutional_landscape",
        "safety_case_method", "interpretability_method", "background_theory",
        "literature_mapping", "workflow_support",
    ],
    "artifact_focus": [
        "benchmark", "dataset", "eval_suite", "audit_finding",
        "safety_report", "capability_profile", "risk_assessment",
        "policy_analysis", "framework_proposal", "tool_release",
        "empirical_finding", "theoretical_contribution",
    ],
    "risk_domain": [
        "scheming", "deception", "evaluation_awareness", "reward_hacking",
        "power_seeking", "self_preservation", "jailbreak_resistance",
        "alignment_tax", "cyber_offense", "bio_risk", "persuasion",
        "autonomous_replication", "distributional_risk", "systemic_risk",
    ],
    "method_tags": [
        "benchmark_construction", "evaluation_execution", "red_teaming",
        "interpretability_analysis", "formal_verification", "dataset_curation",
        "survey_synthesis", "case_study", "empirical_measurement",
        "theoretical_analysis", "policy_review", "framework_design",
    ],
    "ingestion_state": ["verified", "needs_review", "provisional", "excluded", "deprecated"],
    "priority": ["P0", "P1", "P2", "P3", "archive"],
    "canonical_file_format": ["pdf_native", "pdf_printed", "html", "markdown", "png", "txt", "mixed", "unknown"],
    "processing_flags": [
        "missing_abstract", "missing_metadata", "ocr_needed",
        "duplicate_suspect", "low_quality_scan", "language_mismatch",
        "file_corrupted", "needs_redownload",
    ],
}

VOCAB_VERSIONS: dict[str, str] = {
    "risk_domain": "v1",
    "method_tags": "v1",
}


def validate_tag_value(tag_group: str, tag_value: str) -> bool:
    return tag_value in VOCAB.get(tag_group, [])


def get_vocab() -> dict:
    return {k: list(v) for k, v in VOCAB.items()}
