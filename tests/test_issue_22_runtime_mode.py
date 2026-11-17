"""Regression tests for #22: lightweight runtime-mode endpoint.

/api/mode must expose the same deployment flags as /overview (read_only,
remote_writes_enabled) without touching the collection database, so the app
shell can confirm the runtime mode even while the aggregated statistics are
slow or the stores are unavailable.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import overview


def make_client():
    app = FastAPI()
    app.include_router(overview.router, prefix="/api")
    return TestClient(app)


def test_mode_defaults_to_writable(monkeypatch):
    monkeypatch.delenv("LITLIB_RESEARCH_READ_ONLY", raising=False)
    monkeypatch.delenv("LITLIB_REMOTE_WRITE_ENABLED", raising=False)
    response = make_client().get("/api/mode")
    assert response.status_code == 200
    assert response.json() == {"read_only": False, "remote_writes_enabled": False}


def test_mode_reflects_readonly_deployment_flags(monkeypatch):
    monkeypatch.setenv("LITLIB_RESEARCH_READ_ONLY", "1")
    monkeypatch.setenv("LITLIB_REMOTE_WRITE_ENABLED", "1")
    assert make_client().get("/api/mode").json() == {
        "read_only": True,
        "remote_writes_enabled": True,
    }


def test_mode_has_no_business_payload():
    # The mode probe must stay lightweight: no collection counts, no batches.
    body = make_client().get("/api/mode").json()
    assert set(body) == {"read_only", "remote_writes_enabled"}
