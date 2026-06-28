# 文献库未来工作计划

> 更新日期：2026-06-28
> 最近审核：2026-06-27，数据库实测核对：143 works（117 活跃 + 26 隔离）、5 篇 pending-parse（reward hacking / goal misgeneralization 主题新摄入未解析）、156 source_files、145 literature_parse_runs、260 metadata_extractions（applied 119）、373 classification_extractions（approved 119）、1842 classification_tags、21 duplicate_groups / 46 candidates（10 未审）、5 analysis_runs（全 pending）。healthcheck 通过，系统一致。P6 collector 集成：**地基已实施并合并 master**（2026-06-28，9 task subagent-driven TDD，28 测试绿），检索层待实施（见 P6）。发现一个父系统遗留 bug：`/api/metadata?include_quarantined=true` 不返回 quarantined work（见 P1.0g 已知问题，**已于 Phase D-hygiene 修复为测试侧问题**，现 0 failed）。`uv run python -m pytest tests/` 为 **213 passed、6 skipped、0 failed**（hermetic，MinerU_API_KEY unset）；裸 `pytest` 干净收集。**三链路完整性规划 A→B→B'→C→D 已全部交付**（2026-06-29），能力矩阵全 ✅，详见 P6 段与 `docs/superpowers/specs/2026-06-28-three-chain-completeness-plan.md`。
> 依据：`D:\02_academic\doctoral\LITERATURE_SYSTEM_PLAN.md`、当前仓库代码、`literature.sqlite`、`index.json`、`parse_ledger.json`
> 定位：本文件是当前项目内的后续执行计划；外部规划文档保留为设计背景和历史路线依据。

## 1. 当前状态核对

### 1.1 总体判断

项目已具备：

- 本地稳定存储：`works/`、`_inbox/`、`_duplicates/`、`_quarantine/`、`_archive/` 已存在。
- 主数据库：`literature.sqlite` 当前有 138 个 `works`（112 未隔离 + 26 隔离）、151 条 `source_files`（140 active + 11 archived）、569 条 `parse_artifacts`、140 条 `literature_parse_runs`、260 条 `metadata_extractions`、373 条 `classification_extractions`、1842 条 `work_classification_tags`、21 个 `duplicate_groups`、5 条 `analysis_runs`。
- 解析账本：`parse_ledger.json` 共 140 条，全部 `succeeded`。
- 活跃 PDF：`works/*/source/*.pdf` 共 140 个。
- MinerU 全文：140 条成功解析记录均有 `content_md_path`，实际路径为 `works/{work_id}/parsed/mineru/{source_file_id}/content.md`。
- API 后端：FastAPI 已提供 `/api` 路由组，包含 works、metadata、classification、relations、duplicates 等完整 API。
- 前端：Vue 3 SPA 已提供 Dashboard、Works、WorkDetail、Duplicates、Relations、MetadataReview、ClassificationReview 七个页面。
- 摄入 MVP：`scripts/literature_ingest.py` 已存在，并有 `tests/test_literature_ingest.py` 覆盖新 PDF 摄入和精确重复归档。
- 去重闭环：重复候选已审查，same_work/exact_sha256 冗余源文件已归档，关系型重复已写入 `work_relations`。标题候选扫描脚本 `scan_title_duplicates.py` 已就绪，Duplicates 页面支持辅助信号展示和一键合并。
- 元数据增强与审核：`scripts/literature_metadata_extract.py` 已完成基于 MinerU `content.md` 的批量抽取，138 篇文献均已写入 `metadata_extractions`；MetadataReview 已具备风险分级、低风险批量通过、原文/PDF 预览、人机修正闭环和审核页隔离闭环。
- 分类系统：已完成分类本体 v0.2 实施，包括 `works` 表扩展字段（primary_doc_type、publication_status、ingestion_state、priority 等）、`work_classification_tags` 多值标签表、`classification_extractions` 候选表；`scripts/literature_classification_extract.py` 已完成批量抽取；ClassificationReview 页面已实现审核、编辑、保存草稿、隔离等功能。
- 阶段 0（分类积压清理）已完成：每个 work 有 3 个模型候选（mimo2.5pro、mimo-claude、qwen3:4b），批量通过后每个 work 保留 1 个最优 approved extraction（mimo2.5pro > mimo-claude > qwen3:4b），当前状态：approved 119（112 活跃 + 7 隔离）/ pending 0 / rejected 254。
- 词汇表已同步：30 个缺失标签值已补全到 `classification_vocab.py` 和 `labels.js`，前后端完全一致。
- 数据一致性：三个页面（WorkDetail、MetadataReview、ClassificationReview）都以 `works` 表为唯一真相源；审批 apply 采用填空语义，不覆盖人工编辑值；日期展示统一为年月日格式。
- WorkDetail 增强：左右分栏布局、PDF 预览、分类信息内联编辑（含年月日）、贡献方显示（带类型颜色图例）、置信度/证据片段、标签管理合并到分类区。
- 去重系统增强：标题扫描脚本 `scan_title_duplicates.py`、辅助信号展示（arXiv/DOI/文件大小/标签数）、决策直接写回 DB、same_work 二次确认合并（自动评分选优、归档副本、合并标签、隔离副本）。
- 摄入批次标题去重 bug 已修复：`source_by_work` 在批次内更新。
- 数据一致性检查已通过：quarantined works 均有 quarantine code；26 个隔离文献中 24 个有 `_quarantine/{work_id}` 目录（含 active source 文件），2 个为 archived source 状态无 quarantine 目录（W-sha-50c7c11439c3、W-sha-e2a35f439caf）；无重复 approved extraction。

仍未落地或明显不足：

- `collections`、`work_collections` 表尚不存在。
- 尚无综述矩阵导出（`scripts/literature_matrix.py`）、分析 API（`GET /api/works/{id}/analyses`）、分析页面。
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

缺失：`collections`、`work_collections`。

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

- ✅ `analysis_runs` 数据结构和本地分析结果写入规范已建立。
- 下一步：接入具体 reader/writing/citation 工具。

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

> **✅ 已修复（Phase D-hygiene，2026-06-28）**：原"测试假性失败"已落盘修法——给 `test_quarantine_excludes_from_default_list` 的两个 list 请求加 `&search={work_id}` 限定到被隔离的 work，断言变确定且真正测过滤语义（路由本就正确，见 memory `metadata-api-include-quarantined-bug`）。同阶段在 `pyproject.toml` 加 `[tool.pytest.ini_options] testpaths=["tests"]`，裸 `pytest` 不再收集 `parser/tests` 的 fitz 报错。`uv run python -m pytest tests/` 现 192 passed / 6 skipped / 0 failed；裸 pytest 干净收集 198 tests。

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


已完成实现（详见 `docs/plans/classification-integration-v1.md`）：

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

#### P1.0i：分类结果筛选增强 ✅ 已完成

在分类审核完成后，Works 页面需要支持按分类结果（标签）筛选文献，让用户能够快速定位特定类型的文献。

**实施方案**：

| 变更 | 文件 | 内容 |
|------|------|------|
| 1 | `api/routes/works.py` | tag 过滤器改为 `list[str]` 多值，SQL 用 `IN` 匹配 |
| 2 | `api/routes/works.py` | 新增 `classified_only: bool` 参数 |
| 3 | `web/src/views/Works.vue` | 新增 `risk_domain`、`artifact_focus` 多选过滤器 |
| 4 | `web/src/views/Works.vue` | `reading_lane` 改为多选 |
| 5 | `web/src/views/Works.vue` | "已分类"快捷 toggle 按钮 |

**验收标准**：
- ✅ Works 页面可按 `risk_domain`、`reading_lane`、`artifact_focus` 多选筛选
- ✅ 点击"已分类"按钮可快速筛选已分类的文献（primary_doc_type 非空）
- ✅ 多选筛选逻辑为 OR（选多个值 = 匹配任意一个）

#### P1.1：分析运行 ✅ 基础设施已完成

> **设计已细化**：P1.1/P1.2 的实施以 `docs/superpowers/specs/2026-06-12-reading-methodology-analysis-runs-design.md` 为准（三层阅读模板与 AnalysisRun 设计：digest 速览层 / angle 角度层 / synthesis 综合层，模板版本化，executor 无关提交约定）。

已完成交付物：

- ✅ `scripts/migrate_add_analysis_runs.py`：幂等迁移，创建 `analysis_runs` 表 + 3 索引（work_id、angle+template_version、review_status）。
- ✅ `templates/angles/digest@v1.md`：digest 速览层模板，6 字段（one_sentence_positioning、tldr、literature_role、core_artifacts、relevance_to_autonomy_safety、suggested_reading_priority），executor 无关，中文输出。
- ✅ `scripts/literature_analyze.py`：CLI 支持 `plan` / `submit` / `status` / `review` 四子命令。submit 支持 `--strict` 模式（evidence quote 子串校验）和 `--force`（supersede 旧 run）。submit 双写 DB + Markdown 到 `works/{work_id}/analyses/`。
- ✅ `tests/test_analysis_runs.py`：16 个测试，覆盖迁移幂等、plan 排除 quarantined、submit 写 DB/写 MD、缺 evidence 拒绝、重复提交拒绝、review 状态流转、status 统计。测试使用临时 DB + 临时 LIBRARY_ROOT，不污染真实数据。
- ✅ `scripts/literature_healthcheck.py`：扩展 6 项 analysis_runs 检查（orphan work_id、md_path 存在性、唯一未 superseded run、review_status 合法性、extracted_json 合法性、quarantined work 无 pending run）。
- ✅ 5 篇 digest 试跑通过，evidence quote 全部经真实性验证。

当前状态：

- `analysis_runs` 表：5 条记录（全部 pending，0 superseded）。
- 覆盖率：4.5%（5/112 active works）。
- 测试：97 passed, 6 skipped。
- healthcheck：healthy=true, total_issues=0。

全库 digest 批量生成策略（待执行）：

- 每批 10-20 篇，使用 `submit --strict`。
- 任何 submit 出现 `quote_warnings` 的条目不得视为 A 级。
- 分批执行，不一次性跑完 107 篇。

未完成（属于后续阶段）：

- `scripts/literature_matrix.py` 综述矩阵导出。
- `GET /api/works/{id}/analyses` 分析 API。
- 前端 WorkDetail 分析列表、Matrix 页面。
- L2 角度模板（`risk-definition@v1`、`eval-method@v1` 等）。
- L3 综合层（`synthesis-{angle}@v1`）。

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

### P3.5：文档解析子项目化（document-parser 纳入仓库 + 官网精准解析 API）

> 优先级：**在 P6 collector 之前**。collector 一旦铺量采集，解析链路必须先稳定可靠，否则会堆积 pending。
> 状态：**已完成（2026-06-28）**。设计见 `docs/superpowers/specs/2026-06-27-parser-subproject-design.md`，执行审计见 `docs/superpowers/reviews/2026-06-27-parser-subproject-audit.md`。
> **Phase B 追加（2026-06-28，merge `d42455a`）**：parser 子项目此前仅 CLI 可用，现已补齐 API+UI 两链——`POST /api/parse/trigger` + `GET /api/parse/status`（薄适配器，键控 `literature_parse_runs`）+ WorkDetail 触发按钮。D13 路由提升为单核 `parser/core/mineru/router.py`（CLI/API/UI 三收敛）。真实 cloud vlm smoke 跑通（W-arxiv-2506.19248 → 112KB content.md）。见总规划 `docs/superpowers/specs/2026-06-28-three-chain-completeness-plan.md` 矩阵 parser-E/F（CLI/API/UI 全 ✅）。
> **遗留 → Phase D ✅ 已解决（2026-06-28，分支 `fix/phaseD-status-unify`，待合并）**：原"CLI 读 `parse_ledger.json` 而 API/UI 读 `literature_parse_runs` 的状态源不一致"已统一——新 CLI 改 DB-only（删 ledger 读写、新增 `get_pending_db`/`run_pending`、复用 `sync_work_parse_status`），ingest 删 `update_ledger` 停止双写，healthcheck/dashboard 脱离 ledger，旧自部署 CLI 归档，`parse_ledger.json` 移至 `_archive/`。`literature_parse_runs` 成为唯一状态源。
> **Phase B' 追加（2026-06-29，分支 `fix/phaseBp-inbox-ingest`）**：inbox 手动摄入动线补齐 API+UI 两链——`GET /api/ingest/plan`（dry-run 预览，不写盘）+ `POST /api/ingest/execute`（薄适配器零业务逻辑，全委托 `scripts.literature_ingest` 的 `build_ingest_plan`/`execute_plan`，§2 单核）+ `web/src/views/InboxReview.vue`（仿 IntakeReview 双栏：待摄入列表 + 详情 + 确认摄入）。ingest 直写 works + 建 parse_runs pending（与 Phase B 解析链前后衔接）。4 个 ingest API 测试绿（`tests/test_ingest_api.py`，temp library_root + patch LIBRARY_ROOT，不触网络/真 inbox）。见总规划矩阵 ingest-G（CLI/API/UI 全 ✅）。

**现状**：文档解析依赖仓库外的 `D:\06_tools\document-parser` 项目（本地封装模块 + 远程自部署 MinerU，端口 18200/18201）。这造成两个问题：解析能力不在版本控制内、依赖自部署 MinerU 的运维成本。

**目标**：

1. 把 `document-parser` **复制一份拉到本仓库作为子项目**（与 collector 同样的子项目形态，如 `parser/` 或 `document_parser/`），让解析能力进入版本控制、与文献库同仓库演进。
2. 远程解析从**自部署 MinerU** 改为 **MinerU 官网精准解析 API**。
   - 官网 API 文档：https://mineru.net/apiManage/docs
   - 需接入官网 API 的鉴权（API token）、任务提交/轮询/下载流程、配额与限流处理。
3. 保留本地封装层对文献库的契约不变：仍输出 `content.md` + `content.json` 到 `works/{work_id}/parsed/mineru/{source_file_id}/`，路径写入 `literature_parse_runs.content_md_path`，不破坏现有元数据/分类/分析链路。

**交付物（待细化）**：

- 子项目目录结构、与现有 `scripts/literature_batch_parse.py` 的衔接方式。
- 官网 API 适配层（替换原 MINERU_SERVER_URL 自部署调用）。
- 配置：API token、并发限制、失败降级（官网 API 不可用时回退策略）。
- 迁移验证：用现有 5 篇 pending（reward hacking / goal misgeneralization）+ 抽样已解析文献做一致性比对。

**验收标准（待细化）**：

- 解析能力在本仓库内，不再依赖 `D:\06_tools\document-parser`。
- 新 PDF 走官网精准解析 API 成功产出 content.md，路径契约与现有一致。
- 配额/限流/失败有明确处理，不污染 pending 状态。

**待决问题**：官网 API 的计费/配额是否足以支撑批量回填；自部署 MinerU 是否完全停用还是保留作降级。

### P4：前端上传与操作闭环

目标：把日常管理从命令行进一步收敛到 SPA。

交付物：

- 新增前端上传页或 Works 页上传入口。
- 后端实现 `POST /api/works`，但内部仍复用摄入逻辑，不绕过 `_inbox`/DB/ledger 约定。
- ~~Duplicates 页面决策直接写回 DB，并可选择导出 JSON 作为备份。~~ ✅ 已完成
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

### P6：开源文献收集（collector）集成

> 设计已细化，见 `docs/superpowers/specs/2026-06-27-collector-integration-design.md`（集成地基）与 `docs/superpowers/specs/2026-06-27-collector-retrieval-design.md`（检索层）。

**实施状态（2026-06-28）**：
- ✅ **地基已完成并合并 master**（merge `70f6c82`）。计划：`docs/superpowers/plans/2026-06-28-collector-foundation.md`（9 task TDD）。落地：`collector/` 包（normalize / candidate_store 候选层去重 / gate 轻+重闸门四态 / adapters/arxiv + fetch / ingest_bridge 复用 ingest 全链路 / replace_source needs_better_copy）、`scripts/migrate_add_intake_candidates.py`、`scripts/literature_intake.py`（A2 list/promote）、边界测试（collector 不直接写 works）。28 测试绿。
- ⏳→✅ **检索层已通过三链路 Phase A/C 交付**。原 7-task 检索层计划的实质能力（`collection_topics` 表 + 成熟度 seedling/proposed/mapped、(a) 显式 ID + (c) 引用图 1 跳发现、GitHub 论文 PDF、collect/resolve 拆步 CLI）均已在 Phase A（审核闭环）+ Phase C（topics 闸门 + collect 进 UI）落地：检索层 discovery 走 `collector.candidate_store.insert_candidate`（边界守卫测试锁定）、collect 编排经 §2 单核 `collector.collect.collect_once`、topic/collect/resolve 均含 CLI 子命令（`scripts/literature_intake.py`）。CLI/API/UI 三链齐（见总规划 §3 矩阵 collector-A/B/C/D 全 ✅）。
- ✅ **三链路完整性 Phase A（collector 审核闭环 API + UI）已完成**（2026-06-28，分支 `feat/phaseA-intake-review`）。计划：`docs/superpowers/plans/2026-06-28-phaseA-intake-review.md`（8 实施 task + 部署前置，subagent-driven TDD）。落地：`collection_topics` 迁移到 live DB；core 抽 `candidate_store.set_review_status` / `gate.resolve_pending` 为 nucleus（CLI 改调，单一真相源）；`api/routes/intake.py`（GET /candidates·/stats·/topics、POST /resolve·/promote·/topics、PATCH /candidates/{id}/review，全委托 core）挂进 `api/main.py`；`web/src/views/IntakeReview.vue` + 侧边栏「采集审核」入口。18 个 intake API 测试绿（`tests/test_intake_api.py`），全 `tests/` 套件 173 passed / 9 skipped / 1 failed（该 failed 是既有 `test_api.py::TestMetadataQuarantine` 分页脆弱，与本 phase 无关）。只新增，既有 6 路由 + 7 页面语义不动。**Phase B/C/D 待续**（见总体规划 §4）。
- ✅ **三链路完整性 Phase C（collector 主题闸门 + collect 进 UI）已完成**（2026-06-29，分支 `fix/phaseC-collector-ui`）。计划：`docs/superpowers/plans/2026-06-29-phaseC-collector-ui.md`（4 task TDD）。落地：**(1) §2 单核**——把锁在 CLI 的 collect 编排（按 topic query_def 分发到 collect_explicit/collect_from_seeds/collect_repo_paper + light_gate 写 resolution）提取为 `collector/collect.py::collect_once`，CLI `scripts/literature_intake.collect` 改薄包装（零逻辑复制，清理死 import）；**(2) API**——新增 `POST /api/intake/collect`（薄适配器，全委托 collect_once），`topics.list_topics` 改 additive `SELECT *`（补 description/axis_hint/proposed_note/mapped_tags，既有 key 不破）；**(3) UI**——新增 `web/src/views/TopicsReview.vue`（侧边栏「🗂️ 主题闸门」→ `/topics`）：左栏主题列表（map_status 三色 badge）+ 右栏详情 + 成熟度闸门按钮（seedling→proposed prompt 填 4 判据 proposed_note；proposed→mapped prompt 填 mapped_tags）+ 按主题发起采集按钮 + 触发 resolve 按钮；`api.js` 加 transitionTopic/collectIntake。测试：`tests/test_collect_once.py`（4 测试桩网络入口）+ `tests/test_intake_api.py` +3 collect 端点 + `tests/test_collection_topics.py` +1 list_topics additive。`test_collector_boundary` 3/3 守卫通过（collector 仍经 ingest_bridge 写 works）。`vite build` 无错。collector-A/B/C 三链路现全 ✅（见总规划 §3 矩阵）。（注：实施期 worktree 报的 `test_batch_parse_cli` 2 失败是 phaseD-status-unify 的测试纪律遗留——token 闸门依赖真实 .env，已于 hotfix `4d2a38a` fixture hermetic 设 dummy key 修复。）
- ✅ **三链路完整性 Phase B'（inbox 手动摄入 API+UI）已完成**（2026-06-29，分支 `fix/phaseBp-inbox-ingest`，merge `bd02763`）。`GET /api/ingest/plan`(dry-run) + `POST /api/ingest/execute`（薄适配器零业务逻辑，全委托 `scripts.literature_ingest` nucleus，§2 单核）+ `web/src/views/InboxReview.vue`（侧边栏「📂 收件箱摄入」→ `/inbox`）。ingest 直写 works（无候选闸门，源可信）+ 建 parse_runs pending（Phase B 解析接力）。4 个 ingest API 测试绿（`tests/test_ingest_api.py`，temp library_root + patch LIBRARY_ROOT）。
- ✅ **三链路完整性 Phase D（hygiene + 状态源统一 + acceptance）全部完成**（2026-06-28/29）：
  - **D-hygiene**（merge `49579d6`）：P1.0g 测试侧修复 + `pyproject.toml testpaths=["tests"]` 隔离 parser/tests。红基线解除。
  - **D 状态源统一**（merge `0a9d508`）：废弃 `parse_ledger.json`，`literature_parse_runs` 成唯一权威；新 CLI 改 DB-only 复用 `sync_work_parse_status`；ingest 停双写；healthcheck/dashboard 脱离 ledger；旧自部署 CLI 归档。
  - **D-acceptance**（commit `c93a8e5`）：真实三链 smoke 跑通——采集路径 collect→resolve→promote→parse(arxiv 1706.03762→vlm cloud, 43.5KB md)；inbox 旁路 plan→execute→parse(arxiv 1810.04805→pymupdf 本地, 66.8KB md)；UI(playwright) 渲染 /inbox·/topics·/intake 零错误。两种解析后端均验证。
- 🎉 **三链路完整性规划全部交付完成（A→B→B'→C→D）**。能力矩阵所有行 CLI/API/UI 全 ✅；`uv run python -m pytest tests/` **213 passed / 6 skipped / 0 failed**（hermetic，MinerU_API_KEY unset）；§2 双单核全程 PRESERVED（`route_and_parse` 唯一 parser/core/mineru/router.py、`collect_once` 唯一 collector/collect.py）；状态源统一。总规划 + §6 DoD 见 `docs/superpowers/specs/2026-06-28-three-chain-completeness-plan.md`。**审核+测试操作手册**：`docs/superpowers/specs/2026-06-29-three-chain-runbook.md`。

**地基遗留 follow-up（非阻塞，跟踪用）**：
- `ingest_bridge.promote` 的 `library_root` 契约隐式依赖 `api.db.LIBRARY_ROOT`（生产 OK，但应加断言/docstring 明确）。
- `gate._title_match` 是 works 全表扫描（无索引）；works 规模增大后需加 normalized-title 列/哈希。
- `llm_judge.run_executor`（写文件执行器模式）仅留接口，下游抽取/分类任务启动时补实现。
- collector 尚无 healthcheck（候选与 work 一致性、孤立 PDF、重复晋升防护）。
- CLI `promote`（review 状态）与 `ingest_bridge.promote`（真正晋升）命名易混，检索层扩展时考虑改名/加 docstring。

目标：把"开源文献/项目收集"作为本仓库的子模块接入，补上目前缺失的**入库前去重**能力，让"是否新文献"的判别前移到入库前。

核心设计（已讨论确认）：

- **collector 作为子模块**（同仓库、同机、共享 `literature.sqlite`），只采集 + 投递候选，**不直接写 `works`**。
- 新增 `intake_candidates` 表作为候选队列（队列在库，单一真相源）。
- **两段式预去重闸门**：轻量闸门（采集时用 arXiv/DOI/标题元数据查 works，决定是否下载）+ 重量闸门（下载后 SHA256 查 source_files，复用现有 exact_sha256 逻辑）。
- **四态判别**：exact_hit / title_candidate（复用 duplicate_groups）/ needs_better_copy（命中隔离 work，激活"坏副本≠坏文献"再获取）/ sha256_duplicate。
- 第一版：**A2 人工批量晋升**（验证后再开 A1 自动化）、来源只做 **arXiv + GitHub**。

与现有路线的衔接：

- 吸收并扩展 P3：候选晋升后复用 parse pending 链路，建议与 P3 同步推进。
- 复用 P4 上传 API 基础（第二版 intake API）。
- 与 P5 协同：arXiv 适配器采集的元数据天然补全 arXiv/CrossRef 增强。

检索实施层的三个待决问题（**2026-06-27 已全部闭合**，见 `docs/superpowers/specs/2026-06-27-collector-retrieval-design.md`）：检索驱动方式（两层主题+成熟度+(a)(c) 发现）、GitHub 资产边界（v1 只收论文 PDF）、采集与闸门执行节奏（手动 CLI、collect/resolve 拆步）。

**实施参考**：采集/抓取环节可参考 **`web-access` 技能包**（搜索、网页抓取、登录后操作、动态渲染页面等流程），其中应有不少可直接复用的采集与浏览器自动化流程。

## 4. 推荐实施路线

如果没有更强的近期需求，建议顺序如下：

1. P0 状态基线与质量护栏。✅ 已完成
2. P1.0 基于 MinerU `content.md` 的元数据增强。✅ 抽取入库已完成
3. P1.0c MetadataReview 审核界面与人工抽样门禁。✅ 第一版已完成
4. P1.0d 元数据审核优先级与批量通过策略。✅ 风险分级与低风险批量通过第一版已完成
5. P1.0e 审核页联动本地文档预览。✅ 第一版已完成
6. P1.0f 人机共用审核修正闭环。✅ 核心闭环已完成
7. P1.0g 审核页隔离文献/文件闭环。✅ 已完成并审核通过
8. P1.0h 文献类型标签重建与确认。✅ 分类系统 Phase 1-3 已完成，阶段 0 已完成
9. P1.0i 分类结果筛选增强。✅ 已完成
10. 去重系统增强。✅ 已完成（标题扫描、辅助信号、一键合并）
11. P1.1 分析运行。
12. P1.2 综述矩阵。
13. P2 Collections/标签/主题体系。
14. P3 摄入后解析自动化。
15. **P3.5 文档解析子项目化（document-parser 入仓库 + 官网精准解析 API）。← 优先级在 collector 之前。✅ 已完成**
16. P4 前端上传与操作闭环。（部分完成：Duplicates 决策写回 DB ✅）
17. P5 引用导出与外部元数据补全。
18. P6 开源文献收集（collector）集成。（**地基 + 检索层 + 三链路 CLI/API/UI 全部完成并合并 master**；collector A/B/C/D 全 ✅。剩余：live DB 建主题数据、collector healthcheck follow-up）

如果近期会大量新增 PDF，则把 P3 提前到 P0 之后。

如果近期目标是写综述，则 P1 应保持最高优先级。当前 P1.0 抽取入库、P1.0c/d/e/f/g 审核、修正和隔离闭环已经可用；P1.0h 分类系统 Phase 1-3 已完成，`doc_type` 等核心类型字段已重建为可追踪、可审核的元数据。下一步建议进入 P1.1：让本地模型围绕固定阅读角度产出 AnalysisRun。

## 5. 外部规划文档的保留方式

`D:\02_academic\doctoral\LITERATURE_SYSTEM_PLAN.md` 建议保留，不移动、不覆盖。它仍然有三类价值：

- 解释为什么采用“稳定物理存储 + SQLite + 视图层 + 前端台账”的架构。
- 保留迁移前背景、坏源处理、MinerU 并发经验和约束。
- 为 AnalysisRun、nature-skills 集成、综述矩阵提供设计蓝图。

当前项目内部以后以本文件和 `README.md` 作为实际状态入口；外部规划文档作为上位设计和历史记录引用。
