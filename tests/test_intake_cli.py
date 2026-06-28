# tests/test_intake_cli.py
import sqlite3
from types import SimpleNamespace
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
    # CLI 现委托 candidate_store nucleus，需同步 patch 其 get_conn（与 cli.get_conn 同一临时库）
    from collector import candidate_store as cs
    monkeypatch.setattr(cs, "get_conn", lambda: _row_conn(db))
    cli.promote_review(approve=["IC-1"])
    conn = sqlite3.connect(db)
    rs = conn.execute("SELECT review_status FROM intake_candidates WHERE id='IC-1'").fetchone()[0]
    conn.close()
    assert rs == "approved"


def test_promote_unknown_id_raises(tmp_path, monkeypatch):
    from collector import candidate_store as cs
    db = _db(tmp_path, [{"id":"IC-1","resolution":"new","review_status":"pending"}])
    monkeypatch.setattr(cli, "get_conn", lambda: _row_conn(db))
    monkeypatch.setattr(cs, "get_conn", lambda: _row_conn(db))
    import pytest
    with pytest.raises(KeyError):
        cli.promote_review(approve=["IC-doesnotexist"])


def test_resolve_default_only_handles_new_and_better_copy(tmp_path, monkeypatch):
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    c = sqlite3.connect(db_path)
    c.execute("""CREATE TABLE intake_candidates (id TEXT PRIMARY KEY, resolution TEXT,
                 status TEXT, review_status TEXT, title TEXT, arxiv_id TEXT, ingested_work_id TEXT)""")
    c.execute("INSERT INTO intake_candidates (id,resolution) VALUES ('IC-1','new')")
    c.execute("INSERT INTO intake_candidates (id,resolution) VALUES ('IC-2','exact_hit')")
    c.execute("INSERT INTO intake_candidates (id,resolution) VALUES ('IC-3','needs_better_copy')")
    c.commit(); c.close()
    # CLI resolve 现委托 gate.resolve_pending（内部用 gate.get_conn + gate.heavy_gate）。
    # 用 Row factory 以匹配 api.db.get_conn 语义。
    from collector import gate
    monkeypatch.setattr(gate, "get_conn", lambda: _row_conn(db_path))
    resolved = []
    def fake_heavy_gate(cid):
        resolved.append(cid); return "new"
    monkeypatch.setattr(gate, "heavy_gate", fake_heavy_gate)
    cli.resolve()
    assert set(resolved) == {"IC-1", "IC-3"}   # exact_hit 不下载


def test_collect_topic_runs_gate_and_persists(tmp_path, monkeypatch):
    import api.db
    import scripts.migrate_add_intake_candidates as mic
    import scripts.migrate_add_collection_topics as mct
    from collector import topics as topics_mod
    from collector import discovery_explicit as de
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    monkeypatch.setattr(api.db, "DB_PATH", db_path)
    monkeypatch.setattr(api.db, "LIBRARY_ROOT", db_path.parent)
    mic.run(db_path); mct.run(db_path)
    # 建最小 works 表（light_gate 读 arxiv_id）
    c = sqlite3.connect(db_path)
    c.execute("CREATE TABLE works (id TEXT PRIMARY KEY, arxiv_id TEXT, doi TEXT, title TEXT, read_status TEXT)")
    c.execute("INSERT INTO works VALUES ('W-1','2210.11314',NULL,'Existing',NULL)")  # 已有 work
    c.commit(); c.close()
    # 建一个带 explicit_ids 的主题
    ct = topics_mod.create(name="T", description="", explicit_ids=["2210.11314", "2501.00009"])
    # mock fetch_metadata（避免打真实 arXiv）
    monkeypatch.setattr(de, "fetch_metadata",
                        lambda aid: {"arxiv_id": aid, "title": "Paper " + aid, "authors": [], "doi": None, "abstract": None})
    # collect
    args = SimpleNamespace(topic=ct["id"], ids=None, github=None, auto_resolve=False)
    cli.collect(args)
    # 2210.11314 命中已有 work → exact_hit；2501.00009 无命中 → new
    conn = sqlite3.connect(db_path)
    rows = {r[0]: r[1] for r in conn.execute("SELECT arxiv_id, resolution FROM intake_candidates")}
    conn.close()
    assert rows["2210.11314"] == "exact_hit"
    assert rows["2501.00009"] == "new"


def test_collect_unknown_topic_errors_cleanly(tmp_path, monkeypatch):
    import api.db
    import scripts.migrate_add_intake_candidates as mic
    import scripts.migrate_add_collection_topics as mct
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    monkeypatch.setattr(api.db, "DB_PATH", db_path)
    monkeypatch.setattr(api.db, "LIBRARY_ROOT", db_path.parent)
    mic.run(db_path); mct.run(db_path)
    from types import SimpleNamespace
    args = SimpleNamespace(topic="CT-doesnotexist", ids=None, github=None, auto_resolve=False)
    import pytest
    with pytest.raises(SystemExit):
        cli.collect(args)
