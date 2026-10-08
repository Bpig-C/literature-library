<template>
  <div class="discovery-layout">
    <!-- Left: runs panel with tab switch -->
    <div class="runs-panel">
      <h1>发现检索</h1>

      <!-- Tab bar: 新建检索 / 运行记录 -->
      <div class="left-tab-bar">
        <button class="tab-btn" :class="{ active: leftTab === 'form' }" @click="leftTab = 'form'">新建检索</button>
        <button class="tab-btn" :class="{ active: leftTab === 'runs' }" @click="leftTab = 'runs'; loadRuns()">运行记录</button>
      </div>

      <!-- ===== Tab 1: 新建检索（表单区域）===== -->
      <div v-if="leftTab === 'form'" class="tab-content">
      <div class="input-mode-toggle">
        <button class="mode-toggle-btn" :class="{ active: inputMode === 'composite' }" @click="inputMode = 'composite'">复合表单</button>
        <button class="mode-toggle-btn" :class="{ active: inputMode === 'quick' }" @click="inputMode = 'quick'">快速模式</button>
      </div>

      <!-- Composite Form (default) -->
      <div v-if="inputMode === 'composite'" class="composite-form">
        <div class="form-row">
          <label class="form-label">关联主题（可选）</label>
          <select v-model="composite.topic_id" class="form-select">
            <option value="">不关联主题</option>
            <option v-for="t in topics" :key="t.id" :value="t.id">
              {{ t.name }}（{{ t.map_status }}）
            </option>
          </select>
        </div>
        <div class="form-row">
          <label class="form-label">Names / Known Names</label>
          <textarea v-model="composite.names" placeholder="作者或机构名称，每行一个 (可选)" class="form-textarea"></textarea>
        </div>
        <div class="form-row">
          <label class="form-label">Titles / Known Titles</label>
          <textarea v-model="composite.titles" placeholder="论文标题关键词或已知标题，每行一个 (可选)" class="form-textarea"></textarea>
        </div>
        <div class="form-row">
          <label class="form-label">Authors</label>
          <textarea v-model="composite.authors" placeholder="作者姓名，每行一个 (可选)" class="form-textarea"></textarea>
        </div>
        <div class="form-row">
          <label class="form-label">Institutions</label>
          <textarea v-model="composite.institutions" placeholder="机构名称，每行一个 (可选)" class="form-textarea"></textarea>
        </div>
        <div class="form-row">
          <label class="form-label">Keywords</label>
          <textarea v-model="composite.keywords" placeholder="检索关键词，每行一个 (可选)" class="form-textarea"></textarea>
        </div>
        <div class="form-row">
          <label class="form-label">Known URLs</label>
          <textarea v-model="composite.known_urls" placeholder="已知 URL，每行一个 (可选)" class="form-textarea"></textarea>
        </div>
        <div class="form-row">
          <label class="form-label">Preferred Domains</label>
          <textarea v-model="composite.preferred_domains" placeholder="优先域名，每行一个，如 arxiv.org (可选)" class="form-textarea"></textarea>
        </div>
        <div class="form-row">
          <label class="form-label">Exclude Terms</label>
          <textarea v-model="composite.exclude_terms" placeholder="排除词，每行一个 (可选)" class="form-textarea"></textarea>
        </div>
        <div class="form-row form-row-inline">
          <label class="form-label">Artifact Type Hint</label>
          <select v-model="composite.artifact_type_hint" class="form-select">
            <option value="">unknown</option>
            <option value="system_card">system_card</option>
            <option value="model_card">model_card</option>
            <option value="technical_report">technical_report</option>
            <option value="research_article">research_article</option>
          </select>
        </div>
        <div class="form-row form-row-inline">
          <label class="form-label">Max Results</label>
          <input type="number" v-model.number="composite.max_results" min="1" max="100" class="form-input form-input-xs" />
        </div>
        <div class="form-row">
          <label class="form-label">Freeform Note / Research Context</label>
          <textarea v-model="composite.freeform_note" placeholder="自由备注、研究背景或其他上下文信息 (可选)" class="form-textarea form-textarea-lg"></textarea>
        </div>
        <button class="btn-plan btn-plan-composite" :disabled="busy || !hasCompositeInput" @click="doCompositePlan">
          生成方案
        </button>
      </div>

      <!-- Quick Mode (legacy) -->
      <div v-else class="quick-form">
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
      </div>
      </div><!-- end tab-content form -->

      <!-- ===== Tab 2: 运行记录 ===== -->
      <div v-else class="tab-content">
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
          <div class="run-id">{{ run.id }}</div>
          <div class="run-meta">
            <StatusBadge :status="run.status" size="small" />
            <span class="muted tiny">{{ run.created_at?.slice(0, 16) }}</span>
          </div>
        </div>
        <EmptyState v-if="!runs.length" icon="data" title="无检索运行记录" />
      </div>
      </div><!-- end tab-content runs -->
    </div>

    <!-- Middle: hits list -->
    <div class="hits-panel">
      <div class="hits-header">
        <h2 v-if="selectedRun">Hits — {{ selectedRun.mode }}: {{ runSummary(selectedRun).slice(0, 30) }}</h2>
        <h2 v-else>命中列表</h2>
        <div v-if="selectedRun" class="run-actions">
          <button class="btn-run-action secondary" :disabled="busy" @click="copyRunPrompt">
            复制 agent 指令
          </button>
          <button class="btn-run-action" :disabled="busy" @click="loadHits">
            刷新命中
          </button>
        </div>
      </div>
      <div v-if="selectedRun" class="selected-run-info">
        <span class="muted tiny">run id</span>
        <code>{{ selectedRun.id }}</code>
        <StatusBadge :status="selectedRun.status" size="small" />
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
            <StatusBadge :status="hit.review_status" size="small" :label="hitStatusLabel(hit.review_status)" />
          </div>
          <div v-if="hit.reason" class="hit-reason muted tiny">{{ hit.reason?.slice(0, 80) }}</div>
        </div>
        <EmptyState
          v-if="selectedRun && !hits.length"
          icon="search"
          :title="hitStatusFilter === 'pending' ? '无待审命中' : '无命中记录'"
        />
        <EmptyState v-if="!selectedRun" icon="inbox" title="请从左侧选择一个检索运行" />
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
        <StatusBadge :status="selectedHit.review_status" size="large" :label="hitStatusLabel(selectedHit.review_status)" />
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
  discoveryCompositePlan,
  discoveryRun,
  getDiscoveryRuns,
  getDiscoveryHits,
  acceptDiscoveryHit,
  rejectDiscoveryHit,
  getIntakeTopics,
} from '../api'
import { showError } from '../error-handler'
import { useNextStep } from '../composables/useNextStep'
import StatusBadge from '../components/StatusBadge.vue'
import EmptyState from '../components/EmptyState.vue'

const route = useRoute()
const { notifyNext } = useNextStep()

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
const leftTab = ref('form')  // 'form' | 'runs' — 左侧面板 Tab 切换
const inputMode = ref('composite')  // 'composite' or 'quick'
const planMode = ref('topic')
const planInput = ref('')
const composite = ref({
  topic_id: '',
  names: '',
  titles: '',
  authors: '',
  institutions: '',
  keywords: '',
  known_urls: '',
  preferred_domains: '',
  exclude_terms: '',
  artifact_type_hint: '',
  max_results: 20,
  freeform_note: '',
})
const runs = ref([])
const runStatusFilter = ref('')
const selectedRun = ref(null)
const hits = ref([])
const hitStatusFilter = ref('pending')
const selectedHit = ref(null)
const reviewNote = ref('')
const showRawMeta = ref(false)
const topics = ref([])
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

async function loadTopics() {
  try {
    const data = await getIntakeTopics({ per_page: 200 })
    topics.value = data.topics || data || []
  } catch (e) { topics.value = [] }
}

function runSummary(run) {
  const input = run?.input_json || {}
  const plan = run?.search_plan_json || {}
  // 如果有关联主题ID，尝试解析成名称
  const topicId = input.topic_id || plan.topic_id
  if (topicId) {
    const topic = topics.value.find(t => t.id === topicId)
    if (topic) return `[${topic.name}]` + (input.name || input.title || input.known_url || input.url || (plan.queries || []).join(', ') || '')
  }
  return input.name || input.title || input.known_url || input.url || input.topic_id || (plan.queries || []).join(', ') || run?.id || ''
}

function hasCompositeInput() {
  const c = composite.value
  return !!(c.topic_id?.trim() ||
    c.names?.trim() ||
    c.titles?.trim() ||
    c.authors?.trim() ||
    c.institutions?.trim() ||
    c.keywords?.trim() ||
    c.known_urls?.trim() ||
    c.preferred_domains?.trim() ||
    c.exclude_terms?.trim() ||
    c.freeform_note?.trim())
}

async function doCompositePlan() {
  if (!hasCompositeInput() || busy.value) return
  busy.value = true
  try {
    const c = composite.value
    const payload = {}
    if (c.topic_id?.trim()) payload.topic_id = c.topic_id.trim()
    if (c.names?.trim()) payload.names = c.names.trim().split('\n').map(s => s.trim()).filter(Boolean)
    if (c.titles?.trim()) payload.titles = c.titles.trim().split('\n').map(s => s.trim()).filter(Boolean)
    if (c.authors?.trim()) payload.authors = c.authors.trim().split('\n').map(s => s.trim()).filter(Boolean)
    if (c.institutions?.trim()) payload.institutions = c.institutions.trim().split('\n').map(s => s.trim()).filter(Boolean)
    if (c.keywords?.trim()) payload.keywords = c.keywords.trim().split('\n').map(s => s.trim()).filter(Boolean)
    if (c.known_urls?.trim()) payload.known_urls = c.known_urls.trim().split('\n').map(s => s.trim()).filter(Boolean)
    if (c.preferred_domains?.trim()) payload.preferred_domains = c.preferred_domains.trim().split('\n').map(s => s.trim()).filter(Boolean)
    if (c.exclude_terms?.trim()) payload.exclude_terms = c.exclude_terms.trim().split('\n').map(s => s.trim()).filter(Boolean)
    if (c.artifact_type_hint) payload.artifact_type_hint = c.artifact_type_hint
    if (c.max_results && c.max_results !== 20) payload.max_results = c.max_results
    if (c.freeform_note?.trim()) payload.freeform_note = c.freeform_note.trim()

    // Build input signals for the run
    const inputSignals = { ...payload, mode: 'composite' }

    const plan = await discoveryCompositePlan(payload)
    const run = await discoveryRun({
      mode: 'composite',
      input: inputSignals,
      plan,
      executor: 'agent:web-access',
      topic_id: payload.topic_id || undefined,
    })
    window.__naive_message?.success(`复合方案已生成并创建 run：${run.run_id}，${(plan.queries || []).length} 条查询`)
    await loadRuns()
  } catch (e) {
    showError(e)
  } finally {
    busy.value = false
  }
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
    window.__naive_message?.success(`方案已生成并创建 run：${run.run_id}，${(plan.queries || []).length} 条查询`)
    await loadRuns()
  } catch (e) {
    showError(e)
  } finally {
    busy.value = false
  }
}

async function loadRuns() {
  const params = {}
  if (runStatusFilter.value) params.status = runStatusFilter.value
  const topicId = route.query.topic_id
  if (topicId) params.topic_id = topicId
  console.log('[DiscoveryReview] loadRuns params:', params)
  try {
    const res = await getDiscoveryRuns(params)
    console.log('[DiscoveryReview] runs loaded:', res.runs?.length || 0)
    runs.value = res.runs || []
  } catch (e) {
    console.error('[DiscoveryReview] loadRuns failed:', e)
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

function buildRunPrompt(run) {
  const plan = run.search_plan_json || {}
  const inputSignals = plan.input_signals || run.input_json || {}
  const isComposite = plan.mode === 'composite'

  return `你是 literature_library 的 discovery-search agent。
工作目录：D:\\02_academic\\doctoral\\literature_library
必须先读取并遵循：docs/discovery-agent-protocol.md

任务：
1. 获取 discovery run：run_id=${run.id}
2. 读取 run.search_plan_json，理解完整的检索策略和输入信号
${plan.reasoning ? `3. 策略背景：${plan.reasoning}` : ''}
4. 严格按照 plan 中的 queries、source_hints、preferred_domains、exclude_terms、max_results 执行检索
5. 每条命中必须包含 url 或 title；优先提供 url
6. 每条命中输出 title、url、source_type、snippet、reason、confidence、query、primary_source、content_type、verification_status
7. 【强制】必须加载 web-access skill 并严格遵循其指引执行检索；不得绕过 skill 自行探索
8. 通过 POST /api/discovery/runs/${run.id}/hits 回填 JSON 数组
9. 回填后立即停止。禁止 accept、promote、写 works、改 ontology vocab、下载 PDF 或摄入任何文件

质量约束：
- 优先官方域名、机构发布页、项目主页、PDF/HTML 原文页
- 不登录，不绕过访问控制，不编造 URL
- 无法确认的结果 confidence=low，并说明原因
- 已知 URLs 应直接验证而不是重新搜索

错误处理与噪声控制：
- 如果部分查询有结果但整体信号弱：只回填有明确来源匹配的 hit（至少 2 个独立信号匹配才标记 medium 以上 confidence）
- 如果所有查询均无结果或噪声极高：回填空数组并在 reason 中解释失败原因（如"关键词过于宽泛"、"领域内无公开资料"）
- 如果 web-access skill 不可用：立即停止，在回填中报告错误——不得降级为编造 URL
- 回填后校验：确认没有 hit 的 title/url 包含任何 exclude_term；如有则移除该 hit
${isComposite ? `
Composite 模式特殊要求：
- 综合利用 names/titles/authors/institutions/keywords 多种信号设计组合查询
- 利用 preferred_domains 和 exclude_terms 缩小搜索范围
- 在每条 hit 的 reasoning 中记录匹配了哪些输入信号
- 对于 known_urls 仅作为 source hint 验证，不自动创建 hit` : ''}`
}

async function copyRunPrompt() {
  if (!selectedRun.value) return
  const text = buildRunPrompt(selectedRun.value)
  try {
    await navigator.clipboard.writeText(text)
    window.__naive_message?.success(`已复制 agent 指令：${selectedRun.value.id}`)
  } catch {
    window.prompt('复制以下 agent 指令', text)
  }
}

async function doAccept() {
  if (!selectedHit.value || busy.value) return
  busy.value = true
  try {
    await acceptDiscoveryHit(selectedHit.value.id, reviewNote.value)
    selectedHit.value = { ...selectedHit.value, review_status: 'accepted' }
    await loadHits()
    // 接力引导：accept 后进入 intake 候选池，提示去采集审核
    notifyNext('已接受命中，候选已进入采集闸门', { label: '去采集审核', to: '/intake' })
  } catch (e) {
    showError(e)
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
    showError(e)
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  const topicId = route.query.topic_id
  if (topicId) planInput.value = topicId
  await loadRuns()
  loadTopics()
  // 支持 /discovery?run_id= 深链（如 Pipeline 迷你列表跳转）
  const runId = route.query.run_id
  if (runId) {
    const run = runs.value.find(r => r.id === runId)
    if (run) {
      leftTab.value = 'runs'
      await selectRun(run)
    }
  }
})
</script>

<style scoped>
.discovery-layout { display: grid; grid-template-columns: 300px 1fr 1fr; gap: 0; height: calc(100vh - 40px); }
.runs-panel { min-width: 0; border-right: 1px solid var(--border); padding: 16px; background: var(--bg-surface); display: flex; flex-direction: column; overflow: hidden; }
.hits-panel { min-width: 0; border-right: 1px solid var(--border); overflow-y: auto; padding: 16px; background: var(--bg-surface); }
.detail-panel { min-width: 0; overflow-y: auto; padding: 20px 24px; }
.detail-panel.empty-state { display: flex; align-items: center; justify-content: center; color: var(--text-secondary); }

h1 { font-size: 18px; margin-bottom: 12px; }
h2 { font-size: 15px; margin-bottom: 8px; }

/* Left panel tab bar */
.left-tab-bar {
  display: flex; gap: 0; margin-bottom: 10px;
  border: 1px solid var(--border); border-radius: var(--radius-lg); overflow: hidden;
}
.tab-btn {
  flex: 1; padding: 6px 12px; border: none; background: var(--bg-surface);
  cursor: pointer; font-size: 13px; font-weight: 500; color: var(--text-secondary);
  transition: all .15s;
}
.tab-btn:hover { background: var(--bg-muted); color: var(--text-primary); }
.tab-btn.active {
  background: var(--accent-subtle); color: var(--accent);
  font-weight: 600; border-bottom: 2px solid var(--accent);
}
.tab-content {
  overflow-y: auto; flex: 1;
}

/* Mode toggle */
.input-mode-toggle { display: flex; gap: 4px; margin-bottom: 10px; }
.mode-toggle-btn {
  flex: 1; padding: 5px 8px; border: 1px solid var(--border); border-radius: 4px;
  background: var(--bg-surface); cursor: pointer; font-size: 12px; transition: all .15s;
}
.mode-toggle-btn:hover { border-color: var(--accent); }
.mode-toggle-btn.active { font-weight: 600; border-color: var(--accent); background: var(--selected-bg); color: var(--accent); }

/* Composite form */
.composite-form { margin-bottom: 10px; }
.form-row { margin-bottom: 8px; }
.form-row-inline { display: flex; align-items: center; gap: 8px; }
.form-label {
  display: block; font-size: 11px; color: var(--text-secondary); margin-bottom: 3px;
  font-weight: 500;
}
.form-input, .form-select, .form-textarea {
  width: 100%; border: 1px solid var(--border); border-radius: 4px;
  font-size: 13px; font-family: inherit; background: var(--bg-surface);
  padding: 6px 8px; box-sizing: border-box;
}
.form-input:focus, .form-select:focus, .form-textarea:focus {
  outline: none; border-color: var(--accent);
}
.form-input-sm { height: 32px; }
.form-input-xs { width: 80px; height: 32px; }
.form-textarea { min-height: 80px; max-height: 120px; resize: vertical; }
.form-textarea-lg { min-height: 100px; max-height: 150px; }
.form-select { height: 32px; }
.btn-plan-composite {
  width: 100%; margin-top: 8px; padding: 8px 16px; border: 1px solid var(--accent);
  border-radius: var(--radius-md); background: var(--accent-subtle); color: var(--accent); cursor: pointer;
  font-size: 13px; font-weight: 600;
}
.btn-plan-composite:disabled { opacity: 0.5; cursor: not-allowed; }

/* Quick form (legacy) */
.quick-form { margin-bottom: 10px; }
.mode-selector { margin-bottom: 8px; }
.mode-selector label { font-size: 12px; color: var(--text-secondary); margin-bottom: 4px; display: block; }
.mode-selector select, .plan-input input {
  width: 100%; padding: 6px 8px; border: 1px solid var(--border); border-radius: 4px;
  font-size: 13px; font-family: inherit; background: var(--bg-surface);
}
.plan-input { display: flex; gap: 6px; margin-bottom: 8px; }
.plan-input input { flex: 1; }
.btn-plan {
  padding: 6px 12px; border: 1px solid var(--accent); border-radius: var(--radius-md);
  background: var(--accent-subtle); color: var(--accent); cursor: pointer; font-size: 12px; white-space: nowrap;
}
.btn-plan:disabled { opacity: 0.5; cursor: not-allowed; }
.unsupported-hint { margin-bottom: 12px; padding: 6px 8px; background: var(--warn-bg); border-radius: 4px; }

/* Runs header */
.runs-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-weight: 600; }
.btn-refresh {
  padding: 3px 8px; border: 1px solid var(--border); border-radius: 4px;
  background: var(--bg-surface); cursor: pointer; font-size: 11px;
}

/* Status filter */
.status-filter, .hit-status-filter { display: flex; gap: 4px; margin-bottom: 8px; flex-wrap: wrap; }
.status-btn {
  padding: 2px 8px; border: 1px solid var(--border); border-radius: 4px;
  font-size: 11px; background: var(--bg-surface); cursor: pointer; transition: all .15s;
}
.status-btn:hover { border-color: var(--accent); }
.status-btn.active { font-weight: 600; border-color: var(--accent); background: var(--selected-bg); }

/* Runs list */
.runs-list { display: flex; flex-direction: column; gap: 4px; }
.run-item { padding: 8px 10px; border: 1px solid transparent; border-radius: var(--radius-lg); cursor: pointer; }
.run-item:hover { background: var(--bg-muted); }
.run-item.selected { background: var(--selected-bg); border-color: var(--accent); }
.run-title { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.run-id { margin-top: 2px; font-size: 11px; font-family: Consolas, monospace; color: var(--text-secondary); }
.run-meta { display: flex; gap: 6px; align-items: center; margin-top: 2px; }
.run-status-badge { font-size: 10px; padding: 1px 6px; border-radius: 10px; background: var(--bg-muted); }
.run-status-badge.planned { background: var(--warn-bg); color: var(--warn-fg); }
.run-status-badge.running { background: var(--info-bg); color: var(--info-fg); }
.run-status-badge.succeeded { background: var(--ok-bg); color: var(--ok-fg); }
.run-status-badge.failed { background: var(--bad-bg); color: var(--bad-fg); }

/* Hits panel */
.hits-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.run-actions { display: flex; gap: 6px; align-items: center; }
.btn-run-action {
  padding: 4px 10px; border: 1px solid var(--accent); border-radius: 4px;
  background: var(--accent); color: #fff; cursor: pointer; font-size: 12px;
}
.btn-run-action.secondary { background: #fff; color: var(--accent); }
.btn-run-action:disabled { opacity: 0.5; cursor: not-allowed; }
.selected-run-info {
  display: flex; gap: 8px; align-items: center; margin-bottom: 8px; padding: 6px 8px;
  border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--bg-muted); font-size: 12px;
}
.selected-run-info code { font-family: Consolas, monospace; color: var(--text-primary); }

/* Hits list */
.hits-list { display: flex; flex-direction: column; gap: 4px; }
.hit-item { padding: 8px 10px; border: 1px solid transparent; border-radius: var(--radius-lg); cursor: pointer; }
.hit-item:hover { background: var(--bg-muted); }
.hit-item.selected { background: var(--selected-bg); border-color: var(--accent); }
.hit-item.accepted { border-left: 3px solid var(--ok); }
.hit-item.rejected { border-left: 3px solid var(--bad); opacity: 0.7; }
.hit-title { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.hit-meta { display: flex; gap: 6px; align-items: center; margin-top: 2px; font-size: 11px; }
.hit-source { color: var(--text-secondary); }
.hit-conf { font-size: 10px; padding: 1px 5px; border-radius: 8px; }
.hit-conf.high { background: var(--ok-bg); color: var(--ok-fg); }
.hit-conf.medium { background: var(--warn-bg); color: var(--warn-fg); }
.hit-conf.low { background: var(--bad-bg); color: var(--bad-fg); }
.hit-conf.large { font-size: 12px; padding: 2px 8px; }
.hit-review-badge { font-size: 10px; padding: 1px 6px; border-radius: 10px; background: var(--bg-muted); }
.hit-review-badge.large { font-size: 12px; padding: 3px 10px; }
.hit-review-badge.pending { background: var(--warn-bg); color: var(--warn-fg); }
.hit-review-badge.accepted { background: var(--ok-bg); color: var(--ok-fg); }
.hit-review-badge.rejected { background: var(--bad-bg); color: var(--bad-fg); }
.hit-reason { margin-top: 2px; line-height: 1.3; }

/* Hits pagination */
.hits-pagination { display: flex; gap: 8px; align-items: center; justify-content: center; margin-top: 10px; font-size: 12px; }
.hits-pagination button { padding: 3px 10px; border: 1px solid var(--border); border-radius: 4px; background: var(--bg-surface); cursor: pointer; font-size: 12px; }
.hits-pagination button:disabled { opacity: 0.4; cursor: not-allowed; }

/* Detail panel */
.detail-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; }
table.kv { width: 100%; border-collapse: collapse; margin-bottom: 12px; }
table.kv th { text-align: left; width: 100px; color: var(--text-secondary); padding: 4px 8px; vertical-align: top; font-size: 12px; }
table.kv td { padding: 4px 8px; font-size: 13px; word-break: break-word; }
.snippet { background: var(--bg-muted); padding: 6px; border-radius: 4px; font-size: 12px; white-space: pre-wrap; margin: 0; max-height: 200px; overflow: auto; }

/* Section toggle */
.section { margin-bottom: 12px; }
.section-title { font-size: 12px; text-transform: uppercase; color: var(--text-secondary); cursor: pointer; user-select: none; margin-bottom: 6px; }
.raw-json { font-size: 11px; font-family: Consolas, monospace; background: var(--bg-muted); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 10px; max-height: 300px; overflow: auto; white-space: pre-wrap; word-break: break-word; }

/* Review bar */
.review-bar { display: flex; gap: 8px; align-items: center; padding: 12px 0; border-top: 1px solid var(--border); flex-wrap: wrap; }
.note-input { flex: 1 1 150px; min-width: 150px; height: 34px; border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 0 10px; font: inherit; }
.btn-accept, .btn-reject { flex-shrink: 0; height: 34px; padding: 0 16px; border: none; border-radius: var(--radius-lg); cursor: pointer; font: inherit; font-weight: 600; }
.btn-accept { background: #16833a; color: #fff; }
.btn-accept:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-reject { background: #c32f27; color: #fff; }
.btn-reject:disabled { opacity: 0.5; cursor: not-allowed; }
.reviewed-info { padding: 12px 0; border-top: 1px solid var(--border); }

/* Utility */
.muted { color: var(--text-secondary); }
.tiny { font-size: 11px; }
.empty { padding: 20px; text-align: center; }

@media (max-width: 1100px) {
  .discovery-layout { grid-template-columns: 260px 1fr; }
  .detail-panel { grid-column: 1 / -1; border-top: 1px solid var(--border); }
}
@media (max-width: 768px) {
  .discovery-layout { grid-template-columns: 1fr; }
  .runs-panel, .hits-panel { border-right: none; border-bottom: 1px solid var(--border); }
}
</style>
