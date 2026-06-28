# tests/test_intake_cli.py
import sqlite3
from scripts import literature_intake as cli

def _db(tmp_path, rows):
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    c = sqlite3.connect(db_path)
    c.execute("""CREATE TABLE intake_candidates (id TEXT PRIMARY KEY, resolution TEXT,
                 status TEXT, review_status TEXT, title TEXT, arxiv_id TEXT, ingested_work_id TEXT)""")
    for r in rows:
        c.execute("INSERT INTO intake_candidates VALUES (?,?,?,?,?,?,?)",
                  (r["id"], r.get("resolution"), r.get("status"), r.get("review_status"),
                   r.get("title"), r.get("arxiv_id"), r.get("ingested_work_id")))
    c.commit(); c.close()
    return db_path

def _row_conn(db_path):
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    return c

def test_list_new_pending(tmp_path, monkeypatch, capsys):
    db = _db(tmp_path, [
        {"id":"IC-1","resolution":"new","review_status":"pending","title":"A","arxiv_id":"1"},
        {"id":"IC-2","resolution":"new","review_status":"approved","title":"B","arxiv_id":"2"},
    ])
    monkeypatch.setattr(cli, "get_conn", lambda: _row_conn(db))
    cli.list_cmd(None)
    out = capsys.readouterr().out
    assert "IC-1" in out and "IC-2" not in out  # 只列 pending

def test_promote_marks_approved(tmp_path, monkeypatch):
    db = _db(tmp_path, [{"id":"IC-1","resolution":"new","review_status":"pending"}])
    monkeypatch.setattr(cli, "get_conn", lambda: _row_conn(db))
    cli.promote_review(approve=["IC-1"])
    conn = sqlite3.connect(db)
    rs = conn.execute("SELECT review_status FROM intake_candidates WHERE id='IC-1'").fetchone()[0]
    conn.close()
    assert rs == "approved"
