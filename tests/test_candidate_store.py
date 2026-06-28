# tests/test_candidate_store.py
import sqlite3
from collector import candidate_store as cs

def _db(tmp_path):
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    c = sqlite3.connect(db_path)
    c.execute("""CREATE TABLE intake_candidates (id TEXT PRIMARY KEY, source_type TEXT,
        url_canonical TEXT, arxiv_id TEXT, doi TEXT, title TEXT, status TEXT, raw_meta TEXT,
        collection_topic_id TEXT, resolution TEXT, review_status TEXT, collected_at TEXT,
        UNIQUE(source_type, url_canonical))""")
    c.commit(); c.close()
    return db_path

def test_insert_new(tmp_path, monkeypatch):
    db = _db(tmp_path); monkeypatch.setattr(cs, "get_conn", lambda: sqlite3.connect(db))
    cid, status = cs.insert_candidate(source_type="arxiv",
        url_canonical="https://arxiv.org/abs/2501.17805", arxiv_id="2501.17805", title="X")
    assert status == "created" and cid.startswith("IC-")

def test_skip_cross_source_same_arxiv(tmp_path, monkeypatch):
    db = _db(tmp_path); monkeypatch.setattr(cs, "get_conn", lambda: sqlite3.connect(db))
    cid1, _ = cs.insert_candidate(source_type="arxiv", url_canonical="u1", arxiv_id="2501.17805")
    cid2, st = cs.insert_candidate(source_type="github", url_canonical="u2", arxiv_id="2501.17805")
    assert st == "skipped_dup" and cid2 == cid1   # 跨源同篇 → 跳过，返回已有

def test_skip_same_doi(tmp_path, monkeypatch):
    db = _db(tmp_path); monkeypatch.setattr(cs, "get_conn", lambda: sqlite3.connect(db))
    cs.insert_candidate(source_type="arxiv", url_canonical="u1", doi="10.1/x")
    _, st = cs.insert_candidate(source_type="github", url_canonical="u2", doi="10.1/x")
    assert st == "skipped_dup"

def test_skip_same_url(tmp_path, monkeypatch):
    db = _db(tmp_path); monkeypatch.setattr(cs, "get_conn", lambda: sqlite3.connect(db))
    cs.insert_candidate(source_type="arxiv", url_canonical="u", title="X")
    _, st = cs.insert_candidate(source_type="arxiv", url_canonical="u", title="X")
    assert st == "skipped_dup"

def test_no_strong_key_different_title_creates(tmp_path, monkeypatch):
    db = _db(tmp_path); monkeypatch.setattr(cs, "get_conn", lambda: sqlite3.connect(db))
    cs.insert_candidate(source_type="arxiv", url_canonical="u1", title="Reward Hacking")
    _, st = cs.insert_candidate(source_type="arxiv", url_canonical="u2", title="Interpretability")
    assert st == "created"   # 无强键、不同标题 → 不误杀

def test_does_not_skip_against_ingested(tmp_path, monkeypatch):
    db = _db(tmp_path); monkeypatch.setattr(cs, "get_conn", lambda: sqlite3.connect(db))
    cs.insert_candidate(source_type="arxiv", url_canonical="u1", arxiv_id="2501.17805")
    c = sqlite3.connect(db)
    c.execute("UPDATE intake_candidates SET status='ingested' WHERE arxiv_id='2501.17805'"); c.commit(); c.close()
    _, st = cs.insert_candidate(source_type="arxiv", url_canonical="u2", arxiv_id="2501.17805")
    assert st == "created"   # 已晋升的不在候选层跳过（交给闸门 vs works）
