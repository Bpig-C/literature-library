<template>
  <div class="parse-overlay" @click.self="$emit('close')" @keydown.esc="$emit('close')">
  <section class="parse-queue" role="dialog" aria-modal="true" aria-label="后台解析">
    <header><h3>后台解析</h3><button @click="$emit('close')">关闭面板</button></header>
    <p>先确认原件和预算，再加入后台队列。关闭页面不会取消任务；入队不代表解析完成。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="!available">正在核对后台解析能力；不可用时不提交。</p>
    <template v-if="!receipt">
      <label>解析方式 <select v-model="backend" :disabled="busy" @change="invalidate">
        <option value="vlm">MinerU VLM（消耗云端额度）</option><option value="pymupdf">PyMuPDF（本地文本）</option>
      </select></label>
      <label v-if="sources.length">原件 <select v-model="sourceId" :disabled="busy" @change="invalidate">
        <option value="">仅自动选择唯一有效原件</option>
        <option v-for="s in sources" :key="s.id" :value="s.id">{{ s.original_name || s.id }} · {{ s.id }}</option>
      </select></label>
      <label><input v-model="reparse" type="checkbox" :disabled="busy" @change="invalidate">允许为已有同后端成果生成新解析（保留历史）</label>
      <button :disabled="busy || !available" @click="preview">预览解析范围</button>
      <template v-if="plan">
        <p>可处理 {{ plan.items.length }} 个原件；排除 {{ plan.excluded.length }} 个。</p>
        <ul><li v-for="item in plan.items" :key="item.source_file_id">{{ item.work_id }} · {{ item.source_file_id }}</li></ul>
        <ul><li v-for="item in plan.excluded" :key="item.source_file_id">{{ item.work_id }} · {{ reason(item.reason) }}</li></ul>
        <label>最多处理文件数 <input v-model.number="maxItems" type="number" min="1" :max="plan.items.length" :disabled="busy"></label>
        <label v-if="backend === 'vlm'">最多云端文件尝试次数 <input v-model.number="maxSubmissions" type="number" min="1" max="1000" :disabled="busy"></label>
        <label>最多累计页数 <input v-model.number="maxPages" type="number" min="1" :disabled="busy"></label>
        <p>页数执行前按 PDF 核算；这里的上限不是 MinerU 账户剩余额度。超预算会停止继续处理。</p>
        <button :disabled="busy || readOnly || !validBudget" @click="submit">确认预算并入队</button>
      </template>
    </template>
    <template v-else>
      <p>请求：{{ receipt.body.request_id }}<br>计划：{{ receipt.planId || '接收结果待核实' }}</p>
      <p v-if="!status">尚未确认任务状态，请查询或用原请求恢复，勿新建重复请求。</p>
      <button :disabled="busy || !receipt.planId" @click="refresh">查询任务状态</button>
      <button v-if="!receipt.enqueued" :disabled="busy || readOnly || !available" @click="submit">使用原请求继续入队</button>
      <template v-if="status">
        <p>{{ actionText(status.action) }}；本地预算占用：{{ status.budget?.reserved_items || 0 }} 个文件 / {{ status.budget?.reserved_pages || 0 }} 页</p>
        <p v-if="status.remaining?.length">还有 {{ status.remaining.length }} 个计划项未完成，本轮不会自动扩充预算。</p>
        <ul><li v-for="task in status.tasks" :key="task.id">
          {{ task.source_file_id }} · {{ task.state }} / {{ task.phase }}<br>任务：{{ task.id }}
          <span v-if="task.error_code"> · {{ task.error_code }}</span>
          <span v-if="task.tracking_upstream"> · 仍在跟踪已提交的云任务，不会立即取消云端执行</span>
        </li></ul>
        <p v-if="status.action === 'inspect_or_resume'">请按任务 ID 核对诊断后，通过 CLI 恢复原任务；不要重新提交解析。</p>
        <button v-if="canFinish" :disabled="busy" @click="finish">本轮已登记，完成并返回</button>
      </template>
    </template>
  </section>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { request } from '../api'
import { useRuntimeMode } from '../composables/useRuntimeMode'
const props = defineProps({ workIds: { type: Array, required: true }, sources: { type: Array, default: () => [] }, initialBackend: { type: String, default: 'vlm' }, initialReparse: Boolean })
const emit = defineEmits(['close', 'complete'])
const { readOnly } = useRuntimeMode()
// Parents key this component by its fixed selection; never retarget an in-flight request.
const scope = [...props.workIds].sort()
const storageKey = `litlib.parse.pending:${JSON.stringify(scope)}`
const backend = ref(props.initialBackend === 'pymupdf' ? 'pymupdf' : 'vlm'), reparse = ref(props.initialReparse)
const sourceId = ref(''), plan = ref(null), receipt = ref(null), status = ref(null)
const maxItems = ref(1), maxSubmissions = ref(1), maxPages = ref(100)
const busy = ref(false), error = ref(''), available = ref(false)
const canFinish = computed(() => status.value?.action === 'complete' ||
  (status.value?.tasks?.length && status.value.tasks.every(t => t.state === 'succeeded') &&
   status.value.budget?.reserved_items >= status.value.budget?.max_items))
let alive = true
onUnmounted(() => { alive = false })
const validBudget = computed(() => plan.value?.items.length && Number.isInteger(maxItems.value) && maxItems.value >= 1 && maxItems.value <= plan.value.items.length && Number.isInteger(maxPages.value) && maxPages.value > 0 && (backend.value !== 'vlm' || (Number.isInteger(maxSubmissions.value) && maxSubmissions.value >= 1 && maxSubmissions.value <= 1000)))
function invalidate() { plan.value = null }
function persist(value) { localStorage.setItem(storageKey, JSON.stringify(value)); receipt.value = value }
const reason = value => ({ select_exact_source: '存在多个原件，请在详情页明确选择 Source', target_backend_exists: '已有该后端成果', upstream_inspection_required: '旧云任务状态待核实', unfinished_job: '已有未完成任务', inactive: '已归档或隔离', missing_sha: '原件指纹缺失' }[value] || value)
const actionText = value => ({ queued: '已入队，尚未全部完成', complete: '全部完成并登记', inspect_or_resume: '需要核查或恢复', budget_exhausted: '达到预算上限', complete_with_abandoned: '含取消项，非全部成功', no_queued_items: '尚无入队任务' }[value] || value)
async function run(operation) {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { await operation() } catch (e) { if (alive) error.value = e.detail || e.message || String(e) }
  finally { if (alive) busy.value = false }
}
async function preview() {
  await run(async () => {
    plan.value = null
    const result = await request('/parse/plan', { method: 'POST', body: JSON.stringify({ work_ids: scope, source_file_ids: sourceId.value ? [sourceId.value] : [], backend: backend.value, reparse_completed: reparse.value, source_policy: 'single' }) })
    if (alive) { plan.value = result; maxItems.value = Math.min(result.items.length, 1) }
  })
}
async function submit() {
  if (readOnly.value || !available.value || (!receipt.value && !validBudget.value)) return
  await run(async () => {
    if (!receipt.value) {
      // Persist BEFORE the first write. A lost response reuses precisely this body/key.
      persist({ body: { plan: plan.value, request_id: `web-${crypto.randomUUID()}`, max_items: maxItems.value, max_submissions: backend.value === 'vlm' ? maxSubmissions.value : 0, max_pages: maxPages.value }, planId: null, enqueued: false })
    }
    let saved = receipt.value
    if (!saved.planId) {
      const accepted = await request('/parse/plans', { method: 'POST', body: JSON.stringify(saved.body) })
      saved = { ...saved, planId: accepted.plan_id }; persist(saved)
    }
    // Closing/switching the page never silently initiates the next write.
    if (!alive) return
    const result = await request(`/async/parse/plans/${encodeURIComponent(saved.planId)}/enqueue`, { method: 'POST', body: JSON.stringify({ max_tasks: saved.body.max_items }) })
    persist({ ...saved, enqueued: true })
    if (alive) status.value = result
  })
}
async function refresh() {
  if (!receipt.value?.planId) return
  await run(async () => {
    const result = await request(`/async/parse/plans/${encodeURIComponent(receipt.value.planId)}`)
    if (alive) status.value = result
  })
}
function finish() {
  if (!canFinish.value) return
  try { localStorage.removeItem(storageKey); emit('complete'); emit('close') }
  catch (e) { error.value = e.message }
}
onMounted(async () => {
  await run(async () => {
    const saved = localStorage.getItem(storageKey)
    if (saved) receipt.value = JSON.parse(saved)
    const capability = await request('/async/parse/scheduler')
    if (alive) available.value = capability.configured === true
  })
  if (alive && receipt.value?.planId) await refresh()
})
</script>

<style scoped>
.parse-overlay{position:fixed;inset:0;z-index:2000;background:#0006;display:flex;align-items:center;justify-content:center;padding:20px}
.parse-queue{box-sizing:border-box;width:760px;max-width:100%;max-height:85vh;overflow:auto;padding:18px;border:1px solid #a3beb3;border-radius:10px;background:var(--bg-page,#fff)}
header{display:flex;justify-content:space-between;align-items:center}label{display:block;margin:10px 0}button,input,select{font:inherit;padding:6px;margin:4px}li{overflow-wrap:anywhere;margin:6px 0}[role=alert]{color:#a53b24}button:disabled{opacity:.5}
</style>
