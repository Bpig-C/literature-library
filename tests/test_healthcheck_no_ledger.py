"""healthcheck 不再依赖 parse_ledger.json。"""
from __future__ import annotations

import importlib


def test_healthcheck_has_no_parse_ledger_check():
    hc = importlib.import_module("scripts.literature_healthcheck")
    assert not hasattr(hc, "check_parse_ledger"), (
        "check_parse_ledger 应删除——ledger 已废弃，解析一致性由 check_content_md(DB) 覆盖"
    )
