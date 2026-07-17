# 文献库技术说明

> 更新时间：2026-07-17
> 适用版本：V1.3。collector / parser / inbox / review / discovery 链路已具备 CLI、API、UI 闭环；P1 发布阻断项已清零。
> ⚠️ 注意：本文档部分页面/API 端点清单滞后于代码（缺 Pipeline/IngestHub/TemplateManage 页面与 templates 路由组），以代码为准；全面刷新待排期。
> 数据根目录：`D:\02_academic\doctoral\literature_library`

## 1. 系统目标

把博士阶段阅读过的文献稳定存储、结构化管理、支持后续综述写作。核心约束：

- 物理文件（PDF）和逻辑关系（标签、重复、关联）分离，关系由 SQLite 管理，不靠文件夹表达。
- 不直接删除文件，只归档或隔离。
- 本地优先，不依赖外部服务（Ollama 用于元数据抽取，非必需）。

## 2. 当前架构

### 技术栈

| 层 | 技术 | 端口 |
|---|---|---|
| 数据库 | SQLite (WAL 模式) | — |
| 后端 | FastAPI (Python) | 19527 |
| 前端 | Vue 3 + Vite | 19528 |
| PDF 解析 | 二元路由：PyMuPDF 本地（文本层，默认/免费）↔ MinerU 官网 cloud vlm（扫描型/降级） | 经 parser/ 子项目 |
| 文献采集 | collector 子项目（topics 成熟度闸门 / collect·resolve / intake 审核 / ingest_bridge） | CLI·API·UI 三链 |
| 发现检索 | discovery 子项目（topic/name/title/url/composite 五种模式 + agent 回填协议 + web-access 约束） | CLI·API·UI·Agent |
| 元数据抽取 | Ollama (qwen3:4b) / opencode→MiMo-v2.5-pro（质量裁判） | 11435 |

### 目录结构

```text
literature_library/
  literature.sqlite          # 主数据库，逻辑关系中心
  index.json                 # 前端/脚本可读的文献索引（历史产物，新功能优先查 DB）
  # parse_ledger.json 已废弃并归档；解析状态现以 literature_parse_runs 表为准
  pyproject.toml             # Python 项目配置（uv）
  _inbox/                    # 新 PDF 临时投递入口
  _duplicates/               # 精确重复文件归档处
  _quarantine/               # 失败、坏源文件暂存处
    {work_id}/               # 按 work 隔离
  _archive/                  # 已归档的历史中间产物
    dedup/                   # 去重归档的冗余源文件
    ingested_inbox/          # 摄入后归档的 inbox 原文件
  works/                     # 文献永久存储区
    {work_id}/
      source/                # PDF 源文件
      parsed/mineru/{source_file_id}/content.md  # MinerU 解析产物
      analyses/              # 分析结果 Markdown（由 literature_analyze.py --submit 双写）
  _analysis_outbox/          # 分析结果提交暂存区（JSON 待 submit）
    digest/                  # digest 角度的待提交 JSON
  scripts/                   # 本地维护脚本
  api/                       # FastAPI 后端
  web/                       # Vue 3 前端 SPA
  tests/                     # 测试
  views/                     # 历史 HTML 台账（已被 SPA 替代）
```

### SQLite 作为逻辑中心

所有文献的元数据、解析状态、重复关系、文献间关联都记录在 `literature.sqlite` 中。文件系统只负责存储物理文件，不做逻辑查询。

### FastAPI 后端

`api/main.py` 启动 FastAPI 应用，挂载 10 组路由：works、relations、duplicates、files、metadata、classification、intake、discovery、parse、ingest。生产模式下同时托管 Vue 构建产物。CORS 允许 `localhost:19528`。

### Vue 前端

单页应用，11 个页面：Dashboard、Works、WorkDetail、Duplicates、Relations、MetadataReview、ClassificationReview、IntakeReview、InboxReview、TopicsReview、DiscoveryReview。通过 `/api` 前缀与后端通信。

### MinerU / content.md 解析链路

PDF → `parser/` 子项目（`core/mineru/`）→ 输出 `content.md` + `content.json`。解析结果路径记录在 `literature_parse_runs.content_md_path`，后续所有文本处理（元数据抽取、全文分析）都以这个路径为入口，不重新解析 PDF。

**后端选择**（`parser/conf.json` `mineru.backend`，默认 `cloud`）：
- **cloud**（默认）：MinerU 官网「精准解析 API」。`scripts/literature_batch_parse.py` 进程内直连 `parser/core/mineru/cloud_client.py`：预签名上传 → 轮询 → 下载 zip → 解压，`full.md`→`content.md`、`content_list.json`→`content.json`。token 从根目录 `.env` 的 `MinerU_API_KEY` 读（Bearer）。默认 `model_version=pipeline`；数学密集型可按 work 标 `vlm`（pipeline 对公式有间距伪影）。
- **selfdeploy**（降级）：`MINERU_BACKEND=selfdeploy` + `MINERU_SERVER_URL` → 走原 `WebClient`/`LocalClient`（自部署 MinerU，端口 18200/18201）。

**质量裁判**（`scripts/llm_judge.py`）：opencode→MiMo-v2.5-pro 对每篇 `content.md` 出类型化裁决 `{quality,needs_reparse,issues,completeness,reason}`；`needs_reparse` 触发 vlm 重解析。该模块为后续元数据/主题/分类共用的本地强模型基础设施。

## 3. 数据模型

### works

**职责**：文献主表，每篇文献一行。日常检索、排序、编辑都围绕这张表。

| 字段 | 说明 | 谁写入 |
|---|---|---|
| `id` | 主键，格式 `W-arxiv-*` 或 `W-sha-*` | 摄入脚本 |
| `title` | 标题 | 摄入/元数据回填/手动编辑 |
| `authors` | JSON 数组，关键作者 | 摄入/元数据回填/手动编辑 |
| `year` | 发表年份 | 摄入/手动编辑（暂不自动回填） |
| `arxiv_id` | arXiv ID | 摄入/元数据回填 |
| `doi` | DOI | 元数据回填 |
| `doc_type` | 文献类型 | 摄入 |
| `language` | 语言 | 摄入 |
| `parse_status` | 解析状态（按 active 源覆盖计算；唯一权威为 `sync_work_parse_status` 重算 `literature_parse_runs`） | `sync_work_parse_status`（解析触发/批处理/归档端点后调用） |
| `read_status` | 阅读状态，含 `quarantined` | 手动/API |
| `title_zh` | 中文标题 | 元数据回填 |
| `venue` | 发表场所 | 元数据回填 |
| `url` | 论文主页 | 元数据回填 |
| `abstract` | 摘要 | 元数据回填 |
| `contributors` | JSON：贡献方列表（name/type/role） | 元数据回填 |
| `publication_date_json` | JSON：结构化日期（year/month/day/raw/kind） | 元数据回填 |
| `primary_doc_type` | 文档类型（research_article/technical_report/...） | 分类抽取 |
| `publication_status` | 发布状态（published/preprint/draft） | 分类抽取 |
| `ingestion_state` | 摄入状态（new/processed/needs_review） | 分类抽取 |
| `priority` | 优先级（core/secondary/archive） | 分类抽取 |
| `is_core_literature` | 是否核心文献 | 分类抽取 |
| `primary_source_actor_type` | 来源机构类型（university/company/government/...） | 分类抽取 |
| `region` | 地区（US/CN/EU/global） | 分类抽取 |
| `canonical_file_format` | 首选文件格式 | 分类抽取 |

### source_files

**职责**：记录每个 work 的每个源文件（PDF）。一个 work 可能有多个 source_file（例如去重前的冗余副本）。

| 字段 | 说明 |
|---|---|
| `id` | 主键 |
| `work_id` | 关联 works |
| `content_sha256` | 文件内容哈希，用于精确去重 |
| `source_path` | 物理路径 |
| `status` | `active` 或 `archived` |
| `archive_path` | 归档后的新路径 |
| `archive_reason` | 归档原因 |

### literature_parse_runs

**职责**：记录每次解析尝试。一个 work 可能有多条记录（重跑解析时），但通常只有一条 `succeeded`。

| 字段 | 说明 |
|---|---|
| `id` | 主键 |
| `work_id` | 关联 works |
| `source_file_id` | 关联 source_files |
| `status` | `pending` / `succeeded` / `failed` |
| `content_md_path` | **关键字段**：MinerU 输出的 content.md 路径，后续元数据抽取以此为入口 |
| `content_json_path` | MinerU 输出的 content.json 路径 |

### parse_artifacts

**职责**：记录解析产出的每个文件（content.md、content.json 等），用于追踪解析产物完整性。

| 字段 | 说明 |
|---|---|
| `id` | 主键 |
| `work_id` | 关联 works |
| `source_file_id` | 关联 source_files |
| `type` | 产物类型 |
| `file_path` | 产物物理路径 |

### duplicate_groups / duplicate_candidates

**职责**：去重分析的候选组和候选条目。`duplicate_groups` 是一组重复候选，`duplicate_candidates` 是组内的具体条目。

`duplicate_groups.duplicate_type` 区分精确重复（`exact_sha256`）和标题候选（`title_candidate`）。`exact_sha256` 组自动确认，标题候选需人工决策。

`duplicate_candidates.reviewed` 标记是否已人工审查。

### work_relations

**职责**：文献间关系（same_work、not_duplicate、version_of、translation_of、supersedes、part_of）。去重决策和手动关联都写入此表。

### work_codes

**职责**：文献标记代码，例如 `bad_source` 表示坏源已隔离。用于 quarantine 操作追踪。

### metadata_extractions

**职责**：保存每次模型抽取的原始结果。一个 work 可能有多条抽取记录（不同模型、多次抽取）。不直接回填 works，需人工审核后才应用。

| 字段 | 说明 |
|---|---|
| `id` | 主键，格式 `ME-{hex}` 或 `ext-claude-{hex}` |
| `work_id` | 关联 works |
| `model_name` | 使用的模型：`qwen3:4b-instruct-*`（Ollama）或 `mimo2.5pro` |
| `content_md_path` | 输入的 content.md 路径 |
| `input_chars` / `input_tokens_est` | 输入规模 |
| `extracted_json` | 模型抽取的完整 JSON（含 title、title_zh、publication_date、authors、contributors、abstract 等） |
| `confidence_json` | 字段级置信度（high/medium/low） |
| `applied` | 是否已回填 works |
| `review_status` | 审核状态：`pending` / `approved` / `needs_fix` / `rejected` |
| `review_note` | 审核备注 |
| `reviewed_at` | 审核时间 |
| `risk_level` | 风险等级：`low` / `medium` / `high` |
| `risk_score` | 风险分数（0–100） |
| `risk_reasons` | JSON 数组：风险原因列表 |
| `review_source` | 审核来源：`human` / `batch_low_risk` / `system` / `claude` / `mimo` |
| `fix_action` | 修正动作：`edited` / `superseded` / `quarantined` / `rerun_requested` |

**双模型架构**：同一篇文献可以有 Ollama（qwen3:4b）和 Mimo 2.5 Pro 两种模型的抽取结果。审核时可对比两种结果，选择更准确的一条批准。批准一条后，同 work 的其他 pending 抽取自动 supersede。

**抽取字段**（extracted_json 内部结构）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `title` | string | 精确标题 |
| `title_zh` | string | 中文标题 |
| `publication_date` | object | `{year, month, day, raw, kind}` |
| `authors` | string[] | 个人作者名（关键作者，最多 5 个） |
| `contributors` | object[] | `[{name, type, role}]` — 机构/团队贡献方 |
| `doi` | string | DOI |
| `arxiv_id` | string | arXiv ID |
| `venue` | string | 期刊/会议/机构 |
| `url` | string | 主页 URL |
| `abstract` | string | 摘要 |

**必须**：metadata_extractions 是模型原始结果层，works 是稳定层。两者之间必须经过人工审核门禁，不能自动回填。

### analysis_runs

**职责**：文献分析运行记录。每条记录是一次对单篇文献的结构化分析（如 digest 速览卡片），结果先进入此表，审核后才被综述矩阵和综合层采信。

| 字段 | 说明 |
|---|---|
| `id` | 主键，格式 `AR-{hex}` |
| `kind` | 分析类型：`digest` / `angle` / `synthesis` |
| `angle` | 角度名，如 `digest`、`risk-definition` |
| `template_version` | 模板版本号（整数） |
| `work_id` | 关联 works（L1/L2 必填；L3 为 NULL） |
| `input_work_ids` | L3 输入集合（JSON 数组）；L1/L2 为 NULL |
| `executor` | 执行工具：`human` / `opencode` / `mimocode` / `ollama` |
| `model_name` | 使用的模型名 |
| `input_scope` | 输入范围：`full` / `head:12000` |
| `input_chars` | 输入字符数 |
| `extracted_json` | 公共信封 JSON（含 angle、template_version、work_id、fields、evidence、confidence 等） |
| `confidence` | 整体置信度：`high` / `medium` / `low` |
| `not_addressed` | 该文献对这个角度是否无话可说（0/1） |
| `review_status` | 审核状态：`pending` / `approved` / `needs_fix` / `rejected` |
| `review_note` | 审核备注 |
| `reviewed_at` | 审核时间 |
| `review_source` | 审核来源：`human` / `agent` / `batch` |
| `superseded_by` | 指向新 run id（模板升版重跑时旧 run 标记此字段） |
| `md_path` | 双写的 Markdown 文件相对路径 |
| `raw_response` | 模型原始响应 |
| `created_at` / `updated_at` | 时间戳 |

**索引**：`work_id`、`(angle, template_version)`、`review_status`。

**与 metadata_extractions 的区别**：metadata_extractions 的审核是回填门禁（approved 才写 works）；analysis_runs 的审核是采信标记（run 本身就是产品，没有"应用到 works"动作）。

**唯一性约束**：每个 `(work_id, angle, template_version)` 至多一条未 superseded 的 run。重跑通过 supersede 链追溯。

## 4. 文件系统约定

### works/{work_id}/source/

存放 PDF 源文件。摄入脚本复制文件到这里，不要手动移动。路径记录在 `source_files.source_path`。

### works/{work_id}/parsed/mineru/{source_file_id}/content.md

MinerU 解析产物。路径记录在 `literature_parse_runs.content_md_path`。后续元数据抽取以此为唯一文本入口，不重新解析 PDF。

### works/{work_id}/analyses/

分析结果 Markdown 文件。由 `scripts/literature_analyze.py --submit` 从 JSON 自动生成，文件名格式 `{date}_{angle}@v{N}.md`。JSON 为机器层真相（`analysis_runs.extracted_json`），Markdown 是人读视图。

### _archive/

归档区，存放已处理的中间产物。子目录包括：
- `dedup/`：去重归档的冗余源文件
- `ingested_inbox/`：摄入后归档的 inbox 原文件

### _quarantine/

隔离区，存放坏源或待处理文件。按 work_id 子目录隔离。`POST /api/works/{id}/quarantine` 会把源文件移到这里。

### _inbox/

新 PDF 的临时投递入口。摄入脚本扫描此目录，处理后归档到 `_archive/ingested_inbox/`。

## 5. 核心工作流

### 摄入

新 PDF 放入 `_inbox`，执行摄入脚本：

```powershell
python scripts\literature_ingest.py --execute
```

流程：扫描 inbox → 计算 sha256 → 精确重复移入 `_duplicates/exact_sha256` → 新文件复制到 `works/{work_id}/source/` → inbox 原文件归档 → 写 DB(`works`/`source_files`/`literature_parse_runs` pending 行)/index。摄入也可经前端 `/inbox`(InboxReview) dry-run + 确认，或 `POST /api/ingest/plan`·`/execute`（Phase B'）。

**不要**手动把 PDF 放入 `works/`；让摄入脚本维护 DB 一致性。

### 解析

摄入后默认只创建 `pending` 任务，不自动启动 MinerU。需要时手动触发：

```powershell
uv run python scripts\literature_batch_parse.py --library-root D:\02_academic\doctoral\literature_library --max-workers 1 --limit 3
```

建议保持保守并发（`max_workers=1`）。解析成功后 `content_md_path` 写入 `literature_parse_runs`。

### 去重

`scripts/literature_dedup.py` 分析生成 `duplicate_groups` 和 `duplicate_candidates`。精确 SHA256 重复自动确认，标题候选需人工审查。

前端 Duplicates 页面提供决策按钮：`same_work`、`not_duplicate`、`version_of`、`translation_of`、`supersedes`、`part_of`、`quarantine`。

决策写回 DB：`same_work` + `exact_sha256` 时归档冗余源文件，关系型决策写入 `work_relations`。

### 元数据抽取

基于 MinerU 输出的 `content.md`，用本地 Ollama 模型抽取结构化元数据：

```powershell
python scripts\literature_metadata_extract.py --limit 10
```

流程：读取 content.md 前 8000 字符 → 发送给 Ollama (qwen3:4b) → 解析 JSON 响应 → validator 校验字段 → 写入 `metadata_extractions`。

**必须**：抽取结果先全部进入 `metadata_extractions`，不直接回填 `works`。需要显式 `--apply` 或通过审核界面才应用。

### 元数据审核与回填

MetadataReview 页面（`/metadata`）提供人工审核门禁：

1. 顶部三行筛选：审核状态（待审/已批准/需修正/已拒绝/全部）→ 模型来源（全部/Mimo/Ollama）→ 风险等级
2. 列表项显示模型标签（紫色 Mimo / 蓝色 Ollama），便于对比同 work 的两条抽取
3. 主区显示抽取结果与当前 works 字段对比，支持逐字段编辑
4. 审核通过后**覆盖式回填** works（高/中置信度字段直接覆盖已有值）
5. 批准一条后，同 work 的其他 pending 抽取自动 supersede
6. 批量批准低风险时，同 work 的 Mimo 优先于 Ollama 应用

**审核操作流程**：

| 操作 | 含义 | 结果 | 后续 |
|---|---|---|---|
| 批准 (approved) | 抽取结果正确 | 覆盖写入 works 表 → 其他 pending supersede | 完成 |
| 需修正 (needs_fix) | 有小问题 | 在页面上直接编辑字段 → 再批准 | 无需重抽 |
| 拒绝 (rejected) | 抽取完全不对 | 不写入 works，备注必填 | 通知 Mimo 重抽 |
| 隔离 (quarantine) | 文献本身没价值 | work 隔离，所有抽取作废 | 完成 |
| 批量批准低风险 | 一键操作 | 每 work 只应用最优抽取（Mimo > Ollama） | 完成 |

**拒绝 vs 隔离的区别**：
- **拒绝** = 抽取有问题，文献有价值，需要重新抽取
- **隔离** = 文献本身没价值（404/空页面/不在范围），整个丢弃

**拒绝后的重抽取流程**：
1. 用户在页面上拒绝一条抽取，填写拒绝原因
2. 用户告知 Mimo「帮我看一下被拒绝的」
3. Mimo 读取拒绝备注，带着原因重新抽取
4. 新结果写入 `metadata_extractions`，用户在页面上看到新抽取结果

### 前端管理

Vue SPA 提供 11 个页面：

| 页面 | 路径 | 职责 |
|---|---|---|
| Dashboard | `/` | 统计总览、快捷入口 |
| Works | `/works` | 文献列表，搜索/筛选/分页，隔离/恢复操作 |
| WorkDetail | `/works/:id` | 文献详情，编辑元数据，查看 content.md，管理关系 |
| Duplicates | `/duplicates` | 去重候选组，决策按钮，合并预览 |
| Relations | `/relations` | 文献关系管理 |
| MetadataReview | `/metadata` | 元数据抽取结果审核（双模型对比、覆盖式批准） |
| ClassificationReview | `/classification` | 分类标签审核（primary_doc_type、risk_domain、method_tags 等） |
| IntakeReview | `/intake` | 采集候选审核（resolution、review_status、promote） |
| InboxReview | `/inbox` | Inbox 摄入 dry-run 预览与确认 |
| TopicsReview | `/topics` | 采集主题管理（成熟度转换、mapped_tags） |
| DiscoveryReview | `/discovery` | 受约束发现检索 run/hit 审核和 agent 回填入口（支持 topic/name/title/url/composite 模式） |

### 5.1 发现检索端到端流程

文献库的发现→摄入流水线由三个核心模块组成，按线性顺序协作：

**Stage 1 — Topic Gate（前置输入源）**
- 管理采集主题 (`collection_topics`) 及其生命周期（seedling → proposed → mapped）
- 每个主题携带结构化检索线索 (`query_def`: keywords, known_names, known_titles)
- 在 `/topics` 页面可触发 discovery plan 生成
- **角色**：不是后置分类器，而是 Discovery 的**结构化输入来源**

**Stage 2 — Discovery（受约束发现检索）**
- 基于 topic 或手动输入创建检索方案 (`search_plan_json`)
- 支持 5 种输入模式：topic / name / title / url / **composite** (V1.2)
- Agent 按 plan 执行检索，回填 `discovery_hits`
- 用户在 `/discovery` 审核 hits，执行 accept/reject
- **唯一桥梁**：`accept_hit_to_intake()` 将接受的 hit 转为 `intake_candidates`

**Stage 3 — Intake Candidates（候选审核闸门）**
- 接收来自 Discovery accept 和 Direct collect 两个来源的候选
- 统一经 light_gate（元数据查重）→ heavy_gate（SHA256 查重）→ A2 review → promote
- Promoted 候选通过 `ingest_bridge` 进入 works 正式库

**硬约束**：
- Discovery agent 只能回填 `discovery_hits`，不得写 works/intake/ontology
- Accept 后只创建 `intake_candidates(resolution='pending')`，不自动 promote
- DOI / arXiv / GitHub URL 不作为自动 discovery mode（仍走 collect 入口）
- Title-only hit 不能批量接受
- 已知 URLs 仅作 source_hint，不自动创建 hit

详见 [业务流程六：主题驱动发现检索](docs/workflows/business-flows.md#流程六主题驱动发现检索)。

## 6. API 概览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/works` | 文献列表（搜索、筛选、分页、排序） |
| GET | `/api/works/{id}` | 文献详情（含源文件、关系、重复候选、解析记录） |
| PATCH | `/api/works/{id}` | 更新文献元数据 |
| POST | `/api/works/{id}/quarantine` | 隔离文献（移文件到 _quarantine/） |
| POST | `/api/works/{id}/restore` | 恢复隔离文献 |
| GET | `/api/relations` | 所有文献关系 |
| POST | `/api/relations` | 新增关系 |
| DELETE | `/api/relations` | 删除关系 |
| GET | `/api/duplicates` | 重复组列表（含候选条目） |
| POST | `/api/duplicates/{group_id}/review` | 审查重复组决策 |
| GET | `/api/duplicates/{group_id}/merge-preview` | 预览合并推荐（得分、推荐主条目） |
| GET | `/api/files/{work_id}/content` | 获取 content.md 原文 |
| GET | `/api/files/{work_id}/pdf` | 获取 PDF 文件 |
| GET | `/api/metadata` | 元数据抽取列表（按状态/模型/风险筛选） |
| GET | `/api/metadata/{ext_id}` | 单条抽取详情 |
| PATCH | `/api/metadata/{ext_id}/review` | 审核单条抽取结果（批准/需修正/拒绝） |
| POST | `/api/metadata/apply-approved` | 批量应用已批准的抽取结果 |
| POST | `/api/metadata/batch-approve-low-risk` | 批量批准低风险待审抽取（Mimo 优先） |
| POST | `/api/metadata/{ext_id}/quarantine` | 从元数据审核页隔离文献 |
| GET | `/api/classification/tags/{work_id}` | 获取文献分类标签 |
| POST | `/api/classification/tags/{work_id}` | 创建分类标签 |
| DELETE | `/api/classification/tags/{tag_id}` | 删除分类标签 |
| GET | `/api/classification/vocab` | 分类词汇表 |
| GET | `/api/classification/extractions` | 分类抽取列表 |
| GET | `/api/classification/extractions/{ext_id}` | 分类抽取详情 |
| PATCH | `/api/classification/extractions/{ext_id}/review` | 审核分类抽取结果 |
| POST | `/api/classification/extractions/batch-approve-low-risk` | 批量批准低歧义分类抽取 |
| GET | `/api/intake/candidates` | 采集候选列表 |
| GET | `/api/intake/stats` | 采集统计 |
| POST | `/api/intake/resolve` | 触发 SHA256 门控解析 |
| PATCH | `/api/intake/candidates/{candidate_id}/review` | 审核采集候选 |
| POST | `/api/intake/promote` | 批量提升已批准候选为正式文献 |
| GET | `/api/intake/topics` | 采集主题列表 |
| POST | `/api/intake/topics` | 主题成熟度转换 |
| POST | `/api/intake/collect` | 按主题/显式 ID 发起采集 |
| POST | `/api/discovery/plan` | 生成 discovery search plan，不创建 run |
| POST | `/api/discovery/composite-plan` | 生成 composite 多信号 discovery search plan |
| POST | `/api/discovery/run` | 创建 discovery run |
| GET | `/api/discovery/runs` | 发现检索 run 列表 |
| GET | `/api/discovery/runs/{run_id}` | 查看单个 run 和 search plan |
| POST | `/api/discovery/runs/{run_id}/hits` | agent 回填 discovery hits |
| GET | `/api/discovery/hits` | 发现检索命中列表 |
| POST | `/api/discovery/hits/{hit_id}/accept` | 接受单个 hit 并创建 intake candidate |
| POST | `/api/discovery/hits/batch-accept` | 批量接受 hits 并创建 intake candidates |
| POST | `/api/discovery/hits/{hit_id}/reject` | 拒绝 hit 并记录审核备注 |
| GET | `/api/parse/status` | 解析状态汇总或单篇查询 |
| POST | `/api/parse/trigger` | 触发解析 |
| GET | `/api/ingest/plan` | 摄入 dry-run 预览 |
| POST | `/api/ingest/execute` | 执行摄入 |

## 7. CLI 工具

### literature_analyze.py

分析运行管理 CLI，支持四个子命令：

```powershell
# 生成待分析任务清单（排除 quarantined，排除已有未 superseded run）
uv run python scripts/literature_analyze.py plan --angle digest

# 提交分析结果（校验 envelope + evidence quote，写 DB + 双写 Markdown）
uv run python scripts/literature_analyze.py submit --input _analysis_outbox/digest/ --strict

# 查看各角度覆盖率和审核状态分布
uv run python scripts/literature_analyze.py status

# 审核单条 run
uv run python scripts/literature_analyze.py review AR-xxx --mark approved --note "LGTM"
```

`--strict` 模式：submit 时校验 evidence quote 是否为 content.md 的子串，不匹配则拒绝提交。

## 8. 前端页面

见第 5 节"前端管理"表格。前端通过 `web/src/api.js` 封装所有 API 调用，所有请求走 `/api` 前缀。

侧边栏导航：总览 → 文献 → 去重 → 关系 → 元数据 → 分类。

## 9. 质量护栏

- **健康检查**：`scripts/healthcheck_library.py --json` 是 V1 当前健康检查入口，覆盖孤儿文件、phantom DB 路径、work dir 无 DB、quarantine/source 状态不一致、dangling refs，并提供可选修复模式。旧 `literature_healthcheck.py` 已归档到 `scripts/_archive/`，仅作历史参考。
- **测试**：`uv run pytest` 或 `.venv\Scripts\python.exe -m pytest tests\ -q` 运行全部测试。V1 发布复核为 348 passed / 7 skipped；`parser/tests/` 为 parser 子项目 smoke 测试；旧测试已归档至 `parser/tests_legacy/`。
- **不直接删除文件**：所有删除操作都是归档（`_archive/`）或隔离（`_quarantine/`）。
- **不绕过 DB 移动源文件**：文件移动必须同步更新 `source_files.source_path` 与 `source_files.status`。
- **metadata_extractions 先审后回填**：模型抽取结果不自动写入 works，必须经过审核门禁。
- **analysis_runs 先入库后采信**：模型输出先进入 analysis_runs，审核后才被矩阵和综合层默认采信。
- **WAL 模式**：SQLite 使用 WAL 日志模式，支持并发读。

## 10. 当前限制

- 仍无"直接前端文件上传到 work"端点；新增文献经 `_inbox/` 摄入——现已有前端入口 `/inbox`(InboxReview，dry-run+确认，Phase B')，也可命令行或 `POST /api/ingest/*`。
- 摄入后不自动触发解析，需手动触发：CLI `python scripts/literature_batch_parse.py --execute`、API `POST /api/parse/trigger`、或 WorkDetail 按钮（经 `parser/` 子项目二元路由：PyMuPDF 本地 / MinerU cloud vlm）。
- `year` 暂不自动回填，因为模型容易误提取会议年份或修订日期。
- 综述矩阵导出（`scripts/literature_matrix.py`）、分析 API（`GET /api/works/{id}/analyses`）、分析页面尚未实现。
- 引用导出（BibTeX/RIS）尚未实现。
- `index.json` 是历史产物、`parse_ledger.json` 已废弃归档（解析状态以 `literature_parse_runs` 表为准，Phase D），新功能应优先查询 SQLite。
- 前端路由已改为惰性加载（`router.js`），构建产物按页面拆分 chunk，避免单 chunk 过大。
- 隔离/恢复路径已收敛到共享 nucleus `api/quarantine.py`。新 quarantine 操作必须保持 `works.read_status`、`source_files.source_path`、`source_files.status` 一致；以 `healthcheck_library.py` 复核为准。
- P1.1 全库 digest 尚未批量生成（当前 5/112 覆盖率）。

## 11. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-06-14 | P1.1 AnalysisRun 基础设施：`analysis_runs` 表、`literature_analyze.py`（plan/submit/status/review）、`digest@v1` 模板、`test_analysis_runs.py`（16 tests）、healthcheck 扩展 6 项检查、5 篇 digest 试跑；测试隔离修复（LIBRARY_ROOT patch）；restore 清理空 quarantine 目录 |
| 2026-06-14 | 分类积压清空（119 approved / 0 pending）；词汇表同步（1842 tags）；confidence 合并修复；去重系统增强；WorkDetail 重构；数据一致性修复 |
| 2026-06-08 | 双模型支持（Ollama + Mimo 2.5 Pro）；覆盖式批准+supersede；模型 tab 过滤；works 新增 contributors/publication_date_json/分类字段；TECHNICAL_OVERVIEW 全面更新 |
| 2026-06-05 | 初始版本。基于 Phase 0–4 完成状态和 P1.0/P1.0c 实现生成。 |
