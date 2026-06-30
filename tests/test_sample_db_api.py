"""API tests using the sample_db fixture — no real DB snapshot required."""

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


class TestWorksFromSample:
    def test_list_works(self):
        resp = client.get("/api/works")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3

    def test_get_work_detail(self):
        resp = client.get("/api/works/W-sample-001")
        assert resp.status_code == 200
        assert resp.json()["id"] == "W-sample-001"

    def test_work_not_found(self):
        resp = client.get("/api/works/W-nonexistent")
        assert resp.status_code == 404


class TestMetadataFromSample:
    def test_list_metadata(self):
        resp = client.get("/api/metadata?status=all")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2

    def test_get_metadata_detail(self):
        resp = client.get("/api/metadata/ME-sample-pending")
        assert resp.status_code == 200
        assert resp.json()["id"] == "ME-sample-pending"

    def test_review_metadata(self):
        resp = client.patch("/api/metadata/ME-sample-pending/review", json={
            "review_status": "approved",
            "review_note": "sample test",
        })
        assert resp.status_code == 200
        assert resp.json().get("ok")

        # Verify
        resp = client.get("/api/metadata/ME-sample-pending")
        assert resp.json()["review_status"] == "approved"

    def test_metadata_not_found(self):
        resp = client.get("/api/metadata/ME-nonexistent")
        assert resp.status_code == 404


class TestExtractionTriggersFromSample:
    def _seed_parsed_work(self, sample_db, tmp_path, work_id):
        content_path = tmp_path / f"{work_id}.md"
        content_path.write_text(
            "# Sample Extraction Paper\n\nThis paper describes a benchmark evaluation method.",
            encoding="utf-8",
        )
        conn = _make_conn_factory(sample_db)()
        conn.execute("DELETE FROM classification_extractions WHERE work_id = ?", (work_id,))
        conn.execute("DELETE FROM metadata_extractions WHERE work_id = ?", (work_id,))
        conn.execute("DELETE FROM literature_parse_runs WHERE work_id = ?", (work_id,))
        conn.execute("DELETE FROM source_files WHERE work_id = ?", (work_id,))
        conn.execute("DELETE FROM works WHERE id = ?", (work_id,))
        conn.execute(
            """
            INSERT INTO works
            (id, title, authors, year, doc_type, language, metadata_status,
             parse_status, read_status, created_at, updated_at)
            VALUES (?, 'Sample Extraction Paper', '[]', 2026, 'paper', 'en',
                    'pending', 'succeeded', 'unread', datetime('now'), datetime('now'))
            """,
            (work_id,),
        )
        conn.execute(
            """
            INSERT INTO source_files
            (id, work_id, original_name, source_path, relative_source_path,
             file_size, file_ext, import_time, status)
            VALUES (?, ?, 'sample.pdf', ?, ?, 1000, '.pdf', datetime('now'), 'active')
            """,
            (f"SF-{work_id}", work_id, str(content_path), f"works/{work_id}/source/sample.pdf"),
        )
        conn.execute(
            """
            INSERT INTO literature_parse_runs
            (id, work_id, source_file_id, status, content_md_path, started_at, finished_at)
            VALUES (?, ?, ?, 'succeeded', ?, datetime('now'), datetime('now'))
            """,
            (f"PR-{work_id}", work_id, f"SF-{work_id}", str(content_path)),
        )
        conn.commit()
        conn.close()
        return content_path

    def test_metadata_extract_creates_pending_candidate(self, sample_db, tmp_path, monkeypatch):
        from scripts import literature_metadata_extract as meta_script

        work_id = "W-sample-trigger-meta"
        self._seed_parsed_work(sample_db, tmp_path, work_id)
        monkeypatch.setattr(meta_script, "DB_PATH", sample_db)
        monkeypatch.setattr(
            meta_script.llm_judge,
            "chat",
            lambda messages, timeout=120: {
                "message": {
                    "content": json.dumps({
                        "title": "Sample Extraction Paper",
                        "title_zh": "样例抽取论文",
                        "publication_date": {"year": 2026, "month": None, "day": None, "raw": "2026", "kind": "exact"},
                        "authors": ["Ada Example"],
                        "contributors": [{"name": "Example Lab", "type": "lab", "role": "publisher"}],
                        "doi": None,
                        "arxiv_id": None,
                        "venue": "Example Venue",
                        "url": "https://example.org/paper",
                        "abstract": "A short abstract.",
                        "evidence": {"title": "Sample Extraction Paper"},
                        "confidence": {"title": "high", "publication_date": "high", "authors": "medium"},
                        "missing": [],
                    }, ensure_ascii=False)
                }
            },
        )

        resp = client.post("/api/metadata/extract", json={"work_ids": [work_id], "force": True})
        assert resp.status_code == 200
        assert resp.json()["created"] == 1

        conn = _make_conn_factory(sample_db)()
        row = conn.execute(
            "SELECT review_status, extracted_json FROM metadata_extractions WHERE work_id = ? ORDER BY created_at DESC LIMIT 1",
            (work_id,),
        ).fetchone()
        conn.close()
        assert row["review_status"] == "pending"
        assert json.loads(row["extracted_json"])["title"] == "Sample Extraction Paper"

    def test_classification_extract_creates_pending_candidate(self, sample_db, tmp_path, monkeypatch):
        from scripts import literature_classification_extract as cls_script

        work_id = "W-sample-trigger-class"
        self._seed_parsed_work(sample_db, tmp_path, work_id)
        monkeypatch.setattr(cls_script, "DB_PATH", sample_db)
        monkeypatch.setattr(
            cls_script.llm_judge,
            "chat",
            lambda messages, timeout=120: {
                "message": {
                    "content": json.dumps({
                        "primary_doc_type": "research_article",
                        "secondary_doc_type": None,
                        "publication_status": "published",
                        "primary_source_actor_type": "university",
                        "region": "global",
                        "reading_lane": ["evaluation_method"],
                        "artifact_focus": ["benchmark"],
                        "risk_domain": ["deception"],
                        "method_tags": ["benchmark_construction"],
                        "ingestion_state": "usable",
                        "priority": "P2",
                        "alternative_primary_doc_types": [],
                        "evidence": {
                            "primary_doc_type": "paper",
                            "reading_lane": "evaluation method",
                            "artifact_focus": "benchmark",
                        },
                        "confidence": {
                            "primary_doc_type": "high",
                            "publication_status": "high",
                            "reading_lane": "high",
                            "artifact_focus": "high",
                        },
                    }, ensure_ascii=False)
                }
            },
        )

        resp = client.post("/api/classification/extract", json={"work_ids": [work_id], "force": True})
        assert resp.status_code == 200
        assert resp.json()["created"] == 1

        conn = _make_conn_factory(sample_db)()
        row = conn.execute(
            "SELECT review_status, ambiguity_score, ambiguity_reasons, extracted_json "
            "FROM classification_extractions WHERE work_id = ? ORDER BY created_at DESC LIMIT 1",
            (work_id,),
        ).fetchone()
        conn.close()
        assert row["review_status"] == "pending"
        assert isinstance(row["ambiguity_score"], int)
        assert isinstance(json.loads(row["ambiguity_reasons"]), list)
        assert json.loads(row["extracted_json"])["primary_doc_type"] == "research_article"


class TestDuplicatesFromSample:
    def test_list_duplicates(self):
        resp = client.get("/api/duplicates")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_groups"] >= 1

    def test_merge_preview(self):
        resp = client.get("/api/duplicates/DG-sample-001/merge-preview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["group_id"] == "DG-sample-001"
        assert len(data["candidates"]) >= 1
        assert data["recommended_primary"]

    def test_merge_preview_not_found(self):
        resp = client.get("/api/duplicates/DG-nonexistent/merge-preview")
        assert resp.status_code == 404


class TestRelationsFromSample:
    def test_list_relations(self):
        resp = client.get("/api/relations")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["relations"]) >= 1
