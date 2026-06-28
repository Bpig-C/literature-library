# tests/test_candidate_store_review.py
import sqlite3
import pytest
from collector import candidate_store as cs


def _db(tmp_path):
    db = tmp_path / "literature.sqlite"
    c = sqlite3.connect(db)
    c.execute("""CREATE TABLE intake_candidates (
        id TEXT PRIMARY KEY, review_status TEXT, review_note TEXT, status TEXT)""")
    c.execute("INSERT INTO intake_candidates (id, review_status, status) VALUES ('IC-1','pending','resolved')")
    c.commit(); c.close()
    return db


def test_set_review_status_approves_with_note(tmp_path, monkeypatch):
    db = _db(tmp_path)
    def _get_conn():
        cc = sqlite3.connect(db); cc.row_factory = sqlite3.Row; return cc
    monkeypatch.setattr(cs, "get_conn", _get_conn)
    cs.set_review_status("IC-1", "approved", note="ok")
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT review_status, review_note FROM intake_candidates WHERE id='IC-1'").fetchone()
    conn.close()
    assert row[0] == "approved" and row[1] == "ok"


def test_set_review_status_rejects_bad_status(tmp_path, monkeypatch):
    db = _db(tmp_path)
    def _get_conn():
        cc = sqlite3.connect(db); cc.row_factory = sqlite3.Row; return cc
    monkeypatch.setattr(cs, "get_conn", _get_conn)
    with pytest.raises(ValueError):
        cs.set_review_status("IC-1", "bogus")


def test_set_review_status_unknown_id_raises(tmp_path, monkeypatch):
    db = _db(tmp_path)
    def _get_conn():
        cc = sqlite3.connect(db); cc.row_factory = sqlite3.Row; return cc
    monkeypatch.setattr(cs, "get_conn", _get_conn)
    with pytest.raises(KeyError):
        cs.set_review_status("IC-missing", "approved")
