# 流程管理页面增强 — 可选文件预览与选择性推进

**版本**: v1.0
**日期**: 2026-07-01
**状态**: 待实施（Phase 5 完成后执行）
**优先级**: P1（用户体验关键改进）

---

## 一、需求概述

### 当前问题

PipelineView.vue（流程管理页面）当前只显示每个阶段的**待处理数量**和「全部XX」按钮。用户点击「全部摄入/全部解析/全部抽取」时，**无法看到具体哪些文件会被处理**，也无法选择性地只处理部分文件。

### 目标效果

```
┌─────────────────────────────────────────────────────┐
│ 📥 收件箱摄入                    待摄入: 12 篇       │
│ 将 _inbox/ 中的 PDF 文件摄入到文献库                   │
│                                                      │
│ ┌─ 文件列表 (可折叠) ─────────────────────────┐      │
│ │ ☑ paper_001.pdf    2.3 MB   2026-06-30      │      │
│ │ ☑ paper_002.pdf    1.8 MB   2026-06-29      │      │
│ │ ☐ paper_003.pdf    4.1 MB   2026-06-28      │      │
│ │ ☑ paper_004.pdf    0.9 MB   2026-06-28      │      │
│ │ ... (共 12 项)                             │      │
│ │                                             │      │
│ │ [筛选: 全部 ▾] [反选] [全选/取消全选]        │      │
│ │ 已选: 10 篇                                  │      │
│ └─────────────────────────────────────────────┘      │
│                                      [▶ 摄入选中(10)] │
└─────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────┐
│ 📄 文档解析                       待解析: 8 篇       │
│ 使用 MinerU 将 PDF 转换为可读文本                     │
│                                                      │
│ ┌─ 文件列表 (可折叠) ─────────────────────────┐      │
│ │ ☐ work_a001  《论文标题A》   解析失败(重试)   │      │
│ │ ☑ work_a002  《论文标题B》   待解析           │      │
│ │ ☑ work_a003  《论文标题C》   待解析           │      │
│ │ ...                                         │      │
│ │                                             │      │
│ │ [按状态筛选: 全部 ▾] [按标题搜索...]          │      │
│ │ 已选: 2 篇                                   │      │
│ └─────────────────────────────────────────────┘      │
│                                     [▶ 解析选中(2)]  │
└─────────────────────────────────────────────────────┘
```

### 核心交互规则

| 规则 | 说明 |
|------|------|
| **默认折叠** | 每个阶段的文件列表默认收起，点击数量 badge 或箭头展开 |
| **选择才推进** | 「推进」按钮的文字随选中数动态变化：「全部摄入」→「摄入选中(N)」；未选中任何项时按钮 **disabled** |
| **跨页选择** | 列表支持分页，选中状态在翻页后保持（用 Set 存 ID） |
| **筛选能力** | 每个阶段支持不同的筛选维度（见下文 §二） |
| **批量操作安全** | 点击「推进选中」后仍需 ConfirmDialog 二次确认 |

---

## 二、各阶段的数据源与筛选方案

### 阶段 1: 收件箱摄入 (📥)

**数据来源**: `getIngestPlan()` → `res.files` 数组（需确认字段）

```js
// api.js 已有:
export function getIngestPlan(params = {}) { return request(`/ingest/plan${q}`) }
// 返回: { summary: { ingests: N }, files: [{ filename, size, modified_at, path }] }
```

> ⚠️ **需要确认**: `getIngestPlan` 的返回值是否包含文件列表。如果只有 summary.count，需要在后端加一个 `/ingest/plan?detail=true` 或前端分页拉取。如果后端暂不支持，先用 mock 数据占位。

**筛选维度**:
| 筛选项 | 类型 | 说明 |
|--------|------|------|
| 搜索框 | 文本输入 | 按文件名模糊搜索 |
| 大小排序 | 升序/降序 | 按文件大小排序 |
| 时间排序 | 升序/降序 | 按修改时间排序 |
| 反选/全选/取消全选 | 操作按钮 | 批量选择辅助 |

**列表列**: `[☑ 选择框]` `[文件名]` `[大小]` `[修改时间]`

---

### 阶段 2: 文档解析 (📄)

**数据来源**: `parseStatus()` → 可能需要扩展

```js
// api.js 已有:
export function parseStatus(workId) { return request(`/parse/status${workId ? '?work_id=' + workId : ''}`) }
// 当前返回: { pending: N, running: N }
// 需要: 返回 pending_files: [{ work_id, title, status, created_at }]
```

> ⚠️ **可能需要的改动**: 后端 `parse_status` 接口需要返回待解析的文件列表，而不只是计数。如果目前不支持，先在文档里标注为"依赖后端扩展"。

**筛选维度**:
| 筛选项 | 类型 | 说明 |
|--------|------|------|
| 状态筛选 | Tag 按钮 | `待解析` / `解析失败(重试)` / `解析中` |
| 搜索框 | 文本输入 | 按标题搜索 |
| 排序 | 下拉 | 按创建时间 / 按标题 |

**列表列**: `[☑ 选择框]` `[work_id / 标题]` `[StatusBadge: 状态]` `[创建时间]`

---

### 阶段 3: 元数据抽取 (🏷️)

**数据来源**: `getMetadataExtractions({ status: 'pending' })`

```js
// api.js 已有:
export function getMetadataExtractions(params = {}) {
  const q = new URLSearchParams(params).toString()
  return request(`/metadata${q ? '?' + q : ''}`)
}
// 返回: { items: [{ id, work_id, work_title, status, model_name, created_at }], total: N }
// ✅ 这个接口已经返回完整列表！无需改后端
```

**筛选维度**（参考 ClassificationReview 页面的模式）:

| 筛选项 | 类型 | Naive UI 组件 | 说明 |
|--------|------|---------------|------|
| 状态筛选 | Tag 组 | NTag (可点击切换) | `pending` / `approved` / `rejected` |
| 搜索框 | 输入框 | NInput | 按标题/work_id 搜索 |
| 模型筛选 | Tag 组 | NTag | Mimo / Ollama（如果 model_name 字段可用） |
| 排序 | Select + 按钮 | NSelect | 创建时间 / 标题 |

**列表列**: `[☑ 选择框]` `[标题/work_id]` `[StatusBadge]` `[model_name]` `[created_at]`

---

### 阶段 4: 分类抽取 (📋)

**数据来源**: `getClassificationExtractions({ status: 'pending' })`

```js
// api.js 已有:
export function getClassificationExtractions(params = {}) { ... }
// 返回: { items: [{ id, work_id, work_title, status, ambiguity_score, model_name }], total: N }
// ✅ 完整列表可用！
```

**筛选维度**:

| 筛选项 | 类型 | 说明 |
|--------|------|------|
| 模糊度筛选 | Tag 组 | 高 / 中 / 低（复用 ClassificationReview 的模式） |
| 状态筛选 | Tag 组 | pending / approved / rejected |
| 优先级筛选 | Tag 组 | P0 / P1 / P2 / P3（如果有 priority 字段） |
| 搜索框 | 输入框 | 按标题搜索 |

**列表列**: `[☑ 选择框]` `[标题]` `[ambiguity_score]` `[StatusBadge]` `[priority]` `[created_at]`

---

## 三、技术实施方案

### 3.1 组件拆分

将 PipelineView.vue 从单文件拆分为：

```
web/src/views/PipelineView.vue              # 主页面（编排 4 个 StageCard）
web/src/components/StageCard.vue            # 新建: 单个阶段卡片（可展开的文件列表）
web/src/components/SelectableFileList.vue   # 新建: 可选择的文件列表（含筛选/分页）
```

#### StageCard.vue 结构

```vue
<template>
  <div class="stage-card" :class="{ expanded: isExpanded }">
    <!-- 折叠态: 只显示头部 -->
    <div class="stage-header" @click="toggleExpand">
      <span class="stage-icon">{{ icon }}</span>
      <div class="stage-info">
        <h2>{{ title }}</h2>
        <p>{{ description }}</p>
      </div>
      <div class="stage-stats">
        <span class="stat-badge" :class="{ active: count > 0 }">
          {{ statLabel }}: {{ count }} 篇
        </span>
      </div>
      <span class="expand-arrow">{{ isExpanded ? '▲' : '▼' }}</span>
    </div>

    <!-- 展开态: 文件列表 + 操作 -->
    <Transition name="expand">
      <div v-if="isExpanded" class="stage-body">
        <!-- 筛选栏 -->
        <div class="filter-bar">
          <slot name="filters" />
        </div>

        <!-- 文件列表 (带选择框) -->
        <SelectableFileList
          :items="fileItems"
          :selected-ids="selectedIds"
          :loading="loading"
          :total="totalCount"
          :page-size="pageSize"
          @update:selected="onSelectionChange"
          @update:page="onPageChange"
        >
          <template #item="{ item }">
            <slot name="file-item" :item="item" />
          </template>
        </SelectableFileList>

        <!-- 底部操作栏 -->
        <div class="stage-actions">
          <span class="selection-summary">
            已选: <b>{{ selectedIds.size }}</b> / {{ count }} 篇
          </span>
          <button
            class="btn-primary"
            :disabled="selectedIds.size === 0 || loading"
            @click="onExecute"
          >
            {{ actionLabel }} ({{ selectedIds.size }})
          </button>
          <router-link v-if="reviewRoute" :to="reviewRoute" class="btn-link">
            去审核 →
          </router-link>
        </div>
      </div>
    </Transition>
  </div>
</template>
```

#### SelectableFileList.vue 结构

```vue
<template>
  <div class="selectable-list">
    <div class="list-toolbar">
      <label class="select-all-label">
        <input type="checkbox" :checked="isAllSelected" @change="toggleAll" />
        全选本页
      </label>
      <button class="toolbar-btn" @click="$emit('invert')">反选</button>
    </div>

    <div class="list-body">
      <div
        v-for="item in pagedItems"
        :key="item.id"
        class="list-item"
        :class="{ selected: selectedIds.has(item.id) }"
        @click="toggleItem(item)"
      >
        <input
          type="checkbox"
          :checked="selectedIds.has(item.id)"
          @click.stop
          @change="toggleItem(item)"
          class="item-checkbox"
        />
        <slot name="item" :item="item" />
      </div>
      <EmptyState v-if="!pagedItems.length && !loading" icon="search" title="没有匹配的记录" />
    </div>

    <div v-if="totalPages > 1" class="pagination-bar">
      <!-- 用原生按钮或简单分页，不引入新依赖 -->
      <button :disabled="page <= 1" @click="$emit('update:page', page - 1)">上一页</button>
      <span>{{ page }} / {{ totalPages }}</span>
      <button :disabled="page >= totalPages" @click="$emit('update:page', page + 1)">下一页</button>
    </div>
  </div>
</template>
```

### 3.2 状态管理

使用**组件内部 ref**（不需要 Pinia），结构如下：

```js
// PipelineView.vue
const stages = ref({
  ingest: {
    count: 0,
    loading: false,
    expanded: false,
    selectedIds: new Set(),      // 选中的文件 ID 集合
    files: [],                    // 文件列表数据
    page: 1,
    pageSize: 20,
    filter: '',                   // 搜索关键词
    filters: {},                  // 其他筛选条件（状态/模型等）
  },
  parse: { /* 同构 */ },
  metadata: { /* 同构 */ },
  classify: { /* 同构 */ },
})
```

### 3.3 各阶段 API 调用差异

| 阶段 | 加载列表 API | 执行操作 API | 选择性执行？ |
|------|-------------|-------------|------------|
| **摄入** | `getIngestPlan()` | `executeIngest({ filenames: [...] })` ⚠️ 需确认是否支持 | 取决于后端 |
| **解析** | `parseStatus({ detail: true })` ⚠️ 可能需扩展 | `parseTrigger({ work_ids: [...] })` ⚠️ 需确认 | 取决于后端 |
| **元数据** | `getMetadataExtractions({ status:'pending' })` | `triggerMetadataExtraction({ all_pending: true })` → 改为 `{ work_ids: [...] }` ⚠️ 需确认 | 取决于后端 |
| **分类** | `getClassificationExtractions({ status:'pending' })` | `triggerClassificationExtraction({ all_pending: true })` → 改为 `{ work_ids: [...] }` ⚠️ 需确认 | 取决于后端 |

> **⚠️ 关键风险点**: 当前所有批量操作 API 都是 `all_pending: true` 模式（无参数=全部）。**选择性推进需要后端支持传入具体的 work_id/filename 列表**。
>
> 如果后端暂时不支持：
> - **方案 A（推荐）**: 先实现 UI 层（展示+选择），点击「推进选中」时给出提示 "该功能需要后端支持选择性执行，即将调用全量模式"，然后退化为 `all_pending: true`
> - **方案 B**: 前端不调 API，只生成一个操作计划清单让用户确认，用户去对应审核页面手动处理

### 3.4 复用已有组件

| 已有组件 | 在何处复用 |
|---------|-----------|
| **ConfirmDialog** | 每个 StageCard 的「推进」按钮点击后 |
| **StatusBadge** | 元数据/分类阶段文件列表中的状态标签 |
| **EmptyState** | 筛选后无结果时 |
| **useFormatUtils.js** | `formatSize()`, `formatDate()`, `truncateText()` |

---

## 四、实施任务分解

### Task 1: 创建 StageCard.vue 组件（基础骨架）
- [ ] 新建 `web/src/components/StageCard.vue`
- [ ] 实现 props: icon/title/description/count/statLabel/actionLabel/reviewRoute
- [ ] 实现折叠/展开动画（CSS Transition）
- [ ] 头部区域布局（图标+信息+统计+箭头）
- [ ] 插槽: filters / actions / default（文件列表区）
- [ ] 验收: 在 PipelineView 中替换现有的 4 个 stage-card 为 `<StageCard>`, 视觉一致

### Task 2: 创建 SelectableFileList.vue 组件
- [ ] 新建 `web/src/components/SelectableFileList.vue`
- [ ] 实现复选框选择（单选/反选/全选本页）
- [ ] 实现 selectedIds (Set) 的双向绑定
- [ ] 实现简易分页（上一页/下一页/页码显示）
- [ ] 插槽: item（自定义每行渲染）
- [ ] 验收: 能正确勾选/取消/反选/翻页保持选中状态

### Task 3: 重构 PipelineView.vue 使用 StageCard
- [ ] 引入 StageCard 替换 4 个内联 stage-card
- [ ] 每个阶段的文件列表数据加载逻辑独立
- [ ] 保持原有的 4 个 batch 函数（batchIngest/batchParse/batchMetadata/batchClassify）
- [ ] 验收: 功能与重构前完全一致（回归测试）

### Task 4: 实现元数据阶段的完整文件列表（优先做，因为 API 最成熟）
- [ ] loadMetadata() 改为加载完整列表（不只是 count）
- [ ] StageCard 内嵌入 SelectableFileList
- [ ] 筛选栏: 状态 Tag (pending/approved/rejected) + 搜索框
- [ ] 文件行: checkbox + 标题 + StatusBadge + 模型名 + 时间
- [ ] 「抽取选中(N)」按钮 → ConfirmDialog → 调 API
- [ ] 验收: 能展开看到 pending 的元数据条目，能选择/筛选，能触发抽取

### Task 5: 实现分类阶段的完整文件列表
- [ ] loadClassify() 改为加载完整列表
- [ ] 筛选栏: 模糊度(high/med/low) + 状态 + 优先级(P0-P3) + 搜索
- [ ] 文件行: checkbox + 标题 + amb badge + StatusBadge + priority
- [ ] 「抽取选中(N)」按钮
- [ ] 复用 ClassificationReview 的模糊度/优先级筛选样式
- [ ] 验收: 筛选功能正常，选择正常

### Task 6: 实现摄入阶段的文件列表
- [ ] 确认/扩展 getIngestPlan API 是否返回文件详情
- [ ] 如果不支持: 显示 "待摄入: N 篇 (点击查看文件)" + 占位 EmptyState
- [ ] 如果支持: 渲染文件列表（文件名 + 大小 + 修改时间）
- [ ] 筛选: 搜索框 + 大小/时间排序
- [ ] 「摄入选中(N)」按钮
- [ ] 验收: 文件列表正确展示

### Task 7: 实现解析阶段的文件列表
- [ ] 确认/扩展 parseStatus API 是否返回文件详情
- [ ] 如果不支持: 显示占位 + "待解析: N 篇"
- [ ] 如果支持: 渲染列表（work_id + 标题 + 解析状态）
- [ ] 筛选: 状态(待解析/失败/运行中) + 搜索
- [ ] 「解析选中(N)」按钮
- [ ] 验收: 正常

### Task 8: 响应式适配与打磨
- [ ] ≤768px: StageCard 展开后的列表宽度自适应
- [ ] ≤640px: 筛选栏折行，操作按钮堆叠
- [ ] 文件列表行高适中（移动端可触摸）
- [ ] 展开/收起动画流畅（max-height transition）
- [ ] 验收: 手机上能正常展开/选择/操作

---

## 五、验收 Checklist

### 必须通过（PASS 条件）

- [ ] **BUILD-1**: `npm run build` 通过，零错误
- [ ] **COMP-1**: 4 个阶段均可展开/收起，动画流畅
- [ ] **SEL-1**: 每个阶段的文件列表支持多选（checkbox）
- [ ] **SEL-2**: 全选/反选/取消全选功能正常
- [ ] **SEL-3**: 翻页后选中状态保持（跨页选择）
- [ ] **FILT-1**: 至少元数据和分类两个阶段有筛选功能（状态/模糊度等）
- [ ] **BTN-1**: 未选中任何项时，「推进」按钮 disabled 且文字为灰色
- [ ] **BTN-2**: 选中 N 项后，按钮文字变为「推进选中(N)」
- [ ] **CONF-1**: 点「推进选中」后弹出 ConfirmDialog
- [ ] **API-1**: 元数据和分类阶段的列表数据正确从 API 加载
- [ ] **COMP-2**: 复用了 ConfirmDialog / StatusBadge / EmptyState（不重复造轮子）
- [ ] **REDLINE-1**: 不引入新的 npm 依赖（纯 Vue 3 + 已有的 Naive UI）
- [ ] **REDLINE-2**: 不改后端 API（如果需要扩展，在前端标注 TODO 并优雅降级）

### 理想通过（锦上添花）

- [ ] **PERF-1**: 单阶段文件 >100 时列表渲染流畅（考虑虚拟滚动或仅前 100 条可选拉取更多）
- [ ] **A11Y-1**: 键盘 Tab 能遍历 checkbox 和按钮
- [ ] **A11Y-2**: 列表行有 `:focus-visible` 样式（已注入 :root）

---

## 六、工作量估算

| Task | 内容 | 预计时间 |
|------|------|---------|
| 1 | StageCard.vue 基础组件 | 1-1.5h |
| 2 | SelectableFileList.vue | 1.5-2h |
| 3 | PipelineView 重构 | 1h |
| 4 | 元数据阶段完整实现 | 1.5-2h |
| 5 | 分类阶段完整实现 | 1.5-2h |
| 6 | 摄入阶段实现 | 1-1.5h |
| 7 | 解析阶段实现 | 1-1.5h |
| 8 | 响应式与打磨 | 1-1.5h |
| **总计** | | **10-13h** |

---

## 七、红线（不可违反）

1. **不新增 npm 依赖** — 用已有的 Naive UI 组件（NTag/NInput/NSelect/NPagination）和原生 HTML
2. **不改后端 API** — 如果现有 API 不够用，在前端用 TODO 注释标记并优雅降级
3. **保留 ConfirmDialog 集成** — 所有破坏性操作必须走已有组件
4. **保留 StatusBadge** — 状态标签统一用已有组件
5. **构建必须通过** — 每次 Task 完成后跑一次 build
