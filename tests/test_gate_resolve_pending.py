# tests/test_gate_resolve_pending.py
import sqlite3
from collector import gate


def _conn(db):
    """Match api.db.get_conn semantics: Row factory so r['id'] works."""
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    return c


def _db(tmp_path, rows):
    db = tmp_path / "literature.sqlite"
    c = sqlite3.connect(db)
    c.execute("""CREATE TABLE intake_candidates (
        id TEXT PRIMARY KEY, resolution TEXT, local_pdf_path TEXT, fetched_sha256 TEXT)""")
    c.execute("""CREATE TABLE source_files (id TEXT PRIMARY KEY, content_sha256 TEXT)""")
    for r in rows:
        c.execute("INSERT INTO intake_candidates (id, resolution, local_pdf_path) VALUES (?,?,?)",
                  (r["id"], r["resolution"], r.get("local_pdf_path")))
    c.commit(); c.close()
    return db


def test_resolve_pending_only_new_and_better_copy(tmp_path, monkeypatch):
    db = _db(tmp_path, [
        {"id": "IC-1", "resolution": "new"},
        {"id": "IC-2", "resolution": "exact_hit"},
        {"id": "IC-3", "resolution": "needs_better_copy"},
    ])
    calls = []
    monkeypatch.setattr(gate, "get_conn", lambda: _conn(db))
    monkeypatch.setattr(gate, "heavy_gate", lambda cid: (calls.append(cid), "fetch_failed")[1])
    results = gate.resolve_pending()
    assert {cid for cid, _ in results} == {"IC-1", "IC-3"}   # exact_hit 不处理


def test_resolve_pending_explicit_ids(tmp_path, monkeypatch):
    db = _db(tmp_path, [{"id": "IC-1", "resolution": "new"}, {"id": "IC-2", "resolution": "new"}])
    monkeypatch.setattr(gate, "get_conn", lambda: _conn(db))
    monkeypatch.setattr(gate, "heavy_gate", lambda cid: "new")
    results = gate.resolve_pending(ids=["IC-1"])
    assert [cid for cid, _ in results] == ["IC-1"]
