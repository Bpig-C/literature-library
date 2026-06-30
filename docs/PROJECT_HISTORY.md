# 项目历史记录

> 状态：历史记录
> 更新时间：2026-06-30

本文档用于承接已完成阶段、历史判断和旧路线图记录，避免 `FUTURE_WORK_PLAN.md` 同时承担“未来计划”和“完成流水账”两种职责。

当前事实仍以代码、测试、`scripts/healthcheck_library.py`、`README.md`、`TECHNICAL_OVERVIEW.md` 和最新审核报告为准。本文档仅回答“过去完成了什么、历史证据在哪里”。

## 历史证据位置

- 规格与实施计划：`docs/superpowers/specs/`、`docs/superpowers/plans/`
- 审核与整改记录：`docs/superpowers/reviews/`
- 架构与流程现行入口：`docs/architecture/README.md`、`docs/workflows/README.md`
- 旧脚本归档：`_archive/`、`scripts/_archive/`、`parser/_legacy_service/`

## V1 前主要完成项

### 数据根与物理存储

- 建立 `works/`、`_inbox/`、`_duplicates/`、`_quarantine/`、`_archive/` 等本地文件区。
- 确立 SQLite 作为逻辑事实源，文件系统只保存 PDF 和解析/分析产物。
- 建立“不直接删除源文件，归档或隔离优先”的维护原则。

### 摄入与去重

- `scripts/literature_ingest.py` 完成 `_inbox` dry-run / execute 摄入。
- 摄入链路写入 `works`、`source_files`、`literature_parse_runs`，并处理 sha256 精确重复。
- Duplicates 页面和 API 支持重复组审核、关系决策、same_work 合并、隔离操作。
- 标题相似候选、辅助信号展示、合并主文献选择等去重增强已进入 V1。

### 解析链路

- parser 能力纳入仓库，形成 `parser/` 子项目。
- 解析单核收敛到 `parser/core/mineru/router.py::route_and_parse`。
- 解析状态源统一到 `literature_parse_runs`；`parse_ledger.json` 废弃并归档。
- CLI/API/UI 三条解析入口已具备：`scripts/literature_batch_parse.py`、`POST /api/parse/trigger`、WorkDetail 触发按钮。

### 元数据与分类审核

- 建立 `metadata_extractions`，形成模型抽取、风险分级、人工审核、低风险批量批准、supersede 审计链。
- 建立 `classification_extractions`、`work_classification_tags` 和分类词表同步机制。
- MetadataReview 与 ClassificationReview 已具备队列筛选、编辑、草稿/审核、PDF/证据辅助、隔离入口。
- WorkDetail 集成元数据、分类、标签、源文件状态、PDF 预览和关系信息。

### Collector / Intake / Inbox

- collector 地基完成：topic、candidate store、gate、fetch、ingest bridge。
- IntakeReview 支持采集候选审核、resolve、promote。
- TopicsReview 支持主题成熟度闸门和按主题触发采集。
- InboxReview 支持手动 inbox 摄入 dry-run 和确认执行。
- collector 晋升写入 works 的路径收敛到 `collector.ingest_bridge`。

### V1.1 前端端到端主流程

- V1.1 前端端到端主流程已完成：前端可覆盖“发现/投递 -> 入库 -> 解析 -> 元数据抽取 -> 分类抽取 -> 审核”的主链路。
- 新增元数据抽取与分类抽取 API 薄适配器：`POST /api/metadata/extract`、`POST /api/classification/extract`。
- WorkDetail 增加主流程工作台，能展示源文件、解析、元数据、分类状态，并在解析成功后触发抽取或跳转审核。
- TopicsReview 增加主题创建入口；InboxReview 摄入成功后显示新文献 ID 和后续入口。
- 统一 collect、resolve、promote、ingest、parse、metadata extract、classification extract 的前端结果反馈。
- 第三方复核补齐了抽取触发回归测试和审核页查询参数承接，最终验收为 `pytest tests\ -q` 通过、healthcheck 零问题、`npm.cmd run build` 成功。
- 专门完成报告：`docs/superpowers/reviews/2026-06-30-v1.1-frontend-end-to-end-flow-result.md`；实施方案：`docs/superpowers/plans/2026-06-30-v1.1-frontend-end-to-end-flow.md`。

### 健康检查与发布审核

- 当前健康检查入口为 `scripts/healthcheck_library.py`。
- 健康检查覆盖 orphan files、phantom DB entries、work dirs without DB rows、status inconsistencies、dangling references。
- V1 发布前第三方审核发现并推动修复 SQL 注入、路径安全、quarantine/restore 一致性、fresh schema、parser 测试、真实 DB 假绿、文档/API 漂移等问题。
- P1 发布阻断项已在 `2026-06-29-v1-final-publication-p1-remediation.md` 中清零。

## 历史路线图摘录

以下主题曾经长期停留在 `FUTURE_WORK_PLAN.md` 中，现已按性质归档到本文档：

- Phase 0-4 的本地文献库、去重、元数据、分类和前端迁移记录。
- parser 子项目化、状态源统一、CLI/API/UI 三链路完整性记录。
- collector 地基、采集审核、主题闸门、inbox 摄入记录。
- V1.1 前端端到端主流程、抽取 API、WorkDetail 工作台和前端任务反馈记录。
- 旧的 document-parser / 自部署 MinerU 方案与 `parse_ledger.json` 迁移记录。
- 早期关于 collections、analysis_runs、综述矩阵、引用导出的初始设想。

如需逐步复盘，请优先查看：

- `docs/superpowers/specs/2026-06-28-three-chain-completeness-plan.md`
- `docs/superpowers/specs/2026-06-29-three-chain-runbook.md`
- `docs/superpowers/reviews/2026-06-29-whole-project-third-party-audit-report.md`
- `docs/superpowers/reviews/2026-06-29-whole-project-third-party-audit-remediation-result.md`
- `docs/superpowers/reviews/2026-06-29-v1-final-publication-review.md`
- `docs/superpowers/reviews/2026-06-29-v1-final-publication-p1-remediation.md`
- `docs/superpowers/reviews/2026-06-30-v1.1-frontend-end-to-end-flow-result.md`
