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


class MissingMarkdown(RuntimeError):
    code = 'missing_content_md'


class CloudStageError(RuntimeError):
    def __init__(self, code, *, http_status=None, provider_code=None):
        super().__init__(code)
        self.code=code;self.http_status=http_status;self.provider_code=provider_code


class CloudClient(PdfParseClient):
    """官网精准解析 API 客户端。"""

    def __init__(self):
        from config import config
        self._config = config
        # 最近一次解析的 batch_id（供调用方记录为 task_id，便于回溯/重试）
        self.last_batch_id = ""
        self.on_progress = None
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
    def _event(self, stage, **fields):
        if self.on_progress:
            self.on_progress(stage, **fields)

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
        # A lost POST response may already have created a billable task.
        # Read retries are safe; submission retries require a new explicit decision.
        if method.upper() == 'POST': attempts = 1
        timeout = kwargs.pop('timeout', 120)
        last_exc: Exception | None = None
        for i in range(attempts):
            try:
                resp = requests.request(method, url, timeout=timeout, **kwargs)
            except Exception as exc:
                last_exc = exc
                if method.upper() == 'POST':
                    self._event('submission_unknown', error_code='response_lost')
                    raise RuntimeError('submission_unknown: inspect provider before retry') from None
                logger.warning("Read request failed (%s/%s): %s", i + 1, attempts, type(exc).__name__)
                time.sleep(2 ** i)
                continue
            # 识别业务层限流码（响应体里 code != 0）
            code = self._safe_code(resp)
            if method.upper() == 'POST':
                if resp.status_code != 200 or code != 0:
                    self._event('submission_rejected' if resp.status_code < 500 and code is not None else 'submission_unknown',
                                http_status=resp.status_code, provider_code=code)
                return resp
            if code == -60009:  # 任务提交队列已满 → 退避重试
                logger.warning("队列已满，退避重试 (%s/%s)", i + 1, attempts)
                time.sleep(2 ** i)
                continue
            if code == -60018:  # 每日解析任务数已达上限 → 明确不重试，直接返回（由上层判失败）
                logger.error("每日解析任务数已达上限（-60018），不重试")
                return resp
            return resp
        raise RuntimeError('read retries exhausted: '+type(last_exc).__name__)

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
    def create_upload_batch(self,files,language,remember):
        """One native multi-file POST. Persist mapping/links before any PUT."""
        if not 1<=len(files)<=50:raise ValueError('native upload batch requires 1..50 files')
        if len({f['data_id'] for f in files})!=len(files) or len({f['name'] for f in files})!=len(files):raise ValueError('unique native batch identities required')
        payload={'files':[{'name':f['name'],'data_id':f['data_id'],
            'is_ocr':_detect_is_ocr(Path(f['path'])) if self.is_ocr_auto else False} for f in files],
            'model_version':'vlm','language':_normalize_language(language),'enable_formula':True,'enable_table':True}
        headers=self._headers()
        try:resp=requests.request('POST',f'{self.api_base}/api/v4/file-urls/batch',headers=headers,json=payload,timeout=120)
        except Exception:raise CloudStageError('submission_unknown') from None
        try:body=resp.json()
        except (ValueError,TypeError):body={}
        code=body.get('code') if isinstance(body,dict) else None
        if resp.status_code!=200 or code!=0:
            definite=resp.status_code==429 or (resp.status_code<500 and code is not None and code!=0)
            raise CloudStageError('submission_rejected' if definite else 'submission_unknown',http_status=resp.status_code,provider_code=code)
        data=body.get('data') or {};batch=data.get('batch_id');urls=data.get('file_urls') or []
        if not isinstance(batch,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}',batch):raise CloudStageError('submission_unknown')
        # An ID is worth preserving even when links are incomplete/malformed.
        remember(batch,urls if isinstance(urls,list) else [])
        if len(urls)!=len(files):raise CloudStageError('batch_response_incomplete')
        return batch

    def query_batch(self,batch_id):
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}',batch_id):raise ValueError('invalid batch ID')
        resp=requests.request('GET',f'{self.api_base}/api/v4/extract-results/batch/{batch_id}',headers=self._headers(),timeout=60)
        try:body=resp.json()
        except (ValueError,TypeError):raise CloudStageError('provider_response_invalid',http_status=resp.status_code) from None
        code=body.get('code') if isinstance(body,dict) else None
        if resp.status_code!=200 or code!=0:raise CloudStageError('provider_query_failed',http_status=resp.status_code,provider_code=code)
        entries=(body.get('data') or {}).get('extract_result') or []
        if not isinstance(entries,list):raise CloudStageError('provider_response_invalid')
        return [{k:r.get(k) for k in ('data_id','file_name','state','full_zip_url')} for r in entries if isinstance(r,dict)]

    def submit_pdf(self, req: ParseRequest) -> str:
        """One POST and upload; task ID is emitted durably before upload.

        Queue rate/capacity reservation belongs to the host scheduler. This
        method never retries a task-creating request or waits for cloud work.
        """
        self._event('configuration',backend='vlm')
        batch_id,upload_url=self._create_batch(req)
        self._event('upload',task_id=batch_id)
        self._upload_file(upload_url,req.pdf_path)
        return batch_id

    def poll_once(self, batch_id: str, file_name: str) -> dict:
        """Exactly one query; pending/running remains nonterminal."""
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}',batch_id):raise ValueError('invalid task ID')
        self._event('poll',task_id=batch_id)
        resp=requests.request('GET',f'{self.api_base}/api/v4/extract-results/batch/{batch_id}',headers=self._headers(),timeout=60)
        try:data=resp.json()
        except (ValueError,TypeError):raise CloudStageError('provider_response_invalid',http_status=resp.status_code) from None
        code=data.get('code') if isinstance(data,dict) else None
        if resp.status_code!=200 or code!=0:
            raise CloudStageError('provider_query_failed',http_status=resp.status_code,provider_code=code)
        results=(data.get('data') or {}).get('extract_result') or []
        entry=next((r for r in results if r.get('file_name')==file_name),None)
        # An unmatched filename must never be silently assigned to this source,
        # including operator-identified tasks after a lost submission response.
        if entry is None and results:raise CloudStageError('provider_identity_mismatch')
        if entry is None:return {'state':'pending'}
        state=entry.get('state')
        if state not in ('pending','running','done','failed','waiting-file'):state='pending'
        return {'state':state,'full_zip_url':entry.get('full_zip_url') if state=='done' else None}

    def download_existing(self, req: ParseRequest, batch_id: str, *, max_bytes=256*1024*1024):
        # Signed URLs are obtained just in time and never stored in the catalog.
        result=self.poll_once(batch_id,req.pdf_path.with_suffix('.pdf').name)
        if result['state']!='done' or not result.get('full_zip_url'):
            raise CloudStageError('result_not_ready')
        self._event('download',task_id=batch_id)
        self._materialize(result['full_zip_url'],req.output_dir,req.pdf_path.stem,max_bytes=max_bytes)

    def parse_pdf(self, req: ParseRequest) -> tuple[bool, str]:
        output_dir = (req.output_dir if req.output_dir else req.pdf_path.parent).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = req.pdf_path.stem

        if not req.pdf_path.exists():
            return False, f"源文件不存在：{req.pdf_path}"

        # 1. 申请上传链接
        self._event('configuration', backend='vlm')
        try:
            self._apply_rate_limit()
            batch_id, upload_url = self._create_batch(req)
        except Exception as exc:
            msg = 'create_batch failed: ' + type(exc).__name__
            logger.error(msg)
            return False, msg
        logger.info("cloud: batch_id=%s file=%s", batch_id, req.pdf_path.name)

        # 2. 上传文件（不设 Content-Type）
        try:
            self._event('upload', task_id=batch_id)
            self._upload_file(upload_url, req.pdf_path)
        except Exception as exc:
            msg = 'upload failed: ' + type(exc).__name__
            logger.error(msg)
            return False, msg

        # 3. 轮询结果
        try:
            self._event('poll', task_id=batch_id)
            result = self._poll_batch(batch_id, file_name=req.pdf_path.with_suffix('.pdf').name)
        except Exception as exc:
            msg = 'poll failed: ' + type(exc).__name__
            logger.error(msg)
            return False, msg

        state = result.get("state")
        if state != "done":
            err = result.get("err_msg") or f"state={state}"
            self._event('upstream_failed', task_id=batch_id)
            return False, 'upstream result not complete'

        zip_url = result.get("full_zip_url")
        if not zip_url:
            return False, "done 但缺少 full_zip_url"

        # 4. 下载 + 解压 + 产出 content.md / content.json
        try:
            self._event('download', task_id=batch_id)
            self._materialize(zip_url, output_dir, stem)
        except Exception as exc:
            self._event('materialize_failed', error_code=getattr(exc,'code','materialize_failed'), task_id=batch_id)
            msg = 'materialize failed: ' + ('missing full.md' if isinstance(exc,MissingMarkdown) else type(exc).__name__)
            logger.error(msg)
            return False, msg

        msg = f"✅ 官网 API 解析完成，输出目录：{output_dir}"
        logger.info(msg)
        return True, msg

    # ---- 步骤实现 ----
    def recover_pdf(self, req: ParseRequest, batch_id: str) -> tuple[bool, str]:
        """Read an existing provider task and materialize it, without POST/PUT."""
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', batch_id):
            raise ValueError('invalid upstream task ID')
        self.last_batch_id = batch_id
        try:
            self._event('poll', task_id=batch_id)
            result=self._poll_batch(batch_id, file_name=req.pdf_path.with_suffix('.pdf').name)
            if result.get('state')!='done' or not result.get('full_zip_url'):
                return False, 'existing cloud result not ready'
            self._event('download', task_id=batch_id)
            self._materialize(result['full_zip_url'],req.output_dir,req.pdf_path.stem)
            return True, 'existing task recovered'
        except Exception as error:
            return False, 'existing task recovery failed: '+type(error).__name__

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
                    # Cache objects can end in .asset. The upload API receives a
                    # PDF filename while bytes remain read from the pinned cache.
                    "name": req.pdf_path.with_suffix('.pdf').name,
                    "is_ocr": is_ocr,
                    "data_id": _sanitize_data_id(req.pdf_path.stem),
                }
            ],
            "model_version": self._resolve_model_version(req),
            "language": _normalize_language(req.lang_list),
            "enable_formula": bool(req.formula_enable),
            "enable_table": bool(req.table_enable),
        }
        headers = self._headers()  # validate configuration before marking submission
        self._event('submitting', backend='vlm')
        resp = self._request_with_retry(
            "POST",
            f"{self.api_base}/api/v4/file-urls/batch",
            headers=headers,
            json=payload,
            retries=3,
        )
        if resp.status_code != 200:
            return self._raise_for_response(resp)
        try:
            data = resp.json()
            if not isinstance(data, dict): raise ValueError('object required')
        except (ValueError, TypeError):
            self._event('submission_unknown', error_code='invalid_json')
            raise RuntimeError('submission response invalid; inspect before retry') from None
        code = data.get("code")
        if code != 0:
            # -60018 日上限：不重试，直接抛
            raise RuntimeError(f'provider rejected submission: code={code}')
        d = data.get("data") or {}
        batch_id = d.get("batch_id")
        file_urls = d.get("file_urls") or []
        if not batch_id or not file_urls:
            self._event('submission_unknown', error_code='invalid_response')
            raise RuntimeError('submission response missing fields')
        self.last_batch_id = batch_id
        self._event('upstream_submitted', task_id=batch_id)
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

    def _materialize(self, zip_url: str, output_dir: Path, stem: str, *, max_bytes=None) -> None:
        # 下载原始 zip（保留为 package.zip）
        resp = requests.get(zip_url, timeout=600, **({'stream':True} if max_bytes is not None else {}))
        if resp.status_code != 200:
            raise RuntimeError(f"下载结果 zip 返回 HTTP {resp.status_code}")
        package_zip = output_dir / "package.zip"
        if max_bytes is None:package_zip.write_bytes(resp.content)
        else:
            temporary=output_dir/'package.zip.part';size=0
            try:
                with temporary.open('wb') as target:
                    for chunk in resp.iter_content(1024*1024):
                        size+=len(chunk)
                        if size>max_bytes:raise CloudStageError('download_budget_exceeded')
                        target.write(chunk)
                temporary.replace(package_zip)
            finally:
                resp.close();temporary.unlink(missing_ok=True)

        raw_dir = output_dir / "_raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(package_zip, "r") as zf:
            if max_bytes is not None and (len(zf.infolist())>10000 or sum(i.file_size for i in zf.infolist())>max_bytes):
                raise CloudStageError('extraction_budget_exceeded')
            self._safe_extract_zip(zf, raw_dir)

        full_md = self._find(raw_dir, "full.md")
        # Current MinerU archives prefix content-list names with the document
        # identity. Never replace an existing structured result with a stub,
        # and never guess between different documents in an unexpected bundle.
        candidates = sorted({*raw_dir.rglob("content_list.json"),
                             *raw_dir.rglob("*_content_list.json")})
        candidates = [path for path in candidates if path.is_file()]
        if len(candidates) > 1:
            raise CloudStageError('ambiguous_content_list')
        content_list = candidates[0] if candidates else None

        if not full_md:
            raise MissingMarkdown('missing full.md; original package retained')

        # content.md / content.json 写到契约位置 output_dir 根
        (output_dir / "content.md").write_text(full_md.read_text(encoding="utf-8"), encoding="utf-8")
        if content_list:
            (output_dir / "content.json").write_text(content_list.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            # 兜底：无 content_list.json 时写入最小结构
            (output_dir / "content.json").write_text(
                json.dumps({"source": "mineru_cloud", "full_md": "content.md",
                            "content_list_available": False}, ensure_ascii=False, indent=2),
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
        raise RuntimeError(f'provider HTTP {resp.status_code}')

    def is_parsed(self, folder_path: Path) -> bool:
        return self._check_parsed(folder_path)
