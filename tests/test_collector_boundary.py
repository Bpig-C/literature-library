# tests/test_collector_boundary.py
import re
from pathlib import Path

COLLECTOR_DIR = Path(__file__).resolve().parents[1] / "collector"

def _collector_py_files():
    if not COLLECTOR_DIR.exists():
        return []
    return list(COLLECTOR_DIR.rglob("*.py"))

def test_collector_never_directly_inserts_into_works():
    """collector 包内不得出现 'INSERT INTO works' 或 'REPLACE INTO works'。
    晋升必须经 ingest_bridge -> literature_ingest。"""
    offenders = []
    pat = re.compile(r"INSERT\s+INTO\s+works|REPLACE\s+INTO\s+works", re.IGNORECASE)
    for f in _collector_py_files():
        text = f.read_text(encoding="utf-8")
        if pat.search(text):
            offenders.append(str(f))
    assert not offenders, f"collector 直接写 works（违反边界）: {offenders}"

def test_replace_source_only_updates_read_status():
    """replace_source 对 works 的写只能是 read_status 恢复。"""
    f = COLLECTOR_DIR / "replace_source.py"
    if not f.exists():
        return
    text = f.read_text(encoding="utf-8")
    updates = re.findall(r"UPDATE\s+works\s+SET\s+(\w+)", text, re.IGNORECASE)
    assert all(col.lower() == "read_status" for col in updates), \
        f"replace_source 写了 works 非 read_status 列: {updates}"

def test_direct_db_writes_only_in_replace_source():
    """除 ingest_bridge 经 ingest pipeline 外，collector 对 source_files / work_codes 的
    直写只允许出现在 replace_source.py（needs_better_copy 的受控豁免）。这让该架构例外
    可审计，而非隐藏。"""
    write_pat = re.compile(
        r"INSERT\s+INTO\s+source_files|UPDATE\s+source_files|"
        r"DELETE\s+FROM\s+work_codes|INSERT\s+INTO\s+work_codes",
        re.IGNORECASE)
    allowed = {"replace_source.py"}
    offenders = []
    for f in _collector_py_files():
        text = f.read_text(encoding="utf-8")
        if write_pat.search(text) and f.name not in allowed:
            offenders.append(f.name)
    assert not offenders, f"collector 在 replace_source 之外直写 source_files/work_codes: {offenders}"
