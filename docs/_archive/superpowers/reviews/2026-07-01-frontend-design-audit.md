# 前端 UI/UX 审计与重构方案

**日期**: 2026-07-01
**审计范围**: V1.3 P2-3 前端设计审计
**审计结论**: 零代码变更，仅产出设计文档

---

## 一、逐页现状审计

### 1. Dashboard.vue

| 维度 | 评估 | 说明 |
|------|------|------|
| 视觉一致性 | 良好 | 使用 CSS 变量，样式简洁 |
| 组件复用 | 无 | 独立页面，无共享组件 |
| 布局合理性 | 良好 | 自适应网格 stat-card，quick-links 横排 |
| 交互反馈 | 不足 | 无加载态、无错误态，仅 mount 时拉一次数据 |
| 响应式 | 缺失 | 无 media query，stat-card 靠 auto-fit 自适应 |

**硬编码色值**: `#f8fafc`(table header)、`#eef5ff`(hover)、`#374151`/`#3a4250`(text)

---

### 2. Works.vue

| 维度 | 评估 | 说明 |
|------|------|------|
| 视觉一致性 | 混合 | 大量使用 Naive UI 组件，但自定义 CSS 仍多 |
| 组件复用 | 部分 | 使用 n-input/n-select/n-button/n-pagination/n-modal |
| 布局合理性 | 良好 | 表格布局合理，高级筛选收起/展开 |
| 交互反馈 | 良好 | 有 loading (Naive UI 内置)、搜索防抖 |
| 响应式 | 部分 | filter-grid 有 `@media (max-width: 900px)` |

**硬编码色值**: `#f8fafc`、`#eef5ff`、`#374151`、`#6b7280`、`#d97706`、`#9ca3af`

---

### 3. DiscoveryReview.vue

| 维度 | 评估 | 说明 |
|------|------|------|
| 视觉一致性 | 不足 | 独立定义紫色系按钮(#7c3aed/#ede9fe/#6d28d9)，与全局 accent 色脱节 |
| 组件复用 | 无 | 完全自包含，badge/pagination/review-bar 全部自定义 |
| 布局合理性 | 良好 | 三栏布局(run/hits/detail)，信息密度高 |
| 交互反馈 | 不足 | 使用原生 alert() 做成功/失败反馈 |
| 响应式 | 良好 | 三个断点: 1100px(双栏)、768px(单栏) |

**硬编码色值**: `#7c3aed`、`#ede9fe`、`#6d28d9`、`#475467`、`#111827`、`#eef5ff`、`#fef9c3`/`#92400e`、`#dcfce7`/`#15803d`、`#fee2e2`/`#991b1b`、`#e0f2fe`/`#0369a1`

**特别问题**: `btn-plan-composite` 使用紫色主题与全局蓝色 accent 不一致; 分页器完全自定义且样式简陋

---

### 4. TopicsReview.vue

| 维度 | 评估 | 说明 |
|------|------|------|
| 视觉一致性 | 不足 | badge/m-seedling/m-proposed/m-mapped 颜色各自定义，紫色按钮同样脱节 |
| 组件复用 | 无 | 完全自包含 |
| 布局合理性 | 良好 | 双栏(380px+1fr)，右侧详情信息密度高 |
| 交互反馈 | 不足 | 使用原生 alert()/confirm() |
| 响应式 | 缺失 | 无 media query |

**硬编码色值**: `#fff8e1`、`#e6f4ea`、`#7c3aed`、`#6d28d9`、`#ede9fe`、`#e74c3c`(删除按钮)、`#fce4ec`/`#c62828`(tag-unknown)

**特别问题**: 新建主题 modal 和映射标签 modal 是完全手写的，与 MetadataReview/ClassificationReview 的 modal 样式略有差异

---

### 5. InboxReview.vue

| 维度 | 评估 | 说明 |
|------|------|------|
| 视觉一致性 | 良好 | 风格较统一，使用 CSS 变量 |
| 组件复用 | 无 | 完全自包含 |
| 布局合理性 | 良好 | 双栏(420px+1fr)，summary-bar 设计合理 |
| 交互反馈 | 不足 | 使用原生 alert()/confirm() |
| 响应式 | 缺失 | 无 media query |

**硬编码色值**: `#e6f4ea`/`#16833a`(ok)、`#fdecea`/`#bad`(skip)、`#fff8e1`/`#9a6700`(warn/cand)、`#fce4ec`

---

### 6. IntakeReview.vue

| 维度 | 评估 | 说明 |
|------|------|------|
| 视觉一致性 | 不足 | badge.res-* 样式与 MetadataReview/ClassificationReview 的 badge 类似但独立定义 |
| 组件复用 | 无 | 完全自包含 |
| 布局合理性 | 良好 | 双栏(380px+1fr)，review-bar 有批量晋升 |
| 交互反馈 | 不足 | 使用原生 alert()/confirm() |
| 响应式 | 缺失 | 无 media query |

**硬编码色值**: `#e6f4ea`、`#fff8e1`、`#fdecea`、`#fce4ec`

---

### 7. MetadataReview.vue

| 维度 | 评估 | 说明 |
|------|------|------|
| 视觉一致性 | 混合 | 大量自定义 badge/risk-badge/conf-badge/model-badge，但使用 Naive UI 的 n-select/n-pagination |
| 组件复用 | 部分 | 使用 PdfPreviewDrawer、ResizeHandle、usePagination |
| 布局合理性 | 良好 | 动态双/三栏(list+detail+pdf drawer)，ResizeHandle 可拖拽 |
| 交互反馈 | 良好 | 使用 Naive UI 的 message/dialog，有防抖搜索 |
| 响应式 | 不足 | 仅有 `@media (max-width: 1180px)` 处理 PDF drawer 布局 |

**硬编码色值**: `#fef2f2`/`#fecaca`/`#7f1d1d`(risk reasons)、`#ede9fe`/`#6d28d9`(mimo)、`#e0f2fe`/`#0369a1`(ollama)、`#fed7aa`/`#9a3412`(needs_fix)、`#e5e7eb`/`#374151`(quarantined)、`#6b7280`/`#4b5563`(quarantine btn)、`#fef08a`(highlight)

**特别问题**:
- 审核栏(review-bar)有 4 个按钮: approve/fix/reject/quarantine，样式各自定义
- 隔离 modal 完全自定义，与 ClassificationReview 的隔离 modal 几乎相同但样式略有差异
- 字段对比表(field-table)的四列布局是页面特有的

---

### 8. ClassificationReview.vue

| 维度 | 评估 | 说明 |
|------|------|------|
| 视觉一致性 | 混合 | 与 MetadataReview 结构高度相似，但 badge/amb-badge/conf-badge 样式独立定义 |
| 组件复用 | 部分 | 使用 PdfPreviewDrawer、ResizeHandle、usePagination、labels.js |
| 布局合理性 | 良好 | 与 MetadataReview 相同的动态布局 |
| 交互反馈 | 良好 | 使用 Naive UI message |
| 响应式 | 缺失 | 无 media query |

**硬编码色值**: `#fee2e2`/`#991b1b`(amb high)、`#fef3c7`/`#92400e`(amb medium)、`#dcfce7`/`#166534`(amb low)、`#ede9fe`/`#6d28d9`(mimo)、`#e0f2fe`/`#0369a1`(ollama)、`#dc2626`(P0)、`#ea580c`(P1)、`#2563eb`(P2)、`#6b7280`(P3)、`#9ca3af`(archive)

**特别问题**:
- 与 MetadataReview 共享大量结构模式(列表+详情+审核栏+隔离 modal)，但代码完全独立，无组件提取
- `QUARANTINE_REASONS` 常量在两个页面各定义了一遍，内容相同
- 审核栏按钮样式(btn-approve/btn-fix/btn-reject/btn-quarantine/btn-save-draft)在两个页面各定义一遍

---

## 二、跨页面问题汇总

### 2.1 重复代码统计

| 重复模式 | 出现页面数 | 说明 |
|----------|-----------|------|
| `.badge` 样式定义 | 6 | 每页独立定义颜色映射 |
| `.muted` / `.tiny` 工具类 | 8 | 每页重复定义 |
| `table.kv` 键值表 | 4 | Discovery/Topics/Inbox/Intake 各自定义 |
| `review-bar` 审核栏 | 4 | Metadata/Classification/Discovery/Intake 各自定义 |
| `modal-overlay` / `modal-box` | 4 | Topics/Metadata/Classification/Works(不同实现) |
| `empty-state` 占位 | 7 | 几乎每页都有一句 "从左侧选择..." |
| `QUARANTINE_REASONS` 常量 | 2 | Metadata/Classification 各定义一次(内容相同) |
| pagination 手写实现 | 2 | Discovery/Intake 手写分页; Metadata/Classification 用 n-pagination |

### 2.2 硬编码色值清单

以下色值在 scoped CSS 中反复出现但未抽象为 CSS 变量:

| 色值 | 用途 | 出现页数 |
|------|------|---------|
| `#eef5ff` | 选中/active 背景 | 7 |
| `#fef9c3` / `#92400e` | pending/warning 状态 | 5 |
| `#dcfce7` / `#15803d` | approved/success 状态 | 5 |
| `#fee2e2` / `#991b1b` | rejected/error 状态 | 5 |
| `#e6f4ea` / `#16833a` | ok/green 状态 | 4 |
| `#ede9fe` / `#6d28d9` / `#7c3aed` | 紫色(Mimo/discovery) | 3 |
| `#e0f2fe` / `#0369a1` | 蓝色(Ollama/running) | 3 |
| `#fdecea` | 红色浅底 | 3 |
| `#fff8e1` | 黄色浅底 | 3 |
| `#475467` | section-title 色 | 4 |
| `#374151` / `#3a4250` | 深灰文字 | 5 |
| `#6b7280` / `#9ca3af` | 灰色文字 | 5 |
| `#f1f4f8` | 表头/统计卡片背景 | 3 |

### 2.3 交互反馈不一致

| 页面 | 成功反馈 | 失败反馈 | 确认操作 |
|------|---------|---------|---------|
| Dashboard | 无 | 无 | 无 |
| Works | `message.success()` (Naive UI) | `message.error()` | `dialog.warning()` (Naive UI) |
| Discovery | `alert()` | `alert()` | 无确认 |
| Topics | `alert()` | `alert()` | `confirm()` |
| Inbox | `alert()` | `alert()` | `confirm()` |
| Intake | `alert()` | `alert()` | `confirm()` |
| Metadata | `message.success()` | `message.warning()` | `dialog.warning()` |
| Classification | `message.success()` | `message.error()` | 无(直接操作) |

---

## 三、设计令牌草案

### 3.1 现有令牌(保留)

```css
:root {
  --bg: #f7f8fa;
  --panel: #ffffff;
  --line: #d9dee7;
  --text: #20242c;
  --muted: #667085;
  --accent: #1f6feb;
  --ok: #16833a;
  --warn: #9a6700;
  --bad: #c32f27;
  --chip: #eef2f7;
}
```

### 3.2 圆角阶梯

```css
:root {
  --radius-xs: 2px;        /* 微型元素: tag 删除按钮 */
  --radius-sm: 4px;        /* 小按钮、输入框、badge */
  --radius-md: 6px;        /* 卡片、列表项、panel */
  --radius-lg: 8px;        /* modal、详情面板 */
  --radius-xl: 10px;       /* 大 modal */
  --radius-full: 999px;    /* 药丸/圆形 badge */
}
```

### 3.3 阴影阶梯

```css
:root {
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.06);           /* 卡片微阴影 */
  --shadow-md: 0 2px 8px rgba(0,0,0,0.08);           /* 浮层/下拉 */
  --shadow-lg: 0 8px 32px rgba(0,0,0,0.18);          /* modal */
  --shadow-focus: 0 0 0 2px rgba(31,111,235,0.25);   /* focus ring */
}
```

### 3.4 间距阶梯

```css
:root {
  --space-1: 4px;
  --space-2: 6px;
  --space-3: 8px;
  --space-4: 12px;
  --space-5: 16px;
  --space-6: 20px;
  --space-7: 24px;
  --space-8: 32px;
}
```

### 3.5 状态色变体

```css
:root {
  /* 成功/通过 */
  --ok-bg: #dcfce7;
  --ok-fg: #15803d;
  --ok-border: #16833a;

  /* 警告/待审 */
  --warn-bg: #fef9c3;
  --warn-fg: #92400e;
  --warn-border: #9a6700;

  /* 错误/拒绝 */
  --bad-bg: #fee2e2;
  --bad-fg: #991b1b;
  --bad-border: #c32f27;

  /* 信息/进行中 */
  --info-bg: #e0f2fe;
  --info-fg: #0369a1;
  --info-border: #0284c7;

  /* 中性/已归档 */
  --neutral-bg: #e5e7eb;
  --neutral-fg: #374151;
  --neutral-border: #9ca3af;

  /* 选中态 */
  --selected-bg: #eef5ff;
  --selected-border: var(--accent);

  /* 需修正 */
  --fix-bg: #fed7aa;
  --fix-fg: #9a3412;

  /* 紫色(Mimo / Discovery) */
  --purple-bg: #ede9fe;
  --purple-fg: #6d28d9;
  --purple-border: #7c3aed;
}
```

### 3.6 字体/排版

```css
:root {
  --font-sans: "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
  --font-mono: ui-monospace, Consolas, "Courier New", monospace;

  --text-xs: 11px;
  --text-sm: 12px;
  --text-base: 13px;
  --text-md: 14px;
  --text-lg: 16px;
  --text-xl: 18px;
  --text-2xl: 22px;

  --line-height-tight: 1.3;
  --line-height-normal: 1.5;
  --line-height-relaxed: 1.6;
}
```

### 3.7 过渡/动画

```css
:root {
  --transition-fast: 0.1s ease;
  --transition-normal: 0.15s ease;
  --transition-slow: 0.2s ease;
}
```

---

## 四、公共组件候选清单

### 4.1 StatusBadge (状态徽章)

**来源页**: 全部页面
**当前状态**: 每页独立定义 `.badge.pending`/`.badge.approved` 等，颜色逻辑重复
**职责**: 根据 status 类型自动映射背景色/文字色，支持 `size="small|default|large"` 和 `variant="dot|filled|outlined"`

**合并建议**:
- 统一颜色映射使用设计令牌 (`--ok-bg/--ok-fg`, `--warn-bg/--warn-fg` 等)
- 支持的 status 类型: pending / approved / rejected / needs_fix / quarantined / succeeded / failed / running / planned

### 4.2 ConfidenceBadge (置信度徽章)

**来源页**: MetadataReview, ClassificationReview, DiscoveryReview
**当前状态**: 三个页面各自定义 `.conf-badge.high/.medium/.low`
**职责**: 显示置信度等级(high/medium/low)，支持分数模式和文字模式

### 4.3 TagChip (标签芯片)

**来源页**: TopicsReview (`.tag-chip`), MetadataReview (`.author-tag`), ClassificationReview (`.chip`)
**当前状态**: 各页面独立定义
**职责**: 显示单个标签值，支持 `group=value` 格式、未知标签警告、删除按钮

### 4.4 ConfirmDialog (确认对话框)

**来源页**: MetadataReview/ClassificationReview (自定义 modal), Works (n-modal), TopicsReview/InboxReview/IntakeReview (原生 confirm/alert)
**当前状态**: 三种实现方式混用
**职责**: 统一确认/取消对话框，支持标题、描述、原因输入、radio 选项列表、loading 态
**特别说明**: MetadataReview 和 ClassificationReview 的隔离 modal 内容几乎相同，`QUARANTINE_REASONS` 常量应提取

### 4.5 EmptyState (空状态)

**来源页**: 全部页面
**当前状态**: 每页用 `<div class="muted">从左侧选择...查看详情</div>` 或类似文案
**职责**: 统一空状态展示，支持 icon slot、标题、描述、操作按钮

### 4.6 LoadingSpinner (加载指示器)

**来源页**: MetadataReview ("加载中..."), PdfPreviewDrawer ("Loading PDF..."), 其他页面隐式(busy 指钮 disabled)
**当前状态**: 无统一 loading 组件，分散在各处
**职责**: 全屏加载、内联加载、按钮 loading 态

### 4.7 ReviewBar (审核操作栏)

**来源页**: MetadataReview, ClassificationReview, DiscoveryReview, IntakeReview
**当前状态**: 四个页面各自实现，结构相似但按钮组合不同
**职责**: 固定在详情面板底部的操作栏，包含备注输入 + 操作按钮组
**按钮组合变体**:
- MetadataReview: 备注 + 批准/需修正/拒绝/隔离
- ClassificationReview: 备注 + 保存草稿/批准/需修正/拒绝/隔离
- DiscoveryReview: 备注 + 接受/拒绝
- IntakeReview: 批准/拒绝/晋升(无备注)

### 4.8 PaginationNav (分页导航)

**来源页**: DiscoveryReview (手写), IntakeReview (手写), MetadataReview (n-pagination), ClassificationReview (n-pagination), Works (n-pagination)
**当前状态**: 手写 vs Naive UI 混用
**职责**: 统一分页组件，支持 page/total 显示、上一页/下一页

### 4.9 KeyValueTable (键值表)

**来源页**: DiscoveryReview (`table.kv`), TopicsReview (`table.kv`), InboxReview (`table.kv`), IntakeReview (`table.kv`)
**当前状态**: 四个页面各自定义 `table.kv` 样式
**职责**: 左列标签(灰色)+右列值的标准键值展示表

### 4.10 Modal (模态框)

**来源页**: TopicsReview (创建/映射 modal), MetadataReview (隔离 modal), ClassificationReview (隔离 modal), Works (n-modal)
**当前状态**: 自定义 modal vs Naive UI modal 混用
**职责**: 统一 modal 容器，支持标题、描述、内容 slot、操作按钮、loading 态

### 4.11 SectionToggle (折叠区块)

**来源页**: MetadataReview ("证据片段 [-]/[+]", "Extracted JSON [-]/[+]", "原文预览 [-]/[+]"), ClassificationReview ("证据片段 [-]/[+]"), DiscoveryReview ("原始元数据 [-]/[+]"), TopicsReview ("最近发现检索 [-]/[+]")
**当前状态**: 各页面独立实现，样式一致但代码重复
**职责**: 可折叠的内容区块，标题带 [-]/[+] 指示器

### 4.12 StatCard (统计卡片)

**来源页**: Dashboard, MetadataReview (`.stats-bar > .stat-card`), ClassificationReview (同)
**当前状态**: Dashboard 和审核页面各自定义
**职责**: 数字 + 标签的统计展示卡片，支持 active/点击态

---

## 五、双面板布局线框图

### 5.1 整体架构

```
+------------------------------------------------------------------+
|  顶部全局导航栏 (Logo + 用户信息)                                   |
+------------------------------------------------------------------+
| 左侧流程面板    |              右侧内容面板                         |
| (240-280px)    |                                                  |
|                 |  +--------------------------------------------+ |
|  [折叠/展开]    |  |  顶部 Tab 栏                                 | |
|                 |  |  [总览] [文献] [主题闸门] [发现] [收件箱] ... | |
|  流程导航:      |  +--------------------------------------------+ |
|  > 总览        |  |                                              | |
|  > 文献        |  |           当前 Tab 内容区                      | |
|                |  |                                              | |
|  流程:          |  |  (各页面的主内容)                              | |
|  > 主题闸门    |  |                                              | |
|  > 发现检索    |  |                                              | |
|  > 收件箱      |  |                                              | |
|  > 采集审核    |  |                                              | |
|  > 分类审核    |  |                                              | |
|  > 元数据      |  |                                              | |
|                |  +--------------------------------------------+ |
|  库内:          |                                                  |
|  > 去重        |                                                  |
|  > 关系        |                                                  |
|                 |                                                  |
+------------------------------------------------------------------+
```

### 5.2 左侧流程面板(折叠态)

```
+------+
|  文  |
| 献库 |
+------+
|  📊  |  <-- 总览
|  📚  |  <-- 文献
|------|
|  流程 |
|------|
|  🗂️  |  <-- 主题闸门
|  🔎  |  <-- 发现检索
|  📂  |  <-- 收件箱
|  📥  |  <-- 采集审核
|  📋  |  <-- 分类审核
|  🏷️  |  <-- 元数据
|------|
|  库内 |
|------|
|  🔍  |  <-- 去重
|  🔗  |  <-- 关系
+------+
```

### 5.3 双面板布局线框(展开态，以元数据审核为例)

```
+------------------------------------------------------------------+
|  文献库                                    [折叠侧栏 «]            |
+------------------------------------------------------------------+
|  流程导航        |  [总览] [文献] [主题] [发现] [收件箱] [采集] [元数据*] [分类] |
|                  |------------------------------------------------|
|  > 发现检索      |                                                |
|  > 收件箱        |  元数据审核                                     |
|  > 采集审核      |                                                |
|  > 分类审核      |  +----------+  +------------------------------+ |
|  > 元数据 [active]|  | 列表面板  |  | 详情面板                      | |
|                  |  |          |  |                              | |
|  库内            |  | 筛选器    |  |  标题                        | |
|  > 去重          |  | [待审 12] |  |  ID · 模型 · 时间            | |
|  > 关系          |  | [已批  5] |  |                              | |
|                  |  | [需修  3] |  |  [原文预览] [PDF侧栏]        | |
|                  |  | [已拒  1] |  |  [证据片段]                   | |
|                  |  |          |  |                              | |
|                  |  | 搜索框    |  |  字段对比表                   | |
|                  |  |          |  |                              | |
|                  |  | 排序      |  |  审核栏                      | |
|                  |  |          |  |  [备注...] [批准][修正][拒绝]  | |
|                  |  | [列表项]  |  |                              | |
|                  |  | [列表项]  |  +------------------------------+ |
|                  |  | [列表项]  |                                   |
|                  |  | ...       |                                   |
|                  |  | [分页]    |                                   |
|                  |  +----------+                                    |
+------------------------------------------------------------------+
```

### 5.4 三面板布局(PDF 打开时)

```
+------------------------------------------------------------------+
| 流程导航 | 列表面板 (可拖拽) | 详情面板 (可拖拽) | PDF 侧栏        |
| 240px   | 260-400px       | flex              | 420px / 42vw    |
|         |                  |                    |                  |
|         | [列表项...]      | [内容]             | [PDF 渲染]       |
|         | [列表项...]      |                    | [Prev] [Next]   |
|         | [分页]          |                    | [缩放控制]       |
+------------------------------------------------------------------+
```

### 5.5 响应式策略

```
桌面 (>1200px):   左侧栏(280px) + 内容面板
平板 (768-1200px): 左侧栏折叠为图标(60px) + 内容面板
手机 (<768px):     左侧栏隐藏 + 顶部 Tab 切换
```

---

## 六、优先级排序的落地建议

### P0 - 高优先级(影响全局一致性)

1. **补全 CSS 变量(设计令牌)**
   - 在 `AppLayout.vue` 的 `:root` 中添加 3.2-3.7 节定义的全部令牌
   - 工作量小、风险零，可立即执行
   - 为后续所有组件重构奠定基础

2. **提取 StatusBadge 公共组件**
   - 6 个页面重复定义 badge 样式
   - 统一颜色映射到设计令牌
   - 消除约 80 行重复 CSS

3. **提取 ConfirmDialog 公共组件**
   - 统一 alert()/confirm()/自定义 modal 为单一组件
   - MetadataReview 和 ClassificationReview 的隔离 modal 完全相同，应合并
   - `QUARANTINE_REASONS` 常量提取到共享位置

### P1 - 中优先级(消除重复代码)

4. **提取 ReviewBar 公共组件**
   - 4 个审核页面的底部操作栏结构高度相似
   - 支持 slot 配置不同按钮组合
   - 消除约 120 行重复 CSS + 模板

5. **提取 EmptyState 公共组件**
   - 7 个页面使用几乎相同的空状态文案和样式
   - 统一为一个带 icon/title/description 的组件

6. **提取 KeyValueTable 公共组件**
   - 4 个页面使用 `table.kv` 模式
   - 统一样式定义

7. **提取 SectionToggle 公共组件**
   - 4 个页面使用 [-]/[+] 折叠模式
   - 统一交互和样式

### P2 - 低优先级(布局优化)

8. **统一 Modal 实现**
   - 将 TopicsReview 的创建/映射 modal 和 MetadataReview/ClassificationReview 的隔离 modal 统一
   - 考虑使用 Naive UI 的 n-modal 替代全部自定义 modal

9. **统一 PaginationNav**
   - 消除 DiscoveryReview/IntakeReview 的手写分页
   - 全部使用 n-pagination 或统一自定义组件

10. **双面板布局标准化**
    - 将 MetadataReview/ClassificationReview 的动态 grid 布局模式提取为可复用的 Layout 组件
    - 左侧列表宽度、折叠逻辑、ResizeHandle 交互统一

11. **统一交互反馈**
    - 全部替换 alert()/confirm() 为 Naive UI 的 message/dialog
    - 统一成功/失败/确认的反馈模式

### P3 - 远期(架构优化)

12. **标签数据集中管理**
    - `READING_LANE_LABELS` 等大量标签映射在 `labels.js` 中已集中，但 Works.vue 中仍有独立的 OPTIONS 数组
    - 可从 labels.js 自动生成 OPTIONS 配置

13. **响应式补全**
    - TopicsReview、InboxReview、IntakeReview、ClassificationReview 缺失响应式支持
    - 统一断点策略: >1200px / 768-1200px / <768px

14. **PdfPreviewDrawer 国际化**
    - 当前按钮文案为英文(Prev/Next/Open/Close/Loading PDF...)
    - 应统一为中文

---

## 七、实施路径建议

```
Phase 1 (令牌基础):
  AppLayout.vue 添加 CSS 变量 → 0 业务影响

Phase 2 (核心组件):
  StatusBadge → ConfirmDialog → ReviewBar → EmptyState
  逐个提取，逐页替换，每步可独立测试

Phase 3 (布局统一):
  KeyValueTable → SectionToggle → Modal → PaginationNav
  消除剩余重复代码

Phase 4 (体验优化):
  统一交互反馈 → 响应式补全 → PdfPreviewDrawer 国际化
```

---

## 八、审计文件清单

| 文件 | 行数 | 需重构项 |
|------|------|---------|
| `App.vue` | 27 | 添加设计令牌(非重构) |
| `AppLayout.vue` | 194 | 补全 CSS 变量 |
| `Dashboard.vue` | 98 | 补充加载/错误态 |
| `Works.vue` | 517 | OPTIONS 可从 labels.js 生成 |
| `DiscoveryReview.vue` | 702 | badge/pagination/review-bar 抽取 |
| `TopicsReview.vue` | 683 | badge/modal 抽取，添加响应式 |
| `InboxReview.vue` | 187 | 添加响应式，badge 统一 |
| `IntakeReview.vue` | 236 | badge/pagination 抽取，添加响应式 |
| `MetadataReview.vue` | 846 | 最复杂页面，badge/modal/review-bar 抽取 |
| `ClassificationReview.vue` | 964 | 与 MetadataReview 高度重复，需大量合并 |
| `PdfPreviewDrawer.vue` | 199 | 国际化 |
| `ResizeHandle.vue` | 85 | 已是公共组件，无需修改 |

---

**本任务零代码变更。** 以上全部为审计发现与设计提案，不涉及任何 .vue / .js / .css 业务文件的修改。
