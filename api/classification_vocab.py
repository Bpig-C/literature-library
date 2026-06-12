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
        "framework", "taxonomy", "evaluation_framework", "benchmark", "dataset",
        "evaluation_suite", "metric", "model", "system_card", "model_card",
        "safety_report", "transparency_report", "safety_case_argument",
        "risk_update", "interpretability_finding", "audit_finding",
        "standard", "guideline", "governance", "policy", "risk_management",
        "audit", "red_teaming", "safety_case", "transparency",
        "monitorability", "interpretability", "leaderboard", "platform",
        "trend", "literature_index", "workflow_cache",
    ],
    "risk_domain": [
        "deception", "scheming", "sandbagging", "evaluation_awareness",
        "information_concealment", "persuasion", "misinformation",
        "autonomy", "self_replication", "resource_acquisition",
        "goal_preservation", "covert_action", "oversight_subversion",
        "autonomous_ai_rnd", "multi_agent_collusion", "sabotage",
        "cybersecurity", "biosecurity", "chemical_security", "dual_use",
        "catastrophic_risk", "misuse", "governance_risk", "model_behavior",
        "privacy", "fairness", "robustness", "safety_case_validity", "unknown",
    ],
    "method_tags": [
        "benchmark_construction", "dataset_curation", "evaluation_protocol",
        "evaluation_execution", "pre_deployment_evaluation",
        "multi_model_comparison", "capability_evaluation", "risk_assessment",
        "red_teaming", "auditing", "external_audit",
        "sandbagging_detection", "elicitation", "evaluation_awareness_testing",
        "reward_hacking_detection", "cross_modality_consistency",
        "agentic_behavior_audit", "multi_agent_sandbox",
        "white_box_probing", "safety_case_construction", "safety_case",
        "model_card_analysis", "policy_mapping", "taxonomy_building",
        "standard_comparison", "empirical_experiment", "case_study",
        "expert_elicitation", "leaderboard_comparison",
        "text_extraction", "document_repair", "summary_synthesis",
    ],
    "ingestion_state": ["verified", "needs_review", "provisional", "excluded", "deprecated"],
    "priority": ["P0", "P1", "P2", "P3", "archive"],
    "canonical_file_format": ["pdf_native", "pdf_printed", "html", "markdown", "png", "txt", "mixed", "unknown"],
    "processing_flags": [
        "needs_pdf_conversion", "html_retained", "screenshot_only",
        "homepage_snapshot_problem", "not_original_document",
        "text_extraction_failed", "text_extraction_fixed",
        "duplicate_candidate", "duplicate_confirmed",
        "cache_only", "repair_workspace",
        "source_url_uncertain", "source_url_dead",
        "manually_verified", "needs_relocation", "deprecated_version",
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
