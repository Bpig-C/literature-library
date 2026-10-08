<template>
  <div class="agent-fab-root">
    <!-- 悬浮按钮：不遮挡主要内容，固定右下角 -->
    <button v-if="!open" type="button" class="agent-fab" data-testid="agent-fab"
      :title="'打开 Agent 任务面板（' + currentLabel + '）'" @click="open = true">
      <span class="fab-icon">⚡</span>
      <span>Agent 任务</span>
    </button>
    <div v-show="open" class="agent-fab-panel" data-testid="agent-fab-panel">
      <header class="fab-panel-head">
        <strong>Agent 任务面板</strong>
        <span class="head-hint">生成 → 编辑 → 复制；复制不表示已派发或开始执行</span>
        <button type="button" class="fab-close" aria-label="收起 Agent 任务面板" @click="open = false">×</button>
      </header>
      <AgentTaskPanel ref="panelRef" :record="record" :initial-mode="initialMode" />
    </div>
  </div>
</template>

<script setup>
// 工单工作包 C：文献详情页与研究详情页的统一悬浮入口。
import { computed, ref } from 'vue'
import AgentTaskPanel from './AgentTaskPanel.vue'
import { AGENT_TASK_MODES } from '../../researchAgentPrompt'

const props = defineProps({
  record: { type: Object, required: true },
  initialMode: { type: String, default: 'organize' },
})
const open = ref(false)
const panelRef = ref(null)
const currentLabel = computed(() =>
  AGENT_TASK_MODES.find(m => m.value === props.initialMode)?.label || '整理/补全文献')
</script>

<style scoped>
.agent-fab-root { position: fixed; right: 22px; bottom: 22px; z-index: 70; display: flex; flex-direction: column; align-items: flex-end; gap: 10px; }
.agent-fab { display: flex; align-items: center; gap: 7px; padding: 10px 16px; border: 1px solid var(--accent-mute); border-radius: 999px; background: var(--accent-subtle, var(--bg-surface)); color: var(--accent-ink); cursor: pointer; font-size: 12px; font-weight: 620; box-shadow: 0 4px 14px rgba(0,0,0,.14); }
.agent-fab:hover { filter: brightness(.97); }
.fab-icon { font-size: 13px; }
.agent-fab-panel { display: flex; flex-direction: column; gap: 8px; width: min(680px, calc(100vw - 32px)); max-height: min(78dvh, 900px); overflow-y: auto; padding: 12px; border: 1px solid var(--border-strong); border-radius: var(--radius-lg); background: var(--bg-surface); box-shadow: 0 10px 30px rgba(0,0,0,.18); }
.fab-panel-head { display: flex; align-items: center; gap: 10px; }
.fab-panel-head strong { font-size: 13px; }
.head-hint { flex: 1; color: var(--text-tertiary); font-size: 10px; }
.fab-close { padding: 3px 10px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-page); cursor: pointer; font-size: 14px; }
</style>
