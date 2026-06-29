"""P1-01 regression tests: SQL injection via status query parameter.

Verifies that malicious status values are rejected with HTTP 400 before
reaching the SQL layer. Uses sample_db fixture — no real DB required.
"""

from __future__ import annotations

import sqlite3
import unittest
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


@pytest.fixture(autouse=True, scope="module")
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


class TestMetadataStatusInjection(unittest.TestCase):
    """P1-01: metadata endpoint must reject SQL injection via status."""

    def test_sqli_or_1_equals_1_returns_400(self):
        resp = client.get("/api/metadata?status=%27%20OR%201%3D1%20--")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Invalid status", resp.json().get("detail", ""))

    def test_sqli_union_select_returns_400(self):
        resp = client.get("/api/metadata?status=union%20select%20*%20from%20works")
        self.assertEqual(resp.status_code, 400)

    def test_sqli_drop_table_returns_400(self):
        resp = client.get("/api/metadata?status=drop%20table%20works")
        self.assertEqual(resp.status_code, 400)

    def test_sqli_single_quote_returns_400(self):
        resp = client.get("/api/metadata?status='")
        self.assertEqual(resp.status_code, 400)

    def test_valid_status_all_returns_200(self):
        resp = client.get("/api/metadata?status=all")
        self.assertEqual(resp.status_code, 200)

    def test_valid_status_pending_returns_200(self):
        resp = client.get("/api/metadata?status=pending")
        self.assertEqual(resp.status_code, 200)

    def test_valid_status_approved_returns_200(self):
        resp = client.get("/api/metadata?status=approved")
        self.assertEqual(resp.status_code, 200)

    def test_valid_status_rejected_returns_200(self):
        resp = client.get("/api/metadata?status=rejected")
        self.assertEqual(resp.status_code, 200)

    def test_valid_status_needs_fix_returns_200(self):
        resp = client.get("/api/metadata?status=needs_fix")
        self.assertEqual(resp.status_code, 200)


class TestClassificationStatusInjection(unittest.TestCase):
    """P1-01: classification endpoint must reject SQL injection via status."""

    def test_sqli_or_1_equals_1_returns_400(self):
        resp = client.get("/api/classification/extractions?status=%27%20OR%201%3D1%20--")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Invalid status", resp.json().get("detail", ""))

    def test_sqli_union_select_returns_400(self):
        resp = client.get("/api/classification/extractions?status=union%20select%201")
        self.assertEqual(resp.status_code, 400)

    def test_sqli_semicolon_returns_400(self):
        resp = client.get("/api/classification/extractions?status=;drop%20table%20works")
        self.assertEqual(resp.status_code, 400)

    def test_valid_status_all_returns_200(self):
        resp = client.get("/api/classification/extractions?status=all")
        self.assertEqual(resp.status_code, 200)

    def test_valid_status_pending_returns_200(self):
        resp = client.get("/api/classification/extractions?status=pending")
        self.assertEqual(resp.status_code, 200)

    def test_valid_status_rejected_returns_200(self):
        resp = client.get("/api/classification/extractions?status=rejected")
        self.assertEqual(resp.status_code, 200)

    def test_valid_status_needs_fix_returns_200(self):
        resp = client.get("/api/classification/extractions?status=needs_fix")
        self.assertEqual(resp.status_code, 200)
