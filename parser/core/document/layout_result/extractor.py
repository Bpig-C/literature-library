"""
PdfiumLayoutExtractor stub。
当前返回空列表，预留 PyMuPDF 替换接口。

后续替换方式：
    在 extract_layout_json 内实现 fitz.open(pdf_file_path) 逻辑即可，
    调用方（artifact_generator.py）无需修改。

接口约定（每个元素的字段）：
    page_no   : int   — 页码（0-based）
    bbox      : list  — [x0, y0, x1, y1]，坐标单位与 MinerU content_list 一致
    text      : str   — 该区域的文本内容
    style     : dict  — 字体、字号等样式信息（可为 {}）
    link      : str   — 超链接 URL（可为 ""）
    position  : str   — 布局位置描述（可为 ""）
"""
from pathlib import Path
class PdfiumLayoutExtractor:

    @staticmethod
    def extract_layout_json(pdf_file_path: Path) -> list[dict]:
        # TODO: 替换为 PyMuPDF (fitz) 实现
        return []
