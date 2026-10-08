<template>
  <div class="ingest-hub">
    <div class="ingest-flow">
      <strong>先入库建立 Work 身份，再解析材料。</strong>
      <span>完整书目 A 在解析后到 <router-link to="/metadata-workspace">元数据工作台</router-link> 批量交给 Agent；研究批次用于 C 原文与 D 解释分类。</span>
    </div>
    <n-tabs v-model:value="activeTab" type="line" animated>
      <n-tab-pane name="inbox" tab="📥 收件箱">
        <InboxReview />
      </n-tab-pane>
      <n-tab-pane name="discovery" tab="🔍 辅助发现">
        <DiscoveryReview />
      </n-tab-pane>
    </n-tabs>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import DiscoveryReview from './DiscoveryReview.vue'
import InboxReview from './InboxReview.vue'

const activeTab = ref('inbox')
</script>

<style scoped>
.ingest-hub {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.ingest-flow { padding: 10px 16px; background: #edf5f1; color: #35594e; line-height: 1.6; }
.ingest-flow strong { margin-right: 8px; }
.ingest-flow a { color: #166c58; text-decoration: underline; }

.ingest-hub :deep(.n-tabs) {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.ingest-hub :deep(.n-tabs-nav) {
  padding: 0 var(--space-4);
  border-bottom: 1px solid var(--border);
  background: var(--bg-surface);
  flex-shrink: 0;
}

.ingest-hub :deep(.n-tabs-pane-wrapper) {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.ingest-hub :deep(.n-tab-pane) {
  height: 100%;
}
</style>
