"""
MinerU 官网「精准解析 API」客户端（cloud 后端）。

通过 https://mineru.net 的批量预签名上传接口解析本地 PDF：
  1. POST /api/v4/file-urls/batch  申请上传链接（返回 batch_id + file_urls）
  2. PUT  <file_urls[0]>            上传文件（不要设 Content-Type，系统自动提交解析）
  3. GET   /api/v4/extract-results/batch/{batch_id}  轮询直到 done/failed
  4. 下载 full_zip_url → 安全解压 → full.md 作为 content.md、content_list.json 作为 content.json

实现与 LocalClient/WebClient 相同的 PdfParseClient.parse_pdf(req)->(bool,msg) 接口，
可被 mineru_op 调度，也可被 scripts/literature_batch_parse.py 进程内直连调用。

鉴权：token 从环境变量读取（MinerU_API_KEY 优先，MINERU_API_TOKEN 兼容），
以 "Bearer <token>" 发送；不在代码或配置中硬编码 token。
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any

import requests

from .base_client import ParseRequest, PdfParseClient

logger = logging.getLogger(__name__)

# 终态：不再继续轮询
_TERMINAL_STATES = {"done", "failed"}
# 官网 model_version 取值
_VALID_MODEL_VERSIONS = {"pipeline", "vlm", "MinerU-HTML"}
# data_id 允许字符（官方：大小写字母、数字、_、-、.，≤128）
_DATA_ID_RE = re.compile(r"[^A-Za-z0-9_.\-]")


def _load_token() -> str:
    import os
    return (
        os.getenv("MinerU_API_KEY")
        or os.getenv("MINERU_API_TOKEN")
        or ""
    )


def _sanitize_data_id(raw: str) -> str:
    """把任意字符串规整成官方 data_id 合法形式（≤128 字符）。"""
    cleaned = _DATA_ID_RE.sub("-", raw)[:128]
    return cleaned or "doc"


def _normalize_language(value: Any) -> str:
    """ParseRequest.lang_list 可能是 'ch'/'en' 或列表；API 需要单个字符串。"""
    if isinstance(value, (list, tuple, set)):
        items = [str(v).strip() for v in value if str(v).strip()]
        return items[0] if items else "ch"
    text = str(value or "").strip()
    return text or "ch"


def _detect_is_ocr(pdf_path: Path, threshold_chars_per_page: int = 50) -> bool:
    """探测 PDF 是否缺少文本层（疑似扫描件），决定是否开启 OCR。

    平均每页可提取文本字符低于阈值 → 视为扫描件，is_ocr=True。
    用 PyMuPDF（fitz）；不可用时安全回落到 False。
    """
    try:
        import fitz  # PyMuPDF
    except Exception:
        logger.debug("PyMuPDF 不可用，is_ocr 探测回落为 False")
        return False
    try:
        doc = fitz.open(str(pdf_path))
        pages = doc.page_count or 1
        total = sum(len(page.get_text() or "") for page in doc)  # type: ignore[attr-defined]
        doc.close()
    except Exception as exc:
        logger.debug("is_ocr 探测失败：%s，回落 False", exc)
        return False
    avg = total / max(pages, 1)
    logger.info("OCR 探测：%s 页均 %d 字符 -> is_ocr=%s", pdf_path.name, int(avg), avg < threshold_chars_per_page)
    return avg < threshold_chars_per_page


def _extract_json_from_text(text: str) -> dict | None:
    """从可能带 ```json fence 或前后噪声的文本中提取首个 JSON 对象。"""
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        try:
            return json.loads(fence.group(1))
        except Exception:
            pass
    brace = re.search(r"\{.*\}", text, re.S)
    if brace:
        try:
            return json.loads(brace.group(0))
        except Exception:
            return None
    return None


class CloudClient(PdfParseClient):
    """官网精准解析 API 客户端。"""

    def __init__(self):
        from config import config
        self._config = config
        # 最近一次解析的 batch_id（供调用方记录为 task_id，便于回溯/重试）
        self.last_batch_id = ""
        cloud = getattr(config, "cloud", {}) or {}
        self.api_base = (cloud.get("api_base") or "https://mineru.net").rstrip("/")
        self.model_version = cloud.get("model_version", "vlm")
        self.language = cloud.get("language", "en")
        self.is_ocr_auto = bool(cloud.get("is_ocr_auto", True))
        self.poll_interval = int(cloud.get("poll_interval", 10))
        self.timeout = int(cloud.get("timeout", 1800))
        self.submit_rate_per_min = int(cloud.get("submit_rate_per_min", 30))
        self._min_submit_gap = (60.0 / self.submit_rate_per_min) if self.submit_rate_per_min else 0
        self._last_submit = 0.0

    # ---- 内部 HTTP 工具 ----
    def _headers(self) -> dict[str, str]:
        token = _load_token()
        if not token:
            raise RuntimeError("MinerU API token 未配置（环境变量 MinerU_API_KEY 为空）")
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }

    def _apply_rate_limit(self) -> None:
        if self._min_submit_gap <= 0:
            return
        wait = self._min_submit_gap - (time.time() - self._last_submit)
        if wait > 0:
            time.sleep(wait)
        self._last_submit = time.time()

    def _request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        """带指数退避的请求；对队列满(-60009)/网络错重试，对日上限(-60018)/token 错不重试。"""
        attempts = kwargs.pop("retries", 3)
        last_exc: Exception | None = None
        for i in range(attempts):
            try:
                resp = requests.request(method, url, timeout=kwargs.pop("timeout", 120), **kwargs)
            except Exception as exc:
                last_exc = exc
                logger.warning("请求异常 (%s/%s)：%s", i + 1, attempts, exc)
                time.sleep(2 ** i)
                continue
            # 识别业务层限流码（响应体里 code != 0）
            code = self._safe_code(resp)
            if code == -60009:  # 任务提交队列已满 → 退避重试
                logger.warning("队列已满，退避重试 (%s/%s)", i + 1, attempts)
                time.sleep(2 ** i)
                continue
            if code == -60018:  # 每日解析任务数已达上限 → 明确不重试，直接返回（由上层判失败）
                logger.error("每日解析任务数已达上限（-60018），不重试")
                return resp
            return resp
        raise RuntimeError(f"请求多次失败：{url} last_error={last_exc}")

    @staticmethod
    def _safe_code(resp: requests.Response) -> int | None:
        try:
            data = resp.json()
            if isinstance(data, dict):
                return data.get("code")
        except Exception:
            return None
        return None

    # ---- 主流程 ----
    def parse_pdf(self, req: ParseRequest) -> tuple[bool, str]:
        output_dir = (req.output_dir if req.output_dir else req.pdf_path.parent).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = req.pdf_path.stem

        if not req.pdf_path.exists():
            return False, f"源文件不存在：{req.pdf_path}"

        # 1. 申请上传链接
        try:
            self._apply_rate_limit()
            batch_id, upload_url = self._create_batch(req)
        except Exception as exc:
            msg = f"申请上传链接失败：{exc}"
            logger.error(msg)
            return False, msg
        logger.info("cloud: batch_id=%s file=%s", batch_id, req.pdf_path.name)

        # 2. 上传文件（不设 Content-Type）
        try:
            self._upload_file(upload_url, req.pdf_path)
        except Exception as exc:
            msg = f"文件上传失败：{exc}"
            logger.error(msg)
            return False, msg

        # 3. 轮询结果
        try:
            result = self._poll_batch(batch_id, file_name=req.pdf_path.name)
        except Exception as exc:
            msg = f"轮询失败：{exc}"
            logger.error(msg)
            return False, msg

        state = result.get("state")
        if state != "done":
            err = result.get("err_msg") or f"state={state}"
            return False, f"解析未完成：{err}"

        zip_url = result.get("full_zip_url")
        if not zip_url:
            return False, "done 但缺少 full_zip_url"

        # 4. 下载 + 解压 + 产出 content.md / content.json
        try:
            self._materialize(zip_url, output_dir, stem)
        except Exception as exc:
            msg = f"下载/解压/落地产物失败：{exc}"
            logger.exception(msg)
            return False, msg

        msg = f"✅ 官网 API 解析完成，输出目录：{output_dir}"
        logger.info(msg)
        return True, msg

    # ---- 步骤实现 ----
    def _resolve_model_version(self, req: ParseRequest) -> str:
        backend = (req.backend or "").strip()
        if backend in _VALID_MODEL_VERSIONS:
            return backend
        return self.model_version

    def _create_batch(self, req: ParseRequest) -> tuple[str, str]:
        is_ocr = _detect_is_ocr(req.pdf_path) if self.is_ocr_auto else False
        payload: dict[str, Any] = {
            "files": [
                {
                    "name": req.pdf_path.name,
                    "is_ocr": is_ocr,
                    "data_id": _sanitize_data_id(req.pdf_path.stem),
                }
            ],
            "model_version": self._resolve_model_version(req),
            "language": _normalize_language(req.lang_list),
            "enable_formula": bool(req.formula_enable),
            "enable_table": bool(req.table_enable),
        }
        resp = self._request_with_retry(
            "POST",
            f"{self.api_base}/api/v4/file-urls/batch",
            headers=self._headers(),
            json=payload,
            retries=3,
        )
        if resp.status_code != 200:
            return self._raise_for_response(resp)
        data = resp.json()
        code = data.get("code")
        if code != 0:
            # -60018 日上限：不重试，直接抛
            raise RuntimeError(f"创建批次失败 code={code} msg={data.get('msg')} (trace_id={data.get('trace_id')})")
        d = data.get("data") or {}
        batch_id = d.get("batch_id")
        file_urls = d.get("file_urls") or []
        if not batch_id or not file_urls:
            raise RuntimeError(f"返回缺字段：{data}")
        self.last_batch_id = batch_id
        return batch_id, file_urls[0]

    def _upload_file(self, upload_url: str, pdf_path: Path) -> None:
        # 官方要求：上传时不要设置 Content-Type
        with pdf_path.open("rb") as f:
            resp = requests.put(upload_url, data=f, timeout=600)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"PUT 上传返回 HTTP {resp.status_code}: {resp.text[:300]}")

    def _poll_batch(self, batch_id: str, file_name: str, idle_timeout: int | None = None) -> dict[str, Any]:
        url = f"{self.api_base}/api/v4/extract-results/batch/{batch_id}"
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            resp = self._request_with_retry("GET", url, headers=self._headers(), retries=3)
            if resp.status_code != 200:
                return self._raise_for_response(resp)  # type: ignore[return-value]
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"查询批次失败 code={data.get('code')} msg={data.get('msg')}")
            results = (data.get("data") or {}).get("extract_result") or []
            # 找到本文件对应的结果（按 file_name 匹配，否则取第一个）
            entry = next((r for r in results if r.get("file_name") == file_name), (results[0] if results else None))
            if not entry:
                time.sleep(self.poll_interval)
                continue
            state = entry.get("state")
            if state in _TERMINAL_STATES:
                return entry
            logger.info("cloud: %s state=%s", file_name, state)
            time.sleep(self.poll_interval)
        return {"state": "timeout", "err_msg": f"轮询超时（{self.timeout}s）"}

    def _materialize(self, zip_url: str, output_dir: Path, stem: str) -> None:
        # 下载原始 zip（保留为 package.zip）
        resp = requests.get(zip_url, timeout=600)
        if resp.status_code != 200:
            raise RuntimeError(f"下载结果 zip 返回 HTTP {resp.status_code}")
        package_zip = output_dir / "package.zip"
        package_zip.write_bytes(resp.content)

        raw_dir = output_dir / "_raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(package_zip, "r") as zf:
            self._safe_extract_zip(zf, raw_dir)

        full_md = self._find(raw_dir, "full.md")
        content_list = self._find(raw_dir, "content_list.json")

        if not full_md:
            raise RuntimeError(f"结果包中找不到 full.md（已保留原始 zip: {package_zip}）")

        # content.md / content.json 写到契约位置 output_dir 根
        (output_dir / "content.md").write_text(full_md.read_text(encoding="utf-8"), encoding="utf-8")
        if content_list:
            (output_dir / "content.json").write_text(content_list.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            # 兜底：无 content_list.json 时写入最小结构
            (output_dir / "content.json").write_text(
                json.dumps({"source": "mineru_cloud", "full_md": "content.md"}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        # 拷贝 images/ 到 output_dir，保证 content.md 内图片引用可解析
        images_src = self._find_dir(raw_dir, "images")
        if images_src:
            images_dst = output_dir / "images"
            if images_dst.exists():
                shutil.rmtree(images_dst)
            shutil.copytree(images_src, images_dst)

    # ---- 解压安全与查找 ----
    @staticmethod
    def _safe_extract_zip(zf: zipfile.ZipFile, extract_dir: Path) -> None:
        """逐文件解压，防 ZIP Slip 路径穿越。"""
        extract_dir = extract_dir.resolve()
        for member in zf.infolist():
            target = extract_dir / member.filename
            try:
                inside = target.resolve().relative_to(extract_dir)
            except ValueError:
                logger.warning("跳过不安全的 zip 条目：%s", member.filename)
                continue
            if member.is_dir():
                (extract_dir / inside).mkdir(parents=True, exist_ok=True)
            else:
                tgt = extract_dir / inside
                tgt.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, tgt.open("wb") as dst:
                    shutil.copyfileobj(src, dst)

    @staticmethod
    def _find(root: Path, name: str) -> Path | None:
        matches = list(root.rglob(name))
        return matches[0] if matches else None

    @staticmethod
    def _find_dir(root: Path, name: str) -> Path | None:
        matches = [p for p in root.rglob(name) if p.is_dir()]
        return matches[0] if matches else None

    @staticmethod
    def _raise_for_response(resp: requests.Response) -> Any:
        body = resp.text[:500]
        raise RuntimeError(f"HTTP {resp.status_code}: {body}")

    def is_parsed(self, folder_path: Path) -> bool:
        return self._check_parsed(folder_path)
