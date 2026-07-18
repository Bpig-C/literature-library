# 阶段一/二收尾：全范围审查（首次执行）

> 状态：当前有效
> 审查日期：2026-07-18
> 方法：4 个互相独立的只读子 agent（文档一致性 / 数据口径 / 代码风险 / 使用旅程）+ 主 agent 交叉复核
> 依据：FUTURE_WORK_PLAN 主线配套原则「每阶段一轮全范围审查」（首次执行，往回适用于阶段一+二）

## 处置总览

| 来源 | finding 数 | 已修 | 登记/暂缓 | 误报剔除 |
|------|-----------|------|-----------|----------|
| Agent A 文档一致性 | 26 | 26（文档修复批） | 0 | 1（IngestHub 接力缺口疑点，实为内嵌组件复用） |
| Agent B 数据口径 | 5 健康问题 | 0（均登记待决策） | 5 | 0（13 项指标全部与独立 SQL 一致） |
| Agent C 代码风险 | 7 | 4 | 3（索引/schema/conftest 待确认） | 0 |
| Agent D 使用旅程 | 10 | 9 | 1（I-7 积压落点筛选） | 0 |

## 已修复（本轮）

**高危**
- **I-1 SPA 深链 404**：刷新/收藏/分享任何前端路由均 404。修：`api/main.py` 增加 404 exception handler，非 /api 路径回退 index.html（验证：/inbox、/metadata?search= 等 200，/api 404 仍 JSON）。
- **I-2 `window.__naive_message` 从未挂载**：`mountMessageApi` 定义后无调用点，旅程 B（主题创建/发现检索/采集审核/模板管理）成功与错误提示全部静默。修：新增 `MessageApiMount.vue` 置于 NMessageProvider 内挂载（发现 docstring 声称"在 App.vue setup 调用"在 naive-ui 注入机制下不可行，正确形态是 provider 子组件）。

**文档漂移（26 项，修复批执行）**
- TECHNICAL_OVERVIEW：路由 11→12 组、补 export 三端点、pipeline/stats 描述、删"引用导出未实现"、综述矩阵改写、Dashboard 职责、变更记录。
- HANDOVER：路由/组件计数、#6/#10 状态矛盾（与 FUTURE_WORK_PLAN 直接冲突）、已完成表补录。
- README/user-manual/cli-manual/business-flows：补出口侧（流程七：已批准文献导出）与自动下一条。
- superpowers 治理闭环：两份阶段 plan 归档至 `docs/_archive/superpowers/plans/` 并改状态，README 索引同步。
- PROJECT_HISTORY 补口径澄清条目；FUTURE_WORK_PLAN 日期戳。

**中危代码问题**
- A3 批量批准后陈旧 selected 可二次提交 + 两个 doBatchApprove 无 try/catch（失败静默）。修：批量后 selected=null + catch 提示。
- I-4 discovery accept 后无接力。修：notifyNext → /intake。
- I-3 Pipeline 跳传 query 是死参数（/discovery?run_id=、/intake?selected= 目标页不消费）。修：两目标页支持深链选中。
- I-5 Pipeline「前往文献入库上传 PDF」过期文案（/ingest 无上传 UI）。修：如实描述 _inbox 路径 + 链接改 /inbox。
- I-10 主题创建零反馈。修：成功 toast（随 I-2 修复生效）。

**低危顺手修**
- A4 PipelineView 两个死 #extra 块（自引入起从未渲染）移除；A7 StageCard 禁用 tooltip 文案泛化；A5-c BibTeX/RIS 不再白打 digest 查询；Agent A C1 疑点复核：IngestHub 以 tab 内嵌 InboxReview（IngestHub.vue:8,17），接力覆盖两路，非缺口（误报剔除）。

## 登记待决策（写入 USER_ISSUES.md / 待用户确认）

| # | 问题 | 为何暂缓 |
|---|------|----------|
| B-1 | classification_extractions 缺 superseded_by 列（schema 不对称） | schema 变更需用户确认（红线） |
| B-2 | 隔离路径语义分叉：works 页隔离留 pending extractions（现存 10 条，可经"显示已隔离"找回），审核页隔离连带 reject | 语义决策权在用户 |
| B-3 | intake promote 后 review_status 未同步 ingested（1 行：ingested+approved 交叉） | 需数据订正+代码同步，一并确认 |
| B-4 | 8 篇 approved 后被隔离的 work 被导出静默排除（非任何 backlog 口径） | 确认是否为预期终态 |
| C-1 | parse_runs/work_id、metadata_extractions/work_id 无索引，stats/export 全表扫描（当前 15ms 健康，千级变慢） | schema 变更需确认，建议趁库小补 |
| C-2 | works.parse_status 派生漂移 29 行（28 隔离 work 停留 succeeded；1 活跃 W-sha-a8a170a6a268 active 源无 parse run） | 需用户判断该 work 是"换副本预期态"还是"漏解析"；quarantine/restore 不重算 parse_status 的语义待定 |
| C-5 | conftest 与真实 schema 漂移（UNIQUE 约束、discovery 两表、parse_status 词表），新测试在宽松 schema 下掩盖真实约束 | 修 fixture 是一批工作量，立待办 |
| C-6 | export 规模边界（~32k 篇撞 SQL 变量上限；digest 选取无次级排序键） | 当前无风险，记录为已知限制 |
| I-6/I-7/I-9 | /ingest 默认 tab、积压落点无筛选、导航与页面标题命名不一致 | 低优先体验项 |
| I-8 | 审核完成无下一步接力（元数据批准→分类抽取；分类批准→导出） | 体验增强候选 |

## 复核结论

- 数据口径全部健康：stats 13 项指标与独立 SQL 完全一致；积压分解 11+20=31 精确成立，无第三种隐藏状态；导出 111=非隔离 approved，与积压互补（111+11=122=全部非隔离）。
- 数据健康 10 项抽查：orphan/supersede 断链/applied 交叉态/多条 approved 全部为 0，仅发现 B-1/B-2/B-3 三个真实遗留。
- 旅程 A 全闭环（含接力与导出）；旅程 B 在 I-2/I-4 修复后闭环。
- 修复后回归：pytest 566 passed、healthcheck 全空、check_docs PASS、npm build 通过、SPA 深链 200、Dashboard 渲染验证（截图核对数字与文案）。

## 方法论备注（供后续全范围审查复用）

- 本次 4 份报告零误报（仅 Agent A 一条疑点经复核排除），证据质量高。
- 高危两项（I-1/I-2）均为"功能审核与两轮独立审核都未覆盖、只有全范围视角才能看到"的问题，验证了该机制的价值。
