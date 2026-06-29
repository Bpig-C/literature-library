"""Tests for P1-POST-01: classification review paths must validate tags against vocab."""

from __future__ import annotations

import json
import sqlite3
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.main import app


def _make_conn_factory(db_path):
    def _conn():
        c = sqlite3.connect(str(db_path))
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        return c
    return _conn


@pytest.fixture(autouse=True)
def _patch_routes(sample_db):
    factory = _make_conn_factory(sample_db)
    patches = [
        patch("api.routes.works.get_conn", factory),
        patch("api.routes.relations.get_conn", factory),
        patch("api.routes.duplicates.get_conn", factory),
        patch("api.routes.files.get_conn", factory),
        patch("api.routes.metadata.get_conn", factory),
        patch("api.routes.classification.get_conn", factory),
    ]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


client = TestClient(app)


class TestReviewExtractionVocabBypass:
    """review_extraction must reject invalid tag values in edited_fields."""

    def test_invalid_reading_lane_rejected(self, sample_db):
        """Free-text reading_lane value not in vocab → 400, no tag persisted."""
        resp = client.patch(
            "/api/classification/extractions/CE-valid-001/review",
            json={
                "review_status": "approved",
                "edited_fields": {"reading_lane": ["__FREE_TAG_SHOULD_NOT_PERSIST__"]},
            },
        )
        assert resp.status_code == 400
        body = resp.json()
        assert "Invalid tag" in body.get("detail", "") or "vocab" in body.get("detail", "").lower()
        # Verify nothing leaked into DB
        conn = sqlite3.connect(str(sample_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT 1 FROM work_classification_tags WHERE tag_value = ?",
            ("__FREE_TAG_SHOULD_NOT_PERSIST__",),
        ).fetchone()
        conn.close()
        assert row is None

    def test_invalid_method_tag_rejected(self, sample_db):
        """Free-text method_tags value not in vocab → 400."""
        resp = client.patch(
            "/api/classification/extractions/CE-valid-001/review",
            json={
                "review_status": "approved",
                "edited_fields": {"method_tags": ["__BAD_METHOD__"]},
            },
        )
        assert resp.status_code == 400
        conn = sqlite3.connect(str(sample_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT 1 FROM work_classification_tags WHERE tag_value = ?",
            ("__BAD_METHOD__",),
        ).fetchone()
        conn.close()
        assert row is None

    def test_valid_tags_accepted(self, sample_db):
        """Valid vocab tags → 200, tags written to DB."""
        # Use a fresh extraction to avoid state issues
        now = "2026-01-01T00:00:00+00:00"
        conn = sqlite3.connect(str(sample_db))
        conn.row_factory = sqlite3.Row
        conn.execute(
            "INSERT INTO classification_extractions "
            "(id, work_id, model_name, extracted_json, confidence_json, "
            "ambiguity_score, review_status, applied, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("CE-valid-test", "W-sample-002", "test-model",
             json.dumps({
                 "primary_doc_type": "research_article",
                 "reading_lane": ["evaluation_method"],
                 "artifact_focus": ["benchmark"],
                 "risk_domain": ["deception"],
                 "method_tags": ["benchmark_construction"],
                 "evidence": {
                     "primary_doc_type": "abstract",
                     "reading_lane": "test",
                     "artifact_focus": "test",
                     "risk_domain": "test",
                     "method_tags": "test",
                 },
             }),
             json.dumps({"reading_lane": "medium", "artifact_focus": "medium"}),
             5, "pending", 0, now, now),
        )
        conn.commit()
        conn.close()

        resp = client.patch(
            "/api/classification/extractions/CE-valid-test/review",
            json={"review_status": "approved"},
        )
        assert resp.status_code == 200
        assert resp.json().get("ok")

        conn = sqlite3.connect(str(sample_db))
        conn.row_factory = sqlite3.Row
        tags = conn.execute(
            "SELECT * FROM work_classification_tags WHERE work_id = 'W-sample-002'"
        ).fetchall()
        conn.close()
        tag_values = {(t["tag_group"], t["tag_value"]) for t in tags}
        assert ("reading_lane", "evaluation_method") in tag_values


class TestBatchApproveVocabBypass:
    """batch-approve endpoints must reject invalid tag values."""

    def test_batch_approve_low_risk_invalid_tag_rejected(self, sample_db):
        """batch-approve-low-risk must not write invalid tags."""
        # Insert an extraction with invalid tags + low ambiguity
        conn = sqlite3.connect(str(sample_db))
        conn.row_factory = sqlite3.Row
        now = "2026-01-01T00:00:00+00:00"
        conn.execute(
            "INSERT INTO classification_extractions "
            "(id, work_id, model_name, extracted_json, confidence_json, "
            "ambiguity_score, review_status, applied, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("CE-batch-bad", "W-sample-003", "mimo2.5pro-test",
             json.dumps({
                 "primary_doc_type": "research_article",
                 "reading_lane": ["__INVALID_BATCH_TAG__"],
                 "artifact_focus": ["benchmark"],
                 "risk_domain": ["deception"],
                 "method_tags": ["benchmark_construction"],
                 "evidence": {"primary_doc_type": "abstract"},
             }),
             json.dumps({"reading_lane": "medium"}),
             5, "pending", 0, now, now),
        )
        conn.commit()
        conn.close()

        resp = client.post("/api/classification/extractions/batch-approve-low-risk")
        assert resp.status_code == 400
        assert "Invalid tag" in resp.json().get("detail", "") or "vocab" in resp.json().get("detail", "").lower()

        conn = sqlite3.connect(str(sample_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT 1 FROM work_classification_tags WHERE tag_value = ?",
            ("__INVALID_BATCH_TAG__",),
        ).fetchone()
        conn.close()
        assert row is None

    def test_batch_approve_with_tag_invalid_rejected(self, sample_db):
        """batch-approve-with-tag must not write invalid tags."""
        conn = sqlite3.connect(str(sample_db))
        conn.row_factory = sqlite3.Row
        now = "2026-01-01T00:00:00+00:00"
        conn.execute(
            "INSERT INTO classification_extractions "
            "(id, work_id, model_name, extracted_json, confidence_json, "
            "ambiguity_score, review_status, applied, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("CE-batch-tag-bad", "W-sample-003", "mimo2.5pro-test",
             json.dumps({
                 "primary_doc_type": "research_article",
                 "reading_lane": ["evaluation_method"],
                 "artifact_focus": ["__INVALID_ARTIFACT__"],
                 "risk_domain": ["deception"],
                 "method_tags": ["benchmark_construction"],
                 "evidence": {"primary_doc_type": "abstract"},
             }),
             json.dumps({"artifact_focus": "medium"}),
             5, "pending", 0, now, now),
        )
        conn.commit()
        conn.close()

        resp = client.post(
            "/api/classification/extractions/batch-approve-with-tag",
            json={"threshold": 100, "tag": "test-batch"},
        )
        assert resp.status_code == 400
        assert "Invalid tag" in resp.json().get("detail", "") or "vocab" in resp.json().get("detail", "").lower()

        conn = sqlite3.connect(str(sample_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT 1 FROM work_classification_tags WHERE tag_value = ?",
            ("__INVALID_ARTIFACT__",),
        ).fetchone()
        conn.close()
        assert row is None
