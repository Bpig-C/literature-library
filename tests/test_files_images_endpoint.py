"""/files/{work_id}/images/{name} 解析产物图片端点测试（UX-002 断点3）。

用 sample_db + 临时 works 目录验证：
- 正常图片 200 + 正确 media type + 字节一致；
- 文件名穿越/非法字符 → 404；
- DB 中 output_dir 指向 works 之外（投毒）→ 403；
- 无 parse run / 无 output_dir → 404。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)

PNG_BYTES = b"\x89PNG\r\n\x1a\n fake-image-bytes"


def _make_conn_factory(db_path):
    def _conn():
        c = sqlite3.connect(str(db_path))
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        return c
    return _conn


@pytest.fixture()
def images_env(sample_db, tmp_path):
    works_dir = tmp_path / "works"
    img_dir = works_dir / "W-sample-001" / "parsed" / "mineru" / "SF-001" / "images"
    img_dir.mkdir(parents=True)
    (img_dir / "p001-x7.png").write_bytes(PNG_BYTES)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.png").write_bytes(b"SECRET")

    def _set_run(output_dir: str | None):
        conn = sqlite3.connect(str(sample_db))
        conn.execute(
            "UPDATE literature_parse_runs SET status='succeeded', output_dir=? WHERE id='PR-001'",
            (output_dir,),
        )
        conn.commit()
        conn.close()

    _set_run(str(img_dir.parent))

    import api.routes.files as files_mod
    files_mod.LIBRARY_ROOT = tmp_path
    files_mod._WORKS_ROOT = works_dir.resolve()

    factory = _make_conn_factory(sample_db)
    patches = [patch("api.routes.files.get_conn", factory)]
    for p in patches:
        p.start()
    yield {"img_dir": img_dir, "outside": outside, "set_run": _set_run, "db": sample_db}
    for p in patches:
        p.stop()
    files_mod.LIBRARY_ROOT = Path(__file__).resolve().parents[1]
    files_mod._WORKS_ROOT = (files_mod.LIBRARY_ROOT / "works").resolve()


def test_serve_parsed_image_200(images_env):
    r = client.get("/api/files/W-sample-001/images/p001-x7.png")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert r.content == PNG_BYTES


def test_missing_image_404(images_env):
    r = client.get("/api/files/W-sample-001/images/nope.png")
    assert r.status_code == 404


def test_traversal_name_404(images_env):
    r = client.get("/api/files/W-sample-001/images/..%2Fcontent.md")
    assert r.status_code == 404
    r2 = client.get("/api/files/W-sample-001/images/..")
    assert r2.status_code == 404


def test_poisoned_output_dir_outside_works_403(images_env):
    images_env["set_run"](str(images_env["outside"]))
    r = client.get("/api/files/W-sample-001/images/secret.png")
    assert r.status_code == 403


def test_work_without_run_404(images_env):
    r = client.get("/api/files/W-unknown/images/p001-x7.png")
    assert r.status_code == 404


def test_run_without_output_dir_falls_back_to_content_md_parent(images_env):
    """output_dir 为空时，回退用 content_md_path 的父目录定位 images/。"""
    conn = sqlite3.connect(str(images_env["db"]))
    conn.execute(
        "UPDATE literature_parse_runs SET output_dir='', content_md_path=? WHERE id='PR-001'",
        (str(images_env["img_dir"].parent / "content.md"),),
    )
    conn.commit()
    conn.close()
    r = client.get("/api/files/W-sample-001/images/p001-x7.png")
    assert r.status_code == 200
    assert r.content == PNG_BYTES
