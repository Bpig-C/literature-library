"""
文件转 PDF 模块。
支持 Office 文档（.docx/.xlsx/.pptx/.odt 等）通过 LibreOffice 转换，
HTML 文件通过 Chrome headless 转换。
"""
import logging
import subprocess
import shutil
from pathlib import Path
from typing import Optional

from config import config

logger = logging.getLogger(__name__)

# Office 格式扩展名集合
_OFFICE_EXTS = {
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".odt", ".ods", ".odp", ".rtf", ".csv",".wps"
}
_HTML_EXTS = {".html", ".htm"}


class Convert2PDF:

    @staticmethod
    def convert(file_path: Path) -> Path:
        """统一转换接口：根据文件类型选择转换路径，返回 PDF 路径。
        若已是 PDF 则直接返回原路径。"""
        ext = file_path.suffix.lower()
        if ext == ".pdf":
            return file_path
        if ext in _OFFICE_EXTS:
            return Convert2PDF.office_to_pdf(file_path)
        if ext in _HTML_EXTS:
            return Convert2PDF.html_to_pdf(file_path)
        raise ValueError(f"Unsupported file type for conversion: {ext}")

    @staticmethod
    def office_to_pdf(office_path: Path, output_dir: Optional[Path] = None) -> Path:
        """通过 LibreOffice 将 Office 文件转换为 PDF。"""
        if output_dir is None:
            output_dir = office_path.parent

        lo_path = Convert2PDF._resolve_libreoffice_bin()
        cmd = [
            lo_path,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_dir),
            str(office_path),
        ]

        if config.libreoffice_extra_args:
            cmd.extend(config.libreoffice_extra_args)

        logger.info("LibreOffice convert: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(
                f"LibreOffice conversion failed (rc={result.returncode}): "
                f"{result.stderr or result.stdout}"
            )

        pdf_path = output_dir / (office_path.stem + ".pdf")
        if not pdf_path.exists():
            raise FileNotFoundError(
                f"LibreOffice did not produce expected PDF: {pdf_path}"
            )
        logger.info("Office -> PDF: %s", pdf_path)
        return pdf_path

    @staticmethod
    def _resolve_libreoffice_bin() -> str:
        """优先使用配置的 libreoffice_path，否则回退到系统命令。"""
        candidates = []
        if config.libreoffice_path:
            candidates.append(config.libreoffice_path)
        candidates.extend(["libreoffice", "soffice"])

        for candidate in candidates:
            if Path(candidate).exists():
                return candidate
            resolved = shutil.which(candidate)
            if resolved:
                return resolved

        raise RuntimeError(
            "LibreOffice executable not found. "
            "Please install libreoffice globally or configure libreoffice.path."
        )

    @staticmethod
    def html_to_pdf(html_path: Path, output_path: Optional[Path] = None) -> Path:
        """通过 Chrome headless 将 HTML 转换为 PDF。"""
        if output_path is None:
            output_path = html_path.with_suffix(".pdf")

        chrome_candidates = [
            "./third_party/chrome-linux64/chrome",
            "google-chrome", "chromium", "chromium-browser",
        ]
        chrome_bin = None
        for c in chrome_candidates:
            if Path(c).exists() or _which(c):
                chrome_bin = c
                break

        if chrome_bin is None:
            raise RuntimeError("Chrome/Chromium not found for HTML->PDF conversion")

        cmd = [
            chrome_bin,
            "--headless", "--no-sandbox", "--disable-gpu",
            f"--print-to-pdf={output_path}",
            str(html_path.resolve().as_uri()),
        ]

        logger.info("Chrome headless convert: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode != 0:
            raise RuntimeError(
                f"Chrome conversion failed (rc={result.returncode}): "
                f"{result.stderr or result.stdout}"
            )
        if not output_path.exists():
            raise FileNotFoundError(f"Chrome did not produce PDF: {output_path}")

        logger.info("HTML -> PDF: %s", output_path)
        return output_path


def _which(name: str) -> bool:
    """简单检查 PATH 中是否存在可执行文件。"""
    import shutil
    return shutil.which(name) is not None
