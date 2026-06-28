# tests/test_collection_topics.py
import sqlite3
import pytest

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


# --- Task 2: 主题 CRUD + 成熟度状态机 ---
from collector import topics  # noqa: E402


def test_create_topic_defaults_to_seedling_active(tmp_path, monkeypatch):
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="目标错误泛化", description="hunch", seed_paper_ids=["2210.00001"])
    assert ct["map_status"] == "seedling" and ct["lifecycle"] == "active"
    assert ct["query_def"]["seed_paper_ids"] == ["2210.00001"]


def test_transition_seedling_to_proposed_allowed(tmp_path, monkeypatch):
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="X", description="")
    topics.transition(ct["id"], to_map_status="proposed", proposed_note="复现5篇/不可折叠/轴risk_domain/边界可述")
    assert topics.get(ct["id"])["map_status"] == "proposed"


def test_transition_mapped_to_seedling_forbidden(tmp_path, monkeypatch):
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="Y", description="")
    topics.transition(ct["id"], to_map_status="proposed", proposed_note="n")
    topics.transition(ct["id"], to_map_status="mapped", mapped_tags=[{"group": "risk_domain", "value": "y"}])
    with pytest.raises(ValueError):
        topics.transition(ct["id"], to_map_status="seedling")


def test_mapped_does_not_touch_vocab(tmp_path, monkeypatch):
    """边界：collector 只把 mapped_tags 记成 JSON，绝不维护 ontology 词表。"""
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="Z", description="")
    topics.transition(ct["id"], to_map_status="proposed", proposed_note="n")
    out = topics.transition(ct["id"], to_map_status="mapped",
                            mapped_tags=[{"group": "risk_domain", "value": "z"}])
    assert out["map_status"] == "mapped"
    # 无 vocab 表（methodology 词表在文档里，不在 DB）；mapped_tags 只是 JSON 记录
    conn = sqlite3.connect(db_path)
    tabs = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "risk_domain_vocab" not in tabs  # collector 不维护词表


def test_transition_lifecycle_orthogonal(tmp_path, monkeypatch):
    """lifecycle (active/paused/retired) 可独立于 map_status 流转。"""
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="L", description="")
    out = topics.transition(ct["id"], to_lifecycle="paused")
    assert out["lifecycle"] == "paused"
    assert out["map_status"] == "seedling"   # lifecycle 改了，map_status 不动
    out = topics.transition(ct["id"], to_lifecycle="retired")
    assert out["lifecycle"] == "retired"


def test_amend_mapped_tags_without_status_change(tmp_path, monkeypatch):
    """已 mapped 的主题可补/改 mapped_tags 而不重复走状态流转。"""
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="M", description="")
    topics.transition(ct["id"], to_map_status="proposed", proposed_note="n")
    topics.transition(ct["id"], to_map_status="mapped",
                      mapped_tags=[{"group": "risk_domain", "value": "a"}])
    # 再次提供 mapped_tags（status 已是 mapped，不变），应更新 tags 而不报错
    out = topics.transition(ct["id"],
                            mapped_tags=[{"group": "risk_domain", "value": "a"},
                                         {"group": "risk_domain", "value": "b"}])
    assert out["map_status"] == "mapped"
    assert out["mapped_tags"] == [{"group": "risk_domain", "value": "a"},
                                  {"group": "risk_domain", "value": "b"}]


def test_list_topics_additive_columns(tmp_path, monkeypatch):
    """list_topics 返回 additive 全列(UI 展示主题详情/4 判据/映射标签所需)。
    既有 key(id/name/map_status/lifecycle)不变,另含 description/axis_hint 等。"""
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    topics.create(name="A", description="d1", explicit_ids=["2501.1"], axis_hint="risk_domain")
    rows = topics.list_topics()
    assert len(rows) == 1
    r = rows[0]
    # 既有 key 不破
    for k in ("id", "name", "map_status", "lifecycle"):
        assert k in r
    # additive 新列
    assert r["description"] == "d1"
    assert r["axis_hint"] == "risk_domain"
    assert r["query_def"] == {"explicit_ids": ["2501.1"], "seed_paper_ids": []}
    assert "proposed_note" in r
    assert "mapped_tags" in r
