import json
from pathlib import Path

from scripts.literature_batch_parse import (
    Ledger,
    bucket_for_size,
    classify_error,
    filter_jobs,
    load_jobs,
    mineru_health_url_from_api_base,
    previous_failure_count,
    should_stop_for_transient_storm,
    upload_filename_for_attempt,
)


def test_bucket_for_size():
    assert bucket_for_size(1) == "small"
    assert bucket_for_size(5 * 1024 * 1024) == "medium"
    assert bucket_for_size(20 * 1024 * 1024) == "large"


def test_load_jobs_and_filter_completed(tmp_path):
    library = tmp_path / "literature_library"
    pdf = library / "works" / "W-test" / "source" / "paper.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-test")
    index = {
        "works": [
            {
                "work_id": "W-test",
                "title": "Test Work",
                "source_files": [
                    {
                        "source_file_id": "SF-test",
                        "original_name": "paper.pdf",
                        "library_relative_path": "works/W-test/source/paper.pdf",
                        "content_sha256": "abc",
                    }
                ],
            }
        ]
    }
    (library / "index.json").write_text(json.dumps(index), encoding="utf-8")

    jobs = load_jobs(library)
    assert len(jobs) == 1
    assert jobs[0].work_id == "W-test"
    assert jobs[0].bucket == "small"

    ledger = Ledger(library / "parse_ledger.json")
    assert filter_jobs(
        jobs,
        ledger,
        bucket="all",
        limit=None,
        retry_failed=False,
        retry_transient=False,
        include_completed=False,
    ) == jobs

    ledger.update("SF-test", status="succeeded")
    assert filter_jobs(
        jobs,
        ledger,
        bucket="all",
        limit=None,
        retry_failed=False,
        retry_transient=False,
        include_completed=False,
    ) == []
    assert filter_jobs(
        jobs,
        ledger,
        bucket="all",
        limit=None,
        retry_failed=False,
        retry_transient=False,
        include_completed=True,
    ) == jobs


def test_classify_error():
    assert classify_error("PDFium: Data format error") == "invalid_pdf"
    assert classify_error("ConnectionResetError 10054") == "transport"
    assert classify_error("WinError 206 文件名或扩展名太长") == "path_error"


def test_mineru_health_url_from_api_base():
    assert mineru_health_url_from_api_base("http://127.0.0.1:18201") == "http://127.0.0.1:18200/health"
    assert mineru_health_url_from_api_base("http://localhost:18201") == "http://127.0.0.1:18200/health"
    assert mineru_health_url_from_api_base("http://10.0.0.5:18201") == "http://10.0.0.5:18200/health"


def test_should_stop_for_transient_storm():
    results = [
        {"status": "failed", "failure_kind": "transport"},
        {"status": "failed", "failure_kind": "timeout"},
        {"status": "failed", "failure_kind": "transport"},
    ]
    assert should_stop_for_transient_storm(results, 3)
    assert not should_stop_for_transient_storm(results, 4)
    assert not should_stop_for_transient_storm([*results, {"status": "failed", "failure_kind": "invalid_pdf"}], 3)
    assert not should_stop_for_transient_storm(results, 0)


def test_upload_filename_for_attempt(tmp_path):
    library = tmp_path / "literature_library"
    pdf = library / "works" / "W-test" / "source" / "paper.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-test")
    index = {
        "works": [
            {
                "work_id": "W-test",
                "title": "Test Work",
                "source_files": [
                    {
                        "source_file_id": "SF-test",
                        "original_name": "paper.pdf",
                        "library_relative_path": "works/W-test/source/paper.pdf",
                        "content_sha256": "abc",
                    }
                ],
            }
        ]
    }
    (library / "index.json").write_text(json.dumps(index), encoding="utf-8")
    job = load_jobs(library)[0]

    assert upload_filename_for_attempt(job, 1) == "SF-test.pdf"
    assert upload_filename_for_attempt(job, 2) == "SF-test-r2.pdf"


def test_previous_failure_count():
    assert previous_failure_count({}) == 0
    assert previous_failure_count({"status": "succeeded", "failure_count": 3}) == 0
    assert previous_failure_count({"status": "failed"}) == 1
    assert previous_failure_count({"status": "failed", "failure_count": 0}) == 1
    assert previous_failure_count({"status": "failed", "failure_count": 4}) == 4
