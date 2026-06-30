"""V1 healthcheck 不再依赖 parse_ledger.json，旧入口已归档。"""
from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path


def test_healthcheck_has_no_parse_ledger_check():
    hc = importlib.import_module("scripts.healthcheck_library")
    assert not hasattr(hc, "check_parse_ledger"), (
        "check_parse_ledger 应删除——ledger 已废弃，解析一致性由 healthcheck_library(DB) 覆盖"
    )


def test_legacy_literature_healthcheck_is_archived():
    assert importlib.util.find_spec("scripts.literature_healthcheck") is None
    archived = Path("scripts/_archive/literature_healthcheck.py")
    assert archived.exists(), "旧 healthcheck 应保留在 scripts/_archive/ 作为历史参考"
