"""D13 二元路由核（唯一权威）。从 scripts/literature_batch_parse.py 提升。

路由策略（pipeline 弃用）：
- 文本层 PDF（born-digital）→ PyMuPDF 本地直抽；质检不合格 → 回退 cloud vlm。
- 扫描型 PDF（无文本层）→ cloud vlm。

单核约束：CLI/API/UI 都调本模块的 route_and_parse，不再各自实现路由。
import 安全：parser-core 子模块全部惰性导入（函数内），保证
`from core.mineru.router import route_and_parse` 不触发 fitz/网络。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


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


def route_and_parse(
    cloud_client: Any,
    pymupdf_client: Any,
    source_path: str,
    output_dir: Path,
    language: str,
) -> tuple[bool, str, str]:
    """二元路由（D13）。language 取 works.language 原值，内部经 map_mineru_language 映射。

    返回 (ok, msg, backend_used ∈ {"pymupdf","vlm"})。pipeline 不再使用。
    """
    from core.mineru.base_client import ParseRequest  # noqa: PLC0415（惰性）
    from core.mineru.pymupdf_client import has_text_layer  # noqa: PLC0415（惰性）

    pdf_path = Path(source_path)
    lang = map_mineru_language(language)

    def _cloud_vlm() -> tuple[bool, str]:
        req = ParseRequest(
            pdf_path=pdf_path,
            output_dir=Path(output_dir),
            backend="vlm",
            lang_list=lang,
            formula_enable=True,
            table_enable=True,
        )
        return cloud_client.parse_pdf(req)

    # 1) 文本层 → PyMuPDF
    if has_text_layer(pdf_path):
        ok, msg = pymupdf_client.parse_pdf(
            ParseRequest(pdf_path=pdf_path, output_dir=Path(output_dir))
        )
        if ok and _quality_ok(pymupdf_client):
            return True, msg, "pymupdf"
        print(f"  PyMuPDF 质检不合格({pymupdf_client.last_metrics})，回退 cloud vlm")
        ok2, msg2 = _cloud_vlm()
        return ok2, msg2, "vlm"

    # 2) 扫描型 → cloud vlm
    ok, msg = _cloud_vlm()
    return ok, msg, "vlm"
