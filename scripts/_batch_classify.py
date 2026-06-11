"""Batch insert Mimo classification extractions for batch 1 (works 1-5)."""
import sqlite3, json, uuid, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.classification_ambiguity import compute_ambiguity

DB = Path(__file__).resolve().parents[1] / "literature.sqlite"
conn = sqlite3.connect(str(DB))
conn.row_factory = sqlite3.Row
now = datetime.now(timezone.utc).isoformat(timespec="seconds")

extractions = [
    {
        "work_id": "W-arxiv-2501.17805",
        "extracted_json": {
            "primary_doc_type": "institutional_report",
            "publication_status": "published",
            "primary_source_actor_type": "international_network",
            "region": "international",
            "reading_lane": ["framework_taxonomy", "institutional_landscape"],
            "artifact_focus": ["risk_assessment", "policy_analysis"],
            "risk_domain": [],
            "method_tags": ["survey_synthesis"],
            "ingestion_state": "needs_review",
            "priority": "P1",
            "alternative_primary_doc_types": ["survey_review"],
            "evidence": {
                "primary_doc_type": "International scientific report contributed by 30 countries, UN, EU, OECD",
                "publication_status": "Published January 2025",
                "reading_lane": "Comprehensive safety risk assessment across frontier AI domains",
                "artifact_focus": "Multi-country risk assessment and policy recommendations"
            },
            "confidence": {"primary_doc_type": "high", "publication_status": "high", "primary_source_actor_type": "high", "reading_lane": "medium", "artifact_focus": "high"},
            "ambiguity_notes": "Clear institutional report from international coalition"
        },
        "confidence_json": {"primary_doc_type": "high", "publication_status": "high", "primary_source_actor_type": "high"}
    },
    {
        "work_id": "W-arxiv-2503.04746",
        "extracted_json": {
            "primary_doc_type": "technical_report",
            "publication_status": "published",
            "primary_source_actor_type": "government_agency",
            "region": "UK",
            "reading_lane": ["governance_method", "safety_case_method"],
            "artifact_focus": ["framework_proposal", "policy_analysis"],
            "risk_domain": [],
            "method_tags": ["survey_synthesis", "framework_design"],
            "ingestion_state": "needs_review",
            "priority": "P1",
            "alternative_primary_doc_types": ["governance_framework"],
            "evidence": {
                "primary_doc_type": "UK AI Safety Institute technical report on emerging practices",
                "publication_status": "Published as part of Frontier AI Safety Commitments",
                "reading_lane": "Safety framework practices for risk identification, mitigation, governance",
                "artifact_focus": "56 emerging practices for safety frameworks"
            },
            "confidence": {"primary_doc_type": "high", "publication_status": "high", "primary_source_actor_type": "high", "reading_lane": "high", "artifact_focus": "high"},
            "ambiguity_notes": "Could be governance_framework but is primarily a technical synthesis report"
        },
        "confidence_json": {"primary_doc_type": "high", "publication_status": "high", "primary_source_actor_type": "high"}
    },
    {
        "work_id": "W-arxiv-2507.06261",
        "extracted_json": {
            "primary_doc_type": "system_model_card",
            "publication_status": "published",
            "primary_source_actor_type": "frontier_ai_company",
            "region": "US",
            "reading_lane": ["model_technical_profile"],
            "artifact_focus": ["capability_profile", "empirical_finding"],
            "risk_domain": [],
            "method_tags": ["benchmark_construction", "empirical_measurement"],
            "ingestion_state": "needs_review",
            "priority": "P2",
            "alternative_primary_doc_types": ["research_article", "technical_report"],
            "evidence": {
                "primary_doc_type": "Google Gemini 2.5 model card describing architecture, training, and evaluations",
                "publication_status": "Published July 2025",
                "reading_lane": "Technical profile of Gemini 2.X model family",
                "artifact_focus": "Benchmark results and capability demonstrations"
            },
            "confidence": {"primary_doc_type": "high", "publication_status": "high", "primary_source_actor_type": "high", "reading_lane": "high", "artifact_focus": "medium"},
            "ambiguity_notes": "Model card with extensive benchmarking, could also be research_article"
        },
        "confidence_json": {"primary_doc_type": "high", "publication_status": "high", "primary_source_actor_type": "high"}
    },
    {
        "work_id": "W-arxiv-2507.16534",
        "extracted_json": {
            "primary_doc_type": "evaluation_report",
            "publication_status": "published",
            "primary_source_actor_type": "academic_group",
            "region": "CN",
            "reading_lane": ["evaluation_method", "safety_case_method"],
            "artifact_focus": ["risk_assessment", "benchmark", "empirical_finding"],
            "risk_domain": ["cyber_offense", "bio_risk", "persuasion", "deception", "scheming", "autonomous_replication", "distributional_risk"],
            "method_tags": ["benchmark_construction", "evaluation_execution", "case_study"],
            "ingestion_state": "needs_review",
            "priority": "P0",
            "alternative_primary_doc_types": ["technical_report", "benchmark_dataset_paper"],
            "evidence": {
                "primary_doc_type": "Comprehensive evaluation of 18 frontier AI models across 7 risk areas",
                "publication_status": "Published July 2025",
                "reading_lane": "E-T-C risk analysis framework with red/yellow/green line methodology",
                "artifact_focus": "Risk evaluation benchmarks and empirical findings across 7 risk domains"
            },
            "confidence": {"primary_doc_type": "medium", "publication_status": "high", "primary_source_actor_type": "medium", "reading_lane": "high", "artifact_focus": "high"},
            "ambiguity_notes": "Could be evaluation_report or benchmark_dataset_paper"
        },
        "confidence_json": {"primary_doc_type": "medium", "publication_status": "high", "primary_source_actor_type": "medium"}
    },
    {
        "work_id": "W-arxiv-2512.01166",
        "extracted_json": {
            "primary_doc_type": "evaluation_report",
            "publication_status": "published",
            "primary_source_actor_type": "civil_society_org",
            "region": "international",
            "reading_lane": ["governance_method", "evaluation_method"],
            "artifact_focus": ["policy_analysis", "audit_finding"],
            "risk_domain": [],
            "method_tags": ["policy_review", "survey_synthesis"],
            "ingestion_state": "needs_review",
            "priority": "P1",
            "alternative_primary_doc_types": ["research_article", "survey_review"],
            "evidence": {
                "primary_doc_type": "Systematic assessment of 12 AI safety frameworks using 65 weighted criteria",
                "publication_status": "Published December 2025, updated April 2026",
                "reading_lane": "Evaluation of frontier AI safety frameworks against risk management standards",
                "artifact_focus": "Policy analysis with scoring across 4 dimensions"
            },
            "confidence": {"primary_doc_type": "high", "publication_status": "high", "primary_source_actor_type": "high", "reading_lane": "high", "artifact_focus": "high"},
            "ambiguity_notes": "Clear evaluation report from civil society organization"
        },
        "confidence_json": {"primary_doc_type": "high", "publication_status": "high", "primary_source_actor_type": "high"}
    }
]

for ext in extractions:
    extracted = ext["extracted_json"]
    confidence = ext.get("confidence_json", {})
    amb = compute_ambiguity(extracted, confidence)
    ext_id = f"CE-{uuid.uuid4().hex[:12]}"
    conn.execute(
        """INSERT INTO classification_extractions
        (id, work_id, model_name, prompt_version, extracted_json, confidence_json,
         ambiguity_score, ambiguity_reasons, review_status, applied,
         raw_response, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)""",
        (ext_id, ext["work_id"], "mimo2.5pro", "v1",
         json.dumps(extracted, ensure_ascii=False),
         json.dumps(confidence, ensure_ascii=False),
         amb["score"],
         json.dumps(amb["reasons"], ensure_ascii=False),
         "mimo_extraction", now, now)
    )
    print(f'{ext["work_id"]}: {extracted["primary_doc_type"]} (amb={amb["score"]})')

conn.commit()
conn.close()
print("Batch 1 done: 5 works")
