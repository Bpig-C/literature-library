# 问题记录

## 已修复

### PDF-001: 关闭 PDF 预览后布局不恢复

**发现时间**：2026-06-11
**修复时间**：2026-06-11
**影响页面**：MetadataReview.vue, ClassificationReview.vue

**现象**：点击"PDF 侧栏"打开预览后，再点击 Close 关闭，详情面板没有自适应展开，右侧留下空白区域。

![正常状态](screenshots/正常.png)
![关闭异常](screenshots/pdf预览关闭异常.png)

**根因**：CSS 默认定义 3 列网格（`340px 6px 1fr`），但 `ResizeHandle` 组件只在 PDF 打开时渲染（`v-if="selected && showPdfDrawer"`）。关闭 PDF 后 DOM 只有 2 个子元素（list-panel, detail-panel），但网格仍预留 3 列，中间列为空。

**修复**：
- `layoutStyle` 计算：PDF 关闭时只生成 2 列（`listWidth 1fr`），不包含 handle 列
- `ResizeHandle`（list 和 detail 之间）加 `v-if="selected && showPdfDrawer"`

---

### PDF-002: 关闭 PDF 后再打开翻页报错

**发现时间**：2026-06-11
**修复时间**：2026-06-11
**影响页面**：MetadataReview.vue, ClassificationReview.vue, PdfPreviewDrawer.vue

**现象**：关闭 PDF 预览后重新打开，首页正常，但翻页时报错 `Cannot read properties of null (reading 'sendWithPromise')`。

![翻页异常](screenshots/pdf预览关闭后再打开翻页异常.png)

**根因**：组件销毁时 pdfjs-dist 的 worker 仍有异步操作在运行，重建组件后旧 worker 与新实例竞争。`onBeforeUnmount` 中的清理不够彻底。

**修复**：`onBeforeUnmount` 中递增 `loadToken` 和 `renderToken`，确保任何挂起的异步操作被废弃：
```js
onBeforeUnmount(() => {
  const token = ++loadToken
  renderToken += 1
  cancelRender()
  if (loadTask) { try { loadTask.destroy() } catch {} loadTask = null }
  if (pdfDoc) { try { pdfDoc.destroy() } catch {} pdfDoc = null }
})
```

---

### PDF-003: 关闭 PDF 后切换文献布局错乱

**发现时间**：2026-06-11
**修复时间**：2026-06-11
**影响页面**：MetadataReview.vue, ClassificationReview.vue

**现象**：关闭 PDF 预览后切换到其他文献，PDF 预览跑到左下角，整体布局大幅错乱，详情面板无法正常显示。

![布局异常](screenshots/PDF预览关闭切换文献后布局异常.png)

**根因**：与 PDF-001 相同的网格布局问题。`detailWidth` 在关闭 PDF 时可能保留了固定宽度值，导致 detail 面板在切换文献后仍以固定宽度渲染，破坏了整体布局。

**修复**：
- `closePdfDrawer()` 中 `detailWidth.value = null`，让 detail 面板回到 `1fr` 自适应
- 配合 PDF-001 的 2 列布局修复，切换文献时网格正确重置
