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
                     arxiv_id TEXT, title TEXT, status TEXT, ingested_work_id TEXT,
                     collection_topic_id TEXT)""")
    conn.execute("INSERT INTO intake_candidates VALUES ('IC-1', ?, '2406.10162', 'Reward Hacking', 'resolved', NULL, NULL)",
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


def test_promote_consumes_relative_local_pdf_path(tmp_path, monkeypatch):
    """heavy_gate 现在把 local_pdf_path 存成相对 library root（_collector_cache/{id}.pdf）。
    promote 必须按 LIBRARY_ROOT 解析，不能因相对路径 FileNotFoundError。"""
    import api.db
    import scripts.literature_ingest as ingest

    # heavy_gate 的写法：PDF 落在 {LIBRARY_ROOT}/_collector_cache/{cid}.pdf，DB 存相对路径
    cid = "IC-rel"
    cache_dir = tmp_path / "_collector_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    pdf_file = cache_dir / f"{cid}.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 relative-path promote content")

    db_path = tmp_path / "literature.sqlite"
    conn = sqlite3.connect(db_path)
    ingest.ensure_core_schema(conn)
    conn.execute("""CREATE TABLE intake_candidates (id TEXT PRIMARY KEY, local_pdf_path TEXT,
                     arxiv_id TEXT, title TEXT, status TEXT, ingested_work_id TEXT,
                     collection_topic_id TEXT)""")
    # 注意：相对路径（POSIX 分隔符），与 heavy_gate 写入一致
    conn.execute(
        "INSERT INTO intake_candidates VALUES (?, ?, '2212.08073', 'Relative Path Paper', 'resolved', NULL, NULL)",
        (cid, f"_collector_cache/{cid}.pdf"))
    conn.commit(); conn.close()

    def _get_conn():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr(br, "get_conn", _get_conn)
    # resolve_pdf_path 经 api.db.LIBRARY_ROOT 解析相对路径——patch 到 tmp_path
    monkeypatch.setattr(api.db, "LIBRARY_ROOT", tmp_path)

    work_id = br.promote(cid, library_root=tmp_path)
    assert work_id and work_id.startswith("W-")   # 没因相对路径 FileNotFoundError

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT status, ingested_work_id FROM intake_candidates WHERE id=?", (cid,)).fetchone()
    conn.close()
    assert row[0] == "ingested" and row[1] == work_id

