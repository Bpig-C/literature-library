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


# --- heavy_gate download-branch tests ---
import api.db
from pathlib import Path

def _db_for_download(tmp_path, *, source_type="arxiv", arxiv_id="2212.08073", source_shas=()):
    db = tmp_path / "literature.sqlite"; sqlite3.connect(db).close()
    c = sqlite3.connect(db)
    c.execute("""CREATE TABLE source_files (id TEXT PRIMARY KEY, content_sha256 TEXT)""")
    c.execute("""CREATE TABLE intake_candidates (id TEXT PRIMARY KEY, source_type TEXT, arxiv_id TEXT,
        local_pdf_path TEXT, fetched_sha256 TEXT, resolution TEXT, resolved_at TEXT)""")
    c.execute("INSERT INTO intake_candidates (id, source_type, arxiv_id, resolution) VALUES ('IC-1', ?, ?, 'new')",
              (source_type, arxiv_id))
    for i, sha in enumerate(source_shas):
        c.execute("INSERT INTO source_files VALUES (?,?)", (f"SF-{i}", sha))
    c.commit(); c.close()
    return db

def _fetch_row(db, cid="IC-1"):
    c = sqlite3.connect(db); c.row_factory = sqlite3.Row
    row = c.execute("SELECT * FROM intake_candidates WHERE id=?", (cid,)).fetchone()
    c.close(); return row

def test_heavy_gate_downloads_arxiv_then_new(tmp_path, monkeypatch):
    db = _db_for_download(tmp_path)
    monkeypatch.setattr(api.db, "LIBRARY_ROOT", tmp_path)
    monkeypatch.setattr(api.db, "DB_PATH", db)
    monkeypatch.setattr(gate, "get_conn", lambda: _row_conn(db))
    def fake_download(url, dest):
        Path(dest).write_bytes(b"%PDF-1.4 fake-downloaded")
        return dest
    monkeypatch.setattr(gate, "download_pdf", fake_download)
    res = gate.heavy_gate("IC-1")
    assert res == "new"
    row = _fetch_row(db)
    assert row["local_pdf_path"] == "_collector_cache/IC-1.pdf"
    assert row["fetched_sha256"] and len(row["fetched_sha256"]) == 64
    assert row["resolved_at"]

def test_heavy_gate_download_matches_source_file_sha256_duplicate(tmp_path, monkeypatch):
    # 用与 fake_download 相同的内容算 sha，预置进 source_files
    content = b"%PDF-1.4 fake-downloaded"
    expected_sha = hashlib.sha256(content).hexdigest()
    db = _db_for_download(tmp_path, source_shas=[expected_sha])
    monkeypatch.setattr(api.db, "LIBRARY_ROOT", tmp_path)
    monkeypatch.setattr(api.db, "DB_PATH", db)
    monkeypatch.setattr(gate, "get_conn", lambda: _row_conn(db))
    def fake_download(url, dest):
        Path(dest).write_bytes(content)
        return dest
    monkeypatch.setattr(gate, "download_pdf", fake_download)
    res = gate.heavy_gate("IC-1")
    assert res == "sha256_duplicate"

def test_heavy_gate_download_fails_persists_fetch_failed(tmp_path, monkeypatch):
    db = _db_for_download(tmp_path)
    monkeypatch.setattr(api.db, "LIBRARY_ROOT", tmp_path)
    monkeypatch.setattr(api.db, "DB_PATH", db)
    monkeypatch.setattr(gate, "get_conn", lambda: _row_conn(db))
    monkeypatch.setattr(gate, "download_pdf", lambda url, dest: None)  # 下载失败
    res = gate.heavy_gate("IC-1")
    assert res == "fetch_failed"
    row = _fetch_row(db)
    assert row["resolution"] == "fetch_failed"
    assert row["resolved_at"]                  # 落库，不再谎报
    assert not row["local_pdf_path"]           # 下载失败，local_pdf_path 仍 NULL

def test_heavy_gate_github_no_arxiv_id_fetch_failed(tmp_path, monkeypatch):
    db = _db_for_download(tmp_path, source_type="github", arxiv_id=None)
    monkeypatch.setattr(api.db, "LIBRARY_ROOT", tmp_path)
    monkeypatch.setattr(api.db, "DB_PATH", db)
    monkeypatch.setattr(gate, "get_conn", lambda: _row_conn(db))
    called = []
    monkeypatch.setattr(gate, "download_pdf", lambda url, dest: called.append(url))
    res = gate.heavy_gate("IC-1")
    assert res == "fetch_failed"
    assert called == []                         # github v1 无 PDF 直链，根本不尝试下载
    row = _fetch_row(db)
    assert row["resolution"] == "fetch_failed"
    assert row["resolved_at"]

def test_heavy_gate_existing_pdf_does_not_redownload(tmp_path, monkeypatch):
    # 候选已有绝对路径 local_pdf_path（既有测试风格），不应触发 download_pdf
    sha = _make_pdf(tmp_path / "a.pdf")
    db = _db_for_download(tmp_path, source_shas=[sha])
    # 把候选的 local_pdf_path 改成既有绝对路径
    c = sqlite3.connect(db)
    c.execute("UPDATE intake_candidates SET local_pdf_path=? WHERE id='IC-1'", (str(tmp_path / "a.pdf"),))
    c.commit(); c.close()
    monkeypatch.setattr(api.db, "LIBRARY_ROOT", tmp_path)
    monkeypatch.setattr(api.db, "DB_PATH", db)
    monkeypatch.setattr(gate, "get_conn", lambda: _row_conn(db))
    called = []
    monkeypatch.setattr(gate, "download_pdf", lambda url, dest: called.append(url))
    res = gate.heavy_gate("IC-1")
    assert res == "sha256_duplicate"
    assert called == []                         # 未重复下载
