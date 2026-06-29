"""API tests using the sample_db fixture — no real DB snapshot required."""

from __future__ import annotations

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
