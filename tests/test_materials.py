"""Materials endpoint: closure listing, integrity binding and path safety."""
import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.research import router, _release_manifest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    docs = tmp_path / "materials"
    (docs / "docs").mkdir(parents=True)
    (docs / "docs" / "manual.md").write_text("manual body", encoding="utf-8")
    (docs / "AGENTS.md").write_text("agents", encoding="utf-8")
    secret = tmp_path / "outside.md"
    secret.write_text("outside", encoding="utf-8")

    def digest(p):
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()

    manifest = {
        "release_id": "rl-test",
        "essentials": {
            "library/docs/AGENTS.md": {"sha256": digest(docs / "AGENTS.md"), "bytes": 6,
                                       "key": "objects/sha256/aa/aaa"},
            "library/docs/docs/manual.md": {"sha256": digest(docs / "docs" / "manual.md"),
                                            "bytes": len((docs / "docs" / "manual.md").read_bytes()),
                                            "key": "objects/sha256/bb/bbb"},
        },
        "code": {"files": {"contracts/research-workflow-v1.json": digest(
            Path(__file__).resolve().parents[1] / "contracts" / "research-workflow-v1.json")}},
    }
    (tmp_path / "release-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setenv("LITLIB_RUNTIME_MATERIALS_ROOT", str(docs))
    monkeypatch.setattr("api.routes.research._release_manifest",
                        lambda: {"data": manifest, "sha256": "m" * 64})
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_materials_list_covers_docs_closure_and_contract(client):
    body = client.get("/api/materials").json()
    assert body["available"] is True
    paths = {item["path"] for item in body["items"]}
    assert paths == {"library/docs/AGENTS.md", "library/docs/docs/manual.md",
                     "contracts/research-workflow-v1.json"}
    for item in body["items"]:
        assert len(item["sha256"]) == 64 and item["bytes"] > 0 and item["url"].startswith("/api/materials/")


def test_materials_file_serves_with_integrity_headers(client):
    r = client.get("/api/materials/library/docs/docs/manual.md")
    assert r.status_code == 200 and r.text == "manual body"
    assert r.headers["x-litlib-sha256"] == hashlib.sha256(b"manual body").hexdigest()
    assert r.headers["x-litlib-bytes"] == "11"


def test_materials_refuses_traversal_and_unlisted_paths(client):
    for path in (
        "/api/materials/library/docs/../../release-manifest.json",
        "/api/materials/library/docs/%2e%2e%2foutside.md",
        "/api/materials/library/docs/absent.md",
        "/api/materials/contracts/other.json",
    ):
        assert client.get(path).status_code == 404, path


def test_materials_detects_tampering(client, tmp_path, monkeypatch):
    victim = tmp_path / "materials" / "AGENTS.md"
    victim.write_text("tampered", encoding="utf-8")
    assert client.get("/api/materials/library/docs/AGENTS.md").status_code == 502


def test_materials_unavailable_without_manifest(client, monkeypatch):
    monkeypatch.setattr("api.routes.research._release_manifest", lambda: None)
    assert client.get("/api/materials").json()["available"] is False
    assert client.get("/api/materials/library/docs/AGENTS.md").status_code == 503
