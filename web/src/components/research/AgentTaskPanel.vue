<template>
  <section class="agent-task-panel" data-testid="agent-task-panel">
    <div class="panel-toolbar">
      <div class="mode-switch" role="tablist" aria-label="任务类型">
        <button v-for="mode in AGENT_TASK_MODES" :key="mode.value" type="button" role="tab"
          :aria-selected="selectedMode === mode.value"
          :class="{ active: selectedMode === mode.value }"
          @click="selectMode(mode.value)">{{ mode.label }}</button>
      </div>
      <button type="button" :disabled="loading" @click="generate">
        {{ prompt ? '重新生成' : '生成任务提示词' }}
      </button>
    </div>

    <p class="panel-hint">自动带入本篇资料与版本；取不到的明确标“未取得”。生成不会启动 Agent、保存研究记录或提交审核；复制/保存反馈不代表已派发任务。</p>

    <div class="panel-fields">
      <label>
        <span>批次（切换后重新读取该批次记录）</span>
        <select v-model="batchInput"><option value="">未绑定批次（仅准备检查任务）</option><option v-for="id in batchOptions" :key="id" :value="id">{{ id }}</option></select>
      </label>
      <label>
        <span>我特别关注的问题（可选，会写入提示词）</span>
        <input v-model="focusInput" type="text" placeholder="例如：Table 1 数值与原文是否一致" />
      </label>
    </div>

    <p v-if="notice" class="panel-status" role="status">{{ notice }}</p>
    <p v-if="staleNotice" class="panel-status is-warn" role="alert">{{ staleNotice }}</p>

    <label class="panel-editor">交给 Agent 的任务提示词（可编辑）
      <textarea v-model="prompt" :disabled="loading" rows="16" data-testid="agent-task-prompt"
        @input="userEdited = true" /></label>

    <div class="panel-actions">
      <button type="button" :disabled="loading || !prompt" data-testid="agent-task-copy" @click="copy">复制提示词</button>
      <button type="button" :disabled="loading" @click="generate">重新生成（保留场景见提示）</button>
    </div>
    <details v-if="savedEdits.length"><summary>重新生成前的编辑备份（{{ savedEdits.length }}）</summary><div v-for="(text, index) in savedEdits" :key="index"><textarea readonly :value="text" rows="5" /><button type="button" @click="prompt = text; userEdited = true; staleNotice = '已恢复旧编辑，请核对上下文'">恢复此份</button></div></details>
    <p v-if="copyStatus" role="status" :class="{ 'is-error': copyFailed }">{{ copyStatus }}</p>
  </section>
</template>

<script setup>
// 悬浮入口与内嵌入口复用同一面板核心（工单工作包 C）。
// 上下文或版本变化时不静默覆盖用户已编辑文本：标记过期并提示重新生成。
import { ref, watch } from 'vue'
import { getWork, queryResearch } from '../../api'
import { listResearchFeedback, listParseCorrections } from '../../api'
import { AGENT_TASK_MODES, buildResearchAgentPrompt } from '../../researchAgentPrompt'
import { researchWorkId } from '../../researchPresentation'

const props = defineProps({
  record: { type: Object, required: true },
  initialMode: { type: String, default: 'organize' },
  selectedFeedbackId: { type: String, default: '' },
})
const emit = defineEmits(['generated'])

const selectedMode = ref(props.initialMode)
const loading = ref(false)
const prompt = ref('')
const notice = ref('')
const staleNotice = ref('')
const copyStatus = ref('')
const copyFailed = ref(false)
const userEdited = ref(false)
const batchInput = ref('')
const batchOptions = ref([])
const savedEdits = ref([])
const focusInput = ref('')
let generation = 0

watch(() => JSON.stringify(props.record), () => {
  // 页面目标/版本变化：清空自动上下文，但不覆盖用户文本——标记过期。
  generation++
  loading.value = false
  notice.value = ''
  if (userEdited.value && prompt.value) {
    staleNotice.value = '页面记录已变化；下方保留了你的编辑文本，但其中旧上下文可能过期，请点击“重新生成”后再核对使用。'
  } else {
    prompt.value = ''
    staleNotice.value = ''
  }
}, { immediate: true })

watch(() => props.record?.source?.work_id || props.record?.work_id, async (id) => {
  batchInput.value = props.record?.batch_id || ''
  batchOptions.value = batchInput.value ? [batchInput.value] : []
  if (!id) return
  try {
    const response = await fetch('/api/overview')
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const overview = await response.json()
    if (!overview.research?.available) throw new Error('批次目录不可用')
    if (id !== (props.record?.source?.work_id || props.record?.work_id)) return
    batchOptions.value = [...new Set([...(overview.research.batches || []).map(row => row.id), props.record?.batch_id].filter(Boolean))]
  } catch { notice.value = '批次列表读取失败，请重试；不能猜测批次。' }
}, { immediate: true })
watch(() => props.record?.batch_id, value => { batchInput.value = value || '' })
watch([batchInput, focusInput, selectedMode, () => props.selectedFeedbackId], () => {
  generation++; loading.value = false
  if (prompt.value) staleNotice.value = '批次、关注点或任务范围已变化，旧提示词已过期，请重新生成。'
})

function selectMode(mode) {
  if (selectedMode.value === mode) return
  selectedMode.value = mode
  if (userEdited.value && prompt.value) {
    staleNotice.value = '任务类型已切换；已保留你的编辑文本。切换后旧提示词的任务范围不再匹配，请点击“重新生成”。'
  }

}

async function generate() {
  const ticket = ++generation
  let record = props.record
  const id = record.source?.work_id || record.work_id
  loading.value = true
  notice.value = ''
  copyStatus.value = ''
  staleNotice.value = ''
  const tasks = [
    id ? getWork(id) : Promise.reject(new Error('缺少 Work ID')),
    fetch('/api/research/schema').then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() }),
  ]
  if (selectedMode.value !== 'organize') {
    tasks.push(listResearchFeedback({ work_id: id }))
    tasks.push(listParseCorrections({ work_id: id }))
  }
  const results = await Promise.allSettled(tasks)
  if (ticket !== generation) return
  const [work, schema, feedback, corrections] = results.map(r => r.status === 'fulfilled' ? r.value : null)
  if (batchInput.value) {
    try {
      const [response, overview] = await Promise.all([
        queryResearch({ work_id: id, batch_id: batchInput.value, ...(props.record?.source?.id ? { source_id: props.record.source.id } : {}), limit: 200 }),
        fetch('/api/overview').then(async r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() }),
      ])
      if (ticket !== generation) return
      const rows = response.items || []
      const sourceId = props.record?.source?.id
      const matches = sourceId ? rows.filter(row => row.source?.id === sourceId) : rows
      if (matches.length !== 1) throw new Error('该批次下没有唯一匹配来源，请到研究视图选择具体记录。')
      record = { ...matches[0], batch_id: response.batch_id || batchInput.value, batch_release_id: overview.research?.batches?.find(batch => batch.id === batchInput.value)?.release_id || null }
    } catch (e) { loading.value = false; staleNotice.value = e.message; return }
  } else if (record.batch_id) {
    loading.value = false; staleNotice.value = '请先选择实际批次。'; return
  }
  if (results.slice(2).some(result => result.status === 'rejected')) {
    loading.value = false; staleNotice.value = '反馈或解析纠错清单读取失败，未生成任务；请重试，不能将读取失败视为没有问题。'; return
  }
  if (userEdited.value && prompt.value) savedEdits.value.push(prompt.value)
  prompt.value = buildResearchAgentPrompt(record, work, schema, window.location.origin, {
    mode: selectedMode.value,
    focus: focusInput.value,
    batchId: batchInput.value || record.batch_id || null,
    feedbackItems: feedback?.items?.filter(item => props.selectedFeedbackId ? item.id === props.selectedFeedbackId : item.status !== 'closed') || [],
    parseIssues: corrections?.items?.filter(item => props.selectedFeedbackId ? item.id === props.selectedFeedbackId : !['adopted', 'withdrawn'].includes(item.status)) || [],
  })
  const failedNames = []
  if (results[0].status === 'rejected') failedNames.push('书目/解析信息')
  if (results[1].status === 'rejected') failedNames.push('研究库报告')
  notice.value = failedNames.length
    ? `部分资料读取失败（${failedNames.join('、')}）；未取得的信息已在提示词中明确标注，请核对后再交给 Agent。`
    : '已读取当前卡片与最新上下文。复制前可调整任务范围与关注点。'
  userEdited.value = false
  loading.value = false
  emit('generated', { mode: selectedMode.value })
}

async function copy() {
  if (staleNotice.value) { copyStatus.value = '提示词上下文已过期，请重新生成后复制。'; return }
  try {
    await navigator.clipboard.writeText(prompt.value)
    copyStatus.value = '已复制，可粘贴给本地 Agent。'
    copyFailed.value = false
  } catch {
    copyStatus.value = '浏览器未允许自动复制，请在文本框内全选后手动复制。'
    copyFailed.value = true
  }
}

defineExpose({ generate, selectMode })
</script>

<style scoped>
.agent-task-panel { display: flex; flex-direction: column; gap: 9px; min-width: 0; padding: 12px; border: 1px solid var(--info-border); border-radius: var(--radius-md); background: var(--info-bg); }
.panel-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.mode-switch { display: flex; gap: 4px; flex-wrap: wrap; }
.mode-switch button { padding: 5px 10px; border: 1px solid var(--border-strong); border-radius: 999px; background: var(--bg-surface); color: var(--text-secondary); cursor: pointer; font-size: 11px; }
.mode-switch button.active { color: var(--accent-ink); border-color: var(--accent-mute); background: var(--accent-subtle); font-weight: 620; }
.panel-toolbar > button { padding: 6px 10px; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--bg-surface); color: var(--accent-ink); cursor: pointer; font-size: 11px; }
.panel-toolbar > button:disabled { cursor: wait; opacity: .5; }
.panel-hint { margin: 0; font-size: 11px; line-height: 1.6; color: var(--text-secondary); }
.panel-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.panel-fields label { display: grid; gap: 3px; font-size: 11px; color: var(--text-secondary); min-width: 0; }
.panel-fields input, .panel-fields select { width: 100%; box-sizing: border-box; padding: 6px 8px; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--bg-surface); color: var(--text-primary); font-size: 11px; }
.panel-status { margin: 0; padding: 7px 9px; border-radius: 6px; background: var(--bg-surface); color: var(--info-fg); font-size: 11px; line-height: 1.6; overflow-wrap: anywhere; }
.panel-status.is-warn { color: var(--warn-fg); background: var(--warn-bg); }
.panel-editor { display: grid; gap: 5px; font-size: 11px; color: var(--text-secondary); }
.panel-editor textarea { box-sizing: border-box; width: 100%; min-width: 0; resize: vertical; white-space: pre-wrap; overflow-wrap: anywhere; padding: 10px; border: 1px solid var(--border); border-radius: 6px; font: 12px/1.65 var(--font-sans); color: var(--text-primary); background: var(--bg-surface); }
.panel-actions { display: flex; gap: 8px; }
.panel-actions button { padding: 7px 10px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-surface); color: var(--accent-ink); cursor: pointer; font-size: 11px; }
.panel-actions button:disabled { opacity: .5; cursor: not-allowed; }
p[role='status']:not(.panel-status) { margin: 0; font-size: 11px; }
p[role='status'].is-error, p.is-error { color: var(--warn-fg); }
@media (max-width: 720px) { .panel-fields { grid-template-columns: 1fr; } }
</style>
