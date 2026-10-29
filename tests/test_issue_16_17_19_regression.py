"""Regression tests for the 2026-10-25 issue batch (#16 / #17 / #19).

#16  Work 级 A 当前头不得依赖 C/D 研究来源登记（无来源≠无 A）。
#17  正式 original_abstracts 必须进入目录摘要与书目投影，选择规则确定。
#19  目录 language 编辑必须进入正式 payload.language，批准传播不得回滚；
     文献语言与原题语言分开处理。

All stores are synthetic, isolated SQLite files; no production data.
"""
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pytest

from api.bibliographic_projection import get_active_projection, merge_v5_payload, payload_from_works_row
from api.research_context import ResearchContext
from api.research_schema import apply_schema
from api.research_stability import select_catalog_abstract
from api.research_catalog import propagate_metadata
from scripts.literature_ingest import ensure_core_schema


@pytest.fixture
def stores(tmp_path, monkeypatch):
    library = tmp_path / "library"
    (library / "_inbox").mkdir(parents=True)
    with sqlite3.connect(library / "literature.sqlite") as c:
        ensure_core_schema(c)
        # 生产 works 表（schema 6）含 abstract/title_zh 列；基础建表脚本
        # 未含，测试补齐。
        cols = {r[1] for r in c.execute("PRAGMA table_info(works)")}
        if "abstract" not in cols:
            c.execute("ALTER TABLE works ADD COLUMN abstract TEXT")
        if "title_zh" not in cols:
            c.execute("ALTER TABLE works ADD COLUMN title_zh TEXT")
    # 合成运行时资产（apply_schema 需要 baseline 本体，带 manifest 完整性校验）。
    assets_root = tmp_path / "research-assets"
    assets_root.mkdir()
    baseline = {"version": "autonomy-risk-v1", "concepts": [
        {"id": "synthetic", "definition": "Synthetic fixture only"}]}
    (assets_root / "autonomy-risk-v1.json").write_text(
        json.dumps(baseline, ensure_ascii=False), "utf-8")
    manifest = {}
    for path in assets_root.iterdir():
        manifest[path.name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                               "bytes": path.stat().st_size}
    (assets_root / "assets-manifest.json").write_text(json.dumps(manifest), "utf-8")
    monkeypatch.setenv("LITLIB_RESEARCH_ASSETS_ROOT", str(assets_root))
    research_root = tmp_path / "research"
    ctx = ResearchContext(research_root, research_root / "research.sqlite")
    assert apply_schema(ctx, backup=False)["ok"]
    monkeypatch.setenv("LITLIB_DB_PATH", str(library / "literature.sqlite"))
    monkeypatch.setenv("LITLIB_LIBRARY_ROOT", str(library))
    monkeypatch.setenv("LITLIB_RESEARCH_ROOT", str(research_root))
    monkeypatch.setenv("LITLIB_RESEARCH_DB", str(ctx.db_path))
    monkeypatch.delenv("LITLIB_STORAGE_MODE", raising=False)
    return library / "literature.sqlite", ctx


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _insert_work(catalog_path, work_id="W-reg", **overrides):
    row = {"id": work_id, "title": "Regression Work", "authors": '["Alice"]',
           "year": 2026, "language": "en", "doi": None, "arxiv_id": None,
           "doc_type": None, "read_status": "unread", "abstract": None,
           "created_at": _now(), "updated_at": _now()}
    row.update(overrides)
    with closing(sqlite3.connect(catalog_path)) as conn:
        conn.row_factory = sqlite3.Row
        keys = {r[1] for r in conn.execute("PRAGMA table_info(works)")}
        fields = [k for k in row if k in keys]
        conn.execute(
            f"INSERT INTO works ({', '.join(fields)}) VALUES ({', '.join('?' * len(fields))})",
            [row[f] for f in fields])
        conn.commit()
        return conn.execute("SELECT * FROM works WHERE id=?", (work_id,)).fetchone()


def _insert_metadata(ctx, work_id, payload, *, version=1, review="approved",
                     content="stable", validity="active", record_id="RM-reg-1"):
    with closing(ctx.connect()) as conn:
        conn.execute(
            """INSERT INTO research_metadata_records
               (id, work_id, version, payload_json, content_state,
                agent_review_status, validity_status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (record_id, work_id, version, json.dumps(payload, ensure_ascii=False),
             content, review, validity, _now(), _now()))
        conn.commit()


# ---------------------------------------------------------------- #16

def test_issue16_summary_reports_a_head_without_research_sources(stores):
    catalog_path, ctx = stores
    _insert_work(catalog_path)
    payload = {"original_title": {"text": "Regression Work", "language": "en"},
               "authors": [{"display_name": "Alice"}], "language": "en"}
    _insert_metadata(ctx, "W-reg", payload,
                     review="approved", content="stable")

    from api.routes.works import _work_research_summary
    summary = _work_research_summary("W-reg")
    # staged 仅描述 C/D 来源登记；A 当前头必须独立可读（issue #16）。
    assert summary["available"] is True
    assert summary["staged"] is False
    head = summary["metadata_head"]
    assert head and head["agent_review_status"] == "approved" \
        and head["content_state"] == "stable" and head["version"] == 1


def test_issue16_summary_states_missing_a_and_real_review_state(stores):
    catalog_path, ctx = stores
    _insert_work(catalog_path)
    from api.routes.works import _work_research_summary
    # 无来源 + 无 A：准确报无记录（metadata_head 为 None，而非缺键）。
    summary = _work_research_summary("W-reg")
    assert summary["staged"] is False
    assert summary["metadata_head"] is None

    # 无来源 + pending 当前头：如实反映 pending，不伪报稳定。
    _insert_metadata(ctx, "W-reg",
                     {"original_title": {"text": "Regression Work", "language": "en"},
                      "authors": [{"display_name": "Alice"}]},
                     review="pending", content="needs_review", record_id="RM-reg-2")
    summary = _work_research_summary("W-reg")
    assert summary["staged"] is False
    assert summary["metadata_head"]["agent_review_status"] == "pending"


def test_issue16_summary_current_head_not_mixed_with_superseded(stores):
    catalog_path, ctx = stores
    _insert_work(catalog_path)
    base = {"original_title": {"text": "Regression Work", "language": "en"},
            "authors": [{"display_name": "Alice"}]}
    _insert_metadata(ctx, "W-reg", base, version=1, record_id="RM-reg-v1")
    _insert_metadata(ctx, "W-reg", base, version=2, record_id="RM-reg-v2",
                     validity="superseded")
    _insert_metadata(ctx, "W-reg", base, version=3, review="approved",
                     record_id="RM-reg-v3")
    from api.routes.works import _work_research_summary
    summary = _work_research_summary("W-reg")
    assert summary["metadata_head"]["id"] == "RM-reg-v3"


def test_issue16_summary_with_sources_unchanged(stores):
    catalog_path, ctx = stores
    _insert_work(catalog_path)
    with closing(ctx.connect()) as conn:
        conn.execute(
            """INSERT INTO research_sources
               (id, work_id, source_file_id, source_path, snapshot_path,
                source_sha256, parse_exists, created_at)
               VALUES ('RS-reg-1','W-reg','SF-reg-1','works/source.pdf',
                       'snapshots/source.pdf','synthetic-sha',1,?)""", (_now(),))
        conn.commit()
    from api.routes.works import _work_research_summary
    summary = _work_research_summary("W-reg")
    assert summary["staged"] is True
    assert summary["source_ids"] == ["RS-reg-1"]


# ---------------------------------------------------------------- #17

def test_issue17_abstract_selector_rules():
    # 语言匹配 payload.language 优先（主子标签匹配）。
    payload = {"language": "zh-CN",
               "original_abstracts": [
                   {"text": "English abstract", "language": "en"},
                   {"text": "中文摘要", "language": "zh-CN"}]}
    assert select_catalog_abstract(payload) == "中文摘要"
    # 次选：匹配原题语言。
    payload = {"original_title": {"text": "T", "language": "fr"},
               "original_abstracts": [
                   {"text": "English abstract", "language": "en"},
                   {"text": "Résumé français", "language": "fr"}]}
    assert select_catalog_abstract(payload) == "Résumé français"
    # 无语言可匹配：唯一文本可选；多个文本不按存储顺序猜测。
    payload = {"original_abstracts": [{"text": "Only one", "language": "de"}]}
    assert select_catalog_abstract(payload) == "Only one"
    payload = {"original_abstracts": [
        {"text": "First stored", "language": "de"},
        {"text": "Second stored", "language": "ja"}]}
    assert select_catalog_abstract(payload) is None
    # 空文本条目跳过；译文与概览绝不冒充原摘要。
    payload = {"original_abstracts": [{"text": "  ", "language": "en"}],
               "abstract_translations": [{"text": "翻译", "language": "zh"}],
               "descriptive_overview": "Agent 概述"}
    assert select_catalog_abstract(payload) is None
    # 缺失保留缺失语义；旧顶层 abstract 仅作只读兼容回退。
    assert select_catalog_abstract({}) is None
    assert select_catalog_abstract({"abstract": "legacy"}) == "legacy"


def test_issue17_propagation_writes_catalog_and_projection_abstract(stores):
    catalog_path, ctx = stores
    _insert_work(catalog_path, language="en")
    abstract_text = "Verified original abstract " + "x" * 40
    payload = {"original_title": {"text": "Regression Work", "language": "en"},
               "authors": [{"display_name": "Alice"}], "language": "en",
               "original_abstracts": [{"text": abstract_text, "language": "en",
                                       "bound_version": 1}]}
    _insert_metadata(ctx, "W-reg", payload, version=2, record_id="RM-reg-abs")
    result = propagate_metadata(ctx, "W-reg", payload, record_id="RM-reg-abs")
    assert result["projection_id"]

    with closing(sqlite3.connect(catalog_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT abstract FROM works WHERE id='W-reg'").fetchone()
        assert row["abstract"] == abstract_text
        projection = get_active_projection(conn, "W-reg")
    # Work 行与活动投影对同一选择返回一致摘要；导出读同一投影键。
    assert projection["payload"]["abstract"] == abstract_text


def test_issue17_new_selection_replaces_old_and_missing_keeps_explicit(stores):
    catalog_path, ctx = stores
    _insert_work(catalog_path, language="en")
    v2 = {"original_title": {"text": "Regression Work", "language": "en"},
          "authors": [{"display_name": "Alice"}], "language": "en",
          "original_abstracts": [{"text": "old abstract text", "language": "en"}]}
    _insert_metadata(ctx, "W-reg", v2, version=2, record_id="RM-reg-v2")
    propagate_metadata(ctx, "W-reg", v2, record_id="RM-reg-v2")

    # 换版：新摘要替换旧摘要，不保留与当前来源不兼容的旧值。
    v3 = {"original_title": {"text": "Regression Work", "language": "en"},
          "authors": [{"display_name": "Alice"}], "language": "en",
          "original_abstracts": [{"text": "new abstract text", "language": "en"}]}
    _insert_metadata(ctx, "W-reg", v3, version=3, record_id="RM-reg-v3")
    propagate_metadata(ctx, "W-reg", v3, record_id="RM-reg-v3")
    with closing(sqlite3.connect(catalog_path)) as conn:
        conn.row_factory = sqlite3.Row
        assert conn.execute(
            "SELECT abstract FROM works WHERE id='W-reg'").fetchone()["abstract"] \
            == "new abstract text"

    # 无摘要的记录：不伪造、不清空既有目录值（缺失语义保留）。
    v4 = {"original_title": {"text": "Regression Work", "language": "en"},
          "authors": [{"display_name": "Alice"}], "language": "en"}
    _insert_metadata(ctx, "W-reg", v4, version=4, record_id="RM-reg-v4")
    propagate_metadata(ctx, "W-reg", v4, record_id="RM-reg-v4")
    with closing(sqlite3.connect(catalog_path)) as conn:
        conn.row_factory = sqlite3.Row
        assert conn.execute(
            "SELECT abstract FROM works WHERE id='W-reg'").fetchone()["abstract"] \
            == "new abstract text"


def test_issue17_merge_overlay_matches_selector_and_ignores_translations():
    base = {"title": "T", "abstract": "stale row abstract"}
    payload = {"language": "zh",
               "original_abstracts": [{"text": "英文原文摘要", "language": "en"},
                                      {"text": "中文原文摘要", "language": "zh"}],
               "abstract_translations": [{"text": "不该出现的翻译", "language": "zh"}]}
    merged = merge_v5_payload(base, payload)
    assert merged["abstract"] == "中文原文摘要"
    # 只有旧顶层 abstract（无 original_abstracts）时保持既有投影行为。
    merged = merge_v5_payload(base, {"abstract": "legacy field"})
    assert merged["abstract"] == "legacy field"


# ---------------------------------------------------------------- #19

def _catalog_row(catalog_path, work_id="W-reg"):
    with closing(sqlite3.connect(catalog_path)) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM works WHERE id=?", (work_id,)).fetchone()


def test_issue19_language_edit_bridges_into_formal_payload(stores):
    catalog_path, ctx = stores
    _insert_work(catalog_path, language="zh-CN")
    head_payload = {"original_title": {"text": "Regression Work", "language": "en"},
                    "authors": [{"display_name": "Alice"}], "language": "en"}
    from api.routes.works import _work_catalog_metadata_payload
    row = _catalog_row(catalog_path)
    payload = _work_catalog_metadata_payload(row, head_payload)
    # 新目录语言进入正式 payload.language（此前只进 original_title/catalog-sync）。
    assert payload["language"] == "zh-CN"
    # 题目文本未变：原题语言保留已核查值，不随文献语言被盲目改写。
    assert payload["original_title"]["language"] == "en"
    # catalog-sync 扩展仍记录变更字段。
    sync = next(e for e in payload["extensions"] if e.get("name") == "catalog-sync")
    assert "language" in sync["content"]["changed_fields"]


def test_issue19_propagation_after_bridged_revision_does_not_revert(stores):
    catalog_path, ctx = stores
    _insert_work(catalog_path, language="zh-CN")
    head_payload = {"original_title": {"text": "Regression Work", "language": "en"},
                    "authors": [{"display_name": "Alice"}], "language": "en"}
    from api.routes.works import _work_catalog_metadata_payload
    payload = _work_catalog_metadata_payload(_catalog_row(catalog_path), head_payload)
    # 合成审核后状态：传播不应把目录语言改回旧值（issue #19 的回滚路径）。
    _insert_metadata(ctx, "W-reg", payload, version=2, review="approved",
                     content="stable", record_id="RM-reg-lang")
    propagate_metadata(ctx, "W-reg", payload, record_id="RM-reg-lang")
    with closing(sqlite3.connect(catalog_path)) as conn:
        conn.row_factory = sqlite3.Row
        assert conn.execute(
            "SELECT language FROM works WHERE id='W-reg'").fetchone()["language"] \
            == "zh-CN"
        projection = get_active_projection(conn, "W-reg")
    assert projection["payload"]["language"] == "zh-CN"


def test_issue19_first_bridge_and_title_change_use_catalog_language(stores):
    catalog_path, ctx = stores
    _insert_work(catalog_path, language="zh-CN")
    from api.routes.works import _work_catalog_metadata_payload
    # 无旧 A 的首次桥接：正式语言与原题语言都按当前目录语言。
    payload = _work_catalog_metadata_payload(_catalog_row(catalog_path), None)
    assert payload["language"] == "zh-CN"
    assert payload["original_title"]["language"] == "zh-CN"
    # 题目实际变更：新题按当前目录语言标注原题语言。
    with closing(sqlite3.connect(catalog_path)) as conn:
        conn.execute("UPDATE works SET title='新标题' WHERE id='W-reg'")
        conn.commit()
    head_payload = {"original_title": {"text": "Regression Work", "language": "en"},
                    "authors": [{"display_name": "Alice"}], "language": "en"}
    payload = _work_catalog_metadata_payload(_catalog_row(catalog_path), head_payload)
    assert payload["original_title"] == {"text": "新标题", "language": "zh-CN"}


def test_issue19_unknown_catalog_language_keeps_head_value(stores):
    catalog_path, ctx = stores
    _insert_work(catalog_path, language=None)
    head_payload = {"original_title": {"text": "Regression Work", "language": "en"},
                    "authors": [{"display_name": "Alice"}], "language": "en"}
    from api.routes.works import _work_catalog_metadata_payload
    payload = _work_catalog_metadata_payload(_catalog_row(catalog_path), head_payload)
    # 目录语言未知：无损继承，不把正式语言改写成 unknown。
    assert payload["language"] == "en"


# ------------------------------------------- 2026-10-26 独立复核缺陷回归
# 审计 F2/F3（#17）：摘要选择核对 bound_version；换版缺摘要不得把旧版本
# 摘要继续当作当前目录/投影值。

def test_audit_f2_abstract_selection_checks_bound_version():
    from api.research_stability import catalog_abstract_statement
    # 同语言、v1 摘要排在 v2 之前：不得以数组顺序代替版本证据。
    payload = {"language": "en",
               "original_abstracts": [
                   {"text": "v1 abstract", "language": "en", "bound_version": "v1"},
                   {"text": "v2 abstract", "language": "en", "bound_version": "v2"}]}
    assert catalog_abstract_statement(payload) == (None, "version_ambiguous")
    assert select_catalog_abstract(payload) is None
    # 全部条目同一版本（整数与字符串归一化等价）：范围内按语言选择。
    payload = {"language": "en",
               "original_abstracts": [
                   {"text": "v1 abstract", "language": "en", "bound_version": 1},
                   {"text": "v1摘要", "language": "en", "bound_version": "1"},
                   {"text": "zh text", "language": "zh", "bound_version": 1}]}
    assert select_catalog_abstract(payload) is None
    assert catalog_abstract_statement(payload)[1] == "selection_ambiguous"
    # 范围一致时，带版本标签的条目优先于无标签条目（标签是版本证据）。
    payload = {"language": "en",
               "original_abstracts": [
                   {"text": "unlabelled first", "language": "en"},
                   {"text": "labelled v1", "language": "en", "bound_version": "v1"}]}
    assert select_catalog_abstract(payload) == "labelled v1"
    # 完全无版本标签（legacy 数据）：维持既有语言规则，不因缺标签而拒绝。
    payload = {"language": "en",
               "original_abstracts": [{"text": "only", "language": "en"}]}
    assert select_catalog_abstract(payload) == "only"


def test_audit_f3_explicit_empty_abstracts_clear_stale_version_value(stores):
    catalog_path, ctx = stores
    _insert_work(catalog_path, language="en")
    v1_payload = {"original_title": {"text": "Regression Work", "language": "en"},
                  "authors": [{"display_name": "Alice"}], "language": "en",
                  "original_abstracts": [{"text": "v1 abstract text", "language": "en",
                                          "bound_version": "v1"}]}
    _insert_metadata(ctx, "W-reg", v1_payload, version=1, record_id="RM-f3-v1")
    propagate_metadata(ctx, "W-reg", v1_payload, record_id="RM-f3-v1")
    with closing(sqlite3.connect(catalog_path)) as conn:
        conn.row_factory = sqlite3.Row
        assert conn.execute("SELECT abstract FROM works WHERE id='W-reg'"
                            ).fetchone()["abstract"] == "v1 abstract text"

    # 换版新头：显式 original_abstracts=[]（该版本无摘要），不得保留 v1 摘要
    # 与 v2 身份混用；缺失说明写入当前投影，历史在被取代投影中可回查。
    v2_payload = {"original_title": {"text": "Regression Work", "language": "en"},
                  "authors": [{"display_name": "Alice"}], "language": "en",
                  "original_abstracts": []}
    _insert_metadata(ctx, "W-reg", v2_payload, version=2, record_id="RM-f3-v2")
    propagate_metadata(ctx, "W-reg", v2_payload, record_id="RM-f3-v2")
    with closing(sqlite3.connect(catalog_path)) as conn:
        conn.row_factory = sqlite3.Row
        assert conn.execute("SELECT abstract FROM works WHERE id='W-reg'"
                            ).fetchone()["abstract"] is None
        active = get_active_projection(conn, "W-reg")
        assert "abstract" not in active["payload"]
        assert "abstract_note" in active["payload"]
        superseded = conn.execute(
            "SELECT payload_json FROM bibliographic_projections "
            "WHERE work_id='W-reg' AND status!='active' ORDER BY created_at"
        ).fetchall()
        assert any(json.loads(row["payload_json"]).get("abstract") == "v1 abstract text"
                   for row in superseded)

    # 字段缺失（不是显式空列表）：记录未涉及摘要——既有目录值保持缺失语义。
    v3_payload = {"original_title": {"text": "Regression Work", "language": "en"},
                  "authors": [{"display_name": "Alice"}], "language": "en",
                  "original_abstracts": [
                      {"text": "v1 abstract text", "language": "en",
                       "bound_version": "v1"}]}
    v3_payload_2 = {"original_title": {"text": "Regression Work", "language": "en"},
                    "authors": [{"display_name": "Alice"}], "language": "en"}
    _insert_metadata(ctx, "W-reg", v3_payload, version=3, record_id="RM-f3-v3")
    propagate_metadata(ctx, "W-reg", v3_payload, record_id="RM-f3-v3")
    _insert_metadata(ctx, "W-reg", v3_payload_2, version=4, record_id="RM-f3-v4")
    propagate_metadata(ctx, "W-reg", v3_payload_2, record_id="RM-f3-v4")
    with closing(sqlite3.connect(catalog_path)) as conn:
        conn.row_factory = sqlite3.Row
        assert conn.execute("SELECT abstract FROM works WHERE id='W-reg'"
                            ).fetchone()["abstract"] == "v1 abstract text"


def test_audit_f3_merge_overlay_version_ambiguous_and_missing():
    base = {"title": "T", "abstract": "stale row abstract"}
    # 版本歧义：不写不清，附待确认说明。
    merged = merge_v5_payload(base, {"language": "en", "original_abstracts": [
        {"text": "a v1", "language": "en", "bound_version": "v1"},
        {"text": "a v2", "language": "en", "bound_version": "v2"}]})
    assert "abstract" not in merged
    assert "待确认" in merged["abstract_note"]
    # 显式空列表：base 携带的旧摘要被移除，不与新版本身份混用。
    merged = merge_v5_payload(base, {"language": "en", "original_abstracts": []})
    assert "abstract" not in merged
    assert "abstract_note" in merged


# 审计 F4（#19 横向）：非书目修改不得触发桥接；书目修改仅覆盖实际编辑的
# 字段，未编辑 language 继承当前 A。

def _research_head(ctx, work_id="W-reg"):
    with closing(ctx.connect()) as conn:
        row = conn.execute(
            """SELECT id, version, payload_json, agent_review_status, validity_status
               FROM research_metadata_records WHERE work_id=?
               ORDER BY version DESC LIMIT 1""", (work_id,)).fetchone()
        return (dict(row) | {"payload": json.loads(row["payload_json"])}) if row else None


def test_audit_f4_read_status_only_patch_never_bridges(stores, monkeypatch):
    catalog_path, ctx = stores
    _insert_work(catalog_path, language="en")
    # 目录 en；待审核 A 头已把语言修订为 zh（来自研究侧修订，未投影目录）。
    pending = {"original_title": {"text": "Regression Work", "language": "en"},
               "authors": [{"display_name": "Alice"}], "language": "zh"}
    _insert_metadata(ctx, "W-reg", pending, version=1, review="pending",
                     content="needs_review", record_id="RM-f4-pend")

    from fastapi.testclient import TestClient
    from api.main import app
    from api.routes import works as works_route

    def fake_conn():
        conn = sqlite3.connect(catalog_path)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(works_route, "get_conn", fake_conn)
    monkeypatch.setattr(works_route, "LIBRARY_ROOT", catalog_path.parent)
    client = TestClient(app)
    response = client.patch("/api/works/W-reg", json={"read_status": "read"})
    assert response.status_code == 200, response.text
    assert response.json()["metadata_bridge"] is None

    head = _research_head(ctx)
    # 无关目录编辑不生成新头、不 supersede 待审核 zh 修订。
    assert head["id"] == "RM-f4-pend"
    assert head["payload"]["language"] == "zh"
    with closing(sqlite3.connect(catalog_path)) as conn:
        conn.row_factory = sqlite3.Row
        assert conn.execute("SELECT read_status FROM works WHERE id='W-reg'"
                            ).fetchone()["read_status"] == "read"


def test_audit_f4_title_edit_inherits_pending_language(stores, monkeypatch):
    catalog_path, ctx = stores
    _insert_work(catalog_path, language="en")
    pending = {"original_title": {"text": "Regression Work", "language": "en"},
               "authors": [{"display_name": "Alice"}], "language": "zh"}
    _insert_metadata(ctx, "W-reg", pending, version=1, review="pending",
                     content="needs_review", record_id="RM-f4-pend")

    from fastapi.testclient import TestClient
    from api.main import app
    from api.routes import works as works_route

    def fake_conn():
        conn = sqlite3.connect(catalog_path)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(works_route, "get_conn", fake_conn)
    monkeypatch.setattr(works_route, "LIBRARY_ROOT", catalog_path.parent)
    client = TestClient(app)
    response = client.patch("/api/works/W-reg", json={"title": "Edited Title"})
    assert response.status_code == 200, response.text

    head = _research_head(ctx)
    # 书目修改触发桥接：新头携带新题，但未编辑 language 继承待审核 zh 值，
    # 不被目录行 en 倒灌；旧头被 supersede。
    assert head["id"] != "RM-f4-pend"
    assert head["payload"]["original_title"]["text"] == "Edited Title"
    assert head["payload"]["language"] == "zh"
    with closing(ctx.connect()) as conn:
        old = conn.execute(
            "SELECT validity_status FROM research_metadata_records "
            "WHERE id='RM-f4-pend'").fetchone()
        assert old["validity_status"] == "superseded"


def test_audit_f4_type_bridge_only_carries_type_fields(stores):
    catalog_path, ctx = stores
    _insert_work(catalog_path, language="en")
    head_payload = {"original_title": {"text": "Regression Work", "language": "en"},
                    "authors": [{"display_name": "Alice"}], "language": "zh",
                    "citation_year": "2025"}
    from api.routes.works import _work_catalog_metadata_payload
    # 类型桥接 changed=∅：书目键全部继承头，不得被目录行 en/2026 倒灌。
    payload = _work_catalog_metadata_payload(_catalog_row(catalog_path), head_payload,
                                             changed=set())
    assert payload["language"] == "zh"
    assert payload["citation_year"] == "2025"
    assert payload["original_title"] == {"text": "Regression Work", "language": "en"}
    sync = next(e for e in payload["extensions"] if e.get("name") == "catalog-sync")
    assert sync["content"]["changed_fields"] == []


@pytest.mark.parametrize("entries,expected", [
    ([{"text": "old", "bound_version": "v1"}, {"text": "current", "bound_version": "v2"}], "current"),
    ([{"text": "old", "bound_version": "v1"}], None),
    ([{"text": "unscoped"}], None),
    ([{"text": "current", "bound_version": "2601.00001v2"}], "current"),
    ([{"text": "current", "bound_version": "arXiv:2601.00001v2"}], "current"),
    ([{"text": "current", "bound_version": "arXiv:2601.00001v2 fixed PDF"}], "current"),
    ([{"text": "other paper", "bound_version": "arXiv:2601.00002v2 fixed PDF"}], None),
])
def test_explicit_arxiv_version_selects_only_matching_abstract(entries, expected):
    payload = {"arxiv": "2601.00001v2", "original_abstracts": entries}
    assert select_catalog_abstract(payload) == expected
    merged = merge_v5_payload({"abstract": "stale", "arxiv_id": "2601.00001v1"}, payload)
    assert merged.get("abstract") == expected


@pytest.mark.parametrize('reference,bound,expected', [
    ('2601.00001', 'arXiv:2601.00002v2 fixed PDF', None),
    ('2601.00001', 'arXiv:2601.00001v2 fixed PDF', 'current'),
    ('hep-th/9901001', 'arXiv:hep-th/9901002v1', None),
    ('hep-th/9901001', 'arXiv:hep-th/9901001v1', 'current'),
])
def test_versionless_reference_checks_complete_paper_identity(stores, reference, bound, expected):
    catalog_path, ctx = stores
    _insert_work(catalog_path, abstract='previous abstract')
    payload = {'arxiv': reference, 'language': 'en',
               'original_title': {'text': 'Regression Work', 'language': 'en'},
               'authors': [{'display_name': 'Alice'}],
               'original_abstracts': [{'text': 'current', 'language': 'en', 'bound_version': bound}]}
    original = json.dumps(payload, sort_keys=True)
    assert select_catalog_abstract(payload) == expected
    assert merge_v5_payload({'abstract': 'previous abstract'}, payload).get('abstract') == expected
    _insert_metadata(ctx, 'W-reg', payload, record_id='RM-paper-scope')
    propagate_metadata(ctx, 'W-reg', payload, record_id='RM-paper-scope')
    with closing(sqlite3.connect(catalog_path)) as conn:
        conn.row_factory = sqlite3.Row
        assert conn.execute("SELECT abstract FROM works WHERE id='W-reg'").fetchone()[0] == expected
        assert get_active_projection(conn, 'W-reg')['payload'].get('abstract') == expected
    with closing(ctx.connect(read_only=True)) as conn:
        stored = json.loads(conn.execute('SELECT payload_json FROM research_metadata_records WHERE id=?', ('RM-paper-scope',)).fetchone()[0])
    assert json.dumps(stored, sort_keys=True) == original


@pytest.mark.parametrize("abstracts", [None, [{"text": "old", "bound_version": "v1"}]])
def test_version_change_without_matching_abstract_clears_catalog_and_projection(stores, abstracts):
    catalog_path, ctx = stores
    _insert_work(catalog_path, language="en")
    base = {"original_title": {"text": "Regression Work", "language": "en"},
            "authors": [{"display_name": "Alice"}], "language": "en"}
    old = {**base, "arxiv": "2601.00001v1", "original_abstracts": [{"text": "old", "bound_version": "v1"}]}
    _insert_metadata(ctx, "W-reg", old, version=1, record_id="RM-old")
    propagate_metadata(ctx, "W-reg", old, record_id="RM-old")
    new = {**base, "arxiv": "2601.00001v2"}
    if abstracts is not None:
        new["original_abstracts"] = abstracts
    _insert_metadata(ctx, "W-reg", new, version=2, record_id="RM-new")
    propagate_metadata(ctx, "W-reg", new, record_id="RM-new")
    with closing(sqlite3.connect(catalog_path)) as conn:
        conn.row_factory = sqlite3.Row
        assert conn.execute("SELECT abstract FROM works WHERE id='W-reg'").fetchone()[0] is None
        assert not get_active_projection(conn, "W-reg")["payload"].get("abstract")
        assert any(json.loads(r[0]).get("abstract") == "old" for r in conn.execute(
            "SELECT payload_json FROM bibliographic_projections WHERE status='superseded'"))
