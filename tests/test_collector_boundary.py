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
