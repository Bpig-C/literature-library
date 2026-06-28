# tests/test_promote_topic_tags.py
"""Task 7: 晋升后把主题的 mapped_tags 作为建议标签落 classification_extractions。

边界约束（不绕过分类审核门禁）：
  - 写入 source 标识 collector（model_name='collector'）
  - review_status='pending'，applied=0 —— 等人审
"""
import sqlite3, json
from collector import ingest_bridge as br


# classification_extractions 真实 schema（见 scripts/migrate_add_classification_columns.py）
_CE_DDL = """
CREATE TABLE classification_extractions (
    id                  TEXT PRIMARY KEY,
    work_id             TEXT NOT NULL,
    model_name          TEXT,
    prompt_version      TEXT,
    extracted_json      TEXT,
    confidence_json     TEXT,
    ambiguity_score     INTEGER DEFAULT 0,
    ambiguity_reasons   TEXT,
    review_status       TEXT NOT NULL DEFAULT 'pending',
    review_note         TEXT,
    reviewed_at         TEXT,
    fix_action          TEXT,
    applied             INTEGER NOT NULL DEFAULT 0,
    applied_at          TEXT,
    raw_response        TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
)
"""


def _bootstrap(db_path):
    c = sqlite3.connect(db_path)
    c.execute("CREATE TABLE works (id TEXT PRIMARY KEY)")
    c.execute("""CREATE TABLE intake_candidates
        (id TEXT PRIMARY KEY, collection_topic_id TEXT,
         local_pdf_path TEXT, arxiv_id TEXT, title TEXT,
         ingested_work_id TEXT, status TEXT)""")
    c.execute("CREATE TABLE collection_topics (id TEXT PRIMARY KEY, name TEXT, mapped_tags TEXT)")
    c.execute(_CE_DDL)
    c.commit()
    c.close()


def test_promote_writes_suggested_tags_pending(tmp_path, monkeypatch):
    db_path = tmp_path / "literature.sqlite"
    sqlite3.connect(db_path).close()
    _bootstrap(db_path)

    c = sqlite3.connect(db_path)
    c.execute("INSERT INTO intake_candidates (id, collection_topic_id) VALUES ('IC-1','CT-1')")
    c.execute("INSERT INTO collection_topics VALUES ('CT-1','奖励黑客', ?)",
              (json.dumps([{"group": "risk_domain", "value": "reward_hacking"}]),))
    c.commit(); c.close()

    monkeypatch.setattr(br, "get_conn", lambda: sqlite3.connect(db_path))
    monkeypatch.setattr(br, "_do_ingest", lambda cid, library_root: "W-9")  # 桩掉真实晋升

    work_id = br.promote("IC-1", library_root=tmp_path)
    assert work_id == "W-9"

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT model_name, review_status, applied, extracted_json "
        "FROM classification_extractions WHERE work_id='W-9'").fetchone()
    st = conn.execute(
        "SELECT status, ingested_work_id FROM intake_candidates WHERE id='IC-1'").fetchone()
    conn.close()

    assert row is not None
    assert row[0] == "collector"          # 来源标识 = collector
    assert row[1] == "pending"            # 建议标签，等人审
    assert row[2] == 0                    # 未应用，待人审
    payload = json.loads(row[3])
    assert payload["suggested_tags"] == [{"group": "risk_domain", "value": "reward_hacking"}]
    # 候选状态已翻 ingested
    assert st[0] == "ingested" and st[1] == "W-9"


def test_promote_no_topic_writes_no_tags(tmp_path, monkeypatch):
    """候选无 collection_topic_id → 不写建议标签（照样晋升）。"""
    db_path = tmp_path / "literature.sqlite"
    sqlite3.connect(db_path).close()
    _bootstrap(db_path)

    c = sqlite3.connect(db_path)
    c.execute("INSERT INTO intake_candidates (id, collection_topic_id) VALUES ('IC-2',NULL)")
    c.commit(); c.close()

    monkeypatch.setattr(br, "get_conn", lambda: sqlite3.connect(db_path))
    monkeypatch.setattr(br, "_do_ingest", lambda cid, library_root: "W-10")

    br.promote("IC-2", library_root=tmp_path)

    conn = sqlite3.connect(db_path)
    n = conn.execute(
        "SELECT COUNT(*) FROM classification_extractions WHERE work_id='W-10'").fetchone()[0]
    st = conn.execute(
        "SELECT status, ingested_work_id FROM intake_candidates WHERE id='IC-2'").fetchone()
    conn.close()

    assert n == 0
    assert st[0] == "ingested" and st[1] == "W-10"
