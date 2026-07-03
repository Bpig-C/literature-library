# 前端全面重构计划 v2.0（总控审核修订版）

> **设计方向**：学术/专业 — 干净、克制、高信息密度，类似 Notion/Obsidian 的研究工具感
>
> **日期**：2026-07-01（v1 由本地模型起草，v2 由总控模型审核修订）
>
> **范围**：视觉全量重构 + 流程管理页面（新功能）
>
> **核心策略**：**全量替换** — :root CSS 变量体系、所有页面硬编码色值、布局骨架全部按新规范重写。不保留旧变量。
>
> **色系统一决策**：废弃独立 purple 色系，DiscoveryReview 等紫色系页面统一映射到蓝色 `--accent` 系列。全局仅一个主色调。

---

## 设计原则

1. **信息密度优先**：学术工具需要展示大量信息，不浪费空间
2. **视觉层次清晰**：通过字体、颜色、间距建立清晰的信息层次
3. **克制的装饰**：圆角/阴影/动画保持最小必要量，不过度设计
4. **一致性**：所有页面使用相同的设计语言和组件
5. **全量替换**：本次是视觉重写不是修补，已有 CSS 变量和硬编码色值全部更新为新规范

---

## 设计规范（最终版）

### 色彩系统

```css
:root {
  /* === 主色调 — 全局唯一主色（替代原有的 accent + purple 双色体系） === */
  --accent: #2563eb;           /* 主按钮/链接/激活状态 */
  --accent-hover: #1d4ed8;     /* 悬停态 */
  --accent-subtle: #eff6ff;    /* 浅背景（选中行/激活标签） */
  --accent-mute: #93c5fd;      /* 弱化强调（边框/分割线） */

  /* === 中性色 === */
  --text-primary: #111827;     /* 正文 */
  --text-secondary: #4b5563;   /* 辅助文字 */
  --text-tertiary: #9ca3af;    /* 占位符/禁用 */
  --border: #e5e7eb;           /* 分割线 */
  --border-strong: #d1d5db;    /* 强分割线（卡片边界） */
  --bg-page: #f9fafb;          /* 页面底色 */
  --bg-surface: #ffffff;       /* 卡片/面板 */
  --bg-muted: #f3f4f6;         /* 次级背景（侧栏/表头hover） */

  /* === 状态色（三元组：本色 / 背景色 / 前景色）=== */
  --ok: #16a34a;
  --ok-bg: #dcfce7;
  --ok-fg: #15803d;

  --warn: #d97706;
  --warn-bg: #fef9c3;
  --warn-fg: #92400e;

  --bad: #dc2626;
  --bad-bg: #fee2e2;
  --bad-fg: #991b1b;

  --info: #2563eb;             /* info 复用 accent 蓝 */
  --info-bg: #dbeafe;
  --info-fg: #0369a1;

  --neutral: #6b7280;
  --neutral-bg: #f3f4f6;
  --neutral-fg: #374151;

  --selected-bg: #eff6ff;      /* 选中/高亮 → 用 accent-subtle */
  --selected-border: #2563eb;

  --fix: #d97706;              /* fix/修复 状态复用 warn */
  --fix-bg: #fef3c7;
  --fix-fg: #92400e;

  /* 注意：原 purple 色系已删除。DiscoveryReview 的紫色 UI 元素统一改用 --accent 系列。
     STATUS_COLOR_MAP 中的 'unknown'/'discovery' 映射从 purple 改为 accent 色。*/
}
```

### 字体系统

```css
:root {
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", sans-serif;
  --font-mono: "SF Mono", "Cascadia Code", "Consolas", monospace;

  --text-xs: 11px;
  --text-sm: 12px;
  --text-base: 13px;
  --text-md: 14px;
  --text-lg: 16px;
  --text-xl: 18px;
  --text-2xl: 20px;

  --line-height-tight: 1.3;
  --line-height-normal: 1.5;
  --line-height-relaxed: 1.6;
}
```

### 间距系统（4px 基准）

```css
:root {
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-8: 32px;
  --space-10: 40px;
}
```

### 圆角系统（更克制 — 替代原有 xs/sm/md/lg/xl/full 六级）

```css
:root {
  --radius-sm: 3px;           /* 小元素：tag/badge/input */
  --radius-md: 4px;           /* 卡片/面板/按钮 */
  --radius-lg: 6px;           /* 大卡片/modal */
  --radius-xl: 8px;           /* 容器级 */
}
```

> **与旧值的对应关系（供批量替换参考）**：
> | 旧变量 | 旧值 | 新变量 | 新值 |
> |--------|------|--------|------|
> | `--radius-xs` | 2px | → `--radius-sm` | 3px |
> | `--radius-sm` | 4px | → `--radius-md` | 4px |
> | `--radius-md` | 6px | → `--radius-lg` | 6px |
> | `--radius-lg` | 8px | → `--radius-xl` | 8px |
> | `--radius-xl` | 10px | → `--radius-xl` | 8px（合并）|
> | `--radius-full` | 999px | → `--radius-xl` 或保持 inline | pill 按钮 |

### 阴影系统（保留 — ConfirmDialog/DualPanelLayout/EmptyState 需要用）

```css
:root {
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.06);   /* 微妙提升 */
  --shadow-md: 0 2px 8px rgba(0,0,0,0.08);   /* 卡片/下拉 */
  --shadow-lg: 0 8px 32px rgba(0,0,0,0.18);  /* Modal/弹窗 */
  --shadow-focus: 0 0 0 2px rgba(37,99,235,0.25); /* 焦点环（用 accent 色）*/
}
```

### 过渡动画系统（保留 — 侧边栏 hover 展开/ConfirmDialog 淡入淡出需用）

```css
:root {
  --transition-fast: 0.1s ease;      /* hover/焦点 */
  --transition-normal: 0.15s ease;   /* 展开/收起 */
  --transition-slow: 0.2s ease;      /* Modal 进出 */
}
```

### 布局专用变量

```css
:root {
  /* 侧边栏 */
  --sidebar-collapsed-width: 56px;   /* 图标态默认宽度 */
  --sidebar-expanded-width: 200px;   /* 展开宽度 */
  --sidebar-transition: width 0.2s ease;

  /* 顶部栏 */
  --topbar-height: 48px;

  /* PDF Drawer */
  --pdf-drawer-width-desktop: 420px;
  --pdf-drawer-width-tablet: 340px;
}
```

---

## 布局重构

### 当前问题

- 侧边栏默认 200px 太宽，内容区被压缩
- 页面标题区域混乱，缺少统一的顶部导航栏
- 双面板布局各页面实现不一致
- 缺少全局的面包屑导航

### 新布局设计

```
┌─────────────────────────────────────────────────────────────┐
│  顶部栏 (--topbar-height: 48px)                              │
│  [文献库]  总览 > 文献库 > 元数据审核              [时钟]    │
├────────┬─────────────────────────────────────────────────────┤
│        │                                                     │
│  侧边栏 │                   内容区                             │
│  56px  │                                                     │
│  图标态 │                                                     │
│  hover │                                                     │
│  展开   │                                                     │
│        │                                                     │
│ [📊]   │                                                     │
│ [📚]   │                                                     │
│ [流程] │                                                     │
│ ...    │                                                     │
└────────┴─────────────────────────────────────────────────────┘
```

**改进点**：
1. 侧边栏默认 **56px 图标态**，鼠标 hover 展开到 200px（基于现有 collapsed 逻辑改造触发方式）
2. 新增 **48px 顶部栏**：左侧 Logo + 面包屑导航，右侧可选时钟
3. 内容区获得更多空间（侧边栏从常占 200px → 默认只占 56px）
4. 移动端：侧边栏变为抽屉式 overlay（复用现有 768px 断点逻辑）

---

## 已有资产清单（本轮必须复用的组件和 Composable）

在开始实施前，先确认以下文件已存在且可用：

### 已有 UI 组件（web/src/components/）

| 组件文件 | 当前状态 | 本轮用途 |
|----------|---------|---------|
| `StatusBadge.vue` | ✅ 已建，3页面/12处引用 | Phase 2/4/5 所有状态标签 |
| `EmptyState.vue` | ✅ 已建，3页面/5处引用 | Phase 2/2.5/3/4/5 所有空状态 |
| `ConfirmDialog.vue` | ✅ 已建，3页面/4处引用 | **Phase 2.5 批量操作必须使用此组件** |
| `SearchHeader.vue` | ✅ 已建，待集成 | Phase 3 Works 筛选器 |
| `ReviewBar.vue` | ✅ 已建，待集成 | Phase 4 审核页面的操作栏 |
| `DualPanelLayout.vue` | ✅ 已建，MetadataReview 在用 | Phase 1 侧边栏联动 + Phase 4 全部审核页 |

### 已有 Composable（web/src/composables/）

| Composable | 当前状态 | 本轮用途 |
|------------|---------|---------|
| `useQuarantine.js` | ✅ 已建，4页面接入 | Phase 2.5/4 审核页隔离操作 |
| `useFormatUtils.js` | ✅ 已建，6页面接入 | 全局通用 |
| `useDualPanel.js` | ✅ 已建 | Phase 4 双面板页 |
| `usePdfDrawer.js` | ✅ 已建，3页面接入 | WorkDetail/MetadataReview/ClassificationReview |
| `useAsyncOperation.js` | ✅ 已建 | Phase 2.5 异步批量操作 |
| `constants/options.js` | ✅ 已建 | StatusBadge 的 STATUS_COLOR_MAP 需更新 |

### 关键修改点：STATUS_COLOR_MAP 更新

`constants/options.js` 中的 `STATUS_COLOR_MAP` 需要同步更新：

```js
// 旧的 purple 映射 → 改为 accent
// 旧: discovery/discovered/running → purple 系列
// 新: discovery/discovered/running → accent (#2563eb) 系列
// unknown → neutral（不变）
// 其他 status 保持 ok/warn/bad 映射不变
```

---

## 实施阶段

### Phase 1: 全局布局 + 设计规范全量落地（5-7h）🔴 核心

**目标**：建立新的布局骨架，全量替换 CSS 变量体系

#### 任务清单

| # | 任务 | 详细要求 | 涉及文件 | 复用资产 |
|---|------|---------|---------|---------|
| 1.1 | 重写 `:root` CSS 变量 | 按「设计规范」章节完整替换 AppLayout.vue 中的 `:root` 块。删除所有旧变量名（`--bg/--panel/--line/--muted/--chip/--radius-xs/--radius-full` 等），统一用新规范命名 | `AppLayout.vue` | — |
| 1.2 | 同步更新 6 个已有组件的样式 | 将以下组件中的旧变量引用替换为新变量名和新值：<br/>• `StatusBadge.vue`: 圆角 `--radius-*` → 新值<br/>• `EmptyState.vue`: 间距/字体/圆角<br/>• `ConfirmDialog.vue`: 圆角/阴影/过渡/颜色<br/>• `SearchHeader.vue`: 同上<br/>• `ReviewBar.vue`: 同上<br/>• `DualPanelLayout.vue`: 侧边栏变量/ResizeHandle | 6 个 .vue 组件 | — |
| 1.3 | 更新 STATUS_COLOR_MAP | `constants/options.js` 中将 `discovery`/`running` 等 purple 映射改为 `--accent` 蓝色系 | `options.js` | — |
| 1.4 | 视图硬编码色值批量替换 | 逐文件替换以下视图中的 hex 色值为新 CSS 变量：<br/>• `TopicsReview.vue`: 绿色系 `#18a058/#e8f5e9/#f0f9eb/#d4edda/#c3e6cb`<br/>• `InboxReview.vue`: 蓝色系 `#2080f0/#e8f3ff`<br/>• `IntakeReview.vue`: 绿色系同 TopicsReview<br/>• `MetadataReview.vue`: 浅蓝 `#e8f3ff/#f0f9ff`<br/>• `ClassificationReview.vue`: 绿色系<br/>• `WorkDetail.vue`: 浅蓝 `#e8f3ff/#eef5ff`<br/>• `DiscoveryReview.vue`: 紫色系 `var(--purple-*)` → `var(--accent-*)` | 7 个 .vue 视图 | StatusBadge |
| 1.5 | 侧边栏改为图标态(hover展开) | • 默认宽度改为 `56px`(grid-template-columns: 56px 1fr)<br/>• mouseenter → 展开到 200px，mouseleave → 收回 56px<br/>• 折叠状态下显示 tooltip（title 属性或 NTooltip）<br/>• 删除旧的 collapse 按钮（不再需要 click 切换）<br/>• nav-group 标题在折叠时隐藏 | `AppLayout.vue` | DualPanelLayout(联动) |
| 1.6 | 新增顶部栏 | • 在 layout 顶层新增 48px 高的 header 区域<br/>• 左侧：Logo "文献库" + 面包屑（读取 router.currentRoute.meta.title 链）<br/>• 右侧：可选时钟（可后续加）<br/>• 底部 border 使用 `--border` | `AppLayout.vue` | — |
| 1.7 | 响应式适配确认 | • ≤768px: 侧边栏隐藏，顶部栏出现汉堡菜单按钮<br/>• 点击汉堡菜单弹出抽屉式侧栏（OverlayDrawer 或自定义）<br/>• 确认现有 `@media (max-width: 768px)` 逻辑兼容新布局 | `AppLayout.vue` | — |
| 1.8 | 回归验证 | • 11 个页面逐页打开检查无样式崩坏<br/>• 重点验证：StatusBadge 颜色正确、ConfirmDialog 弹窗正常、双面板不变形<br/>• `npm run build` 通过 | 全部 | — |

#### 验收 checklist（PASS 标准）

- [ ] `grep -rn 'var(--purple' web/src/` 结果为零（purple 引用全部清除）
- [ ] `grep -rn 'var(--radius-xs\|--radius-full' web/src/` 结果为零（旧圆角变量清除）
- [ ] `grep -rn '#[0-9a-fA-F]{3,8}\b' web/src/views/` 结果 ≤ 5（仅 Naive UI 组件 props 允许残留）
- [ ] `npm run build` 成功，零错误
- [ ] 11 个页面目测无布局崩坏
- [ ] 侧边栏默认 56px，hover 展开 200px，tooltip 正常
- [ ] 顶部栏 48px 显示当前页面标题
- [ ] DiscoveryReview 不再显示紫色，改为蓝色 accent

---

### Phase 2: Dashboard 重构（1.5-2h）

**目标**：从导航入口升级为治理控制台

| 任务 | 说明 | 复用资产 |
|------|------|---------|
| 统计卡片 | 显示各阶段待处理数量（收件箱/解析中/元数据待审/分类待审），调用 API 获取真实数据 | EmptyState（某阶段为空时）、StatusBadge（状态指示） |
| 快捷操作 | 一键跳转到各审核页面（router-link） | — |
| 待办队列 | 显示最近需要处理的事项（可选，时间不够可简化） | EmptyState |

#### 验收 checklist

- [ ] Dashboard 显示 4+ 个统计卡片，数字来自 API（非硬编码）
- [ ] 点击快捷入口能跳转到正确的审核页面
- [ ] 无数据时显示 EmptyState 组件
- [ ] `npm run build` 通过

---

### Phase 2.5: 流程管理页面（新功能）⭐（3-4h）🔴 核心

**目标**：解决"只能一篇一篇触发"的效率问题——一键批量推进整个流水线

**路由**：`/pipeline`（新增，需在 router.js 添加）

**页面结构**：

```
┌─────────────────────────────────────────────────────────────┐
│  流程管理                                                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  📂 收件箱摄入                                         │   │
│  │  待摄入: 12 篇                          [▶ 全部摄入]   │   │
│  └──────────────────────────────────────────────────────┘   │
│                          ↓                                   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  📄 文档解析                                           │   │
│  │  待解析: 8 篇    解析中: 2 篇         [▶ 全部解析]    │   │
│  └──────────────────────────────────────────────────────┘   │
│                          ↓                                   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  🏷️ 元数据抽取                                         │   │
│  │  待抽取: 5 篇                          [▶ 全部抽取]   │   │
│  │                                     [去审核 →]        │   │
│  └──────────────────────────────────────────────────────┘   │
│                          ↓                                   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  📋 分类抽取                                           │   │
│  │  待抽取: 3 篇                          [▶ 全部抽取]   │   │
│  │                                     [去审核 →]        │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**功能清单与 API 对应**：

| 功能 | API（已存在于 api.js） | 说明 |
|------|----------------------|------|
| 读取收件箱待处理数 | `getIngestPlan()` → `GET /api/ingest/plan` | 取 `summary.ingests` |
| 批量摄入 | `executeIngest(body)` → `POST /api/ingest/execute` | ⚠️ **必须走 ConfirmDialog 二次确认** |
| 读取解析待处理数 | `getParseStatus()` → `GET /api/parse/status` | 取 pending count |
| 批量解析 | `parseTrigger({all_pending:true})` → `POST /api/parse/trigger` | ⚠️ **ConfirmDialog** |
| 读取元数据待处理数 | `getMetadata(q)` → `GET /api/metadata?status=pending` | 前端过滤 pending |
| 批量元数据抽取 | `extractMetadata({all_pending:true})` → `POST /api/metadata/extract` | ⚠️ **ConfirmDialog** |
| 读取分类待处理数 | `getClassificationExtractions(q)` → `GET /api/classification/extractions?status=pending` | 前端过滤 pending |
| 批量分类抽取 | `classifyExtract({all_pending:true})` → `POST /api/classification/extract` | ⚠️ **ConfirmDialog** |

**⚠️ 关键约束：所有「全部XX」按钮点击后必须调用 ConfirmDialog 组件做二次确认，禁止直接执行或使用 window.confirm/原生 dialog。**

确认弹窗文案示例：
```
标题: "批量摄入"
消息: "即将摄入 _inbox/ 中的 12 个 PDF 文件，确定继续？"
类型: "info"
确认动作: executeIngest()
```

**状态管理模式**：

```js
// PipelineView.vue
import { ref, onMounted } from 'vue'
import { getIngestPlan, executeIngest } from '../api'
import { useAsyncOperation } from '../composables/useAsyncOperation'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import EmptyState from '../components/EmptyState.vue'

// 各阶段状态
const stages = ref({
  ingest:   { count: 0, loading: false },
  parse:    { count: 0, loading: false, running: 0 },
  metadata: { count: 0, loading: false },
  classify: { count: 0, loading: false }
})

// ConfirmDialog 共享状态
const confirm = ref({ show: false, title: '', message: '', action: null })
function showConfirm(title, message, action) {
  confirm.value = { show: true, title, message, action }
}

// 加载数据
async function loadAll() { /* 并发调用 4 个 status API */ }
onMounted(loadAll)

// 批量操作模板（每个阶段共用）
async function batchAction(stageName, apiFn, label) {
  const count = stages.value[stageName].count
  if (!count) return
  showConfirm(`批量${label}`, `即将${label} ${count} 个项目，确定？`, async () => {
    confirm.value.show = false
    stages.value[stageName].loading = true
    try { await apiFn({ all_pending: true }); await loadAll() }
    finally { stages.value[stageName].loading = false }
  })
}
```

**侧边栏新增入口**：

```
流程组:
├── 流程管理  ← 新增（排在最前，作为流程链的总览）
├── 主题闸门
├── 发现检索
├── 收件箱摄入
├── 采集审核
├── 分类审核
└── 元数据审核
```

**新建文件**：
- `web/src/views/PipelineView.vue`（流程管理页主体）

**修改文件**：
- `web/src/router.js`（添加 `/pipeline` 路由）
- `web/src/components/AppLayout.vue`（侧边栏添加「流程管理」入口）

#### 验收 checklist

- [ ] 页面加载后显示 4 个阶段的实时待处理数量
- [ ] 每个「全部XX」按钮点击后弹出 ConfirmDialog
- [ ] ConfirmDialog 确认后执行对应 API 调用
- [ ] 操作完成后数量自动刷新
- [ ] 「去审核→」链接跳转到正确的审核页面
- [ ] 某阶段数量为 0 时显示 EmptyState
- [ ] 无 window.confirm / 无 alert 调用
- [ ] `npm run build` 通过

---

### Phase 3: Works 文献库重构（2-3h）

**目标**：优化文献浏览和筛选体验

| 任务 | 说明 | 复用资产 |
|------|------|---------|
| 统一筛选器 | 将 Works.vue 顶部的搜索/筛选区替换为 SearchHeader 组件风格 | **SearchHeader** |
| 列表项优化 | 减小行高提高信息密度，每项显示：标题+作者+年份+状态badge | **StatusBadge** |
| 分页样式 | 确认使用 Naive UI NPagination 组件，统一样式 | — |
| 空状态 | 无结果时显示 EmptyState | **EmptyState** |

#### 验收 checklist

- [ ] SearchHeader 组件正常工作（搜索+防抖）
- [ ] 文献列表每项有 StatusBadge 显示状态
- [ ] 空列表显示 EmptyState
- [ ] 分页功能正常
- [ ] `npm run build` 通过

---

### Phase 4: 审核页面统一（6-8h）🔴 最复杂

**目标**：统一 4 个审核页面的布局和交互模式

**涉及页面**：
- `MetadataReview.vue`
- `ClassificationReview.vue`
- `IntakeReview.vue`
- `InboxReview.vue`

| 任务 | 说明 | 复用资产 |
|------|------|---------|
| 统一双面板 | 全部迁移到 DualPanelLayout 组件（目前仅 MetadataReview 使用） | **DualPanelLayout** + **useDualPanel** |
| 统一列表项 | 左侧列表每项格式：StatusBadge(状态) + 标题 + 元信息(作者/来源/时间) | **StatusBadge** |
| 统一审核栏 | 右侧详情底部操作区统一使用 ReviewBar 组件（通过/拒绝/隔离/备注） | **ReviewBar** |
| 统一空状态 | 列表为空时使用 EmptyState | **EmptyState** |
| 统一危险操作 | 所有隔离/恢复/永久删除操作通过 ConfirmDialog | **ConfirmDialog** + **useQuarantine** |

**每个页面的标准结构**：

```
<DualPanelLayout>
  <!-- 左侧列表 -->
  <template #left>
    <div class="list-header">标题 + 筛选</div>
    <div class="list-body">
      <div v-for="item in items" :key="item.id" class="list-item">
        <StatusBadge :status="item.status" size="small" />
        <span class="item-title">{{ item.title }}</span>
        <span class="item-meta">{{ item.meta }}</span>
      </div>
      <EmptyState v-if="!items.length" icon="search" title="无记录" />
    </div>
    <Pagination :page="page" @update:page="loadData" />
  </template>

  <!-- 右侧详情 -->
  <template #right>
    <div v-if="selected">
      <div class="detail-header">
        <StatusBadge :status="selected.status" size="large" />
        <h2>{{ selected.title }}</h2>
      </div>
      <div class="detail-fields"><!-- 字段展示 --></div>
      <ReviewBar
        :status="selected.review_status"
        @approve="doApprove"
        @reject="doReject"
        @quarantine="showQuarantineConfirm"
      />
    </div>
    <EmptyState v-else icon="cursor" title="选择一条记录查看详情" />
  </template>
</DualPanelLayout>
```

#### 验收 checklist

- [ ] 4 个页面全部使用 DualPanelLayout（不再有内联的双面板实现）
- [ ] 4 个页面的列表项都有 StatusBadge
- [ ] 4 个页面都有 ReviewBar 操作栏
- [ ] 4 个页面的空状态都用 EmptyState
- [ ] 所有危险操作都走 ConfirmDialog
- [ ] 隔离操作调用 useQuarantine composable
- [ ] 4 个页面的布局风格一致（用户看不出是不同人写的）
- [ ] `npm run build` 通过

---

### Phase 5: 其他页面优化（4-5h）

**目标**：逐页面优化剩余页面的视觉一致性

| 页面 | 重点任务 | 复用资产 |
|------|---------|---------|
| **TopicsReview** | 迁移到 DualPanelLayout；主题列表使用 StatusBadge(lifecycle)；空状态 EmptyState | DualPanelLayout + StatusBadge + EmptyState |
| **DiscoveryReview** | 紫色→蓝色 accent 完成（Phase 1 已做基础）；三栏优化；run/hit 状态用 StatusBadge | StatusBadge + EmptyState |
| **Duplicates** | 列表紧凑化；合并预览区域；分页确认 | EmptyState |
| **Relations** | 图谱展示区域保持功能优先；容器样式用新变量 | — |
| **WorkDetail** | 详情布局优化；PDF drawer 用 usePdfDrawer；操作区用 ReviewBar | usePdfDrawer + StatusBadge |

#### 验收 checklist

- [ ] TopicsReview 使用 DualPanelLayout
- [ ] DiscoveryReview 无任何紫色残留
- [ ] Duplicates 列表信息密度合理
- [ ] WorkDetail PDF 抽屉正常
- [ ] 所有页面硬编码色值 grep ≤ 5
- [ ] `npm run build` 通过

---

## 技术约束

| 约束 | 说明 |
|------|------|
| 不引入新依赖 | 保持现有 Naive UI + Vue 3 + Vite |
| 不改后端 API | 所有接口已在 api.js 中封装，前端直接调用 |
| 不改功能逻辑 | 只改视觉、布局、新增流程管理页面（纯前端） |
| 每个Phase构建通过 | 每完成一个 Phase 必须 `npm run build` 成功才能进入下一 Phase |
| 必须复用已有组件 | Phase 1.2 明确列出的 6 个组件 + 6 个 composable 必须使用，不得重复造轮子 |
| 禁止 window.confirm/alert | 所有二次确认走 ConfirmDialog，所有错误提示走 error-handler.js 的 showError() |
| CSS 变量全量替换 | 旧变量名彻底清除，不做向后兼容 |

---

## 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 全量替换导致某个页面样式崩坏 | 中 | 高 | Phase 1.8 强制 11 页回归验证；每页截图对比 |
| Naive UI 组件 props不接受 CSS 变量导致色值无法消除 | 高 | 低 | 允许 NTag/NButton 的 color 属性保留 hex（≤5 处），在验收 checklist 里明确放行 |
| ConfirmDialog 集成遗漏导致漏用 window.confirm | 中 | 中 | Phase 2.5/4 验收 checklist 有专项检查；grep `window\.confirm` 必须零匹配 |
| 工作量超出估算 | 中 | 中 | 优先保 Phase 1 + 2.5（这两个价值最高）；Phase 4-5 可拆成下个迭代 |
| metadata?status=pending 后端不支持筛选 | 低 | 中 | 前端 fallback：拉全量列表后 `.filter(item => item.status === 'pending')` |

---

## 回滚预案

如果某 Phase 导致严重退化：

```bash
# 方案 A: git revert（推荐）
git revert HEAD~N   # N = 该 Phase 的 commit 数量

# 方案 B: git reset 到 Phase 前的 tag（慎用）
git reset --hard phase-N-start   # 需提前打 tag

# 每个Phase开工前建议打 tag:
git tag -a phase-1-start -m "Phase 1 开工基线"
git tag -a phase-2-start -m "Phase 2 开工基线"
# ...
```

---

## 预计工作量（修正版）

| Phase | 内容 | 预计时间 | 复杂度 | 依赖 |
|-------|------|---------|--------|------|
| **Phase 1** | 全局布局 + :root 全量替换 + 6组件同步 + 7视图色值替换 + 11页回归 | **5-7h** | 🔴 高 | 无（第一步） |
| **Phase 2** | Dashboard 治理控制台 | **1.5-2h** | 🟢 低 | Phase 1 |
| **Phase 2.5** | 流程管理页面（新功能，含 ConfirmDialog + 8 API） | **3-4h** | 🟡 中 | Phase 1 |
| **Phase 3** | Works 文献库重构 | **2-3h** | 🟡 中 | Phase 1 |
| **Phase 4** | 4 个审核页面统一（DualPanelLayout+ReviewBar+StatusBadge 全接入） | **6-8h** | 🔴 高 | Phase 1 |
| **Phase 5** | 其余 5 页面逐一优化 | **4-5h** | 🟡 中 | Phase 1 |
| **总计** | | **22-29h** | | |

### 推荐执行顺序（如需拆迭代）

**第一优先级（必做）**：Phase 1 → Phase 2.5 → Phase 4
- 理由：Phase 1 是基础；Phase 2.5 是最有价值的新功能；Phase 4 是视觉统一的收官

**第二优先级（重要但不紧急）**：Phase 2 → Phase 3
- 理由：Dashboard 和 Works 是高频页面但当前可用

**第三优先级（锦上添花）**：Phase 5
- 理由：TopicsReview/Discovery/Duplicates 等当前能用，可以后续迭代

---

## 实施者指令摘要（交给本地模型的最后一段话）

> 你拿到的是经过总控审核的 v2.0 计划。关键变更点：
> 
> 1. **全量替换策略**：CSS 变量不是增量补充而是整体重写。旧变量名全部清除。
> 2. **色系统一**：purple 已废弃，DiscoveryReview 改用蓝色 accent。`constants/options.js` 的 STATUS_COLOR_MAP 要同步更新。
> 3. **必须复用**：StatusBadge/EmptyState/ConfirmDialog/SearchHeader/ReviewBar/DualPanelLayout 这 6 个组件已经存在，不要重新创建。
> 4. **Phase 2.5 的 ConfirmDialog 是强约束**：所有批量操作的二次确认必须走这个组件。
> 5. **每个 Phase 结束后**：`npm run build` 必须通过 + `grep 'window\.confirm\|alert('` 必须零匹配 + 打 git tag。
> 
> 从 Phase 1 开始做。做完 Phase 1 后交回审核，再决定是否继续。
