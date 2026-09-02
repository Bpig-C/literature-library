"""路由核（唯一权威）。从 scripts/literature_batch_parse.py 提升。

路由策略（2026-08-31 起，用户决策"双路合并解析为默认"）：
- auto（默认）→ cloud vlm 优先；成功即自动旁路合并（detail.json +
  content.merged.md：MinerU 结构主体 + PyMuPDF 字形样式）。
  vlm 失败（无 token/网络/云端错误）→ 回退 PyMuPDF 本地直抽（带质检），
  质检不合格则整体失败。保证离线/无额度时流水线不断，但产物为纯文本+栅格图。
- backend="pymupdf" → 强制本地直抽（秒级/免费，只有文本层栅格图；不回退）。
- backend="vlm" → 强制云 VLM（失败不回退本地，显式要求云端产物时用）。
- 扫描型 PDF 在任何路径下都依赖 vlm（PyMuPDF 无 OCR）。

单核约束：CLI/API/UI 都调本模块的 route_and_parse，不再各自实现路由。
import 安全：parser-core 子模块全部惰性导入（函数内），保证
`from core.mineru.router import route_and_parse` 不触发 fitz/网络。
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

# backend 覆盖合法值（None/auto 等价：走 D13 自动路由）
VALID_BACKENDS = ("auto", "pymupdf", "vlm")

# 解析产物契约文件/目录名。解析前清理只删这些已知产物，未知文件保留，
# 避免 output_dir 被 DB 投毒时误删目录外的无责文件。
_KNOWN_ARTIFACTS = {
    "content.md", "content.json", "full.md", "content_list.json",
    "package.zip", "images", "_raw", "layout.json", "middle.json",
    "model.json", "span.json", "origin.pdf", "layout.pdf",
    # 合并旁路资产（UX-007 方案C）
    "detail.json", "content.merged.md",
}


def map_mineru_language(raw: str) -> str:
    """works.language 原值 → MinerU language 取值（ch/en/...）。

    消费者侧映射属 nucleus：CLI/API 只传 works.language 原值，统一在此映射。
    幂等：对自身输出再映射结果不变。缺失/未知 → en。
    """
    lang = (raw or "").strip().lower()
    if lang in ("", "unknown"):
        return "en"
    if lang.startswith("zh") or lang in ("chinese", "中文"):
        return "ch"
    if lang.startswith("en") or lang in ("english",):
        return "en"
    return lang[:2]


def _quality_ok(pymupdf_client: Any) -> bool:
    """薄封装，避免顶层 import 循环。"""
    from core.mineru.pymupdf_client import PyMuPDFClient  # noqa: PLC0415（惰性）
    return PyMuPDFClient.quality_ok(getattr(pymupdf_client, "last_metrics", {}))


def _clean_parse_artifacts(output_dir: Path, pdf_path: Path) -> None:
    """解析前清理契约输出目录里的**已知产物**（content.md/images 等，均可再生）。

    未知文件保留；目录不存在、或 output_dir 包含源 PDF（含同目录/祖先目录，
    防误删源文件）时跳过。
    """
    out = Path(output_dir)
    try:
        pdf_res = Path(pdf_path).resolve()
        if not out.exists():
            return
        out_res = out.resolve()
        if out_res == pdf_res or out_res in pdf_res.parents:
            return
    except OSError:
        return
    for child in out.iterdir():
        if child.name not in _KNOWN_ARTIFACTS:
            continue
        try:
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        except OSError:
            pass


def _maybe_build_detail_assets(pdf_path: Path, out_dir: Path) -> None:
    """cloud vlm 解析成功后旁路生成合并资产（detail.json + content.merged.md）。

    UX-007 方案C：旁路资产，不替换 content.md 等原始产物。任何失败只告警，
    不影响解析结果本身。
    """
    try:
        from core.document.detail_result.merged_md import build_detail_assets  # noqa: PLC0415
        raw_dir = out_dir / "_raw"
        if not raw_dir.is_dir():
            return
        info = build_detail_assets(pdf_path, raw_dir, out_dir)
        print(f"  detail 合并旁路资产：{info['nodes']} 节点 / {info['pages']} 页 "
              f"-> detail.json + content.merged.md")
    except Exception as exc:  # noqa: BLE001 — 合并失败不得影响解析
        print(f"  WARN: 合并旁路资产生成失败（不影响解析结果）：{exc}")


def route_and_parse(
    cloud_client: Any,
    pymupdf_client: Any,
    source_path: str,
    output_dir: Path,
    language: str,
    backend: str | None = None,
) -> tuple[bool, str, str]:
    """路由分发。language 取 works.language 原值，内部经 map_mineru_language 映射。

    backend: None/"auto" → 双路合并默认：cloud vlm 优先（成功即生成合并旁路
    资产），失败回退 PyMuPDF（带质检），两者皆败则失败；
    "pymupdf"/"vlm" → 强制指定后端（显式 pymupdf 质检不合格**不**回退 vlm）。
    非法值抛 ValueError。

    返回 (ok, msg, backend_used ∈ {"pymupdf","vlm"})。
    """
    from core.mineru.base_client import ParseRequest  # noqa: PLC0415（惰性）

    if backend not in (None, *VALID_BACKENDS):
        raise ValueError(f"backend 必须是 {'/'.join(VALID_BACKENDS)} 之一，得到 {backend!r}")

    pdf_path = Path(source_path)
    out_dir = Path(output_dir)
    lang = map_mineru_language(language)
    _clean_parse_artifacts(out_dir, pdf_path)

    def _cloud_vlm() -> tuple[bool, str]:
        req = ParseRequest(
            pdf_path=pdf_path,
            output_dir=out_dir,
            backend="vlm",
            lang_list=lang,
            formula_enable=True,
            table_enable=True,
        )
        return cloud_client.parse_pdf(req)

    def _local_pymupdf() -> tuple[bool, str]:
        return pymupdf_client.parse_pdf(
            ParseRequest(pdf_path=pdf_path, output_dir=out_dir)
        )

    # 0) 显式覆盖：强制 vlm / 强制 pymupdf（不回退）
    if backend == "vlm":
        ok, msg = _cloud_vlm()
        if ok:
            _maybe_build_detail_assets(pdf_path, out_dir)
        return ok, msg, "vlm"
    if backend == "pymupdf":
        ok, msg = _local_pymupdf()
        return ok, msg, "pymupdf"

    # 1) auto（默认=双路合并）：cloud vlm 优先，成功即合并 PyMuPDF 版面
    ok, msg = _cloud_vlm()
    if ok:
        _maybe_build_detail_assets(pdf_path, out_dir)
        return True, msg, "vlm"

    # 2) vlm 失败 → PyMuPDF 本地兜底（带质检；扫描件质检不过 → 整体失败）
    ok2, msg2 = _local_pymupdf()
    if ok2 and _quality_ok(pymupdf_client):
        return True, f"{msg2}（cloud vlm 不可用已回退本地：{msg[:120]}）", "pymupdf"
    if ok2:
        return False, (f"PyMuPDF 质检不合格({pymupdf_client.last_metrics})，"
                       f"且 cloud vlm 失败：{msg[:120]}"), "pymupdf"
    return False, f"cloud vlm 与 PyMuPDF 均失败。vlm: {msg[:120]}；pymupdf: {msg2[:120]}", "vlm"
