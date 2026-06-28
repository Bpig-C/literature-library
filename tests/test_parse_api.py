# tests/test_parse_api.py
"""Parse trigger/status API route tests. Temp DB copy; patches get_conn + LIBRARY_ROOT
in api.routes.parse. The nucleus delegation point _run_parse is stubbed so tests
never touch real clients / fitz / network."""
from __future__ import annotations
import shutil, sqlite3, tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.db import DB_PATH
from api.main import app

_tmp_dir = tempfile.mkdtemp(prefix="litlib_parse_")
_tmp_db = Path(_tmp_dir) / "literature.sqlite"
shutil.copy2(str(DB_PATH), str(_tmp_db))


def _test_get_conn():
    c = sqlite3.connect(str(_tmp_db)); c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL"); return c


@pytest.fixture(autouse=True, scope="function")
def _patch_get_conn():
    import api.routes.parse as parse
    with patch("api.routes.parse.get_conn", _test_get_conn), \
         patch("api.routes.parse.LIBRARY_ROOT", _tmp_dir):
        yield


@pytest.fixture(autouse=True, scope="session")
def _seed():
    conn = _test_get_conn()
    now = "2026-06-28T00:00:00"
    conn.executemany(
        "INSERT OR REPLACE INTO works(id,title,language,parse_status,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?)",
        [("W-parse-test-1", "T1", "english", "pending", now, now),
         ("W-parse-test-2", "T2", "chinese", "pending", now, now)],
    )
    out1 = str(Path(_tmp_dir) / "works" / "W-parse-test-1" / "parsed" / "mineru" / "SF-1")
    out2 = str(Path(_tmp_dir) / "works" / "W-parse-test-2" / "parsed" / "mineru" / "SF-2")
    conn.executemany(
        "INSERT OR REPLACE INTO literature_parse_runs"
        "(id,work_id,source_file_id,source_path,task_id,status,backend,parse_method,"
        " file_size,started_at,finished_at,output_dir,error,content_json_path,"
        " content_md_path,package_path) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [("LPR-SF-1", "W-parse-test-1", "SF-1", "/tmp/a.pdf", "", "pending", "",
          "auto", 0, now, None, out1, "", "", "", ""),
         ("LPR-SF-2", "W-parse-test-2", "SF-2", "/tmp/b.pdf", "", "pending", "",
          "auto", 0, now, None, out2, "", "", "", "")],
    )
    conn.commit(); conn.close()


@pytest.fixture(autouse=True, scope="session")
def _cleanup():
    yield
    shutil.rmtree(_tmp_dir, ignore_errors=True)


client = TestClient(app)


def test_status_aggregate_counts():
    r = client.get("/api/parse/status")
    assert r.status_code == 200
    s = r.json()
    assert s["total"] >= 2
    assert s["pending"] >= 2


def test_status_single_work():
    r = client.get("/api/parse/status", params={"work_id": "W-parse-test-1"})
    assert r.status_code == 200
    body = r.json()
    assert body["work"]["work_id"] == "W-parse-test-1"
    assert body["work"]["status"] == "pending"
    assert body["work"]["content_md_path"] in ("", None)
