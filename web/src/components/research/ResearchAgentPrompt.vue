<template>
  <section class="agent-prompt">
    <button type="button" :disabled="loading" @click="toggle">{{ opened ? '收起 Agent 提示词' : '生成 Agent 提示词' }}</button>
    <!-- 内嵌入口与悬浮入口复用同一 AgentTaskPanel 核心（工单工作包 C）。 -->
    <template v-if="opened">
      <AgentTaskPanel :record="record" :initial-mode="initialMode" />
    </template>
  </section>
</template>

<script setup>
import { ref } from 'vue'
import AgentTaskPanel from './AgentTaskPanel.vue'

const props = defineProps({
  record: { type: Object, required: true },
  initialMode: { type: String, default: 'organize' },
})
const opened = ref(false)
const loading = ref(false)
function toggle() { opened.value = !opened.value }
</script>

<style scoped>
.agent-prompt { min-width: 0; display: flex; flex-direction: column; align-items: flex-start; gap: 8px; }
.agent-prompt > button { padding: 7px 10px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-surface); color: var(--accent-ink); cursor: pointer; }
.agent-prompt > button:disabled { opacity: .5; cursor: wait; }
.agent-prompt :deep(.agent-task-panel) { width: 100%; box-sizing: border-box; }
</style>
