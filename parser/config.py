"""
配置加载模块，从 conf.json 读取配置，映射为 Config dataclass。
忽略 conf.json 中键名包含 "注释" 的字段，并支持环境变量覆盖敏感配置。
"""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_api_keys(value: str) -> dict[str, str]:
    clients: dict[str, str] = {}
    for item in _split_csv(value):
        if "=" not in item:
            continue
        client_id, api_key = item.split("=", 1)
        client_id = client_id.strip()
        api_key = api_key.strip()
        if client_id and api_key:
            clients[client_id] = api_key
    return clients


def _build_mineru_url(server_url: str, server_ip: str, server_port: int) -> str:
    if server_url:
        return server_url
    host = server_ip or "127.0.0.1"
    return f"http://{host}:{server_port}/file_parse"


@dataclass
class Config:
    # server
    server_ip: str = "127.0.0.1"
    server_port: int = 18201
    server_url: str = ""
    max_request_body: int = 50 * 1024 * 1024
    share_dir: Path = Path("./Datas")
    api_clients: dict[str, str] = field(default_factory=lambda: {"test_client": "test_key"})
    cors_origins: list[str] = field(default_factory=lambda: [
        "http://localhost",
        "http://localhost:3000",
        "http://127.0.0.1",
        "http://127.0.0.1:3000",
    ])
    expose_datas_static: bool = False

    # mineru
    localcommand_mineru: bool = True
    mineru_server_ip: str = ""
    mineru_server_url: str = ""
    mineru_server_port: int = 18200
    timeout: int = 1200
    mineru_worker_count: int = 4
    # 解析后端选择：cloud（官网精准 API）/ selfdeploy（走 mineru_server_url 的 WebClient）
    # selfdeploy 相关字段仅当 backend=selfdeploy 时启用。
    mineru_backend: str = "cloud"
    # 官网精准解析 API 配置（token 强制走环境变量 MinerU_API_KEY，不在此落盘）
    cloud: dict = field(default_factory=lambda: {
        "api_base": "https://mineru.net",
        "model_version": "pipeline",
        "language": "en",
        "is_ocr_auto": True,
        "poll_interval": 10,
        "timeout": 1800,
        "submit_rate_per_min": 30,
    })

    # parse_request
    parse_return_middle_json: bool = True
    parse_return_model_output: bool = True
    parse_return_md: bool = True
    parse_return_images: bool = True
    parse_return_content_list: bool = True
    parse_start_page_id: int = 0
    parse_end_page_id: int = 99999
    parse_method: str = "auto"
    parse_lang_list: str = "ch"
    parse_output_dir: str = "./output"
    parse_server_url: str = ""
    parse_backend: str = "pipeline"
    parse_table_enable: bool = True
    parse_formula_enable: bool = True
    parse_response_format_zip: bool = True

    # libreoffice
    libreoffice_path: str = "libreoffice"
    libreoffice_extra_args: List[str] = field(default_factory=list)

    @property
    def uploads_dir(self) -> Path:
        return self.share_dir / "uploads"

    @staticmethod
    def load(conf_path: str | None = None) -> "Config":
        if conf_path is None:
            conf_path = str(Path(__file__).parent / "conf.json")

        with open(conf_path, encoding="utf-8-sig") as f:
            raw = json.load(f)

        def clean(obj):
            if isinstance(obj, dict):
                return {k: clean(v) for k, v in obj.items() if "注释" not in k}
            return obj

        data = clean(raw)
        srv = data.get("server", {})
        mnu = data.get("mineru", {})
        pr = data.get("parse_request", {})
        lo = data.get("libreoffice", {})

        api_clients = srv.get("api_clients", {"test_client": "test_key"})
        env_api_clients = os.getenv("DOC_PARSER_API_KEYS", "")
        if env_api_clients:
            api_clients = _parse_api_keys(env_api_clients)

        cors_origins = srv.get("cors_origins", [
            "http://localhost",
            "http://localhost:3000",
            "http://127.0.0.1",
            "http://127.0.0.1:3000",
        ])
        env_cors_origins = os.getenv("DOC_PARSER_CORS_ORIGINS", "")
        if env_cors_origins:
            cors_origins = _split_csv(env_cors_origins)

        share_dir = os.getenv("DOC_PARSER_SHARE_DIR", srv.get("share_dir", "./Datas"))

        mineru_server_ip = mnu.get("ip", "")
        mineru_server_port = int(mnu.get("port", 18200))
        mineru_server_url = os.getenv("MINERU_SERVER_URL", mnu.get("url", ""))

        # 后端选择：cloud（官网精准 API，默认） / selfdeploy（本地或远程自部署 MinerU）
        mineru_backend = os.getenv("MINERU_BACKEND", mnu.get("backend", "cloud")).strip().lower()
        if mineru_backend not in ("cloud", "selfdeploy"):
            mineru_backend = "cloud"
        cloud_cfg = mnu.get("cloud", {}) or {}
        # 语言默认英文论文；允许环境变量覆盖
        cloud_cfg.setdefault("api_base", "https://mineru.net")
        cloud_cfg.setdefault("model_version", os.getenv("MINERU_MODEL_VERSION", "pipeline"))
        cloud_cfg.setdefault("language", os.getenv("MINERU_LANGUAGE", "en"))
        cloud_cfg.setdefault("is_ocr_auto", True)
        cloud_cfg.setdefault("poll_interval", 10)
        cloud_cfg.setdefault("timeout", 1800)
        cloud_cfg.setdefault("submit_rate_per_min", 30)

        return Config(
            server_ip=os.getenv("DOC_PARSER_HOST", srv.get("ip", "127.0.0.1")),
            server_port=int(os.getenv("DOC_PARSER_PORT", srv.get("port", 18201))),
            server_url=srv.get("url", ""),
            share_dir=Path(share_dir),
            api_clients=api_clients,
            cors_origins=cors_origins,
            expose_datas_static=bool(srv.get("expose_datas_static", False)),

            localcommand_mineru=bool(mnu.get("localcommand_mineru", True)),
            mineru_server_ip=mineru_server_ip,
            mineru_server_url=_build_mineru_url(mineru_server_url, mineru_server_ip, mineru_server_port),
            mineru_server_port=mineru_server_port,
            timeout=int(mnu.get("timeout", 1200)),
            mineru_worker_count=int(mnu.get("mineru_worker_count", 4)),
            mineru_backend=mineru_backend,
            cloud=cloud_cfg,

            parse_return_middle_json=bool(pr.get("return_middle_json", True)),
            parse_return_model_output=bool(pr.get("return_model_output", True)),
            parse_return_md=bool(pr.get("return_md", True)),
            parse_return_images=bool(pr.get("return_images", True)),
            parse_return_content_list=bool(pr.get("return_content_list", True)),
            parse_start_page_id=int(pr.get("start_page_id", 0)),
            parse_end_page_id=int(pr.get("end_page_id", 99999)),
            parse_method=pr.get("parse_method", "auto"),
            parse_lang_list=pr.get("lang_list", "ch"),
            parse_output_dir=pr.get("output_dir", "./output"),
            parse_server_url=pr.get("server_url", ""),
            parse_backend=os.getenv("MINERU_PARSE_BACKEND", pr.get("backend", "pipeline")),
            parse_table_enable=bool(pr.get("table_enable", True)),
            parse_formula_enable=bool(pr.get("formula_enable", True)),
            parse_response_format_zip=bool(pr.get("response_format_zip", True)),

            libreoffice_path=lo.get("path", "libreoffice"),
            libreoffice_extra_args=lo.get("extra_args", []),
        )


config = Config.load()



