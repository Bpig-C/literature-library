# UI 库迁移设计文档

日期：2026-06-11
方案：渐进式引入 Naive UI（Phase 0+1+2）
参考：../../reviews/2026-06-11-ui-migration-review.md

## 概述

将当前手写 UI 组件逐步替换为 Naive UI，优先替换反馈层（alert/confirm/prompt），再替换选择器、分页器和表单校验。不涉及表格、PDF 抽屉核心、布局响应式。

## 依赖与配置

### 安装

```bash
cd web
npm install naive-ui unplugin-vue-components unplugin-auto-import
```

### vite.config.js

```js
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import AutoImport from 'unplugin-auto-import/vite'
import { NaiveUiResolver } from 'unplugin-vue-components/resolvers'

export default defineConfig({
  plugins: [
    vue(),
    Components({ resolvers: [NaiveUiResolver()] }),
    AutoImport({ imports: [{ from: 'naive-ui', imports: ['useMessage', 'useDialog'] }] }),
  ],
  server: {
    port: 19528,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:19527',
        changeOrigin: true,
      },
    },
  },
})
```

### App.vue 主题配置

```vue
<script setup>
import AppLayout from './components/AppLayout.vue'

const themeOverrides = {
  common: {
    primaryColor: '#1f6feb',
    successColor: '#16833a',
    warningColor: '#9a6700',
    errorColor: '#c32f27',
    fontFamily: '"Segoe UI", "Microsoft YaHei", Arial, sans-serif',
  }
}
</script>

<template>
  <NConfigProvider :theme-overrides="themeOverrides">
    <NMessageProvider>
      <NDialogProvider>
        <AppLayout>
          <router-view />
        </AppLayout>
      </NDialogProvider>
    </NMessageProvider>
  </NConfigProvider>
</template>
```

## Phase 0：基线与防回归

1. 确认 `cd web && npm run build` 通过
2. 安装 `vite-plugin-visualizer`，添加 `build:report` 脚本
3. 记录基线 bundle 大小

## Phase 1：反馈层替换

### 替换清单

| 文件 | 行号 | 当前调用 | 替换为 |
|------|------|----------|--------|
| Works.vue | 218 | `prompt('隔离原因...')` | `dialog.info()` + NInput |
| Works.vue | 225 | `confirm('确认恢复...')` | `dialog.warning()` |
| WorkDetail.vue | 389 | `prompt('隔离原因...')` | `dialog.info()` + NInput |
| WorkDetail.vue | 396 | `confirm('确认恢复...')` | `dialog.warning()` |
| MetadataReview.vue | 433 | `confirm('批量批准...')` | `dialog.warning()` |
| MetadataReview.vue | 435 | `alert('已批准...')` | `message.success()` |
| MetadataReview.vue | 507 | `alert('拒绝时请填写原因')` | `message.warning()` |
| MetadataReview.vue | 551 | `alert('隔离失败...')` | `message.error()` |
| ClassificationReview.vue | 506 | `alert('已批准...')` | `message.success()` |
| ClassificationReview.vue | 524 | `alert('隔离失败...')` | `message.error()` |

### 隔离对话框改造

- 使用 `dialog.info()` + 自定义内容模板
- 展示当前文献标题（只读）
- 保留自由文本输入
- 保持取消语义

## Phase 2：选择器、分页、表单校验

### 2a. searchable-select → n-select

**ClassificationReview.vue**：
- `primary_source_actor_type`：`n-select filterable tag`，支持自定义输入
- `region`：`n-select filterable`，只读选择

**删除**：v-click-outside 指令、dropdownOpen/searchText reactive 状态、filteredOptions 函数、所有 `.ss-*` CSS

### 2b. 分页适配层

创建 `web/src/composables/usePagination.js`：

```js
import { ref, computed } from 'vue'

export function usePagination({ perPage = 20, mode = 'page' } = {}) {
  const page = ref(1)
  const total = ref(0)

  const params = computed(() => {
    if (mode === 'offset') return { limit: perPage, offset: (page.value - 1) * perPage }
    return { page: page.value, per_page: perPage }
  })

  const totalPages = computed(() => Math.ceil(total.value / perPage))

  function reset() { page.value = 1 }

  return { page, total, totalPages, params, reset }
}
```

**替换**：3 个页面的手写分页按钮 → `<n-pagination v-model:page="page" :page-count="totalPages" />`

### 2c. n-form + 字段校验

**MetadataReview.vue**：
- 拒绝时 `review_note` 必填
- `publication_date` year/month/day 数字范围
- `doi` 正则校验
- `url` URL 格式校验
- `arxiv_id` 格式校验

**ClassificationReview.vue**：无强制校验（保持现有逻辑）

## 不做的事

- Works.vue 表格维持现状（Phase 3 再做）
- PDF 抽屉核心不替换
- AppLayout 响应式不改
- ResizeHandle 保留

## 验收标准

1. `cd web && npm run build` 通过
2. 所有隔离/恢复/批量批准/拒绝/下拉选择/分页流程可手工验证
3. UI 替换后不丢失业务语义：隔离原因、审核备注、低风险/低模糊度批量批准、已隔离显示
4. 每个阶段结束后做两轮审核：实现者自查 + 独立 reviewer 复核
