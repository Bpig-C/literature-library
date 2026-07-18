<template>
  <!-- 仅用于把 naive-ui message API 挂到 window.__naive_message，供 error-handler
       与非 setup 上下文（如 Pinia 外的工具函数、模板内联调用）使用。无渲染内容。 -->
</template>

<script setup>
import { useMessage } from 'naive-ui'
import { mountMessageApi } from '../error-handler'

// 必须放在 NMessageProvider 子树内调用 useMessage()（见 App.vue）
mountMessageApi(useMessage())
</script>
