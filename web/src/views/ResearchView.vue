<template>
  <div class="research-page">
    <div class="page-intro">
      <div>
        <span class="page-kicker">RESEARCH RECORDS</span>
        <h1>研究视图</h1>
        <p>横向比较研究记录，同时保留原文、来源快照和两层审核状态。</p>
      </div>
      <div class="result-count"><strong>{{ total }}</strong><span>当前结果</span></div>
    </div>

    <div class="governance-note">
      <div>
        <strong>按批次查看研究记录</strong>
        <span>查看这一批文献的原文、解释与审核状态。中文工作稿可以单独编辑，原记录保留。</span>
        <span>完整书目 A 按 Work 独立抽取与核查；<router-link to="/metadata-workspace">去元数据工作台查看或批量补全 →</router-link> 本页只安排 C 原文与 D 解释分类。</span>
        <span v-if="usableSummary">可用基线：<b>{{ usableSummary.usable_count }}</b> / {{ usableSummary.total }} 条两层内容均“稳定”；另 {{ usableSummary.waiting_human }} 条稳定但人工判断待定（不阻断使用）。</span>
        <span v-if="usableSummary?.source_dependency_review_pending" class="dependency-warning">
          其中 {{ usableSummary.source_dependency_review_pending }} 条解释沿用固定原文版本；后续原文仅定位信息变化，解释仍可用，但来源定位待复核。
        </span>
      </div>
      <router-link to="/research/ontology" class="ontology-link">查看研究分类词表·草案 →</router-link>
    </div>

    <div class="filter-panel">
      <div class="filter-primary">
        <n-select
          v-model:value="batchId"
          :options="batchOptions"
          :loading="batchesLoading"
          filterable
          clearable
          aria-label="选择研究批次"
          placeholder="选择研究批次（可搜索名称）"
          @update:value="changeBatch"
        />
        <ResearchBatchCreateButton @created="handleBatchCreated" />
        <n-input
          v-model:value="filters.q"
          clearable
          placeholder="搜索 Work ID、citation key 或来源文本"
          @input="debouncedSearch"
          @keyup.enter="applyFilters"
        />
        <n-button type="primary" :loading="loading" @click="applyFilters">查询</n-button>
        <n-button quaternary :disabled="loading" @click="resetFilters">重置</n-button>
      </div>

      <p class="batch-help">研究批次是一组文献的一轮整理任务，不是风险分类；当前轮次用于继续工作，历史轮次只用于回查，无需记编号。</p>
      <p v-if="batchesError" class="batch-help">{{ batchesError }} <n-button text @click="loadBatches">重新加载批次</n-button></p>

      <details class="advanced-filters">
      <summary>条件与审核状态筛选</summary>
      <div class="filter-grid">
        <label v-for="item in filterDefinitions" :key="item.key" class="filter-item">
          <span>{{ item.label }}</span>
          <n-select
            v-model:value="filters[item.key]"
            :options="optionsFor(item.key, item.options)"
            filterable
            tag
            clearable
            :placeholder="item.placeholder || '全部'"
            @update:value="applyFilters"
          />
        </label>
      </div>
      </details>
    </div>

    <div class="status-legend" aria-label="审核状态说明">
      <span><i class="legend-dot agent"></i>原文层与解释层分别读取五类状态（含内容三态）</span>
      <span><i class="legend-dot human"></i>人工采纳是叠加判断：可用基线只看“验证+独立审查+内容稳定”，人工待定不阻断使用</span>
      <span>任一 pending 都是待处理状态，不等于已核验。</span>
    </div>

    <n-alert v-if="error" type="warning" :show-icon="false" class="load-alert">
      {{ error }}
      <template #action><n-button text type="primary" @click="loadData">重试</n-button></template>
    </n-alert>

    <n-alert v-else-if="!batchId" type="info" :show-icon="false" class="load-alert">
      {{ batchesLoading ? '正在加载研究批次…' : '请选择一个研究批次，或点击“新建研究批次”从已解析并送入研究库的文献开始。多个批次不会自动混在一起。' }}
    </n-alert>

    <div v-if="loading && !rows.length" class="loading-state"><n-spin size="large" /></div>

    <div v-else-if="rows.length" class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>文献</th>
            <th>更新对象</th>
            <th>研究作用</th>
            <th>部署条件</th>
            <th>原文层状态</th>
            <th>解释层状态</th>
            <th>分类映射</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="rowKey(row)">
            <td class="work-cell">
              <router-link v-if="workId(row)" :to="{ path: `/works/${encodeURIComponent(workId(row))}`, query: { batch_id: batchId } }" class="work-title">
                {{ workTitle(row) }}
              </router-link>
              <strong v-else class="work-title">{{ workTitle(row) }}</strong>
              <span>{{ workId(row) || '无 Work ID' }}</span>
            </td>
            <td>{{ readableListField(row, 'update_object') }}</td>
            <td>{{ readableListField(row, 'research_role') }}</td>
            <td>{{ readableListField(row, 'deployment_condition') }}</td>
            <td v-for="layer in researchLayers" :key="layer.key">
              <div class="layer-mini" :class="{ missing: !layerRecord(row, layer.key) }">
                <span v-for="state in layerStatuses" :key="state.key">
                  {{ state.short }}
                  <n-tag size="tiny" :type="statusType(layerStatusValue(row, layer.key, state.key), state.context)">
                    {{ statusLabel(layerStatusValue(row, layer.key, state.key), state.context) }}
                  </n-tag>
                </span>
              </div>
            </td>
            <td><n-tag size="small" :type="statusType(statusValue(row, 'mapping_status'), 'mapping')">{{ statusLabel(statusValue(row, 'mapping_status'), 'mapping') }}</n-tag></td>
            <td><n-button text type="primary" size="small" @click="openDetail(row)">查看记录</n-button></td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-else-if="batchId && !error" class="empty-state">
      <strong>没有匹配的研究记录</strong>
      <span>可以调整筛选；这不代表文献不存在，只表示当前 research 记录没有命中。</span>
    </div>

    <p v-if="total > limit" class="limit-note">当前显示前 {{ limit }} 条，共 {{ total }} 条；请继续收紧筛选条件。</p>

    <n-modal v-model:show="showDetail" preset="card" title="研究记录" class="record-modal" style="width: min(900px, 94vw)">
      <template v-if="selected">
        <div class="record-heading">
          <div>
            <strong>{{ workTitle(selected) }}</strong>
            <span>{{ workId(selected) || '无 Work ID' }}</span>
          </div>
        </div>
        <div class="layer-status-grid">
          <section v-for="layer in researchLayers" :key="layer.key" class="layer-status-card" :class="{ missing: !layerRecord(selected, layer.key) }">
            <header><strong>{{ layer.label }}</strong><code>{{ layerRecord(selected, layer.key)?.id || '尚未生成' }}</code></header>
            <div>
              <span v-for="state in layerStatuses" :key="state.key">
                <small>{{ state.label }}</small>
                <n-tag size="small" :type="statusType(layerStatusValue(selected, layer.key, state.key), state.context)">
                  {{ statusLabel(layerStatusValue(selected, layer.key, state.key), state.context) }}
                </n-tag>
              </span>
            </div>
            <!-- B6/B9(R5)：局部人工采纳必须显示实际范围，不冒充整条认可 -->
            <small v-if="layer.key === 'interpretation' && layerRecord(selected, layer.key)?.human_adoption_scope"
                   class="adoption-scope-note">
              局部采纳：仅覆盖 {{ adoptionScopeText(layerRecord(selected, layer.key).human_adoption_scope) }}；其余内容未经人工认可
            </small>
          </section>
        </div>
        <div class="adoption-policy">
          可用基线（研究消费口径）：原文层与解释层均为“结构验证通过 + 独立审查通过 + 内容稳定 + 有效”。
          人工采纳是叠加判断，不参与该门槛；待人工、未读的材料继续参与消费，只以内容三态为准。
        </div>
        <div class="mapping-summary">
          <span>分类映射</span>
          <n-tag size="small" :type="statusType(statusValue(selected, 'mapping_status'), 'mapping')">{{ statusLabel(statusValue(selected, 'mapping_status'), 'mapping') }}</n-tag>
        </div>
        <div v-if="needsInterpretationReview(selected)" class="ontology-note">
          解释状态为 stale：可能由 ontology 或上游原文记录修订触发；来源快照保持不变，不表示需要重新解析 PDF。
        </div>
        <section class="citations-panel">
          <h3>引用图与跨篇比较</h3>
          <div class="citations-actions">
            <button type="button" @click="loadSelectedCitations">查看该文献引用图</button>
            <button type="button" :disabled="!batchId" @click="loadBatchComparison">查看批次跨篇比较</button>
          </div>
          <p v-if="citationsError" class="ontology-note">{{ citationsError }}</p>
          <div v-if="citationsData" class="citations-summary">
            <p>引用对象 {{ citationsData.references?.length || 0 }} 条；引用边 {{ citationsData.cites?.length || 0 }} 条（其中已核验 {{ verifiedEdgeCount }} 条）。</p>
            <ul v-if="citationsData.references?.length">
              <li v-for="ref in citationsData.references" :key="ref.id">
                <code>{{ ref.id }}</code>
                <span>{{ ref.external_object?.title || '未命名引用对象' }}</span>
                <n-tag size="small" :type="ref.match_status === 'matched' ? 'success' : 'default'">{{ ref.match_status }}</n-tag>
                <code v-if="ref.matched_work_id">{{ ref.matched_work_id }}</code>
              </li>
            </ul>
            <p v-else>该文献尚未登记引用对象（引用匹配与核验在研究层 CLI/API 进行，证据须引自引用方自己的快照）。</p>
          </div>
          <p v-if="comparisonError" class="ontology-note">{{ comparisonError }}</p>
          <div v-if="comparisonData" class="citations-summary">
            <p>批次 {{ comparisonData.batch_id }} 比较输出 <code>{{ comparisonData.output_id }}</code>；概念组 {{ Object.keys(comparisonData.concepts || {}).length }} 个{{ comparisonData.previous_output_ids?.length ? `；历史输出 ${comparisonData.previous_output_ids.length} 份可追溯` : '' }}。</p>
            <details v-for="(rows, concept) in comparisonData.concepts || {}" :key="concept" class="comparison-concept">
              <summary><code>{{ concept }}</code> · {{ rows.length }} 行</summary>
              <article v-for="row in rows" :key="row.record_id" class="comparison-row">
                <header><strong>{{ row.work_id }}</strong><code>{{ row.record_id }}</code>
                  <n-tag size="small" :type="row.basis_role === 'baseline' ? 'success' : 'default'">{{ row.basis_role }}</n-tag>
                </header>
                <p v-if="row.statement">{{ row.statement }}</p>
                <p class="comparison-meta">
                  映射：{{ row.mapping_status || '未映射' }} · 扩展 {{ (row.extensions || []).length }}
                  · 原文层扩展 {{ (row.source_record_extensions || []).length }}
                  · 证据 {{ (row.evidence || []).length }} 条
                  <template v-if="row.metadata_binding"> · 元数据 {{ row.metadata_binding.id }} v{{ row.metadata_binding.version }}<template v-if="row.metadata_binding.review_pending">（待复核）</template></template>
                  <template v-if="row.human_adoption_scope"> · 局部采纳 {{ adoptionScopeText(row.human_adoption_scope) }}</template>
                  <template v-if="row.source_dependency_review_pending?.length"> · 来源定位待复核 {{ row.source_dependency_review_pending.length }} 项</template>
                </p>
              </article>
            </details>
          </div>
        </section>
        <ResearchRecordReadable :record="selected" />
        <section>
          <h3>来源与快照</h3>
          <div class="provenance-grid">
            <span>source_file_id</span><code>{{ sourceValue(selected, 'source_file_id') }}</code>
            <span>parse_run_id</span><code>{{ sourceValue(selected, 'parse_run_id') }}</code>
            <span>snapshot hash</span><code>{{ sourceValue(selected, 'snapshot_hash') }}</code>
            <span>质量状态</span><strong>{{ sourceQuality(selected) }}</strong>
          </div>
        </section>
      </template>
    </n-modal>
    <BatchAgentTaskFab v-if="batchId" :batch-id="batchId" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getResearchUsable, queryResearch, getWorkCitations, getBatchComparison } from '../api'
import ResearchRecordReadable from '../components/research/ResearchRecordReadable.vue'
import BatchAgentTaskFab from '../components/research/BatchAgentTaskFab.vue'
import ResearchBatchCreateButton from '../components/research/ResearchBatchCreateButton.vue'
import { enumLabel, listFieldDisplay } from '../researchPresentation'

const route = useRoute()
const router = useRouter()
const limit = 50
const loading = ref(false)
const error = ref('')
const rows = ref([])
const total = ref(0)
const batchId = ref(null)
const batches = ref([])
const batchesLoading = ref(false)
const batchesError = ref('')
const BATCH_STATUS_LABELS = {
  planned: '待执行',
  running: '执行中',
  completed: '已完成',
  completed_with_errors: '完成但有异常',
  failed: '失败',
}
function batchStatusLabel(status) {
  return BATCH_STATUS_LABELS[status] || status || '状态未记录'
}
function batchOption(batch, historical = false) {
  const successor = batch.successor_batch_ids?.[0]
  const suffix = historical && successor
    ? ` · 后继 ${successor}`
    : ` · ${batchStatusLabel(batch.status)}`
  return {
    value: batch.id,
    label: `${batch.name || '未命名研究批次'} · ${batch.works} 篇${suffix} · ${batch.id}`,
  }
}
const batchOptions = computed(() => {
  const current = batches.value.filter(batch => batch.is_current_round !== false)
    .map(batch => batchOption(batch))
  const historical = batches.value.filter(batch => batch.is_current_round === false)
    .map(batch => batchOption(batch, true))
  const knownIds = new Set(batches.value.map(batch => batch.id))
  const groups = []
  if (current.length) groups.push({ type: 'group', label: '当前轮次', key: 'current', children: current })
  if (historical.length) groups.push({ type: 'group', label: '历史轮次（仅回查）', key: 'historical', children: historical })
  // Preserve a directly linked batch even when the catalogue is unavailable.
  if (batchId.value && !knownIds.has(batchId.value)) {
    groups.unshift({
      type: 'group', label: '链接指定', key: 'linked',
      children: [{ value: batchId.value, label: `链接指定的批次 · ${batchId.value}` }],
    })
  }
  return groups
})
async function loadBatches() {
  batchesLoading.value = true
  batchesError.value = ''
  try {
    const response = await fetch('/api/overview')
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const overview = await response.json()
    if (!overview.research?.available) throw new Error('研究批次列表暂不可用')
    batches.value = overview.research.batches || []
    if (!batchId.value && batches.value.length === 1) {
      batchId.value = batches.value[0].id
      await loadData()
    }
  } catch (err) {
    batchesError.value = `批次列表加载失败：${err.message}。已有批次链接仍可使用。`
  } finally {
    batchesLoading.value = false
  }
}
async function handleBatchCreated(batch) {
  const createdId = batch?.batch_id
  if (!createdId) return
  batchId.value = createdId
  filters.value.q = ''
  await router.replace({ query: { batch_id: createdId } })
  await loadBatches()
  await loadData()
}
function changeBatch() {
  showDetail.value = false
  selected.value = null
  rows.value = []
  usableSummary.value = null
  applyFilters()
}
let querySequence = 0
const selected = ref(null)
// B9: citations/comparison are consumed from the page, not only via CLI/API
// （声明放在 selected 之后，避免打包后的初始化顺序问题）
const citationsData = ref(null)
const citationsError = ref('')
const comparisonData = ref(null)
const comparisonError = ref('')
function adoptionScopeText(scope) {
  if (!scope || typeof scope !== 'object') return '未声明范围'
  const parts = []
  if (Array.isArray(scope.axes) && scope.axes.length) parts.push(`轴 ${scope.axes.join('/')}`)
  if (Array.isArray(scope.unit_keys) && scope.unit_keys.length) parts.push(`单元 ${scope.unit_keys.join('/')}`)
  for (const [key, value] of Object.entries(scope)) {
    if (key in { axes: 1, unit_keys: 1 }) continue
    parts.push(`${key}=${Array.isArray(value) ? value.join('/') : value}`)
  }
  return parts.join('；') || '未声明范围'
}

const verifiedEdgeCount = computed(() =>
  (citationsData.value?.cites || []).filter(e => e.verified).length)

async function loadSelectedCitations() {
  citationsError.value = ''
  const citingWork = workId(selected.value)
  if (!citingWork) {
    citationsError.value = '当前记录没有 Work ID，无法查询引用图。'
    citationsData.value = null
    return
  }
  try {
    citationsData.value = await getWorkCitations(citingWork)
  } catch (error) {
    citationsData.value = null
    citationsError.value = `无法读取引用图：${error?.message || '请求失败'}`
  }
}

async function loadBatchComparison() {
  comparisonError.value = ''
  comparisonData.value = null
  if (!batchId.value) return
  try {
    comparisonData.value = await getBatchComparison(batchId.value)
  } catch (error) {
    comparisonError.value = `无法读取跨篇比较：${error?.message || '请求失败'}`
  }
}
const showDetail = ref(false)
const usableSummary = ref(null)

const filters = ref({
  q: '',
  update_object: null,
  research_role: null,
  deployment_condition: null,
  source_validation_status: null,
  source_agent_review_status: null,
  source_human_adoption_status: null,
  source_validity_status: null,
  source_content_state: null,
  interpretation_validation_status: null,
  interpretation_agent_review_status: null,
  interpretation_human_adoption_status: null,
  interpretation_validity_status: null,
  interpretation_content_state: null,
  mapping_status: null,
})

const REVIEW_OPTIONS = [
  { label: '待 Agent 审阅', value: 'pending' },
  { label: 'Agent 已通过', value: 'approved' },
  { label: 'Agent 要求修订', value: 'needs_revision' },
  { label: 'Agent 已拒绝', value: 'rejected' },
]
const HUMAN_OPTIONS = [
  { label: '待人工采纳', value: 'pending' },
  { label: '人工已采纳', value: 'adopted' },
  { label: '人工未采纳', value: 'rejected' },
]
const VALIDATION_OPTIONS = [
  { label: '待验证', value: 'pending' },
  { label: '验证通过', value: 'passed' },
  { label: '验证失败', value: 'failed' },
]
const MAPPING_OPTIONS = [
  { label: '已映射', value: 'mapped' },
  { label: '部分映射', value: 'partially_mapped' },
  { label: '未映射', value: 'unmapped' },
  { label: '映射有歧义', value: 'ambiguous' },
]
const VALIDITY_OPTIONS = [
  { label: '有效', value: 'active' },
  { label: '待重审', value: 'stale' },
  { label: '已被替代', value: 'superseded' },
]
const CONTENT_OPTIONS = [
  { label: '待补全', value: 'needs_completion' },
  { label: '待审查', value: 'needs_review' },
  { label: '稳定', value: 'stable' },
]

const filterDefinitions = [
  { key: 'update_object', label: '更新对象', placeholder: '输入或选择对象' },
  { key: 'research_role', label: '研究作用', placeholder: '输入或选择作用' },
  { key: 'deployment_condition', label: '部署条件', placeholder: '输入或选择条件' },
  { key: 'source_validation_status', label: '原文·验证', options: VALIDATION_OPTIONS },
  { key: 'source_agent_review_status', label: '原文·Agent', options: REVIEW_OPTIONS },
  { key: 'source_human_adoption_status', label: '原文·人工', options: HUMAN_OPTIONS },
  { key: 'source_validity_status', label: '原文·有效性', options: VALIDITY_OPTIONS },
  { key: 'source_content_state', label: '原文·内容三态', options: CONTENT_OPTIONS },
  { key: 'interpretation_validation_status', label: '解释·验证', options: VALIDATION_OPTIONS },
  { key: 'interpretation_agent_review_status', label: '解释·Agent', options: REVIEW_OPTIONS },
  { key: 'interpretation_human_adoption_status', label: '解释·人工', options: HUMAN_OPTIONS },
  { key: 'interpretation_validity_status', label: '解释·有效性', options: VALIDITY_OPTIONS },
  { key: 'interpretation_content_state', label: '解释·内容三态', options: CONTENT_OPTIONS },
  { key: 'mapping_status', label: '映射状态', options: MAPPING_OPTIONS },
]

const researchLayers = [
  { key: 'source_record', label: '原文层（source_record）' },
  { key: 'interpretation', label: '解释层（interpretation）' },
]
const layerStatuses = [
  { key: 'validation_status', label: '结构与证据锚点', short: '验证', context: 'validation' },
  { key: 'agent_review_status', label: 'Agent 审阅', short: 'Agent', context: 'agent' },
  { key: 'human_adoption_status', label: '人工采纳', short: '人工', context: 'human' },
  { key: 'validity_status', label: '有效性', short: '有效性', context: 'validity' },
  { key: 'content_state', label: '内容三态', short: '内容', context: 'content' },
]

function responseRows(payload) {
  const body = payload?.data ?? payload ?? {}
  const candidates = Array.isArray(body) ? body : body.items || body.results || body.records || body.works || []
  return Array.isArray(candidates)
    ? candidates.map(item => ({ ...item, batch_id: item?.batch_id || body?.batch_id || batchId.value }))
    : []
}

function responseTotal(payload, fallback) {
  const body = payload?.data ?? payload ?? {}
  return Number(body.total ?? body.total_matching ?? body.count ?? fallback) || 0
}

function recordOf(row) { return row?.interpretation || row?.source_record || row || {} }

function rawValue(value) {
  if (value && typeof value === 'object' && 'value' in value) return value.value
  return value
}

function valueAt(row, key) {
  const layerStatus = key.match(/^(source|interpretation)_(validation_status|agent_review_status|human_adoption_status|validity_status|content_state)$/)
  if (layerStatus) {
    const layer = layerStatus[1] === 'source' ? row?.source_record : row?.interpretation
    return rawValue(layer?.[layerStatus[2]])
  }
  if (['update_object', 'research_role', 'deployment_condition'].includes(key)) {
    return rawValue(row?.interpretation?.payload?.[key])
  }
  if (['agent_review_status', 'human_adoption_status'].includes(key)) {
    return rawValue(row?.interpretation?.[key] ?? 'pending')
  }
  if (key === 'validation_status') {
    return rawValue(row?.validation_status ?? row?.interpretation?.validation_status ?? row?.source_record?.validation_status)
  }
  if (key === 'mapping_status') {
    return rawValue(row?.mapping_status ?? row?.interpretation?.payload?.mapping_status)
  }
  const record = recordOf(row)
  return rawValue(
    row?.[key]
    ?? row?.interpretation?.[key]
    ?? row?.interpretation?.payload?.[key]
    ?? row?.source_record?.[key]
    ?? row?.source_record?.payload?.[key]
    ?? record?.fields?.[key]
  )
}

function displayValue(value, fallback = '—') {
  if (value === undefined || value === null || value === '') return fallback
  if (Array.isArray(value)) return value.length ? value.map(v => displayValue(v, '')).filter(Boolean).join('；') : fallback
  if (typeof value === 'object') return Object.entries(value).map(([k, v]) => `${k}: ${displayValue(v, '')}`).join('；') || fallback
  return String(value)
}

function readableListField(row, key) { return listFieldDisplay(row, key) }
function statusValue(row, key) {
  const value = key === 'mapping_status'
    ? (row?.mapping_status ?? row?.interpretation?.payload?.mapping_status)
    : valueAt(row, key)
  return value === undefined || value === null || value === '' ? 'unknown' : String(value).toLowerCase()
}
function workId(row) { return row?.source?.work_id || row?.work_id || '' }
function workTitle(row) {
  // RWEB-01: a litlib-asset:// URI's trailing segment is a version number,
  // never a filename; only real source paths may donate a display name.
  const path = row?.source?.source_path || ''
  const filename = path.startsWith('litlib-asset://')
    ? ''
    : path.split(/[\\/]/).pop()?.replace(/\.pdf$/i, '')
  return row?.title || row?.work_title || filename || row?.source?.citation_key || workId(row) || '未命名记录'
}
function rowKey(row) { return row?.interpretation?.id || row?.source_record?.id || row?.source?.id || `${workId(row)}-${JSON.stringify(recordOf(row)).slice(0, 80)}` }

function optionsFor(key, base = []) {
  const seen = new Set(base.map(item => String(item.value)))
  const dynamic = []
  for (const row of rows.value) {
    const value = valueAt(row, key)
    const values = Array.isArray(value) ? value : [value]
    for (const item of values) {
      if (item === undefined || item === null || item === '' || typeof item === 'object') continue
      const normalized = String(item)
      if (!seen.has(normalized)) {
        seen.add(normalized)
        const label = ['update_object', 'research_role', 'mapping_status'].includes(key)
          ? enumLabel(key, normalized)
          : readableListField(row, key)
        dynamic.push({ label, value: normalized })
      }
    }
  }
  return [...base, ...dynamic]
}

function statusLabel(status, context) {
  const labels = {
    validation: { pending: '待验证', passed: '验证通过', failed: '验证失败' },
    agent: { pending: '待 Agent 审阅', approved: 'Agent 已通过', needs_revision: 'Agent 要求修订', rejected: 'Agent 已拒绝' },
    human: { pending: '待人工采纳', adopted: '人工已采纳', rejected: '人工未采纳' },
    mapping: { mapped: '已映射', partially_mapped: '部分映射', unmapped: '未映射', ambiguous: '映射有歧义' },
    validity: { active: '有效', stale: '待重审', superseded: '已被替代' },
    content: { needs_completion: '待补全', needs_review: '待审查', stable: '稳定' },
  }
  if (status === 'missing') return '尚未生成'
  if (status === 'unknown') return '状态未提供'
  return labels[context]?.[status] || status || '未知'
}

function statusType(status, context) {
  if (context === 'human' && status === 'adopted') return 'success'
  if (context === 'agent' && status === 'approved') return 'info'
  if (context === 'validation' && status === 'passed') return 'success'
  if (context === 'mapping' && status === 'mapped') return 'success'
  if (context === 'validity' && status === 'active') return 'success'
  if (context === 'content') {
    if (status === 'stable') return 'success'
    if (status === 'needs_completion') return 'error'
    return 'warning'
  }
  if (['rejected', 'failed'].includes(status)) return 'error'
  if (['needs_revision', 'stale', 'superseded', 'partially_mapped', 'ambiguous'].includes(status)) return 'warning'
  return 'default'
}

function layerRecord(row, layer) { return row?.[layer] || null }
function layerStatusValue(row, layer, key) {
  const record = layerRecord(row, layer)
  if (!record) return 'missing'
  const value = record?.[key]
  return value === undefined || value === null || value === '' ? 'unknown' : String(value).toLowerCase()
}

function sourceObject(row) {
  return row?.source || {}
}

function sourceValue(row, key) {
  const source = sourceObject(row)
  const aliases = key === 'snapshot_hash' ? ['content_sha256', 'source_sha256'] : [key]
  for (const alias of aliases) {
    const value = row?.snapshot?.[alias] ?? source?.[alias] ?? row?.source_record?.[alias] ?? row?.interpretation?.[alias] ?? row?.[alias]
    if (value !== undefined && value !== null && value !== '') return displayValue(value)
  }
  return '—'
}

function sourceQuality(row) {
  const source = sourceObject(row)
  if (source?.parse_exists === false || source?.parse_exists === 0) return '解析产物缺失'
  const quality = source?.parse_quality
  return { unchecked: '未检查', passed: '解析质量通过', failed: '解析质量失败' }[quality] || displayValue(quality)
}

function needsInterpretationReview(row) {
  return row?.interpretation?.validity_status === 'stale'
}

function openDetail(row) {
  const id = workId(row)
  if (id) router.push({path:`/research/records/${encodeURIComponent(id)}`,query:{batch_id:batchId.value,source_id:row.source?.id}})
  else { selected.value = row; showDetail.value = true }
}

let searchTimer
function debouncedSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(applyFilters, 300)
}

function queryParams() {
  const params = { batch_id: batchId.value, limit }
  for (const [key, value] of Object.entries(filters.value)) {
    // The backend owns batch/status filtering. Payload dimensions are also sent
    // for forward compatibility and are enforced below as a client-side guard.
    if (value !== undefined && value !== null && value !== '') params[key] = value
  }
  return params
}

function matchesClientFilters(row) {
  for (const key of ['update_object', 'research_role', 'deployment_condition', 'agent_review_status', 'human_adoption_status']) {
    const expected = filters.value[key]
    const actual = valueAt(row, key)
    if (expected && Array.isArray(actual) && !actual.map(String).includes(String(expected))) return false
    if (expected && !Array.isArray(actual) && String(actual ?? '') !== String(expected)) return false
  }
  return true
}

async function loadData() {
  const sequence = ++querySequence
  const requestedBatch = batchId.value
  router.replace({ query: { ...route.query, batch_id: requestedBatch || undefined, q: filters.value.q || undefined } })
  if (!batchId.value) {
    loading.value = false
    rows.value = []
    total.value = 0
    usableSummary.value = null
    error.value = ''
    return
  }
  loading.value = true
  error.value = ''
  try {
    const response = await queryResearch(queryParams())
    if (sequence !== querySequence) return
    const fetched = responseRows(response)
    rows.value = fetched.filter(matchesClientFilters)
    total.value = rows.value.length < fetched.length ? rows.value.length : responseTotal(response, rows.value.length)
    const usable = await getResearchUsable(requestedBatch)
    if (sequence !== querySequence) return
    usableSummary.value = {
      usable_count: Number(usable?.usable_count ?? usable?.data?.usable_count) || 0,
      total: Number(usable?.total ?? usable?.data?.total) || 0,
      waiting_human: (usable?.items ?? usable?.data?.items ?? []).filter(item => item.waiting_human).length,
      source_dependency_review_pending: (usable?.items ?? usable?.data?.items ?? [])
        .filter(item => item.source_dependency_review_pending?.length).length,
    }
  } catch (err) {
    if (sequence !== querySequence) return
    error.value = `研究数据暂时不可用：${err?.message || '请求失败'}。文献库其他功能不受影响。`
    rows.value = []
    total.value = 0
    usableSummary.value = null
  } finally {
    if (sequence === querySequence) loading.value = false
  }
}

function applyFilters() {
  loadData()
}

function resetFilters() {
  filters.value = {
    q: '', update_object: null, research_role: null, deployment_condition: null,
    source_validation_status: null, source_agent_review_status: null,
    source_human_adoption_status: null, source_validity_status: null,
    source_content_state: null,
    interpretation_validation_status: null, interpretation_agent_review_status: null,
    interpretation_human_adoption_status: null, interpretation_validity_status: null,
    interpretation_content_state: null,
    mapping_status: null,
  }
  applyFilters()
}

onMounted(() => {
  batchId.value = route.query.batch_id ? String(route.query.batch_id) : null
  filters.value.q = String(route.query.q || route.query.search || '')
  loadData()
  loadBatches()
})
</script>

<style scoped>
.research-page { width: min(1480px, 100%); margin: 0 auto; }
.page-intro { display: flex; align-items: flex-end; justify-content: space-between; margin-bottom: 20px; }
.page-kicker { display: block; margin-bottom: 6px; color: var(--accent); font-size: 9px; font-weight: 680; letter-spacing: .11em; }
.page-intro h1 { font-size: 28px; font-weight: 610; letter-spacing: -.035em; }
.page-intro p { margin-top: 6px; color: var(--text-secondary); font-size: 12px; }
.result-count { display: flex; min-width: 90px; flex-direction: column; align-items: flex-end; padding-left: 20px; border-left: 1px solid var(--border); }
.result-count strong { font-size: 24px; font-weight: 620; }
.result-count span { color: var(--text-tertiary); font-size: 9px; }
.governance-note { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 14px 16px; margin-bottom: 14px; border: 1px solid var(--info-border); border-radius: var(--radius-lg); background: var(--info-bg); }
.governance-note div { display: flex; min-width: 0; flex-direction: column; gap: 3px; }
.governance-note strong { color: var(--info-fg); font-size: 13px; }
.governance-note span { color: var(--text-secondary); font-size: 12px; }
.ontology-link { flex: 0 0 auto; color: var(--info-fg); font-size: 11px; font-weight: 650; }
.filter-panel { padding: 14px; border: 1px solid var(--border); border-radius: var(--radius-xl); background: var(--bg-surface); box-shadow: var(--shadow-sm); }
.filter-primary { display: grid; grid-template-columns: minmax(220px, .8fr) auto minmax(260px, 1fr) auto auto; gap: 8px; margin-bottom: 14px; }
.batch-help { margin: 0 0 10px; font-size: 12px; color: var(--text-secondary); }
.filter-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(165px, 1fr)); gap: 12px; }
.advanced-filters summary { cursor: pointer; font-size: 12px; color: var(--text-secondary); padding: 4px 0; }
.advanced-filters[open] summary { margin-bottom: 12px; }
.filter-item { display: grid; min-width: 0; grid-template-columns: minmax(0, 1fr); align-items: baseline; gap: 7px; }
.filter-item span { font-size: 12px; font-weight: 560; }
.filter-item small { color: var(--text-tertiary); font: 10px var(--font-mono); }
.filter-item :deep(.n-select) { grid-column: 1 / -1; }
.status-legend { display: flex; flex-wrap: wrap; gap: 9px 18px; margin: 12px 2px; color: var(--text-secondary); font-size: 11px; }
.status-legend span { display: inline-flex; align-items: center; gap: 6px; }
.legend-dot { width: 7px; height: 7px; border-radius: 50%; }
.legend-dot.agent { background: var(--info); }
.legend-dot.human { background: var(--ok); }
.load-alert { margin: 12px 0; }
.loading-state { display: grid; min-height: 260px; place-items: center; }
.table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: var(--radius-xl); background: var(--bg-surface); box-shadow: var(--shadow-sm); }
table { width: 100%; min-width: 1440px; table-layout: fixed; border-collapse: collapse; }
th:nth-child(1) { width: 250px; }
th:nth-child(2), th:nth-child(3) { width: 125px; }
th:nth-child(4) { width: 280px; }
th:nth-child(5), th:nth-child(6) { width: 215px; }
th:nth-child(7) { width: 120px; }
th:nth-child(8) { width: 110px; }
th { white-space: nowrap; }
td { line-height: 1.7; overflow-wrap: anywhere; }
.table-wrap { max-width: 100%; }
.filter-item > span { white-space: nowrap; }
th, td { padding: 12px 11px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; font-size: 12px; }
th { position: sticky; top: 0; color: var(--text-secondary); background: #f5f5f2; font-size: 10px; font-weight: 620; letter-spacing: .025em; }
tbody tr:hover td { background: #f2f8f5; }
tbody tr:last-child td { border-bottom: 0; }
.work-cell { min-width: 240px; }
.work-cell > span { display: block; margin-top: 3px; color: var(--text-tertiary); font: 10px var(--font-mono); }
.work-cell .n-tag { margin-top: 5px; }
.work-title { display: block; color: var(--text-primary); font-weight: 590; line-height: 1.4; }
a.work-title:hover { color: var(--accent); }
.empty-state { display: flex; min-height: 260px; flex-direction: column; align-items: center; justify-content: center; gap: 7px; color: var(--text-secondary); }
.empty-state strong { color: var(--text-primary); font-size: 15px; }
.empty-state span { font-size: 12px; }
.limit-note { margin-top: 12px; color: var(--text-secondary); font-size: 11px; text-align: right; }
.record-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding-bottom: 12px; border-bottom: 1px solid var(--border); }
.record-heading div { display: flex; flex-direction: column; gap: 4px; }
.record-heading span { color: var(--text-tertiary); font: 11px var(--font-mono); }
.layer-mini { display: grid; min-width: 190px; gap: 4px; }
.layer-mini > span { display: flex; align-items: center; justify-content: space-between; gap: 7px; color: var(--text-tertiary); font-size: 9px; }
.layer-mini.missing { opacity: .72; }
.layer-status-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 14px 0 10px; }
.layer-status-card { padding: 11px; margin-top: 0; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-page); }
.layer-status-card.missing { border-style: dashed; }
.layer-status-card header { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }
.layer-status-card header strong { font-size: 12px; }
.layer-status-card header code { overflow-wrap: anywhere; color: var(--text-tertiary); font-size: 9px; }
.layer-status-card > div { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 9px; }
.layer-status-card span { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; }
.layer-status-card small { color: var(--text-secondary); font-size: 9px; }
.citations-panel { margin-top: 14px; padding: 12px; border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--bg-surface); }
.citations-panel h3 { margin-bottom: 7px; }
.citations-actions { display: flex; gap: 8px; margin-bottom: 8px; }
.citations-actions button { padding: 4px 10px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-surface); cursor: pointer; }
.citations-summary ul { margin: 6px 0 0; padding-left: 18px; }
.citations-summary li { display: flex; gap: 8px; align-items: center; margin: 3px 0; }
.adoption-policy { padding: 9px 11px; margin-bottom: 12px; color: var(--text-secondary); border-left: 3px solid var(--border-strong); background: var(--bg-page); font-size: 11px; }
.adoption-policy.warning { color: var(--bad-fg); border-color: var(--bad); background: var(--bad-bg); }
.mapping-summary { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 9px 11px; margin-bottom: 12px; border-radius: var(--radius-md); background: var(--bg-page); }
.mapping-summary span { color: var(--text-secondary); font-size: 10px; }
.ontology-note { padding: 10px 12px; margin-bottom: 14px; color: var(--warn-fg); border: 1px solid var(--warn-border); border-radius: var(--radius-md); background: var(--warn-bg); font-size: 12px; }
section { margin-top: 16px; }
section h3 { margin-bottom: 7px; color: var(--text-secondary); font-size: 11px; text-transform: uppercase; letter-spacing: .04em; }
section p { line-height: 1.65; white-space: pre-wrap; }
.provenance-grid { display: grid; grid-template-columns: 120px minmax(0, 1fr); gap: 7px 10px; padding: 12px; border-radius: var(--radius-md); background: var(--bg-page); }
.provenance-grid span { color: var(--text-secondary); font-size: 11px; }
.provenance-grid code { overflow-wrap: anywhere; font-size: 11px; }
.detail-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
pre { max-height: 360px; overflow: auto; padding: 12px; color: var(--text-primary); border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-page); font: 11px/1.55 var(--font-mono); white-space: pre-wrap; word-break: break-word; }
@media (max-width: 720px) {
  .page-intro { align-items: flex-start; }
  .result-count { display: none; }
  .governance-note { align-items: flex-start; flex-direction: column; }
  .filter-primary { grid-template-columns: 1fr 1fr; }
  .filter-primary :deep(.n-input) { grid-column: 1 / -1; }
  .layer-status-grid { grid-template-columns: 1fr; }
  .detail-columns { grid-template-columns: 1fr; }
}
</style>
