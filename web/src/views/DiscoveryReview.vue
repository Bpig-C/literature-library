<template>
  <div class="discovery-layout">
    <!-- Left: runs list -->
    <div class="runs-panel">
      <h1>发现检索</h1>
      <div class="mode-selector">
        <label>检索模式：</label>
        <select v-model="planMode" :disabled="busy">
          <option value="topic">topic（按主题）</option>
          <option value="name">name（按名称）</option>
          <option value="title">title（按标题）</option>
          <option value="url">url（按 URL）</option>
          <option value="doi" disabled>doi — 请走现有 collect</option>
          <option value="arxiv_id" disabled>arxiv_id — 请走现有 collect</option>
          <option value="github_url" disabled>github_url — 请走现有 collect</option>
        </select>
      </div>
      <div class="plan-input">
        <input v-if="planMode === 'topic'" v-model="planInput" placeholder="topic_id" />
        <input v-else-if="planMode === 'name'" v-model="planInput" placeholder="作者或机构名称" />
        <input v-else-if="planMode === 'title'" v-model="planInput" placeholder="论文标题关键词" />
        <input v-else-if="planMode === 'url'" v-model="planInput" placeholder="目标 URL" />
        <button class="btn-plan" :disabled="busy || !planInput.trim()" @click="doPlan">
          生成方案
        </button>
      </div>
      <div class="unsupported-hint">
        <span class="muted tiny">V1.1 暂不支持 DOI / arXiv ID / GitHub URL 发现，请使用现有采集流程。</span>
      </div>

      <div class="runs-header">
        <span>检索运行</span>
        <button class="btn-refresh" @click="loadRuns" :disabled="busy">刷新</button>
      </div>
      <div class="status-filter">
        <button v-for="s in RUN_STATUSES" :key="s.key" class="status-btn" :class="{ active: runStatusFilter === s.key }"
          @click="runStatusFilter = s.key; loadRuns()">{{ s.label }}</button>
      </div>
      <div class="runs-list">
        <div v-for="run in runs" :key="run.id" class="run-item"
          :class="{ selected: selectedRun?.id === run.id }"
          @click="selectRun(run)">
          <div class="run-title">{{ run.mode }}: {{ runSummary(run).slice(0, 40) || '—' }}</div>
          <div class="run-meta">
            <span class="run-status-badge" :class="run.status">{{ run.status }}</span>
            <span class="muted tiny">{{ run.created_at?.slice(0, 16) }}</span>
          </div>
        </div>
        <div v-if="!runs.length" class="empty muted">无检索运行记录</div>
      </div>
    </div>

    <!-- Middle: hits list -->
    <div class="hits-panel">
      <div class="hits-header">
        <h2 v-if="selectedRun">Hits — {{ selectedRun.mode }}: {{ runSummary(selectedRun).slice(0, 30) }}</h2>
        <h2 v-else>命中列表</h2>
        <button v-if="selectedRun" class="btn-run-action" :disabled="busy" @click="loadHits">
          刷新命中
        </button>
      </div>
      <div class="hit-status-filter">
        <button v-for="s in HIT_STATUSES" :key="s.key" class="status-btn" :class="{ active: hitStatusFilter === s.key }"
          @click="hitStatusFilter = s.key; loadHits()">{{ s.label }}</button>
      </div>
      <div class="hits-list">
        <div v-for="hit in hits" :key="hit.id" class="hit-item"
          :class="{ selected: selectedHit?.id === hit.id, [hit.review_status]: true }"
          @click="selectHit(hit)">
          <div class="hit-title">{{ hit.title || '(无标题)' }}</div>
          <div class="hit-meta">
            <span class="hit-source">{{ hit.source_type }}</span>
            <span v-if="hit.confidence" class="hit-conf" :class="confLevel(hit.confidence)">
              {{ confidenceLabel(hit.confidence) }}
            </span>
            <span class="hit-review-badge" :class="hit.review_status">{{ hitStatusLabel(hit.review_status) }}</span>
          </div>
          <div v-if="hit.reason" class="hit-reason muted tiny">{{ hit.reason?.slice(0, 80) }}</div>
        </div>
        <div v-if="selectedRun && !hits.length" class="empty muted">
          {{ hitStatusFilter === 'pending' ? '无待审命中' : '无命中记录' }}
        </div>
        <div v-if="!selectedRun" class="empty muted">请从左侧选择一个检索运行</div>
      </div>
      <div v-if="hitsTotal > hitsPerPage" class="hits-pagination">
        <button :disabled="hitsPage <= 1" @click="hitsPage--; loadHits()">上一页</button>
        <span>{{ hitsPage }} / {{ Math.ceil(hitsTotal / hitsPerPage) }}</span>
        <button :disabled="hitsPage >= Math.ceil(hitsTotal / hitsPerPage)" @click="hitsPage++; loadHits()">下一页</button>
      </div>
    </div>

    <!-- Right: hit detail -->
    <div class="detail-panel" v-if="selectedHit">
      <div class="detail-header">
        <h2>{{ selectedHit.title || '(无标题)' }}</h2>
        <span class="hit-review-badge large" :class="selectedHit.review_status">
          {{ hitStatusLabel(selectedHit.review_status) }}
        </span>
      </div>
      <table class="kv">
        <tr><th>URL</th><td><a :href="selectedHit.url" target="_blank" rel="noopener">{{ selectedHit.url || '—' }}</a></td></tr>
        <tr><th>来源类型</th><td>{{ selectedHit.source_type }}</td></tr>
        <tr><th>置信度</th><td>
          <span v-if="selectedHit.confidence" class="hit-conf large" :class="confLevel(selectedHit.confidence)">
            {{ confidenceLabel(selectedHit.confidence) }}
          </span>
          <span v-else class="muted">—</span>
        </td></tr>
        <tr><th>run</th><td>{{ selectedHit.run_id || '—' }}</td></tr>
        <tr><th>查询</th><td>{{ selectedHit.query || '—' }}</td></tr>
        <tr><th>匹配原因</th><td>{{ selectedHit.reason || '—' }}</td></tr>
        <tr v-if="selectedHit.snippet"><th>片段</th><td><pre class="snippet">{{ selectedHit.snippet }}</pre></td></tr>
        <tr><th>内容类型</th><td>{{ selectedHit.content_type || 'unknown' }}</td></tr>
        <tr><th>验证状态</th><td>{{ selectedHit.verification_status || 'unverified' }}</td></tr>
      </table>

      <!-- Raw meta toggle -->
      <div class="section">
        <h3 class="section-title" @click="showRawMeta = !showRawMeta">
          原始元数据 {{ showRawMeta ? '[-]' : '[+]' }}
        </h3>
        <pre v-if="showRawMeta" class="raw-json">{{ JSON.stringify(selectedHit.raw_json || {}, null, 2) }}</pre>
      </div>

      <!-- Review actions -->
      <div class="review-bar" v-if="selectedHit.review_status === 'pending'">
        <input v-model="reviewNote" placeholder="审核备注（可选）..." class="note-input" />
        <button class="btn-accept" :disabled="busy" @click="doAccept">接受</button>
        <button class="btn-reject" :disabled="busy" @click="doReject">拒绝</button>
      </div>
      <div v-else class="reviewed-info muted">
        已{{ hitStatusLabel(selectedHit.review_status) }}
        <span v-if="selectedHit.review_note"> — {{ selectedHit.review_note }}</span>
      </div>
    </div>
    <div class="detail-panel empty-state" v-else>
      <div class="muted">从中间栏选择一条命中查看详情</div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import {
  discoveryPlan,
  discoveryRun,
  getDiscoveryRuns,
  getDiscoveryHits,
  acceptDiscoveryHit,
  rejectDiscoveryHit,
} from '../api'

const route = useRoute()

const RUN_STATUSES = [
  { key: '', label: '全部' },
  { key: 'planned', label: '待执行' },
  { key: 'running', label: '运行中' },
  { key: 'succeeded', label: '已完成' },
  { key: 'failed', label: '失败' },
]

const HIT_STATUSES = [
  { key: 'pending', label: '待审' },
  { key: 'accepted', label: '已接受' },
  { key: 'rejected', label: '已拒绝' },
  { key: '', label: '全部' },
]

const busy = ref(false)
const planMode = ref('topic')
const planInput = ref('')
const runs = ref([])
const runStatusFilter = ref('')
const selectedRun = ref(null)
const hits = ref([])
const hitStatusFilter = ref('pending')
const selectedHit = ref(null)
const reviewNote = ref('')
const showRawMeta = ref(false)
const hitsPage = ref(1)
const hitsTotal = ref(0)
const hitsPerPage = 20



function hitStatusLabel(s) {
  return HIT_STATUSES.find(h => h.key === s)?.label || s
}

function confLevel(c) {
  if (typeof c === 'string') return c
  if (c >= 0.8) return 'high'
  if (c >= 0.5) return 'medium'
  return 'low'
}

function confidenceLabel(c) {
  if (typeof c === 'number') return `${(c * 100).toFixed(0)}%`
  return c || '—'
}

function runSummary(run) {
  const input = run?.input_json || {}
  const plan = run?.search_plan_json || {}
  return input.name || input.title || input.known_url || input.url || input.topic_id || (plan.queries || []).join(', ') || run?.id || ''
}

async function doPlan() {
  if (!planInput.value.trim() || busy.value) return
  busy.value = true
  try {
    const payload = { mode: planMode.value }
    const input = { mode: planMode.value }
    if (planMode.value === 'topic') payload.topic_id = planInput.value.trim()
    else if (planMode.value === 'name') payload.name = planInput.value.trim()
    else if (planMode.value === 'title') payload.title = planInput.value.trim()
    else if (planMode.value === 'url') payload.known_url = planInput.value.trim()
    if (planMode.value === 'topic') input.topic_id = planInput.value.trim()
    else if (planMode.value === 'name') input.name = planInput.value.trim()
    else if (planMode.value === 'title') input.title = planInput.value.trim()
    else if (planMode.value === 'url') input.known_url = planInput.value.trim()
    const plan = await discoveryPlan(payload)
    const run = await discoveryRun({
      mode: planMode.value,
      input,
      plan,
      executor: planMode.value === 'url' ? 'manual' : 'agent:web-access',
      topic_id: planMode.value === 'topic' ? planInput.value.trim() : null,
    })
    alert(`方案已生成并创建 run：${run.run_id}，${(plan.queries || []).length} 条查询`)
    await loadRuns()
  } catch (e) {
    alert(e.message)
  } finally {
    busy.value = false
  }
}

async function loadRuns() {
  const params = {}
  if (runStatusFilter.value) params.status = runStatusFilter.value
  const topicId = route.query.topic_id
  if (topicId) params.topic_id = topicId
  try {
    const res = await getDiscoveryRuns(params)
    runs.value = res.runs || []
  } catch {
    runs.value = []
  }
}

async function selectRun(run) {
  selectedRun.value = run
  hitStatusFilter.value = 'pending'
  hitsPage.value = 1
  selectedHit.value = null
  await loadHits()
}

async function loadHits() {
  if (!selectedRun.value) { hits.value = []; return }
  const params = {
    run_id: selectedRun.value.id,
    review_status: hitStatusFilter.value,
    page: hitsPage.value,
    per_page: hitsPerPage,
  }
  try {
    const res = await getDiscoveryHits(params)
    hits.value = res.hits || []
    hitsTotal.value = res.total || 0
  } catch {
    hits.value = []
    hitsTotal.value = 0
  }
}

function selectHit(hit) {
  selectedHit.value = hit
  reviewNote.value = ''
  showRawMeta.value = false
}

async function doAccept() {
  if (!selectedHit.value || busy.value) return
  busy.value = true
  try {
    await acceptDiscoveryHit(selectedHit.value.id, reviewNote.value)
    selectedHit.value = { ...selectedHit.value, review_status: 'accepted' }
    await loadHits()
  } catch (e) {
    alert(e.message)
  } finally {
    busy.value = false
  }
}

async function doReject() {
  if (!selectedHit.value || busy.value) return
  busy.value = true
  try {
    await rejectDiscoveryHit(selectedHit.value.id, reviewNote.value)
    selectedHit.value = { ...selectedHit.value, review_status: 'rejected', review_note: reviewNote.value }
    await loadHits()
  } catch (e) {
    alert(e.message)
  } finally {
    busy.value = false
  }
}

onMounted(() => {
  const topicId = route.query.topic_id
  if (topicId) planInput.value = topicId
  loadRuns()
})
</script>

<style scoped>
.discovery-layout { display: grid; grid-template-columns: 300px 1fr 1fr; gap: 0; height: calc(100vh - 40px); }
.runs-panel, .hits-panel { min-width: 0; border-right: 1px solid var(--line); overflow-y: auto; padding: 16px; background: var(--panel); }
.detail-panel { min-width: 0; overflow-y: auto; padding: 20px 24px; }
.detail-panel.empty-state { display: flex; align-items: center; justify-content: center; color: var(--muted); }

h1 { font-size: 18px; margin-bottom: 12px; }
h2 { font-size: 15px; margin-bottom: 8px; }

/* Mode selector */
.mode-selector { margin-bottom: 8px; }
.mode-selector label { font-size: 12px; color: var(--muted); margin-bottom: 4px; display: block; }
.mode-selector select, .plan-input input {
  width: 100%; padding: 6px 8px; border: 1px solid var(--line); border-radius: 4px;
  font-size: 13px; font-family: inherit; background: var(--panel);
}
.plan-input { display: flex; gap: 6px; margin-bottom: 8px; }
.plan-input input { flex: 1; }
.btn-plan {
  padding: 6px 12px; border: 1px solid #7c3aed; border-radius: 4px;
  background: #ede9fe; color: #6d28d9; cursor: pointer; font-size: 12px; white-space: nowrap;
}
.btn-plan:disabled { opacity: 0.5; cursor: not-allowed; }
.unsupported-hint { margin-bottom: 12px; padding: 6px 8px; background: #fef9c3; border-radius: 4px; }

/* Runs header */
.runs-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-weight: 600; }
.btn-refresh {
  padding: 3px 8px; border: 1px solid var(--line); border-radius: 4px;
  background: var(--panel); cursor: pointer; font-size: 11px;
}

/* Status filter */
.status-filter, .hit-status-filter { display: flex; gap: 4px; margin-bottom: 8px; flex-wrap: wrap; }
.status-btn {
  padding: 2px 8px; border: 1px solid var(--line); border-radius: 4px;
  font-size: 11px; background: #fff; cursor: pointer; transition: all .15s;
}
.status-btn:hover { border-color: var(--accent); }
.status-btn.active { font-weight: 600; border-color: var(--accent); background: #eef5ff; }

/* Runs list */
.runs-list { display: flex; flex-direction: column; gap: 4px; }
.run-item { padding: 8px 10px; border: 1px solid transparent; border-radius: 6px; cursor: pointer; }
.run-item:hover { background: var(--bg); }
.run-item.selected { background: #eef5ff; border-color: var(--accent); }
.run-title { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.run-meta { display: flex; gap: 6px; align-items: center; margin-top: 2px; }
.run-status-badge { font-size: 10px; padding: 1px 6px; border-radius: 10px; background: var(--chip); }
.run-status-badge.planned { background: #fef9c3; color: #92400e; }
.run-status-badge.running { background: #e0f2fe; color: #0369a1; }
.run-status-badge.succeeded { background: #dcfce7; color: #15803d; }
.run-status-badge.failed { background: #fee2e2; color: #991b1b; }

/* Hits panel */
.hits-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.btn-run-action {
  padding: 4px 10px; border: 1px solid var(--accent); border-radius: 4px;
  background: var(--accent); color: #fff; cursor: pointer; font-size: 12px;
}
.btn-run-action:disabled { opacity: 0.5; cursor: not-allowed; }

/* Hits list */
.hits-list { display: flex; flex-direction: column; gap: 4px; }
.hit-item { padding: 8px 10px; border: 1px solid transparent; border-radius: 6px; cursor: pointer; }
.hit-item:hover { background: var(--bg); }
.hit-item.selected { background: #eef5ff; border-color: var(--accent); }
.hit-item.accepted { border-left: 3px solid #16833a; }
.hit-item.rejected { border-left: 3px solid #c32f27; opacity: 0.7; }
.hit-title { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.hit-meta { display: flex; gap: 6px; align-items: center; margin-top: 2px; font-size: 11px; }
.hit-source { color: var(--muted); }
.hit-conf { font-size: 10px; padding: 1px 5px; border-radius: 8px; }
.hit-conf.high { background: #dcfce7; color: #15803d; }
.hit-conf.medium { background: #fef9c3; color: #92400e; }
.hit-conf.low { background: #fee2e2; color: #991b1b; }
.hit-conf.large { font-size: 12px; padding: 2px 8px; }
.hit-review-badge { font-size: 10px; padding: 1px 6px; border-radius: 10px; background: var(--chip); }
.hit-review-badge.large { font-size: 12px; padding: 3px 10px; }
.hit-review-badge.pending { background: #fef9c3; color: #92400e; }
.hit-review-badge.accepted { background: #dcfce7; color: #15803d; }
.hit-review-badge.rejected { background: #fee2e2; color: #991b1b; }
.hit-reason { margin-top: 2px; line-height: 1.3; }

/* Hits pagination */
.hits-pagination { display: flex; gap: 8px; align-items: center; justify-content: center; margin-top: 10px; font-size: 12px; }
.hits-pagination button { padding: 3px 10px; border: 1px solid var(--line); border-radius: 4px; background: #fff; cursor: pointer; font-size: 12px; }
.hits-pagination button:disabled { opacity: 0.4; cursor: not-allowed; }

/* Detail panel */
.detail-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; }
table.kv { width: 100%; border-collapse: collapse; margin-bottom: 12px; }
table.kv th { text-align: left; width: 100px; color: var(--muted); padding: 4px 8px; vertical-align: top; font-size: 12px; }
table.kv td { padding: 4px 8px; font-size: 13px; word-break: break-word; }
.snippet { background: var(--bg); padding: 6px; border-radius: 4px; font-size: 12px; white-space: pre-wrap; margin: 0; max-height: 200px; overflow: auto; }

/* Section toggle */
.section { margin-bottom: 12px; }
.section-title { font-size: 12px; text-transform: uppercase; color: #475467; cursor: pointer; user-select: none; margin-bottom: 6px; }
.raw-json { font-size: 11px; font-family: Consolas, monospace; background: var(--bg); border: 1px solid var(--line); border-radius: 6px; padding: 10px; max-height: 300px; overflow: auto; white-space: pre-wrap; word-break: break-word; }

/* Review bar */
.review-bar { display: flex; gap: 8px; align-items: center; padding: 12px 0; border-top: 1px solid var(--line); flex-wrap: wrap; }
.note-input { flex: 1 1 150px; min-width: 150px; height: 34px; border: 1px solid var(--line); border-radius: 6px; padding: 0 10px; font: inherit; }
.btn-accept, .btn-reject { flex-shrink: 0; height: 34px; padding: 0 16px; border: none; border-radius: 6px; cursor: pointer; font: inherit; font-weight: 600; }
.btn-accept { background: #16833a; color: #fff; }
.btn-accept:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-reject { background: #c32f27; color: #fff; }
.btn-reject:disabled { opacity: 0.5; cursor: not-allowed; }
.reviewed-info { padding: 12px 0; border-top: 1px solid var(--line); }

/* Utility */
.muted { color: var(--muted); }
.tiny { font-size: 11px; }
.empty { padding: 20px; text-align: center; }

@media (max-width: 1100px) {
  .discovery-layout { grid-template-columns: 260px 1fr; }
  .detail-panel { grid-column: 1 / -1; border-top: 1px solid var(--line); }
}
@media (max-width: 768px) {
  .discovery-layout { grid-template-columns: 1fr; }
  .runs-panel, .hits-panel { border-right: none; border-bottom: 1px solid var(--line); }
}
</style>
