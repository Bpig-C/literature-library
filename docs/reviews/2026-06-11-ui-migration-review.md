# 前端 UI 库替换可行性审核

审核日期：2026-06-11

## 结论

建议采纳“渐进式引入 UI 库”的方向，并优先选择 Naive UI 作为试点方案；但原报告中有几处执行层假设需要修正。当前项目是 Vue 3 + Vite SPA，前端运行依赖很少，UI 组件大多手写，确实已经在弹窗反馈、表单校验、选择器、分页、表格交互和响应式布局上出现维护风险。

推荐策略不是一次性全量替换，而是先做反馈层和表单控件的薄切片验证，再决定是否继续替换表格、布局和 PDF 抽屉。

## 已确认的机会

1. 反馈层替换最值得先做
   - 当前 `Works.vue`、`WorkDetail.vue`、`MetadataReview.vue`、`ClassificationReview.vue` 仍有 `prompt()`、`confirm()`、`alert()`。
   - 用统一的 message/dialog 能立刻改善隔离、恢复、批量批准、失败提示等流程。
   - 这是最低耦合、最高收益的第一阶段。

2. 分类审核页的 searchable-select 是明确的删除机会
   - `ClassificationReview.vue` 自己维护 `v-click-outside`、`dropdownOpen`、`searchText`、过滤逻辑和下拉 CSS。
   - 可用 `n-select filterable` 先替换 `primary_source_actor_type` 和 `region` 两类字段。
   - 注意：当前 `primary_source_actor_type` 支持自定义值，`region` 是锁定选项；迁移时必须分别映射 `tag`/自定义输入和只读选择行为。

3. 分页器可以优先替换，但要先统一分页模型
   - `Works.vue` 使用 `page/per_page`。
   - `ClassificationReview.vue` 使用 `limit/offset`。
   - `MetadataReview.vue` 使用 `page/per_page`。
   - 引入 `n-pagination` 前，应先抽出一个分页适配层，避免每页行为和接口参数在迁移后继续分裂。

4. 表单验证值得做，但不应只替换控件外观
   - 元数据审核中的日期对象、作者列表、贡献方列表、拒绝理由、隔离原因都有业务语义。
   - 迁移到 `n-form` 时，应同步补齐字段级校验、拒绝必填备注、日期范围、URL/DOI/arXiv 格式等规则。

5. 数据表格替换可做，但收益被报告高估
   - 当前列表多数已分页，虚拟滚动不是第一收益。
   - 如果做列排序，必须确认后端支持全量排序参数；只在当前页前端排序会给用户造成误导。
   - `Works.vue` 是表格迁移的首选试点，`Relations.vue` 次之。

6. PDF 抽屉不应早期整体替换
   - `PdfPreviewDrawer.vue` 包含 pdfjs 生命周期、渲染取消、缩放、翻页、错误处理。
   - UI 库只能替换壳层、按钮、加载态，不应先重写 PDF 渲染核心。

7. `ResizeHandle` 建议保留
   - 审核页的分割面板是项目特定交互，UI 库没有完全等价替代。
   - 后续可只统一按钮和视觉样式，不强行删除。

## 报告中需要修正的点

1. “Naive UI 原生 CSS 变量可直接复用现有变量”表述过强
   - Naive UI 的主题主要通过 `NConfigProvider` / `themeOverrides` 管理。
   - 现有 `--accent`、`--line`、`--chip` 不能自动被组件消费，需要建立一层 token 映射。

2. 安装和 Vite 配置不完整
   - 如果使用报告里的 `NaiveUiResolver()` 自动导入方案，除了 `naive-ui` 还需要安装 `unplugin-vue-components`。
   - 如果要自动导入 `useMessage`、`useDialog` 等 composable，还需要单独评估 `unplugin-auto-import`，或者显式 import。
   - 当前 `web/vite.config.js` 只有 `vue()`，不能直接套用报告配置片段。

3. `createDiscreteApi` 示例不适合直接作为全局模式
   - 对 `<script setup>` 组件，全局属性不是最清晰的调用方式。
   - 推荐二选一：
     - 在 `App.vue` 包一层 `NConfigProvider`、`NMessageProvider`、`NDialogProvider`，组件内通过 composable 使用；
     - 或创建 `web/src/ui/feedback.js`，集中导出 `message/dialog`，只用于非组件上下文。

4. “Naive UI 默认 reset.css 会冲突”需要核实
   - Naive UI 官方 README 强调组件使用不需要额外导入 CSS。
   - 真正需要关注的是当前 `AppLayout.vue` 里的全局 `* { box-sizing; margin; padding }` 和 body 字体设置会影响所有组件。

5. 包体积估算只能作为方向，不宜作为决策证据
   - 报告里的 gzip 数字没有给出构建方法、组件集合和版本。
   - 项目应以实际 `vite build` 和 bundle analyzer 结果为准。

## 建议迁移顺序

### Phase 0：基线与防回归

- 增加前端最小 smoke check：`npm run build` 必须通过。
- 建议增加 1 个浏览器截图/交互检查，覆盖 Works 隔离/恢复、MetadataReview 批量批准、ClassificationReview 下拉选择。
- 记录迁移前 bundle 大小和主要页面截图。

### Phase 1：反馈层

- 引入 Naive UI 的 message/dialog/config provider。
- 替换 `alert()`、`confirm()`、`prompt()`。
- 隔离原因从 prompt 改为受控输入/选择，保留取消语义。

### Phase 2：选择器、分页、表单校验

- 先替换 `ClassificationReview.vue` 的 searchable-select。
- 再替换三处分页器。
- 最后引入 `n-form`，补业务校验，不只换样式。

### Phase 3：表格和壳层

- 先试点 `Works.vue` 表格，确认后端排序参数。
- 再评估 `Relations.vue`。
- PDF 抽屉只替换外层控件，不动 pdfjs 渲染核心。
- AppLayout 可以单独做响应式侧栏，不必和数据组件迁移耦合。

## 验收标准

- `cd web; npm run build` 通过。
- 所有隔离、恢复、批量批准、拒绝必填、下拉选择、分页流程可手工验证。
- UI 替换后不丢失现有业务语义：隔离原因、审核备注、低风险/低模糊度批量批准、已隔离显示、PDF 预览。
- 如果表格支持排序，排序必须作用于完整结果集，而不是当前页。
- 每个阶段结束后做两轮审核：
  - 第一轮：实现者自查功能和构建。
  - 第二轮：独立 reviewer 对照本文件和真实代码复核，列出遗漏和幻觉风险。

