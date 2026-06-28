# tests/test_discovery_citation.py
"""Task 4 (c): citation-graph discovery adapter (Semantic Scholar 1 hop).
Reuses collect_explicit to write candidates (no re-implementation of candidate writing).
"""
import sqlite3
import scripts.migrate_add_intake_candidates as mic
from collector import candidate_store as cs
from collector import discovery_explicit as de
from collector import discovery_citation as dc


def _db(tmp_path):
    db_path = tmp_path / "literature.sqlite"
    sqlite3.connect(db_path).close()
    mic.run(db_path)
    return db_path


def test_citation_expansion_one_hop(tmp_path, monkeypatch):
    db_path = _db(tmp_path)
    monkeypatch.setattr(cs, "get_conn", lambda: sqlite3.connect(db_path))
    # collect_explicit 内部会调 fetch_metadata —— 必须桩掉，避免打真实 arXiv API
    monkeypatch.setattr(de, "fetch_metadata",
                        lambda aid: {"arxiv_id": aid, "title": "T " + aid, "authors": [], "doi": None, "abstract": None})

    def fake_expand(seed_arxiv_id):
        # forward (citing seed) + backward (cited by seed) 各一篇
        return ([{"arxiv_id": "2502.00010", "title": "Cites seed"}],
                [{"arxiv_id": "2401.00001", "title": "Cited by seed"}])
    monkeypatch.setattr(dc, "expand_one_hop", fake_expand)

    created = dc.collect_from_seeds(["2501.17805"], source_type="arxiv")
    aids = {c["arxiv_id"] for c in created}
    assert aids == {"2502.00010", "2401.00001"}
    assert all(c["resolution"] == "pending" for c in created)


def test_collect_from_seeds_deduped(tmp_path, monkeypatch):
    """两个种子都指向同一篇 → 候选层去重，只产 1 个。"""
    db_path = _db(tmp_path)
    monkeypatch.setattr(cs, "get_conn", lambda: sqlite3.connect(db_path))
    monkeypatch.setattr(de, "fetch_metadata",
                        lambda aid: {"arxiv_id": aid, "title": "T", "authors": [], "doi": None, "abstract": None})

    def fake_expand(seed):
        return ([{"arxiv_id": "2502.00010", "title": "X"}], [])
    monkeypatch.setattr(dc, "expand_one_hop", fake_expand)
    created = dc.collect_from_seeds(["2501.17805", "2501.99999"], source_type="arxiv")
    assert len(created) == 1   # 两个种子扩出同一个 id → insert_candidate 去重


def test_collect_from_seeds_skips_none_ids(tmp_path, monkeypatch):
    db_path = _db(tmp_path)
    monkeypatch.setattr(cs, "get_conn", lambda: sqlite3.connect(db_path))
    monkeypatch.setattr(de, "fetch_metadata",
                        lambda aid: {"arxiv_id": aid, "title": "T", "authors": [], "doi": None, "abstract": None})

    def fake_expand(seed):
        # 一条有效 arxiv_id + 一条 normalize 掉的脏数据（None）
        return ([{"arxiv_id": None, "title": "no id"}, {"arxiv_id": "2502.00010", "title": "ok"}], [])
    monkeypatch.setattr(dc, "expand_one_hop", fake_expand)
    created = dc.collect_from_seeds(["2501.17805"], source_type="arxiv")
    assert {c["arxiv_id"] for c in created} == {"2502.00010"}


def test_expand_one_hop_parses_s2_shape(tmp_path, monkeypatch):
    """离线验证 expand_one_hop 对 S2 JSON 形状（citingPaper/citedPaper/externalIds.ArXiv）的解析。

    不打网络：通过 monkeypatch dc._s2_get（expand_one_hop 内部三处 fetch 都走它：
    先 _arxiv_to_s2paper 解析 paperId，再 citations，再 references）喂入录制 JSON。
    """
    # _arxiv_to_s2paper 的返回
    paper_resp = {"paperId": "PID-1", "externalIds": {"ArXiv": "2501.17805"}, "title": "Seed"}
    # /citations 返回（forward：引用 seed 的论文）
    citations_resp = {"data": [
        {"citingPaper": {"externalIds": {"ArXiv": "2502.00010"}, "title": "Cites seed"}},
        {"citingPaper": {"externalIds": {"DOI": "10.1/x"}, "title": "No arxiv -> dropped"}},  # 无 ArXiv → 丢
        {"citingPaper": {"externalIds": {}, "title": "Empty ext"}},                            # 空 → 丢
    ]}
    # /references 返回（backward：seed 引用的论文）
    references_resp = {"data": [
        {"citedPaper": {"externalIds": {"ArXiv": "2401.00001"}, "title": "Cited by seed"}},
    ]}
    # pop 顺序必须匹配 expand_one_hop 的调用顺序：paper 先，citations 次，references 最后
    responses = [paper_resp, citations_resp, references_resp]
    monkeypatch.setattr(dc, "_s2_get", lambda url: responses.pop(0))

    forward, backward = dc.expand_one_hop("2501.17805")
    assert [p["arxiv_id"] for p in forward] == ["2502.00010"]   # 只有带 ArXiv 的进 forward
    assert [p["arxiv_id"] for p in backward] == ["2401.00001"]
