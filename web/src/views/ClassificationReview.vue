<template>
  <div class="review-layout" :style="layoutStyle">
    <!-- Left: list panel -->
    <div class="list-panel">
      <h1>分类审核</h1>
      <div class="stats-bar">
        <div class="ambiguity-bar">
          <span class="amb-label">模糊度:</span>
          <button class="amb-btn" :class="{ active: ambFilter === 'high' }" @click="ambFilter = ambFilter === 'high' ? null : 'high'">
            高 ({{ summary.ambiguity?.high || 0 }})
          </button>
          <button class="amb-btn" :class="{ active: ambFilter === 'medium' }" @click="ambFilter = ambFilter === 'medium' ? null : 'medium'">
            中 ({{ summary.ambiguity?.medium || 0 }})
          </button>
          <button class="amb-btn" :class="{ active: ambFilter === 'low' }" @click="ambFilter = ambFilter === 'low' ? null : 'low'">
            低 ({{ summary.ambiguity?.low || 0 }})
          </button>
          <button v-if="statusFilter === 'pending' && summary.ambiguity?.low > 0" class="batch-btn" @click="doBatchApprove">
            批量批准低模糊度 ({{ summary.ambiguity.low }})
          </button>
        </div>
        <div class="status-bar">
          <div v-for="s in STATUSES" :key="s.key" class="stat-card"
            :class="{ active: statusFilter === s.key }" @click="statusFilter = s.key; loadList()">
            <b>{{ summary[s.key] || 0 }}</b><span>{{ s.label }}</span>
          </div>
        </div>
      </div>
      <input v-model="search" placeholder="搜索标题、ID..." class="search-input" @input="debouncedLoad" />
      <label class="include-toggle">
        <input type="checkbox" v-model="includeQuarantined" @change="page = 1; loadList()" />
        <span>显示已隔离</span>
        <b v-if="summary.quarantined">({{ summary.quarantined }})</b>
      </label>
      <div class="ext-list">
        <div v-for="ext in extractions" :key="ext.id"
          class="ext-item" :class="{ selected: selected?.id === ext.id, [ext.review_status]: true, quarantined: ext.work_read_status === 'quarantined' }"
          @click="selectExtraction(ext)">
          <div class="ext-title">{{ ext.work_title || ext.work_id }}</div>
          <div class="ext-meta">
            <span>{{ ext.work_year || '' }}</span>
            <span class="amb-badge" :class="ambLevel(ext.ambiguity_score)">
              amb {{ ext.ambiguity_score }}
            </span>
            <span class="model-badge" :class="ext.model_name?.startsWith('mimo') ? 'mimo' : 'ollama'">{{ ext.model_name?.startsWith('mimo') ? 'Mimo' : 'Ollama' }}</span>
            <span class="badge" :class="ext.review_status">{{ statusLabel(ext.review_status) }}</span>
            <span v-if="ext.work_read_status === 'quarantined'" class="badge quarantined">已隔离</span>
            <span class="muted tiny">{{ ext.created_at?.slice(0, 10) }}</span>
          </div>
        </div>
        <div v-if="!extractions.length" class="empty">没有匹配的记录</div>
      </div>
      <div class="pagination" v-if="totalPages > 1">
        <button :disabled="page <= 1" @click="page--; loadList()">上一页</button>
        <span>{{ page }} / {{ totalPages }}</span>
        <button :disabled="page >= totalPages" @click="page++; loadList()">下一页</button>
      </div>
    </div>
    <ResizeHandle @resize="onResizeList" />

    <!-- Right: detail panel -->
    <div class="detail-panel" v-if="selected">
      <div class="detail-header">
        <div>
          <h2>{{ selected.work_title }}</h2>
          <div class="muted tiny">{{ selected.work_id }} · <span class="model-badge" :class="selected.model_name?.startsWith('mimo') ? 'mimo' : 'ollama'">{{ selected.model_name?.startsWith('mimo') ? 'Mimo 2.5 Pro' : 'Ollama' }}</span> · {{ selected.created_at?.slice(0, 19) }}</div>
        </div>
        <div class="header-badges">
          <button class="ctrl-btn pdf-toggle" :class="{ active: showPdfDrawer }" @click="togglePdfDrawer">
            {{ showPdfDrawer ? '关闭 PDF' : 'PDF 侧栏' }}
          </button>
          <a :href="pdfLink" target="_blank" class="pdf-link">打开 PDF</a>
          <span class="amb-badge large" :class="ambLevel(selected.ambiguity_score)">
            amb {{ selected.ambiguity_score }}
          </span>
          <span class="badge large" :class="selected.review_status">{{ statusLabel(selected.review_status) }}</span>
          <span v-if="selected.work_read_status === 'quarantined'" class="badge large quarantined">已隔离</span>
        </div>
      </div>

      <!-- Current work info -->
      <div class="section">
        <h3 class="section-title">当前文献信息</h3>
        <div class="kv-grid">
          <div class="kv-item"><span class="kv-label">doc_type</span><span>{{ selected.work_doc_type || '—' }}</span></div>
          <div class="kv-item"><span class="kv-label">primary_doc_type</span><span>{{ selected.work_primary_doc_type || '—' }}</span></div>
          <div class="kv-item" v-if="selected.work_title_zh"><span class="kv-label">中文标题</span><span>{{ selected.work_title_zh }}</span></div>
          <div class="kv-item" v-if="selected.work_authors"><span class="kv-label">作者</span><span>{{ selected.work_authors }}</span></div>
          <div class="kv-item"><span class="kv-label">年份</span><span>{{ selected.work_year || '—' }}</span></div>
          <div class="kv-item" v-if="selected.work_language"><span class="kv-label">语言</span><span>{{ selected.work_language }}</span></div>
          <div class="kv-item" v-if="selected.work_venue"><span class="kv-label">发表场所</span><span>{{ selected.work_venue }}</span></div>
          <div class="kv-item" v-if="selected.work_arxiv_id"><span class="kv-label">arXiv ID</span><span>{{ selected.work_arxiv_id }}</span></div>
          <div class="kv-item" v-if="selected.work_doi"><span class="kv-label">DOI</span><span>{{ selected.work_doi }}</span></div>
          <div class="kv-item" v-if="selected.work_publication_status"><span class="kv-label">发布状态</span><span>{{ selected.work_publication_status }}</span></div>
          <div class="kv-item" v-if="selected.work_priority"><span class="kv-label">优先级</span><span>{{ selected.work_priority }}</span></div>
        </div>
        <div v-if="selected.work_abstract" class="work-abstract">
          <span class="kv-label">摘要</span>
          <div class="abstract-text">{{ selected.work_abstract }}</div>
        </div>
      </div>

      <!-- Classification fields -->
      <div class="section">
        <h3 class="section-title">分类候选字段</h3>
        <div class="field-table">
          <div class="field-row header">
            <div class="field-name">字段</div>
            <div class="field-extracted">候选值</div>
            <div class="field-conf">置信</div>
          </div>
          <div v-for="f in CLASS_FIELDS" :key="f.key" class="field-row">
            <div class="field-name">{{ f.label }}</div>
            <div class="field-extracted">
              <template v-if="f.type === 'list'">
                <div class="tag-list" v-if="(editForm[f.key] || []).length">
                  <span v-for="(v, i) in editForm[f.key]" :key="i" class="chip">{{ resolveTagValue(f.key, v) }}</span>
                </div>
                <span v-else class="muted">—</span>
              </template>
              <template v-else-if="f.type === 'select'">
                <select v-model="editForm[f.key]" class="field-select">
                  <option :value="null">未标注</option>
                  <option v-for="opt in f.options" :key="opt" :value="opt">{{ resolveSelectLabel(f.key, opt) }}</option>
                </select>
              </template>
              <template v-else-if="f.type === 'searchable-select'">
                <div class="searchable-select-wrap" v-click-outside="() => closeDropdown(f.key)">
                  <div class="ss-input-row">
                    <input
                      :value="getSearchText(f.key)"
                      @input="onSearchInput(f.key, $event)"
                      @focus="openDropdown(f.key)"
                      :placeholder="'检索或输入...'"
                      class="ss-input"
                    />
                    <button v-if="editForm[f.key]" class="ss-clear" @click="clearSearchableSelect(f.key)">×</button>
                  </div>
                  <div v-if="dropdownOpen[f.key]" class="ss-dropdown">
                    <div v-for="opt in filteredOptions(f)" :key="opt.key"
                      class="ss-option" :class="{ selected: editForm[f.key] === opt.key }"
                      @click="selectOption(f.key, opt.key)">
                      {{ opt.label }}
                    </div>
                    <div v-if="!filteredOptions(f).length" class="ss-option ss-empty">无匹配项</div>
                  </div>
                </div>
              </template>
              <template v-else-if="f.type === 'locked-select'">
                <div class="searchable-select-wrap" v-click-outside="() => closeDropdown(f.key)">
                  <div class="ss-input-row">
                    <input
                      :value="getSearchText(f.key)"
                      @input="onSearchInput(f.key, $event)"
                      @focus="openDropdown(f.key)"
                      readonly
                      :placeholder="'请选择...'"
                      class="ss-input"
                    />
                    <button v-if="editForm[f.key]" class="ss-clear" @click="clearSearchableSelect(f.key)">×</button>
                  </div>
                  <div v-if="dropdownOpen[f.key]" class="ss-dropdown">
                    <div v-for="opt in filteredOptions(f)" :key="opt.key"
                      class="ss-option" :class="{ selected: editForm[f.key] === opt.key }"
                      @click="selectOption(f.key, opt.key)">
                      {{ opt.label }}
                    </div>
                    <div v-if="!filteredOptions(f).length" class="ss-option ss-empty">无匹配项</div>
                  </div>
                </div>
              </template>
              <template v-else>
                <input v-model="editForm[f.key]" class="field-input" />
              </template>
            </div>
            <div class="field-conf">
              <span v-if="confidence[f.key]" class="conf-badge" :class="confidence[f.key]">{{ confidence[f.key] }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Ambiguity reasons -->
      <div class="section" v-if="selected.ambiguity_reasons?.length">
        <h3 class="section-title">模糊原因</h3>
        <div class="reason-list">
          <div v-for="(reason, i) in selected.ambiguity_reasons" :key="i" class="reason-item">
            {{ reason }}
          </div>
        </div>
      </div>

      <!-- Evidence -->
      <div class="section" v-if="evidence && Object.keys(evidence).length">
        <h3 class="section-title" @click="showEvidence = !showEvidence">
          证据片段 {{ showEvidence ? '[-]' : '[+]' }}
        </h3>
        <div v-if="showEvidence" class="evidence-box">
          <div v-for="(v, k) in evidence" :key="k" class="evidence-item">
            <span class="ev-key">{{ k }}</span>
            <span class="ev-val">{{ v }}</span>
          </div>
        </div>
      </div>

      <!-- Review bar -->
      <div class="review-bar">
        <input v-model="reviewNote" placeholder="审核备注..." class="note-input" />
        <button class="btn-approve" @click="doReview('approved')">批准</button>
        <button class="btn-fix" @click="doReview('needs_fix')">需修正</button>
        <button class="btn-reject" @click="doReview('rejected')">拒绝</button>
        <button
          class="btn-quarantine"
          :disabled="selected.work_read_status === 'quarantined'"
          @click="openQuarantineModal"
        >
          {{ selected.work_read_status === 'quarantined' ? '已隔离' : '隔离此文献' }}
        </button>
      </div>

      <div v-if="showQuarantineModal" class="modal-overlay" @click.self="showQuarantineModal = false">
        <div class="modal-box">
          <h3>隔离文献</h3>
          <p class="modal-desc">隔离后，这篇文献会从默认审核队列和批量批准中移出，并在文献管理、元数据审核、分类审核中保持同一个隔离状态。</p>
          <div class="modal-reasons">
            <label v-for="r in QUARANTINE_REASONS" :key="r.key" class="reason-option">
              <input type="radio" v-model="quarantineReason" :value="r.key" />
              <span>{{ r.label }}</span>
            </label>
          </div>
          <div class="modal-actions">
            <button class="btn-cancel" @click="showQuarantineModal = false">取消</button>
            <button class="btn-confirm-quarantine" :disabled="!quarantineReason || quarantineLoading" @click="doQuarantine">
              {{ quarantineLoading ? '处理中...' : '确认隔离' }}
            </button>
          </div>
        </div>
      </div>
    </div>
    <div v-else class="detail-empty">选择一条记录查看详情</div>
    <ResizeHandle v-if="selected && showPdfDrawer" @resize="onResizeDetail" />
    <PdfPreviewDrawer
      v-if="selected && showPdfDrawer"
      :key="pdfPreviewKey"
      :url="pdfLink"
      :work-id="selected.work_id"
      @close="closePdfDrawer"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, reactive, onBeforeUnmount, nextTick } from 'vue'
import {
  getClassificationExtractions, getClassificationExtraction,
  reviewClassificationExtraction, batchApproveLowAmbiguity,
  quarantineFromClassificationReview, pdfUrl,
} from '../api'
import PdfPreviewDrawer from '../components/PdfPreviewDrawer.vue'
import ResizeHandle from '../components/ResizeHandle.vue'
import {
  PRIMARY_DOC_TYPE_LABELS, PUBLICATION_STATUS_LABELS,
  INGESTION_STATE_LABELS, PRIORITY_LABELS,
  SOURCE_ACTOR_TYPE_LABELS, REGION_LABELS,
  TAG_VALUE_LABELS,
  label,
} from '../labels'

const STATUSES = [
  { key: 'pending', label: '待审核' },
  { key: 'approved', label: '已批准' },
  { key: 'needs_fix', label: '需修正' },
  { key: 'rejected', label: '已拒绝' },
  { key: 'all', label: '全部' },
]

const CLASS_FIELDS = [
  { key: 'primary_doc_type', label: '主文档类型', type: 'select',
    options: Object.keys(PRIMARY_DOC_TYPE_LABELS) },
  { key: 'publication_status', label: '发布状态', type: 'select',
    options: Object.keys(PUBLICATION_STATUS_LABELS) },
  { key: 'primary_source_actor_type', label: '来源机构类型', type: 'searchable-select',
    options: SOURCE_ACTOR_TYPE_LABELS, allowCustom: true },
  { key: 'region', label: '地区', type: 'locked-select',
    options: REGION_LABELS, allowCustom: false },
  { key: 'reading_lane', label: '阅读用途', type: 'list' },
  { key: 'artifact_focus', label: '贡献对象', type: 'list' },
  { key: 'risk_domain', label: '风险领域', type: 'list' },
  { key: 'method_tags', label: '方法标签', type: 'list' },
  { key: 'ingestion_state', label: '入库状态', type: 'select',
    options: Object.keys(INGESTION_STATE_LABELS) },
  { key: 'priority', label: '优先级', type: 'select',
    options: Object.keys(PRIORITY_LABELS) },
]

const QUARANTINE_REASONS = [
  { key: 'bad_source', label: '坏源：PDF 内容为空、反爬页、扫描损坏等' },
  { key: 'out_of_scope', label: '不在范围：不属于当前研究主题或综述范围' },
  { key: 'not_literature', label: '非文献：不是论文、报告、标准等目标文献' },
  { key: 'duplicate_residual', label: '重复残留：已由其他 work 覆盖' },
  { key: 'needs_rerun', label: '待重跑：主题对，但上传文档本身有问题，需替换后重新抽取' },
  { key: 'user_removed', label: '用户移除：明确不想保留' },
]

const extractions = ref([])
const total = ref(0)
const page = ref(1)
const perPage = 50
const statusFilter = ref('pending')
const ambFilter = ref(null)
const search = ref('')
const includeQuarantined = ref(false)
const selected = ref(null)
const summary = ref({})
const editForm = ref({})
const confidence = ref({})
const evidence = ref({})
const reviewNote = ref('')
const showEvidence = ref(false)
const showQuarantineModal = ref(false)
const quarantineReason = ref('')
const quarantineLoading = ref(false)
const showPdfDrawer = ref(false)
const pdfPreviewKey = ref(0)
const listWidth = ref(340)
const detailWidth = ref(null) // null = auto (1fr)

// Searchable-select state
const dropdownOpen = reactive({})
const searchText = reactive({})

function openDropdown(key) {
  dropdownOpen[key] = true
  searchText[key] = ''
}
function closeDropdown(key) {
  dropdownOpen[key] = false
}
function onSearchInput(key, e) {
  searchText[key] = e.target.value
}
function getSearchText(key) {
  return searchText[key] ?? ''
}
function filteredOptions(f) {
  const q = (searchText[f.key] || '').toLowerCase()
  const entries = Object.entries(f.options)
  return entries
    .filter(([k, v]) => !q || k.toLowerCase().includes(q) || v.toLowerCase().includes(q))
    .map(([k, v]) => ({ key: k, label: `${v} (${k})` }))
}
function selectOption(key, value) {
  editForm[key] = value
  searchText[key] = ''
  dropdownOpen[key] = false
}
function clearSearchableSelect(key) {
  editForm[key] = null
  searchText[key] = ''
}

// Click-outside directive — ignores clicks inside dropdown children
const vClickOutside = {
  mounted(el, binding) {
    el._clickOutside = (e) => {
      if (el.contains(e.target)) return
      if (e.target.closest('.ss-dropdown')) return
      binding.value()
    }
    // Use 'click' instead of 'mousedown' so dropdown option @click handlers
    // fire before the dropdown is closed (mousedown fires before click).
    document.addEventListener('click', el._clickOutside)
  },
  unmounted(el) {
    document.removeEventListener('click', el._clickOutside)
  },
}

const totalPages = computed(() => Math.ceil(total.value / perPage))
const pdfLink = computed(() => selected.value ? pdfUrl(selected.value.work_id) : '#')

const layoutStyle = computed(() => {
  const cols = [`${listWidth.value}px`, '6px']
  if (selected.value && showPdfDrawer.value) {
    cols.push(detailWidth.value === null ? 'minmax(320px, 1fr)' : `${detailWidth.value}px`)
    cols.push('6px', 'minmax(420px, 42vw)')
  } else {
    cols.push('minmax(0, 1fr)')
  }
  return { gridTemplateColumns: cols.join(' ') }
})

function onResizeList(w) { listWidth.value = Math.max(240, Math.min(w, 600)) }
function onResizeDetail(w) { detailWidth.value = Math.max(300, Math.min(w, 900)) }

function openPdfDrawer() {
  if (!showPdfDrawer.value) {
    showPdfDrawer.value = true
    pdfPreviewKey.value += 1
  }
}

function closePdfDrawer() {
  showPdfDrawer.value = false
  detailWidth.value = null
}

function togglePdfDrawer() {
  if (showPdfDrawer.value) closePdfDrawer()
  else openPdfDrawer()
}

let timer = null
function debouncedLoad() {
  clearTimeout(timer)
  timer = setTimeout(() => { page.value = 1; loadList() }, 300)
}

function ambLevel(score) {
  if (score >= 50) return 'high'
  if (score >= 20) return 'medium'
  return 'low'
}

function statusLabel(s) {
  const map = { pending: '待审核', approved: '已批准', needs_fix: '需修正', rejected: '已拒绝' }
  return map[s] || s
}

const SELECT_LABEL_MAP = {
  primary_doc_type: PRIMARY_DOC_TYPE_LABELS,
  publication_status: PUBLICATION_STATUS_LABELS,
  ingestion_state: INGESTION_STATE_LABELS,
  priority: PRIORITY_LABELS,
}

function resolveSelectLabel(fieldKey, opt) {
  const map = SELECT_LABEL_MAP[fieldKey]
  return map ? label(map, opt) : opt
}

function resolveTagValue(fieldKey, value) {
  const map = TAG_VALUE_LABELS[fieldKey]
  return map ? label(map, value) : value
}

async function loadList() {
  const params = {
    status: statusFilter.value,
    limit: perPage,
    offset: (page.value - 1) * perPage,
    search: search.value,
    include_quarantined: includeQuarantined.value,
  }
  const res = await getClassificationExtractions(params)
  extractions.value = res.extractions
  total.value = res.total
  summary.value = res.summary || {}
}

async function selectExtraction(ext) {
  const keepPdfOpen = showPdfDrawer.value
  selected.value = await getClassificationExtraction(ext.id)
  if (keepPdfOpen) pdfPreviewKey.value += 1
  initEditForm()
}

function initEditForm() {
  if (!selected.value) return
  const ej = selected.value.extracted_json || {}
  editForm.value = {
    primary_doc_type: ej.primary_doc_type || null,
    publication_status: ej.publication_status || null,
    primary_source_actor_type: ej.primary_source_actor_type || null,
    region: ej.region || null,
    reading_lane: [...(ej.reading_lane || [])],
    artifact_focus: [...(ej.artifact_focus || [])],
    risk_domain: [...(ej.risk_domain || [])],
    method_tags: [...(ej.method_tags || [])],
    ingestion_state: ej.ingestion_state || null,
    priority: ej.priority || null,
  }
  confidence.value = selected.value.confidence_json || {}
  evidence.value = selected.value.extracted_json?.evidence || {}
  reviewNote.value = selected.value.review_note || ''
  showEvidence.value = false
  // Reset searchable-select state
  Object.keys(dropdownOpen).forEach(k => { dropdownOpen[k] = false })
  Object.keys(searchText).forEach(k => { searchText[k] = '' })
}

async function doReview(status) {
  if (!selected.value) return
  const data = {
    review_status: status,
    review_note: reviewNote.value,
    edited_fields: { ...editForm.value },
  }
  await reviewClassificationExtraction(selected.value.id, data)
  await loadList()
  selected.value = null
}

async function doBatchApprove() {
  const res = await batchApproveLowAmbiguity()
  alert(`已批准 ${res.approved} 条低模糊度记录`)
  await loadList()
}

function openQuarantineModal() {
  quarantineReason.value = ''
  showQuarantineModal.value = true
}

async function doQuarantine() {
  if (!selected.value || !quarantineReason.value) return
  quarantineLoading.value = true
  try {
    await quarantineFromClassificationReview(selected.value.id, quarantineReason.value)
    showQuarantineModal.value = false
    selected.value = null
    await loadList()
  } catch (e) {
    alert('隔离失败: ' + e.message)
  } finally {
    quarantineLoading.value = false
  }
}

onMounted(loadList)
</script>

<style scoped>
.review-layout {
  display: grid;
  grid-template-columns: 340px 1fr;
  gap: 0;
  height: calc(100vh - 40px);
}
.list-panel {
  min-width: 0;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 16px;
  overflow-y: auto;
}
.detail-panel {
  min-width: 0;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 20px;
  overflow-y: auto;
}
.detail-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--muted);
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 6px;
}
h1 { font-size: 20px; margin-bottom: 12px; }
h2 { font-size: 16px; margin-bottom: 4px; }
.muted { color: var(--muted); }
.tiny { font-size: 12px; }

/* Stats */
.stats-bar { margin-bottom: 10px; }
.ambiguity-bar, .status-bar { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 6px; }
.amb-label, .status-label { font-size: 12px; color: var(--muted); align-self: center; }
.stat-card {
  display: flex; flex-direction: column; align-items: center;
  padding: 4px 10px; border: 1px solid var(--line); border-radius: 6px;
  cursor: pointer; font-size: 12px; background: #fff;
}
.stat-card.active { border-color: var(--accent); background: #eef5ff; }
.stat-card b { font-size: 16px; }
.amb-btn {
  height: 28px; padding: 0 10px; border: 1px solid var(--line); border-radius: 4px;
  background: #fff; cursor: pointer; font: inherit; font-size: 12px;
}
.amb-btn.active { border-color: var(--accent); background: #eef5ff; }
.batch-btn {
  height: 28px; padding: 0 10px; border: 1px solid var(--ok); border-radius: 4px;
  background: #fff; color: var(--ok); cursor: pointer; font: inherit; font-size: 12px;
}
.include-toggle {
  display: flex; align-items: center; gap: 6px; margin: 0 0 8px;
  color: var(--muted); font-size: 12px; user-select: none;
}
.include-toggle input { margin: 0; }
.search-input {
  width: 100%; height: 32px; border: 1px solid var(--line); border-radius: 6px;
  padding: 0 10px; font: inherit; margin-bottom: 8px;
}

/* List */
.ext-list { overflow-y: auto; flex: 1 1 auto; }
.ext-item {
  padding: 8px; border-bottom: 1px solid var(--line); cursor: pointer;
  border-radius: 4px; margin-bottom: 2px;
}
.ext-item:hover { background: #f8fafc; }
.ext-item.selected { background: #eef5ff; border-color: var(--accent); }
.ext-item.quarantined { opacity: .68; background: #f9fafb; }
.ext-title { font-weight: 600; font-size: 13px; margin-bottom: 2px; }
.ext-meta { display: flex; gap: 6px; align-items: center; font-size: 12px; }
.amb-badge {
  padding: 1px 6px; border-radius: 999px; font-size: 11px; font-weight: 600;
}
.amb-badge.high { background: #fee2e2; color: #991b1b; }
.amb-badge.medium { background: #fef3c7; color: #92400e; }
.amb-badge.low { background: #dcfce7; color: #166534; }
.badge {
  padding: 1px 6px; border-radius: 999px; font-size: 11px;
}
.model-badge { font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 999px; }
.model-badge.mimo { background: #ede9fe; color: #6d28d9; }
.model-badge.ollama { background: #e0f2fe; color: #0369a1; }
.badge.pending { background: #fef3c7; color: #92400e; }
.badge.approved { background: #dcfce7; color: #166534; }
.badge.needs_fix { background: #fee2e2; color: #991b1b; }
.badge.rejected { background: #f3f4f6; color: #6b7280; }
.badge.quarantined { background: #e5e7eb; color: #374151; }
.pagination { display: flex; justify-content: center; align-items: center; gap: 12px; margin-top: 8px; }
.pagination button { height: 28px; padding: 0 10px; border: 1px solid var(--line); border-radius: 4px; background: #fff; cursor: pointer; font: inherit; font-size: 12px; }
.pagination button:disabled { opacity: 0.4; cursor: default; }

/* Detail */
.detail-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.header-badges { display: flex; gap: 8px; }
.amb-badge.large, .badge.large { font-size: 13px; padding: 3px 10px; }
.section { margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--line); }
.section-title { font-size: 13px; text-transform: uppercase; color: #475467; margin-bottom: 8px; cursor: pointer; }
.kv-grid { display: grid; gap: 4px 8px; font-size: 13px; }
.kv-item { display: grid; grid-template-columns: 140px 1fr; gap: 0 8px; }
.kv-label { color: var(--muted); }

/* Field table */
.field-table { font-size: 13px; }
.field-row { display: grid; grid-template-columns: 120px 1fr 60px; gap: 8px; padding: 6px 0; border-bottom: 1px solid var(--line); align-items: center; }
.field-row.header { font-weight: 600; color: var(--muted); font-size: 12px; }
.field-name { color: var(--muted); }
.field-select, .field-input {
  height: 28px; border: 1px solid var(--line); border-radius: 4px; padding: 0 6px; font: inherit; font-size: 12px; width: 100%;
}
.conf-badge { padding: 1px 6px; border-radius: 999px; font-size: 11px; }
.conf-badge.high { background: #dcfce7; color: #166534; }
.conf-badge.medium { background: #fef3c7; color: #92400e; }
.conf-badge.low { background: #fee2e2; color: #991b1b; }

/* Tags */
.tag-list { display: flex; gap: 4px; flex-wrap: wrap; }
.chip { display: inline-block; padding: 2px 8px; border-radius: 999px; background: var(--chip); font-size: 12px; }

/* Reasons */
.reason-list { font-size: 13px; }
.reason-item { padding: 4px 0; color: #92400e; }

/* Evidence */
.evidence-box { font-size: 12px; }
.evidence-item { display: flex; gap: 8px; padding: 4px 0; border-bottom: 1px solid var(--line); }
.ev-key { color: var(--muted); min-width: 100px; }
.ev-val { color: #374151; }

/* Review bar */
.review-bar {
  display: flex; gap: 8px; align-items: center; margin-top: 16px;
  padding-top: 12px; border-top: 1px solid var(--line);
}
.note-input {
  flex: 1; height: 32px; border: 1px solid var(--line); border-radius: 6px;
  padding: 0 10px; font: inherit;
}
.btn-approve { height: 32px; padding: 0 14px; border: 1px solid var(--ok); border-radius: 6px; background: #fff; color: var(--ok); cursor: pointer; font: inherit; }
.btn-fix { height: 32px; padding: 0 14px; border: 1px solid var(--warn); border-radius: 6px; background: #fff; color: var(--warn); cursor: pointer; font: inherit; }
.btn-reject { height: 32px; padding: 0 14px; border: 1px solid var(--bad); border-radius: 6px; background: #fff; color: var(--bad); cursor: pointer; font: inherit; }
.btn-quarantine { height: 32px; padding: 0 14px; border: 1px solid #4b5563; border-radius: 6px; background: #fff; color: #4b5563; cursor: pointer; font: inherit; }
.btn-quarantine:disabled { opacity: .5; cursor: default; }

.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.4); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.modal-box { background: #fff; border-radius: 8px; padding: 22px; width: 440px; max-width: 90vw; box-shadow: 0 8px 32px rgba(0,0,0,.18); }
.modal-box h3 { margin: 0 0 8px; font-size: 16px; color: #111827; }
.modal-desc { font-size: 13px; color: #6b7280; margin-bottom: 16px; line-height: 1.5; }
.modal-reasons { display: flex; flex-direction: column; gap: 8px; margin-bottom: 20px; }
.reason-option { display: flex; align-items: flex-start; gap: 8px; font-size: 13px; cursor: pointer; padding: 6px 8px; border-radius: 6px; transition: background .1s; }
.reason-option:hover { background: #f3f4f6; }
.reason-option input { margin-top: 2px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 10px; }
.btn-cancel { height: 34px; padding: 0 16px; border: 1px solid var(--line); border-radius: 6px; background: #fff; cursor: pointer; font: inherit; }
.btn-confirm-quarantine { height: 34px; padding: 0 16px; border: none; border-radius: 6px; background: var(--bad); color: #fff; cursor: pointer; font: inherit; font-weight: 600; }
.btn-confirm-quarantine:disabled { opacity: .5; cursor: default; }

/* PDF preview */
.ctrl-btn { height: 26px; padding: 0 8px; border: 1px solid var(--line); border-radius: 4px; font-size: 11px; background: #fff; cursor: pointer; transition: all .15s; }
.ctrl-btn.active { background: var(--accent); color: #fff; border-color: var(--accent); }
.ctrl-btn:disabled { opacity: 0.4; cursor: default; }
.ctrl-btn:active:not(:disabled) { transform: scale(0.95); }
.pdf-toggle { font-weight: 600; }
.pdf-link { font-size: 12px; color: var(--accent); text-decoration: none; align-self: center; }
.pdf-link:hover { text-decoration: underline; }

/* Work metadata */
.work-abstract { margin-top: 6px; font-size: 13px; }
.abstract-text {
  margin-top: 4px; max-height: 120px; overflow-y: auto;
  font-size: 12px; color: #374151; line-height: 1.5;
  white-space: pre-wrap; word-break: break-word;
}

/* Searchable select */
.searchable-select-wrap { position: relative; width: 100%; }
.ss-input-row { display: flex; gap: 4px; }
.ss-input {
  flex: 1; height: 28px; border: 1px solid var(--line); border-radius: 4px;
  padding: 0 6px; font: inherit; font-size: 12px; min-width: 0;
}
.ss-input[readonly] { background: #f9fafb; cursor: pointer; }
.ss-clear {
  width: 24px; height: 28px; border: 1px solid var(--line); border-radius: 4px;
  background: #fff; cursor: pointer; font-size: 14px; color: var(--muted);
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.ss-clear:hover { color: var(--bad); border-color: var(--bad); }
.ss-dropdown {
  position: absolute; top: 100%; left: 0; right: 0; z-index: 100;
  max-height: 200px; overflow-y: auto; background: #fff;
  border: 1px solid var(--line); border-radius: 4px;
  box-shadow: 0 4px 12px rgba(0,0,0,.1); margin-top: 2px;
}
.ss-option {
  padding: 6px 8px; font-size: 12px; cursor: pointer; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis;
}
.ss-option:hover { background: #f0f5ff; }
.ss-option.selected { background: #e0ecff; font-weight: 600; }
.ss-option.ss-empty { color: var(--muted); cursor: default; }

</style>
