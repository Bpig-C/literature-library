# tests/test_collection_topics.py
import sqlite3

def _run_migration(conn_path):
    import api.db as db
    db.LIBRARY_ROOT = conn_path.parent
    db.DB_PATH = conn_path
    import scripts.migrate_add_collection_topics as m
    m.run(conn_path)
    m.run(conn_path)  # 幂等：再跑不报错

def test_migration_creates_collection_topics(tmp_path, monkeypatch):
    db_path = tmp_path / "literature.sqlite"
    sqlite3.connect(db_path).close()
    _run_migration(db_path)
    conn = sqlite3.connect(db_path)
    rows = conn.execute("PRAGMA table_info(collection_topics)").fetchall()
    cols = {r[1] for r in rows}
    assert {"id","name","description","query_def","map_status","lifecycle",
            "mapped_tags","proposed_note","axis_hint","created_at","updated_at"} <= cols
    conn.close()

def test_migration_adds_topic_fk_column(tmp_path):
    db_path = tmp_path / "literature.sqlite"
    c = sqlite3.connect(db_path)
    # 地基已建 intake_candidates 的前提：测试里手动建一个最小占位表
    c.execute("CREATE TABLE intake_candidates (id TEXT PRIMARY KEY)")
    c.close()
    _run_migration(db_path)
    conn = sqlite3.connect(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(intake_candidates)").fetchall()}
    assert "collection_topic_id" in cols
    conn.close()
