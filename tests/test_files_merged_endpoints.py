"""合并旁路资产端点测试：GET /files/{work_id}/merged 与 /detail（UX-007）。"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def _make_conn_factory(db_path):
    def _conn():
        c = sqlite3.connect(str(db_path))
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        return c
    return _conn


@pytest.fixture()
def merged_env(sample_db, tmp_path):
    works_dir = tmp_path / "works"
    out_dir = works_dir / "W-sample-001" / "parsed" / "mineru" / "SF-001"
    out_dir.mkdir(parents=True)
    (out_dir / "content.merged.md").write_text("# merged view\n\n![fig](images/a.png)", encoding="utf-8")
    (out_dir / "detail.json").write_text('{"schema_version": "4.0"}', encoding="utf-8")

    conn = sqlite3.connect(str(sample_db))
    conn.execute(
        "UPDATE literature_parse_runs SET status='succeeded', output_dir=? WHERE id='PR-001'",
        (str(out_dir),),
    )
    conn.commit()
    conn.close()

    import api.routes.files as files_mod
    files_mod.LIBRARY_ROOT = tmp_path
    files_mod._WORKS_ROOT = works_dir.resolve()
    factory = _make_conn_factory(sample_db)
    patches = [patch("api.routes.files.get_conn", factory)]
    for p in patches:
        p.start()
    yield {"out_dir": out_dir, "db": sample_db}
    for p in patches:
        p.stop()
    files_mod.LIBRARY_ROOT = Path(__file__).resolve().parents[1]
    files_mod._WORKS_ROOT = (files_mod.LIBRARY_ROOT / "works").resolve()


def test_merged_content_200(merged_env):
    r = client.get("/api/files/W-sample-001/merged")
    assert r.status_code == 200
    assert "# merged view" in r.text


def test_detail_json_200(merged_env):
    r = client.get("/api/files/W-sample-001/detail")
    assert r.status_code == 200
    assert r.json()["schema_version"] == "4.0"


def test_merged_missing_404(merged_env):
    (merged_env["out_dir"] / "content.merged.md").unlink()
    r = client.get("/api/files/W-sample-001/merged")
    assert r.status_code == 404


def test_detail_missing_404(merged_env):
    (merged_env["out_dir"] / "detail.json").unlink()
    r = client.get("/api/files/W-sample-001/detail")
    assert r.status_code == 404


def test_unknown_work_404(merged_env):
    assert client.get("/api/files/W-unknown/merged").status_code == 404
    assert client.get("/api/files/W-unknown/detail").status_code == 404


def test_multi_source_work_serves_latest_finished_run(merged_env):
    """回归：多源 work（两个 succeeded run）按 finished_at 取最新，
    而非 run id 字符串序——否则 v2 副本的合并资产会被旧 run 的空目录遮蔽。"""
    conn = sqlite3.connect(str(merged_env["db"]))
    # 造一个 id 字符串序更靠后、但完成时间更早的旧 run
    conn.execute(
        """INSERT INTO literature_parse_runs
           (id, work_id, source_file_id, status, finished_at, output_dir)
           VALUES ('PR-999-old', 'W-sample-001', 'SF-old', 'succeeded',
                   '2020-01-01T00:00:00+00:00', ?)""",
        (str(merged_env["out_dir"].parent / "SF-old"),),
    )
    conn.commit()
    conn.close()
    try:
        # sample_db 为 session 级共享：用例结束必须删行，避免污染其他测试的行数断言
        assert client.get("/api/files/W-sample-001/merged").status_code == 200
        assert "# merged view" in client.get("/api/files/W-sample-001/merged").text
    finally:
        conn = sqlite3.connect(str(merged_env["db"]))
        conn.execute("DELETE FROM literature_parse_runs WHERE id='PR-999-old'")
        conn.commit()
        conn.close()
