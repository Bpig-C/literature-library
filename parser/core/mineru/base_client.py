"""
PdfParseClient 抽象基类。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ParseRequest:
    pdf_path: Path
    output_dir: Optional[Path] = None          # 输出目录（None 时用 pdf_path.parent）
    return_middle_json: bool = True
    return_model_output: bool = True
    return_md: bool = True
    return_images: bool = True
    return_content_list: bool = True
    start_page_id: int = 0
    end_page_id: int = 99999
    parse_method: str = "auto"
    lang_list: str = "ch"
    server_url: str = ""
    backend: str = "hybrid-auto-engine"
    table_enable: bool = True
    formula_enable: bool = True
    response_format_zip: bool = True


class PdfParseClient(ABC):

    @abstractmethod
    def parse_pdf(self, req: ParseRequest) -> tuple[bool, str]:
        """解析 PDF，返回 (success, message)。"""

    @abstractmethod
    def is_parsed(self, folder_path: Path) -> bool:
        """检查指定目录是否已包含解析结果（存在 .json 文件即视为已解析）。"""

    def _check_parsed(self, folder_path: Path) -> bool:
        """通用实现：目录下存在任意 .json 文件即视为已解析。"""
        if not folder_path.exists():
            return False
        for p in folder_path.rglob("*.json"):
            return True
        return False
