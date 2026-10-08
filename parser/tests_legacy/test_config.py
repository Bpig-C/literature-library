"""
单元测试 1：配置加载
不依赖任何外部服务，直接验证 conf.json 解析是否正确。
运���：pytest tests/test_config.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import Config


def test_load_defaults():
    cfg = Config.load()
    assert cfg.server_ip == "127.0.0.1"
    assert cfg.server_port == 18201
    assert cfg.mineru_server_port == 18200
    assert cfg.mineru_server_url == "http://127.0.0.1:18200/file_parse"
    assert isinstance(cfg.localcommand_mineru, bool)
    assert cfg.timeout > 0


def test_mineru_url_env_override(monkeypatch):
    monkeypatch.setenv("MINERU_SERVER_URL", "http://mineru.example/file_parse")
    cfg = Config.load()
    assert cfg.mineru_server_url == "http://mineru.example/file_parse"


def test_parse_request_fields():
    cfg = Config.load()
    assert cfg.parse_method in ("auto", "txt", "ocr")
    assert cfg.parse_start_page_id == 0
    assert cfg.parse_end_page_id > 0
    assert isinstance(cfg.parse_table_enable, bool)
    assert isinstance(cfg.parse_formula_enable, bool)


def test_libreoffice_config():
    cfg = Config.load()
    # path 可以不存在，但字段本身应该有值
    assert isinstance(cfg.libreoffice_path, str)
    assert isinstance(cfg.libreoffice_extra_args, list)
