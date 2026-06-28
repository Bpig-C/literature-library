# tests/test_ingest_bridge.py
import sqlite3
from pathlib import Path
from collector import ingest_bridge as br

def test_promote_creates_work_and_backfills(tmp_path, monkeypatch):
    import scripts.literature_ingest as ingest
    pdf = tmp_path / "c.pdf"
    pdf.write_bytes(b"%PDF-1.4 real content here for ingest")  # 非空 PDF 内容
    db_path = tmp_path / "literature.sqlite"
    conn = sqlite3.connect(db_path)
    ingest.ensure_core_schema(conn)   # 建 works/source_files/parse_runs/duplicate_*/...
    conn.execute("""CREATE TABLE intake_candidates (id TEXT PRIMARY KEY, local_pdf_path TEXT,
                     arxiv_id TEXT, title TEXT, status TEXT, ingested_work_id TEXT)""")
    conn.execute("INSERT INTO intake_candidates VALUES ('IC-1', ?, '2406.10162', 'Reward Hacking', 'resolved', NULL)",
                 (str(pdf),))
    conn.commit(); conn.close()

    def _get_conn():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row  # match api.db.get_conn row_factory
        return c
    monkeypatch.setattr(br, "get_conn", _get_conn)
    work_id = br.promote("IC-1", library_root=tmp_path)
    assert work_id and work_id.startswith("W-")
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT status, ingested_work_id FROM intake_candidates WHERE id='IC-1'").fetchone()
    conn.close()
    assert row[0] == "ingested" and row[1] == work_id
