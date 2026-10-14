"""Ingest purpose tests: required field, duplicate append, idempotent retry, query."""
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts.literature_ingest import (
    ensure_core_schema, validate_purpose, save_ingest_notes,
    query_ingest_notes, IngestPlan,
)


@pytest.fixture()
def db(tmp_path):
    conn = sqlite3.connect(tmp_path / "literature.sqlite")
    ensure_core_schema(conn)
    conn.execute(
        "INSERT INTO works (id, title, parse_status, read_status, created_at, updated_at) "
        "VALUES ('W-test1', 'Test Work', 'pending', 'unread', '2026-01-01', '2026-01-01')")
    conn.commit()
    for sf in ['SF-abc','SF-old','SF-a','SF-b','SF-test1']:
        conn.execute("INSERT INTO source_files (id,work_id,content_sha256,source_path,relative_source_path) VALUES (?,'W-test1',?,'synthetic','synthetic')",(sf,sf))
    conn.commit()
    yield tmp_path
    conn.close()


class _ShimAction:
    def __init__(self, work_id, source_file_id=None):
        self.work_id = work_id
        self.source_file_id = source_file_id or f"SF-{work_id[-4:]}"


class _ShimDup:
    def __init__(self, work_id, source_file_id):
        self.existing_work_id = work_id
        self.existing_source_file_id = source_file_id


def _plan(work_id, source_file_id=None, dup_sf=None):
    plan = IngestPlan(generated_at="", library_root=str(Path(".")), inbox_dir="", dry_run=False)
    if work_id:
        plan.ingests.append(_ShimAction(work_id, source_file_id))
    if dup_sf:
        plan.exact_duplicates.append(_ShimDup(work_id, dup_sf))
    return plan


# 1. blank/missing purpose rejected
def test_blank_purpose_rejected():
    with pytest.raises(ValueError, match="required"):
        validate_purpose("")
    with pytest.raises(ValueError, match="required"):
        validate_purpose("   ")
    with pytest.raises(ValueError, match="required"):
        validate_purpose("\t\n")


def test_overlong_purpose_rejected():
    with pytest.raises(ValueError, match="2000"):
        validate_purpose("x" * 2001)


def test_valid_purpose_stripped():
    assert validate_purpose("  用于综述  ") == "用于综述"


# 2. new work gets purpose
def test_new_work_purpose_saved(db):
    plan = _plan("W-test1", "SF-abc")
    r = save_ingest_notes(db, plan, "用于风险分类综述", "req-001")
    assert r["purposes_saved"] == 1
    notes = query_ingest_notes(db, "W-test1")
    assert len(notes) == 1
    assert notes[0]["purpose"] == "用于风险分类综述"
    assert notes[0]["request_id"] == "req-001"


# 3. duplicate append doesn't create new work/source/parse
def test_duplicate_append(db):
    plan = _plan(None, None, dup_sf="SF-abc")
    plan.exact_duplicates[0].existing_work_id = "W-test1"
    plan.exact_duplicates[0].existing_source_file_id = "SF-abc"
    r = save_ingest_notes(db, plan, "用于案例分析", "req-002")
    assert r["purposes_saved"] == 1
    notes = query_ingest_notes(db, "W-test1")
    assert len(notes) == 1
    assert notes[0]["purpose"] == "用于案例分析"


# 4. mixed batch: new + duplicate each get purpose
def test_mixed_batch(db):
    conn = sqlite3.connect(db / "literature.sqlite")
    conn.execute("INSERT INTO works (id, title, parse_status, read_status, created_at, updated_at) "
                 "VALUES ('W-test2', 'Second', 'pending', 'unread', '2026-01-01', '2026-01-01')")
    conn.commit()
    conn.execute("INSERT INTO source_files (id,work_id,content_sha256,source_path,relative_source_path) VALUES ('SF-new','W-test2','new','synthetic','synthetic')")
    conn.commit()
    conn.close()
    plan = _plan("W-test2", "SF-new")
    plan.exact_duplicates.append(_ShimDup("W-test1", "SF-old"))
    r = save_ingest_notes(db, plan, "批量入库用途", "req-003")
    assert r["purposes_saved"] == 2
    assert len(query_ingest_notes(db, "W-test1")) == 1
    assert len(query_ingest_notes(db, "W-test2")) == 1


# 5. same work from multiple files gets only one note
def test_same_work_one_note(db):
    plan = _plan("W-test1", "SF-a")
    plan.ingests.append(_ShimAction("W-test1", "SF-b"))
    r = save_ingest_notes(db, plan, "一次用途", "req-004")
    assert r["purposes_saved"] == 1
    assert r["works_annotated"] == 1


# 6a. same request_id retry is idempotent
def test_retry_idempotent(db):
    plan = _plan("W-test1", "SF-abc")
    save_ingest_notes(db, plan, "用途", "req-stable")
    r2 = save_ingest_notes(db, plan, "用途", "req-stable")
    assert r2["purposes_saved"] == 0
    assert r2["purposes_already_existed"] == 1
    assert len(query_ingest_notes(db, "W-test1")) == 1


# 6b. different request_id with same text appends
def test_different_request_same_text(db):
    plan = _plan("W-test1", "SF-abc")
    save_ingest_notes(db, plan, "重复文本", "req-a")
    save_ingest_notes(db, plan, "重复文本", "req-b")
    assert len(query_ingest_notes(db, "W-test1")) == 2


# 7. missing work is silently skipped
def test_nonexistent_work_rejected(db):
    plan = _plan("W-nonexistent", "SF-xyz")
    with pytest.raises(ValueError,match='not found'):
        save_ingest_notes(db, plan, "用途", "req-x")


# 8. empty request_id rejected
def test_empty_request_id_rejected(db):
    plan = _plan("W-test1", "SF-abc")
    with pytest.raises(ValueError, match="request_id"):
        save_ingest_notes(db, plan, "用途", "")


# 9. query on empty DB returns empty list
def test_query_no_data(tmp_path):
    conn = sqlite3.connect(tmp_path / "literature.sqlite")
    ensure_core_schema(conn)
    conn.close()
    assert query_ingest_notes(tmp_path, "W-nobody") == []


# 10. query from non-existent DB returns empty
def test_query_no_db(tmp_path):
    assert query_ingest_notes(tmp_path / "nonexistent", "W-1") == []
