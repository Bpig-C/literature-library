# tests/test_discovery_explicit.py
"""Task 3 (a): explicit-ID discovery adapter. Routes inserts through
candidate_store.insert_candidate (tiered candidate-layer dedup)."""
import sqlite3
import scripts.migrate_add_intake_candidates as mic
from collector import candidate_store as cs
from collector import discovery_explicit as de


def _db(tmp_path):
    db_path = tmp_path / "literature.sqlite"
    sqlite3.connect(db_path).close()
    mic.run(db_path)   # 建真实 intake_candidates 表（含 insert_candidate 需要的全部列）
    return db_path


def test_explicit_ids_create_pending_candidates(tmp_path, monkeypatch):
    db_path = _db(tmp_path)
    monkeypatch.setattr(cs, "get_conn", lambda: sqlite3.connect(db_path))

    def fake_fetch(arxiv_id):
        return {"arxiv_id": arxiv_id, "title": "Paper " + arxiv_id,
                "authors": [], "doi": None, "abstract": None}
    monkeypatch.setattr(de, "fetch_metadata", fake_fetch)

    created = de.collect_explicit(["2501.17805", "2501.00002"], source_type="arxiv")
    assert len(created) == 2
    assert all(c["resolution"] == "pending" for c in created)
    assert {c["arxiv_id"] for c in created} == {"2501.17805", "2501.00002"}


def test_explicit_ids_dedup_on_recollect(tmp_path, monkeypatch):
    db_path = _db(tmp_path)
    monkeypatch.setattr(cs, "get_conn", lambda: sqlite3.connect(db_path))
    monkeypatch.setattr(
        de, "fetch_metadata",
        lambda aid: {"arxiv_id": aid, "title": "T", "authors": [], "doi": None, "abstract": None})
    de.collect_explicit(["2501.17805"], source_type="arxiv")
    again = de.collect_explicit(["2501.17805"], source_type="arxiv")
    assert len(again) == 0   # 已是候选 → skipped_dup，不重复计
