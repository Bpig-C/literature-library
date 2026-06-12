# 文献库未来工作计划

> 更新日期：2026-06-13  
> 最近审核：2026-06-13，分类系统 Phase 1-3 已完成，阶段 0（分类积压清理）已完成；数据库含 138 works、260 metadata_extractions、373 classification_extractions、1374 classification_tags；`python -m pytest tests/test_api.py` 为 81 passed、4 skipped。  
> 依据：`D:\02_academic\doctoral\LITERATURE_SYSTEM_PLAN.md`、当前仓库代码、`literature.sqlite`、`index.json`、`parse_ledger.json`  
> 定位：本文件是当前项目内的后续执行计划；外部规划文档保留为设计背景和历史路线依据。

## 1. 当前状态核对

### 1.1 总体判断

项目已经从外部规划文档中 2026-06-04 的状态继续向前推进。外部文档仍有参考价值，尤其是系统目标、架构原则、目录约定、去重策略、摄入流水线、AnalysisRun 设计和关键约束；但其中关于 Phase 1、Phase 3、Phase 4 的实施状态已经落后于当前项目。

当前项目已具备：

- 本地稳定存储：`works/`、`_inbox/`、`_duplicates/`、`_quarantine/`、`_archive/` 已存在。
- 主数据库：`literature.sqlite` 当前有 138 个 `works`、151 条 `source_files`（140 active + 11 archived）、569 条 `parse_artifacts`、140 条 `literature_parse_runs`、260 条 `metadata_extractions`、373 条 `classification_extractions`、1374 条 `work_classification_tags`。
- 解析账本：`parse_ledger.json` 共 140 条，全部 `succeeded`。
- 活跃 PDF：`works/*/source/*.pdf` 共 140 个。
- MinerU 全文：140 条成功解析记录均有 `content_md_path`，实际路径为 `works/{work_id}/parsed/mineru/{source_file_id}/content.md`。
- API 后端：FastAPI 已提供 `/api` 路由组，包含 works、metadata、classification、relations 等完整 API。
- 前端：Vue 3 SPA 已提供 Dashboard、Works、WorkDetail、Duplicates、Relations、MetadataReview、ClassificationReview 七个页面。
- 摄入 MVP：`scripts/literature_ingest.py` 已存在，并有 `tests/test_literature_ingest.py` 覆盖新 PDF 摄入和精确重复归档。
- 去重闭环：重复候选已审查，same_work/exact_sha256 冗余源文件已归档，关系型重复已写入 `work_relations`。
- 元数据增强与审核：`scripts/literature_metadata_extract.py` 已完成基于 MinerU `content.md` 的批量抽取，138 篇文献均已写入 `metadata_extractions`；MetadataReview 已具备风险分级、低风险批量通过、原文/PDF 预览、人机修正闭环和审核页隔离闭环。
- 分类系统：已完成分类本体 v0.2 实施，包括 `works` 表扩展字段（primary_doc_type、publication_status、ingestion_state、priority 等）、`work_classification_tags` 多值标签表、`classification_extractions` 候选表；`scripts/literature_classification_extract.py` 已完成批量抽取；ClassificationReview 页面已实现审核、编辑、保存草稿、隔离等功能。阶段 0（分类积压清理）已完成：每个 work 有 3 个模型候选（mimo2.5pro、mimo-claude、qwen3:4b），批量通过后每个 work 保留 1 个最优 approved extraction（mimo2.5pro > mimo-claude > qwen3:4b），当前状态：approved 119 / pending 125（缺 evidence）/ rejected 129（含 superseded）。

## 1. 当前状态核对

### 1.1 总体判断

项目已经从外部规划文档中 2026-06-04 的状态继续向前推进。外部文档仍有参考价值，尤其是系统目标、架构原则、目录约定、去重策略、摄入流水线、AnalysisRun 设计和关键约束；但其中关于 Phase 1、Phase 3、Phase 4 的实施状态已经落后于当前项目。

当前项目已具备：

- 本地稳定存储：`works/`、`_inbox/`、`_duplicates/`、`_quarantine/`、`_archive/` 已存在。
- 主数据库：`literature.sqlite` 当前有 138 个 `works`、151 条 `source_files`（140 active + 11 archived）、569 条 `parse_artifacts`、140 条 `literature_parse_runs`、260 条 `metadata_extractions`、373 条 `classification_extractions`、1120 条 `work_classification_tags`。
- 解析账本：`parse_ledger.json` 共 140 条，全部 `succeeded`。
- 活跃 PDF：`works/*/source/*.pdf` 共 140 个。
- MinerU 全文：140 条成功解析记录均有 `content_md_path`，实际路径为 `works/{work_id}/parsed/mineru/{source_file_id}/content.md`。
- API 后端：FastAPI 已提供 `/api` 路由组，包含 works、metadata、classification、relations 等完整 API。
- 前端：Vue 3 SPA 已提供 Dashboard、Works、WorkDetail、Duplicates、Relations、MetadataReview、ClassificationReview 七个页面。
- 摄入 MVP：`scripts/literature_ingest.py` 已存在，并有 `tests/test_literature_ingest.py` 覆盖新 PDF 摄入和精确重复归档。
- 去重闭环：重复候选已审查，same_work/exact_sha256 冗余源文件已归档，关系型重复已写入 `work_relations`。
- 元数据增强与审核：`scripts/literature_metadata_extract.py` 已完成基于 MinerU `content.md` 的批量抽取，138 篇文献均已写入 `metadata_extractions`；MetadataReview 已具备风险分级、低风险批量通过、原文/PDF 预览、人机修正闭环和审核页隔离闭环。
- 分类系统：已完成分类本体 v0.2 实施，包括 `works` 表扩展字段（primary_doc_type、publication_status、ingestion_state、priority 等）、`work_classification_tags` 多值标签表、`classification_extractions` 候选表；`scripts/literature_classification_extract.py` 已完成批量抽取；ClassificationReview 页面已实现审核、编辑、保存草稿、隔离等功能。

仍未落地或明显不足：

- `analysis_runs`、`collections`、`work_collections` 表尚不存在。
- 尚无分析运行脚本、分析 API、分析页面、综述矩阵导出。
- 尚无前端上传/`POST /api/works`，新增文献仍依赖 `_inbox` + 命令行摄入。
- 摄入脚本只创建 `pending` 解析任务，不自动触发 document-parser/MinerU。
- 分类系统 Phase 4（废弃旧 `doc_type` + Dashboard 统计升级）未启动，blocked: coverage 48.6% < 95%。
- 标签/主题/集合（Collections）仍未进入可用工作流。
- 引用导出（BibTeX/RIS）尚未实现。
- 视图层 `views/*.md` 自动生成尚未恢复；当前 `views/` 主要保留 HTML dashboard。
- API 与前端测试覆盖不足，尚无端到端回归。

## 2. 按外部规划逐项核对

### 2.1 背景与目标

规划中的核心目标仍然成立：稳定物理存储、SQLite 作为逻辑中心、前端台账、后续结构化分析。当前已经完成“看见并管理文献”的主要路径，但“标签/主题由数据库管理”和“多角度结构化分析”还没有真正开始。

### 2.2 架构决策

“物理位置与逻辑关系分离”的原则已基本贯彻。`works/{work_id}/source/` 承担稳定源文件存储，关系和候选重复进入 SQLite。

需要注意：规划中示例路径 `works/{work_id}/parsed/content.md` 与当前实际路径不一致。当前应以数据库中的 `literature_parse_runs.content_md_path` 为准，不能在新功能里硬编码 `parsed/content.md`。

### 2.3 目录结构

核心目录已经存在。当前差异：

- `_quarantine/` 中已有 `bad_source/` 目录。
- `views/` 目前包含 `library_dashboard.html` 和 `dedup_dashboard.html`，不是规划中的主题 Markdown 视图。
- `works/{work_id}/analyses/` 目录约定尚未成为运行机制。

### 2.4 Work ID 方案

当前库已经使用 `W-arxiv-*`、`W-sha-*` 等 ID。后续新增摄入应继续沿用既有 `scripts/literature_ingest.py` 的 ID 生成逻辑，并补充 DOI/CrossRef/arXiv 元数据增强，而不是另起规则。

### 2.5 SQLite 对象模型

已存在：`works`、`source_files`、`parse_artifacts`、`duplicate_groups`、`duplicate_candidates`、`work_relations`、`literature_parse_runs`、`work_codes` 等。

缺失：`collections`、`work_collections`、`analysis_runs`。

已扩展：`works` 已包含 `title_zh`、`venue`、`url`、`abstract`，并新增 `metadata_extractions` 保存模型抽取原始结果、证据、置信度和应用状态。后续更稳的结构化落点是 `work_authors`、`work_institutions`、审核状态表或审核字段。

### 2.6 去重策略

精确重复和标题候选已进入数据库。当前 `duplicate_groups` 为 13 组，`duplicate_candidates` 为 30 条，候选均已审查；前端 Duplicates 页面和 Relations 页面可用。去重决策已从 localStorage/导出 JSON 推进为 API 写回：`same_work`/`exact_sha256` 冗余 `source_files` 归档，关系型决策写入 `work_relations`，Works/WorkDetail 能显示有效源文件数和归档源文件。

后续可增强的是“审计与解释层”：

- 在 UI 中更清晰展示每种关系类型的语义和来源。
- 为去重决策保留更完整的操作人、时间、原始候选快照。
- 与 MetadataReview 一样，形成可抽样复核的质量面板。

### 2.7 摄入流水线

Phase 1 MVP 已实现为命令行脚本。当前能力包括扫描 `_inbox`、sha256 去重、复制到 `works/`、归档 inbox、写 SQLite/index/ledger。

仍缺 S6-S8 的自动解析闭环：摄入后不会自动提交 document-parser/MinerU，只会创建 `pending` 任务。下一步应把“摄入”和“解析 pending”串成一个可选命令或 API 工作流。

### 2.8 nature-skills 集成

目前还没有实际集成。外部规划中关于 `nature-reader`、`nature-citation`、`nature-writing`、`nature-academic-search` 的设计仍有价值，但应从最小闭环开始：

- 先建立 `analysis_runs` 数据结构和本地分析结果写入规范。
- 再接入具体 reader/writing/citation 工具。

### 2.9 前端设计

当前实际实现已经超过外部文档中的 Phase 3 初始状态：

- Dashboard：统计卡片和快捷入口已完成。
- Works：搜索、筛选、分页、解析列、隔离/恢复操作已完成。
- WorkDetail：元数据编辑、源文件、关联管理、重复候选、content.md、隔离/恢复已完成。
- Duplicates：候选组、决策按钮、localStorage、筛选、统计、导出 JSON 已完成。
- Relations：表格、新增、删除已完成。

仍缺规划中的：

- 标签/主题多选过滤。
- 笔记 `notes/reading.md` 内联编辑。
- 分析列表和分析详情。
- 综述矩阵页面。
- 前端上传入口。

### 2.10 技术栈与约束

当前技术栈为 FastAPI + SQLite + Vue 3 + Vite + uv，与规划兼容。约束仍应继续遵守：

- 不删文件，只归档或隔离。
- 不手动移动 `works/` 下源文件，文件移动必须同步 DB/index/ledger。
- `views/` 作为生成产物，不作为人工长期维护入口。
- MinerU 按需启动，并保持保守并发。

## 3. 后续优先级

### P0：状态基线与质量护栏 ✅ 已完成

目标：把当前已经做出的 Phase 1/3/4 成果稳定下来，避免后续开发踩到隐含状态差异。

交付物：

- ✅ 新增只读健康检查脚本 `scripts/literature_healthcheck.py`。
- ✅ 检查 DB 记录、PDF 路径、`content_md_path`、ledger、index 的一致性。
- ✅ 检查 `_inbox` pending、`_quarantine`、已 review duplicate、孤儿 source/artifact。
- ✅ 输出 Markdown/JSON 报告到 `views/healthcheck.md`。
- ✅ 为现有 API 路由增加基础测试 `tests/test_api.py`，覆盖列表、详情、文件 content、重复组、关系增删。

验收标准：

- ✅ 能一条命令回答”当前库是否一致、是否有 pending/缺文件/孤儿记录”。
- ✅ 在不启动前端的情况下，能验证后端核心 API 不回归。

建议顺序：最先做。它会让后面的分析、上传、自动解析更稳。

### P1：元数据增强、分析运行与综述矩阵

目标：先把每篇文献的基础书目信息补齐，再让已有 140 篇全文开始产出综述材料。

这一阶段拆成三个连续小步：

- P1.0：元数据增强。给每篇文献补齐“身份证”：日期、作者、单位、标题、摘要、DOI/arXiv、venue、URL 等。
- P1.0c：元数据审核门禁。把模型抽取结果人工抽样审核后，再安全回填 `works`。
- P1.1：分析运行。围绕一个明确角度阅读单篇文献，并把结构化结果保存为 AnalysisRun。
- P1.2：综述矩阵。把多篇文献在同一批角度下的分析结果横向排成表，用于综述写作。

#### P1.0：基于 MinerU content.md 的元数据增强 ✅ 抽取入库已完成

原则：不直接把 PDF 交给模型，也不重新做 PDF 前几页解析。当前项目已经通过 MinerU 生成了 `content.md`，后续抽取应以 `literature_parse_runs.content_md_path` 指向的 Markdown 为唯一文本入口。

输入策略：

- 从数据库读取每个 work 的最新成功 `content_md_path`。
- 读取 `content.md` 的前部片段，默认控制在约前五页对应的信息范围内。
- “前五页”在 Markdown 中不是天然分页，因此第一版建议采用稳妥近似：从文档开头截取固定字符/token 预算，例如 12k-16k token 内，覆盖标题、作者、单位、摘要、引言开头。
- 如果 MinerU 输出中有页码、标题层级或 page 标记，后续再升级为真正的前五页切片。
- 若前部片段找不到作者/单位/年份，默认标记低置信或未提及，不强行让模型从全文后部猜测。

本地模型配置参考：

- 参考脚本：`D:\06_tools\zh-asr-offline\local_model\batch_meeting_docs.py`
- Ollama URL：`http://localhost:11435`
- 默认模型：`qwen3:4b-instruct-2507-q4_K_M`
- 建议 `num_ctx=16384`
- 建议 `temperature=0.2`
- 输出要求：只输出 JSON，不输出解释性正文。

当前抽取字段：

```json
{
  "title": "",
  "title_zh": "",
  "date": {
    "year": null,
    "month": null,
    "day": null,
    "raw": "",
    "kind": "exact/inferred"
  },
  "authors": [
    {
      "name": "",
      "affiliations": [""],
      "email": ""
    }
  ],
  "all_authors": [],
  "author_count": null,
  "institutions": [
    {
      "name": "",
      "country_or_region": "",
      "type": "university/company/government/lab/unknown"
    }
  ],
  "doi": "",
  "arxiv_id": "",
  "venue": "",
  "url": "",
  "abstract": "",
  "evidence": {
    "title": "",
    "date": "",
    "authors": "",
    "institutions": "",
    "abstract": ""
  },
  "confidence": {
    "title": "high/medium/low",
    "date": "high/medium/low",
    "authors": "high/medium/low",
    "institutions": "high/medium/low",
    "abstract": "high/medium/low"
  },
  "missing": []
}
```

建议数据落点：

- ✅ 新增 `metadata_extractions` 表，保存每次模型抽取的原始 JSON、模型名、输入范围、置信度、是否已应用。
- ✅ 扩展 `works` 字段：`title_zh`、`venue`、`url`、`abstract`。
- 作者/单位第一版可以继续写入 `works.authors` JSON；更稳的长期结构是新增 `work_authors` 和 `work_institutions`。
- 当前策略：抽取结果先全部进入 `metadata_extractions`，不直接回填 `works`；`year` 暂不自动回填，避免把会议年份、修订日期或网页更新时间写入稳定层。

建议命令行工具：

- ✅ `scripts/literature_metadata_extract.py`
- ✅ 支持 `--limit`、`--work-id`、`--no-write`、`--apply`、`--apply-only`、`--overwrite`、`--force`、`--output`。
- ✅ 默认抽取并写入 `metadata_extractions`，不回填 `works`；需要显式 `--apply` 或 `--apply-only` 才应用。

P1.0 验收标准：

- ✅ 已对 138 篇文献生成结构化元数据并写入 `metadata_extractions`。
- ✅ 每条结果包含证据片段、字段级置信度、输入路径、输入长度和校验警告。
- ✅ 作者最多 5 个关键作者进入 `authors`，完整名单进入 `all_authors`，避免审核界面过载。
- ✅ `missing` 由 validator 根据最终字段值重算，不再信任模型原始输出。
- ⏳ 高置信字段尚未回填 `works`，需先完成 P1.0c 审核门禁。

**P1.0 交付物**：`scripts/literature_metadata_extract.py`，Schema migration（metadata_extractions 表 + works 扩展字段），healthcheck 覆盖率检查，WorkDetail 新字段展示。使用本地 Ollama qwen3:4b 模型，/no_think 模式，key-author 提取（最多 5 个，完整列表进入 `all_authors`），URL/机构类型/missing 由 validator 兜底清洗。

#### P1.0c：元数据抽取后的人工审核门禁 ✅ 第一版已完成

P1.0 的正式批量抽取已经写入 `metadata_extractions`，尚未回填 `works`。`metadata_extractions` 是模型原始结果与证据层；`works` 是日常检索、排序、综述矩阵会直接依赖的稳定层。两者之间需要一个人工抽样审核门禁，确认抽取质量足够后再执行回填。

建议正式抽取流程：

1. 从 `metadata_extractions` 读取最新未应用结果，生成审核队列。
2. 人工抽样审核：优先抽查日期、作者/团队作者、机构类型、URL、DOI/arXiv、venue、missing、evidence 与 confidence 是否一致。
3. 审核通过后，才执行安全回填：默认只填空字段，不覆盖已有人工字段；`year` 暂不自动回填，避免把会议年份、修订日期或网页日期写入 `works.year`。
4. 审核不通过时，先修 Prompt/validator，再用 `--force --work-id` 或批量 `--force` 对问题文献重新抽取。

已完成审核界面第一版：

- 页面名称：MetadataReview，可从侧边栏进入。
- 左侧列表按 `pending` / `approved` / `needs_fix` / `rejected` 状态筛选。
- 主区显示抽取结果与当前 `works` 字段对比，支持逐字段编辑候选值。
- 作者区默认显示 `authors` 中的最多 5 个关键作者；如果模型抽取了更长列表，则完整列表保存在 `all_authors`，审核界面提供展开查看，不直接铺满主界面。
- 侧边栏固定显示审查清单，内容可编辑并保存在本地或 DB：
  - 日期是否为文献发布日期，而不是会议年份、修订日期、网页更新时间。
  - 作者是否为关键作者；`all_authors` 是否仅作为完整名单参考；团队作者是否需要标记为 group author。
  - 机构名称、国家/地区、类型是否合理；公司、政府、实验室、大学不要混淆。
  - URL 是否为论文主页、arXiv abs、DOI landing 或 publisher 页面，不使用新闻、license、GitHub、补充材料链接。
  - DOI、arXiv、venue、URL 为空时，`missing` 是否同步列出。
  - evidence 是否能支持高置信字段；不能支持时降级或标记待复核。
- 支持抽样审核和批量门禁：按比例抽样、按风险字段筛选、标记 `approved` / `needs_fix` / `rejected`。
- 通过审核后再提供“应用到 works”动作，默认只填空字段；覆盖已有字段必须显式开启。

#### P1.0d：元数据审核优先级与批量通过策略 ✅ 第一版已完成

MetadataReview 已为每条 `metadata_extractions` 提供风险分级与低风险批量通过入口，用来把人工审核精力集中到高风险抽取结果。后续仍可增强抽样策略和风险规则，但第一版调度闭环已经可用。

建议风险等级：

- `low`：可批量审核。所有核心字段置信度为 high；无 validation_warnings；`missing` 只包含 DOI/venue/title_zh 等常见缺失；URL 为空或为 arXiv/DOI/publisher；机构类型已规范；抽取标题与当前标题高度相似。
- `medium`：建议抽样审核。存在少量非核心字段缺失；date 只有 year 或 kind=inferred；机构/作者是团队作者；URL 为项目主页或非 arXiv 论文主页；当前值与抽取值有轻微差异。
- `high`：必须人工审核。存在 validation_warnings；title 缺失或当前标题与抽取标题差异大；date 证据像会议年份、修订日期或网页更新时间；URL 像新闻、license、GitHub、补充材料；authors 为空或被截断到 `all_authors`；机构类型为 unknown；DOI/arXiv 格式异常；abstract 为空或明显不是摘要。

建议评分信号：

- 字段级 confidence：title/date/authors/institutions/abstract 任一 low 提高风险。
- validator warnings：任何 warning 至少 medium，URL/DOI/arXiv 被清空至少 high。
- missing 字段：title/date/authors/institutions/abstract 缺失为 high；doi/venue/title_zh 缺失通常为 low。
- 一致性：当前 `works.title` 与抽取 title 差异大为 high；work_id 是 `W-arxiv-*` 但 arxiv_id 为空或不匹配为 medium/high。
- 日期语义：date.raw 包含 `updated`、`revised`、`accessed`、会议名或网页日期时提高风险。
- URL 来源：arXiv abs/DOI/publisher 为低风险；项目主页为 medium；新闻、license、GitHub、supplement 为 high 或直接置空。
- 作者复杂度：`all_authors` 长、团队作者、机构作者、作者为空都提高风险。

建议界面行为：

- 列表增加 `risk_level`、`risk_score`、`risk_reasons`，默认按 high -> medium -> low 排序。
- 增加筛选：风险等级、缺失核心字段、URL 风险、日期风险、机构 unknown、存在 warnings。
- 支持“批量批准低风险 pending”：只对 `risk_level=low` 且无人工编辑冲突的记录执行。
- 中风险采用抽样审核：例如每 10 条抽 2 条；抽样失败时整组转为 high 或 needs_fix。
- 高风险逐条审核，侧边栏优先显示触发风险的具体原因。
- 每条记录保留风险快照，避免后续规则变化导致历史审核解释丢失。

#### P1.0e：审核页联动本地文档预览 ✅ 第一版已完成

MetadataReview 已联动本地解析产物和 PDF 预览，形成“字段候选 + 证据 + 原文”的横向对照。后续可继续优化证据定位体验，但第一版审核辅助已经可用。

建议第一版：

- 复用现有 `/api/files/{work_id}/content`，在审核详情中增加 `content.md` 预览面板。
- 点击 evidence 字段时，在预览面板中搜索并滚动到对应片段；找不到时提示“证据未在当前切片中定位”。
- 预览面板支持 Markdown/纯文本切换、搜索、只看前部片段/全文切换。
- PDF 预览可先复用 `/api/files/{work_id}/pdf` 作为“打开 PDF”或 iframe；如果浏览器 PDF 体验不稳定，优先保证 `content.md` 预览。
- 后续再考虑 MinerU `content.json`、图片和 package 中的版面信息，做更接近 PDF 的版面预览；不要在第一版强依赖复杂 layout。

验收标准：

- 审核人员能在同一页面看到字段候选、证据片段和原文位置。
- 日期、作者、机构、摘要等核心字段的 evidence 可一键定位或搜索。
- 不破坏现有 PDF/content API，也不复制解析产物。

#### P1.0f：人机共用的审核修正闭环 ✅ 核心闭环已完成

本项目默认是 agent 可操控的 CLI + 人类审核界面共用模式。`approved`、`needs_fix`、`rejected` 不只是 UI 状态，也应成为后续 agent 执行修复、重抽、回填的任务入口。

建议状态语义：

- `approved`：人或低风险批量策略认可候选值，可执行填空式回填 `works`；默认不覆盖已有人工字段，不回填 `year`。
- `needs_fix`：候选值部分可用但需要修正。优先由人直接编辑候选字段；人工编辑过的字段应视为 `human-confirmed`，在后续 approved/apply 时可作为高可信来源回填 `works`。如果属于系统性错误，agent 根据 review_note 调整 Prompt/validator/risk 规则，并对相关 work 执行重抽。
- `rejected`：本次抽取不可信或不适用，不回填 `works`。保留原始抽取与拒绝原因，供后续 agent 汇总错误模式。

建议 agent 工作流：

1. 定期读取 `needs_fix` / `rejected` 队列，按 `review_note`、`risk_reasons`、validation warnings 聚类。
2. 对单篇问题，使用 `scripts/literature_metadata_rerun.py --ext-id ... --rerun` 或 `--work-id ... --rerun` 真正调用 Ollama 重抽；对批量模式问题，先修 Prompt/validator/risk，再小批量 canary。
3. 支持字段级重抽，例如 `--fields title,date,url`。模型仍返回完整 JSON，但系统只用新结果覆盖指定字段，其他字段沿用旧 extraction，降低局部修复造成的扰动。
4. 重抽后生成新的 `metadata_extractions` 记录，旧记录写入 `superseded_by` 并保留为审计历史；API `POST /metadata/{ext_id}/supersede` 仅用于外部已提供替换字段的手工 supersede，不负责调用模型。
5. 对已人工编辑并 approved 的记录，执行安全回填；对 rejected 记录不自动重试，除非用户或 agent 明确创建修复任务。

后续可增加字段：

- `review_source`: `human` / `agent` / `batch_low_risk`
- `fix_action`: `edited` / `prompt_updated` / `validator_updated` / `rerun_requested` / `quarantined`
- `superseded_by`: 指向新一轮 extraction id
- `review_assignee` 或 `agent_task_id`

已完成实现要点：

- 人工在 MetadataReview 中编辑过的字段会被视为 `human-confirmed`，对应 `confidence_json[field]` 提升为 `high`；后续 approved/apply 可安全回填 `works`。
- `_apply_single` 按当前 extraction id 标记 `applied`，不会误伤同一 work 的历史、拒绝或 superseded 记录。
- `scripts/literature_metadata_rerun.py` 已支持真重抽：调用 Ollama 生成新的 `metadata_extractions` 记录，并将旧记录写入 `superseded_by`。
- 支持字段级重抽：`--fields title,date,url`。模型仍返回完整 JSON，但系统只用新结果覆盖指定字段，其他字段沿用旧 extraction，降低局部修复扰动。
- API `POST /metadata/{ext_id}/supersede` 调整为“外部已提供替换字段”的手工 supersede；真正模型重抽走 CLI，避免无字段时复制旧记录形成假新版本。
- 测试覆盖人工编辑回填、applied 精确标记、fix_action、supersede 写链路和 supersede 参数约束。

常用命令：

```powershell
# 查看 needs_fix 队列和错误模式聚类
python scripts\literature_metadata_rerun.py --status needs_fix --limit 20

# 对指定 extraction 真重抽
python scripts\literature_metadata_rerun.py --ext-id ME-xxxx --rerun

# 只重抽部分字段，并创建 superseding extraction
python scripts\literature_metadata_rerun.py --ext-id ME-xxxx --fields title,date,url --rerun

# 只预览，不写数据库
python scripts\literature_metadata_rerun.py --ext-id ME-xxxx --fields url --rerun --no-write --json
```

#### P1.0g：审核页隔离文献/文件闭环 ✅ 已完成并审核通过

MetadataReview 不仅是元数据质量审核页，也承担“来源是否应该留在主库”的质量闸门。审核人员在查看字段、证据和原文时，如果发现该 PDF 是误收、坏源、重复残留、非目标材料、质量过低或不应进入当前综述范围，可以在同一页面直接隔离，而不需要跳转到 Works/WorkDetail 再处理。

完成状态：

- ✅ 新增 `POST /api/metadata/{ext_id}/quarantine`，支持从审核记录隔离整个 work。
- ✅ 隔离原因支持 `bad_source`、`out_of_scope`、`not_literature`、`duplicate_residual`、`needs_rerun`、`user_removed`。
- ✅ 当前 extraction 标记为 `rejected` + `fix_action='quarantined'` + `review_source='human'`，`review_note` 写入隔离原因。
- ✅ 同一 work 的其他 pending 以及 approved-but-unapplied extraction 会被阻断自动回填；已有 `review_note` 不被覆盖。
- ✅ `works.read_status` 更新为 `quarantined`，`work_codes` 写入隔离原因，源文件移动到 `_quarantine/{work_id}/` 并同步 `source_files.source_path`。
- ✅ 默认 metadata 列表、agent queue、批量低风险通过、自动 apply 和默认 Works 列表均排除 quarantined work；审计模式可显式包含。
- ✅ restore 后不自动重开 rejected/quarantined extraction，且会清理隔离相关 code。
- ✅ healthcheck 增加隔离一致性校验，覆盖隔离 code、`source_files.source_path` 是否指向 `_quarantine/{work_id}/`、源文件是否存在。
- ✅ API 测试覆盖隔离、队列排除、apply 跳过、恢复后可见性、approved-unapplied 阻断、review_note 保护和 Works 默认列表排除。

核心原则：

- 隔离不是删除。任何源文件、解析产物、抽取记录和审计信息都不应被物理删除。
- 隔离对象优先是 `work`。第一版按 `work_id` 隔离整篇文献及其源文件；如果后续一个 work 下有多个 source_file 且只想隔离其中一个，再扩展为 source_file 级隔离。
- 隔离后从主工作流退出。被隔离的 work 不应继续出现在默认审核队列、自动回填、分析运行、综述矩阵、引用导出和默认 Works 列表中。
- 恢复必须可行。只要用户恢复 work，就能复用已保留的解析产物和元数据历史，避免重新解析和重复抽取。

建议数据处理：

- 复用现有 `POST /api/works/{work_id}/quarantine`，将 `works.read_status` 更新为 `quarantined`，并写入 `work_codes.code='bad_source'` 或更细分的隔离 code。
- 源 PDF 移动到 `_quarantine/{work_id}/`，`source_files.source_path` 同步更新；不要删除 `source_files` 记录。
- `works/{work_id}/parsed/` 下的 MinerU 产物保留在原位，`literature_parse_runs`、`parse_artifacts`、`metadata_extractions` 保留原记录。
- 当前审核中的 `metadata_extractions` 应同步标记为不可应用：`review_status='rejected'`，`review_source='human'`，`fix_action='quarantined'`，`review_note` 写入隔离原因。
- 如果该 work 还有其他 pending/approved 但未 applied 的 extraction，应一并阻止自动回填；可选择批量写 `fix_action='quarantined'`，但不要覆盖历史 review_note。
- 如已存在 `approved` 且已 applied 的元数据，不自动回滚 `works` 字段；隔离状态本身负责将其排除出主流程。恢复后仍保留这些稳定字段。

建议 UI 行为：

- MetadataReview 详情页增加“隔离此文献”按钮，位置靠近 Reject/Needs Fix，但视觉上明确区分为来源级动作。
- 点击后弹出确认框，必须填写或选择隔离原因，例如：
  - `bad_source`：PDF 内容为空、反爬页、导航页、扫描损坏、解析产物不可用。
  - `out_of_scope`：不属于当前研究主题或综述范围。
  - `not_literature`：不是论文/报告/标准等目标文献。
  - `duplicate_residual`：已由其他 work 覆盖，本条只是重复残留。
  - `needs_rerun`：主题对但上传的文档本身有问题，需替换后重新抽取。
  - `user_removed`：用户明确不想保留。
- 确认后调用 quarantine API，并刷新审核队列；当前记录从 pending 队列移出。
- 在 Works/WorkDetail 中继续支持恢复；恢复后 work 回到 `unread` 或恢复前状态，且可以重新进入元数据审核队列。
- 隔离状态应在 MetadataReview 详情中可见，避免用户对同一 work 继续审核。

后端/API 约束：

- `GET /api/metadata` 默认排除 `works.read_status='quarantined'`；可增加 `include_quarantined=true` 供审计查看。
- `GET /api/metadata/agent/queue` 默认排除 quarantined，避免 agent 对已隔离文献继续重抽。
- `POST /api/metadata/apply-approved` 和批量低风险通过必须跳过 quarantined work。
- `POST /api/works/{work_id}/restore` 恢复后不自动把 rejected/quarantined 的 extraction 改回 pending；需要用户或 agent 明确重新打开审核，避免误恢复坏抽取。
- Healthcheck 增加一致性检查：DB 标记 quarantined 的 work 应有 `_quarantine/{work_id}/` 源文件或明确的无源说明；有 `bad_source` code 的 work 应与 `read_status='quarantined'` 一致。

解析数据处理策略：

- 已解析 `content.md` 和 `content.json` 保留，不移动。原因是解析产物可能体积较大、路径已被 `literature_parse_runs.content_md_path` 引用，移动会带来大量路径更新风险。
- 隔离后默认不再展示 content preview；若在审计模式打开，可继续通过原 `content_md_path` 查看。
- 如果后续需要彻底清理空间，另设“归档解析产物”维护脚本，将 parsed 目录移动到 `_archive/parsed/{work_id}/` 并同步 DB；这不属于审核页第一版动作。

验收标准：

- 审核人员能在 MetadataReview 中一键隔离当前 work，并填写原因。
- 隔离后源 PDF 移入 `_quarantine/{work_id}/`，`works.read_status='quarantined'`，`work_codes` 有隔离原因，当前 extraction 标记为 `rejected` + `fix_action='quarantined'`。
- 隔离后的 work 不再进入默认 metadata 审核队列、agent 修复队列、批量 approve、自动 apply、分析运行和矩阵/引用导出。
- 恢复 work 后，源 PDF 回到 `works/{work_id}/source/`，解析产物和历史审核记录仍可追溯，不需要重新 MinerU 解析。
- 全流程有 API 测试覆盖：隔离、队列排除、apply 跳过、恢复后可见性。

#### P1.0h：文献类型标签重建与确认 ✅ 分类系统 Phase 1-3 已完成

当前 `works.doc_type` 是摄入阶段基于文件名/PDF 元数据关键词的弱规则猜测，不是小模型确认结果，也没有记录来源、置信度或人工审核状态。它已经被 Dashboard、Works 筛选和后续矩阵规划使用，因此在进入 P1.1 分析运行和 P1.2 综述矩阵之前，需要先把 `doc_type` 从"临时筛选字段"升级为可追踪、可审核的核心元数据。


已完成实现（详见 `classification_integration_plan_v1.md`）：

- ✅ 新增 `works` 表扩展字段：`primary_doc_type`、`publication_status`、`ingestion_state`、`priority`、`is_core_literature`、`primary_source_actor_type`、`region`、`canonical_file_format`、`secondary_doc_type`、`contributors`。
- ✅ 新建 `work_classification_tags` 表（1374 条标签），支持多值标签（reading_lane、artifact_focus、risk_domain、method_tags 等）。
- ✅ 新建 `classification_extractions` 表（373 条候选），保存模型分类建议，通过审核后才写入 works 和标签表。
- ✅ `scripts/literature_classification_extract.py` 已完成批量抽取，支持 Ollama 本地模型。
- ✅ `scripts/migrate_add_classification_columns.py` 和 `scripts/migrate_backfill_doc_type.py` 迁移脚本已完成。
- ✅ `api/routes/classification.py` 已实现标签 CRUD、分类抽取审核、批量批准低模糊度候选等 API。
- ✅ `api/classification_vocab.py` 词汇表模块已完成。
- ✅ `ClassificationReview.vue` 页面已实现，支持按状态/模糊度/优先级筛选、候选字段编辑、保存草稿、审核操作、隔离文献、PDF 预览联动、贡献方字段展示。
- ✅ 阶段 0（分类积压清理）已完成：重算 ambiguity_score（226 条更新），批量通过可自动处理的 pending（112 条 approved，tag=`batch-approved-2026-06-13`）。剩余 125 条 pending（106 条缺 primary_doc_type evidence，19 条 quarantined）为边界保留项，不应自动批准。

核心原则：

- `doc_type` 是每篇 work 的主类型，用于筛选、统计、矩阵和引用导出；它不是 P2 中的多主题/collection。
- P2 负责多归属标签，例如 topic、institution、survey_chapter、custom collection；P1.0h 只治理文献“是什么类型”。
- 摄入规则可继续给初值，但必须标记为低可信来源，不能默认为已确认。
- 小模型可基于 `content.md` 重新判断类型，但必须返回 evidence 和 confidence；低置信度或与现有值冲突的记录进入人工审核。
- 人工确认后的 `doc_type` 应优先级最高，后续重抽和外部元数据补全默认不得覆盖。

建议数据处理：

- 新增或迁移字段：
  - `doc_type_source`: `ingest_rule` / `model` / `external` / `human`
  - `doc_type_confidence`: `low` / `medium` / `high`
  - `doc_type_review_status`: `pending` / `confirmed` / `needs_fix`
- 或新增独立审计表 `work_metadata_assertions`，记录字段名、候选值、来源、置信度、证据、审核状态；第一版若想降低复杂度，可先用 `works` 上的三个字段。
- 修改 `scripts/literature_ingest.py`：规则生成的类型写入 `doc_type_source='ingest_rule'`、`doc_type_confidence='low'`、`doc_type_review_status='pending'`。
- 扩展元数据抽取 prompt 或新增专门脚本，只重判 `doc_type`，避免影响现有标题、作者、机构审核流程。
- 生成冲突队列：规则值与模型值不同、模型低置信度、类型为 `benchmark/report/system_card` 等高误判风险项优先人工检查。

建议第一版类型体系需要单独讨论和冻结，候选包括：

- `paper`
- `preprint`
- `technical_report`
- `standard_or_framework`
- `system_card`
- `benchmark`
- `survey`
- `dataset`
- `thesis`
- `book_chapter`
- `other_literature`
- `not_literature`

验收标准：

- 每个 `doc_type` 都能看到来源、置信度和审核状态。
- 当前由摄入规则生成的旧值可批量标记为 `ingest_rule/low/pending`。
- 至少能用模型对一批 work 重新生成 `doc_type` 候选，并保留 evidence。
- Works/MetadataReview 能筛出 `doc_type_review_status='pending'` 或冲突项供人工确认。
- P1.2 综述矩阵默认只使用 `confirmed` 或高置信度类型；低置信度类型在导出中有提示或被排除。

#### P1.1：分析运行

> **设计已细化**：P1.1/P1.2 的实施以 `docs/superpowers/specs/2026-06-12-reading-methodology-analysis-runs-design.md` 为准（三层阅读模板与 AnalysisRun 设计：digest 速览层 / angle 角度层 / synthesis 综合层，模板版本化，executor 无关提交约定）。本节以下内容保留为原始设计依据；冲突处以设计文档为准（差异：第一版不开 `POST /api/works/{id}/analyses`，写入走 CLI 校验）。

交付物：

- 新增 schema migration：`analysis_runs`。
- 约定 `works/{work_id}/analyses/{date}_{angle}.md` 的文件命名和 DB 双写。
- 新增命令行脚本 `scripts/literature_analyze.py`，先支持手动/半自动写入分析结果。
- 新增 `scripts/literature_matrix.py`，按 `angle` 和 work 子集导出 Markdown/CSV 综述矩阵。
- 新增 API：
  - `GET /api/works/{id}/analyses`
  - `POST /api/works/{id}/analyses`
  - `GET /api/matrix`
- 前端 WorkDetail 增加分析列表，新增 Matrix 页面。

验收标准：

- 能为至少 3 篇文献、2 个角度写入分析结果。
- 能导出一个按年份排序的 Markdown 综述矩阵。
- 分析结果同时存在于 SQLite 和 `works/{id}/analyses/`。

建议顺序：P0 后优先做。当前全文已经齐备，这是最能转化为论文/综述价值的一步。

#### P1.2：综述矩阵

> 设计已细化，见 `docs/superpowers/specs/2026-06-12-reading-methodology-analysis-runs-design.md` §9.1（GET /api/matrix）与 §4.2（统一输出信封使矩阵列定义直接来自模板 schema）。

P1.2 使用 P1.1 的分析结果生成矩阵。它不是重新分析文献，而是把已经保存的 AnalysisRun 按文献、年份、机构、主题、角度重新组织成 Markdown/CSV 表格。

第一版矩阵建议至少支持：

- 按年份排序。
- 按 doc_type、language、collection、机构筛选。
- 选择多个 angle 作为列。
- 导出 Markdown 和 CSV。

### P2：Collections/标签/主题体系

目标：把“逻辑归属不靠物理文件夹”的设计真正产品化。

交付物：

- 新增 schema migration：`collections`、`work_collections`。
- 支持 collection 类型：`topic`、`institution`、`year`、`survey_chapter`、`custom`。
- 新增 API：
  - `GET /api/collections`
  - `POST /api/collections`
  - `PUT /api/works/{id}/collections`
- Works 页面支持 collection 筛选。
- WorkDetail 支持 collection 编辑。
- 可选：生成 `views/{collection}.md` 只读视图。

验收标准：

- 一篇 work 可属于多个 topic。
- Works 页面可按 topic/institution/survey chapter 过滤。
- 主题视图不复制 PDF，只引用 work 和路径。

建议顺序：与 P1 可并行，但最好先完成基础 schema migration 模式。

### P3：摄入后解析自动化

目标：让新增 PDF 从 `_inbox` 到 `content.md` 的链路更少手工操作。

交付物：

- 为 `scripts/literature_ingest.py` 增加可选参数，例如 `--parse-pending` 或新增 `scripts/literature_parse_pending.py`。
- 检测 document-parser/MinerU 健康状态。
- 只处理 ledger 中 `pending` 的新增条目。
- 保持保守并发：`max_workers=1`，并明确失败降级策略。
- API 可选新增：
  - `POST /api/ingest/run`
  - `POST /api/parse/pending`
  - `GET /api/parse/status`

验收标准：

- 新 PDF 放入 `_inbox` 后，一条命令可完成摄入并提交解析。
- MinerU 不可用时，不破坏已写入的 pending 状态。
- 解析成功后，DB、ledger、content path 一致。

建议顺序：如果近期会持续新增 PDF，则提前到 P1 之前也可以。

### P4：前端上传与操作闭环

目标：把日常管理从命令行进一步收敛到 SPA。

交付物：

- 新增前端上传页或 Works 页上传入口。
- 后端实现 `POST /api/works`，但内部仍复用摄入逻辑，不绕过 `_inbox`/DB/ledger 约定。
- Duplicates 页面决策直接写回 DB，并可选择导出 JSON 作为备份。
- WorkDetail 增加 `notes/reading.md` 编辑。

验收标准：

- 用户可通过浏览器上传 PDF，并在 Works 中看到 pending work。
- 去重决策刷新页面后仍保留在数据库。
- 阅读笔记保存为文件并能在详情页重新加载。

### P5：外部元数据补全与引用导出

目标：提高文献库的可引用性和综述写作效率。

交付物：

- 在 P1.0 本地模型抽取的基础上，引入 arXiv/CrossRef/PubMed 元数据补全脚本。
- 对 DOI/arXiv/venue/url/abstract 等字段做外部校验和补强。
- 新增 BibTeX/RIS/CSV 导出脚本和 API。
- 前端支持按 metadata_status 过滤并批量标记 `verified`。

验收标准：

- 至少可为 arXiv ID 文献自动补全标题、作者、年份、URL/abstract。
- 可从当前筛选结果导出 BibTeX。
- `metadata_status` 能反映人工确认进度。

## 4. 推荐实施路线

如果没有更强的近期需求，建议顺序如下：

1. P0 状态基线与质量护栏。✅ 已完成
2. P1.0 基于 MinerU `content.md` 的元数据增强。✅ 抽取入库已完成
3. P1.0c MetadataReview 审核界面与人工抽样门禁。✅ 第一版已完成
4. P1.0d 元数据审核优先级与批量通过策略。✅ 风险分级与低风险批量通过第一版已完成
5. P1.0e 审核页联动本地文档预览。✅ 第一版已完成
6. P1.0f 人机共用审核修正闭环。✅ 核心闭环已完成
7. P1.0g 审核页隔离文献/文件闭环。✅ 已完成并审核通过
8. P1.0h 文献类型标签重建与确认。✅ 分类系统 Phase 1-3 已完成
9. P1.1 分析运行。
10. P1.2 综述矩阵。
11. P2 Collections/标签/主题体系。
12. P3 摄入后解析自动化。
13. P4 前端上传与操作闭环。
14. P5 引用导出与外部元数据补全。

如果近期会大量新增 PDF，则把 P3 提前到 P0 之后。

如果近期目标是写综述，则 P1 应保持最高优先级。当前 P1.0 抽取入库、P1.0c/d/e/f/g 审核、修正和隔离闭环已经可用；P1.0h 分类系统 Phase 1-3 已完成，`doc_type` 等核心类型字段已重建为可追踪、可审核的元数据。下一步建议进入 P1.1：让本地模型围绕固定阅读角度产出 AnalysisRun。

## 5. 外部规划文档的保留方式

`D:\02_academic\doctoral\LITERATURE_SYSTEM_PLAN.md` 建议保留，不移动、不覆盖。它仍然有三类价值：

- 解释为什么采用“稳定物理存储 + SQLite + 视图层 + 前端台账”的架构。
- 保留迁移前背景、坏源处理、MinerU 并发经验和约束。
- 为 AnalysisRun、nature-skills 集成、综述矩阵提供设计蓝图。

当前项目内部以后以本文件和 `README.md` 作为实际状态入口；外部规划文档作为上位设计和历史记录引用。
