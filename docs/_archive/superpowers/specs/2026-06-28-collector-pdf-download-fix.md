# collector PDF 下载缺口修复简报

> 日期：2026-06-28
> 发现于：三链路完整性 Phase A 端到端 smoke（Phase A 已合并 master，merge `048a93e`）
> 性质：collector 检索层（retrieval 层 7-task TDD）的实施遗漏，**非 Phase A 缺陷**，不阻塞 Phase A
> 优先级：**promote（候选→work）端到端的 blocker**；建议在 Phase C（collect/resolve 进 UI）之前或之中修复

---

## 1. 一句话问题

collector 从未实现"下载 PDF"这一步——`fetch.download_pdf` 写好但全仓库无调用者，`intake_candidates.local_pdf_path` 没有任何代码写入。导致 `resolve` 的 SHA256 闸门跑不了、`promote` 永远 `FileNotFoundError`，**"候选晋升为 work"在整个系统里是断的**。

## 2. 症状（smoke 实证）

```
$ python scripts/literature_intake.py collect --ids 2212.08073
collected 1 candidates                      # ✅ 元数据 + 轻量闸门判 new

$ python scripts/literature_intake.py resolve
resolved 1 candidates                       # ⚠️ 谎报：实际什么都没发生

# 候选 DB 状态：
resolution       = "new"          # 没变（应为 new/sha256_duplicate/fetch_failed 之一）
fetched_sha256   = NULL           # 没算
local_pdf_path   = NULL           # 没下载
resolved_at      = NULL           # 没落库
```

`resolve` 报 "resolved N" 但候选状态一字未改——具有误导性。

## 3. 根因（grep 实证）

| 事实 | 证据 |
|---|---|
| `download_pdf` 无人调用 | `grep -rn download_pdf collector/ scripts/` → 只有 `collector/fetch.py:7` 的定义，无调用者 |
| `local_pdf_path` 无人写 | 只被 `gate.py:78`（读）、`ingest_bridge.py:28`（读）引用，无任何 `UPDATE ... local_pdf_path` |
| `heavy_gate` 不下载 | `collector/gate.py:73-94`：只 `SELECT local_pdf_path` → `sha256_file`；PDF 缺失时 `return "fetch_failed"` **且不落库** |
| `collect` 设计不下载 | `discovery_explicit.py:2` docstring 明确 "No download" |

`retrieval` spec §5.2 规定 **resolve 负责"下载 + SHA256"**，但 retrieval 层实施时下载这步漏了。`heavy_gate` 的 docstring 自称 "Download-bound SHA256 check"——名不副实。

## 4. 影响

- `resolve`：重量闸门（SHA256 查 `source_files`）永远跳过 → 跨源/重复 PDF 无法判 `sha256_duplicate`。
- `promote`：`ingest_bridge._do_ingest` 读 `local_pdf_path` → NULL 时 `FileNotFoundError` → **晋升为 work 跑不通**。
- Phase A 的 18 个 API 测试全绿，是因为 promote 测试 stub 了 `ingest_bridge.promote`，跳过了真实 PDF/ingest——**只有端到端 smoke 暴露**。

## 5. 修复方案

### 5.1 主修：让 `heavy_gate` 名副其实（先下载，再 SHA256）

`heavy_gate` 的 docstring 已经自称 "Download-bound"，修复就是补上下载。**业务逻辑放 core（单核原则），CLI/API 都不动**（它们已委托 `resolve_pending` → `heavy_gate`）。

**涉及文件**：`collector/gate.py`（修改 `heavy_gate`）

**思路**：进入 `heavy_gate` 时，若 `local_pdf_path` 为空，先按候选 `source_type` 派生 PDF URL、用现成的 `fetch.download_pdf` 下载到缓存、`UPDATE local_pdf_path`；然后照旧 SHA256。下载失败 → `resolution='fetch_failed'` **并落库**（修掉当前"不落库"的小 bug）。

**代码骨架**（示意，团队据实调整）：
```python
# collector/gate.py
from pathlib import Path
from api.db import LIBRARY_ROOT
from collector.fetch import download_pdf
from collector.adapters import arxiv as arxiv_adapter
import scripts.literature_ingest as ingest   # 已有 utc_now / sha256_file

CACHE_DIR = LIBRARY_ROOT / "_collector_cache"

def _pdf_url_for(candidate: sqlite3.Row) -> str | None:
    """按来源派生 PDF 直链。arxiv 用 arxiv.pdf_url；github v1 不支持（见 §5.3）。"""
    if candidate["source_type"] == "arxiv" and candidate["arxiv_id"]:
        return arxiv_adapter.pdf_url(candidate["arxiv_id"])
    return None   # github 自有 PDF：留 follow-up

def heavy_gate(candidate_id: str):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM intake_candidates WHERE id=?", (candidate_id,)).fetchone()
        if not row:
            return "fetch_failed"
        pdf_path = row["local_pdf_path"]

        # —— 补：缺 PDF 先下载（让 download-bound 名副其实）——
        if not pdf_path:
            url = _pdf_url_for(row)
            if not url:
                _set_resolution(conn, candidate_id, "fetch_failed")  # 无可用 PDF 源
                return "fetch_failed"
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            dest = CACHE_DIR / f"{candidate_id}.pdf"
            if not download_pdf(url, dest):          # 现成函数，30s 超时 + UA
                _set_resolution(conn, candidate_id, "fetch_failed")  # 下载失败要落库
                return "fetch_failed"
            pdf_path = str(dest.relative_to(LIBRARY_ROOT))   # schema 约定：相对 library root
            conn.execute("UPDATE intake_candidates SET local_pdf_path=? WHERE id=?",
                         (pdf_path, candidate_id)); conn.commit()

        # —— 原有 SHA256 逻辑不变 ——
        digest = sha256_file(LIBRARY_ROOT / pdf_path)
        hit = conn.execute("SELECT 1 FROM source_files WHERE content_sha256=?", (digest,)).fetchone()
        resolution = "sha256_duplicate" if hit else "new"
        conn.execute(
            "UPDATE intake_candidates SET fetched_sha256=?, resolution=?, resolved_at=? WHERE id=?",
            (digest, resolution, utc_now(), candidate_id)); conn.commit()
        return resolution
    finally:
        conn.close()

def _set_resolution(conn, cid, resolution):
    conn.execute(
        "UPDATE intake_candidates SET resolution=?, resolved_at=? WHERE id=?",
        (resolution, utc_now(), cid)); conn.commit()
```

### 5.2 附带修：`heavy_gate` 缺 PDF 时落库

当前 PDF 缺失分支 `return "fetch_failed"` **不写 DB**（候选 resolution 仍 `new`），是 `resolve` 谎报"resolved N"的直接原因。5.1 的 `_set_resolution(..., "fetch_failed")` 一并修掉。

### 5.3 GitHub PDF：单列 follow-up（不在本次主修）

`github.collect_repo_paper` 目前只从 README 抽 arxiv_id 做强键对齐，**不提供 GitHub 自有 PDF 的直链**（raw_meta 里只有 repo_url / readme_excerpt）。下载 GitHub repo 内的论文 PDF 需要先在 repo 里定位 PDF 文件（releases / 顶层文件），是 GitHub adapter 的独立增强，不在本次主修范围。**主修只覆盖 arxiv 路径**（当前绝大多数候选来源）。GitHub 路径下 `_pdf_url_for` 返回 None → `fetch_failed`，行为明确不静默。

## 6. 边界约束（必须守）

1. **单核三适配器**：下载逻辑只在 `heavy_gate`（core）里写一次。CLI（`resolve`）和 API（`POST /intake/resolve`）已委托 `resolve_pending` → `heavy_gate`，**不用改**。
2. **collector 不直接写 works**：下载只写 `intake_candidates.local_pdf_path` + 缓存文件；晋升仍只走 `ingest_bridge.promote`。
3. **保守并发**：`download_pdf` 已是单文件 30s 超时；`resolve_pending` 串行调即可。批量并发下载留 future（参考 document-parser 的并发约束）。
4. **缓存路径**：`local_pdf_path` 存**相对 library root** 的路径（与 schema 注释一致），缓存目录 `_collector_cache/`。promote 后由 `ingest_bridge._do_ingest` `shutil.copy2` 到 inbox 接管；重入保护在 heavy_gate 入口的 `if not pdf_path` 守卫——已 resolve 的候选不会重复下载；`download_pdf` 本身覆盖写，这是安全的且允许 `fetch_failed` 候选被重试 resolve。
5. **`_quarantine` 不受影响**：下载的是新候选 PDF，不碰隔离体系。`needs_better_copy` 的替换流程（`replace_source`）是另一条路径，本次不动。

## 7. 测试要求（TDD，参照 `tests/test_gate_resolve_pending.py` 既有风格）

新增/扩充 `collector/gate.py` 的 `heavy_gate` 测试（`tests/test_gate.py` 或新文件），**monkeypatch `download_pdf` 避免真联网**：

- `heavy_gate` 候选无 `local_pdf_path` + arxiv 来源 → 调 `download_pdf(arxiv.pdf_url(aid), dest)` → 写 `local_pdf_path` → SHA256 未命中 `source_files` → `resolution='new'`，`fetched_sha256` 非空，`resolved_at` 落库。
- SHA256 命中已有 `source_files` → `resolution='sha256_duplicate'`。
- `download_pdf` 返回 None（下载失败）→ `resolution='fetch_failed'` **且落库**（断言 `resolved_at` 非空、`local_pdf_path` 仍 NULL）。
- 候选 `local_pdf_path` 已存在（二次 resolve）→ **不重复下载**（断言 `download_pdf` 未被调）→ 直接 SHA256。
- github 来源（无 arxiv_id）→ `_pdf_url_for` 返回 None → `resolution='fetch_failed'` 落库。

端到端验证（用 live DB 留的样本）：
```
# live DB 现有候选 IC-bbc198f1（Constitutional AI 2212.08073，new/pending，无 PDF）
python scripts/literature_intake.py resolve
# 期望：local_pdf_path 非空、fetched_sha256 非空、resolution ∈ {new, sha256_duplicate}、resolved_at 落库
```
修复后这条候选可一路走到 `promote` 验证"晋升为真实 work"（Phase A 的 UI「采集审核」页 → 批准 → 晋升）。

## 8. 涉及文件清单

| 文件 | 动作 |
|---|---|
| `collector/gate.py` | **主修**：`heavy_gate` 补下载步骤 + `_pdf_url_for` + fetch_failed 落库 |
| `collector/fetch.py` | 不改（`download_pdf` 现成，被启用） |
| `collector/adapters/arxiv.py` | 不改（`pdf_url` 现成，被启用） |
| `scripts/literature_intake.py` | 不改（`resolve` 已委托 `resolve_pending`） |
| `api/routes/intake.py` | 不改（`POST /intake/resolve` 已委托 `resolve_pending`） |
| `tests/test_gate*.py` | **新增** `heavy_gate` 下载分支测试 |
| `collector/adapters/github.py` | follow-up（GitHub 自有 PDF 直链，本次不做） |

## 9. 验收

- [ ] `resolve` 后候选 `local_pdf_path` / `fetched_sha256` / `resolved_at` 三者非空，`resolution` ∈ {new, sha256_duplicate, fetch_failed}。
- [ ] `resolve` 下载失败时 `resolution='fetch_failed'` 落库（不再谎报 resolved）。
- [ ] live DB `IC-bbc198f1` 能走到 `promote` 成功生成 work（`ingested_work_id` 回填），新 work 进入既有 metadata/分类审核流。
- [ ] `uv run python -m pytest tests/` 全绿（含新增 heavy_gate 下载测试；既有 173 passed 不回归）。
- [ ] 单核：CLI 与 API 未新增任何下载/SHA256 逻辑，全部经 `heavy_gate`。
