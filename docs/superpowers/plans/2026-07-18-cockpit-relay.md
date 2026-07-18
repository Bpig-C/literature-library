# 阶段二实施方案：驾驶舱与流程接力

> 所属主线：`FUTURE_WORK_PLAN.md`「当前主线」阶段二（#6 + 流程断点引导）。
> 方案位置：按治理存于 `docs/superpowers/plans/2026-07-18-cockpit-relay.md`（执行时创建）。

## 目标与非目标

**目标**
1. Dashboard 升级为"今日待办"驾驶舱：全部流程队列数字一屏可见、每个数字可点击直达对应页面，并区分"流程待办"与"积压补审"。
2. 消灭三个已知流程断点的引导缺失：摄入后无下一步、抽取后无审核引导、分类前置条件（建议先审元数据）不告知。
3. 审核页审核动作后自动跳到下一条待审，减少人工点数。

**非目标（明确排除）**
- 不做自动触发链（摄入后自动解析、审核后自动下一步抽取）——主线边界是"引导"，不是"自动化"；与 UX-001 保留边界（不做无人工闸门的一键全流程）一致。
- 不做 Dashboard 推倒重构；在 Scholar OS 版 Dashboard 上增量增强。
- 不做 #5 parse status 多源语义、#7 审核日志语义统一。
- "清积压"（31 篇补审、12 候选、inbox 1 篇）是用户使用动作，不是本阶段验收条件；本阶段交付的是让积压可见、可点击的面板。

## 代码事实（已核实）

- `/api/pipeline/stats`（`api/routes/ingest.py`）已返回：inbox PDF 数、parse pending/succeeded/failed/running、元数据"待抽取"（已解析无 extraction）与"待审核"（pending extraction）、分类同构两类——**复用并扩展它，不新建端点**。
- 缺口指标：①"待补审" = 已解析成功 且 NOT EXISTS approved 元数据（当前 31 篇），现有 stats 没有；②intake 候选待审数（`/api/intake/stats` 存在，`api/routes/intake.py:85`，可直接用或并入 pipeline/stats）。
- 分类抽取**代码上无硬门禁**：`scripts/literature_classification_extract.py:get_works_to_process` 只要求解析成功+content_md_path；"先审元数据"是 `system-architecture.md` 推荐的治理顺序——所以本阶段做"告知提示"而非阻断。
- Dashboard 现状（Scholar OS 版）：已有 queue-list 5 项（待入库/待解析/元数据审核/分类审核/重复项），数据源为 5 个独立 API 调用；缺 intake、待抽取类、积压补审数字。
- 接力点现状：`InboxReview.vue:150` 摄入完成只有文字提示；`PipelineView` 各阶段执行完成只有 toast；`MetadataReview.vue:781` 审核后 `selected=null` 清空，无自动下一条；ClassificationReview 同构。
- 前端消息体系：`useMessage`（naive-ui），支持 render 函数自定义内容（可放链接按钮）。

## 设计

### 1. 后端：扩展 `/api/pipeline/stats`

在现有返回上追加三个指标（不改既有字段语义）：
- `intake_pending`：intake_candidates 中 `review_status='pending'` 且未 ingested 的数量。
- `backlog_metadata_unapproved`：非隔离 work 中，存在 succeeded parse run 且 NOT EXISTS approved metadata_extractions 的数量。
- `backlog_classification_unapproved`：同上口径对 classification_extractions。
- 在函数 docstring 写明各指标口径；新增 `tests/test_pipeline_stats.py`（sample_db fixture）覆盖：新指标准确、隔离 work 不计入、既有字段不回归。

### 2. Dashboard 待办面板（`web/src/views/Dashboard.vue`）

- 数据源从 5 个独立调用收敛为 `/api/pipeline/stats` 一次调用（保留既有 stats 总览区不动）。
- 「研究处理队列」升级为两组：
  - **流程待办**：待摄入（/ingest）、待解析（/pipeline）、元数据待抽取（/pipeline）、元数据待审（/metadata）、分类待抽取（/pipeline）、分类待审（/classification）、采集候选待审（/intake）、待去重（/duplicates）——每行数字可点击直达。
  - **积压补审**：未批准元数据 N 篇、未批准分类 N 篇（链接到 /works；文案说明"补审后才可用于引用导出/综述矩阵"）。
- 加一行"建议下一步"：取流程待办中第一个非零阶段，显示一句静态建议（纯前端规则，无 LLM）。
- hero 区压缩高度，让待办面板成为首屏主角；保持现有视觉语言。

### 3. 接力引导

新增 composable `web/src/composables/useNextStep.js`：`notifyNext(message, nextStep)`，基于 useMessage render 函数输出"完成信息 + 前往按钮"（router.push 跳转）。
接入点（均为提示级，不改业务逻辑）：
- `InboxReview.vue` / `IngestHub.vue`：摄入完成 → "前往解析（/pipeline）"。
- `PipelineView.vue`：解析完成 → "去元数据抽取"；元数据抽取完成 → "去元数据审核（/metadata）"；分类抽取完成 → "去分类审核（/classification）"。
- `WorkDetail.vue`：手动触发解析/抽取成功后，同规则提示下一步。

### 4. 分类前置条件告知（提示，非阻断）

- `PipelineView.vue` 分类阶段卡片头部：当 backlog_metadata_unapproved > 0 时显示提示条"建议先完成元数据审核（还有 N 篇已解析未批准元数据）"。
- `WorkDetail.vue` 分类抽取按钮 title 追加同义提示。

### 5. 审核页自动下一条

- `MetadataReview.vue` 与 `ClassificationReview.vue`：doReview 成功后，在当前筛选列表中自动选中下一条 `review_status='pending'` 的记录（无则清空）；保持现有刷新逻辑不变。

### 6. 测试

- `tests/test_pipeline_stats.py`：三个新指标准确性 + 隔离排除 + 既有字段不回归。
- 前端：`npm run build` 通过；手动 smoke（Dashboard 数字与 DB 直查一致、接力提示出现、审核自动下一条）。

## 执行顺序与分工

1. 主 agent：stats 扩展 + 测试 → Dashboard 面板 → 接力 composable 与各接入点 → 前置提示 → 审核自动下一条 → 构建。
2. 修复主 agent 自检发现的问题，跑通全部验收命令。
3. **完成后进入两轮模型独立审核（见下节，为硬性验收环节，不可省略）。**
4. 两轮审核的 finding 全部处理完毕后，才允许做"完成后迁移"与收尾提交。

## 两轮模型独立审核（硬性验收）

实现完成后，必须依次进行**两轮互相独立的模型审核**：两轮均由**新起的、不带实现上下文的独立子 agent**执行，只给任务与代码位置，不透露实现思路与预期结论，避免被带偏。

**第一轮 · 代码质量与口径审核**
- 范围：`/api/pipeline/stats` 三个新指标的 SQL 口径（隔离排除、approved 判定、既有字段不回归）、参数化注入面；Dashboard 数字与端点字段的映射正确性；useNextStep 接入点是否都是"提示级"（无业务逻辑改动、无自动触发）；审核页自动下一条的状态一致性（筛选变化、空列表、刷新竞争）。
- 方式：独立子 agent 只读审查全部 diff（`api/routes/ingest.py`、`web/src/views/Dashboard.vue`、`PipelineView.vue`、`MetadataReview.vue`、`ClassificationReview.vue`、`WorkDetail.vue`、`InboxReview.vue`、`IngestHub.vue`、`web/src/composables/useNextStep.js`、`tests/test_pipeline_stats.py`），输出 finding 列表（含严重度与行号证据）。

**第二轮 · 事实与产出核对审核**
- 范围：Dashboard 每个数字与 sqlite 直查独立计算的口径逐项一致；三个断点的引导实跑验证（摄入完成有"前往解析"、抽取完成有"去审核"、分类阶段有前置提示）；确认没有任何"自动化越界"（摄入后不自动触发解析、抽取后不自动跳转审核动作以外的行为）；确认"清积压"未被写成验收条件。
- 方式：另一个独立子 agent（不复用第一轮 agent），只读 + 起服务实跑，输出核对结论与差异清单。

两轮记录均写入 `docs/superpowers/reviews/2026-07-1x-cockpit-review.md`；所有 finding 修复后需重跑验收命令确认。

## 验收命令

```powershell
.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --basetemp .codex_tmp\pytest-phase2
.venv/Scripts/python.exe scripts/healthcheck_library.py --json
.venv/Scripts/python.exe scripts/check_docs.py
cd web; npm.cmd run build
```

手动验收：Dashboard 各数字与 sqlite 直查一致；摄入完成出现"前往解析"；抽取完成出现"去审核"；分类阶段显示前置提示；审核后自动选中下一条。

## 完成后迁移

- `FUTURE_WORK_PLAN.md`：主线阶段二标 ✅、#6 标 ✅。
- `docs/PROJECT_HISTORY.md` 补录；`docs/superpowers/reviews/` 写两轮审核记录；`.workbuddy/memory/` 当日日志。
- 用户随后用面板驱动"清积压"使用动作（31 篇/12 候选/1 篇 inbox）。

## 回滚

增量改动为主（1 个端点扩展 + 前端数处 + 1 个新 composable），revert commit 即可，无数据迁移。
