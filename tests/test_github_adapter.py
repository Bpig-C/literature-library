# tests/test_github_adapter.py
import sqlite3
import api.db
import scripts.migrate_add_intake_candidates as mic
from collector.adapters import github as gh

README_WITH_ARXIV = """
# My Paper Repo
Code for our paper. See https://arxiv.org/abs/2210.11314 for details.
"""

def _db(tmp_path, monkeypatch):
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    monkeypatch.setattr(api.db, "DB_PATH", db_path)
    monkeypatch.setattr(api.db, "LIBRARY_ROOT", db_path.parent)
    mic.run(db_path)   # 真实 intake_candidates 表
    c = sqlite3.connect(db_path)
    # light_gate 读 works 的 id/arxiv_id/doi/title/read_status —— 建最小 works 表
    c.execute("""CREATE TABLE works (id TEXT PRIMARY KEY, arxiv_id TEXT, doi TEXT,
                 title TEXT, read_status TEXT)""")
    c.commit(); c.close()
    return db_path

def test_extract_arxiv_id_from_readme():
    assert gh.extract_arxiv_id(README_WITH_ARXIV) == "2210.11314"

def test_extract_arxiv_id_none():
    assert gh.extract_arxiv_id("# just code") is None

def test_github_pdf_aligns_to_existing_arxiv_work(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    # 预置一个已有 arXiv work
    c = sqlite3.connect(db_path)
    c.execute("INSERT INTO works VALUES ('W-1','2210.11314',NULL,'Existing',NULL)")
    c.commit(); c.close()
    monkeypatch.setattr(gh, "fetch_repo_readme", lambda repo_url: README_WITH_ARXIV)

    cand = gh.collect_repo_paper("https://github.com/org/repo")
    assert cand["arxiv_id"] == "2210.11314"
    assert cand["resolution"] == "exact_hit"   # 跨源对齐：命中已有 arXiv work，靠强键不靠 SHA256
    assert cand["matched_work_id"] == "W-1"
    # resolution 已持久化到候选行
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT resolution, matched_work_id FROM intake_candidates WHERE id=?",
                       (cand["id"],)).fetchone()
    conn.close()
    assert row[0] == "exact_hit" and row[1] == "W-1"

def test_github_no_arxiv_id_is_new(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    monkeypatch.setattr(gh, "fetch_repo_readme", lambda repo_url: "# just code, no paper")
    cand = gh.collect_repo_paper("https://github.com/org/repo")
    assert cand["arxiv_id"] is None
    assert cand["resolution"] == "new"   # 无强键、无标题 → light_gate 判 new
    assert cand["matched_work_id"] is None
