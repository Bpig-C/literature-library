# tests/test_intake_migration.py
import sqlite3
from pathlib import Path

def _run(db_path):
    import scripts.migrate_add_intake_candidates as m
    m.run(db_path)
    m.run(db_path)  # 幂等

def test_migration_creates_intake_candidates(tmp_path):
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run(db_path)
    conn = sqlite3.connect(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(intake_candidates)").fetchall()}
    assert {"id","source_type","source_url","title","arxiv_id","doi","url_canonical",
            "fetched_sha256","local_pdf_path","resolution","matched_work_id","status",
            "review_status","review_note","collected_at","resolved_at","ingested_work_id",
            "raw_meta","collection_topic_id"} <= cols
    # 唯一约束：(source_type, url_canonical)
    dup = conn.execute("SELECT sql FROM sqlite_master WHERE name='intake_candidates'").fetchone()[0]
    assert "UNIQUE" in dup.upper() or "unique" in dup
    conn.close()

def test_migration_indexes_present(tmp_path):
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run(db_path)
    conn = sqlite3.connect(db_path)
    idx = {r[1] for r in conn.execute("PRAGMA index_list('intake_candidates')").fetchall()}
    assert "idx_ic_arxiv_id" in idx and "idx_ic_resolution" in idx
    conn.close()
