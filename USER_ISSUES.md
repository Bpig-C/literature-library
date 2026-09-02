# 用户问题记录

> **用途**：记录日常使用中发现的不合理之处、体验问题、功能缺陷。
>
> **使用方式**：发现问题时直接在下方添加，定期整理后转移到 `FUTURE_WORK_PLAN.md` 作为开发规划。
>
> **更新时间**：2026-07-17

---

## 问题格式

```markdown
### UX-XXX: 简短标题
- **发现日期**：YYYY-MM-DD
- **页面/模块**：哪个页面或功能
- **问题描述**：具体是什么问题
- **期望行为**：应该是什么样的
- **优先级**：🔴 高 / 🟡 中 / 🟢 低
- **状态**：📋 待处理 / 🔧 已规划 / ✅ 已解决
```

---

## 待处理问题

### UX-005: 元数据模板新增字段缺少基础类型、说明入口和规则辅助生成
- **发现日期**：2026-07-05
- **页面/模块**：模板管理 `/templates` → 元数据字段 → 添加字段
- **问题描述**：
  - 当前添加自定义字段弹窗只能填写“字段名 key / 中文标签 / 类型”。
  - 类型只支持现有抽取模板内部类型：`text`、`textarea`、`list`、`date-object`、`author-list`、`contributor-list`，缺少更基础的 `bool`、`enum`、`number`、`url` 等类型。
  - “说明”目前只能添加后再回到表格行里点开编辑，不在新增字段弹窗中，容易漏填。
  - “验证规则”当前只展示，不能由用户或 agent 直接补充。
  - 对“开源状态”这类字段，人类用户未必能一次写出完整规则；更适合由本地 agent 基于字段名、中文标签、类型和现有模板风格生成候选说明/规则，再由人类确认。
- **期望行为**：
  1. 扩展元数据字段类型体系，至少评估是否加入 `bool`、`enum`、`number`、`url` 等基础类型，并明确与现有 `text/list/textarea` 的关系。
  2. 添加字段弹窗应支持填写“说明 description”，不需要添加后再二次点击编辑。
  3. 验证规则 `rules` 应进入可编辑/可生成流程；用户可手填，也可让本地 agent 生成候选规则。
  4. 本地 agent 生成规则时复用现有 opencode / LLM 调用链或后端 API，输入字段 key、中文标签、类型、已有模板字段和用户意图，输出 description、rules、建议类型和必要的枚举值/取值约束。
  5. agent 生成的规则必须先预览，由用户确认后才写入 `templates/templates.json`。
- **优先级**：🟡 中
- **状态**：📋 待处理
- **验收口径**：
  - 添加 `open_source_status` 这类字段时，用户可在新增弹窗内一次性完成 key、中文标签、类型、说明和规则候选确认。
  - 生成的规则会进入真实元数据抽取 prompt、字段级重抽 prompt 和 `/metadata` 审核表，不只停留在前端展示。
  - 新增字段仍遵守人工审核门禁，不直接污染 `works` 稳定层。

### UX-006: 分类词汇只读页缺少中英对照展示
- **发现日期**：2026-07-05
- **页面/模块**：模板管理 `/templates` → 分类词汇 Tab；分类审核 `/classification`
- **问题描述**：
  - 分类词汇当前仍是只读/预留状态，这个边界是合理的。
  - 但只读页主要展示原始英文标识符，例如 `artifact_focus`、`risk_domain`、`method_tags` 及其 tag key，对人类用户不够友好。
  - 当前分类方法规范已经有中文语义，前端 `labels.js` 也有中文标签；只读资产页没有充分把“英文 key + 中文翻译/解释”组合展示出来。
  - 用户在审核分类时，需要同时知道英文标识符（便于 agent/CLI/代码协作）和中文含义（便于人工判断），两者缺一都会增加理解成本。
- **期望行为**：
  1. 分类词汇只读页按字段组展示中英对照：英文 key、中文标签、简短说明/定义。
  2. 保留英文标识符作为主键，不隐藏；中文翻译作为辅助阅读。
  3. 字段组也应中英对照，例如 `risk_domain / 风险领域`、`method_tags / 方法标签`。
  4. 可从 `web/src/labels.js`、`api/classification_vocab.py` 和 `docs/methodology/classification-methodology.md` 组合生成只读展示数据。
  5. 该项不等同于 QA-004，不开放分类词汇编辑或发布流程。
- **优先级**：🟢 低
- **状态**：📋 待处理
- **验收口径**：
  - `/templates` 分类词汇 Tab 中，用户能同时看到英文标识符和中文翻译。
  - `/classification` 审核页中，关键字段和选项不只显示 raw key；需要 raw key 时也能保留查看。
  - 不修改 `classification_vocab.py` 的词汇发布机制，不开放分类词汇保存。

### REV-001: classification_extractions 缺 superseded_by 列（schema 不对称）
- **发现日期**：2026-07-18（全范围审查 Agent B）
- **页面/模块**：数据层
- **问题描述**：metadata_extractions 与 analysis_runs 都有 superseded_by 审计链，classification_extractions 没有，分类重跑/替代无链可追。
- **期望行为**：评估是否补列对齐（schema 变更，需用户确认并补迁移/回滚/fixture 测试）。
- **优先级**：🟡 中
- **状态**：📋 待处理（待用户决策）

### REV-002: 两条隔离路径对 pending extractions 的语义分叉
- **发现日期**：2026-07-18（全范围审查 Agent B）
- **页面/模块**：works 页隔离 vs 元数据审核页隔离
- **问题描述**：works 页隔离只移源文件+改状态，pending extractions 原样保留（现存 10 条，可经"显示已隔离"找回，解除隔离后回到待审）；审核页隔离则把 pending 打 rejected。两条路径语义不一致。
- **期望行为**：用户选定一种为预期行为并写入文档；若保留"可找回"语义，建议在隔离操作时提示 pending 记录去向。
- **优先级**：🟡 中
- **状态**：📋 待处理（待用户决策）

### REV-003: intake promote 后 review_status 未同步 ingested
- **发现日期**：2026-07-18（全范围审查 Agent B）
- **页面/模块**：collector/ingest_bridge promote
- **问题描述**：现存 1 行 status=ingested 但 review_status=approved 的交叉行，导致 /api/intake/stats 的 approved 桶虚高。
- **期望行为**：promote 成功后同步 review_status='ingested'；订正历史交叉行。
- **优先级**：🟢 低
- **状态**：📋 待处理（待用户确认数据订正）

### REV-004: works.parse_status 派生字段漂移 29 行
- **发现日期**：2026-07-18（全范围审查 Agent C）
- **页面/模块**：api/quarantine.py + 真实库
- **问题描述**：28 篇隔离 work 的 parse_status 停留 succeeded（隔离/恢复均不重算派生值，目前靠"两边都不改"巧合正确）；另有 1 篇活跃 work（W-sha-a8a170a6a268）active 源无 parse run 但状态 succeeded——需用户判断是换副本预期态还是漏解析。
- **期望行为**：quarantine/restore 调用 sync_work_parse_status；对历史漂移跑一次同步；确认该活跃 work 的处理方式。
- **优先级**：🟡 中
- **状态**：📋 待处理（待用户决策）

### REV-005: conftest 与真实 schema 漂移掩盖真实约束
- **发现日期**：2026-07-18（全范围审查 Agent C）
- **页面/模块**：tests/conftest.py
- **问题描述**：缺 intake_candidates UNIQUE(source_type,url_canonical) 与 NOT NULL、缺 discovery_runs/discovery_hits/inventory_meta 等表、works.parse_status fixture 词表与真实词表不符；新测试在宽松 schema 下能通过但真实库会违约。
- **期望行为**：conftest 对齐真实 schema（至少补 UNIQUE/NOT NULL 与 discovery 两表）。
- **优先级**：🟡 中
- **状态**：📋 待处理

### REV-006: parse_runs/metadata_extractions 的 work_id 无索引
- **发现日期**：2026-07-18（全范围审查 Agent C）
- **页面/模块**：数据层（stats/export 查询）
- **问题描述**：backlog/导出的相关子查询全表扫描；当前 150 篇约 15ms 健康，千级后会变慢且 Pipeline 每次刷新调两次 stats。
- **期望行为**：补 literature_parse_runs(work_id,status)、metadata_extractions(work_id,review_status) 索引（schema 变更，需用户确认；建议趁库小就做）。
- **优先级**：🟢 低（当前性能健康）
- **状态**：📋 待处理（待用户确认）

### QA-004: 分类词汇模板仍是预留能力，尚未建立同步/发布流程
- **发现日期**：2026-07-04
- **页面/模块**：模板管理（`api/routes/templates.py`、`TemplateManage.vue`）+ `api/classification_vocab.py` + 前端 labels
- **问题描述**：元数据模板已经接入真实抽取链路；但分类词汇 Tab 仍为只读/预留，保存端点不会自动同步 `classification_vocab.py`、前端 labels 和测试 fixture。
- **期望行为**：分类模板变更应有明确的审核、同步、测试和发布流程；前端编辑入口开放前必须保证后端 vocab、前端 labels、分类抽取 prompt 和测试 fixture 一致。
- **优先级**：🟡 中
- **状态**：📋 待处理

### QA-002: 手动上传候选 PDF 缺少生命周期保护
- **发现日期**：2026-07-03
- **页面/模块**：`POST /api/intake/candidates/{id}/upload-pdf`
- **问题描述**：当前上传端点只校验候选存在，未拒绝已入库、已拒绝或已有 `local_pdf_path` 的候选；重复调用可能覆盖 `_collector_cache/{candidate_id}.pdf` 并改写 resolution。
- **期望行为**：只允许未入库且未拒绝候选上传；已有 PDF 时返回 409 或要求显式 force；上传采用临时文件 + 原子替换，并记录替换原因。
- **优先级**：🟡 中
- **状态**：📋 待处理

### QA-003: 收件箱上传声明大小限制但未执行，且同名文件会覆盖
- **发现日期**：2026-07-03
- **页面/模块**：`POST /api/ingest/upload`
- **问题描述**：`api/routes/ingest.py` 定义了 `MAX_FILE_SIZE = 200MB`，但上传流程未累计检查大小；写入 `_inbox` 时同名 PDF 会直接覆盖。
- **期望行为**：超过限制返回 413 并清理临时文件；同名冲突返回 409 或生成唯一文件名。
- **优先级**：🟢 低
- **状态**：📋 待处理

---

## 已规划问题

<!-- 从待处理转移到这里，标注对应的开发计划 -->

---

## 已解决问题

<!-- 解决后移到这里，保留记录供参考 -->

### UX-009: 合并版文字出现字面 <sub>/<sup> 标签 → ✅ 已解决（2026-08-31）
- **发现日期**：2026-08-31 · **页面/模块**：`/works/:id` 合并版视图（merged_md.py + markdown.js）
- **根因（两层）**：
  1. MinerU vlm 对个别 PDF 产生**失控 `<sub>` 标记**（SkillSentry 单篇 7754 处，疑似被其 logo 下标风格诱导）；
  2. PyMuPDF 样式 span 偏移基于含标签原文，**把标签从中间劈开**（`C<su`+`**b>ontr**`+`olled`）——碎片既躲过剥离正则也无法被渲染器还原，且跨元素拼接成字面 `<sub>`，单节点遍历难以定位。
- **解决方式**：
  - 失控文档（v2 中 `<sub>` > 100 处）：**样式应用前**整篇剥离 `<sub>` 并弃用该篇 style_spans（偏移已失效）；
  - 正常文档：`_apply_style_spans` 增加劈标签防护（span 与标签部分重叠则弃用该 span，宁缺样式不碎标签）；
  - 前端渲染器 `<sub>/<sup>` 白名单还原为真实标签（引文上标等正确显示，其余标签仍转义防注入）；
  - 附带修复重解析后的陈旧读取：文件端点统一 `Cache-Control: no-cache`，前端 content/merged fetch 改 `cache: 'no-store'`。
- **验证**：25 篇 vlm 合并资产离线再生成（0 失败）全量碎片扫描干净；SkillSentry 实测标题/正文无字面标签、27 个上下标正常渲染、图表完好；全量 614 passed。
- **代价说明**：失控文档放弃 PyMuPDF 粗斜体样式（该篇文本干净优先）；正常文档样式不受影响。

### UX-008: /ingest 页面没有上传文件入口 → ✅ 已解决（2026-08-30）
- **发现日期**：2026-08-30 · **页面/模块**：`/ingest` 收件箱 Tab（InboxReview.vue）
- **问题描述**：后端 `POST /api/ingest/upload`（网页上传→_inbox→自动摄入）与前端 `uploadFiles()` 封装自 2026-07-03 起均已存在，但**没有任何页面接线**——收件箱页只有「重新扫描/确认摄入」，网页上传实际不可用。
- **解决方式**：InboxReview 过滤栏新增「上传 PDF」按钮（多选、仅 PDF、防重复提交），上传成功后 notifyNext 反馈摄入统计并自动刷新计划；空状态提示同步更新。
- **保留边界**：上传即自动摄入（后端既有设计，会连带摄入 _inbox 中其他待摄文件）；大小限制与同名覆盖防护仍见 QA-003 待处理。
- **验证**：`npm run build` 通过；按钮渲染/禁用态经浏览器核对。

### UX-007: 输出层合并（MinerU 结构主体 + PyMuPDF 塞入）未接线 → ✅ 已解决（2026-08-29，方案C）
- **发现日期**：2026-08-29 · **页面/模块**：解析链路（`parser/core/document/detail_result/`，来自原 document-parser 服务）
- **用户决策**：方案C——旁路资产 + 合并版 MD + 前端展示，**原始资产一律保留**，有问题可溯源对照。
- **解决方式**：
  1. **合并接线**：`parser/core/document/detail_result/merged_md.py`（新）——`build_detail_assets()` 适配云包 uuid 命名三件套（v1/v2/model.json），调用既有 `merge.merged()`（与原服务逐字节一致，未改）产出 `detail.json`（unified_merge_schema v4）与 `content.merged.md`。合并版 MD 以 MinerU 结构为主体、PyMuPDF 字形样式塞入（style_spans→**粗**/*斜*）；`equation_interline`/`chart`/`algorithm`/`page_footnote` 从 v2 原始节点回填（行间公式 `$$..$$`、图片 `![](images/..)`、算法代码块），页面装饰节点剔除。
  2. **自动触发**：`router.route_and_parse` 在 cloud vlm 成功后自动生成旁路资产（三处路径：强制 vlm/质检回退/扫描型）；失败仅告警不影响解析；重解析清理集补充两个新产物名。
  3. **端点**：`GET /api/files/{work_id}/merged`（合并版 MD）、`GET /api/files/{work_id}/detail`（诊断 JSON），文件名白名单 + works 边界校验。
  4. **前端**：WorkDetail 内容预览升级三态——**合并版**（默认，有产物时）/ 原版渲染 / 原版原文 + 「合并诊断 JSON」溯源链接；合并产物缺失时禁用并提示（仅云 VLM 解析生成）。
  5. **存量回填**：`scripts/literature_merge_detail.py`（离线、不耗额度，dry-run 默认）——存量 8 篇 vlm 全部回填成功（502/427/1023/174/300/246/231/720 节点）；W-arxiv-1706.03762 因源 PDF 缺失跳过（存量数据问题，与本功能无关）。
- **验证**：新增 14 项测试（`parser/tests/test_merged_md.py`、`parser/tests/test_router_detail_assets.py`、`tests/test_files_merged_endpoints.py`）；全量 606 passed；`npm run build` 通过；浏览器实测 W-arxiv-2506.19248 合并版（标题/粗体作者/行内公式/图表/表格渲染）、原版回退（19 图）、诊断 JSON 链接均正常。
- **保留边界**：pymupdf 单独路径无 MinerU 结构、不生成合并资产；content.md 主链路输入完全不变，元数据/分类抽取口径不受影响。

### UX-002: PyMuPDF 解析后丢失 PDF 中的图片/图表 → ✅ 已解决（2026-08-29）
- **发现日期**：2026-07-02 · **页面/模块**：解析流程（parser/core/mineru/router.py 路由策略）
- **解决方式**（三个断点一起打通）：
  1. **PyMuPDF 图片抽取（方案C）**：`parser/core/mineru/pymupdf_client.py` 解析时按页提取实际绘制的栅格图（`get_image_info(xrefs=True)`，含跨页 xref 去重、图标级小图过滤），落盘 `images/` 并在 content.md 按页追加 `![](images/...)` 引用——与 VLM 产物契约一致，不耗云额度。矢量图表不在此路径覆盖。
  2. **后端覆盖 + 强制重解析（方案A）**：`route_and_parse` 新增 `backend` 参数（auto/pymupdf/vlm，显式 pymupdf 不回退）；`POST /api/parse/trigger` 接线 `backend` + `force: true`（重解析不限 pending）；CLI 新增 `--backend/--force/--work-ids`；WorkDetail 页解析状态行新增后端下拉 + 「重新解析」按钮。重解析前自动清理已知解析产物。
  3. **前端可见（新增）**：`GET /api/files/{work_id}/images/{name}` 图片端点（文件名白名单 + works 边界校验）；WorkDetail 内容预览支持「渲染/原文」切换，渲染模式由纯 JS markdown 渲染器（`web/src/utils/markdown.js`，无新依赖）展示标题/表格/图片，`images/` 相对引用自动改写到后端端点。
- **验证**：新增 24 项测试（`parser/tests/test_pymupdf_images.py`、`parser/tests/test_router_backend_override.py`、`tests/test_parse_trigger_reparse.py`、`tests/test_files_images_endpoint.py`）全过；全量 592 passed；`npm run build` 通过；真实文献 W-sha-05e46bff6988（Claude Sonnet 5 System Card，本问题原始案例）强制重解析后图片落盘、端点可访问、前端渲染可见。
- **保留边界**：矢量绘制的图表仍需 VLM 路径；旧 pipeline 后端维持弃用。

### UX-001: 缺少批量触发流程的管理页面 → ✅ 已完成
- **解决日期**：2026-07-01/05 复核确认
- **解决方式**：`/pipeline` 已支持批量摄入、批量解析、批量元数据抽取、批量分类抽取；Dashboard 已提供“流程管理”快捷入口。该项按“每个阶段支持批量触发，然后分别到各审核页面审核”的验收口径关闭。
- **保留边界**：暂不做无人工闸门的一键全流程自动跑；大规模自动调度另行规划。

### PipelineView 分类模糊度阈值口径错误 → ✅ 已修复
- **解决日期**：2026-07-17
- **问题描述**：PipelineView 模糊度阈值沿用 0.7/0.4 小数口径，与后端 0–100 分制不一致，导致高/中歧义 badge 与筛选器失效。
- **解决方式**：阈值由 0.7/0.4 调整为 50/20（commit 25b097f），badge 与筛选器恢复正常。
- **验证**：`npm run build` 通过。

### UX-004: 字段级重抽前端入口（双模式） → ✅ 已完成
- **解决日期**：2026-07-04
- **解决方式**：新增后端 `rerun-preview` / `rerun-apply` / `rerun-prompt` 三个端点，复用 `scripts/literature_metadata_rerun.py` 的字段级重抽、field_focus prompt 和 supersede 链路。
- **前端入口**：`MetadataReview.vue` 每个可重抽字段旁新增「重抽」和「复制」按钮；重抽先预览 diff，确认后写入新 extraction 并 supersede 旧记录；复制 prompt 作为剪贴板/手动降级方案。
- **验证**：`tests/test_metadata_rerun_api.py` 15 passed；`web` 构建通过；健康检查通过。

### QA-001: 元数据模板接入真实抽取链路 → ✅ 已完成
- **解决日期**：2026-07-04
- **解决方式**：新增共享 loader `api/metadata_template.py`，把 `templates/templates.json`、内置字段、字段校验、prompt 生成、rerun 字段白名单统一为一个运行时事实源。
- **接入范围**：`scripts/literature_metadata_extract.py`、`POST /api/metadata/extract`、`scripts/literature_metadata_rerun.py`、`rerun-preview`、`rerun-prompt` 均读取当前元数据模板；`validate_extraction()` 的 missing 字段也按模板字段计算。
- **前端动态化**：`MetadataReview.vue` 已读取模板字段生成审核表；自定义字段可展示、编辑、复制 prompt、发起字段级重抽；人工编辑的模板字段会提升为 high confidence。
- **使用文档**：`docs/manuals/user-manual.md` 已说明前端 `/templates` + `/metadata` 使用方式；`docs/manuals/cli-manual.md` 与 `scripts/README.md` 已说明 CLI/API/agent 批量处理方式，agent 批量重抽直接读模板并调用脚本，不需要从界面复制 prompt。
- **资产落地**：新增可审查的 `templates/templates.json` baseline（metadata v1.1）。
- **遗留拆分**：分类词汇模板同步/发布流程另记为 QA-004。

### UX-003: 元数据字段模板可视化展示 → ✅ 升级为独立模板管理页面
- **解决方式**：从 MetadataReview 详情弹窗（只读展示）升级为 `/templates` 独立页面（可编辑+三大Tab）
- **解决日期**：2026-07-03
- **详情**：见 `docs/PROJECT_HISTORY.md` §六「模板管理独立页面」
