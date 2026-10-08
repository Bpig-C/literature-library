<template>
  <div class="batch-agent-root">
    <button v-if="!open" type="button" class="batch-agent-fab" data-testid="batch-agent-fab"
      title="生成当前研究批次的批量 Agent 工单" @click="open = true">
      <span>⚡</span><span>批次 Agent 任务</span>
    </button>
    <section v-show="open" class="batch-agent-panel" data-testid="batch-agent-panel">
      <header>
        <div><strong>批次 Agent 任务</strong><small>只生成可编辑提示词，不领取任务、不写入研究库</small></div>
        <button type="button" aria-label="收起批次 Agent 任务面板" @click="open = false">×</button>
      </header>
      <label>运行方式
        <select v-model="mode">
          <option v-for="item in BATCH_AGENT_TASK_MODES" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
      </label>
      <p class="mode-note">{{ modeHelp }}</p>
      <label>本轮特别关注（可选）
        <textarea v-model="focus" rows="2" placeholder="例如：只补参考文献候选，并核查 D 是否固定当前 A" />
      </label>
      <p v-if="status" class="status" :class="{ error: failed }">{{ status }}</p>
      <label>交给本地 Agent 的批次工单
        <textarea v-model="prompt" rows="18" data-testid="batch-agent-prompt" @input="edited = true" />
      </label>
      <div class="actions">
        <button type="button" :disabled="loading" @click="generate">{{ prompt ? '重新生成' : '生成批次提示词' }}</button>
        <button type="button" :disabled="loading || !prompt" @click="copy">复制提示词</button>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { queryResearch } from '../../api'
import { BATCH_AGENT_TASK_MODES, buildResearchBatchAgentPrompt } from '../../researchAgentPrompt'

const props = defineProps({ batchId: { type: String, required: true } })
const open = ref(false)
const mode = ref('resume')
const focus = ref('')
const prompt = ref('')
const status = ref('')
const failed = ref(false)
const loading = ref(false)
const edited = ref(false)
let generation = 0

const MODE_HELP = {
  full: '适合已建批、需形成 C 原文、D 解释及 R 引用的新批次；A 元数据在 Work 级单独安排。',
  resume: '逐篇检查 C/D/R 与 A 依赖，只补缺失、待补全、待审或失效部分；A 内容走 Work 级工单。',
  'metadata-references': '保留稳定 C/D，补 R 参考文献并核查 A 依赖；A 抽取或补全请到元数据工作台另生成工单。',
  'targeted-revision': '适合字段、本体、定义或反馈变化；先做影响分析，只修订受影响部分。',
  'review-only': '只安排独立 Agent 核查并登记反馈，不由核查者改写后自审。',
}
const modeHelp = computed(() => MODE_HELP[mode.value])

watch(() => props.batchId, () => {
  generation++
  if (edited.value && prompt.value) status.value = '批次已变化，当前编辑稿已保留但上下文过期，请重新生成。'
  else prompt.value = ''
})
watch([mode, focus], () => {
  generation++
  if (prompt.value) status.value = '运行方式或关注点已变化，旧提示词已过期，请重新生成。'
})

async function generate() {
  const ticket = ++generation
  loading.value = true
  status.value = ''
  failed.value = false
  try {
    const [overviewResponse, schemaResponse, query] = await Promise.all([
      fetch('/api/overview'),
      fetch('/api/research/schema'),
      queryResearch({ batch_id: props.batchId, limit: 200 }),
    ])
    if (!overviewResponse.ok) throw new Error(`批次目录 HTTP ${overviewResponse.status}`)
    if (!schemaResponse.ok) throw new Error(`研究环境 HTTP ${schemaResponse.status}`)
    const overview = await overviewResponse.json()
    const schema = await schemaResponse.json()
    if (ticket !== generation) return
    const batch = overview.research?.batches?.find(item => item.id === props.batchId)
    if (!batch) throw new Error('当前批次不在正式批次目录中，不能猜测发布包和轮次关系。')
    const rows = query.items || []
    prompt.value = buildResearchBatchAgentPrompt(batch, rows, schema, window.location.origin, {
      mode: mode.value, focus: focus.value, total: query.total, batchId: props.batchId,
    })
    edited.value = false
    status.value = `已读取批次 ${batch.name || batch.id} 的 ${rows.length}/${query.total ?? rows.length} 条当前卡片；执行时仍须重新生成正式任务包。`
  } catch (error) {
    failed.value = true
    status.value = `生成失败：${error?.message || '读取错误'}。未生成半真半假的工单。`
  } finally {
    if (ticket === generation) loading.value = false
  }
}

async function copy() {
  try {
    await navigator.clipboard.writeText(prompt.value)
    status.value = '已复制，可交给本地 Agent。复制不表示任务已经领取或开始。'
    failed.value = false
  } catch {
    status.value = '浏览器未允许自动复制，请在文本框内全选后手动复制。'
    failed.value = true
  }
}

defineExpose({ generate })
</script>

<style scoped>
.batch-agent-root{position:fixed;right:22px;bottom:22px;z-index:72;display:flex;flex-direction:column;align-items:flex-end}.batch-agent-fab{display:flex;align-items:center;gap:7px;padding:10px 16px;border:1px solid var(--accent-mute);border-radius:999px;background:var(--accent-subtle,var(--bg-surface));color:var(--accent-ink);font-size:12px;font-weight:620;box-shadow:0 4px 14px rgba(0,0,0,.14);cursor:pointer}.batch-agent-panel{display:grid;gap:9px;width:min(720px,calc(100vw - 32px));max-height:min(82dvh,920px);overflow:auto;padding:14px;border:1px solid var(--border-strong);border-radius:var(--radius-lg);background:var(--bg-surface);box-shadow:0 10px 30px rgba(0,0,0,.18)}header{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}header div{display:grid;gap:3px}header strong{font-size:14px}header small{color:var(--text-tertiary);font-size:10px}header button{padding:3px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg-page);cursor:pointer}label{display:grid;gap:4px;color:var(--text-secondary);font-size:11px}select,textarea{box-sizing:border-box;width:100%;padding:8px;border:1px solid var(--border-strong);border-radius:6px;background:var(--bg-surface);color:var(--text-primary);font:12px/1.6 var(--font-sans)}textarea{resize:vertical}.mode-note,.status{margin:0;padding:7px 9px;border-radius:6px;background:var(--bg-page);color:var(--text-secondary);font-size:11px;line-height:1.6}.status.error{color:var(--warn-fg);background:var(--warn-bg)}.actions{display:flex;gap:8px}.actions button{padding:7px 11px;border:1px solid var(--border);border-radius:6px;background:var(--bg-page);color:var(--accent-ink);cursor:pointer}.actions button:disabled{opacity:.5;cursor:not-allowed}
</style>
