"""Shared fixtures for tests that need a sample database without real data."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def sample_db(tmp_path_factory):
    """Create a minimal SQLite DB with enough data for API tests.

    Yields the path to the temp DB file. The DB is automatically cleaned up.
    """
    tmp_dir = tmp_path_factory.mktemp("litlib_sample")
    db_path = tmp_dir / "literature.sqlite"

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    conn.executescript("""
        CREATE TABLE works (
            id TEXT PRIMARY KEY,
            title TEXT,
            authors TEXT DEFAULT '[]',
            year INTEGER,
            arxiv_id TEXT,
            doi TEXT,
            doc_type TEXT DEFAULT 'paper',
            language TEXT DEFAULT 'en',
            metadata_status TEXT DEFAULT 'pending',
            parse_status TEXT DEFAULT 'parsed',
            read_status TEXT DEFAULT 'unread',
            created_at TEXT,
            updated_at TEXT,
            title_zh TEXT,
            venue TEXT,
            url TEXT,
            abstract TEXT,
            primary_doc_type TEXT,
            publication_status TEXT,
            ingestion_state TEXT,
            priority TEXT,
            is_core_literature INTEGER DEFAULT 0,
            primary_source_actor_type TEXT,
            region TEXT,
            canonical_file_format TEXT,
            contributors TEXT,
            publication_date_json TEXT,
            secondary_doc_type TEXT
        );

        CREATE TABLE source_files (
            id TEXT PRIMARY KEY,
            work_id TEXT,
            content_sha256 TEXT,
            original_name TEXT,
            source_path TEXT,
            relative_source_path TEXT,
            file_size INTEGER,
            file_ext TEXT,
            import_time TEXT,
            mtime TEXT,
            status TEXT DEFAULT 'active',
            archived_at TEXT,
            archive_path TEXT,
            archive_reason TEXT
        );

        CREATE TABLE literature_parse_runs (
            id TEXT PRIMARY KEY,
            work_id TEXT,
            source_file_id TEXT,
            source_path TEXT,
            task_id TEXT,
            status TEXT DEFAULT 'pending',
            backend TEXT,
            parse_method TEXT,
            file_size INTEGER,
            started_at TEXT,
            finished_at TEXT,
            output_dir TEXT,
            error TEXT,
            content_json_path TEXT,
            content_md_path TEXT,
            package_path TEXT
        );

        CREATE TABLE metadata_extractions (
            id TEXT PRIMARY KEY,
            work_id TEXT,
            model_name TEXT,
            content_md_path TEXT,
            input_chars INTEGER DEFAULT 0,
            input_tokens_est INTEGER DEFAULT 0,
            raw_response TEXT DEFAULT '{}',
            extracted_json TEXT DEFAULT '{}',
            confidence_json TEXT DEFAULT '{}',
            applied INTEGER DEFAULT 0,
            applied_at TEXT,
            created_at TEXT,
            review_status TEXT DEFAULT 'pending',
            review_note TEXT DEFAULT '',
            reviewed_at TEXT,
            risk_level TEXT DEFAULT 'low',
            risk_score INTEGER DEFAULT 0,
            risk_reasons TEXT DEFAULT '[]',
            review_source TEXT DEFAULT 'human',
            fix_action TEXT DEFAULT '',
            superseded_by TEXT DEFAULT ''
        );

        CREATE TABLE classification_extractions (
            id TEXT PRIMARY KEY,
            work_id TEXT,
            model_name TEXT,
            prompt_version TEXT,
            extracted_json TEXT DEFAULT '{}',
            confidence_json TEXT DEFAULT '{}',
            ambiguity_score INTEGER DEFAULT 0,
            ambiguity_reasons TEXT DEFAULT '[]',
            review_status TEXT DEFAULT 'pending',
            review_note TEXT,
            reviewed_at TEXT,
            fix_action TEXT,
            applied INTEGER DEFAULT 0,
            applied_at TEXT,
            raw_response TEXT DEFAULT '{}',
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE duplicate_groups (
            id TEXT PRIMARY KEY,
            duplicate_type TEXT,
            key TEXT,
            count INTEGER DEFAULT 0
        );

        CREATE TABLE duplicate_candidates (
            id TEXT PRIMARY KEY,
            group_id TEXT,
            source_file_id TEXT,
            work_id TEXT,
            source_path TEXT,
            score REAL,
            reason TEXT,
            reviewed INTEGER DEFAULT 0
        );

        CREATE TABLE work_relations (
            work_id_a TEXT,
            work_id_b TEXT,
            relation_type TEXT,
            confirmed INTEGER DEFAULT 0,
            note TEXT DEFAULT '',
            relation_category TEXT DEFAULT 'content',
            source TEXT DEFAULT 'human',
            created_at TEXT,
            PRIMARY KEY (work_id_a, work_id_b, relation_type)
        );

        CREATE TABLE work_codes (
            work_id TEXT,
            source_file_id TEXT DEFAULT '',
            code TEXT,
            reason TEXT DEFAULT '',
            created_at TEXT,
            PRIMARY KEY (work_id, code)
        );

        CREATE TABLE work_classification_tags (
            id TEXT PRIMARY KEY,
            work_id TEXT,
            tag_group TEXT,
            tag_value TEXT,
            vocab_version TEXT,
            source TEXT DEFAULT 'human',
            confidence TEXT DEFAULT 'high',
            review_status TEXT DEFAULT 'approved',
            reviewed_at TEXT,
            reviewed_by TEXT,
            evidence TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE intake_candidates (
            id TEXT PRIMARY KEY,
            source_type TEXT,
            source_url TEXT,
            title TEXT,
            arxiv_id TEXT,
            doi TEXT,
            url_canonical TEXT,
            fetched_sha256 TEXT,
            local_pdf_path TEXT,
            resolution TEXT,
            matched_work_id TEXT,
            status TEXT DEFAULT 'pending',
            review_status TEXT DEFAULT 'pending',
            review_note TEXT,
            collected_at TEXT,
            resolved_at TEXT,
            ingested_work_id TEXT,
            raw_meta TEXT,
            collection_topic_id TEXT
        );

        CREATE TABLE parse_artifacts (
            id TEXT PRIMARY KEY,
            work_id TEXT,
            source_file_id TEXT,
            type TEXT,
            file_path TEXT,
            parser TEXT,
            parse_time TEXT,
            task_id TEXT
        );

        CREATE TABLE analysis_runs (
            id TEXT PRIMARY KEY,
            kind TEXT,
            angle TEXT,
            template_version INTEGER,
            work_id TEXT,
            input_work_ids TEXT,
            selector_snapshot TEXT,
            executor TEXT,
            model_name TEXT,
            input_scope TEXT,
            input_chars INTEGER,
            extracted_json TEXT,
            confidence TEXT,
            not_addressed INTEGER DEFAULT 0,
            review_status TEXT DEFAULT 'pending',
            review_note TEXT,
            reviewed_at TEXT,
            review_source TEXT,
            superseded_by TEXT,
            md_path TEXT,
            raw_response TEXT,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE collection_topics (
            id TEXT PRIMARY KEY,
            name TEXT,
            description TEXT,
            query_def TEXT,
            map_status TEXT,
            lifecycle TEXT,
            mapped_tags TEXT,
            proposed_note TEXT,
            axis_hint TEXT,
            created_at TEXT,
            updated_at TEXT
        );
    """)

    # Seed works
    works = [
        ("W-sample-001", "Sample Paper Alpha", '["Author A"]', 2024, "arxiv:2401.00001", "10.1234/alpha",
         "paper", "en", "done", "parsed", "unread"),
        ("W-sample-002", "Sample Paper Beta", '["Author B"]', 2023, None, None,
         "paper", "en", "pending", "parsed", "unread"),
        ("W-sample-003", "Sample Paper Gamma", '["Author C"]', 2025, "arxiv:2501.00003", "10.1234/gamma",
         "system_card", "en", "done", "parsed", "read"),
    ]
    for w in works:
        conn.execute(
            "INSERT INTO works (id, title, authors, year, arxiv_id, doi, doc_type, language, "
            "metadata_status, parse_status, read_status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (*w, now, now),
        )

    # Seed source_files
    sources = [
        ("SF-001", "W-sample-001", "sha256aaa111", "alpha.pdf", "/fake/alpha.pdf", "works/W-sample-001/source/alpha.pdf", 100000, ".pdf"),
        ("SF-002", "W-sample-002", "sha256bbb222", "beta.pdf", "/fake/beta.pdf", "works/W-sample-002/source/beta.pdf", 200000, ".pdf"),
        ("SF-003", "W-sample-003", "sha256ccc333", "gamma.pdf", "/fake/gamma.pdf", "works/W-sample-003/source/gamma.pdf", 150000, ".pdf"),
    ]
    for s in sources:
        conn.execute(
            "INSERT INTO source_files (id, work_id, content_sha256, original_name, source_path, "
            "relative_source_path, file_size, file_ext, import_time, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')",
            (*s, now),
        )

    # Seed parse_runs
    conn.execute(
        "INSERT INTO literature_parse_runs (id, work_id, source_file_id, status, content_md_path, started_at, finished_at) "
        "VALUES ('PR-001', 'W-sample-001', 'SF-001', 'succeeded', '', ?, ?)",
        (now, now),
    )

    # Seed metadata_extractions
    meta_exts = [
        ("ME-sample-pending", "W-sample-001", "test-model", "pending", "low", 0),
        ("ME-sample-approved", "W-sample-002", "test-model", "approved", "low", 1),
    ]
    for me in meta_exts:
        conn.execute(
            "INSERT INTO metadata_extractions "
            "(id, work_id, model_name, content_md_path, input_chars, input_tokens_est, "
            "raw_response, extracted_json, confidence_json, applied, created_at, "
            "review_status, risk_level, risk_score, risk_reasons, review_source, fix_action, superseded_by) "
            "VALUES (?, ?, ?, '', 0, 0, '{}', ?, ?, ?, ?, ?, 'low', 0, '[]', 'human', '', '')",
            (me[0], me[1], me[2],
             json.dumps({"title": f"Extracted {me[0]}", "doi": "10.1234/test"}, ensure_ascii=False),
             json.dumps({"title": "high", "doi": "high"}, ensure_ascii=False),
             me[5], now, me[3]),
        )

    # Seed duplicate_groups + candidates
    conn.execute(
        "INSERT INTO duplicate_groups (id, duplicate_type, key, count) "
        "VALUES ('DG-sample-001', 'title_candidate', 'sample alpha', 2)"
    )
    conn.execute(
        "INSERT INTO duplicate_candidates (id, group_id, source_file_id, work_id, reviewed) "
        "VALUES ('DC-001', 'DG-sample-001', 'SF-001', 'W-sample-001', 0)"
    )
    conn.execute(
        "INSERT INTO duplicate_candidates (id, group_id, source_file_id, work_id, reviewed) "
        "VALUES ('DC-002', 'DG-sample-001', 'SF-002', 'W-sample-002', 0)"
    )

    # Seed work_relation
    conn.execute(
        "INSERT INTO work_relations (work_id_a, work_id_b, relation_type, confirmed, note, created_at) "
        "VALUES ('W-sample-001', 'W-sample-003', 'not_duplicate', 1, 'test relation', ?)",
        (now,),
    )

    conn.commit()
    conn.close()

    return db_path
