# 文献库未来工作计划

> 更新日期：2026-06-05  
> 依据：`D:\02_academic\doctoral\LITERATURE_SYSTEM_PLAN.md`、当前仓库代码、`literature.sqlite`、`index.json`、`parse_ledger.json`  
> 定位：本文件是当前项目内的后续执行计划；外部规划文档保留为设计背景和历史路线依据。

## 1. 当前状态核对

### 1.1 总体判断

项目已经从外部规划文档中 2026-06-04 的状态继续向前推进。外部文档仍有参考价值，尤其是系统目标、架构原则、目录约定、去重策略、摄入流水线、AnalysisRun 设计和关键约束；但其中关于 Phase 1、Phase 3、Phase 4 的实施状态已经落后于当前项目。

当前项目已具备：

- 本地稳定存储：`works/`、`_inbox/`、`_duplicates/`、`_quarantine/`、`_archive/` 已存在。
- 主数据库：`literature.sqlite` 当前有 138 个 `works`、151 条 `source_files`、569 条 `parse_artifacts`、140 条 `literature_parse_runs`。
- 解析账本：`parse_ledger.json` 共 140 条，全部 `succeeded`。
- 活跃 PDF：`works/*/source/*.pdf` 共 140 个。
- MinerU 全文：140 条成功解析记录均有 `content_md_path`，实际路径为 `works/{work_id}/parsed/mineru/{source_file_id}/content.md`。
- API 后端：FastAPI 已提供 `/api` 路由组。
- 前端：Vue 3 SPA 已提供 Dashboard、Works、WorkDetail、Duplicates、Relations 五个页面。
- 摄入 MVP：`scripts/literature_ingest.py` 已存在，并有 `tests/test_literature_ingest.py` 覆盖新 PDF 摄入和精确重复归档。
- 去重辅助：`scripts/literature_dedup.py`、`scripts/dedup_apply.py` 和 `views/dedup_dashboard.html` 已存在。

仍未落地或明显不足：

- `analysis_runs`、`collections`、`work_collections` 表尚不存在。
- 尚无分析运行脚本、分析 API、分析页面、综述矩阵导出。
- 尚无前端上传/`POST /api/works`，新增文献仍依赖 `_inbox` + 命令行摄入。
- 摄入脚本只创建 `pending` 解析任务，不自动触发 document-parser/MinerU。
- 元数据扩展字段 `title_zh`、`venue`、`url`、`abstract` 尚未加入。
- 标签/主题/集合仍未进入可用工作流。
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

待扩展：`works` 仍缺 `title_zh`、`venue`、`url`、`abstract`。如需加入，应通过明确的 schema migration 脚本执行，并同步 API/Pydantic/Vue 表单。

### 2.6 去重策略

精确重复和标题候选已进入数据库。当前 `duplicate_groups` 为 13 组，`duplicate_candidates` 为 30 条，`work_relations` 已增加到 4 条。前端 Duplicates 页面和 Relations 页面已经可用。

后续要补齐的是“决策闭环”：

- 前端的重复决策结果需要能可靠写回数据库，而不只停留在 localStorage/导出 JSON。
- `same_work`、`not_duplicate`、`version_of`、`translation_of`、`supersedes`、`part_of` 的语义需要在文档、API、UI 中保持一致。
- 对已 review 的候选组，需要在 Works/WorkDetail 中清晰显示。

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

- P1.0：元数据增强。给每篇文献补齐“身份证”：年份、作者、单位、标题、摘要、DOI/arXiv、venue、URL 等。
- P1.1：分析运行。围绕一个明确角度阅读单篇文献，并把结构化结果保存为 AnalysisRun。
- P1.2：综述矩阵。把多篇文献在同一批角度下的分析结果横向排成表，用于综述写作。

#### P1.0：基于 MinerU content.md 的元数据增强 ✅ 已完成

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

建议抽取字段：

```json
{
  "title": "",
  "title_zh": "",
  "year": null,
  "authors": [
    {
      "name": "",
      "affiliations": [""],
      "email": ""
    }
  ],
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
    "year": "",
    "authors": "",
    "institutions": "",
    "abstract": ""
  },
  "confidence": {
    "title": "high/medium/low",
    "year": "high/medium/low",
    "authors": "high/medium/low",
    "institutions": "high/medium/low",
    "abstract": "high/medium/low"
  },
  "missing": []
}
```

建议数据落点：

- 新增 `metadata_extractions` 表，保存每次模型抽取的原始 JSON、模型名、输入范围、置信度、是否已应用。
- 扩展 `works` 字段：`title_zh`、`venue`、`url`、`abstract`。
- 作者/单位第一版可以继续写入 `works.authors` JSON；更稳的长期结构是新增 `work_authors` 和 `work_institutions`。
- 高置信字段可自动更新 `works`，中低置信字段进入 `needs_review`。

建议命令行工具：

- `scripts/literature_metadata_extract.py`
- 支持 `--limit`、`--work-id`、`--dry-run`、`--apply-high-confidence`、`--output views/metadata_extractions.json`
- 默认只抽取，不覆盖；需要显式参数才应用到 DB。

P1.0 验收标准：

- ✅ 能对至少 10 篇文献生成结构化元数据 JSON。
- ✅ 每条结果包含证据片段和字段级置信度。
- ✅ 高置信的年份、作者、单位能安全写入 DB。
- ✅ 没有找到的信息明确标记为 `missing`，不编造。

**P1.0 交付物**：`scripts/literature_metadata_extract.py`，Schema migration（metadata_extractions 表 + works 扩展字段），healthcheck 覆盖率检查，WorkDetail 新字段展示。使用本地 Ollama qwen3:4b 模型，/no_think 模式，key-author 提取（最多 5 个 + et al.）。

#### P1.1：分析运行

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

1. P0 状态基线与质量护栏。
2. P1.0 基于 MinerU `content.md` 的元数据增强。
3. P1.1 分析运行。
4. P1.2 综述矩阵。
5. P2 Collections/标签/主题体系。
6. P3 摄入后解析自动化。
7. P4 前端上传与操作闭环。
8. P5 引用导出与外部元数据补全。

如果近期会大量新增 PDF，则把 P3 提前到 P0 之后。

如果近期目标是写综述，则 P1 应保持最高优先级，但先做 P1.0。基础元数据干净以后，再用命令行跑通分析和矩阵，最后补前端体验。

## 5. 外部规划文档的保留方式

`D:\02_academic\doctoral\LITERATURE_SYSTEM_PLAN.md` 建议保留，不移动、不覆盖。它仍然有三类价值：

- 解释为什么采用“稳定物理存储 + SQLite + 视图层 + 前端台账”的架构。
- 保留迁移前背景、坏源处理、MinerU 并发经验和约束。
- 为 AnalysisRun、nature-skills 集成、综述矩阵提供设计蓝图。

当前项目内部以后以本文件和 `README.md` 作为实际状态入口；外部规划文档作为上位设计和历史记录引用。
