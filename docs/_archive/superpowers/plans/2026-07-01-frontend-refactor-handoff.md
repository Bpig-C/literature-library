# 前端重构 — 实施交接指令（Handoff Brief）

> **文档性质**: 本文档是给「本地实施模型」的任务说明书，同时也是「总控审核模型」的验收依据。
>
> **版本**: v2.0-final | **日期**: 2026-07-01
>
> **角色分工**:
> - 🤖 **实施者（你/本地模型）**: 阅读本指令，按 Phase 顺序逐项实施代码变更，每完成一个 Phase 提交一次。
> - 🔍 **审核者（WorkBuddy 总控模型）**: 对每个 Phase 的产出进行独立审计，给出通过/打回/附条件通过的结论。

---

## §0 项目快照与技术约束

### 技术栈（不可变更）

| 项 | 版本 | 说明 |
|----|------|------|
| Vue | 3.5.34 | Composition API + `<script setup>` |
| Naive UI | 2.44.1 | UI 组件库，保持使用 |
| Vue Router | 4.6.4 | 路由 |
| Vite | 8.0.12 | 构建工具 |
| pdfjs-dist | 6.0.227 | PDF 渲染 |
| JavaScript | 纯 JS（无 TypeScript）| **不引入 TS** |
| 状态管理 | 无（纯 ref/reactive）| **暂不引入 Pinia**，用 Composable |
| CSS | 原生 + CSS 变量 | **不引入 Tailwind/SASS** |

### 关键文件地图

```
web/src/
├── main.js                          # 入口
├── App.vue                          # 根组件
├── router.js                        # 路由配置（~60行）
├── api.js                           # API 层（~310行 / ~50接口）
├── labels.js                        # 标签/常量定义
├── composables/
│   └── usePagination.js             # 唯一已有 Composable
├── components/
│   ├── AppLayout.vue                # 全局布局（侧边栏+顶栏+内容区）
│   ├── ResizeHandle.vue             # 拖拽调整手柄
│   └── PdfPreviewDrawer.vue         # PDF 预览抽屉
└── views/
    ├── Dashboard.vue                # 总览仪表盘
    ├── Works.vue                    # 文献库（主列表）
    ├── WorkDetail.vue               # 文献详情
    ├── TopicsReview.vue             # 主题闸门
    ├── DiscoveryReview.vue          # 发现检索
    ├── InboxReview.vue              # 收件箱
    ├── IntakeReview.vue             # 采集审核
    ├── ClassificationReview.vue     # 分类审核
    ├── MetadataReview.vue           # 元数据审核（最复杂，~900行）
    ├── Duplicates.vue               # 去重
    └── Relations.vue                # 关系图
```

### 必读输入文档（按顺序）

| 序号 | 文件路径 | 用途 | 必读性 |
|------|---------|------|--------|
| 1 | `docs/superpowers/reviews/2026-07-01-frontend-design-audit.md` | 原审计方案（UI/令牌/组件/P0-P3） | **必须** |
| 2 | `docs/superpowers/reviews/2026-07-01-frontend-blindspot-supplement.md` | 盲区补充（状态管理/路由/API/错误/性能/a11y） | **必须** |
| 3 | `docs/superpowers/plans/2026-06-30--06-30-v1.3-handoff.md` | V1.3 交接上下文 | 参考 |

---

## §1 实施范围与边界

### ✅ 在范围内（必须做）

| 范围项 | 对应 Phase | 说明 |
|--------|-----------|------|
| 设计令牌（CSS 变量）落地到 `:root` | Phase 1 | 替换所有硬编码色值 |
| 公共 UI 组件提取（StatusBadge 等 6 个） | Phase 2 | 从各页面提取到 `components/` |
| Composable 提取（useQuarantine 等 6 个） | Phase 2 | 从各页面提取到 `composables/` |
| API 层增强（AbortController + 错误分类） | Phase 0 | 改造 `api.js` |
| 全局错误处理（errorHandler） | Phase 0 | 消除所有 `alert()` |
| 路由补全（404 + 命名 + beforeEach） | Phase 0 | 改造 `router.js` |
| 布局统一（Modal/Pagination/双面板） | Phase 3 | 统一交互模式 |
| a11y 快修（Phase 1 级别） | Phase 4 | 键盘导航 + ARIA 最小集 |
| 性能 P0（Duplicates 分页 + PDF 动态导入） | Phase 4 | 低投入高收益 |

### ❌ 明确不在范围内（禁止做）

| 禁止项 | 理由 | 如需做请先申请 |
|--------|------|---------------|
| 引入 TypeScript | 范围外，P2 可选项 | 单独评估 |
| 引入 Pinia / Vuex | 当前规模不需要 | 等跨页面状态超过 5 处再考虑 |
| 替换 fetch 为 axios | 无必要，fetch 够用 | P3 可选项 |
| 引入 Tailwind CSS | 与设计令牌方案冲突 | 不予批准 |
| 改后端 API | 本次纯前端重构 | 不涉及 |
| 修改 parser/collector/api/ 目录 | 后端代码，不动 | 不涉及 |
| 虚拟滚动（vue-virtual-scroller） | 当前数据量不需要 | 等单页 >200 条再启用 |
| KeepAlive 缓存 | 可能导致状态陈旧 | 等有明确需求再启 |
| 国际化 (i18n) | P3 可选项 | 单独规划 |
| WCAG AAA 合规 | 过度工程 | AA 即可（且在 P5） |

### ⚠️ 灰色地带（可选项，实施时自行决定但需记录）

| 可选项 | 建议 | 决策权 |
|--------|------|--------|
| 导航策略：保留两套 vs 合并面包屑 | 推荐保留两套 | 实施者自定，审核时不卡 |
| 选项常量是否抽到 `constants/` 目录 | 推荐 | 实施者自定 |
| 是否加 ESLint / Prettier 配置 | 推荐加 | 实施者自定 |
| ResizeHandle 是否封装为通用指令 | 可选 | 实施者自定 |

---

## §2 分阶段实施指令

### Phase 0: 基础设施加固（预计 2-3 天）

> **目标**: 在做任何 UI 改动前，先把地基打牢。这一步的改动是"无感"的——用户看不到界面变化，但系统更健壮。

#### 任务 0.1: API 层增强 (`web/src/api.js`)

**当前问题**:
- 无请求取消机制（用户快速切换页面时旧请求仍在跑）
- 无超时控制（请求可能永久挂起）
- 错误处理碎片化（每个调用方自己 catch）

**具体要求**:

1. 给核心 `request()` 函数增加三个能力：
   ```
   a) AbortController 支持：
      - 每个 GET 请求自动创建 AbortSignal
      - 返回 { data, cancel } 对象，调用方可主动 cancel
      - 页面卸载时（onUnmounted）自动 cancel 未完成请求

   b) 超时控制：
      - 默认 timeout = 30 秒
      - 可通过参数覆盖: request(url, { timeout: 5000 })
      - 超时抛出 TimeoutError（自定义错误类）

   c) 错误分类：
      - 新建 ApiError 类，包含: { code, message, status, detail }
      - code 枚举: NETWORK_ERROR | TIMEOUT | SERVER_ERROR(5xx) | CLIENT_ERROR(4xx) | PARSE_ERROR
      - 自动根据 response.status 和 error 类型分类
   ```

2. 保持向后兼容：现有的 `api.getWorks()` 等调用方式不变，内部升级即可。

3. 文件末尾导出错误类供全局 errorHandler 使用。

**验收标准**:
- [ ] 所有原有 API 调用无需修改即可正常工作
- [ ] 新增 `test-api-timeout.html` 或类似验证脚本证明超时机制生效
- [ ] `ApiError` 类可通过 `import { ApiError } from './api'` 导出
- [ ] 代码增量 ≤ 80 行

#### 任务 0.2: 全局错误处理 (`web/src/main.js` 或新建 `web/src/error-handler.js`)

**当前问题**:
- DiscoveryReview 用 `alert()` 报错
- 其他页面要么静默失败，要么用 `window.message`
- 无全局捕获机制

**具体要求**:

1. 创建 `useGlobalErrorHandler.js` Composable 或直接在 `main.js` 中配置：
   ```javascript
   // 三层防御
   // L1: app.config.errorHandler — 捕获 Vue 渲染异常
   // L2: window.onerror + unhandledrejection — 捕获非 Vue 异步异常
   // L3: 封装 showError(error) 统一提示函数
   ```

2. `showError(error)` 行为规范：
   - ApiError → 根据 code 显示不同颜色/图标的消息
   - Error → 显示红色 "操作失败: {message}"
   - 未知错误 → 显示橙色 "发生了未知错误"
   - **绝对不再使用 alert() / confirm() / prompt()**

3. 全局搜索并替换所有 `alert(` 调用为 `showError(`。

**验收标准**:
- [ ] `grep -r "alert(" web/src/` 结果为空（注释中的除外）
- [ ] `grep -r "confirm(" web/src/` 结果为空
- [ ] 手动触发一个 API 500 场景时看到友好提示而非白屏/alert
- [ ] 代码增量 ≤ 60 行（不含替换工作）

#### 任务 0.3: 路由补全 (`web/src/router.js`)

**当前问题**:
- 仅 1/11 路由有 name 和 meta
- 无 404 兜底路由
- 无路由守卫
- 路由懒加载未全面应用

**具体要求**:

1. 给每个路由补充 `name` 和 `meta`：
   ```javascript
   meta: {
     title: '页面标题',        // 用于浏览器标签
     icon: 'icon-name',        // 侧边栏图标
     parent: null,            // 父路由 name（用于面包屑）
     group: '文献' | '流程' | '系统',  // 侧边栏分组
   }
   ```

2. 添加 404 兜底：
   ```javascript
   {
     path: '/:pathMatch(.*)*',
     name: 'not-found',
     component: () => import('./views/NotFound.vue'),  // 需新建此组件
   }
   ```

3. 新建 `NotFound.vue`: 简单的 404 页面，带"返回首页"按钮。

4. 添加 `beforeEach` 守卫框架（目前只做日志，不加权限逻辑）：
   ```javascript
   router.beforeEach((to, from) => {
     console.log(`[Router] ${from.path} -> ${to.path}`)
     // 未来可在此加入权限检查、未保存确认等
   })
   ```

5. 检查所有路由都使用了懒加载 `() => import(...)`。

**验收标准**:
- [ ] 访问 `/nonexistent-path` 显示 404 页面而非白屏
- [ ] 每个路由都有 name，可用 `router.push({ name: 'works' })` 导航
- [ ] 浏览器标签显示正确的页面标题（通过路由守卫设置 document.title）
- [ ] 代码增量 ≤ 100 行（含 NotFound.vue）

#### Phase 0 交付物

```
git add web/src/api.js web/src/error-handler.js web/src/router.js web/src/views/NotFound.vue
git commit -m "feat(frontend): Phase 0 - 基础设施加固

- api.js: 增加 AbortController/超时/ApiError 分类
- 新增 error-handler.js: 全局三层错误捕获
- router.js: 路由命名/meta/404/beforeEach
- 新增 NotFound.vue: 404 兜底页面
- 消除所有 alert() 调用"
```

---

### Phase 1: 设计令牌落地（预计 1 天）

> **目标**: 建立 CSS 变量体系，替换所有硬编码色值。这是纯视觉改动，零功能风险。

参考文档: 原审计方案 §3 "设计令牌体系"

#### 任务 1.1: 在 `AppLayout.vue` 的 `:root` 中注入设计令牌

将原审计方案中定义的全部 CSS 变量写入。关键变量示例：

```css
:root {
  /* === 语义色 === */
  --color-ok: #16a34a;
  --color-warn: #d97706;
  --color-bad: #dc2626;
  --color-info: #2563eb;
  --color-neutral: #6b7280;
  --color-selected: #2563eb;
  --color-fix: #7c3aed;        /* accent/强调色 */
  --color-purple: #7c3aed;

  /* === 中性色阶梯 === */
  --gray-50: #f9fafb;
  --gray-100: #f3f4f6;
  /* ... 到 gray-900 */

  /* === 圆角阶梯 === */
  --radius-xs: 2px;
  --radius-sm: 4px;
  --radius-md: 6px;
  --radius-lg: 8px;
  --radius-xl: 10px;
  --radius-full: 999px;

  /* === 阴影阶梯 === */
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.05);
  --shadow-md: 0 4px 6px rgba(0,0,0,0.07);
  --shadow-lg: 0 10px 15px rgba(0,0,0,0.1);
  --shadow-focus: 0 0 0 3px rgba(37,99,235,0.15);

  /* === 间距阶梯 === */
  --space-1: 4px;
  --space-2: 8px;
  /* ... 到 space-8: 32px */

  /* === 字体排版 === */
  --font-xs: 0.75rem;     /* 11px */
  --font-sm: 0.875rem;    /* 14px */
  --font-base: 1rem;      /* 16px */
  --font-lg: 1.125rem;    /* 18px */
  --font-xl: 1.25rem;     /* 20px */
  --font-2xl: 1.375rem;   /* 22px */

  /* === 动画过渡 === */
  --transition-fast: 0.1s ease;
  --transition-normal: 0.15s ease;
  --transition-slow: 0.2s ease;
}
```

**注意**: 以上只是示例，完整变量表以原审计方案 §3 为准。

#### 任务 1.2: 逐页替换硬编码色值

对每个 `.vue` 文件执行以下操作：

1. 扫描 `<style>` 段中的 `#xxxxxx` 色值和 `rgb(...)` 色值
2. 映射到对应的 CSS 变量
3. 替换

**优先级顺序**（从高频到低频）：
1. `#eef5ff`（出现 7 次）→ `var(--gray-50)` 或自定义 hover 色
2. `#f8fafc`（出现 5 次）→ `var(--gray-50)`
3. `#374151` / `#3a4250`（文字色）→ `var(--gray-700)` 或 `var(--text-primary)`
4. `#6b7280`（次要文字）→ `var(--gray-500)` 或 `var(--text-secondary)`
5. DiscoveryReview 的紫色系 → `var(--color-fix)` / `var(--color-purple)`
6. 其余散落色值逐一映射

**特别处理 - DiscoveryReview.vue 的紫色系**:
- 该页面定义了自己的紫色主题色（#7c3aed 系列），与全局 accent 色脱节
- 替换方案：保留语义意图，改用 `var(--color-fix)` 作为主色
- 如果该页面确实需要独立的紫色主题（比如表示"发现"流程），可以定义 `--color-discovery: #7c3aed` 作为页面级变量

#### 任务 1.3: 验证替换后的视觉效果

```bash
cd web && npm run build   # 必须通过
npm run dev              # 目视检查每个页面
```

**验收标准**:
- [ ] `<style>` 段中的硬编码色值 ≤ 5 个（允许遗留的特殊场景）
- [ ] `npm run build` 通过无报错
- [ ] 每个页面目视检查：颜色与替换前**视觉一致或更统一**
- [ ] DiscoveryReview 的紫色系已纳入变量体系（可以是全局变量或页面级变量）

#### Phase 1 交付物

```
git commit -m "feat(frontend): Phase 1 - 设计令牌落地

- AppLayout.vue: 注入完整 CSS 变量体系（色/圆角/阴影/间距/字体/动画）
- 替换 11 个页面的硬编码色值为 CSS 变量引用
- DiscoveryReview 紫色主题纳入变量体系"
```

---

### Phase 2: 核心组件与 Composable 提取（预计 5-8 天）

> **目标**: 消除重复代码，建立可复用的组件/工具库。这是工作量最大的 Phase。

参考文档: 盲区补充 §1（状态管理 TOP 5 重复模式）+ 原审计方案 §4（公共组件清单）

#### 任务 2.1: 提取 Composable（优先级从高到低）

##### 2.1.1 `useQuarantine.js` — 隔离操作 [ROI 最高]

**来源**: Works, WorkDetail, MetadataReview, ClassificationReview 中几乎相同的代码块

**抽取内容**:
```javascript
// web/src/composables/useQuarantine.js
export function useQuarantine() {
  const QUARANTINE_REASONS = [...]  // 统一原因列表
  const showQuarantineModal = ref(false)
  const quarantiningWorkId = ref(null)

  function openQuarantine(workId) { ... }
  function confirmQuarantine(reason) { ... }

  return {
    QUARANTINE_REASONS, showQuarantineModal, quarantiningWorkId,
    openQuarantine, confirmQuarantine,
  }
}
```

**要求**:
- 从 MetadataReview（最完整的实现）作为蓝本
- 参数化 API 调用部分（因为不同页面的隔离接口可能略有差异）
- 4 个消费页面改为 `const { openQ, confirmQ, ... } = useQuarantine()`

**预计减少重复**: ~600 行（4 × 150 行 → 150 行 + 4 × 15 行调用）

##### 2.1.2 `useSelectOptions.js` / `constants/options.js` — 选项常量

**来源**: PRIMARY_DOC_TYPE_OPTIONS, READING_LANE_OPTIONS 等在 5+ 个文件重复

**抽取内容**:
```javascript
// web/src/constants/options.js（纯静态选项放这里）
export const DOC_TYPE_OPTIONS = [...]
export const READING_LANE_OPTIONS = [...]
export const PUBLICATION_STATUS_OPTIONS = [...]
export const INGESTION_STATE_OPTIONS = [...]
export const PRIORITY_OPTIONS = [...]
export const QUARANTINE_REASON_OPTIONS = [...]
```

**要求**:
- 这些选项都是纯静态的（不从 API 获取），放 `constants/` 目录
- 所有消费页面改为 import

**预计减少重复**: ~800 行

##### 2.1.3 `useDualPanel.js` — 双面板布局

**来源**: IntakeReview, InboxReview, Duplicates, MetadataReview, ClassificationReview

**抽取内容**:
```javascript
export function useDualPanel(defaultListWidth = 480) {
  const listWidth = ref(defaultListWidth)
  const listCollapsed = ref(false)
  const detailWidth = computed(...)
  // ... toggle, resize 等
}
```

**要求**:
- 包含 ResizeHandle 的绑定逻辑
- 默认宽度可配置（不同页面可能需要不同的默认比例）
- 提供 `layoutStyle` computed 供模板使用

**预计减少重复**: ~350 行

##### 2.1.4 `usePdfDrawer.js` — PDF 抽屉控制

**来源**: MetadataReview, ClassificationReview

**抽取内容**:
```javascript
export function usePdfDrawer() {
  const showPdfDrawer = ref(false)
  const activePdfWorkId = ref(null)
  const pdfPreviewKey = ref(0)
  // open/close/toggle
}
```

**预计减少重复**: ~100 行

##### 2.1.5 `useFormatUtils.js` — 格式化工具

**来源**: formatSize(), formatDate() 散落 2+ 处，debounce 手写 3 处

**抽取内容**:
```javascript
export function formatSize(bytes) { ... }
export function formatDate(dateStr) { ... }
export function useDebounce(fn, delay = 300) { ... }
```

**要求**:
- formatDate 统一为一种格式（推荐 ISO-like: `YYYY-MM-DD HH:mm`）
- debounce 返回 `{ result, cancel, flush }` 以便手动控制

**预计减少重复**: ~80 行

##### 2.1.6 `useAsyncOperation.js` — 异步操作模式（可选但推荐）

**来源**: 多个页面的 loading/error/data 模式

**抽取内容**:
```javascript
export function useAsyncOperation(asyncFn) {
  const loading = ref(false)
  const error = ref(null)
  const data = ref(null)

  async function execute(...args) {
    loading.value = true
    error.value = null
    try {
      data.value = await asyncFn(...args)
    } catch (e) {
      error.value = e
    } finally {
      loading.value = false
    }
  }

  return { loading, error, data, execute, reset }
}
```

**这是可选的**——如果觉得过度抽象可以跳过。

#### 任务 2.2: 提取公共 UI 组件

参考原审计方案 §4 的组件清单，按以下顺序提取：

##### 2.2.1 `StatusBadge.vue` — 状态标签 [最常用]

**合并来源**:
- Works 的 n-badge
- DiscoveryReview 的自定义 badge（绿/红/黄/灰）
- MetadataReview 的 status dot + text
- 各 Review 页面的状态列

**Props 接口**:
```javascript
defineProps({
  status: { type: String, required: true },  // 'approved' | 'rejected' | 'pending' | ...
  size: { type: String, default: 'medium' },  // 'small' | 'medium' | 'large'
  showDot: { type: Boolean, default: true },
})
```

**内置映射**: status → color/icon/label 的映射表（集中管理）

##### 2.2.2 `ReviewBar.vue` — 审核操作栏

**合并来源**: IntakeReview, InboxReview, MetadataReview, ClassificationReview 的顶部审核栏（通过/拒绝/跳过按钮组）

**Slots**:
```
<ReviewBar>
  <template #extra>...</template>  <!-- 页面特有的额外按钮 -->
</ReviewBar>
```

**Emits**: `@approve`, `@reject`, `@skip`, `@quarantine`

##### 2.2.3 `EmptyState.vue` — 空状态占位

**合并来源**: Dashboard, Works（搜索无结果）、DiscoveryReview（hits 为空）、各 Review（队列清空）

**Props**:
```javascript
defineProps({
  icon: { type: String, default: 'inbox' },
  title: { type: String, default: '暂无数据' },
  description: { type: String, default: '' },
  actionText: { type: String, default: '' },
})
```

**Emits**: `@action`

##### 2.2.4 `SearchHeader.vue` — 搜索头部

**合并来源**: Works, Duplicates, Topics 的搜索栏 + 筛选器组合

**特征**: 输入框 + 搜索按钮 + 高级筛选折叠

**Slots**: `#filters`（各页面筛选器不同）

##### 2.2.5 `ConfirmDialog.vue` — 确认对话框

**消除**: 各页面手写的 `n-modal` + 确认/取消按钮组合

**Props**: `title`, `message`, `confirmText`, `cancelText`, `type('warn'|'danger'|'info')`

**Emits**: `@confirm`, `@cancel`

#### 任务 2.3: 提取后验证

```bash
# 1. 构建检查
cd web && npm run build

# 2. 回归测试（目视）
npm run dev
# 逐页检查: Dashboard → Works → Topics → Discovery → Inbox → 各 Review → Duplicates → Relations

# 3. 功能验证
# - Works: 搜索/筛选/分页/隔离 操作正常
# - DiscoveryReview: 运行查询/hits 列表/审核操作 正常
# - MetadataReview: 双面板/PDF预览/审核操作 正常
```

**验收标准**:
- [ ] `npm run build` 通过
- [ ] 11 个页面功能无损（每个页面的核心操作走一遍）
- [ ] `views/` 目录总代码量比实施前 **减少 ≥ 25%**（目标是 55%，最低 25%）
- [ ] 新增 `components/` 和 `composables/` 的代码有清晰的 JSDoc 注释
- [ ] 没有"为了复用而复用"导致的抽象泄漏（即：消费代码不应比原来更难读懂）

#### Phase 2 交付物

```
git add web/src/composables/ web/src/components/ web/src/constants/
git commit -m "feat(frontend): Phase 2 - 核心组件与Composable提取

Composable:
- useQuarantine: 统一隔离操作(Works/WorkDetail/MetadataReview/ClassificationReview)
- useSelectOptions: 集中选项常量(DOC_TYPE/READING_LANE等5组)
- useDualPanel: 双面板布局逻辑(5页面共享)
- usePdfDrawer: PDF抽屉控制(2页面共享)
- useFormatUtils: 格式化工具(formatSize/formatDate/debounce)

UI Components:
- StatusBadge: 统一状态标签(替代各页面散落的badge实现)
- ReviewBar: 审核操作栏(通过/拒绝/跳过/隔离)
- EmptyState: 空状态占位
- SearchHeader: 搜索+筛选头部
- ConfirmDialog: 确认对话框

预估净减重复代码: ~2000行"
```

---

### Phase 3: 布局统一与双面板重构（预计 3-5 天）

> **目标**: 统一各页面的布局模式和交互范式，特别是双面板布局。

参考文档: 盲区补充 §7（线框疑问解答）+ 原审计方案 §5（双面板线框图）

#### 任务 3.1: 统一 Modal 使用规范

**现状问题**:
- 有些页面用 Naive UI 的 `useDialog()`
- 有些页面用模板内 `<n-modal>`
- 样式/动画/关闭行为不一致

**统一方案**:
1. **简单确认**（删除/隔离等危险操作）→ 用 `ConfirmDialog` 组件（Phase 2 已提取）
2. **表单编辑**（如隔离原因选择）→ 用模板内 `<n-modal>` + 统一的 header/footer 样式
3. **信息展示**（如详情查看）→ 用 `n-drawer`（右侧抽屉）替代 modal

**样式统一**:
```css
/* 所有 modal/drawer 统一圆角和阴影 */
.n-modal { --n-border-radius: var(--radius-lg); }
.n-drawer { --n-border-radius: var(--radius-lg); }
```

#### 任务 3.2: 统一分页组件使用

**现状**: 有的用 Naive UI `n-pagination`，有的手写简易分页。

**统一为**: 全部使用 `n-pagination`，统一 props：
```html
<n-pagination
  :page-count="totalPages"
  :page-size="pageSize"
  v-model:current="currentPage"
  :page-sizes="[10, 20, 50]"
  show-size-picker
  show-quick-jumper
/>
```

对于使用 `usePagination.js` 的页面，更新该 Composable 使其输出与上述 props 兼容。

#### 任务 3.3: 侧边栏导航规范化

参考盲区补充 §7 Q3 的解答：

**左侧导航结构**（流程链）:
```
📊 总览
📚 文献库
─── 流程 ───
🚦 主题闸门
🔍 发现检索
📥 收件箱
✅ 采集审核
📂 分类审核
📝 元数据审核
─── 工具 ───
🔄 去重
🕸️ 关系图
```

**顶部 Tab 结构**（快捷入口 + 非流程页高亮）:
```
[总览] [文献] [主题] [发现] [收件箱] [去重]
```

**分工**:
- 左侧 = 完整导航树 + 当前位置高亮
- 顶部 = 常用页面快捷跳转 + 面包屑（`总览 > 文献库 > 元数据审核`）

**实现要求**:
1. `AppLayout.vue` 中的侧边栏数据改为配置驱动（数组定义，便于后续扩展）
2. 顶部 Tab 栏的数据也从同一配置生成（取 subset）
3. 面包屑根据 `router.currentRoute.meta.parent` 自动生成

#### 任务 3.4: 双面板 Layout 组件（核心任务）

**新建 `components/DualPanelLayout.vue`**:

```vue
<template>
  <div class="dual-panel" :class="{ collapsed }">
    <!-- 左侧列表区 -->
    <div class="panel-list" :style="{ width: listWidth + 'px' }">
      <slot name="list" />
      <ResizeHandle @resize="onResizeList" direction="horizontal" />
    </div>

    <!-- 右侧详情区 -->
    <div class="panel-detail">
      <slot name="detail" />
    </div>

    <!-- 可选: 第三面板 (PDF) -->
    <PdfPreviewDrawer
      v-if="showPdf"
      :work-id="pdfWorkId"
      :width="pdfWidth"
    />
  </div>
</template>
```

**Props**:
```javascript
{
  defaultListWidth: { type: Number, default: 480 },
  minListWidth: { type: Number, default: 320 },
  maxListWidth: { type: Number, default: 600 },
  showPdf: { type: Boolean, default: false },
  pdfDefaultWidth: { type: Number, default: 420 },
}
```

**响应式规则**（来自盲区补充 Q2 解答）:
- 桌面 (>1200px): 双面板并列 + PDF 420px 侧栏
- 平板 (768-1200px): 双面板并列 + PDF 变为 overlay
- 手机 (<768px): 单面板 + 底部 sheet 式详情

**迁移计划**（按顺序）:
1. **MetadataReview**（最复杂的双面板，作为试点）
2. **ClassificationReview**（与 MR 结构相似）
3. **IntakeReview / InboxReview**（较简单的双面板）
4. **Duplicates**（如果有双面板）

每个页面迁移步骤:
1. 将列表区的 template 内容移入 `<template #list>`
2. 将详情区移入 `<template #detail>`
3. 删除页面内的双面板宽度/折叠相关代码（已被 Layout 组件内部处理）
4. 验证 ResizeHandle 拖拽功能正常

**验收标准**:
- [ ] 至少 2 个页面（MetadataReview + ClassificationReview）已迁移到 DualPanelLayout
- [ ] ResizeHandle 在两个方向都能拖拽
- [ ] 窗口缩小时不会出现布局崩坏
- [ ] PDF Drawer 在三面板模式下正常显示

#### Phase 3 交付物

```
git commit -m "feat(frontend): Phase 3 - 布局统一与双面板重构

- DualPanelLayout.vue: 通用双面板布局组件(含ResizeHandle集成)
- Modal/Drawer使用规范统一
- 分页组件全部标准化为n-pagination
- 侧边栏配置驱动化(支持分组/图标/高亮)
- 顶部Tab + 面包屑导航
- MetadataReview/ClassificationReview迁移至DualPanelLayout"
```

---

### Phase 4: 体验优化（预计 2-3 天）

> **目标**: 消除最后的用户体验痛点，为后续迭代打好基础。

#### 任务 4.1: 性能 P0（快速胜利）

##### 4.1.1 Duplicates.vue 分页
- **现状**: 可能一次性渲染所有去重组
- **改造**: 确保服务端分页已启用，前端每页显示 20 条
- **预计耗时**: 30 min

##### 4.1.2 PDF 动态导入
```javascript
// 改前
import PdfPreviewDrawer from './components/PdfPreviewDrawer.vue'

// 改后
const PdfPreviewDrawer = defineAsyncComponent(() =>
  import('./components/PdfPreviewDrawer.vue')
)
```
- **效果**: 首屏加载不再包含 PDFjs-dist（约 300KB gzipped）
- **预计耗时**: 15 min

##### 4.1.3 搜索防抖统一
- 将所有手写的 `setTimeout` 防抖替换为 `useDebounce`（Phase 2 已提取）
- 统一延迟时间: 300ms
- **预计耗时**: 20 min

#### 任务 4.2: a11y 快修（Phase 1 级别）

参考盲区补充 §6 的 a11y Phase 1 方案:

1. **键盘导航基础**:
   - 所有自定义可聚焦元素添加 `tabindex="0"`
   - Modal/Drawer 打开时焦点 trap（Naive UI 内置支持，确认已开启）
   - Esc 键关闭所有弹层

2. **ARIA 最小集**:
   - 所有图标按钮添加 `aria-label`（如: `aria-label="关闭"`）
   - 主要区域添加 landmark: `<header>`, `<nav>`, `<main>`, `<aside>`
   - 表格数据单元格关联表头（Naive UI NDataTable 已内置支持）

3. **焦点可见性**:
   ```css
   :focus-visible {
     outline: 2px solid var(--color-info);
     outline-offset: 2px;
   }
   ```

**不做的（留给 P5）**:
- 不做屏幕阅读器的深度测试（需要真实设备和用户）
- 不做 WCAG AA 全量对比度校验（工具自动化即可延后）
- 不做 keyboard shortcut 系统（超出范围）

#### 任务 4.3: 加载态与骨架屏（可选）

对于加载时间超过 500ms 的操作，考虑添加骨架屏或 loading 动画：
- Works 列表加载
- Discovery hits 加载
- PDF 渲染

可以使用 Naive UI 的 `<n-skeleton>` 组件快速实现。**这是可选的**，如果没有明显感知的加载卡顿可以先不做。

#### Phase 4 交付物

```
git commit -m "feat(frontend): Phase 4 - 体验优化

性能:
- Duplicates 分页服务端化
- PdfPreviewDrawer 改为 defineAsyncComponent 动态导入
- 搜索防抖统一使用 useDebounce

a11y:
- 键盘导航基础(tabindex/焦点trap/Esc关闭)
- ARIA 最小集(图标按钮aria-label/语义化landmark)
- :focus-visible 焦点可见性样式"
```

---

### Phase 5: 合规储备（可选，预计 3-5 天）

> **目标**: WCAG AA 合规 + 性能深度优化 + 工程化完善。
>
> **触发条件**: 仅在 Phase 0-4 全部完成后、且有明确需求时才启动。不强制执行。

#### 任务 5.1: WCAG AA 全量合规

- 使用 axe-core 自动化审计工具扫描所有页面
- 修复所有 Critical 和 Serious 级别的 a11y 问题
- 颜色对比度全量校验（WCAG 2.1 AA: 正文 4.5:1, 大字 3:1）
- 键盘完全可操作（无鼠标依赖）

#### 任务 5.2: Bundle 分析与优化

```bash
cd web && npm run build:report   # 使用 rollup-plugin-visualizer
```
- 检查是否有意外的大依赖
- tree-shaking 是否生效
- 考虑按路由 code-splitting（如果尚未做）

#### 任务 5.3: 工程化

- ESLint + Prettier 配置（如果之前未加）
- EditorConfig
- 可能的单元测试框架引入（Vitest）

**Phase 5 不出交付 commit**——每项任务独立提交。

---

## §3 审核验收标准（总控模型专用）

> **本节是给审核者（WorkBuddy 总控模型）的检查清单。**
>
> **每个 Phase 完成后，实施者通知审核者，审核者按照以下标准逐项检查。**

### 总体原则

| 原则 | 说明 |
|------|------|
| **功能零回归** | 所有现有功能必须保持正常工作，不允许"重构导致功能降级" |
| **构建必须通过** | `npm run build` 零错误零警告是硬性门槛 |
| **代码增量受控** | 每个 Phase 的净增代码量应在预期范围内 |
| **禁止偷懒** | 不能用注释/TODO/TBD 替代实现；不能留 dead code |
| **文档同步** | 如有架构变更需更新 TECHNICAL_OVERVIEW.md 或 README.md |

### 各 Phase 审核检查清单

#### Phase 0 审核卡

**文件范围**: `api.js`, `error-handler.js`, `router.js`, `NotFound.vue`

| # | 检查项 | 通过标准 | 权重 |
|---|--------|---------|------|
| P0-01 | API AbortController | GET请求支持取消，页面卸载时自动cancel | 🔴 必须通过 |
| P0-02 | API 超时控制 | 默认30s超时，超时抛TimeoutError | 🔴 必须通过 |
| P0-03 | ApiError 分类 | NETWORK/TIMEOUT/SERVER/CLIENT/PARSE 五类齐全 | 🔴 必须通过 |
| P0-04 | 向后兼容 | 原有 api.xxx() 调用无需修改即可运行 | 🔴 必须通过 |
| P0-05 | alert() 清零 | `grep -r "alert(" web/src/views/ web/src/components/` 结果为空 | 🔴 必须通过 |
| P0-06 | confirm() 清零 | 同上 | 🔴 必须通过 |
| P0-07 | 全局 errorHandler | app.config.errorHandler 已配置 | 🟡 应该通过 |
| P0-08 | 404 页面 | 访问不存在路径显示 NotFound.vue | 🟡 应该通过 |
| P0-09 | 路由命名 | 每个路由都有 name 字段 | 🟡 应该通过 |
| P0-10 | 路由 meta | 每个路由都有 meta.title 和 meta.group | 🟡 应该通过 |
| P0-11 | beforeEach | 路由守卫已注册（哪怕只做日志） | 🟢 建议通过 |

**判定规则**:
- 🔴 全部通过 → **PASS**
- 任一 🔴 未通过 → **FAIL**（打回重做）
- 🔴 全过但 ≥2 个 🟡 未过 → **CONDITIONAL PASS**（附条件通过，记录为技术债）

---

#### Phase 1 审核卡

**文件范围**: `AppLayout.vue` (`:root` CSS 变量), 所有 views/*.vue 的 `<style>` 段

| # | 检查项 | 通过标准 | 权重 |
|---|--------|---------|------|
| P1-01 | 变量完整度 | 原审计方案 §3 定义的变量全部在 :root 中声明 | 🔴 必须通过 |
| P1-02 | 硬编码色值残留 | views/ + components/ 的 style 段中 `#[hex]` ≤ 5 个 | 🔴 必须通过 |
| P1-03 | 构建通过 | npm run build 零错误 | 🔴 必须通过 |
| P1-04 | DiscoveryReview 紫色系 | 已用 CSS 变量替代（全局或页面级均可） | 🔴 必须通过 |
| P1-05 | 视觉回归 | 截图对比：主要页面颜色与替换前一致或更统一 | 🟡 应该通过 |
| P1-06 | 无内联 style | 没有 `<div style="color: #xxx">` 这种遗留 | 🟢 建议通过 |

---

#### Phase 2 审核卡

**文件范围**: `composables/`, `components/`, `constants/`, 以及修改后的 views/

| # | 检查项 | 通过标准 | 权重 |
|---|--------|---------|------|
| P2-01 | Composable 提取数量 | 至少 4 个核心 Composable 已提取 | 🔴 必须通过 |
| P2-02 | UI 组件提取数量 | 至少 4 个公共 UI 组件已提取 | 🔴 必须通过 |
| P2-03 | 构建通过 | npm run build 零错误 | 🔴 必须通过 |
| P2-04 | 功能回归 | 11 个页面核心操作无损 | 🔴 必须通过 |
| P2-05 | 代码量减少 | views/ 净减 ≥ 25% | 🟡 应该通过 |
| P2-06 | JSDoc 注释 | 新增的 composable/component 有清晰的 JSDoc | 🟡 应该通过 |
| P2-07 | 无抽象泄漏 | StatusBadge/ReviewBar 的使用不应比原来更复杂 | 🟡 应该通过 |
| P2-08 | useQuarantine 覆盖 | Works/WorkDetail/MetadataReview/ClassificationReview 都已使用 | 🟡 应该通过 |
| P2-09 | 选项常量统一 | DOC_TYPE/READING_LANE 等 5+ 组常量集中管理 | 🟢 建议通过 |
| P2-10 | 无循环依赖 | composables/ 和 components/ 之间无循环引用 | 🟢 建议通过 |

**P2-04 功能回归详细验证步骤**:
1. Dashboard → 加载正常，数据展示正确
2. Works → 搜索/筛选/分页/隔离操作正常
3. TopicsReview → 创建/编辑/删除主题正常
4. DiscoveryReview → 运行查询/hits 列表/送审操作正常
5. InboxReview → 审核(通过/拒绝/跳过)/隔离 正常
6. IntakeReview → 同上
7. ClassificationReview → 同上 + 双面板切换正常
8. MetadataReview → 双面板/PDF预览/字段对比/审核操作正常
9. Duplicates → 列表/合并/忽略操作正常
10. Relations → 图谱渲染正常
11. WorkDetail → 文献详情展示正常

---

#### Phase 3 审核卡

**文件范围**: `DualPanelLayout.vue`, `AppLayout.vue` (侧边栏/顶栏改造)

| # | 检查项 | 通过标准 | 权重 |
|---|--------|---------|------|
| P3-01 | DualPanelLayout 组件存在 | components/ 下有此文件且可 import | 🔴 必须通过 |
| P3-02 | 至少 2 个页面迁移 | MetadataReview + ClassificationReview 已使用 | 🔴 必须通过 |
| P3-03 | ResizeHandle 功能 | 拖拽调整面板宽度正常工作 | 🔴 必须通过 |
| P3-04 | 构建通过 | npm run build 零错误 | 🔴 必须通过 |
| P3-05 | 响应式布局 | 缩小窗口到 768px 以下时布局不崩坏 | 🟡 应该通过 |
| P3-06 | Modal 规范统一 | 简单确认用 ConfirmDialog / 表单用 n-modal / 展示用 n-drawer | 🟡 应该通过 |
| P3-07 | 分页统一 | 全部使用 n-pagination 且 props 一致 | 🟡 应该通过 |
| P3-08 | 侧边栏配置驱动 | 导航数据来自数组配置而非硬编码 | 🟡 应该通过 |
| P3-09 | 面包屑导航 | 顶部显示当前路径面包屑 | 🟢 建议通过 |
| P3-10 | PDF 三面板 | MR 打开PDF时三面板显示正常 | 🟢 建议通过 |

---

#### Phase 4 审核卡

**文件范围**: 性能相关改动 + a11y 相关改动

| # | 检查项 | 通过标准 | 权重 |
|---|--------|---------|------|
| P4-01 | PDF 动态导入 | PdfPreviewDrawer 使用 defineAsyncComponent | 🟡 应该通过 |
| P4-02 | 防抖统一 | 搜索输入使用 debounce (300ms) | 🟡 应该通过 |
| P4-03 | Duplicates 分页 | 服务端分页生效，非一次性全量加载 | 🟡 应该通过 |
| P4-04 | 构建通过 | npm run build 零错误 | 🔴 必须通过 |
| P4-05 | tabindex 基础 | 交互元素可被 Tab 键聚焦 | 🟢 建议通过 |
| P4-06 | aria-label | 图标按钮有 aria-label 属性 | 🟢 建议通过 |
| P4-07 | focus-visible | 有 :focus-visible 样式 | 🟢 建议通过 |
| P4-08 | 首屏性能 | 动态导入后 LCP 改善（可用 DevTools 验证） | 🟢 建议通过 |

---

### 审核结论模板

每次审核完成后，审核者输出以下格式的结论：

```markdown
## 前端重构 Phase X 审核报告

**审核时间**: YYYY-MM-DD HH:MM
**实施 Commit**: <commit-hash>
**审核者**: WorkBuddy 总控模型

### 结论: ✅ PASS / ⚠️ CONDITIONAL PASS / ❌ FAIL

### 通过项 (N/M)
- [x] P{X}-XX: ...
- [x] ...

### 未通过/附条件项 (N)
- [ ] P{X}-XX: ... （原因 + 修复建议）
- [ ] ...

### 额外发现
（审核过程中发现的非 checklist 内的问题）

### 技术债登记
（本次遗留的问题，记录到 FUTURE_WORK_PLAN.md）

### 下一步
- 如果 PASS → 可以进入下一 Phase
- 如果 FAIL → 打回实施者修复后重新提交审核
- 如果 CONDITIONAL PASS → 可以进入下一 Phase，但技术债必须在 Phase 4 前清偿
```

---

## §4 禁止事项与红线

以下行为一旦发现，**立即 FAIL**，不予讨论：

| # | 禁止行为 | 后果 |
|---|---------|------|
| R-01 | 引入 package.json 中未列出的新依赖 | **直接 FAIL** — 每个新依赖需要单独申请 |
| R-02 | 删除任何 parser/collector/api/ 目录下的文件 | **直接 FATAL** — 这些是后端代码 |
| R-03 | 在代码中留下 `// TODO` / `// FIXME` / `// HACK` 作为替代实现 | **FAIL** — 要么做完要么不做 |
| R-04 | 将功能改动混入"纯重构"的 commit 中 | **FAIL** — 重构 commit 不应包含功能变更 |
| R-05 | 修改 `vite.config.js` 的构建输出路径或模式 | **FAIL** — 构建配置不在范围内 |
| R-06 | 引入 TypeScript (.ts 文件) 或类型注解 | **直接 FAIL** — 明确禁止 |
| R-07 | 引入 Pinia/Vuex/store | **直接 FAIL** — 用 Composable 替代 |
| R-08 | 删除现有的 `usePagination.js` 而非在其上增强 | **FAIL** — 应渐进改进非推翻重来 |
| R-09 | 在 `<style>` 中使用 `!important` 来覆盖 Naive UI 样式 | **CONDITIONAL PASS** — 每处需单独说明理由 |
| R-10 | 提交信息不含 Phase 编号和中文摘要 | **FAIL** — 格式见各 Phase 交付物示例 |

---

## §5 实施节奏与协作约定

### 推荐节奏

```
Day 1-2:   Phase 0（基础设施加固）
           ↓ 提交审核
Day 3:     Phase 1（设计令牌落地）
           ↓ 提交审核
Day 4-9:   Phase 2（组件提取，最大的Phase）
           ↓ 提交审核
Day 10-13: Phase 3（布局重构）
           ↓ 提交审核
Day 14-16: Phase 4（体验优化）
           ↓ 提交审核
Day 17+:   Phase 5（可选，按需启动）
```

### 协作流程

```
┌─────────────┐    完成实施+commit    ┌─────────────┐
│  实施者      │ ──────────────────→  │  审核者      │
│  (本地模型)  │                      │  (WorkBuddy)  │
└─────────────┘ ←────────────────── └─────────────┘
                  审核结果(PASS/FAIL)
                     │
              ┌──────┴──────┐
              │ PASS?        │
              ├──────┬──────┤
              Yes    No     Conditional
               │      │         │
          进入下一Phase  修复重交   进入下一Phase+记债
```

### 实施者提交审核时的格式要求

实施者完成一个 Phase 后，向审核者发送以下格式消息：

```
📋 Phase X 实施完成，请审核。

- Phase: X (名称)
- Commit: <full-commit-hash>
- 分支: master (或 feature 分支名)
- 变更文件列表:
  - path/to/file1.ts (+120 -45)
  - path/to/file2.vue (-89 +34)
  - ...
- 自测情况:
  - ✅ npm run build 通过
  - ✅ 以下页面目视检查通过: ...
  - ⚠️ 已知问题: ...
- 特别说明: (如果有偏离指令的地方，在此说明原因)
```

### 审核响应时效

- 审核者在收到审核请求后 **30 分钟内** 给出初步结论
- 如需深入审查特定文件，会额外标注预计耗时
- **FAIL 结论必须附带具体的修复指导**，不能只说"不行"

---

## §6 回滚预案

如果某个 Phase 导致严重问题：

```bash
# 1. 查看最近的 commits
git log --oneline -10

# 2. 回滚到指定 Phase 之前的 commit
git revert <phase-commit-hash>   # 推荐：保留历史
# 或者
git reset --hard <pre-phase-commit>  # 激进：丢弃变更

# 3. 重新构建验证
cd web && npm run build && npm run dev
```

**回滚决策权归属**:
- 实施者可以自行 revert 自己的 commit（如果发现明显问题）
- 审核者有权要求实施者 revert 并重新实施
- 如果连续 2 次 FAIL，建议暂停并重新审视设计方案

---

## 附录 A: 快速命令参考

```bash
# 构建
cd web && npm run build

# 开发服务器
cd web && npm run dev

# 搜索硬编码色值（Phase 1 验证用）
grep -rn "#[0-9a-fA-F]\{3,6\}" web/src/views/*/web/src/components/*.vue | grep -v "node_modules"

# 搜索 alert()（Phase 0 验证用）
grep -rn "alert(" web/src/

# 代码行数统计
find web/src/views -name "*.vue" -exec wc -l {} + | tail -1

# Bundle 分析
cd web && npm run build:report
```

## 附录 B: 关联文档索引

| 文档 | 路径 | 内容 |
|------|------|------|
| 原审计方案 | `docs/superpowers/reviews/2026-07-01-frontend-design-audit.md` | UI审计/设计令牌/组件清单/P0-P3 |
| 盲区补充 | `docs/superpowers/reviews/2026-07-01-frontend-blindspot-supplement.md` | 6盲区分析/线框解答/整合蓝图 |
| V1.3交接文档 | `docs/superpowers/plans/2026-06-30--06-30-v1.3-handoff.md` | V1.3上下文/真实纠错记录 |
| 技术概览 | `TECHNICAL_OVERVIEW.md` | 项目整体架构（如有架构变更需同步更新） |
| 未来计划 | `FUTURE_WORK_PLAN.md` | 技术债登记簿 |

---

> **文档结束**
>
> 本文档版本 v2.0-final，由 WorkBuddy 总控模型基于原审计方案 + 盲区补充综合编制。
> 实施过程中如遇到指令未覆盖的场景，遵循「保守原则」：宁可不改也不要引入风险。