# 文献库未来工作计划

> 状态：当前路线图
> 更新时间：2026-07-04
> 当前基线：V1 发布阻断项已清零；V1.1 前端端到端主流程与受约束发现检索已完成；V1.3 知识闭环 P0-P2 已完成；前端全面重构 Phase 0-5 已完成；流程管理页面(Pipeline)已创建并增强；模板管理独立页面(TemplateManage)已创建（元数据可编辑，分类/Discovery预留）；字段级重抽前端入口 UX-004 已完成（智能预览写入 + prompt 复制降级）；前端体验大范围优化已完成（导航栏/采集审核/PDF链路/来源追溯）。2026-07-03 审查修复后复核：`pytest tests -q -p no:cacheprovider --basetemp .codex_tmp\pytest-all-audit` 通过（511 passed, 5 skipped），`scripts/healthcheck_library.py --json` 五类问题全空，`npm.cmd run build` 通过。

本文档只记录尚未完成、需要继续规划或实施的工作。已完成阶段、旧判断和历史路线迁移到 `docs/PROJECT_HISTORY.md`；已完成的分阶段细节归档到 `docs/_archive/superpowers/`，新计划和新审核再写入 `docs/superpowers/plans/` 与 `docs/superpowers/reviews/`。

## 维护原则

- 当前事实以代码、测试、healthcheck 和 active 文档为准，不以历史计划为准。
- 新增任务进入本文档前，应确认不是已有历史计划中的已完成项。
- 完成后的任务应迁移到 `docs/PROJECT_HISTORY.md` 或对应 review/result 文档，不长期留在未来计划中。
- V1.1 任务应优先保持小而可验收：明确目标、涉及入口、测试/验证命令、回滚方式。

## 规划层级

`FUTURE_WORK_PLAN.md` 不是具体实施方案，而是路线图和优先级判断。它回答：

- 哪些方向值得继续做；
- 为什么做；
- 大致优先级如何；
- 做到什么程度可以进入下一阶段实施。

具体任务实施方案应单独成文，通常放在 `docs/superpowers/plans/`，例如 `2026-xx-xx-v1.1-*.md`。实施方案应回答：

- 本阶段的明确目标和非目标；
- 涉及哪些模块、接口、文档和数据迁移；
- 如何分工给 agent/subagent；
- 每一步的测试要求和验收口径；
- 至少两轮复核方式；
- 完成后哪些内容要迁移到 `docs/PROJECT_HISTORY.md` 或 review/result 文档。

因此，合理结构是：

- `FUTURE_WORK_PLAN.md`：长期方向 + V1.1/V1.2 优先级。
- `docs/superpowers/plans/*.md`：某一阶段的可执行实施方案。
- `docs/superpowers/reviews/*.md`：阶段完成后的审核、整改和验收结果。
- `docs/PROJECT_HISTORY.md`：已完成阶段的汇总入口。

## 当前近期重点（最高优先级）

> ✅ 近期发布/启动阻断项已清零。详见 `docs/PROJECT_HISTORY.md`。
>
> 当前仍有高优先级体验与治理待办（如 UX-001、UX-002、QA-001），但不阻塞项目启动和基础回归。

---

## 次优先方向

以下方向在 V1.3 P0-P1 完成后继续有价值，但不应早于上述最高优先级。

### A. 元数据抽取模板

定位：长期维护的抽取规范，用于定义模型从 `content.md` / PDF 证据中抽取哪些字段、如何判断置信度、如何记录证据、哪些字段允许自动回填。

为什么需要长期维护：

- 文献类型越多，元数据字段和边界情况越多。
- 不同来源 PDF 的结构差异会暴露新的抽取失败模式。
- 审核中积累的人工修正应反哺模板，而不是只停留在单条记录。
- **当前状态**：独立模板管理页面已创建（`/templates` → TemplateManage.vue），元数据字段可在线查看和编辑，保存到 `templates/templates.json`。详见 `docs/PROJECT_HISTORY.md`「2026-07-02 前端体验与流程完善」§六。

后续方向：

1. **~~【第一步】字段模板可视化展示~~（UX-003）— ✅ 已完成**
   - 已从 MetadataReview 详情弹窗升级为**独立模板管理页面** `/templates`
   - 三大 Tab：元数据字段（可编辑）/ 分类词汇表（预留）/ Discovery协议（预留）
   - 后端 API 6 个端点就绪（`api/routes/templates.py`），含自动备份和版本回滚
   - 归档位置：`docs/PROJECT_HISTORY.md` §六

2. **~~【第二步】字段级重抽前端化~~（UX-004）— ✅ 已完成**
   - 智能模式：每个字段旁「重抽」→ 后端 `rerun-preview` → 复用 opencode/llm_judge 链路 → 预览 diff 后确认写入
   - 降级模式：「复制」→ 后端 `rerun-prompt` → 复制带 field_focus 的 prompt
   - 写入模式：`rerun-apply` 校验 preview/new_extraction 后写入新记录并 supersede 旧记录

3. **【当前下一步候选】模板管理接入真实抽取链路**（QA-001）
   - 建立元数据抽取模板版本号。
   - 将字段定义、证据要求、风险规则、回填语义写成可审查文档。
   - 抽取脚本、rerun 脚本、测试 fixture 和审核 UI 统一读取模板 loader。
4. **从 MetadataReview 的 rejected / needs_fix / supersede 案例中定期提炼模板改进项。**

优先级：高。它直接影响后续所有文献的结构化质量。

#### 当前已实现的底层能力

以下能力已在 CLI 层或代码层就绪：

| 能力 | 状态 | 入口 |
|------|------|------|
| 全量重抽 | ✅ CLI | `literature_metadata_rerun.py --ext-id ME-xxx --rerun` |
| 字段级重抽 | ✅ CLI | `--fields title,url --rerun`（merge_selected_fields 保留旧值） |
| 预览不写库 | ✅ CLI | `--no-write --json` |
| field_focus prompt 注入 | ✅ 代码 | `field_focus_instruction()` |
| supersede 审计链 | ✅ 代码 | 新记录 + 旧记录标记 superseded_by |
| LLM 调用链 | ✅ 代码 | llm_judge.chat() → opencode subprocess（无需额外 token） |
| 模板管理后端 API | ✅ HTTP | `GET/POST /api/templates/*`（6 端点） |
| 模板管理前端页面 | ✅ 页面 | `/templates` → TemplateManage.vue |
| 元数据字段在线编辑 | ✅ UI | 内联编辑 + 增删 + 导出 JSON/Prompt |
| 字段级重抽 HTTP API | ✅ HTTP | `POST /api/metadata/{ext_id}/rerun-preview` / `rerun-apply`，`GET /rerun-prompt` |
| 字段级重抽前端入口 | ✅ UI | MetadataReview 字段行「重抽」+「复制」双模式 |

缺口：模板定义仍未接入真实抽取链路（QA-001）；模板版本号、脚本 loader、测试 fixture 和审核 UI 需要统一。

### B. 文献分类规范与审核模板

定位：固定研究领域内的分类本体、标签规范、审核准则和争议处理规则。

为什么需要长期维护：

- 当前项目不是通用文献库，而是服务于特定博士研究领域。
- 领域边界、方法标签、风险域、阅读优先级会随着研究推进逐步稳定。
- 分类审核不只是 UI 功能，更是研究方法的一部分。

后续方向：

- 将分类标签、标量字段、多值标签的定义与例子写成规范。
- 为容易混淆的标签建立判别规则和反例。
- 从 ClassificationReview 的高模糊度、人工改动和 rejected 案例中定期更新规范。
- 分类规范变更需要同步 `classification_vocab.py`、`labels.js`、测试和审核说明。

优先级：高。它决定文献库能否形成稳定、可复用的领域地图。

### C. 采集与检索模板

定位：指导 collector 如何从主题、关键词、机构、作者、仓库和种子文献出发，持续发现候选文献。

当前状态：

- V1.1 已具备受约束发现检索地基：`topic` / `name` / `title` / `url` 可生成 discovery run，agent 按 `docs/discovery-agent-protocol.md` 回填 hits，人工接受后只进入 intake candidate。
- **[V1.2 已完成] Composite 多信号组合输入**：新增 `composite` 模式，允许同时提供 names、titles、authors、institutions、keywords、known_urls、preferred_domains、exclude_terms、artifact_type_hint、max_results、freeform_note 等多种信号。agent 根据多种线索综合生成更优的搜索策略（含 search_strategy、dedup_guidance、reasoning 字段），解决单一模式输入对 agent 过于弱的问题。详见 `docs/discovery-agent-protocol.md` 的 "Composite Input Schema" 章节。
- 采集仍坚持人工闸门、小批量验证和去重安全，不做无约束大规模自动抓取。
- 当前 discovery 主要解决"从主题/名称/标题/URL/组合信号 找到可审核候选"的第一步，后续模板应继续沉淀来源质量反馈、失败模式和可复用检索策略。

后续方向：

- 从 accepted/rejected discovery hits 中沉淀可复用的来源质量规则、领域 query 模板、排除词和可信域名线索。
- 补强结构化来源适配：OpenAlex / Crossref / Semantic Scholar / GitHub / Hugging Face 等可作为后续 adapter，而不是让 agent 临场自由探索。
- 建立 discovery run 的失败复盘机制：无结果、噪声高、重复高、低可信来源、title-only 命中等应能回写为模板改进项。
- 将"广泛发现 -> hit 审核 -> intake 审核 -> ingest"的经验整理为长期采集与检索模板。
- 将低质量来源、重复来源、坏 PDF、需要好副本等反馈写回采集策略。

优先级：高。V1.1 已完成第一版受约束发现检索；V1.2 已实现 composite 多信号组合模式；后续价值在于把一次次人工审核经验固化为稳定模板和 adapter，而不是扩大成无边界抓取。

### D. 流程管理面板（批量触发）— ✅ 已完成

> 已归档至 `docs/PROJECT_HISTORY.md`「流程管理页面创建与增强（Pipeline）」章节。

## V1.1 优先队列

### 1. Discovery 本地模型自动执行器

当前 V1.1 discovery 的实际执行方式是：前端创建 planned run，用户复制 agent 指令，再交给本地模型/Codex/opencode 执行检索并回填 hits。这个流程可用且边界清晰，但还不是“一键生成方案后自动执行”。

后续可单独实现本地执行器，把 `/discovery` 的 planned run 交给 opencode 或其他本地 agent 执行：

- 前端提供“执行检索”按钮，或后端提供 `POST /api/discovery/runs/{run_id}/execute`。
- 后端创建受控子进程或任务队列，调用 opencode/Codex，本地模型必须先读 `docs/discovery-agent-protocol.md`。
- 执行器需要记录 stdout/stderr、开始/结束时间、退出码、错误摘要和回填统计。
- 必须有超时、并发上限、取消/重试、失败状态回写和日志查看入口。
- 权限边界保持不变：执行器只能回填 hits，不能 accept、promote、写 `works`、改 ontology vocab 或下载/摄入 PDF。
- 至少两轮审核：一轮查进程调度/权限边界，一轮查搜索结果污染、失败恢复和 UI 状态一致性。

验证：

- 用 fixture 或 dry-run 模式证明 planned run 可以被执行器领取、执行、回填并更新状态。
- opencode 不可用、超时、返回非 JSON、部分 hit 失败、重复 hit 等场景都有明确错误反馈。
- `/discovery` 页面可以看到执行状态、run id、日志入口和回填数量。

优先级：中高。它能减少手工复制指令的摩擦，但不应早于当前 hit 审核和 intake 闸门的稳定性。

### 2. 元数据抽取模板 V1.1

元数据抽取模板已作为独立维护资产落地：

- **✅ 已完成**：独立模板管理页面 `/templates`（TemplateManage.vue），三大 Tab（元数据/分类/Discovery）
- **✅ 已完成**：后端 6 个 API 端点（`api/routes/templates.py`），含自动备份和版本回滚
- **✅ 已完成**：元数据字段在线查看 + 内联编辑 + 增删 + 导出 JSON/Prompt
- **🔒 预留**：分类词汇表和 Discovery 协议编辑（后端已实现，前端按钮 disabled）

剩余目标：

- 梳理当前 metadata 字段、证据要求、风险分级、回填语义。（部分完成——字段定义已统一到 templates.json）
- 定义模板版本号和变更记录方式。（备份机制已有，版本号待加）
- 建立从 MetadataReview 人工修正反哺模板的流程。
- 增加最小 fixture，覆盖常见文献类型和已知失败模式。
- **✅ 已完成**：字段级重抽前端化（UX-004），已具备智能预览写入 + prompt 复制降级双模式。

验证：

- 模板文档、脚本参数、测试 fixture、审核页面说明一致。
- 新增或更新测试能证明旧失败模式被覆盖。

### 3. 分类规范与审核模板 V1.1

把分类本体从“代码中的词表”提升为“可维护的领域规范”。

目标：

- 明确标量字段和多值标签的定义、例子、反例。
- 梳理高模糊度分类案例，沉淀判别规则。
- 建立分类规范变更流程：文档 -> vocab -> labels -> 测试 -> 审核页面。
- 明确人工审核时“保存草稿”“批准”“拒绝”“隔离”的语义。

验证：

- `classification_vocab.py`、`labels.js` 和规范文档一致。
- 高模糊度案例可在测试或审核样例中复现。

### 4. 分类标签事务式保存

当前 WorkDetail 多值分类标签保存仍是前端按 diff 执行 delete-then-add。若中途失败，可能留下部分写入状态。

目标：

- 新增后端批量/事务式标签保存端点。
- 前端 WorkDetail 改为一次提交完整多值标签变更。
- 失败时不产生部分状态，或返回可恢复的明确错误。

验证：

- 增加后端事务测试。
- 覆盖非法 tag、部分失败、空列表、重复 tag 等边界。

### 5. Parse status 多源语义

`GET /api/parse/status?work_id=` 对多源 work 的语义需要明确：返回 source 级列表，还是返回聚合状态。

目标：

- 定义多源 work 的状态聚合规则。
- 如保留单条返回，文档必须说明选择规则。
- 如返回列表，前端 WorkDetail 需要展示每个 source 的状态。

验证：

- 使用 fixture DB 覆盖单源、多源、active+archived 混合场景。

### 6. Dashboard 队列压力面板

Dashboard 目前更像导航入口，尚未成为治理控制台。

目标：

- 展示 metadata、classification、intake、inbox、duplicates 的待办数量。
- 明确区分“阻断项”“建议处理”“历史信息”。
- 每个数字能跳转到对应筛选页面。

验证：

- 前端构建通过。
- API summary 数据有 fixture 测试或页面 smoke。

### 7. 审核日志语义统一

metadata review 倾向提交 diff，classification review 倾向提交完整表单。两者审计语义不完全一致。

目标：

- 明确审核记录保存的是“完整确认状态”还是“人工修改字段”。
- metadata 与 classification 审核备注、review_source、reviewed_at、applied 语义一致。
- 文档更新到 `TECHNICAL_OVERVIEW.md` 或子项目架构文档。

验证：

- 覆盖 approve、needs_fix、reject、draft、batch approve 的审计字段。

### 8. `needs_better_copy` 替换源文件链路

V1 中 `needs_better_copy` promote 已被安全拒绝，避免误创建重复 work。V1.1 可考虑接入真正替换链路。

目标：

- promote 识别 `needs_better_copy` 后替换隔离 work 的坏源文件，而不是创建新 work。
- `replace_quarantined_source` 必须创建新的 `literature_parse_runs(status='pending')`。
- 替换后 work、source_files、work_codes、parse_runs、healthcheck 状态一致。

验证：

- 覆盖好副本替换、缺失 PDF、重复 sha、parse run 创建、healthcheck 零问题。

### 9. 文档治理自动化

当前已经有 `docs/DOCUMENT_GOVERNANCE.md` 和 `docs/superpowers/README.md`，但文档门禁仍靠人工 grep。

目标：

- 增加一个轻量文档检查脚本或测试。
- 检查 active 文档中是否出现禁止性旧入口：`parse_ledger.json` 当前状态源、默认 `D:\06_tools\document-parser`、当前 healthcheck 指向旧脚本、root-level `scripts/_*.py`。
- 输出允许命中与需处理命中的分类。

验证：

- 脚本在当前仓库运行通过。
- 后续 CI 或发布前 runbook 可直接调用。

### 10. 引用导出与综述矩阵

引用导出和综述矩阵仍是研究工作流的重要缺口。

目标：

- 支持 BibTeX/RIS 导出。
- 定义综述矩阵导出的字段来源和筛选条件。
- 与 `analysis_runs`、分类标签、metadata 审核状态对齐。

验证：

- 使用 fixture 数据生成稳定导出。
- 覆盖缺失 DOI、arXiv、中文标题、多作者等边界。

### 11. proposed_new 标签的转正路径（V1.3 遗留体验项）

V1.3 已支持建主题时填词表外的自定义标签（存为 `{group, value, status:"proposed_new"}`，map_status 仍 seedling）。但 `collector/topics.py` 的 `_validate_mapped_tags` 在主题推进到 `mapped` 时**仍严格拒绝词表外值**——所以一个带 proposed_new 标签的主题，从 proposed 推进 mapped 会被拒，除非先去掉自定义标签或人工把值纳入 `classification_vocab`。

这是有意的设计边界（符合"自定义标签必须人工审核后才能进正式词表"的硬约束），**不是 bug**。但当前缺少清晰的用户路径与提示。

目标：

- 明确转正流程：人工审核 proposed_new 值 → 决定纳入 `api/classification_vocab.py` 还是丢弃 → 主题才能推进 mapped。
- 前端 TopicsReview 在 transition 到 mapped 失败时，给出可读提示（"含 N 个待审核自定义标签，先转正或移除"），而不是裸 ValueError。
- 可选：词表侧增加 proposed_new 候选队列与审核端点（与第 4 项"分类标签事务式保存"协同）。

验证：

- 带 proposed_new 标签的主题，未转正时 transition→mapped 被拒且有清晰提示。
- 自定义值纳入词表后，同一主题可正常推进 mapped。

来源：2026-07-01 V1.3 完成后第三方审核（`docs/_archive/superpowers/plans/2026-06-30-v1.3-handoff.md` 反偷懒自检）。

## 暂不进入 V1.1 的候选项

- 完整前端上传并创建 work 的能力：当前 `_inbox` + `/inbox` 已满足 V1 使用。
- 移动端完整适配：当前项目主要是本地桌面研究工具。
- 自动化大规模采集调度：collector 仍应以人工闸门和小批量验证为优先。
- 无约束大规模自动检索和自动入库：V1.1 已支持受约束 discovery run + hit 审核，但仍不能跳过检索方案确认、候选审核和去重闸门。
