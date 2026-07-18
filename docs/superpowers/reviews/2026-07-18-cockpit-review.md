# 阶段二驾驶舱与流程接力：两轮模型独立审核记录

> 状态：当前有效
> 审核日期：2026-07-18
> 审核对象：`api/routes/ingest.py`（pipeline/stats 扩展）、`tests/test_pipeline_stats.py`、`web/src/views/Dashboard.vue`、`web/src/composables/useNextStep.js`、`web/src/views/{InboxReview,PipelineView,WorkDetail,MetadataReview,ClassificationReview}.vue`、`web/src/components/StageCard.vue`
> 方法：两个互相独立的子 agent（无实现上下文），第一轮代码质量审核 + 第二轮事实与产出核对

## 第一轮 · 代码质量审核（8 条 finding）

| # | 严重度 | finding | 处理 |
|---|--------|---------|------|
| F1 | **高** | useNextStep 误用 naive-ui 2.44 message API（`{render}` options 形态不生效，toast 渲染为空且 duration 被吞），所有带跳转的接力提示失效 | ✅ 已修：改为 `message.success(renderFn, {duration: 6000})`（content 接受 Function，源码 `message-props.mjs:7` 确认） |
| F2 | 中 | Dashboard"待去重"恒为 0：读取不存在的 `total` 字段（端点返回 `total_groups`）——沿用自旧代码 | ✅ 已修：`total_groups`（真实库验证 21 个重复组正确显示） |
| F3 | 中 | "待摄入"链接落点 /ingest 默认打开发现检索 tab 而非收件箱 | ✅ 已修：链接改为 /inbox 直达 InboxReview |
| F4 | 低 | 新测试对 session 级 sample_db 的清理不防断言失败 | ✅ 已修：改 yield fixture teardown |
| F5 | 低 | 积压补审两行链接 /works，落点页无法复现该数字（Works 无"未批准"筛选） | ◐ 记录为已知限制：积压包含"从未抽取"的 work，任何审核页都无法完整复现该口径；后续可在 Works 加筛选（未修） |
| F6 | 低 | WorkDetail 分类按钮 tooltip 无条件提示"建议先审元数据"，元数据已批准时误导 | ✅ 已修：按 `metadata_extraction.review_status === 'approved'` 条件显示 |
| F7 | 低 | intake.pending（排除 ingested）与 IntakeReview 页 /api/intake/stats（不排除）口径理论边界；真实库交叉行为 0 | ◐ 记录：stats docstring 已注明口径；edge case 当前不存在（未修） |
| F8 | 低 | `assert "pending" in stats["parse"]` 形同烟雾断言 | ✅ 已修：改 `== 0` 具体断言 |

第一轮验证无问题要点：backlog 与导出门禁互为补集、Dashboard 字段映射正确、旧 API 调用清干净、StageCard 插槽增量安全（仅 PipelineView 使用）、自动下一条两页对称且不会选中刚 rejected 条目、接入点全部提示级。

## 第二轮 · 事实与产出核对（6 口径全部成立）

| # | 结论 | 摘要 |
|---|------|------|
| 1 | 成立 | stats 全部 9 个指标与只读 SQL/文件系统独立重算逐项一致（含 inbox 子目录 PDF=1） |
| 2 | 成立 | SPA 可达、/api/export/bibtex 无回归 |
| 3 | 成立 | 接力提示均"前往/去"文案，全 src 无 watch/onMounted/setInterval 自动触发链（硬边界成立） |
| 4 | 成立 | 分类前置提示数据源为 backlog.metadata_unapproved（当前 11>0 应显示） |
| 5 | 成立 | 两审核页自动下一条逻辑一致，"仅待审"筛选下无缝续审 |
| 6 | 成立 | 无新依赖、无 schema 变更 |

第二轮观察（非缺陷）：metadata pending 共 11 条但其中 10 条挂隔离 work，故"元数据待审"只显示 1（符合排除隔离设计）；intake 5 条 approved 未晋升不计入 pending（与注释口径一致）。

## 修复后回归

- `pytest tests -q`：566 passed, 5 skipped
- `healthcheck_library.py --json`：五类全空
- `check_docs.py`：PASS
- `npm run build`：通过
- 真实库 smoke：stats 9 指标与 DB 直查一致；duplicates `total_groups=21` 正确供给 Dashboard

## 环境说明

- F1 的修复（render 函数作为 content）经 naive-ui 2.44.1 源码确认，但未做真实浏览器点击验证——建议用户首次使用摄入/抽取时留意 toast 是否带"前往"按钮。
- Dashboard 面板视觉与交互未做浏览器端验证（两轮均为静态+API 层）。
