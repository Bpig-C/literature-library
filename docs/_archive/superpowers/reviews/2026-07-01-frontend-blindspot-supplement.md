# V1.3 P2-3 前端重构方案 — 盲区补充与实施蓝图 v2.0

> **文档定位**: 本文档是 `2026-07-01-frontend-design-audit.md`（审计方案 v1.0）的**补充件**，不替代原方案，而是补全原方案未覆盖的 6 个架构维度 + 解决 3 个布局疑问。
>
> **适用阶段**: 前端重构的规划/设计阶段（零代码产出，纯分析+决策）。
>
> **阅读顺序**: 建议先读原审计方案，再读本补充件。本件的 §1–§6 对应 6 个盲区，§7 对应 3 个线框疑问，§8 是整合后的完整蓝图。

---

## §0 执行摘要

### 原方案做得好的地方（确认不变）

| 维度 | 评价 |
|------|------|
| 审计深度 | 数据翔实，逐页打分，可操作性强 |
| 设计令牌 | CSS 变量体系完整、实用、可直接落地到 `:root` |
| 组件识别 | 12 个候选组件合理，但缺组件间依赖关系图 |
| 优先级排序 | P0-P3 合理，P0 内部执行顺序可更细 |
| 实施路径 | Phase 1→4 清晰，缺每 phase 的验收标准 |

### 本补充件新增内容

| 编号 | 盲区名称 | 原方案覆盖 | 本件结论 | 紧急度 |
|------|---------|-----------|---------|--------|
| B-1 | 状态管理策略 | 未提及 | 推荐"Composable 为主 + 按需 Pinia"混合策略 | 高 |
| B-2 | 路由架构 | 未涉及 | 需补：404 / 命名 / 模块化 / 守卫框架 | 中 |
| B-3 | API 层封装 | 未审计 | MVP 级别，需补 P0 三项：AbortController + 错误处理 + 超时 | 高 |
| B-4 | 错误边界与降级 | 未设计 | 需全局 errorHandler + 网络降级 + ErrorBoundary | 中 |
| B-5 | 性能优化 | 未提及 | 当前基础良好，P0 仅 3 项（Duplicates 分页 / PDF 动态导入 / 高亮 debounce） | 低（按需触发）|
| B-6 | 可访问性 a11y | 完全空白 | 基线评分 4.5/10，Phase 1 快修可达 6.0 | 低（合规储备）|

---

## §1 盲区 B-1: 状态管理策略分析与决策

### 1.1 现状诊断

经过对全部 11 个页面级组件（`views/*.vue`）的状态管理审计：

| 指标 | 数值 |
|------|------|
| 页面组件数 | 11 个 |
| 总代码量 (views/) | ~5800 行 |
| 全局状态库 (Pinia/Vuex) | **零使用** — 纯本地 `ref()`/`reactive()` |
| 已有 Composable | 1 个 (`usePagination.js`) |
| 最大单文件状态数 | MetadataReview.vue (~30 个 ref/reactive) |

### 1.2 重复状态模式 TOP 5

#### 🔴 #1: 隔离操作 (useQuarantine) — 4 页面完全重复 [最严重]

涉及: Works, WorkDetail, MetadataReview, ClassificationReview
四个文件中几乎相同的代码块（QUARANTINE_REASONS 定义 + showQuarantineModal + confirmQuarantine 函数），约 200 行 x 4 = **800 行重复**

#### 🔴 #2: 选项定义常量 — 5+ 处大块重复 [最繁琐]

PRIMARY_DOC_TYPE_OPTIONS / READING_LANE_OPTIONS / PUBLICATION_STATUS_OPTIONS / INGESTION_STATE_OPTIONS / PRIORITY_OPTIONS 在多个文件中重复定义，总计约 **1000 行**

#### 🟡 #3: 列表+详情双面板布局 — 5 页面重复

listWidth / listCollapsed / detailWidth / toggleListCollapse / onResizeList / layoutStyle computed 在 IntakeReview, InboxReview, Duplicates, MetadataReview, ClassificationReview 中反复出现，约 **500 行**

#### 🟡 #4: PDF 抽屉控制 — 2 页面完全相同

showPdfDrawer / activePdfWorkId / pdfPreviewKey / openPdfDrawer / closePdfDrawer 在 MetadataReview 和 ClassificationReview 中完全相同，约 **120 行**

#### 🟢 #5: 工具函数散落各处

formatSize()（2处略有差异）/ formatDate()（2处）/ 搜索防抖 debouncedLoad()（3处手写实现），共约 **80 行**

### 1.3 决策建议

**推荐: Composable 为主 + 按需 Pinia（混合模式）**

理由：
1. 当前项目规模中等（11 页面），Composable 完全够用
2. 已有 usePagination 先例，团队熟悉此模式
3. 避免过早引入 Pinia 增加复杂度
4. 如果未来出现 >3 页面共享的可变状态，引入 Pinia 成本很低

### 1.4 立即提取的 Composables（按 ROI 排序）

| 序号 | 名称 | 职责 | 减少重复 | 优先级 |
|------|------|------|---------|--------|
| C-1 | `useQuarantine` | 隔离弹窗 + API 调用 | ~800 行 | **P0** |
| C-2 | `useSelectOptions` | 从 labels.js 生成 n-select 选项 | ~1000 行 | **P0** |
| C-3 | `useListPanel` | 左侧列表面板（折叠/调整宽度/布局样式） | ~500 行 | P1 |
| C-4 | `usePdfDrawer` | PDF 抽屉控制 | ~120 行 | P1 |
| C-5 | `useFormatUtils` | 格式化工具（日期/文件大小） | ~80 行 | P1 |
| C-6 | `useDebounceFn` | 通用防抖 | ~30 行 | P1 |
| C-7 | `useFilterSet` | 筛选器组合（状态+重置+URL构建） | ~450 行 | P2 |
| C-8 | `useContentPreview` | 内容预览（加载/搜索高亮/截取） | ~150 行 | P2 |

**总预估收益**: 减少 **~3200 行**重复代码（占 views/ 代码量的 **55%**）

### 1.5 不引入 Pinia 的前提条件（监控指标）

如果以下任一条件成立，应在下一迭代引入 Pinia：
- 出现 >=3 个页面需要读写同一份可变状态
- 需要服务端推送状态更新（WebSocket/SSE）
- 需要跨标签页状态同步

---

## §2 盲区 B-2: 路由架构审计

### 2.1 现状清单

11 个路由 | **懒加载率 100%** | **嵌套层级 0**（扁平结构）

问题：
- 仅 `/discovery` 有 name 和 meta（其余 10 个路由均无）
- 无 404 兜底路由
- 无 beforeEach/afterEach 守卫
- 单文件集中定义所有路由

### 2.2 必须改进 (P0)

1. **添加 404 处理**
```javascript
{ path: '/:pathMatch(.*)*', name: 'NotFound', component: () => import('../views/NotFound.vue') }
```

2. **为所有路由补充命名和元信息**
```javascript
{ path: '/works', name: 'Works', meta: { title: '文献库', group: 'management' } }
{ path: '/works/:id', name: 'WorkDetail', props: true, meta: { title: '文献详情', parent: 'Works' } }
```

### 2.3 强烈建议 (P1)

3. **添加基础守卫框架**（设置页面标题 + 未来扩展点）
4. **模块化拆分**（可选）：按 dashboard/works/review/analysis/error 分文件

### 2.4 WorkDetail 嵌套问题

**结论: 保持扁平结构**。理由：WorkDetail 有独特的三面板布局，与 Works 差异较大；通过 `meta.parent` 支持面包屑即可。

---

## §3 盲区 B-3: API 层 (api.js) 快速审计

### 3.1 现状快照

- 文件: `web/src/api.js`, 310 行, 50 个导出函数
- HTTP 客户端: 原生 fetch（非 axios）
- 类型定义: 无 TS/JSDoc
- 错误处理: 仅 `res.ok` 检查 + 抛出 Error

### 3.2 核心问题

| # | 问题 | 严重度 |
|---|------|-------|
| A-1 | 缺少 AbortController 支持（无法取消请求） | 高 |
| A-2 | 无超时保护（可能无限挂起） | 高 |
| A-3 | 错误处理简陋（无分类处理 401/403/500 等） | 中 |
| A-4 | 无请求去重（POST 可能重复提交） | 中 |

### 3.3 必须改进项 (P0)

#### A-1+A-2: AbortController + 超时

增强 `request()` 函数，增加:
- `signal` 参数支持（外部传入 AbortSignal）
- 默认 30s 超时（内部创建 AbortController.timeout(30000)）
- 自定义错误类: `ApiError` / `NetworkError` / `RequestCancelledError`
- TypeError 自动包装为 NetworkError

各页面在 `onUnmounted` 时调用 abort，避免内存泄漏和无效更新。

#### A-3: 错误分类处理

创建 `composables/useGlobalErrorHandler.js`:
- NetworkError -> "网络连接失败"
- ApiError(401) -> "登录已过期"
- ApiError(403) -> "没有权限"
- ApiError(500) -> "服务器内部错误"
- 其他 -> "操作失败 (status)"

在 `App.vue` 或 `main.js` 配置:
- `app.config.errorHandler` -- 捕获组件渲染错误
- `window.addEventListener('unhandledrejection')` -- 捕获 Promise 异常

### 3.4 建议改进项 (P1/P2)

- P1: GET 请求去重 (pending pool)；POST 幂等防抖 500ms
- P1: contentUrl/pdfUrl 改为异步统一接口
- P2: 迁移 TypeScript（视团队偏好）；迁移 axios（暂不需要）；引入缓存层

---

## §4 盲区 B-4: 错误边界与异常降级策略

### 4.1 当前现状

碎片化处理：
- Discovery/Topics 用 `window.alert()` -- 阻塞式
- 其他页面用 Naive UI `$message` 或静默失败 -- 不一致
- 全局: 无 errorHandler（未捕获的 Promise rejection 静默丢失）

### 4.2 三层防御体系设计

```
Layer 1: 组件内 try-catch（局部错误）
    ↓ re-throw
Layer 2: 全局 errorHandler（统一分类提示给用户）
    ↓ 兜底
Layer 3: ErrorBoundary UI（渲染崩溃时的 fallback）
```

**Layer 1 规范**: 所有 async 操作必须 try-catch，catch 块 re-throw（让全局 handler 接管显示）

**Layer 2 实现**: `useGlobalErrorHandler` composable + `app.config.errorHandler` + `unhandledrejection` 监听

**Layer 3 实现**: Vue 3 的 `onErrorCapture` 生命周期的 `ErrorBoundary.vue` 组件，显示"组件加载出错"+ 重试按钮

### 4.3 网络降级矩阵

| 场景 | 降级行为 |
|------|---------|
| 网络断连 | 显示离线 banner + 从内存读上次数据 |
| API 500 | 重试 1 次（指数退避），仍失败则提示稍后重试 |
| API 超时 >30s | 取消请求，提示"服务器响应超时" |
| 单接口失败 | 局部错误提示，不影响其他功能区 |
| PDF 加载失败 | 显示"预览不可用" fallback |

### 4.4 实施优先级

- **P0**: 创建 `useGlobalErrorHandler` (2h) + 配置全局捕获 (30min)
- **P1**: 创建 `ErrorBoundary.vue` (1h) + 消除现有 `alert()` 调用 (30min)
- **P2**: 离线检测+降级 banner (2h)

---

## §5 盲区 B-5: 性能优化预案

### 5.1 现状: 基础良好

主要列表都有服务端分页 / 搜索有 300ms debounce / v-for 正确使用 key / PDF Web Worker / 路由懒加载 / usePagination composable

### 5.2 高风险场景

| # | 场景 | 问题 |
|---|------|------|
| PF-1 | Duplicates.vue | 一次性加载全部去重组，无分页 |
| PF-2 | PDF 首屏加载 | 同步 import pdfjs-dist (~500KB gzipped) |
| PF-3 | MetadataReview 高亮 | 12000 字符正则替换，每次输入立即重算 |
| PF-4 | WorkDetail 列表 | 100 条/页，DOM 节点 500-800 |

### 5.3 优化方案

#### P0 (投入小收益大，建议立即做)

1. **Duplicates 前端分页** -- 30-60 min，彻底解决去重页卡顿
2. **pdfjs-dist 动态 import()** -- 15 min，首屏快 500ms-1s
3. **MetadataReview 高亮 debounce** -- 20 min，搜索流畅

#### P1 (下一个迭代)

4. WorkDetail 列表降至 30-50 条 (5min)
5. 筛选器统一下 debounce 150ms (30min)
6. isDuplicateSha 改为 computed 缓存 (10min)
7. PDF 文档 LRU 缓存最近 3-5 个 (1h)

#### P2 (等遇到问题再做)

- vue-virtual-scroller 虚拟滚动（仅当单页 >200 条且无法分页时）
- shallowRef / KeepAlive / Bundle 分析

### 5.4 性能基线测试

提供浏览器 console 脚本，用于量化 DOM 节点数、列表行数、加载耗时。建议每次重要变更前后跑一次并记录。

---

## §6 盲区 B-6: 可访问性 (a11y) 基线审计

### 6.1 基线评分: 4.5/10

| 维度 | 得分 |
|------|------|
| 键盘导航 | 3/10 |
| 屏幕阅读器 | 4/10 |
| 颜色对比度 | 6/10 |
| 语义化 HTML | 5/10 |

### 6.2 核心发现

**好消息**: 选对了技术栈（Vue3 + Naive UI 都对 a11y 友好）；无严重反模式；主文本对比度充足

**主要差距**:

| # | 问题 | 严重度 | 修复成本 |
|---|------|-------|---------|
| A11Y-1 | 零 ARIA 标签（图标按钮无描述） | P0 | 低 (2-3h) |
| A11Y-2 | 自定义可点击元素无键盘支持 | P0 | 低 (2h) |
| A11Y-3 | Modal 无焦点陷阱 | P0 | 中 (2h) |
| A11Y-4 | 表格 th 缺 scope | P0 | 低 (1h) |
| A11Y-5 | 警告色对比度不足 (#9a6700=4.3:1, 要求 4.5:1) | P1 | 15min |
| A11Y-6 | label 与 input 未 for/id 关联 | P1 | 3h |
| A11Y-7 | 无 aria-live 区域（动态内容变化不通知） | P1 | 2h |
| A11Y-8 | 缺"跳转到主内容"链接 | P1 | 30min |

### 6.3 改进路线图

**Phase 1 快速修复 (1-2天)**: 目标基线 4.5 -> 6.0
- 给所有图标按钮加 aria-label
- 表格 th 加 scope
- 创建 useFocusTrap composable 应用于 Modal
- 修复警告色为 #8B6500
- 添加跳转到主内容链接

**Phase 2 中等投入 (3-5天)**: 目标 6.0 -> 7.5，达到 WCAG 2.1 AA 基本合规
- 完善语义化结构 (header/section/aside)
- 表单 label-for 关联 + aria-required
- aria-live 区域通知数据变化
- 键盘交互增强 (列表 Enter/Space 打开)
- 颜色对比度全面审查
- 引入 axe-core 自动化测试

**Phase 3 持续优化**: 接近 AAA 级别（高对比度主题 / 减弱动画 / 多感官支持 / 用户测试）

---

## §7 三个线框疑问的解决方案

### Q1: 左侧流程面板宽度是否够用？

**疑问**: 当前 240-280px 能否容纳中文文字？Localization 余量？

**解决方案**:

| 参数 | 原方案值 | **调整后** | 理由 |
|------|---------|-----------|------|
| 最小宽度 | 240px | **260px** | "元数据审核"(5字x16px=80px)+图标+padding 约240px，留20px余量 |
| 默认宽度 | 260px | **280px** | 舒适阅读宽度 |
| 最大宽度 | 280px | **320px** | Localization 余量 ("Metadata Review" 约120px + padding) |
| 用户调整 | 未明确 | **支持 ResizeHandle 拖拽** | 用户可自行调到满意宽度 |

CSS 变量定义:
```css
:root {
  --sidebar-min-width: 260px;
  --sidebar-default-width: 280px;
  --sidebar-max-width: 320px;
}
```

### Q2: 三面板 PDF 侧栏 420px 固定宽度是否合理？

**疑问**: 小屏幕下是否会挤压主内容？ResizeHandle 是否保留？

**解决方案**: 采用响应式规则 + 保留拖拽

```css
/* PDF Drawer 宽度响应式规则 */
:root {
  --pdf-drawer-width-desktop: 420px;   /* >=1200px */
  --pdf-drawer-width-tablet: 340px;     /* 768px-1199px */
  --pdf-drawer-width-mobile: 100vw;     /* <768px: 全屏 overlay */
}

/* 断点切换 */
@media (max-width: 1199px) {
  .pdf-drawer { width: var(--pdf-drawer-width-tablet); }
}
@media (max-width: 767px) {
  .pdf-drawer {
    width: var(--pdf-drawer-width-mobile);
    position: fixed;
    inset: 0;
    z-index: 1000;
  }
}
```

**关于 ResizeHandle**: 明确保留 MetadataReview 已有的 ResizeHandle 实现。新的双面板 Layout 组件应内置可选的 resize 功能，拖拽范围限制为 `[min-width, max-width]`（如上表定义）。

### Q3: 顶部 Tab 栏 vs 左侧导航的功能重叠

**疑问**: 两套导航的关系是什么？

**解决方案**: 明确分工 -- 左侧放"流程链"，顶部放"非流程页面"

布局示意:
```
+---------------------------------------------------+
| 顶部 Tab: [总览] [文献库] [主题] [发现] [收件箱]     |  <- 非流程页面 + 快捷方式
+------+--------------------------------------------+
|      |                                            |
| 左侧 |              主内容区                        |
| 流程链|                                           |
|      |                                            |
| .主题闸门 |                                          |
| .发现检索 |                                         |
| .收件箱  |                                           |
| .采集审核|                                           |
| .分类审核|                                           |
| .元数据审核|                                          |
|      |                                            |
+------+--------------------------------------------+
```

**分工规则**:

| 区域 | 包含项 | 说明 |
|------|--------|------|
| **左侧导航** (流程链) | 主题闸门 -> 发现检索 -> 收件箱 -> 采集审核 -> 分类审核 -> 元数据审核 | 只放知识闭环的主流程节点，保持线性顺序 |
| **顶部 Tab** | 总览 / 文献库 / 主题管理 / 发现检索* / 收件箱* / 去重 / 关系图 | 非流程页面 + 流程节点的快捷入口 |
| **重叠项处理** | 发现检索、收件箱同时在两侧出现 | 顶部是"快捷入口"（点击直接跳转），左侧是"上下文位置"（高亮当前所在环节） |

**交互细节**:
- 当用户位于某个流程节点时，左侧对应项高亮（粗体或背景色）
- 顶部 Tab 的对应项也高亮（如下划线或颜色变化）
- 点击顶部 Tab 跳转后，左侧自动滚动到对应位置（如需要）
- 左侧导航支持折叠（折叠后只显示图标，tooltip 显示名称）

**额外可选项 B**: 如果觉得两套导航仍然冗余，可以采用合并方案 -- 将顶部 Tab 简化为只剩"面包屑"形式（如: `总览 > 文献库 > 元数据审核`），不再做平级 Tab 切换。这样左侧成为唯一的主导航，顶部只负责显示当前位置。

判断依据: 如果用户主要在流程链中工作，合并方案更清晰；如果用户经常在不同功能间跳跃，保留两套导航更方便。（**保留此决策到实施阶段根据实际使用反馈确定**）

---

## §8 整合后的完整实施蓝图 (v2.0)

### 8.1 Phase 总览（含新增的 Phase 0 和 Phase 5）

```
Phase 0 [新增]: 基础设施加固 (B-2/B-3/B-4 的 P0 项)
    |
    v
Phase 1: 设计令牌落地 (原方案的 P0-1)
    |
    v
Phase 2: 核心组件提取 + Composable 提取 (原方案 P0-2,3 + P1-4~7 + 本件 C-1~C-6)
    |
    v
Phase 3: 布局统一 + 双面板重构 (原方案 P2-8~10 + 本件 Q1/Q2 方案)
    |
    v
Phase 4: 体验优化 (原方案 P2-11 + P3 + 本件 B-5/B-6 的 Phase 1)
    |
    v
Phase 5 [新增]: 合规储备 (B-6 的 Phase 2 + 性能监控 + 自动化测试)
```

### 8.2 各 Phase 详细任务与验收标准

#### Phase 0: 基础设施加固（预计 2-3 天）

目标: 为后续重构打地基，解决阻塞性问题

| 任务 ID | 任务 | 来源 | 工作量 | 验收标准 |
|---------|------|------|--------|---------|
| F0-1 | api.js 增加 AbortController + 超时 | B-3 A-1,A-2 | 2h | 所有接口支持 signal 参数；默认 30s 超时 |
| F0-2 | 创建 useGlobalErrorHandler + 全局配置 | B-4 Layer2 | 2.5h | app.config.errorHandler 已配置；alert() 已消除 |
| F0-3 | 路由补充 404 + 命名 + meta | B-2 R-1,R-2,R-3 | 1.5h | 无效路径显示 404 页面；所有路由有 name/meta.title |
| F0-4 | 创建 ErrorBoundary.vue 组件 | B-4 Layer3 | 1h | 组件渲染崩溃时显示 fallback UI 而非白屏 |
| F0-5 | 路由守卫框架 (beforeEach 设置标题) | B-2 R-4 | 30min | 页面标题自动根据路由 meta 更新 |

**验收 checklist**:
- [ ] 访问 `/invalid-path` 看到 404 页面（非空白）
- [ ] 浏览器标签页标题随路由变化
- [ ] 故意在组件中 throw Error，看到 ErrorBoundary fallback 而非白屏
- [ ] 断网环境下调用 API，看到友好的网络错误提示（非 alert）

---

#### Phase 1: 设计令牌落地（预计 1 天，来自原方案 P0-1）

| 任务 | 验收标准 |
|------|---------|
| 在 AppLayout.vue `:root` 定义完整 CSS 变量集 | 浏览器 DevTools 可见所有变量 |
| 替换前 3 个高频硬编码色值为变量引用 | 视觉无变化，代码中使用 var(--xxx) |
| 创建 tokens 文档（含色板预览） | docs/ 下有 design-tokens.md |

注意: 此阶段零业务风险，纯 CSS 替换。

---

#### Phase 2: 核心组件提取 + Composable 提取（预计 5-8 天）

**2a. UI 组件提取（来自原方案 P0-2,3 和 P1-4~7）**:

| 序号 | 组件 | 页面数 | 工作量 |
|------|------|--------|--------|
| UI-1 | StatusBadge | 6 | 2h |
| UI-2 | ConfirmDialog | 4 | 2h |
| UI-3 | ReviewBar | 4 | 3h |
| UI-4 | EmptyState | 7 | 1.5h |
| UI-5 | KeyValueTable | 4 | 2h |
| UI-6 | SectionToggle | 4 | 1.5h |

**2b. Composable 提取（来自本件 B-1 C-1~C-6）**:

| 序号 | Composable | 减少重复 | 工作量 |
|------|-----------|---------|--------|
| C-1 | useQuarantine | ~800 行 | 3h |
| C-2 | useSelectOptions | ~1000 行 | 4h |
| C-3 | useListPanel | ~500 行 | 3h |
| C-4 | usePdfDrawer | ~120 行 | 1.5h |
| C-5 | useFormatUtils | ~80 行 | 1h |
| C-6 | useDebounceFn | ~30 行 | 1h |

**验收 checklist**:
- [ ] QUARANTINE_REASONS 定义只在 composables/useQuarantine.js 出现一次（Grep 验证）
- [ ] PRIMARY_DOC_TYPE_OPTIONS 只在一处定义
- [ ] npm run build 通过（0 error 0 warning）
- [ ] pytest 509 passed / healthcheck 五项全零（回归验证）
- [ ] 手工遍历 11 个页面，视觉无 regression

---

#### Phase 3: 布局统一 + 双面板重构（预计 3-5 天）

**3a. Modal 统一（原方案 P2-8）**:
自定义 Modal -> n-modal 替换（4 种->1 种）；统一 preset="card" + title prop

**3b. PaginationNav 统一（原方案 P2-9）**:
手写分页 -> n-pagination 或统一 PaginationNav 组件

**3c. 双面板布局标准化（原方案 P2-10 + 本件 Q1/Q2）**:
- 创建 `components/Layout/DualPanelLayout.vue`
- 内置 ResizeHandle（拖拽范围: sidebar 260-320px, detail 自适应）
- PDF Drawer 第三面板响应式规则（桌面 420px / 平板 340px / 手机 overlay）
- 左侧导航实现（流程链 + 折叠 + tooltip + aria-label）

**验收 checklist**:
- [ ] Modal 打开时焦点陷阱生效（Tab 不跳出）
- [ ] 双面板可拖拽调整宽度，松手后不闪烁
- [ ] 缩小浏览器窗口至 768px 以下，PDF Drawer 变为全屏 overlay
- [ ] 键盘 Tab 导航顺序合理（侧栏 -> 主内容 -> 详情）
- [ ] npm build 通过

---

#### Phase 4: 体验优化（预计 2-3 天）

| 任务 | 来源 | 工作量 | 验收标准 |
|------|------|--------|---------|
| 交互反馈统一（message/dialog 替代 alert） | 原方案 P2-11 | 1h | Grep "alert(" 结果为 0 |
| 响应式补全（4 页缺失 media query） | 原方案 P3 | 2h | 移动端模拟器测试通过 |
| 国际化（PDF drawer 英文->中文） | 原方案 P3 | 1h | PDF 相关 UI 无英文残留 |
| Duplicates 前端分页 | 本件 PF-1 | 1h | 100+ 组时页面不卡顿 |
| pdfjs-dist 动态导入 | 本件 PF-2 | 15min | 首屏 Network 面板无 pdfjs-dist |
| MetadataReview 高亮 debounce | 本件 PF-3 | 20min | 大文本搜索输入不卡 |
| a11y Phase 1 快速修复 | 本件 B-6 | 6h | axe-core 扫描 P0 问题清零 |
| WorkDetail 列表数量调优 | 本件 PF-4 | 5min | 列表 DOM 节点 <400 |

**验收 checklist**:
- [ ] Grep "alert(" 匹配数为 0（仅允许在 test 文件中出现）
- [ ] Lighthouse Performance score > 90（本地开发环境）
- [ ] axe-core DevTools 扫描 0 个 critical + serious 违规
- [ ] 仅键盘操作可完成"打开文献库 -> 筛选 -> 点开详情"主流程

---

#### Phase 5: 合规储备（可选，预计 3-5 天）

目标: 达到 WCAG 2.1 AA 基本合规 + 建立性能监控基线

| 任务 | 来源 | 工作量 |
|------|------|--------|
| a11y Phase 2（语义化 / 表单关联 / aria-live / 键盘增强 / 颜色审查） | 本件 B-6 | 12h |
| 引入 axe-core 自动化测试（vitest 集成） | 本件 B-6 | 4h |
| 性能基线记录 + 监控脚本 | 本件 PF | 2h |
| Bundle 分析报告 | 本件 PF | 1h |
| Vite code splitting 优化（如有必要） | 本件 PF | 2h |

**触发条件**: Phase 4 完成后，团队有余力时启动。不阻塞主流程。

---

### 8.3 关键决策汇总（不确定的已标注为可选项）

| 决策点 | 推荐 | 可选项 | 决策依据 |
|--------|------|--------|---------|
| 状态管理模式 | **Composable 为主** | 未来按需引入 Pinia | 当前规模足够，引入成本低 |
| 路由结构 | **保持扁平** | 嵌套（需评估布局共享） | WorkDetail 与 Works 布局差异大 |
| HTTP 客户端 | **保持 fetch** | 迁移 axios (P2) | fetch 够用，减少依赖 |
| 顶部导航 | **保留两套** | 合并为面包屑-only | 用户跨功能跳跃频率待观察 |
| TypeScript | **暂不迁移** | 下个迭代评估 | 工作量 vs 收益不成比例 |
| 虚拟滚动 | **暂不引入** | Duplicates >200 条时再考虑 | 当前分页足够 |
| KeepAlive | **暂不启用** | 切换频率高时考虑 | 数据可能已变化需刷新 |
| a11y 目标 | **Phase 1 到 6 分** | Phase 2 到 7.5 分 (AA 合规) | 学术工具的基本可用性要求 |

---

### 8.4 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| Phase 2 组件提取导致视觉 regression | 中 | 高 | 每提取一个组件后立即 visual diff 对比 |
| Composable 提炼改变了响应式依赖链 | 低 | 中 | 保持 ref/reactive 语义不变，只搬位置 |
| 设计令牌替换遗漏某些内联样式 | 中 | 低 | Grep `#[0-9a-fA-F]{3,6}` 找漏网之鱼 |
| pdfjs-dist 动态导入导致首次打开 PDF 延迟 | 高 | 低 | 显示 loading skeleton，用户体验可接受 |
| a11y 修改破坏现有交互逻辑 | 低 | 中 | 每次修改后键盘-only 回归测试 |

---

## §9 附录

### A. 文档版本历史

| 版本 | 日期 | 作者 | 变更 |
|------|------|------|------|
| v1.0 | 2026-07-01 | 原审计文档 | 8 页面 UI 审计 + 设计令牌 + 12 候选组件 + 4 Phase 路线图 |
| **v2.0 (本件)** | **2026-07-01** | **补充件** | **6 盲区分析 + 3 线框疑问解答 + 整合蓝图 Phase 0-5** |

### B. 相关文档索引

| 文档 | 位置 | 关系 |
|------|------|------|
| 原审计方案 v1.0 | `docs/superpowers/reviews/2026-07-01-frontend-design-audit.md` | 本件的"上游"文档 |
| V1.3 交接文档 | `docs/superpowers/plans/2026-06-30-v1.3-handoff.md` | 项目上下文 |
| FUTURE_WORK_PLAN | `FUTURE_WORK_PLAN.md` | 后续任务池 |

### C. 术语表

| 术语 | 解释 |
|------|------|
| Composable | Vue 3 Composition API 的可复用逻辑单元（类似 React Hook） |
| Design Token | 设计令牌，UI 的原子化配置变量（颜色/圆角/间距等） |
| Focus Trap | 焦点陷阱，将 Tab 键限制在指定区域内（如 Modal） |
| WCAG 2.1 AA | Web 内容可访问性指南 2.1 版本的 A 级合规标准 |
| AbortController | 浏览器原生 API，用于取消 fetch/XMLHttpRequest 请求 |
| ErrorBoundary | 错误边界，捕获子组件渲染崩溃并显示 fallback UI |
| LRU Cache | 最近最少使用缓存，淘汰最久未访问的数据 |
