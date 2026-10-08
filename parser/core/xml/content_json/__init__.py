import json
from pathlib import Path
def read_content_result(file_path: str) -> dict:
    file_json = Path(file_path).with_suffix(".json")
    with open(file_json, "r", encoding="utf-8") as f:
        return json.load(f)