"""
通过 HTTP 远程调用 MinerU 服务的解析客户端。
等价于 C++ PdfParseClient_web。
"""
import hashlib
import json
import logging
import shutil
import zipfile
from pathlib import Path
from config import config

import requests

from .base_client import ParseRequest, PdfParseClient

logger = logging.getLogger(__name__)


def _bool_to_str(value: bool) -> str:
    return "true" if value else "false"


def _normalize_lang_list(value) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else None
    if isinstance(value, (list, tuple, set)):
        items = [str(v).strip() for v in value if str(v).strip()]
        return items or None
    text = str(value).strip()
    return [text] if text else None


def _build_request_data(req: ParseRequest) -> dict:
    data = {
        "backend": req.backend,
        "parse_method": req.parse_method,
        "formula_enable": _bool_to_str(req.formula_enable),
        "table_enable": _bool_to_str(req.table_enable),
        "return_md": _bool_to_str(req.return_md),
        "return_middle_json": _bool_to_str(req.return_middle_json),
        "return_model_output": _bool_to_str(req.return_model_output),
        "return_content_list": _bool_to_str(req.return_content_list),
        "return_images": _bool_to_str(req.return_images),
        "response_format_zip": _bool_to_str(req.response_format_zip),
        "start_page_id": str(req.start_page_id),
        "end_page_id": str(req.end_page_id),
    }

    output_dir = req.output_dir if req.output_dir else req.pdf_path.parent
    if output_dir:
        data["output_dir"] = str(output_dir)

    lang_list = _normalize_lang_list(req.lang_list)
    if lang_list:
        data["lang_list"] = lang_list

    if req.server_url:
        data["server_url"] = req.server_url

    return data


def _flatten_multipart_data(data: dict) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for key, value in data.items():
        if isinstance(value, list):
            for item in value:
                items.append((key, str(item)))
        else:
            items.append((key, str(value)))
    return items


def _build_file_parse_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/file_parse"):
        return base
    return f"{base}/file_parse"


def _format_error_response(resp: requests.Response) -> str:
    try:
        error_body = resp.json()
        if isinstance(error_body, dict):
            error_text = (
                error_body.get("error")
                or error_body.get("message")
                or error_body.get("detail")
                or json.dumps(error_body, ensure_ascii=False)
            )
        else:
            error_text = json.dumps(error_body, ensure_ascii=False)
    except Exception:
        error_text = resp.text[:500]

    return f"Remote MinerU returned HTTP {resp.status_code}: {error_text}"


class WebClient(PdfParseClient):
    def __init__(self):
        self.share_dir =  config.share_dir

    @staticmethod
    def _build_sort_key(node, fallback_index: int) -> tuple:
        if not isinstance(node, dict):
            return (1, float("inf"), float("inf"), float("inf"), float("inf"), float("inf"), fallback_index)

        page_idx = node.get("page_idx")
        if not isinstance(page_idx, int):
            page_idx = float("inf")

        bbox = node.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            return (0, page_idx, float("inf"), float("inf"), float("inf"), float("inf"), fallback_index)

        try:
            x0, y0, x1, y1 = [float(v) for v in bbox]
        except (TypeError, ValueError):
            return (0, page_idx, float("inf"), float("inf"), float("inf"), float("inf"), fallback_index)

        return (0, page_idx, y0, x0, y1, x1, fallback_index)

    @staticmethod
    def _replace_image_refs(node, name_map: dict[str, str]):
        image_path_keys = {"img_path", "preview_img_path", "path"}

        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, str):
                    candidate = value.replace("\\", "/")
                    basename = Path(candidate).name
                    if basename in name_map and (
                        key in image_path_keys
                        or candidate.startswith("images/")
                        or candidate.startswith("/images/")
                    ):
                        node[key] = name_map[basename]
                else:
                    WebClient._replace_image_refs(value, name_map)
        elif isinstance(node, list):
            for item in node:
                WebClient._replace_image_refs(item, name_map)

    @staticmethod
    def _sort_and_sync_content_lists(content_list_path: Path, content_list_v2_path: Path | None):
        with content_list_path.open(encoding="utf-8") as handle:
            content_list = json.load(handle)

        if not isinstance(content_list, list):
            raise ValueError(f"{content_list_path} root must be a list")

        indexed_items = list(enumerate(content_list))
        indexed_items.sort(key=lambda item: WebClient._build_sort_key(item[1], item[0]))
        sorted_content_list = [item for _, item in indexed_items]

        content_list_path.write_text(
            json.dumps(sorted_content_list, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if content_list_v2_path is None or not content_list_v2_path.exists():
            return

        with content_list_v2_path.open(encoding="utf-8") as handle:
            content_list_v2 = json.load(handle)

        if not isinstance(content_list_v2, list):
            raise ValueError(f"{content_list_v2_path} root must be a list")

        flattened_v2 = []
        for page_nodes in content_list_v2:
            if isinstance(page_nodes, list):
                flattened_v2.extend(page_nodes)
            else:
                raise ValueError(f"{content_list_v2_path} must be a list[list]")

        if len(flattened_v2) != len(content_list):
            logger.warning(
                "Skip syncing %s with %s due to length mismatch: v1=%s v2=%s",
                content_list_path,
                content_list_v2_path,
                len(content_list),
                len(flattened_v2),
            )
            return

        sorted_v2_flat = [flattened_v2[index] for index, _ in indexed_items]
        page_count = max(
            [item.get("page_idx", -1) for item in sorted_content_list if isinstance(item, dict)] + [-1]
        ) + 1
        regrouped_v2 = [[] for _ in range(page_count)]
        for item_v1, item_v2 in zip(sorted_content_list, sorted_v2_flat):
            page_idx = item_v1.get("page_idx") if isinstance(item_v1, dict) else None
            if not isinstance(page_idx, int) or page_idx < 0:
                page_idx = 0
                if not regrouped_v2:
                    regrouped_v2.append([])
            while page_idx >= len(regrouped_v2):
                regrouped_v2.append([])
            regrouped_v2[page_idx].append(item_v2)

        content_list_v2_path.write_text(
            json.dumps(regrouped_v2, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    def _copy_pdf_2_share_dir(self, pdf_path: Path):
        pdf_path = Path(pdf_path).resolve()
        share_dir = Path(self.share_dir).resolve()

        share_dir.mkdir(parents=True, exist_ok=True)

        target_path = share_dir / pdf_path.name
        shutil.copy2(pdf_path, target_path)

        return target_path
    def _copy_original_file_2_share_dir(self, pdf_path: Path):
        self._copy_pdf_2_share_dir(pdf_path)

    def _copy_layout_pdf_2_share_dir(self, pdf_path: Path):
        self._copy_pdf_2_share_dir(pdf_path)
    def _copy_imgs_2_share_dir(self, img_folder):
        root_dir = Path(img_folder).resolve()
        if not root_dir.exists():
            logger.warning("Skip image post-process because path does not exist: %s", root_dir)
            return

        share_dir = Path(self.share_dir).resolve()
        share_dir.mkdir(parents=True, exist_ok=True)

        hash_str = hashlib.sha256(str(root_dir).encode("utf-8")).hexdigest()[:16]
        name_map: dict[str, str] = {}

        for images_dir in [p for p in root_dir.rglob("images") if p.is_dir()]:
            for image_path in images_dir.iterdir():
                if not image_path.is_file():
                    continue

                new_name = f"{hash_str}_{image_path.name}"
                target_path = share_dir / new_name

                if target_path.exists():
                    target_path.unlink()
                shutil.copy2(str(image_path), str(target_path))
                name_map[image_path.name] = new_name

        if not name_map:
            logger.info("No images directory found under %s", root_dir)

        v1_files = sorted(
            [
                path for path in root_dir.rglob("*.json")
                if path.is_file() and path.name.endswith("_content_list.json")
            ]
        )
        v2_lookup = {
            path.name.replace("_content_list_v2.json", ""): path
            for path in root_dir.rglob("*.json")
            if path.is_file() and path.name.endswith("_content_list_v2.json")
        }

        for content_list_path in v1_files:
            stem_prefix = content_list_path.name.replace("_content_list.json", "")
            content_list_v2_path = v2_lookup.get(stem_prefix)

            with content_list_path.open(encoding="utf-8") as handle:
                content_list = json.load(handle)
            self._replace_image_refs(content_list, name_map)
            content_list_path.write_text(
                json.dumps(content_list, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            if content_list_v2_path is not None:
                with content_list_v2_path.open(encoding="utf-8") as handle:
                    content_list_v2 = json.load(handle)
                self._replace_image_refs(content_list_v2, name_map)
                content_list_v2_path.write_text(
                    json.dumps(content_list_v2, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

            self._sort_and_sync_content_lists(content_list_path, content_list_v2_path)

    @staticmethod
    def _safe_extract_zip(zf: zipfile.ZipFile, extract_dir: Path) -> None:
        """逐文件解压 ZIP，防御路径穿越和 Windows 长路径限制。

        Python 3.12 的 pathlib 自带 longPathAware 清单，配合注册表
        LongPathsEnabled=1 可处理超长路径。此处逐文件解压主要是防
        止 ZIP Slip 路径穿越攻击（如 ``../../etc/passwd``）。
        """
        extract_dir = extract_dir.resolve()
        for member in zf.infolist():
            target = extract_dir / member.filename
            # 防御路径穿越：确保解压目标在 extract_dir 内
            if not str(target).startswith(str(extract_dir)):
                logger.warning("Skipping unsafe ZIP entry: %s", member.filename)
                continue
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)

    def parse_pdf(self, req: ParseRequest) -> tuple[bool, str]:

        if not config.mineru_server_url:
            msg = "❌ 远端 MinerU 地址未配置: config.mineru_server_url 为空"
            logger.error(msg)
            return False, msg

        request_data = _build_request_data(req)
        output_dir = (req.output_dir if req.output_dir else req.pdf_path.parent).resolve()
        file_output_dir = output_dir / req.pdf_path.stem
        file_output_dir.mkdir(parents=True, exist_ok=True)
        url = _build_file_parse_url(config.mineru_server_url)

        logger.info("Web MinerU POST %s, file=%s", url, req.pdf_path.name)

        with req.pdf_path.open("rb") as f:
            files = {"files": (req.pdf_path.name, f, "application/pdf")}
            try:
                resp = requests.post(
                    url,
                    data=_flatten_multipart_data(request_data),
                    files=files,
                    timeout=config.timeout,
                )
            except Exception as e:
                msg = f"❌ 远端 MinerU 请求异常: {e}"
                logger.error(msg)
                return False, msg

        if resp.status_code != 200:
            msg = _format_error_response(resp)
            logger.error(msg)
            return False, msg

        content_type = (resp.headers.get("Content-Type") or "").lower()

        try:
            if "application/zip" in content_type or "application/octet-stream" in content_type:
                zip_path = file_output_dir / f"{req.pdf_path.stem}_result.zip"
                zip_path.write_bytes(resp.content)
                logger.info("Saved zip: %s", zip_path)

                extract_dir = file_output_dir / "unzipped"
                with zipfile.ZipFile(zip_path, "r") as zf:
                    self._safe_extract_zip(zf, extract_dir)
                logger.info("Extracted to: %s", extract_dir)

                manifest_path = file_output_dir / "manifest.json"
                manifest_path.write_text(
                    json.dumps(
                        {
                            "content_type": content_type,
                            "zip_path": str(zip_path),
                            "extract_dir": str(extract_dir),
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )

                self._copy_imgs_2_share_dir(file_output_dir)


                msg = f"✅ 远端 MinerU 解析完成，输出目录: {file_output_dir}"
                return True, msg

            result = resp.json()
            result_json_path = file_output_dir / f"{req.pdf_path.stem}_result.json"
            result_json_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            if result.get("md") is not None:
                (file_output_dir / f"{req.pdf_path.stem}.md").write_text(
                    result.get("md", ""),
                    encoding="utf-8",
                )

            json_field_map = {
                "middle_json": f"{req.pdf_path.stem}_middle.json",
                "model_output": f"{req.pdf_path.stem}_model_output.json",
                "content_list": f"{req.pdf_path.stem}_content_list.json",
                "images": f"{req.pdf_path.stem}_images.json",
            }
            for field, filename in json_field_map.items():
                if result.get(field) is not None:
                    (file_output_dir / filename).write_text(
                        json.dumps(result[field], ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )

            self._copy_imgs_2_share_dir(file_output_dir)

        except Exception as e:
            msg = f"❌ 远端 MinerU 响应处理失败: {e}"
            logger.exception(msg)
            return False, msg

        msg = f"✅ 远端 MinerU 解析完成，输出目录: {file_output_dir}"
        return True, msg

    def is_parsed(self, folder_path: Path) -> bool:
        return self._check_parsed(folder_path)
