"""healthcheck 不再依赖 parse_ledger.json。"""
from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path


def test_healthcheck_has_no_parse_ledger_check():
    hc = importlib.import_module("scripts.literature_healthcheck")
    assert not hasattr(hc, "check_parse_ledger"), (
        "check_parse_ledger 应删除——ledger 已废弃，解析一致性由 check_content_md(DB) 覆盖"
    )


def test_healthcheck_output_has_no_ledger_key(tmp_path):
    hc = importlib.import_module("scripts.literature_healthcheck")
    # 无 parse_ledger.json 也不应报错/不应含 parse_ledger 键
    if hasattr(hc, "run_all"):
        result = hc.run_all() if callable(getattr(hc, "run_all", None)) else None
        # 若 run_all 存在：断言结果无 parse_ledger 键
        if isinstance(result, dict):
            assert "parse_ledger" not in result, (
                "run_all 结果不应再含 parse_ledger 键"
            )
