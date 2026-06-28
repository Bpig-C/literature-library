# tests/test_gate.py
import sqlite3
from collector import gate

def _db_with_works(tmp_path, works):
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    c = sqlite3.connect(db_path)
    c.execute("""CREATE TABLE works (id TEXT PRIMARY KEY, arxiv_id TEXT, doi TEXT,
                 title TEXT, read_status TEXT DEFAULT 'unread')""")
    for w in works:
        c.execute("INSERT INTO works VALUES (?,?,?,?,?)",
                  (w["id"], w.get("arxiv_id"), w.get("doi"), w.get("title"), w.get("read_status","unread")))
    c.commit(); c.close()
    return db_path

def test_arxiv_exact_hit_active(tmp_path, monkeypatch):
    db = _db_with_works(tmp_path, [{"id":"W-arxiv-2406.10162","arxiv_id":"2406.10162","title":"X"}])
    monkeypatch.setattr(gate, "get_conn", lambda: sqlite3.connect(db))
    res, wid = gate.light_gate({"arxiv_id":"2406.10162"})
    assert res == "exact_hit" and wid == "W-arxiv-2406.10162"

def test_arxiv_hit_quarantined_is_needs_better_copy(tmp_path, monkeypatch):
    db = _db_with_works(tmp_path, [{"id":"W-1","arxiv_id":"2406.10162","title":"X","read_status":"quarantined"}])
    monkeypatch.setattr(gate, "get_conn", lambda: sqlite3.connect(db))
    res, wid = gate.light_gate({"arxiv_id":"2406.10162"})
    assert res == "needs_better_copy" and wid == "W-1"

def test_title_candidate_when_similar(tmp_path, monkeypatch):
    db = _db_with_works(tmp_path, [{"id":"W-2","title":"Reward Hacking in Large Language Models"}])
    monkeypatch.setattr(gate, "get_conn", lambda: sqlite3.connect(db))
    res, _ = gate.light_gate({"title":"Reward Hacking in Large Language Models"})
    assert res == "title_candidate"

def test_new_when_no_match(tmp_path, monkeypatch):
    db = _db_with_works(tmp_path, [])
    monkeypatch.setattr(gate, "get_conn", lambda: sqlite3.connect(db))
    res, wid = gate.light_gate({"arxiv_id":"2501.99999","title":"Brand New Topic"})
    assert res == "new" and wid is None
