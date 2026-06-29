"""Tests for P2-F1: classification scalar fields must be validated against vocab.

The multi-value tag paths (reading_lane/method_tags/...) already validate via
``validate_tag_value``. The scalar fields written straight into ``works`` via
``CLASSIFICATION_FIELDS`` (primary_doc_type, publication_status, ingestion_state,
priority, ...) must be validated too, otherwise a free-text scalar value bypasses
the controlled vocabulary and lands in ``works`` directly.

Uses the shared ``sample_db`` fixture; never touches the real library.
"""
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

_NOW = "2026-01-01T00:00:00+00:00"


def _insert_extraction(db_path, ext_id, work_id, extracted):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(
        "INSERT INTO classification_extractions "
        "(id, work_id, model_name, extracted_json, confidence_json, "
        "ambiguity_score, review_status, applied, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ext_id, work_id, "test-model",
         json.dumps(extracted), json.dumps({}),
         5, "pending", 0, _NOW, _NOW),
    )
    conn.commit()
    conn.close()


class TestScalarFieldVocabBypass:
    """review_extraction must reject scalar field values not in vocab."""

    def test_invalid_primary_doc_type_rejected(self, sample_db):
        """Free-text primary_doc_type not in vocab → 400, not persisted to works."""
        _insert_extraction(
            sample_db, "CE-scalar-bad-doctype", "W-sample-002",
            {"primary_doc_type": "__FREE_DOC_TYPE_SHOULD_NOT_PERSIST__"},
        )
        resp = client.patch(
            "/api/classification/extractions/CE-scalar-bad-doctype/review",
            json={"review_status": "approved"},
        )
        assert resp.status_code == 400, resp.text
        detail = resp.json().get("detail", "")
        assert "Invalid" in detail or "vocab" in detail.lower(), detail

        conn = sqlite3.connect(str(sample_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT primary_doc_type FROM works WHERE id = 'W-sample-002'"
        ).fetchone()
        conn.close()
        assert row["primary_doc_type"] != "__FREE_DOC_TYPE_SHOULD_NOT_PERSIST__"

    def test_invalid_publication_status_rejected(self, sample_db):
        """Free-text publication_status not in vocab → 400."""
        _insert_extraction(
            sample_db, "CE-scalar-bad-pub", "W-sample-002",
            {"primary_doc_type": "research_article",
             "publication_status": "__BAD_PUB_STATUS__"},
        )
        resp = client.patch(
            "/api/classification/extractions/CE-scalar-bad-pub/review",
            json={"review_status": "approved"},
        )
        assert resp.status_code == 400, resp.text

        conn = sqlite3.connect(str(sample_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT publication_status FROM works WHERE id = 'W-sample-002'"
        ).fetchone()
        conn.close()
        assert row["publication_status"] != "__BAD_PUB_STATUS__"

    def test_valid_scalar_accepted_and_persisted(self, sample_db):
        """Valid vocab scalar → 200 and written to works (fill-empty)."""
        _insert_extraction(
            sample_db, "CE-scalar-ok", "W-sample-002",
            {"primary_doc_type": "research_article"},
        )
        resp = client.patch(
            "/api/classification/extractions/CE-scalar-ok/review",
            json={"review_status": "approved"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json().get("ok")

        conn = sqlite3.connect(str(sample_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT primary_doc_type FROM works WHERE id = 'W-sample-002'"
        ).fetchone()
        conn.close()
        assert row["primary_doc_type"] == "research_article"
