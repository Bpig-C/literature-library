# 文献库技术说明

> 更新时间：2026-06-08
> 适用版本：Phase 0–4 已完成，P1.0 元数据抽取+审核+分类审核已完成，双模型（Ollama + Mimo 2.5 Pro）支持
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
| PDF 解析 | MinerU / document-parser | 18200 / 18201 |
| 元数据抽取 | Ollama (qwen3:4b) | 11435 |

### 目录结构

```text
literature_library/
  literature.sqlite          # 主数据库，逻辑关系中心
  index.json                 # 前端/脚本可读的文献索引（历史产物，新功能优先查 DB）
  parse_ledger.json          # MinerU 解析任务账本
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
  scripts/                   # 本地维护脚本
  api/                       # FastAPI 后端
  web/                       # Vue 3 前端 SPA
  tests/                     # 测试
  views/                     # 历史 HTML 台账（已被 SPA 替代）
```

### SQLite 作为逻辑中心

所有文献的元数据、解析状态、重复关系、文献间关联都记录在 `literature.sqlite` 中。文件系统只负责存储物理文件，不做逻辑查询。

### FastAPI 后端

`api/main.py` 启动 FastAPI 应用，挂载 5 组路由。生产模式下同时托管 Vue 构建产物。CORS 允许 `localhost:19528`。

### Vue 前端

单页应用，6 个页面：Dashboard、Works、WorkDetail、Duplicates、Relations、MetadataReview。通过 `/api` 前缀与后端通信。

### MinerU / content.md 解析链路

PDF → MinerU (端口 18200) → document-parser (端口 18201) 封装 → 输出 `content.md` + `content.json`。解析结果路径记录在 `literature_parse_runs.content_md_path`，后续所有文本处理（元数据抽取、全文分析）都以这个路径为入口，不重新解析 PDF。

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
| `parse_status` | 解析状态 | 解析脚本 |
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

## 4. 文件系统约定

### works/{work_id}/source/

存放 PDF 源文件。摄入脚本复制文件到这里，不要手动移动。路径记录在 `source_files.source_path`。

### works/{work_id}/parsed/mineru/{source_file_id}/content.md

MinerU 解析产物。路径记录在 `literature_parse_runs.content_md_path`。后续元数据抽取以此为唯一文本入口，不重新解析 PDF。

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

流程：扫描 inbox → 计算 sha256 → 精确重复移入 `_duplicates/exact_sha256` → 新文件复制到 `works/{work_id}/source/` → inbox 原文件归档 → 写 DB/index/ledger → parse_ledger 新增 `pending` 条目。

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

Vue SPA 提供 7 个页面：

| 页面 | 路径 | 职责 |
|---|---|---|
| Dashboard | `/` | 统计总览、快捷入口 |
| Works | `/works` | 文献列表，搜索/筛选/分页，隔离/恢复操作 |
| WorkDetail | `/works/:id` | 文献详情，编辑元数据，查看 content.md，管理关系 |
| Duplicates | `/duplicates` | 去重候选组，决策按钮 |
| Relations | `/relations` | 文献关系管理 |
| MetadataReview | `/metadata` | 元数据抽取结果审核（双模型对比、覆盖式批准） |
| ClassificationReview | `/classification` | 分类标签审核（primary_doc_type、risk_domain、method_tags 等） |

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
| GET | `/api/files/{work_id}/content` | 获取 content.md 原文 |
| GET | `/api/files/{work_id}/pdf` | 获取 PDF 文件 |
| GET | `/api/metadata` | 元数据抽取列表（按状态/模型/风险筛选） |
| GET | `/api/metadata/{ext_id}` | 单条抽取详情 |
| PATCH | `/api/metadata/{ext_id}/review` | 审核单条抽取结果（批准/需修正/拒绝） |
| POST | `/api/metadata/apply-approved` | 批量应用已批准的抽取结果 |
| POST | `/api/metadata/batch-approve-low-risk` | 批量批准低风险待审抽取（Mimo 优先） |

## 7. 前端页面

见第 5 节"前端管理"表格。前端通过 `web/src/api.js` 封装所有 API 调用，所有请求走 `/api` 前缀。

侧边栏导航：总览 → 文献 → 去重 → 关系 → 元数据 → 分类。

## 8. 质量护栏

- **健康检查**：`scripts/literature_healthcheck.py` 一次性检查 DB 记录、PDF 路径、content_md_path、ledger、index 的一致性，输出报告到 `views/healthcheck.md`。
- **API 测试**：`tests/test_api.py` 使用临时 DB 副本测试核心 API 端点，不会修改真实数据。运行：`uv run python -m pytest tests/test_api.py -v`。
- **不直接删除文件**：所有删除操作都是归档（`_archive/`）或隔离（`_quarantine/`）。
- **不绕过 DB 移动源文件**：文件移动必须同步更新 `source_files.source_path`。
- **metadata_extractions 先审后回填**：模型抽取结果不自动写入 works，必须经过审核门禁。
- **WAL 模式**：SQLite 使用 WAL 日志模式，支持并发读。

## 9. 当前限制

- 没有前端上传入口，新增文献仍依赖 `_inbox` + 命令行摄入。
- 摄入后不自动触发解析，需手动启动 document-parser/MinerU。
- `year` 暂不自动回填，因为模型容易误提取会议年份或修订日期。
- `analysis_runs`、`collections`、`work_collections` 表尚不存在，无分析运行和综述矩阵功能。
- 标签/主题/集合仍未进入可用工作流。
- 引用导出（BibTeX/RIS）尚未实现。
- API 与前端测试覆盖不足，尚无端到端回归。
- `index.json` 和 `parse_ledger.json` 是历史产物，新功能应优先查询 SQLite。
- 分类审核（ClassificationReview）支持批量操作（batch-approve-low-risk、batch-approve-with-tag）和自动回填。
- `analysis_runs` 表尚不存在，分析运行和综述矩阵未启动。

## 10. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-06-14 | 分类积压清空（119 approved / 0 pending）；词汇表同步（1842 tags）；confidence 合并修复；去重系统增强；WorkDetail 重构；数据一致性修复 |
| 2026-06-08 | 双模型支持（Ollama + Mimo 2.5 Pro）；覆盖式批准+supersede；模型 tab 过滤；works 新增 contributors/publication_date_json/分类字段；TECHNICAL_OVERVIEW 全面更新 |
| 2026-06-05 | 初始版本。基于 Phase 0–4 完成状态和 P1.0/P1.0c 实现生成。 |
