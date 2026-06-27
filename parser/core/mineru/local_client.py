"""
本地命令行调用 MinerU 的解析客户端。
等价于 C++ PdfParseClient_local。
"""
import logging
import os
import subprocess
from pathlib import Path

from .base_client import ParseRequest, PdfParseClient

logger = logging.getLogger(__name__)


class LocalClient(PdfParseClient):

    def parse_pdf(self, req: ParseRequest) -> tuple[bool, str]:
        output_dir = req.output_dir if req.output_dir else req.pdf_path.parent

        cmd = [
            "mineru",
            "-p", str(req.pdf_path),
            "-o", str(output_dir),
            "-b", req.backend,
            "-m", req.parse_method,
            "-l", req.lang_list,
            "-f", str(req.formula_enable).lower(),
            "-t", str(req.table_enable).lower(),
        ]

        env = {**os.environ, "MINERU_MODEL_SOURCE": "local"}

        logger.info("Local MinerU cmd: %s", " ".join(cmd))

        try:
            from config import config
            timeout = config.timeout
        except Exception:
            timeout = 1200

        result = subprocess.run(
            cmd, env=env, capture_output=True, text=True, timeout=timeout
        )

        if result.returncode == 0:
            msg = f"✅ 本地 MinerU 解析完成，输出目录: {output_dir}"
            logger.info(msg)
            return True, msg
        else:
            msg = (
                f"❌ 本地 MinerU 命令执行失败，返回码: {result.returncode}\n"
                f"{result.stderr or result.stdout}"
            )
            logger.error(msg)
            return False, msg

    def is_parsed(self, folder_path: Path) -> bool:
        return self._check_parsed(folder_path)
