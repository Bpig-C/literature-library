<template>
  <div class="review-layout" :class="{ 'with-pdf': selected && showPdfDrawer }" :style="layoutStyle">
    <!-- Left: list panel -->
    <div class="list-panel" :class="{ collapsed: listCollapsed }">
      <h1>旧书目候选复核（只读归档）</h1>
      <p class="legacy-note">旧元数据抽取/审核流程已退役（LL-DECOUPLE-20260920）：本页仅保留历史记录的只读回查。新材料的完整 A 元数据在 <router-link to="/metadata-workspace">Work 级元数据工作台</router-link> 批量安排，不要求主题研究批次；获批后传播为书目投影。文献详情页的书目编辑进入同一 A 修订链。</p>
      <div class="stats-bar">
        <div v-for="s in STATUSES" :key="s.key" class="stat-card"
          :class="{ active: statusFilter === s.key }" @click="statusFilter = s.key">
          <b>{{ summary[s.key] || 0 }}</b><span>{{ s.label }}</span>
        </div>
      </div>
      <!-- Risk filter -->
      <div class="risk-bar">
        <span class="risk-label">风险:</span>
        <button v-for="r in RISKS" :key="r.key" class="risk-btn" :class="{ active: riskFilter === r.key, [r.key]: true }"
          @click="riskFilter = r.key">{{ r.label }} ({{ summary.risk?.[r.key] || 0 }})</button>
      </div>
      <input v-model="search" placeholder="搜索标题、ID..." class="search-input" />
      <div class="sort-row">
        <n-select v-model:value="sortKey" :options="sortOptions" size="small" style="flex:1" @update:value="resetAndLoad" />
        <button class="sort-dir-btn" @click="toggleSortDir" :title="sortDir === 'desc' ? '降序' : '升序'">
          {{ sortDir === 'desc' ? '↓' : '↑' }}
        </button>
      </div>
      <label class="include-toggle">
        <input type="checkbox" v-model="includeQuarantined" />
        <span>显示已隔离</span>
      </label>
      <div class="ext-list">
        <div v-for="ext in extractions" :key="ext.id"
          class="ext-item" :class="{ selected: selected?.id === ext.id, [ext.review_status]: true, quarantined: ext.work_read_status === 'quarantined' }"
          @click="selectExtraction(ext)">
          <div class="ext-title">{{ ext.work_title || ext.work_id }}</div>
          <div class="ext-meta">
            <span>{{ ext.work_year || '' }}</span>
            <span class="risk-badge" :class="ext.risk_level" v-if="ext.risk_level && ext.risk_level !== 'pending'">
              {{ ext.risk_level }} {{ ext.risk_score }}
            </span>
            <StatusBadge :status="ext.review_status" size="small" :label="statusLabel(ext.review_status)" />
            <StatusBadge v-if="ext.work_read_status === 'quarantined'" status="quarantined" size="small" label="已隔离" />
            <span class="muted tiny">{{ ext.created_at?.slice(0, 10) }}</span>
          </div>
        </div>
        <EmptyState v-if="!extractions.length" icon="search" title="没有匹配的记录" />
      </div>
      <n-pagination v-if="totalPages > 1" v-model:page="page" :page-count="totalPages" @update:page="loadList()" />
      <div class="list-collapse-bar" @click="toggleListCollapse" :title="listCollapsed ? '展开列表' : '收起列表'">
        {{ listCollapsed ? '»' : '«' }}
      </div>
    </div>
    <ResizeHandle v-if="selected && showPdfDrawer" @resize="onResizeList" />

    <!-- Right: detail panel -->
    <div class="detail-panel" v-if="selected">
      <div class="detail-header">
        <div>
          <h2>{{ selected.work_title }}</h2>
          <div class="muted tiny">{{ selected.work_id }} · {{ selected.created_at?.slice(0, 19) }}</div>
        </div>
        <div class="header-badges">
          <span class="risk-badge large" :class="selected.risk_level" v-if="selected.risk_level && selected.risk_level !== 'pending'">
            risk {{ selected.risk_score }}
          </span>
          <StatusBadge :status="selected.review_status" size="large" :label="statusLabel(selected.review_status)" />
          <StatusBadge v-if="selected.work_read_status === 'quarantined'" status="quarantined" size="large" label="已隔离" />
        </div>
      </div>

      <!-- Content preview panel (right after header) -->
      <div class="section preview-section">
        <div class="preview-header">
          <h3 class="section-title" @click="showPreview = !showPreview" style="margin-bottom:0">
            原文预览 {{ showPreview ? '[-]' : '[+]' }}
          </h3>
          <div class="preview-controls" v-if="showPreview">
            <button class="ctrl-btn" :class="{ active: previewMode === 'front' }" @click="previewMode = 'front'">前部</button>
            <button class="ctrl-btn" :class="{ active: previewMode === 'full' }" @click="previewMode = 'full'">全文</button>
            <input v-model="previewSearch" placeholder="搜索..." class="preview-search" @keydown.enter="highlightNext" />
            <button class="ctrl-btn" @click="highlightNext" :disabled="!previewSearch">下一处</button>
            <span class="muted tiny" v-if="previewContent">({{ previewContent.length }} chars)</span>
            <button v-if="selected" class="ctrl-btn pdf-toggle" :class="{ active: showPdfDrawer }" @click="togglePdfDrawer">
              {{ showPdfDrawer ? '关闭 PDF' : 'PDF 侧栏' }}
            </button>
            <a v-if="selected" :href="pdfLink" target="_blank" class="pdf-link">打开 PDF</a>
          </div>
        </div>
        <div v-if="showPreview" class="preview-body" ref="previewEl">
          <div v-if="previewLoading" class="muted">加载中...</div>
          <pre v-else-if="previewContent" class="preview-text" v-html="highlightedPreview"></pre>
          <div v-else class="muted">无内容</div>
        </div>
      </div>

      <!-- Risk reasons (show for high/medium) -->
      <div class="risk-reasons" v-if="selected.risk_level === 'high' || selected.risk_level === 'medium'">
        <h3 class="section-title">风险原因</h3>
        <div class="reason-list">
          <div v-for="(reason, i) in (selected.risk_reasons || [])" :key="i" class="reason-item">
            {{ reason }}
          </div>
        </div>
      </div>

      <!-- Field comparison table -->
      <div class="field-table">
        <div class="field-row header">
          <div class="field-name">字段</div>
          <div class="field-current">当前值</div>
          <div class="field-extracted">抽取值</div>
          <div class="field-conf">置信</div>
        </div>
      </div>

      <!-- Evidence (clickable to search in preview) -->
      <div class="section" v-if="evidence && Object.keys(evidence).length">
        <h3 class="section-title" @click="showEvidence = !showEvidence">
          证据片段 {{ showEvidence ? '[-]' : '[+]' }}
        </h3>
        <div v-if="showEvidence" class="evidence-box">
          <div v-for="(v, k) in evidence" :key="k" class="evidence-item clickable" @click="searchInPreview(v)">
            <span class="ev-key">{{ k }}</span>
            <span class="ev-val">{{ v }}</span>
            <span class="ev-locate" title="在原文中定位">🔍</span>
          </div>
        </div>
      </div>

      <!-- Review note: retired write path (LL-DECOUPLE-20260920) -->
      <div class="review-bar retired-bar">
        <span>审核/重抽/隔离写入口已退役（服务端一律拒绝）。隔离请用文献详情页的隔离操作；书目修订请用文献详情页编辑（进入 v5 元数据修订）。</span>
      </div>

      <!-- Raw JSON toggle -->
      <div class="section">
        <h3 class="section-title" @click="showRaw = !showRaw">
          Extracted JSON {{ showRaw ? '[-]' : '[+]' }}
        </h3>
        <pre v-if="showRaw" class="raw-json">{{ JSON.stringify(selected.extracted_json, null, 2) }}</pre>
      </div>
    </div>
    <div class="detail-panel empty-state" v-else>
      <div>选择一条记录查看详情</div>
    </div>
    <ResizeHandle v-if="selected && showPdfDrawer" @resize="onResizeDetail" />
    <PdfPreviewDrawer
      v-if="selected && showPdfDrawer && activePdfWorkId === selected.work_id"
      :key="pdfDrawerKey"
      :url="pdfLink"
      :work-id="selected.work_id"
      @close="closePdfDrawer"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, nextTick, defineAsyncComponent } from 'vue'
import { useRoute } from 'vue-router'
import { useMessage, useDialog } from 'naive-ui'
import { usePagination } from '../composables/usePagination'
import {
  getMetadataExtractions,
  contentUrl,
  pdfUrl,
} from '../api'
import { getTemplates } from '../api_templates'
import ResizeHandle from '../components/ResizeHandle.vue'
import StatusBadge from '../components/StatusBadge.vue'
import EmptyState from '../components/EmptyState.vue'

const PdfPreviewDrawer = defineAsyncComponent(() => import('../components/PdfPreviewDrawer.vue'))

const message = useMessage()
const dialog = useDialog()
const route = useRoute()
const queryValue = (key, fallback = '') => typeof route.query[key] === 'string' ? route.query[key] : fallback

const STATUSES = [
  { key: 'pending', label: '待审' },
  { key: 'approved', label: '已批准' },
  { key: 'needs_fix', label: '需修正' },
  { key: 'rejected', label: '已拒绝' },
  { key: 'all', label: '全部' },
]

const RISKS = [
  { key: 'all', label: '全部' },
  { key: 'high', label: '高风险' },
  { key: 'medium', label: '中风险' },
  { key: 'low', label: '低风险' },
]

const QUARANTINE_REASONS = [
  { key: 'bad_source', label: '坏源：PDF 内容为空、反爬页、扫描损坏等' },
  { key: 'out_of_scope', label: '不在范围：不属于当前研究主题或综述范围' },
  { key: 'not_literature', label: '非文献：不是论文、报告、标准等目标文献' },
  { key: 'duplicate_residual', label: '重复残留：已由其他 work 覆盖' },
  { key: 'needs_rerun', label: '待重跑：主题对，但上传文档本身有问题，需替换后重新抽取' },
  { key: 'user_removed', label: '用户移除：明确不想保留' },
]

const DEFAULT_FIELDS = [
  { key: 'title', label: '标题', type: 'text' },
  { key: 'title_zh', label: '中文标题', type: 'text' },
  { key: 'publication_date', label: '发布日期', type: 'date-object' },
  { key: 'authors', label: '作者', type: 'author-list' },
  { key: 'contributors', label: '贡献方', type: 'contributor-list' },
  { key: 'doi', label: 'DOI', type: 'text' },
  { key: 'arxiv_id', label: 'arXiv ID', type: 'text' },
  { key: 'venue', label: '发表场所', type: 'text' },
  { key: 'url', label: 'URL', type: 'text' },
  { key: 'abstract', label: '摘要', type: 'textarea' },
]

const statusFilter = ref(queryValue('status', 'pending'))
const riskFilter = ref('all')
const search = ref(queryValue('search'))
const includeQuarantined = ref(false)
const sortKey = ref('created_at')
const sortDir = ref('desc')
const sortOptions = [
  { label: '抽取时间', value: 'created_at' },
  { label: '风险分数', value: 'risk_score' },
  { label: '标题', value: 'work_title' },
]
const { page, total, totalPages, params: paginationParams, reset } = usePagination({ perPage: 20, mode: 'page' })
const summary = ref({})
const extractions = ref([])
const selected = ref(null)
const editForm = ref({})
const showEvidence = ref(false)
const showRaw = ref(false)
const showAllAuthors = ref(false)
const showPreview = ref(true)
const previewContent = ref('')
const previewLoading = ref(false)
const previewMode = ref('front')
const previewSearch = ref('')
const previewEl = ref(null)
const highlightIndex = ref(0)
const showPdfDrawer = ref(false)
const activePdfWorkId = ref(null)
const pdfPreviewKey = ref(0)
const listWidth = ref(340)
const listPrevWidth = ref(340)
const listCollapsed = ref(false)
const detailWidth = ref(null)
const metadataFields = ref([...DEFAULT_FIELDS])

const confidence = computed(() => selected.value?.confidence_json || {})
const evidence = computed(() => selected.value?.extracted_json?.evidence || {})

const pdfLink = computed(() => selected.value ? pdfUrl(selected.value.work_id) : '#')
const pdfDrawerKey = computed(() => `${activePdfWorkId.value || 'none'}:${pdfPreviewKey.value}`)

const layoutStyle = computed(() => {
  if (selected.value && showPdfDrawer.value) {
    // 5 columns: list | handle | detail | handle | pdf
    const detail = detailWidth.value === null ? 'minmax(320px, 1fr)' : `${detailWidth.value}px`
    return { gridTemplateColumns: `${listWidth.value}px 6px ${detail} 6px minmax(420px, 42vw)` }
  }
  // 2 columns: list | detail (no ResizeHandle between them)
  return { gridTemplateColumns: `${listWidth.value}px minmax(0, 1fr)` }
})

const FRONT_CHARS = 12000
const displayPreview = computed(() => {
  if (!previewContent.value) return ''
  if (previewMode.value === 'front') return previewContent.value.slice(0, FRONT_CHARS)
  return previewContent.value
})

const highlightedPreview = computed(() => {
  const text = displayPreview.value
  if (!text) return ''
  if (!previewSearch.value) return escapeHtml(text)
  const escaped = escapeHtml(text)
  const re = new RegExp(`(${escapeRegex(previewSearch.value)})`, 'gi')
  return escaped.replace(re, '<mark>$1</mark>')
})

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}
function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function statusLabel(s) {
  return STATUSES.find(st => st.key === s)?.label || s
}

function normalizeTemplateField(field) {
  const allowed = new Set(['text', 'textarea', 'date-object', 'author-list', 'contributor-list', 'list'])
  const type = allowed.has(field?.type) ? field.type : 'text'
  return {
    key: field?.key || '',
    label: field?.label || field?.key || '',
    type,
    description: field?.description || '',
    rules: field?.rules || '',
  }
}

async function loadMetadataTemplate() {
  try {
    const res = await getTemplates()
    const fields = (res.metadata?.fields || [])
      .map(normalizeTemplateField)
      .filter(f => f.key)
    metadataFields.value = fields.length ? fields : [...DEFAULT_FIELDS]
    if (selected.value) selectExtraction(selected.value)
  } catch (e) {
    console.warn('[MetadataReview] template load failed, using defaults:', e)
    metadataFields.value = [...DEFAULT_FIELDS]
  }
}function stringifyValue(value) {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}

function fieldDefaultValue(field) {
  if (field.type === 'date-object') return { year: null, month: null, day: null, raw: '', kind: 'inferred' }
  if (field.type === 'author-list' || field.type === 'contributor-list' || field.type === 'list') return []
  return ''
}

function normalizeFieldValue(field, extracted) {
  if (field.key === 'publication_date') {
    return {
      year: extracted.publication_date?.year ?? extracted.date?.year ?? null,
      month: extracted.publication_date?.month ?? extracted.date?.month ?? null,
      day: extracted.publication_date?.day ?? extracted.date?.day ?? null,
      raw: extracted.publication_date?.raw || extracted.date?.raw || '',
      kind: extracted.publication_date?.kind || extracted.date?.kind || 'inferred',
    }
  }
  if (field.key === 'contributors') return extracted.contributors || extracted.institutions || []
  const value = extracted[field.key]
  if (value === undefined || value === null) return fieldDefaultValue(field)
  return value
}

function formatJsonValue(value) {
  if (value === undefined || value === null) return ''
  return JSON.stringify(value, null, 2)
}

function updateJsonField(key, raw) {
  if (!raw.trim()) {
    editForm.value[key] = []
    return
  }
  try {
    editForm.value[key] = JSON.parse(raw)
  } catch {
    editForm.value[key] = raw
  }
}

function onResizeList(w) {
  listWidth.value = Math.max(260, Math.min(w, 640))
}

function onResizeDetail(w) {
  detailWidth.value = Math.max(320, Math.min(w, 960))
}

function toggleListCollapse() {
  if (listCollapsed.value) {
    listWidth.value = listPrevWidth.value
    listCollapsed.value = false
  } else {
    listPrevWidth.value = listWidth.value
    listWidth.value = 80
    listCollapsed.value = true
  }
}

function openPdfDrawer() {
  if (!selected.value) return
  activePdfWorkId.value = selected.value.work_id
  showPdfDrawer.value = true
  pdfPreviewKey.value += 1
}

function closePdfDrawer() {
  showPdfDrawer.value = false
  detailWidth.value = null
  activePdfWorkId.value = null
  pdfPreviewKey.value += 1
}

function togglePdfDrawer() {
  if (showPdfDrawer.value) closePdfDrawer()
  else openPdfDrawer()
}

function isMissing(key) {
  const missing = selected.value?.extracted_json?.missing || []
  return missing.includes(key)
}

function formatCurrent(f) {
  const cur = selected.value?.current
  if (!cur) return ''
  const val = cur[f.key]
  if (val === null || val === undefined || val === '') return '-'
  if (f.type === 'author-list' && Array.isArray(val)) return val.join('; ')
  if (f.type === 'contributor-list' && Array.isArray(val)) return val.map(c => `${c.name}[${c.type}]`).join('; ')
  if (f.type === 'date-object' && typeof val === 'object') return val.year || '-'
  if (typeof val === 'string' && val.length > 100) return val.slice(0, 100) + '...'
  return String(val)
}

async function loadList() {
  const params = { ...paginationParams.value, status: statusFilter.value }
  if (riskFilter.value !== 'all') params.risk = riskFilter.value
  if (search.value) params.search = search.value
  if (includeQuarantined.value) params.include_quarantined = true
  params.sort = sortKey.value
  params.order = sortDir.value
  const res = await getMetadataExtractions(params)
  extractions.value = res.extractions
  total.value = res.total
  summary.value = res.summary
}
function selectExtraction(ext) {
  const keepPdfOpen = showPdfDrawer.value
  selected.value = ext
  if (keepPdfOpen) openPdfDrawer()
  const ej = ext.extracted_json || {}
  const nextForm = {}
  for (const field of metadataFields.value) {
    nextForm[field.key] = normalizeFieldValue(field, ej)
  }
  editForm.value = nextForm
  showEvidence.value = false
  showRaw.value = false
  showAllAuthors.value = false
  // Load content preview
  previewContent.value = ''
  previewSearch.value = ''
  previewMode.value = 'front'
  highlightIndex.value = 0
  loadPreview()
}

async function loadPreview() {
  if (!selected.value) return
  previewLoading.value = true
  try {
    const res = await fetch(contentUrl(selected.value.work_id))
    if (res.ok) previewContent.value = await res.text()
    else previewContent.value = ''
  } catch { previewContent.value = '' }
  previewLoading.value = false
}

async function searchInPreview(text) {
  if (!text) return
  showPreview.value = true
  previewSearch.value = text.trim().slice(0, 60)
  highlightIndex.value = 0
  if (!previewContent.value) {
    await loadPreview()
    await nextTick()
    highlightNext()
  } else {
    nextTick(() => highlightNext())
  }
}

function highlightNext() {
  if (!previewSearch.value || !previewEl.value) return
  const marks = previewEl.value.querySelectorAll('mark')
  if (!marks.length) return
  highlightIndex.value = highlightIndex.value % marks.length
  marks[highlightIndex.value].scrollIntoView({ behavior: 'smooth', block: 'center' })
  marks[highlightIndex.value].style.background = '#fbbf24'
  setTimeout(() => { if (marks[highlightIndex.value]) marks[highlightIndex.value].style.background = '' }, 1200)
  highlightIndex.value++
}
// 审核完成后自动选中下一条 pending：优先原位置之后，没有则取第一条 pending；无 pending 则清空选中watch(statusFilter, () => { reset(); riskFilter.value = 'all'; loadList() })
watch(riskFilter, () => { reset(); loadList() })
watch(includeQuarantined, () => { reset(); loadList() })
let searchTimer = null
watch(search, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { reset(); loadList() }, 300)
})

function toggleSortDir() {
  sortDir.value = sortDir.value === 'desc' ? 'asc' : 'desc'
  loadList()
}

function resetAndLoad() {
  reset()
  loadList()
}

onMounted(async () => {
  await loadMetadataTemplate()
  await loadList()
})
</script>

<style scoped>
.review-layout { display: grid; gap: 0; height: calc(100vh - 40px); }
.list-panel { min-width: 0; border-right: 1px solid var(--border); overflow-y: auto; padding: var(--space-4); background: var(--bg-surface); transition: width .2s; position: relative; }
.list-panel.collapsed { overflow: hidden; padding: var(--space-4) 6px; }
.list-panel.collapsed h1,
.list-panel.collapsed .stats-bar,
.list-panel.collapsed .risk-bar,
.list-panel.collapsed .search-input,
.list-panel.collapsed .sort-row,
.list-panel.collapsed .include-toggle,
.list-panel.collapsed .ext-meta,
.list-panel.collapsed .pagination { display: none; }
.list-collapse-bar {
  position: absolute;
  top: 8px;
  right: 0;
  width: 18px;
  height: 28px;
  cursor: pointer;
  background: var(--bg-muted);
  border-left: 1px solid var(--border);
  border-right: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  color: var(--text-secondary);
  user-select: none;
  transition: background .15s;
  z-index: 10;
}
.list-collapse-bar:hover { background: var(--bg-muted); color: var(--text-primary); }
.detail-panel { min-width: 0; overflow-y: auto; padding: var(--space-5) 24px; }
.detail-panel.empty-state { display: flex; align-items: center; justify-content: center; color: var(--text-secondary); }
h1 { font-size: 18px; margin-bottom: 12px; }
.legacy-note { margin: -5px 0 12px; color: var(--text-tertiary); font-size: 10px; line-height: 1.55; }
h2 { font-size: 16px; margin-bottom: 2px; }

/* Stats bar */
.stats-bar { display: flex; gap: 6px; margin-bottom: 10px; flex-wrap: wrap; }
.stat-card { padding: 6px 10px; border: 1px solid var(--border); border-radius: var(--radius-lg); cursor: pointer; font-size: 12px; background: var(--bg-surface); transition: all .15s; }
.stat-card:hover { border-color: var(--accent); }
.stat-card.active { background: var(--selected-bg); border-color: var(--accent); color: var(--accent); }
.stat-card b { display: block; font-size: 16px; }
.stat-card span { color: var(--text-secondary); }

/* Search */
.search-input { width: 100%; height: 32px; border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 0 10px; font: inherit; margin-bottom: 10px; }
.sort-row { display: flex; gap: 4px; align-items: center; margin-bottom: 8px; }
.sort-dir-btn { width: 28px; height: 28px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-surface); cursor: pointer; font-size: 13px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; }
.sort-dir-btn:hover { background: var(--bg-muted); }
.include-toggle { display: flex; align-items: center; gap: 6px; margin: -2px 0 10px; color: var(--text-secondary); font-size: 12px; user-select: none; }
.include-toggle input { margin: 0; }

/* Risk filter bar */
.risk-bar { display: flex; gap: 6px; align-items: center; margin-bottom: 8px; flex-wrap: wrap; }
.risk-label { font-size: 12px; color: var(--text-secondary); }
.risk-btn { padding: 3px 8px; border: 1px solid var(--border); border-radius: var(--radius-md); font-size: 11px; background: var(--bg-surface); cursor: pointer; transition: all .15s; }
.risk-btn:hover { border-color: var(--accent); }
.risk-btn.active { font-weight: 600; border-color: var(--accent); background: var(--selected-bg); }
.risk-btn.active.high { background: var(--bad-bg); border-color: var(--bad); color: var(--bad-fg); }
.risk-btn.active.medium { background: var(--warn-bg); border-color: var(--warn); color: var(--warn-fg); }
.risk-btn.active.low { background: var(--ok-bg); border-color: var(--ok); color: var(--ok-fg); }
.batch-btn { padding: 3px 10px; border: 1px solid var(--ok); border-radius: var(--radius-md); font-size: 11px; background: var(--ok-bg); color: var(--ok-fg); cursor: pointer; font-weight: 600; margin-left: auto; }
.batch-btn:hover { background: var(--ok); color: #fff; }

/* Extraction list */
.ext-list { max-height: calc(100vh - 260px); overflow-y: auto; }
.ext-item { padding: 8px 10px; border: 1px solid transparent; border-radius: var(--radius-lg); cursor: pointer; margin-bottom: 4px; transition: all .1s; }
.ext-item:hover { background: var(--bg-muted); }
.ext-item.selected { background: var(--selected-bg); border-color: var(--accent); }
.ext-item.quarantined { opacity: .68; background: var(--bg-page); }
.ext-title { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ext-meta { display: flex; gap: 6px; align-items: center; font-size: 11px; color: var(--text-secondary); margin-top: 2px; }

/* Detail header */
.detail-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }

/* Badges */
.badge { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 999px; }
.badge.large { font-size: 13px; padding: 4px 12px; }
.badge.pending { background: var(--warn-bg); color: var(--warn-fg); }
.badge.approved { background: var(--ok-bg); color: var(--ok-fg); }
.badge.needs_fix { background: var(--fix-bg); color: var(--fix-fg); }
.badge.rejected { background: var(--bad-bg); color: var(--bad-fg); }
.badge.quarantined { background: var(--neutral-bg); color: var(--neutral-fg); }

/* Risk badges */
.risk-badge { font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 999px; }
.risk-badge.large { font-size: 12px; padding: 3px 10px; }
.risk-badge.low { background: var(--ok-bg); color: var(--ok-fg); }
.risk-badge.medium { background: var(--warn-bg); color: var(--warn-fg); }
.risk-badge.high { background: var(--bad-bg); color: var(--bad-fg); }
.header-badges { display: flex; gap: 8px; align-items: center; }

/* Risk reasons */
.risk-reasons { margin-bottom: 16px; background: #fef2f2; border: 1px solid #fecaca; border-radius: 6px; padding: 12px; }
.risk-reasons h3 { color: var(--bad-fg); }
.reason-list { font-size: 12px; }
.reason-item { padding: 3px 0; color: #7f1d1d; border-bottom: 1px solid #fecaca; }
.reason-item:last-child { border-bottom: none; }

/* Field table */
.field-table { border: 1px solid var(--border); border-radius: var(--radius-lg); margin-bottom: 16px; }
.field-row { display: grid; grid-template-columns: 100px 1fr 1fr 60px 112px; border-bottom: 1px solid var(--border); font-size: 13px; }
.field-row:last-child { border-bottom: none; }
.field-row.header { background: var(--bg-muted); font-weight: 600; font-size: 12px; color: var(--text-secondary); }
.field-row.missing .field-extracted { background: #fef2f2; }
.field-name { padding: 8px 10px; color: var(--text-secondary); border-right: 1px solid var(--border); }
.field-current { padding: 8px 10px; color: var(--text-primary); border-right: 1px solid var(--border); word-break: break-word; }
.field-extracted { padding: 8px 10px; border-right: 1px solid var(--border); }
.field-conf { padding: 8px 6px; text-align: center; }
.field-actions { padding: 6px; display: flex; gap: 4px; align-items: center; justify-content: center; }
.field-action-btn {
  height: 26px;
  padding: 0 7px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg-surface);
  color: var(--text-primary);
  cursor: pointer;
  font-size: 11px;
  white-space: nowrap;
}
.field-action-btn:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
.field-action-btn.rerun { background: var(--accent-subtle); border-color: var(--accent); color: var(--accent); }
.field-action-btn.copy { background: var(--bg-muted); }
.field-action-btn:disabled { opacity: .5; cursor: default; }

/* Inputs in field table */
.full-input { width: 100%; height: 30px; border: 1px solid var(--border); border-radius: var(--radius-md); padding: 0 6px; font: inherit; font-size: 13px; }
textarea.full-input { height: auto; padding: 6px; resize: vertical; }
.mono-input { font-family: Consolas, monospace; font-size: 12px; }
.sm-input { height: 28px; border: 1px solid var(--border); border-radius: var(--radius-md); padding: 0 4px; font: inherit; font-size: 12px; }
.xs-input { width: 48px; height: 28px; border: 1px solid var(--border); border-radius: var(--radius-md); padding: 0 4px; font: inherit; font-size: 12px; }
.md-input { width: 100px; height: 28px; border: 1px solid var(--border); border-radius: var(--radius-md); padding: 0 4px; font: inherit; font-size: 12px; }
.date-obj { display: flex; gap: 4px; align-items: center; flex-wrap: wrap; }

/* Confidence badges */
.conf-badge { font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 999px; }
.conf-badge.high { background: var(--ok-bg); color: var(--ok-fg); }
.conf-badge.medium { background: var(--warn-bg); color: var(--warn-fg); }
.conf-badge.low { background: var(--bad-bg); color: var(--bad-fg); }

/* List displays */
.list-display { font-size: 12px; }
.list-item { padding: 2px 0; }
.all-authors-toggle { margin-top: 4px; }
.all-authors-list { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
.author-tag { padding: 1px 6px; background: var(--bg-muted); border-radius: 4px; font-size: 11px; }
.link-btn { background: none; border: none; color: var(--accent); cursor: pointer; font: inherit; font-size: 12px; padding: 0; }

/* Evidence */
.section { margin-bottom: 16px; }
.section-title { font-size: 12px; text-transform: uppercase; color: var(--text-secondary); cursor: pointer; user-select: none; margin-bottom: 6px; }
.evidence-box { background: var(--bg-muted); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 10px; font-size: 12px; }
.evidence-item { margin-bottom: 6px; }
.ev-key { font-weight: 600; color: var(--text-secondary); margin-right: 6px; }
.ev-val { color: var(--text-primary); word-break: break-word; }

/* Review bar */
.review-bar { display: flex; gap: 8px; align-items: center; padding: 12px 0; border-top: 1px solid var(--border); margin-bottom: 12px; flex-wrap: wrap; }
.note-input { flex: 1 1 200px; min-width: 200px; height: 34px; border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 0 10px; font: inherit; }
.review-bar button { flex-shrink: 0; white-space: nowrap; height: 34px; padding: 0 16px; border: none; border-radius: var(--radius-lg); cursor: pointer; font: inherit; font-weight: 600; }
.btn-approve { background: var(--ok); color: #fff; }
.btn-fix { background: var(--warn); color: #fff; }
.btn-reject { background: var(--bad); color: #fff; }
.btn-quarantine { background: var(--text-secondary); color: #fff; margin-left: 8px; border: 1px solid var(--text-secondary); }
.btn-quarantine:hover { background: var(--text-primary); }

/* Quarantine modal */
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.modal-box { background: var(--bg-surface); border-radius: var(--radius-xl); padding: 24px; width: 440px; max-width: 90vw; box-shadow: 0 8px 32px rgba(0,0,0,0.18); }
.modal-box h3 { margin: 0 0 8px; font-size: 16px; color: var(--text-primary); }
.modal-desc { font-size: 13px; color: var(--text-secondary); margin-bottom: 16px; line-height: 1.5; }
.modal-reasons { display: flex; flex-direction: column; gap: 8px; margin-bottom: 20px; }
.reason-option { display: flex; align-items: flex-start; gap: 8px; font-size: 13px; cursor: pointer; padding: 6px 8px; border-radius: var(--radius-lg); transition: background .1s; }
.reason-option:hover { background: var(--bg-muted); }
.reason-option input { margin-top: 2px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 10px; }
.btn-cancel { height: 34px; padding: 0 16px; border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--bg-surface); cursor: pointer; font: inherit; }
.btn-confirm-quarantine { height: 34px; padding: 0 16px; border: none; border-radius: var(--radius-lg); background: #c32f27; color: #fff; cursor: pointer; font: inherit; font-weight: 600; }
.btn-confirm-quarantine:disabled { opacity: 0.5; cursor: default; }
.btn-confirm-rerun { height: 34px; padding: 0 16px; border: none; border-radius: var(--radius-lg); background: var(--accent); color: #fff; cursor: pointer; font: inherit; font-weight: 600; }
.btn-confirm-rerun:disabled { opacity: .5; cursor: default; }
.rerun-modal { width: min(760px, 92vw); }
.prompt-modal { width: min(820px, 92vw); }
.rerun-diff-list { display: flex; flex-direction: column; gap: 12px; max-height: 56vh; overflow: auto; margin-bottom: 18px; }
.rerun-diff-item { border: 1px solid var(--border); border-radius: var(--radius-lg); overflow: hidden; }
.rerun-diff-title { display: flex; align-items: center; gap: 8px; padding: 8px 10px; background: var(--bg-muted); font-weight: 600; font-size: 13px; }
.rerun-changed { font-size: 11px; padding: 1px 7px; border-radius: 999px; background: var(--neutral-bg); color: var(--neutral-fg); }
.rerun-changed.yes { background: var(--ok-bg); color: var(--ok-fg); }
.rerun-diff-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0; }
.rerun-diff-grid > div { min-width: 0; padding: 10px; border-right: 1px solid var(--border); }
.rerun-diff-grid > div:last-child { border-right: 0; }
.rerun-diff-grid pre { margin: 4px 0 0; max-height: 180px; overflow: auto; white-space: pre-wrap; word-break: break-word; font-size: 12px; font-family: Consolas, monospace; background: var(--bg-muted); border-radius: var(--radius-md); padding: 8px; }
.prompt-textarea { width: 100%; height: 420px; resize: vertical; font-family: Consolas, monospace; font-size: 12px; line-height: 1.5; border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 10px; margin-bottom: 14px; }

/* Raw JSON */
.raw-json { font-size: 11px; font-family: Consolas, monospace; background: var(--bg-muted); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 10px; max-height: 300px; overflow: auto; white-space: pre-wrap; word-break: break-word; }

/* Preview panel */
.preview-section { border-top: 2px solid var(--accent); padding-top: 12px; }
.preview-header { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }
.preview-controls { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.ctrl-btn { height: 26px; padding: 0 8px; border: 1px solid var(--border); border-radius: var(--radius-md); font-size: 11px; background: var(--bg-surface); cursor: pointer; }
.ctrl-btn.active { background: var(--accent); color: #fff; border-color: var(--accent); }
.ctrl-btn:disabled { opacity: 0.4; cursor: default; }
.ctrl-btn:active:not(:disabled) { transform: scale(0.95); }
.pdf-toggle { font-weight: 600; }
.preview-search { height: 26px; width: 160px; border: 1px solid var(--border); border-radius: var(--radius-md); padding: 0 6px; font: inherit; font-size: 12px; }
.pdf-link { font-size: 11px; color: var(--accent); margin-left: 8px; }
.preview-body { border: 1px solid var(--border); border-radius: var(--radius-lg); max-height: 500px; overflow: auto; background: var(--bg-muted); }
.preview-text { font-size: 12px; font-family: Consolas, monospace; padding: 12px; margin: 0; white-space: pre-wrap; word-break: break-word; line-height: 1.6; }
.preview-text :deep(mark) { background: #fef08a; padding: 1px 2px; border-radius: 2px; }


/* Evidence clickable */
.evidence-item.clickable { cursor: pointer; padding: 4px 6px; border-radius: var(--radius-md); transition: background .1s; }
.evidence-item.clickable:hover { background: var(--selected-bg); }
.ev-locate { font-size: 11px; margin-left: 4px; opacity: 0; transition: opacity .15s; }
.evidence-item.clickable:hover .ev-locate { opacity: 1; }

/* Utility */
.muted { color: var(--text-secondary); }
.tiny { font-size: 11px; }
.empty { padding: 24px; text-align: center; color: var(--text-secondary); font-size: 13px; }

@media (max-width: 1180px) {
  .review-layout.with-pdf { grid-template-rows: minmax(0, 1fr) minmax(360px, 46vh); }
  .pdf-drawer { grid-column: 1 / -1; border-left: 0; border-top: 1px solid var(--border); }
}
</style>
