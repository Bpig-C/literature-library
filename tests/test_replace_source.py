# tests/test_replace_source.py
import sqlite3
from pathlib import Path
from collector import replace_source as rs

def test_replace_restores_quarantined_work(tmp_path, monkeypatch):
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    lib = tmp_path
    (lib / "works" / "W-1" / "source").mkdir(parents=True)
    good_pdf = tmp_path / "good.pdf"; good_pdf.write_bytes(b"%PDF-1.4 good")
    c = sqlite3.connect(db_path)
    c.execute("CREATE TABLE works (id TEXT PRIMARY KEY, read_status TEXT)")
    c.execute("INSERT INTO works VALUES ('W-1','quarantined')")
    c.execute("""CREATE TABLE work_codes (work_id TEXT, source_file_id TEXT, code TEXT, reason TEXT, created_at TEXT,
                 PRIMARY KEY(work_id, source_file_id, code))""")
    c.execute("INSERT INTO work_codes VALUES ('W-1','','bad_source','x','t')")
    c.execute("""CREATE TABLE source_files (id TEXT PRIMARY KEY, work_id TEXT, content_sha256 TEXT,
                 source_path TEXT, relative_source_path TEXT, status TEXT)""")
    c.execute("INSERT INTO source_files VALUES ('SF-old','W-1','oldsha','p','r','active')")
    c.commit(); c.close()
    monkeypatch.setattr(rs, "get_conn", lambda: sqlite3.connect(db_path))

    rs.replace_quarantined_source("W-1", good_pdf, library_root=lib)
    conn = sqlite3.connect(db_path)
    status = conn.execute("SELECT read_status FROM works WHERE id='W-1'").fetchone()[0]
    bad = conn.execute("SELECT count(*) FROM work_codes WHERE work_id='W-1' AND code='bad_source'").fetchone()[0]
    conn.close()
    assert status == "unread"           # 恢复
    assert bad == 0                      # bad_source 清除
