# 项目历史记录

> 状态：历史记录
> 更新时间：2026-07-03

本文档用于承接已完成阶段、历史判断和旧路线图记录，避免 `FUTURE_WORK_PLAN.md` 同时承担“未来计划”和“完成流水账”两种职责。

当前事实仍以代码、测试、`scripts/healthcheck_library.py`、`README.md`、`TECHNICAL_OVERVIEW.md` 和最新审核报告为准。本文档仅回答“过去完成了什么、历史证据在哪里”。

## 历史证据位置

- 规格与实施计划：`docs/_archive/superpowers/specs/`、`docs/_archive/superpowers/plans/`
- 审核与整改记录：`docs/_archive/superpowers/reviews/`
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
- 专门完成报告：`docs/_archive/superpowers/reviews/2026-06-30-v1.1-frontend-end-to-end-flow-result.md`；实施方案：`docs/_archive/superpowers/plans/2026-06-30-v1.1-frontend-end-to-end-flow.md`。

### V1.1 受约束广泛发现与检索

- V1.1 受约束发现检索已完成：新增 `discovery_runs` / `discovery_hits` 数据层、`collector.discovery` core、`/api/discovery/*` API、`scripts/literature_discovery.py` CLI 和 `/discovery` 前端审核页。
- 支持 `topic` / `name` / `title` / `url` 四类受控入口：topic/name/title 创建 planned run 和 search plan，URL 创建 manual hit。
- agent 执行边界已固化到 `docs/discovery-agent-protocol.md`：本地模型只读取 run plan、执行检索并回填 hits，不 accept、不 promote、不写 `works`、不改 ontology vocab、不下载 PDF。
- 审核链路保持两道门：`discovery_hits` 人工接受后只创建 `intake_candidates(resolution='pending')`，后续仍走 `/intake` 的 resolve/review/promote 和现有去重闸门。
- 治理边界已实现：同一 `run_id + dedup_key` 去重，title-only hit 不能批量接受，DOI/arXiv/GitHub URL discovery mode 明确拒绝或转交旧 collect 路径。
- 实施方案：`docs/_archive/superpowers/plans/2026-06-30-v1.1-constrained-discovery.md`；执行协议：`docs/discovery-agent-protocol.md`。
- 验证记录：实现方报告 `pytest: 455 passed, 7 skipped`、healthcheck 无异常、`npm build` 成功；后续审核修复后针对 discovery/API/CLI/smoke 的回归验证为 `94 passed`，并通过 healthcheck 与前端构建。

### 健康检查与发布审核

- 当前健康检查入口为 `scripts/healthcheck_library.py`。
- 健康检查覆盖 orphan files、phantom DB entries、work dirs without DB rows、status inconsistencies、dangling references。
- V1 发布前第三方审核发现并推动修复 SQL 注入、路径安全、quarantine/restore 一致性、fresh schema、parser 测试、真实 DB 假绿、文档/API 漂移等问题。
- P1 发布阻断项已在 `2026-06-29-v1-final-publication-p1-remediation.md` 中清零。

### 前端全面重构（Phase 0-5，6轮审核全部PASS）

- Phase 0 基础设施：api.js 增强（AbortController/30s超时/ApiError/TimeoutError）+ error-handler.js 三层错误捕获 + router.js 路由命名/meta/404/beforeEach + NotFound.vue + alert() 清零（4页面）
- Phase 1 设计令牌：AppLayout.vue :root 注入完整 CSS 变量体系（圆角6级/阴影4级/间距8级/状态色8种/字体6级/过渡3级），废弃 purple 色系统一 accent 蓝
- Phase 2 组件提取：7 Composable（useQuarantine/useFormatUtils/useDualPanel/usePdfDrawer/useAsyncOperation/usePagination/constants.options）+ 6 UI 组件（StatusBadge/EmptyState/ConfirmDialog/SearchHeader/ReviewBar/DualPanelLayout）
- Phase 3 布局统一：DualPanelLayout.vue 通用双面板组件（含 ResizeHandle 拖拽）
- Phase 4 体验优化：PDF defineAsyncComponent 动态导入 + :focus-visible a11y 基础
- Phase 5 WCAG AA 合规储备 + Bundle 分析
- 组件集成迭代：StatusBadge×30 / EmptyState×14 / ConfirmDialog×10 覆盖全视图
- 审核报告：`docs/_archive/superpowers/reviews/2026-07-01-frontend-refactor-audit-report.md`（CONDITIONAL PASS, 7项技术债后续已清零）
- 设计规范修订：`docs/_archive/superpowers/plans/2026-07-01-frontend-redesign-plan.md` v2.0 全量替换方案

### 流程管理页面创建与增强（Pipeline）

- 新增 PipelineView.vue：4 阶段流水线（收件箱→解析→元数据→分类）
- StageCard.vue（325行）：可折叠阶段卡片组件，插槽系统(filters/stats/default)，展开动画
- SelectableFileList.vue（296行）：通用可选文件列表，Set 跨页选中保持，分页，EmptyState 集成
- 网页上传功能：`POST /ingest/upload` 接口 + NUpload 组件（多选拖拽 PDF → _inbox/ → 自动 execute_plan）
- 数据统计修复：新增 `GET /pipeline/stats` 区分「待抽取」vs「待审核」；新增 pending-metadata/pending-classification 列表接口
- 双模式设计：extract 模式（待抽取文件列表+批量操作）+ review 模式（审核列表纯展示）；selectable/actionDisabled 双开关防逻辑矛盾
- PDF 预览+快速隔离：每行预览按钮 → 右侧 PdfPreviewDrawer 并列显示；隔离弹窗复用 useQuarantine composable
- 布局重构：从底部接续改为左右并列（`.pipeline-layout` flex 双栏）
- 审核报告：`docs/_archive/superpowers/reviews/2026-07-01-pipeline-enhancement-audit.md`（PASS 有条件通过，TD-P1/P2/P3 已修复）
- 实施计划：`docs/_archive/superpowers/plans/2026-07-01-pipeline-enhancement.md`

### 文献入库统一页面（IngestHub）

**背景**：发现检索（DiscoveryReview）和收件箱（InboxReview）是两个并列的入库入口，作为独立页面存在导致用户需要在不同页面间切换。两者本质都是"把文献弄进来"，合并为一个统一入口可降低认知负担。

**改动清单**：

| 文件 | 改动 |
|------|------|
| **新建 `web/src/views/IngestHub.vue`** (55行) | NTabs 薄壳包装：🔍发现检索 / 📥收件箱 两个 Tab，子组件零改动嵌入 |
| **`router.js`** | 新增 `/ingest` → IngestHub 路由（lazy import） |
| **`AppLayout.vue`** | 侧边栏「发现检索」「收件箱」两项替换为「📥 文献入库」一项（自动高亮 /ingest、/discovery、/inbox） |
| **`PipelineView.vue`** | 收件箱 StageCard 移除 NUpload 上传按钮 → 改为跳转链接；清理 ~30 行无用上传代码 |

**验收**：构建通过，无新依赖，零回归。

**日期**：2026-07-01 ~ 2026-07-02

### V1.3 知识闭环（P0-P2 完成，P3 远期保留）

- P0：运行状态机修复 + `/complete` 端点（`4fcfe21`）
- P1：发现检索关联主题 + 主题可选分类标签(含 proposed_new) + query_def 复合字段扩展（`e51f483`, `b30ff7f`, `476d6a2`）
- P2：前端侧边栏布局重排（流程分组/图标/tooltips）（`3962c8d`, `e0c463c`）
- P3（远期）：定时重新执行 + 元数据反哺主题 + 持续迭代闭环 — 尚未实施

### 2026-07-02 前端体验与流程完善（大范围 UI/UX 改进）

> **日期**：2026-07-02（全天）
> **性质**：前端交互优化、Bug 修复、新功能模块
> **编译验证**：`npm run build` 通过，零错误

#### 一、导航栏调整与页面结构优化

**1.1 导航栏顺序调换**
- **文件**：`web/src/components/AppLayout.vue`
- **变更**：
  - 「分类审核」和「元数据审核」位置互换
  - 恢复误删的「发现检索」独立入口
  - 最终顺序：流程管理 → 主题闸门 → 发现检索 → 文献入库 → 采集审核 → 元数据审核 → 分类审核

**1.2 发现检索页面 Tab 切换改造**
- **文件**：`web/src/views/DiscoveryReview.vue`
- **变更**：左侧面板从"表单+运行记录堆叠"改为「新建检索」/「运行记录」两个 Tab 切换
  - 新增 `leftTab` ref 变量、`.left-tab-bar` / `.tab-btn` / `.tab-content` CSS
  - 运行记录面板改为 flex column + overflow hidden，支持独立滚动

**1.3 发现检索运行记录显示主题名称**
- **文件**：`web/src/views/DiscoveryReview.vue`
- **变更**：`runSummary()` 函数增加 `topic_id → topic_name` 解析逻辑，来自主题闸门的检索会显示 `[主题名称]` 前缀

#### 二、采集审核（IntakeReview）深度改造

**2.1 "待审(N)但列表为空"根因修复**
- **文件**：`web/src/views/IntakeReview.vue`
- **根因**：`reload()` 构建参数时 `resolution: resolutionFilter.value || undefined` —— 空值时 JS 的 `undefined` 被 `URLSearchParams` 序列化为字符串 `"undefined"`，后端 SQL 收到 `WHERE resolution='undefined'` 导致返回 0 条结果
- **修复**：条件构建 params 对象，空值不传入该字段

**2.2 页面布局修复**
- **文件**：`web/src/views/IntakeReview.vue`
- **变更**：`.intake-layout` 加固定高度，左右两栏独立滚动

**2.3 来源追溯卡片**
- **文件**：`web/src/views/IntakeReview.vue`
- **新增功能**：详情面板标题下方插入「📎 来源追溯」卡片，自动识别来源渠道并展示关键溯源信息
  - **🔍 发现检索来源**：展示运行名称（可跳转）、创建时间、检索词、关联主题、命中摘要；自动调用 `getDiscoveryRun(runId)` 加载运行详情
  - **📥 直接采集来源**：展示 source_type badge、arXiv ID（链接到 arxiv.org）、GitHub 仓库地址、关联主题
  - **❓ 其他**：显示"来源未知"
  - 从 `raw_meta` JSON 中提取 `discovery_run_id` / `query` / `snippet` 等字段

**2.4 PDF 操作体验优化**
- **文件**：`web/src/views/IntakeReview.vue`
- **下载反馈**：
  - 新增 `pdfDownloading` / `pdfUploading` / `pdfFeedback` 状态变量
  - 按钮文字变为「⏳ 下载中…」/「⏳ 上传中…」，操作期间 disabled
  - 操作栏内新增 `.pdf-inline-feedback` 行内反馈条（ok/warn/err 三色）
- **批准拦截**：
  - 有 PDF → 直接批准
  - 无 PDF → 弹纯提示弹窗引导先下载（无"跳过"按钮）
- **已下载状态**：PDF 已就绪时显示实线绿色边框栏 + 文件路径

#### 三、发现检索→采集审核 PDF 下载全链路修复

| 修复点 | 文件 | 内容 |
|--------|------|------|
| Fix 1 | `collector/discovery.py` | accept_hit_to_intake() 从 URL 提取 arxiv_id + 推断 source_type |
| Fix 2 | `collector/gate.py` | _pdf_url_for() 扩展三步查找策略（arxiv_id → URL反向提取 → None） |
| Fix 3 | `api/routes/intake.py` | 新增 POST `/intake/candidates/{id}/upload-pdf`（手动上传+SHA256查重） |
| Fix 4 | `web/src/views/IntakeReview.vue` | 详情面板 PDF 状态行 + 自动下载按钮 + 上传按钮 |
| 新增 API | `web/src/api.js` | `uploadCandidatePdf(id, file)` 函数 |

#### 四、流程管理增强

- **文件**：`web/src/views/PipelineView.vue`
- **变更**：在收件箱摄入之前新增两个 StageCard：
  - **发现检索审核**：统计数字 + 最近 5 条记录列表 + 跳转链接
  - **采集审核**：统计数字 + 最近 5 条候选列表 + 跳转链接
- 新增 `loadDiscovery()` / `loadIntakeReview()` 函数

#### 五、其他页面改进

**5.1 主题闸门悬浮提示**
- **文件**：`web/src/views/TopicsReview.vue`
- **变更**：状态 badge、操作按钮、详情表格字段全部添加 title 中文悬浮说明

**5.2 promote 晋升状态回填修复**
- **文件**：`collector/ingest_bridge.py`
- **变更**：`promote()` 的 SQL UPDATE 回填 `status='ingested'` 和 `ingested_work_id`；2026-07-03 审查后确认 `review_status` 只表示人工审核结论，不再写入 `ingested`
- **一次性 DB 修复**：IC-1f9eed3c (W-arxiv-2506.19248) 从 pending 回退修正

#### 六、模板管理独立页面（UX-003 升级版）

> **背景**：最初在 MetadataReview 详情页做了字段模板弹窗，用户反馈"每个详情都点开很奇怪，看不到更多意义也没有修改能力"，升级为独立管理空间。

**6.1 后端 API（6 个端点）**
- **新建文件**：`api/routes/templates.py`
- **端点清单**：
  | 方法 | 路径 | 功能 | 状态 |
  |------|------|------|------|
  | GET | `/templates` | 获取所有模板概览 | ✅ 可用 |
  | GET | `/templates/metadata/schema` | 获取元数据字段定义 | ✅ 可用 |
  | POST | `/templates/metadata` | 保存元数据模板编辑 | ✅ 可用 |
  | POST | `/templates/metadata/reset` | 恢复元数据默认值 | ✅ 可用 |
  | POST | `/templates/classification` | 保存分类词汇表 | 🔒 预留 |
  | POST | `/templates/discovery` | 保存 Discovery 协议 | 🔒 预留 |
- **特性**：自动备份机制（最多 5 版本 FIFO）、SHA256 变更检测、恢复默认

**6.2 前端实现**
| 文件 | 说明 |
|------|------|
| **新建 `web/src/api_templates.js`** | API 封装层（7 个函数） |
| **新建 `web/src/views/TemplateManage.vue`** (~560行) | 主页面，Tab 切换三大模板 |
| **修改 `web/src/router.js`** | 新增 /templates 路由 |
| **修改 `web/src/components/AppLayout.vue`** | 导航栏新增「系统」分组 + 📑 模板管理 |
| **修改 `web/src/api.js`** | export request 函数（供 api_templates.js 复用） |
| **修改 `web/src/views/MetadataReview.vue`** | 移除旧弹窗代码（~170 行） |

**6.3 TemplateManage.vue 功能细节**

| Tab | 内容 | 编辑能力 |
|-----|------|---------|
| Tab1 元数据字段 | 10 字段定义表（名称/标签/类型/规则/说明） | ✅ 内联编辑/增删/导出JSON+Prompt |
| Tab2 分类词汇表 | 12 组词汇卡片展示 | 🔒 预留（后端已实现） |
| Tab3 Discovery 协议 | Markdown 渲染协议文档 | 🔒 预留（后端已实现） |

- 保存目标：`templates/templates.json`（不存在则自动创建）
- 备份目录：`templates/backups/`（最多保留 5 版本）

### 2026-07-04 UX-004 字段级重抽前端化

元数据审核从“只能整条记录重抽或命令行重抽”补齐为字段级前端闭环：

- 后端新增 `POST /api/metadata/{ext_id}/rerun-preview`：复用 `scripts/literature_metadata_rerun.py` 的字段级重抽逻辑，调用同一 opencode/llm_judge 链路，返回旧值/新值 diff，不直接写库。
- 后端新增 `POST /api/metadata/{ext_id}/rerun-apply`：确认后写入新的 metadata extraction，并 supersede 原记录；写入前校验 `preview_id`、`old_id`、`work_id` 和重复写入。
- 后端新增 `GET /api/metadata/{ext_id}/rerun-prompt`：生成带 `field_focus_instruction()` 的完整 prompt，作为智能链路不可用时的手动降级方案。
- 前端 `MetadataReview.vue` 在每个可重抽字段旁新增「重抽」和「复制」按钮；`publication_date` 映射到 rerun 字段 `date`，`contributors` 映射到 `institutions`。
- 「重抽」走预览弹窗，用户确认后写库并刷新到新记录；「复制」优先写剪贴板，剪贴板不可用时打开手动复制窗口。
- 测试新增 `tests/test_metadata_rerun_api.py` 覆盖 preview/apply/prompt、非法字段、缺失文件、重复写入、当前审核备注传递和 DB 隔离。
- 验证：`python -m pytest tests/test_metadata_rerun_api.py -q -p no:cacheprovider --basetemp .codex_tmp\pytest-rerun-api-20260704-4` 通过（15 passed）；`web` 构建通过；健康检查通过。

#### 七、已记录 Issue（待后续处理）

| Issue | 标题 | 状态 |
|-------|------|------|
| UX-001 | 缺少批量触发流程的管理页面 | 📋 待处理 |
| UX-002 | PyMuPDF 解析后丢失图片/图表 | 📋 待处理 |
| UX-004 | 字段级重抽前端入口（双模式） | ✅ 已完成 |

## 历史路线图摘录

以下主题曾经长期停留在 `FUTURE_WORK_PLAN.md` 中，现已按性质归档到本文档：

- Phase 0-4 的本地文献库、去重、元数据、分类和前端迁移记录。
- parser 子项目化、状态源统一、CLI/API/UI 三链路完整性记录。
- collector 地基、采集审核、主题闸门、inbox 摄入记录。
- V1.1 前端端到端主流程、抽取 API、WorkDetail 工作台和前端任务反馈记录。
- V1.1 受约束发现检索、discovery run/hit、agent 回填协议和双审核闸门记录。
- Pipeline 流程管理页面（4阶段流水线/批量操作/双模式/PDF预览隔离）记录。
- IngestHub 文献入库统一页面（发现检索+收件箱 Tab 合并/侧边栏整合）记录。
- 2026-07-02 前端体验大范围改进：导航栏调整/发现检索Tab改造/采集审核深度改造(追溯卡片+PDF体验+根因修复)/PDF下载链路修复/流程管理增强/模板管理独立页面。
- 2026-07-04 字段级重抽前端化：MetadataReview 字段行重抽预览写入 + 复制 prompt 降级，后端 rerun preview/apply/prompt 三端点。
- 旧的 document-parser / 自部署 MinerU 方案与 `parse_ledger.json` 迁移记录。
- 早期关于 collections、analysis_runs、综述矩阵、引用导出的初始设想。

如需逐步复盘，请优先查看：

**V1.3 知识闭环**
- `docs/_archive/superpowers/reviews/2026-07-01-v1.3-p0-result.md`（P0 状态机+完成端点）
- `docs/_archive/superpowers/reviews/2026-07-01-v1.3-p1-result.md`（P1 主题关联+标签+query_def）
- `docs/_archive/superpowers/reviews/2026-07-01-v1.3-p2-result.md`（P2 侧边栏重排）

**前端全面重构**
- `docs/_archive/superpowers/plans/2026-07-01-frontend-refactor-handoff.md`（完整实施指令，1184行）
- `docs/_archive/superpowers/reviews/2026-07-01-frontend-refactor-audit-report.md`（审核报告）
- `docs/_archive/superpowers/reviews/2026-07-01-component-integration-audit.md`（组件集成审核）
- `docs/_archive/superpowers/reviews/2026-07-01-phase1-audit.md` ~ `phase5-audit.md`（Phase 1-5 分阶段审核）

**流程管理(Pipeline)**
- `docs/_archive/superpowers/plans/2026-07-01-pipeline-enhancement.md`（实施计划）
- `docs/_archive/superpowers/reviews/2026-07-01-pipeline-enhancement-audit.md`（审核报告）
- `docs/_archive/superpowers/reviews/2026-07-01-pipeline-data-audit.md`（数据一致性审计）

**文献入库(IngestHub)**
- 2026-07-01~02 实施：IngestHub.vue + 路由 + 侧边栏合并 + Pipeline 简化

**更早阶段（V1 / V1.1）**
