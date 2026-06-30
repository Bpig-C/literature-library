# tests/test_collection_topics.py
"""Unit tests for collector.topics: migration, CRUD, state machine, mapped_tags validation."""
from __future__ import annotations
import sqlite3
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_migration(conn_path):
    """Run collection_topics migration on a fresh DB."""
    import api.db as db
    db.LIBRARY_ROOT = conn_path.parent
    db.DB_PATH = conn_path
    import scripts.migrate_add_collection_topics as m
    m.run(conn_path)
    m.run(conn_path)  # 幂等：再跑不报错


def _seed_topic(conn, topic_id="CT-T1", map_status="seedling"):
    now = "2026-06-30T00:00:00"
    conn.execute("DELETE FROM collection_topics WHERE id=?", (topic_id,))
    conn.execute(
        """INSERT OR REPLACE INTO collection_topics
           (id,name,description,query_def,map_status,lifecycle,mapped_tags,
            proposed_note,axis_hint,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (topic_id, "test", "d", '{"explicit_ids":[],"seed_paper_ids":[]}',
         map_status, "active", None, None, None, now, now),
    )
    conn.commit()


def _valid_tags():
    return [
        {"group": "risk_domain", "value": "deception"},
        {"group": "reading_lane", "value": "evaluation_method"},
    ]


# ---------------------------------------------------------------------------
# Migration tests (use tmp_path — no real DB dependency)
# ---------------------------------------------------------------------------

def test_migration_creates_collection_topics(tmp_path, monkeypatch):
    db_path = tmp_path / "literature.sqlite"
    sqlite3.connect(db_path).close()
    _run_migration(db_path)
    conn = sqlite3.connect(db_path)
    rows = conn.execute("PRAGMA table_info(collection_topics)").fetchall()
    cols = {r[1] for r in rows}
    assert {"id", "name", "description", "query_def", "map_status", "lifecycle",
            "mapped_tags", "proposed_note", "axis_hint", "created_at", "updated_at"} <= cols
    conn.close()


def test_migration_adds_topic_fk_column(tmp_path):
    db_path = tmp_path / "literature.sqlite"
    c = sqlite3.connect(db_path)
    c.execute("CREATE TABLE intake_candidates (id TEXT PRIMARY KEY)")
    c.close()
    _run_migration(db_path)
    conn = sqlite3.connect(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(intake_candidates)").fetchall()}
    assert "collection_topic_id" in cols
    conn.close()


# ---------------------------------------------------------------------------
# CRUD + state machine tests (use tmp_path + monkeypatch)
# ---------------------------------------------------------------------------

def test_create_topic_defaults_to_seedling_active(tmp_path, monkeypatch):
    from collector import topics
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="目标错误泛化", description="hunch", seed_paper_ids=["2210.00001"])
    assert ct["map_status"] == "seedling" and ct["lifecycle"] == "active"
    assert ct["query_def"]["seed_paper_ids"] == ["2210.00001"]


def test_transition_seedling_to_proposed_allowed(tmp_path, monkeypatch):
    from collector import topics
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="X", description="")
    topics.transition(ct["id"], to_map_status="proposed", proposed_note="复现5篇/不可折叠/轴risk_domain/边界可述")
    assert topics.get(ct["id"])["map_status"] == "proposed"


def test_transition_mapped_to_seedling_forbidden(tmp_path, monkeypatch):
    from collector import topics
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="Y", description="")
    topics.transition(ct["id"], to_map_status="proposed", proposed_note="n")
    topics.transition(ct["id"], to_map_status="mapped", mapped_tags=[{"group": "risk_domain", "value": "deception"}])
    with pytest.raises(ValueError):
        topics.transition(ct["id"], to_map_status="seedling")


def test_mapped_does_not_touch_vocab(tmp_path, monkeypatch):
    """边界：collector 只把 mapped_tags 记成 JSON，绝不维护 ontology 词表。"""
    from collector import topics
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="Z", description="")
    topics.transition(ct["id"], to_map_status="proposed", proposed_note="n")
    out = topics.transition(ct["id"], to_map_status="mapped",
                            mapped_tags=[{"group": "risk_domain", "value": "deception"}])
    assert out["map_status"] == "mapped"
    conn = sqlite3.connect(db_path)
    tabs = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "risk_domain_vocab" not in tabs


def test_transition_lifecycle_orthogonal(tmp_path, monkeypatch):
    from collector import topics
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="L", description="")
    out = topics.transition(ct["id"], to_lifecycle="paused")
    assert out["lifecycle"] == "paused"
    assert out["map_status"] == "seedling"
    out = topics.transition(ct["id"], to_lifecycle="retired")
    assert out["lifecycle"] == "retired"


def test_amend_mapped_tags_without_status_change(tmp_path, monkeypatch):
    from collector import topics
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="M", description="")
    topics.transition(ct["id"], to_map_status="proposed", proposed_note="n")
    topics.transition(ct["id"], to_map_status="mapped",
                      mapped_tags=[{"group": "risk_domain", "value": "deception"}])
    out = topics.transition(ct["id"],
                            mapped_tags=[{"group": "risk_domain", "value": "deception"},
                                         {"group": "risk_domain", "value": "scheming"}])
    assert out["map_status"] == "mapped"
    assert len(out["mapped_tags"]) == 2


def test_list_topics_additive_columns(tmp_path, monkeypatch):
    from collector import topics
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    topics.create(name="A", description="d1", explicit_ids=["2501.1"], axis_hint="risk_domain")
    rows = topics.list_topics()
    assert len(rows) == 1
    r = rows[0]
    for k in ("id", "name", "map_status", "lifecycle"):
        assert k in r
    assert r["description"] == "d1"
    assert r["axis_hint"] == "risk_domain"
    assert r["query_def"] == {"explicit_ids": ["2501.1"], "seed_paper_ids": []}
    assert "proposed_note" in r
    assert "mapped_tags" in r


# ---------------------------------------------------------------------------
# mapped_tags validation tests (use tmp_path + monkeypatch)
# ---------------------------------------------------------------------------

def test_valid_mapped_tags_pass(tmp_path, monkeypatch):
    from collector import topics
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="V1", description="")
    topics.transition(ct["id"], to_map_status="proposed", proposed_note="criteria text")
    result = topics.transition(ct["id"], to_map_status="mapped", mapped_tags=_valid_tags())
    assert result["map_status"] == "mapped"
    assert result["mapped_tags"] == _valid_tags()


def test_invalid_group_rejected(tmp_path, monkeypatch):
    from collector import topics
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="V2", description="")
    topics.transition(ct["id"], to_map_status="proposed", proposed_note="criteria text")
    bad_tags = [{"group": "primary_doc_type", "value": "survey_review"}]
    with pytest.raises(ValueError, match="invalid mapped_tags group"):
        topics.transition(ct["id"], to_map_status="mapped", mapped_tags=bad_tags)


def test_invalid_value_rejected(tmp_path, monkeypatch):
    from collector import topics
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="V3", description="")
    topics.transition(ct["id"], to_map_status="proposed", proposed_note="criteria text")
    bad_tags = [{"group": "risk_domain", "value": "nonexistent_risk_999"}]
    with pytest.raises(ValueError, match="is not in vocab"):
        topics.transition(ct["id"], to_map_status="mapped", mapped_tags=bad_tags)


def test_amend_mapped_tags_also_validates(tmp_path, monkeypatch):
    from collector import topics
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="V4", description="")
    topics.transition(ct["id"], to_map_status="proposed", proposed_note="criteria text")
    topics.transition(ct["id"], to_map_status="mapped", mapped_tags=_valid_tags())
    bad_tags = [{"group": "risk_domain", "value": "totally_fake"}]
    with pytest.raises(ValueError, match="is not in vocab"):
        topics.transition(ct["id"], mapped_tags=bad_tags)
    new_tags = [{"group": "method_tags", "value": "red_teaming"}]
    result = topics.transition(ct["id"], mapped_tags=new_tags)
    assert result["mapped_tags"] == new_tags


def test_seedling_does_not_require_mapped_tags(tmp_path, monkeypatch):
    from collector import topics
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="V5", description="")
    result = topics.transition(ct["id"], to_map_status="proposed",
                               proposed_note="criteria text for proposed")
    assert result["map_status"] == "proposed"
    assert result["mapped_tags"] is None


def test_empty_mapped_tags_list_rejected(tmp_path, monkeypatch):
    from collector import topics
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="E1", description="")
    topics.transition(ct["id"], to_map_status="proposed", proposed_note="criteria text")
    topics.transition(ct["id"], to_map_status="mapped", mapped_tags=_valid_tags())
    with pytest.raises(ValueError, match="non-empty list"):
        topics.transition(ct["id"], mapped_tags=[])


def test_none_value_in_tag_dict_rejected(tmp_path, monkeypatch):
    from collector import topics
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="E2", description="")
    topics.transition(ct["id"], to_map_status="proposed", proposed_note="criteria text")
    bad_tags = [{"group": "risk_domain", "value": None}]
    with pytest.raises(ValueError, match="is not in vocab"):
        topics.transition(ct["id"], to_map_status="mapped", mapped_tags=bad_tags)


def test_duplicate_tags_allowed_by_validation(tmp_path, monkeypatch):
    from collector import topics
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="E3", description="")
    topics.transition(ct["id"], to_map_status="proposed", proposed_note="criteria text")
    dup_tags = [
        {"group": "risk_domain", "value": "deception"},
        {"group": "risk_domain", "value": "deception"},
    ]
    result = topics.transition(ct["id"], to_map_status="mapped", mapped_tags=dup_tags)
    assert result["mapped_tags"] == dup_tags


def test_group_case_sensitive(tmp_path, monkeypatch):
    from collector import topics
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="E4", description="")
    topics.transition(ct["id"], to_map_status="proposed", proposed_note="criteria text")
    bad_tags = [{"group": "Risk_Domain", "value": "deception"}]
    with pytest.raises(ValueError, match="invalid mapped_tags group"):
        topics.transition(ct["id"], to_map_status="mapped", mapped_tags=bad_tags)


def test_idempotent_same_status_noop(tmp_path, monkeypatch):
    from collector import topics
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="E5", description="")
    result = topics.transition(ct["id"], to_map_status="seedling")
    assert result["map_status"] == "seedling"


def test_missing_group_key_rejected(tmp_path, monkeypatch):
    from collector import topics
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="E6", description="")
    topics.transition(ct["id"], to_map_status="proposed", proposed_note="criteria text")
    bad_tags = [{"value": "deception"}]
    with pytest.raises(ValueError, match="invalid mapped_tags entry"):
        topics.transition(ct["id"], to_map_status="mapped", mapped_tags=bad_tags)


def test_missing_value_key_rejected(tmp_path, monkeypatch):
    from collector import topics
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="E7", description="")
    topics.transition(ct["id"], to_map_status="proposed", proposed_note="criteria text")
    bad_tags = [{"group": "risk_domain"}]
    with pytest.raises(ValueError, match="invalid mapped_tags entry"):
        topics.transition(ct["id"], to_map_status="mapped", mapped_tags=bad_tags)


def test_non_dict_tag_entry_rejected(tmp_path, monkeypatch):
    from collector import topics
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="E8", description="")
    topics.transition(ct["id"], to_map_status="proposed", proposed_note="criteria text")
    bad_tags = ["risk_domain:deception"]
    with pytest.raises(ValueError, match="invalid mapped_tags entry"):
        topics.transition(ct["id"], to_map_status="mapped", mapped_tags=bad_tags)


# ---------------------------------------------------------------------------
# P1-2: create topic with mapped_tags (auto status assignment)
# ---------------------------------------------------------------------------

def test_create_topic_with_vocab_tags_marks_approved(tmp_path, monkeypatch):
    """P1-2: 创建时带词表内标签 → status=approved，map_status 仍 seedling。"""
    from collector import topics
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(
        name="T1", description="",
        mapped_tags=[{"group": "risk_domain", "value": "deception"}],
    )
    assert ct["map_status"] == "seedling"
    tags = ct["mapped_tags"]
    assert tags[0]["status"] == "approved"


def test_create_topic_with_custom_tag_marks_proposed_new(tmp_path, monkeypatch):
    """P1-2: 词表外的自定义值 → status=proposed_new，不报错。"""
    from collector import topics
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(
        name="T2", description="",
        mapped_tags=[{"group": "risk_domain", "value": "goal_misgeneralization"}],
    )
    tags = ct["mapped_tags"]
    assert tags[0]["status"] == "proposed_new"
    assert tags[0]["value"] == "goal_misgeneralization"


def test_create_topic_without_tags_keeps_mapped_tags_none(tmp_path, monkeypatch):
    """P1-2: 不带标签 → mapped_tags 仍为 None（兼容旧路径）。"""
    from collector import topics
    db_path = tmp_path / "literature.sqlite"; sqlite3.connect(db_path).close()
    _run_migration(db_path)
    monkeypatch.setattr(topics, "get_conn", lambda: sqlite3.connect(db_path))
    ct = topics.create(name="T3")
    assert ct["mapped_tags"] is None
