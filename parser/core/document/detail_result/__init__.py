from pathlib import Path

from .get_layout import extract_pdf_content_layout
from .merge import merged


def _find_first_file(root: Path, name: str) -> Path | None:
    if not root.exists():
        return None
    for path in root.rglob(name):
        if path.is_file():
            return path
    return None


def build_detail_pdf_for_pdf(pdf_path: Path) -> dict:
    pdf_blocks = extract_pdf_content_layout(str(pdf_path))
    content_list_path = _find_first_file(pdf_path.parent, pdf_path.stem + "_content_list.json")
    content_list_V2_path = _find_first_file(pdf_path.parent, pdf_path.stem + "_content_list_v2.json")
    model_path = _find_first_file(pdf_path.parent, pdf_path.stem + "_model.json")

    if content_list_path is None:
        raise FileNotFoundError(f"Cannot locate content list JSON for: {pdf_path}")
    return merged(str(pdf_path), content_list_V2_path , content_list_path ,model_path , pdf_blocks)

__all__ = ["build_detail_pdf_for_pdf"]
