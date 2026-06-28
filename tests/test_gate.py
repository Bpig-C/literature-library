# tests/test_gate.py
import sqlite3
from collector import gate

def _row_conn(db):
    """Mock get_conn: matches production's sqlite3.Row row_factory so column-name access works."""
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    return c

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
    monkeypatch.setattr(gate, "get_conn", lambda: _row_conn(db))
    res, wid = gate.light_gate({"arxiv_id":"2406.10162"})
    assert res == "exact_hit" and wid == "W-arxiv-2406.10162"

def test_arxiv_hit_quarantined_is_needs_better_copy(tmp_path, monkeypatch):
    db = _db_with_works(tmp_path, [{"id":"W-1","arxiv_id":"2406.10162","title":"X","read_status":"quarantined"}])
    monkeypatch.setattr(gate, "get_conn", lambda: _row_conn(db))
    res, wid = gate.light_gate({"arxiv_id":"2406.10162"})
    assert res == "needs_better_copy" and wid == "W-1"

def test_title_candidate_when_similar(tmp_path, monkeypatch):
    db = _db_with_works(tmp_path, [{"id":"W-2","title":"Reward Hacking in Large Language Models"}])
    monkeypatch.setattr(gate, "get_conn", lambda: _row_conn(db))
    res, _ = gate.light_gate({"title":"Reward Hacking in Large Language Models"})
    assert res == "title_candidate"

def test_new_when_no_match(tmp_path, monkeypatch):
    db = _db_with_works(tmp_path, [])
    monkeypatch.setattr(gate, "get_conn", lambda: _row_conn(db))
    res, wid = gate.light_gate({"arxiv_id":"2501.99999","title":"Brand New Topic"})
    assert res == "new" and wid is None


# --- heavy_gate tests ---
import hashlib

def _make_pdf(path, content=b"%PDF-1.4 fake"):
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()

def _db_with_source(tmp_path, sha):
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    c = sqlite3.connect(db_path)
    c.execute("""CREATE TABLE source_files (id TEXT PRIMARY KEY, work_id TEXT, content_sha256 TEXT)""")
    # 注意：heavy_gate 的 UPDATE 写 fetched_sha256/resolved_at，测试表须含这些列
    c.execute("""CREATE TABLE intake_candidates (id TEXT PRIMARY KEY, local_pdf_path TEXT,
                 fetched_sha256 TEXT, resolution TEXT, resolved_at TEXT)""")
    c.execute("INSERT INTO intake_candidates (id, local_pdf_path, resolution) VALUES ('IC-1', ?, 'new')",
              (str(tmp_path/"a.pdf"),))
    c.execute("INSERT INTO source_files VALUES ('SF-1','W-x',?)", (sha,))
    c.commit(); c.close()
    return db_path

def test_heavy_gate_sha256_duplicate(tmp_path, monkeypatch):
    sha = _make_pdf(tmp_path/"a.pdf")
    db = _db_with_source(tmp_path, sha)
    monkeypatch.setattr(gate, "get_conn", lambda: _row_conn(db))
    res = gate.heavy_gate("IC-1")
    assert res == "sha256_duplicate"

def test_heavy_gate_new_confirmed(tmp_path, monkeypatch):
    _make_pdf(tmp_path/"a.pdf")
    db = _db_with_source(tmp_path, sha="0"*64)  # 不同 sha
    monkeypatch.setattr(gate, "get_conn", lambda: _row_conn(db))
    res = gate.heavy_gate("IC-1")
    assert res == "new"
