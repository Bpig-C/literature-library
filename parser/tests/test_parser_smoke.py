"""Smoke tests: parser core modules importable without external deps."""

import sys
from pathlib import Path

PARSER_ROOT = Path(__file__).resolve().parents[1]
if str(PARSER_ROOT) not in sys.path:
    sys.path.insert(0, str(PARSER_ROOT))


def test_config_loads():
    from config import Config
    cfg = Config.load()
    assert cfg.server_port > 0


def test_router_map_language():
    from core.mineru.router import map_mineru_language
    assert map_mineru_language("zh") == "ch"
    assert map_mineru_language("en") == "en"
    assert map_mineru_language("") == "en"
    assert map_mineru_language("Chinese") == "ch"
