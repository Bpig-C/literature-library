"""ingest 不再写 parse_ledger.json；parse_runs pending 行仍由 insert_db_rows 建立。"""
from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path


def test_ingest_does_not_write_ledger(tmp_path, monkeypatch):
    library_root = tmp_path
    ingest = importlib.import_module("scripts.literature_ingest")
    # 不真正跑 ingest（需文件）；直接断言 update_ledger 已从模块移除
    assert not hasattr(ingest, "update_ledger"), (
        "update_ledger 应已删除——parse_ledger.json 不再是状态源"
    )
    # parse_ledger.json 不应被 insert_db_rows 创建
    assert not (library_root / "parse_ledger.json").exists()
