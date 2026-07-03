<template>
  <div class="ingest-hub">
    <n-tabs v-model:value="activeTab" type="line" animated>
      <n-tab-pane name="discovery" tab="🔍 发现检索">
        <DiscoveryReview />
      </n-tab-pane>
      <n-tab-pane name="inbox" tab="📥 收件箱">
        <InboxReview />
      </n-tab-pane>
    </n-tabs>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import DiscoveryReview from './DiscoveryReview.vue'
import InboxReview from './InboxReview.vue'

const activeTab = ref('discovery')
</script>

<style scoped>
.ingest-hub {
  height: 100%;
  display: flex;
  flex-direction: column;
}

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
