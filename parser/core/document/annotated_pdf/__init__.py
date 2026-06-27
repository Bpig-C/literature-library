import base64
from pathlib import Path
from config import config
from .ge_layout_pdf import ge_layout_pdf
import shutil
from datetime import datetime

def _find_first_file(root: Path, name: str) -> Path | None:
    if not root.exists():
        return None
    for path in root.rglob(name):
        if path.is_file():
            return path
    return None




def _copy_pdf_2_share_dir(pdf_path: Path) -> Path:
    share_dir = Path(config.share_dir).resolve()
    share_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target_name = f"{timestamp}_{pdf_path.name}"
    target_path = share_dir / target_name

    shutil.copy2(pdf_path, target_path)
    return  target_name
    

def _copy_annotated_pdf_2_share_dir(pdf_path: Path):
    return _copy_pdf_2_share_dir(pdf_path)

def build_annotated_file_for_pdf(pdf_path: Path) -> dict:
    annotated_name = pdf_path.stem + "_layout.pdf"
    annotated_path = _find_first_file(pdf_path.parent, annotated_name)
    cache =  True
    result = {
        "file_name": annotated_name,
        "file_type": "pdf",
        "success": False,
        "file_base64": "",
    }

    if annotated_path is None:
        cache =  False
        content_list_name = pdf_path.stem + "_content_list.json"
        content_list_path = _find_first_file(pdf_path.parent, content_list_name)
        if content_list_path is None:
            return  False, result

        ge_layout_pdf(pdf_path, content_list_path)
        annotated_path = _find_first_file(pdf_path.parent, annotated_name)


        if annotated_path is None:
            return  False, result
        
        
        

    result["file_name"] = _copy_pdf_2_share_dir(pdf_path)
    result["annotated_file_name"] = _copy_annotated_pdf_2_share_dir(annotated_path)
    result["success"] = True
    result["file_base64"] = base64.b64encode(annotated_path.read_bytes()).decode()
    return  cache, result

__all__ = ["build_annotated_file_for_pdf"]
