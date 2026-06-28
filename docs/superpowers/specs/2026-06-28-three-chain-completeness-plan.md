# 三链路完整性总体规划（CLI / API / UI）

> 日期：2026-06-28
> 状态：总体规划（落地依据），任务计划与实施由后续 agent 负责
> 关联：`FUTURE_WORK_PLAN.md`（P3.5 parser、P6 collector）、`docs/superpowers/specs/2026-06-27-collector-integration-design.md`、`docs/superpowers/specs/2026-06-27-collector-retrieval-design.md`、`docs/superpowers/specs/2026-06-27-parser-subproject-design.md`
> 上位：`D:\02_academic\doctoral\LITERATURE_SYSTEM_PLAN.md`

## 1. 目标

让文献库的每个能力在 **CLI、后端 API、前端 UI** 三条链路上都完整可用。当前既有系统（works/metadata/classification/dedup/relations/files）三链路已齐全，作为模板；本规划聚焦把 **parser（P3.5）** 与 **collector（P6）** 两个已合并但仅 CLI 可用的子系统补齐 API + UI 两条链，并端到端打通全流程。

## 2. 架构原则（硬约束，所有 agent 必须遵守）

**单核三适配器**：业务逻辑只在 core 包里写一次；CLI 脚本、API 路由、Vue 页面都是薄适配器，绝不重复实现。

```text
┌──────────────────────────────────────────────────────┐
│ Core（单一真相源，已存在）                               │
│  collector/  gate · candidate_store · ingest_bridge · │
│              topics · adapters · discovery_*          │
│  parser/core mineru cloud_client(vlm) · pymupdf ·     │
│              selfdeploy · artifact_generator          │
│  existing    ingest · dedup · metadata · classify     │
└──────────────────────────────────────────────────────┘
        ▲                 ▲                  ▲
        │                 │                  │
   CLI scripts       API routers         Vue SPA
  (operator/agent)  (程序化 + 喂 UI)       (人)
```

- API 是 UI 与 core 之间的契约；CLI 和 API 都只包装 core。
- 禁止在 API 路由或 CLI 里复制业务逻辑（避免"两个真相源"）。
- UI 优先服务"人必须决策"的环节（A2 审核、主题提案拍板）；重批量（全库采集、批量回填）留 CLI/loop。
- 向后兼容：既有 6 个路由 + 7 个页面不动语义，只新增。

## 3. 能力 × 链路矩阵（现状 → 目标）

| 能力 | CLI | API | UI | 说明 |
|---|---|---|---|---|
| collector-A 主题生命周期 | ✅ `literature_intake topic` | ✅ `/intake/topics` | ✅ TopicsReview.vue | `collection_topics` **已迁移到 live DB**（Phase A）；UI 成熟度闸门 + list_topics additive 补字段（Phase C） |
| collector-B 发现(collect) | ✅ `literature_intake collect` | ✅ `/intake/collect` | ✅ TopicsReview.vue | 重批量主战场 CLI/loop；UI 提供"按主题发起一次采集"入口（Phase C）；collect 编排提取为 `collector.collect.collect_once` §2 单核 |
| collector-C 闸门(resolve) | ✅ `literature_intake resolve` | ✅ `/intake/resolve` | ✅ TopicsReview.vue | 可被 promote 链式触发；UI 加触发 resolve 按钮（Phase C） |
| collector-D **A2 审核+晋升** | ✅ `literature_intake list/promote` | ✅ `/intake/*` | ✅ IntakeReview.vue | **Phase A 已完成并合并**；人必须介入，UI 优先级最高 |
| **ingest-G inbox 手动摄入** | ✅ `literature_ingest.py` | ❌ | ❌ | 手动丢 PDF 旁路，无候选闸门（源可信）；被原矩阵遗漏，单列 Phase B' |
| parser-E 解析 pending | ✅ `parser/main.py` | ✅ `/parse/trigger` | ✅ WorkDetail 触发按钮 | **Phase B 已完成**；D13 路由统一到 `core.mineru.router`（单核三适配器）；真实 smoke 经 cloud vlm 验证（W-arxiv-2506.19248） |
| parser-F 解析状态/产物 | ✅ DB-only | ✅ `/parse/status` | ✅ WorkDetail 徽标 | **Phase B/D 已完成**；CLI/API/UI 三收敛键控 `literature_parse_runs`（Phase D 状态源统一：CLI 改 DB-only，`parse_ledger.json` 废弃归档） |
| (既有) works/meta/分类/去重/关系/文件 | ✅ | ✅ | ✅ | 三链齐全，作模板 |

**差距（修订后）**：collector-D（A2审核）、parser-E/F 三链已齐（Phase A/B）；仍缺 API+UI 的有 ingest-G、collector-B/C 的 API/UI 链。collector-A/C 的部署缺口（collection_topics 迁移）已于 Phase A 闭合。

> **澄清（易混点）**：`collector collect` **不直接摄入成 work**。采集链四阶段——collect（落 `intake_candidates` 候选，仅元数据）→ resolve（下载+SHA256 闸门）→ **A2 人工审核关（IntakeReview）** → promote（经 `ingest_bridge` 才写 `works`）。人不点 promote，候选永远是候选。inbox-ingest（ingest-G）则是另一条**无候选闸门**的旁路：手动丢 PDF → 直接摄入成 work → 再 parse。

## 4. 分阶段规划

### Phase A — collector 审核闭环（API + UI）〔✅ 已完成并合并〕

把 collector 唯一必须人介入的环节（A2 审核 + 晋升）搬进 UI。

> **状态：✅ 已完成并合并 master（merge `048a93e`）。** 落地：`api/routes/intake.py`（7 端点全委托 core）+ `IntakeReview.vue`（侧边栏「采集审核」）+ `tests/test_intake_api.py`（18 测试）。Core 抽 nucleus：`candidate_store.set_review_status`、`gate.resolve_pending`（CLI/API 共用单一真相源）。`collection_topics` 已迁移到 live DB。
>
> **端到端 smoke 已完成（2026-06-28）**：联网 `collect 2506.19248`（Inference-Time Reward Hacking, NeurIPS 2025）→ `resolve`（真下载 PDF+SHA256）→ API `review`+`promote` → 真实 work `W-arxiv-2506.19248` 落地（source_files + parse_runs pending，进入既有体系）。CLI/API/UI 三链全通。
>
> **实施中发现并修补的基础层问题**（非 Phase A 缺陷，均闭合）：
> 1. **collector PDF 下载缺口**：retrieval 层遗漏下载步骤——`fetch.download_pdf` 写好但全仓库无调用者、`local_pdf_path` 无任何代码写入 → resolve 的 SHA256 闸门跑不了、promote 必 `FileNotFoundError`，"候选晋升为 work"整链曾断。**已修**（merge `3712882`，`heavy_gate` 现按来源下载 PDF 再 SHA256，`fetch_failed` 落库不再谎报）。详见 `docs/superpowers/specs/2026-06-28-collector-pdf-download-fix.md`。
> 2. **promote A2 守卫**：`POST /intake/promote` 原不校验 `review_status`，程序化调用可绕过人工审核直晋。**已补**：仅晋升 `review_status='approved'` 候选，未审核者进 `failed`、不调 `ingest_bridge`，批次不中断语义不变。
>
> **Phase D 跟踪项**：既有 `test_api.py::TestMetadataQuarantine` 分页脆弱（与 collector 无关，base 即失败）；`pyproject.toml` 无 `[tool.pytest.ini_options]`，裸 `pytest` 会收集 `parser/tests`。

- **部署前置**：把 retrieval 层的 `collection_topics`（及相关）迁移跑到真实库（代码已就绪、仅在测试夹具中）。
- **后端**：新增 `api/routes/intake.py`，挂进 `api/main.py`。端点全部委托 `collector/` core：
  - `GET  /api/intake/candidates`（按 resolution / review_status / topic 过滤、分页）
  - `POST /api/intake/resolve`（触发闸门，可批量）
  - `POST /api/intake/promote`（A2 批量晋升 → 复用 `ingest_bridge`）
  - `GET  /api/intake/stats`（new/exact_hit/title_candidate/needs_better_copy/sha256_duplicate 计数）
  - `GET/POST /api/intake/topics`（主题列表 / 成熟度流转）
- **前端**：新增 `IntakeReview.vue`（仿 `MetadataReview.vue`）——候选列表 + 四态判别展示 + 逐条 approve/reject + 批量 promote + needs_better_copy 高亮。侧边栏加入口。
- **验收**：人能在浏览器走完「候选 → 审核 → 晋升为 work」，晋升后 work 进入既有 metadata/分类审核流。

### Phase B — 解析触发与状态（API + UI）〔打通晋升→全文〕 ✅ 已完成（2026-06-28，分支 `fix/phaseB-parse-trigger`）

> **交付**：`api/routes/parse.py`（薄适配器）+ `parser/core/mineru/router.py`（D13 单核，从 CLI 脚本提升）+ `sync_work_parse_status` helper 复用 + WorkDetail 触发按钮。后端测试 7/7 绿（桩 `_run_parse`，不触达 fitz/网络）；**真实 smoke 经 cloud vlm 端到端验证**：W-arxiv-2506.19248 → `content.md`(112KB) 落地 + `content_md_path` + `parse_status=succeeded`。**遗留**（Phase D）：CLI 读 `parse_ledger.json` 而 API/UI 读 `literature_parse_runs` 的状态源不一致，待统一；`parser/scripts/literature_batch_parse.py` 旧批量队列版待归档；Parse 全库概览页未做（WorkDetail 单 work 触发已满足验收）。

- **后端**：新增 `api/routes/parse.py`，委托 `parser/core`：
  - `POST /api/parse/trigger`（解析指定/全部 pending，尊重 D13 backend 路由，保守并发）
  - `GET  /api/parse/status`（pending/succeeded/failed 计数 + 个别 work 状态）
  - 从 `.env` 读 `MinerU_API_KEY`；不可用时按 selfdeploy 降级策略。
- **前端**：WorkDetail 加解析状态徽标 + 触发按钮；可选轻量 Parse 页看全库 pending。
- **验收**：promote 后能在 UI 触发解析并看到 `content.md` 落地，`literature_parse_runs.content_md_path` 更新。

### Phase B' — inbox 手动摄入（API + UI）〔补齐手动丢 PDF 动线〕

> 与 Phase B（parse）天然前后衔接（丢 PDF → 摄入 → 解析），但各自独立可交付。建议顺序：B 先（核心增量、契约硬约束），B' 后（低频运维旁路）。

- **后端**：新增 `api/routes/ingest.py`，委托 `scripts/literature_ingest.py` 抽出的 core（`build_ingest_plan` / `execute_plan` 提为可 import 模块，CLI/API 共用）：
  - `GET  /api/ingest/plan`（扫描 `_inbox/`，dry-run 返回 IngestPlan：待摄入 + exact_sha256 重复，不写盘）
  - `POST /api/ingest/execute`（执行 plan：拷贝/归档/写 SQLite/追加 parse ledger，带备份）
  - `GET  /api/ingest/inbox`（当前 inbox 清单 + 历史归档）
- **前端**：新 `InboxReview.vue`（仿 IntakeReview）——dry-run 预览（待摄入 vs exact 重复高亮）→ 人工确认 → 执行。
- **边界（关键差异）**：ingest 直接写 `works`，**不经候选闸门**（与 collector 不同，源是用户亲手丢的可信 PDF）；dry-run 预览即人工关。文件 IO（拷贝/归档/备份）放 core，路由薄；ingest 与 collector 两套摄入路径互不混用。
- **验收**：浏览器上传/拖放 PDF 到 `_inbox/` → dry-run 预览 → 确认摄入 → 新 work 进既有 metadata/分类审核流 → 可链式触发 Phase B 解析。

### Phase C — collector 主题与发现进 UI〔补齐 A/B/C 的 UI 链〕 ✅ 已完成（2026-06-29，分支 `fix/phaseC-collector-ui`）

> **交付**：
> - **§2 单核**：`scripts/literature_intake.collect` 的编排（按 topic query_def 分发到 collect_explicit/collect_from_seeds/collect_repo_paper + light_gate 写 resolution）提取为 `collector/collect.py::collect_once`；CLI 改薄包装（零逻辑复制），为 API 铺路。`grep "def collect_once" --include=*.py .` 仅命中 `collector/collect.py`。
> - **API**：新增 `POST /api/intake/collect`（薄适配器，全委托 `collect_once`，零编排逻辑）；`GET /api/intake/topics` 背后的 `topics.list_topics` 改为 **additive** `SELECT *`（解析 query_def/mapped_tags，新增 description/axis_hint/proposed_note/mapped_tags 列；既有 id/name/map_status/lifecycle key 不破，既有消费者与 test_intake_api 不受影响）。
> - **UI**：新增 `web/src/views/TopicsReview.vue`（侧边栏「🗂️ 主题闸门」→ `/topics`）——左栏主题列表（map_status 三色 badge: seedling/proposed/mapped）+ 右栏详情（描述/轴归属/explicit_ids/seed_paper_ids/proposed_note 4 判据/mapped_tags）。成熟度闸门按钮（seedling→proposed prompt 填 proposed_note 提示 4 判据；proposed→mapped prompt 填 mapped_tags）+ 按主题发起采集按钮（`collectIntake`）+ 触发 resolve 按钮（复用 `resolveIntake`）。`api.js` 加 `transitionTopic`/`collectIntake`。
> - **测试**：`tests/test_collect_once.py`（4 测试，桩网络入口，验证分发+闸门写入+unknown topic+非 pending 跳过闸门）；`tests/test_intake_api.py` +3 collect 端点测试；`tests/test_collection_topics.py` +1 list_topics additive 断言。`uv run python -m pytest tests/` 206 passed/6 skipped（2 个 test_batch_parse_cli 失败为预先存在的环境问题——缺 `MinerU_API_KEY`，与 Phase C 无关）。`tests/test_collector_boundary.py` 3/3 守卫通过（collector 仍经 ingest_bridge 写 works）。
> - **向后兼容**：`list_topics` additive；CLI `collect` 行为不变（`test_intake_cli` 6/6 回归通过）。
> - **边界**：UI collect 只做"按主题发起一次采集"入口，持续 loop/批量订阅留 CLI。
> - **遗留**（Phase D）：`test_batch_parse_cli` 的 2 个环境性失败（需 `MinerU_API_KEY`）独立于本 phase。

- Topics 页：主题成熟度（seedling/proposed/mapped）管理 + 提案闸门 4 判据展示。
- 在 UI 触发 collect/resolve（或明确"按主题发起一次采集"为 UI 入口，持续订阅/loop 留 CLI）。
- **验收**：collector 四子能力 A/B/C/D 三链路齐全。

### Phase D — 端到端打通与三链验收

> **进度**：Phase D-hygiene ✅ 已完成（2026-06-28，合并点见 master）。落盘 P1.0g 测试侧修复（`test_quarantine_excludes_from_default_list` 加 `&search={work_id}`，路由本就正确）+ `pyproject.toml` 加 `[tool.pytest.ini_options] testpaths=["tests"]`。`pytest tests/` 192 passed/6 skipped/0 failed；裸 pytest 干净收集 198 tests。
>
> **状态源统一 ✅ 已完成（2026-06-28，分支 `fix/phaseD-status-unify`）**：`parse_ledger.json` 文件状态源废弃，`literature_parse_runs`（DB）成为解析状态唯一权威。具体：旧自部署 MinerU Agent API CLI（`parser/scripts/literature_batch_parse.py`，bucket/failure_kind 唯一消费者）+ ledger 依赖工具 `literature_cleanup_bad_sources.py` 归档至 `_archive/`；新 CLI `scripts/literature_batch_parse.py` 改 DB-only（`get_pending_db` + `run_pending`，逐条 UPDATE parse_runs + 复用 `sync_work_parse_status` 同步 `works.parse_status`，不再读 ledger）；ingest 删 `update_ledger` 停止双写；healthcheck/dashboard 脱离 ledger（纯读 parse_runs）。`parse_ledger.json` 移至 `_archive/parse_ledger.json.bak`。`grep parse_ledger --include=*.py api/ scripts/ collector/ parser/core/` 为空。§2 单核不变量 PRESERVED（`route_and_parse` 仅 `parser/core/mineru/router.py`）。Phase D-acceptance 三链 smoke 待后续。

- 全流程 smoke（两条摄入路径都要走通）：
  - **采集路径**：`collect → resolve → [IntakeReview 审核] → promote → [parse 触发] → content.md → metadata/分类/去重(既有 UI) → 分析`
  - **inbox 旁路**：`丢 PDF → [InboxReview dry-run+确认] → ingest → [parse 触发] → content.md → metadata/分类/去重 → 分析`
- **硬指标**：每个能力从 CLI、API、UI 三入口都能触发并观察到结果。
- 新增端点全部配测试；`parser/tests` 的 `fitz`(PyMuPDF) 收集错误在根 pytest 配置中隔离（ignore 或 testpaths 限定 `tests/`），不污染根测试。✅ 已落地（Phase D-hygiene）：`pyproject.toml` 设 `testpaths=["tests"]`，裸 pytest 不再收集 parser/tests。

## 5. 跨切关注点（贯穿所有 phase）

1. **单核三适配器**——API/CLI 不写业务逻辑。
2. **每端点配测试**（参照 `tests/test_api.py`：temp DB 副本 + patch 各路由 `get_conn`；不污染真实库）。
3. **配置/部署**：`.env` MinerU_API_KEY（已就位）、parser backend 选择、`collection_topics` 迁移、API 进程能 import `parser`/`collector` 子包。
4. **测试隔离**：根 pytest 不要收集 `parser/tests`（PyMuPDF 未必在根 venv）；用 `pyproject.toml` 的 `[tool.pytest.ini_options]` 限定 `testpaths = ["tests"]` 或 ignore parser。
5. **边界守恒**：collector 绝不直接写 `works`（经 `ingest_bridge`）；解析输出契约（`works/{id}/parsed/mineru/{sfid}/content.md` + `content_md_path`）不变。

## 6. 端态验收（Definition of Done）

- 能力矩阵中 ✅/❌ 全部转为 ✅（每能力三链路可达）。
- `uv run python -m pytest tests/` 全绿（含新增 intake/parse 端点测试）。
- 三链路 smoke 脚本/用例：同一动作从 CLI、`curl /api`、UI 各走一遍，结果一致。
- 既有功能无回归（既有 153 passed 基线不退化）。

## 7. 分工

- **总体规划（本文档）**：架构、矩阵、分阶段、验收标准。
- **后续 agent**：按 Phase 拆任务计划（`writing-plans` 技能 → `docs/superpowers/plans/`）→ 实施 → 自审 → 提 PR/合并。每个 Phase 独立可交付。
