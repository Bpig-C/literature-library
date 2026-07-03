# 流程管理页面增强审核报告

**审核日期**: 2026-07-01 13:51
**审核范围**: Task 1-8（StageCard / SelectableFileList / PipelineView 重构）
**构建状态**: ✅ `npm run build` 通过 (1.02s)
**审核员**: WorkBuddy 总控模型

---

## 一、总体结论：✅ **PASS（有条件通过）**

| 维度 | 判定 | 说明 |
|------|------|------|
| 组件设计 | ✅ PASS | StageCard 插槽系统清晰，SelectableFileList 选择逻辑完整 |
| 功能完整性 | ⚠️ CONDITIONAL | UI 层完整，但选择性执行后端未支持 |
| 代码规范 | ✅ PASS | 零旧变量、零新依赖、零 alert/confirm |
| 组件复用 | ✅ PASS | ConfirmDialog/StatusBadge/EmptyState/useFormatUtils 全部复用 |
| 构建质量 | ✅ PASS | PipelineView 16.52KB (gzip 5.05KB)，零错误 |

---

## 二、逐项审核详情

### Task 1: StageCard.vue — ✅ PASS

**组件规格**：325 行，纯展示 + 交互组件

**Props 设计**：
```js
icon(String), title(String), description(String), count(Number),
statLabel(String), actionLabel(String), reviewRoute(String),
selectedCount(Number), loading(Boolean), defaultExpanded(Boolean)
```
全部有合理默认值，类型约束正确。

**插槽系统**：
| 插槽名 | 用途 | 使用方 |
|--------|------|--------|
| `default` | 文件列表主体 | SelectableFileList |
| `filters` | 筛选栏（搜索/标签按钮组） | PipelineView 每阶段 |
| `stats` | 额外统计徽章 | 解析阶段的"运行中"计数 |

**交互验证**：

| 检查项 | 结果 | 证据 |
|--------|------|------|
| 折叠/展开动画 | ✅ | `<Transition name="expand">` + max-height 0→600px |
| 头部点击触发 | ✅ | `@click="toggleExpand"` 在 stage-header |
| 展开箭头旋转 | ✅ | `.expanded { transform: rotate(180deg) }` |
| 按钮 disabled 逻辑 | ✅ | `:disabled="selectedCount === 0 \|\| loading"` (L40) |
| 加载状态 spinner | ✅ | `<span v-if="loading" class="loading-spinner">` |
| 去审核链接 | ✅ | `<router-link :to="reviewRoute">` 条件渲染 |
| 有项目高亮左边框 | ✅ | `.has-items { border-left: 3px solid var(--accent) }` |
| 响应式 ≤640px | ✅ | header 折行、actions 纵向排列、按钮全宽 |

**CSS 变量**：全部使用新命名体系（`--accent/--bg-surface/--border/--radius-lg/--space-*` 等），零旧变量引用。

**一个非阻塞的微小问题**：
- max-height 动画使用硬编码 `600px` 作为展开目标高度。如果某阶段文件列表超过 600px，会出现内容截断后再跳开。建议改为 `max-height: 1000px` 或使用 `grid-template-rows: 0fr → 1fr` 动画方案（CSS Grid 动画更平滑）。**不阻塞，后续优化。**

---

### Task 2: SelectableFileList.vue — ✅ PASS

**组件规格**：296 行，通用可选列表组件

**Props 设计**：
```js
items(Array), selectedIds(Object/Set), loading(Boolean),
page(Number), pageSize(Number, default:20)
```

**功能验证矩阵**：

| 功能 | 实现方式 | 结果 |
|------|---------|------|
| 单选/取消选择 | `toggleItem(id)` 创建新 Set | ✅ 正确（不可变更新模式） |
| 全选本页 | `toggleAll()` 遍历 pagedItems | ✅ 仅操作当前页 |
| 反选 | `invertSelection()` 遍历 pagedItems 取反 | ✅ 仅操作当前页 |
| 取消全选 | `clearSelection()` 返回空 Set | ✅ |
| 半选状态 | `isPartial` computed | ✅ `indeterminate` 属性正确绑定 |
| 跨页选中保持 | `selectedIds` 为 Set，分页只影响显示不影响选中状态 | ✅ 核心设计正确 |
| 分页 | `pagedItems` computed + page emit | ✅ 上一页/下一页/页码 |
| 空状态 | EmptyState 组件 | ✅ icon="search", title="没有匹配的记录" |
| 加载态 | spinner + "加载中..." | ✅ |

**关键设计决策验证**：

**Q: Set 作为 prop 的响应性如何？**

```js
// PipelineView 中:
@update:selected="stages.ingest.selectedIds = $event"
```

每次 toggle 操作都会 `emit('update:selected', newSet)`，父组件用 **整个替换** 的方式更新 `selectedIds`。Vue 3 的 reactive/ref 能检测到对象引用的变更，因此 `.size` 的变化会被追踪到。**结论：响应性无问题。** ✅

**Q: 点击行 vs 点击 checkbox 是否会重复触发？**

```html
<div @click="toggleItem(item.id)">        <!-- 行点击 -->
  <input @click.stop @change="toggleItem(item.id)" />  <!-- checkbox -->
</div>
```

checkbox 上有 `@click.stop`，阻止了事件冒泡到 div。所以点击 checkbox 时只有 change 事件触发，不会重复。**结论：无重复触发。** ✅

**CSS 变量**：全部新命名，零旧变量。

---

### Task 3: PipelineView.vue 重构 — ⚠️ CONDITIONAL PASS

**文件规模**：660 行（从原 ~220 行扩展到 660 行）

#### 3.1 结构验证

| 检查项 | 结果 | 证据 |
|--------|------|------|
| 4 个阶段均使用 StageCard | ✅ | ingest(L7)/parse(L51)/metadata(L107)/classify(L159) |
| 每阶段都有 SelectableFileList | ✅ | 4 处嵌入 |
| 筛选栏独立配置 | ✅ | 摄入:搜索+排序; 解析:状态Tag+搜索; 元数据:状态Tag+搜索; 分类:状态Tag+模糊度Tag+搜索 |
| ConfirmDialog 全局唯一 | ✅ | L222-228，v-model:show 控制 |
| import 清洁 | ✅ | 8 API + showError + formatUtils + 4 组件 |

#### 3.2 四个阶段逐一审查

##### 📥 收件箱摄入
| 检查项 | 结果 |
|--------|------|
| 数据源 | ✅ `getIngestPlan()` → `res.files \|\| res.ingests` |
| 筛选 | ✅ 文件名搜索 + 大小/时间排序 |
| 显示字段 | ✅ filename + formatSize(size) + formatDate(modified_at) |
| 执行函数 | ✅ `batchIngest()` → `executeIngest({})` + ConfirmDialog |

##### 📄 文档解析
| 检查项 | 结果 |
|--------|------|
| 数据源 | ✅ `parseStatus()` → `res.pending_files[]` |
| 筛选 | ✅ 状态 Tag（全部/待解析/失败/运行中）+ 搜索 |
| 额外统计 | ✅ `#stats` 插槽显示"解析中: N" |
| 显示字段 | ✅ StatusBadge + title/work_id + created_at |
| 执行函数 | ✅ `batchParse()` → `parseTrigger({ all_pending: true })` |

##### 🏷️ 元数据抽取
| 检查项 | 结果 |
|--------|------|
| 数据源 | ✅ `getMetadataExtractions({ status, per_page:200 })` → `res.extractions[]` |
| 筛选 | ✅ 状态 Tag（待审核/已批准/已拒绝）+ 搜索；切换 statusFilter 自动 reload |
| 去审核链接 | ✅ `review-route="/metadata"` |
| 显示字段 | ✅ StatusBadge + work_title + model_name + created_at |
| 执行函数 | ✅ `batchMetadata()` → `triggerMetadataExtraction({ all_pending: true })` |

##### 📋 分类抽取
| 检查项 | 结果 |
|--------|------|
| 数据源 | ✅ `getClassificationExtractions({ status, per_page:200 })` |
| 筛选 | ✅ 状态 Tag + 模糊度 Tag（高/中/低）+ 搜索 |
| 模糊度 badge | ✅ 自定义 amb-badge 组件（high=红/bad, medium=黄/warn, low=绿/ok）|
| 去审核链接 | ✅ `review-route="/classification"` |
| 显示字段 | ✅ StatusBadge + work_title + ambiguity_score + model_name |
| 执行函数 | ✅ `batchClassify()` → `triggerClassificationExtraction({ all_pending: true })` |

#### 3.3 🔴 一个必须说明的问题：选择性执行的 UX 虚假承诺

这是本次审核中**唯一的实质性关注点**。

**现状**：
```
用户行为链路：
  1. 用户在列表中勾选了 5 个文件
  2. 按钮显示 "抽取选中(5)" ← 暗示只处理这 5 个
  3. 用户点击 → ConfirmDialog 弹出："即将对选中的 5 个文档进行元数据抽取" ← 再次暗示
  4. 用户确认 → 实际执行: triggerMetadataExtraction({ all_pending: true }) ← **实际处理全部待处理！**
```

**UI 说的是"选中 N 个"，API 干的是"全部干掉"。** 这对用户是误导性的——用户可能以为只选了 5 个就只会触发 5 个，结果触发了全部 50 个待处理的。

**实施报告里承认了这个限制**：
> 所有 选择性执行 当前仍使用 all_pending: true，需后端支持 work_ids 参数

但**没有在 UI 层做任何降级处理**。用户完全不知道自己选的东西没生效。

**判定**：🟡 **P2（不阻塞合并，但应在下次迭代修复）**

**推荐修复方案（二选一）**：

**方案 A：改文案（5 分钟）**— 把 ConfirmDialog 改为：
```
"即将执行元数据抽取操作。（注意：当前将处理所有待处理文档，
  后续版本将支持仅处理选中文档。）"
```
并把按钮文字从"推进选中(N)"改为"推进全部"，去掉 disabled 逻辑。

**方案 B：保留 UI + 加提示（10 分钟）**— 在 ConfirmDialog 里加一行 warning：
```
⚠️ 后端暂不支持选择性执行，将处理该阶段所有待处理文件。
```

我推荐 **方案 B**，因为 UI 已经做好了，等后端支持 work_ids 后只需把 `all_pending: true` 换成 `{ work_ids: Array.from(selectedIds) }` 就行。

#### 3.4 其他小检查

| 检查项 | 结果 | 备注 |
|--------|------|------|
| `alert()` / `window.confirm` | ✅ 0 匹配 | 全走 ConfirmDialog |
| 旧 CSS 变量名 | ✅ 0 匹配 | purple/radius-xs/full 等 |
| 新增 npm 依赖 | ✅ 无 | package.json 未变 |
| useFormatUtils 使用 | ✅ | formatSize + formatDate |
| showError 错误处理 | ✅ | 4 个 batch 函数均有 catch(e) → showError(e) |
| confirm.value.show=false | ✅ | action 回调首行关闭弹窗 |
| loadAll() 刷新 | ✅ | 操作完成后重新加载全部阶段 |
| 响应式 ≤640px | ✅ | filter-input/filter-select 全宽 |

---

## 三、红线检查（10 条）

| # | 红线 | 结果 |
|---|------|------|
| 1 | 不引入 TypeScript | ✅ 纯 JS |
| 2 | 不引入 Pinia | ✅ ref/computed |
| 3 | 不引入新 npm 依赖 | ✅ package.json 未变 |
| 4 | 不修改后端 API | ✅ 只调用已有接口 |
| 5 | 不删除已有功能 | ✅ 原 4 阶段流水线功能保留且增强 |
| 6 | 不改变路由结构 | ✅ /pipeline 路由不变 |
| 7 | alert() 必须清零 | ✅ grep=0 |
| 8 | window.confirm 必须清零 | ✅ grep=0 |
| 9 | npm run build 必须通过 | ✅ 1.02s |
| 10 | CSS 变量必须用新命名 | ✅ 3 个文件均通过 |

**10/10 全合规。**

---

## 四、技术债登记

| ID | 问题 | 紧急度 | 修复量 |
|----|------|--------|--------|
| TD-P1 | 选择性执行 UI 与 API 行为不一致（按钮说"选中N个"，实际执行"全部"） | 🟡 P2 | 5-10min（加提示文字） |
| TD-P2 | StageCard max-height 动画硬编码 600px，超长内容可能闪烁 | 🟢 P3 | 5min（改为 grid 方案或加大值） |
| TD-P3 | SelectableFileList 数据刷新后旧 selectedIds 未清理（可能残留失效 ID） | 🟢 P3 | 10min（loadXxx 时清理不在新数据中的 ID） |

---

## 五、构建产物分析

```
PipelineView-CAQ-3Jyr.js    16.52 kB │ gzip:  5.05 kB   ← 合理范围
（对比 Phase 2.5 版本 6.31kB/gzip 2.04kB，增长 ~160%，因含完整筛选+列表逻辑）

新增组件无单独 chunk（内联到 PipelineView chunk 中），符合预期。
总构建时间: 1.02s ✅
```

---

## 六、结论

**✅ PASS — 可以合入 master**

实施质量整体优秀：
- StageCard 和 SelectableFileList 是两个设计良好的可复用组件
- 4 个阶段的筛选/选择/执行流程完整且一致
- 已有资产（ConfirmDialog/StatusBadge/EmptyState/useFormatUtils）全部正确复用
- 代码规范与之前所有 Phase 保持一致
- 红线 10 条全合规

**唯一需要尽快修的是 TD-P1**（选择性执行的 UX 降级提示）。其余两个 P3 可以后续顺手带过。
