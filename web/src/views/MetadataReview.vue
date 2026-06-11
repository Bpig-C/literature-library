<template>
  <div class="review-layout" :class="{ 'with-pdf': selected && showPdfDrawer }" :style="layoutStyle">
    <!-- Left: list panel -->
    <div class="list-panel">
      <h1>元数据审核</h1>
      <div class="stats-bar">
        <div v-for="s in STATUSES" :key="s.key" class="stat-card"
          :class="{ active: statusFilter === s.key }" @click="statusFilter = s.key">
          <b>{{ summary[s.key] || 0 }}</b><span>{{ s.label }}</span>
        </div>
      </div>
      <!-- Model filter -->
      <div class="model-bar">
        <button v-for="m in MODELS" :key="m.key" class="model-btn" :class="{ active: modelFilter === m.key, [m.key]: true }"
          @click="modelFilter = m.key">{{ m.label }} ({{ summary.model?.[m.key] || 0 }})</button>
      </div>
      <!-- Risk filter -->
      <div class="risk-bar">
        <span class="risk-label">风险:</span>
        <button v-for="r in RISKS" :key="r.key" class="risk-btn" :class="{ active: riskFilter === r.key, [r.key]: true }"
          @click="riskFilter = r.key">{{ r.label }} ({{ summary.risk?.[r.key] || 0 }})</button>
        <button v-if="statusFilter === 'pending' && summary.risk?.low > 0" class="batch-btn" @click="doBatchApprove">
          批量批准低风险 ({{ summary.risk.low }})
        </button>
      </div>
      <input v-model="search" placeholder="搜索标题、ID..." class="search-input" />
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
            <span class="badge" :class="ext.review_status">{{ statusLabel(ext.review_status) }}</span>
            <span v-if="ext.work_read_status === 'quarantined'" class="badge quarantined">已隔离</span>
            <span class="model-badge" :class="ext.model_name?.startsWith('mimo') ? 'mimo' : 'ollama'">{{ ext.model_name?.startsWith('mimo') ? 'Mimo' : 'Ollama' }}</span>
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
          <div class="muted tiny">{{ selected.work_id }} · {{ selected.model_name }} · {{ selected.created_at?.slice(0, 19) }}</div>
        </div>
        <div class="header-badges">
          <span class="risk-badge large" :class="selected.risk_level" v-if="selected.risk_level && selected.risk_level !== 'pending'">
            risk {{ selected.risk_score }}
          </span>
          <span class="badge large" :class="selected.review_status">{{ statusLabel(selected.review_status) }}</span>
          <span v-if="selected.work_read_status === 'quarantined'" class="badge large quarantined">已隔离</span>
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
        <div v-for="f in FIELDS" :key="f.key" class="field-row" :class="{ missing: isMissing(f.key) }">
          <div class="field-name">{{ f.label }}</div>
          <div class="field-current">{{ formatCurrent(f) }}</div>
          <div class="field-extracted">
            <!-- date object -->
            <template v-if="f.type === 'date-object'">
              <div class="date-obj">
                <input v-model.number="editForm[f.key].year" type="number" placeholder="year" class="sm-input" />
                <input v-model.number="editForm[f.key].month" type="number" placeholder="m" class="xs-input" />
                <input v-model.number="editForm[f.key].day" type="number" placeholder="d" class="xs-input" />
                <input v-model="editForm[f.key].raw" placeholder="raw" class="md-input" />
                <select v-model="editForm[f.key].kind" class="sm-input">
                  <option value="exact">exact</option>
                  <option value="inferred">inferred</option>
                </select>
              </div>
            </template>
            <!-- textarea for abstract -->
            <template v-else-if="f.type === 'textarea'">
              <textarea v-model="editForm[f.key]" rows="4" class="full-input"></textarea>
            </template>
            <!-- author/inst/contributor list (read-only) -->
            <template v-else-if="f.type === 'author-list' || f.type === 'inst-list' || f.type === 'contributor-list'">
              <div class="list-display">
                <div v-for="(item, i) in (editForm[f.key] || [])" :key="i" class="list-item">
                  <template v-if="f.type === 'author-list'">
                    {{ item.name || item }}
                    <span class="muted tiny" v-if="item.affiliations?.length">({{ item.affiliations.join(', ') }})</span>
                  </template>
                  <template v-else-if="f.type === 'contributor-list'">
                    {{ item.name || item }}
                    <span class="muted tiny" v-if="item.type">[{{ item.type }}]</span>
                    <span class="muted tiny" v-if="item.role">{{ item.role }}</span>
                  </template>
                  <template v-else>
                    {{ item.name || item }}
                    <span class="muted tiny" v-if="item.type">[{{ item.type }}]</span>
                    <span class="muted tiny" v-if="item.country_or_region">{{ item.country_or_region }}</span>
                  </template>
                </div>
                <div v-if="selected.extracted_json?.all_authors?.length" class="all-authors-toggle">
                  <button class="link-btn" @click="showAllAuthors = !showAllAuthors">
                    {{ showAllAuthors ? '收起' : `展开全部 ${selected.extracted_json.all_authors.length} 位作者` }}
                  </button>
                  <div v-if="showAllAuthors" class="all-authors-list">
                    <span v-for="(a, i) in selected.extracted_json.all_authors" :key="i" class="author-tag">
                      {{ a.name || a }}
                    </span>
                  </div>
                </div>
              </div>
            </template>
            <!-- default: text input -->
            <template v-else>
              <input v-model="editForm[f.key]" :type="f.type === 'number' ? 'number' : 'text'" class="full-input" />
            </template>
          </div>
          <div class="field-conf">
            <span v-if="confidence[f.key]" class="conf-badge" :class="confidence[f.key]">{{ confidence[f.key] }}</span>
          </div>
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

      <!-- Review note -->
      <div class="review-bar">
        <input v-model="reviewNote" :placeholder="notePlaceholder" class="note-input" />
        <button class="btn-approve" @click="doReview('approved')" title="结果正确，覆盖写入 works 表，同 work 其他抽取自动 supersede">批准</button>
        <button class="btn-fix" @click="doReview('needs_fix')" title="有小问题，我在页面上直接编辑后重新批准">需修正</button>
        <button class="btn-reject" @click="doReview('rejected')" title="抽取完全不对，拒绝后通知 Mimo 重新抽取">拒绝</button>
        <button class="btn-quarantine" @click="openQuarantineModal" title="这篇文献本身没价值（404/空页面），整个隔离">隔离此文献</button>
      </div>

      <!-- Quarantine modal -->
      <div v-if="showQuarantineModal" class="modal-overlay" @click.self="showQuarantineModal = false">
        <div class="modal-box">
          <h3>隔离文献</h3>
          <p class="modal-desc">隔离后，该文献将从审核队列、自动回填、分析运行和综述矩阵中移出。源文件移入隔离区，但解析产物和抽取历史会保留。</p>
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
      v-if="selected && showPdfDrawer"
      :key="pdfPreviewKey"
      :url="pdfLink"
      :work-id="selected.work_id"
      @close="closePdfDrawer"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { getMetadataExtractions, reviewMetadata, batchApproveLowRisk, quarantineFromReview, contentUrl, pdfUrl } from '../api'
import PdfPreviewDrawer from '../components/PdfPreviewDrawer.vue'
import ResizeHandle from '../components/ResizeHandle.vue'

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

const MODELS = [
  { key: 'all', label: '全部模型' },
  { key: 'mimo', label: 'Mimo 2.5 Pro' },
  { key: 'ollama', label: 'Ollama' },
]

const QUARANTINE_REASONS = [
  { key: 'bad_source', label: '坏源：PDF 内容为空、反爬页、扫描损坏等' },
  { key: 'out_of_scope', label: '不在范围：不属于当前研究主题或综述范围' },
  { key: 'not_literature', label: '非文献：不是论文、报告、标准等目标文献' },
  { key: 'duplicate_residual', label: '重复残留：已由其他 work 覆盖' },
  { key: 'needs_rerun', label: '待重跑：主题对，但上传文档本身有问题，需替换后重新抽取' },
  { key: 'user_removed', label: '用户移除：明确不想保留' },
]

const FIELDS = [
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

const statusFilter = ref('pending')
const riskFilter = ref('all')
const modelFilter = ref('all')
const search = ref('')
const includeQuarantined = ref(false)
const page = ref(1)
const perPage = 20
const total = ref(0)
const summary = ref({})
const extractions = ref([])
const selected = ref(null)
const editForm = ref({})
const reviewNote = ref('')
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
const showQuarantineModal = ref(false)
const quarantineReason = ref('')
const quarantineLoading = ref(false)
const showPdfDrawer = ref(false)
const pdfPreviewKey = ref(0)
const listWidth = ref(340)
const detailWidth = ref(null)

const totalPages = computed(() => Math.ceil(total.value / perPage))

const confidence = computed(() => selected.value?.confidence_json || {})
const evidence = computed(() => selected.value?.extracted_json?.evidence || {})

const pdfLink = computed(() => selected.value ? pdfUrl(selected.value.work_id) : '#')

const notePlaceholder = computed(() => {
  if (!selected.value) return '审核备注...'
  const model = selected.value.model_name || ''
  const isMimo = model.startsWith('mimo')
  return isMimo
    ? '审核备注（可选）...'
    : '拒绝时请注明原因，Mimo 将重新抽取...'
})

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

function onResizeList(w) {
  listWidth.value = Math.max(260, Math.min(w, 640))
}

function onResizeDetail(w) {
  detailWidth.value = Math.max(320, Math.min(w, 960))
}

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
  const params = { status: statusFilter.value, page: page.value, per_page: perPage }
  if (riskFilter.value !== 'all') params.risk = riskFilter.value
  if (modelFilter.value !== 'all') params.model = modelFilter.value
  if (search.value) params.search = search.value
  if (includeQuarantined.value) params.include_quarantined = true
  const res = await getMetadataExtractions(params)
  extractions.value = res.extractions
  total.value = res.total
  summary.value = res.summary
}

async function doBatchApprove() {
  if (!confirm('确认批量批准所有低风险待审记录？')) return
  const res = await batchApproveLowRisk()
  alert(`已批准 ${res.approved} 条，回填 ${res.applied} 条`)
  await loadList()
}

function selectExtraction(ext) {
  const keepPdfOpen = showPdfDrawer.value
  selected.value = ext
  if (keepPdfOpen) pdfPreviewKey.value += 1
  const ej = ext.extracted_json || {}
  editForm.value = {
    title: ej.title || '',
    title_zh: ej.title_zh || '',
    publication_date: { year: ej.publication_date?.year ?? ej.date?.year ?? null, month: ej.publication_date?.month ?? ej.date?.month ?? null, day: ej.publication_date?.day ?? ej.date?.day ?? null, raw: ej.publication_date?.raw || ej.date?.raw || '', kind: ej.publication_date?.kind || ej.date?.kind || 'inferred' },
    authors: ej.authors || [],
    contributors: ej.contributors || ej.institutions || [],
    doi: ej.doi || '',
    arxiv_id: ej.arxiv_id || '',
    venue: ej.venue || '',
    url: ej.url || '',
    abstract: ej.abstract || '',
  }
  reviewNote.value = ''
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

async function doReview(status) {
  if (!selected.value) return
  if (status === 'rejected' && !reviewNote.value.trim()) {
    alert('拒绝时请填写原因，便于 Mimo 重新抽取')
    return
  }
  const editedFields = {}
  // Build diff: only send fields that changed from original extracted_json
  const orig = selected.value.extracted_json || {}
  for (const f of FIELDS) {
    if (f.type === 'date-object') {
      const cur = JSON.stringify(editForm.value[f.key])
      const oth = JSON.stringify(orig[f.key] || orig.date) // fallback for legacy date field
      if (cur !== oth) editedFields[f.key] = editForm.value[f.key]
    } else if (f.type === 'author-list' || f.type === 'inst-list' || f.type === 'contributor-list') {
      // These are read-only, don't send diffs
    } else {
      if (editForm.value[f.key] !== (orig[f.key] || '')) {
        editedFields[f.key] = editForm.value[f.key]
      }
    }
  }
  await reviewMetadata(selected.value.id, {
    review_status: status,
    review_note: reviewNote.value,
    edited_fields: Object.keys(editedFields).length ? editedFields : null,
  })
  await loadList()
  // Re-select updated item
  const updated = extractions.value.find(e => e.id === selected.value?.id)
  if (updated) selectExtraction(updated)
}

function openQuarantineModal() {
  quarantineReason.value = ''
  showQuarantineModal.value = true
}

async function doQuarantine() {
  if (!selected.value || !quarantineReason.value) return
  quarantineLoading.value = true
  try {
    await quarantineFromReview(selected.value.id, quarantineReason.value)
    showQuarantineModal.value = false
    selected.value = null
    await loadList()
  } catch (e) {
    alert('隔离失败: ' + e.message)
  } finally {
    quarantineLoading.value = false
  }
}

watch(statusFilter, () => { page.value = 1; riskFilter.value = 'all'; modelFilter.value = 'all'; loadList() })
watch(riskFilter, () => { page.value = 1; loadList() })
watch(modelFilter, () => { page.value = 1; loadList() })
watch(includeQuarantined, () => { page.value = 1; loadList() })
let searchTimer = null
watch(search, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { page.value = 1; loadList() }, 300)
})

onMounted(loadList)
</script>

<style scoped>
.review-layout { display: grid; grid-template-columns: 340px 6px minmax(0, 1fr); gap: 0; height: calc(100vh - 40px); }
.list-panel { min-width: 0; border-right: 1px solid var(--line); overflow-y: auto; padding: 16px; background: var(--panel); }
.detail-panel { min-width: 0; overflow-y: auto; padding: 20px 24px; }
.detail-panel.empty-state { display: flex; align-items: center; justify-content: center; color: var(--muted); }
h1 { font-size: 18px; margin-bottom: 12px; }
h2 { font-size: 16px; margin-bottom: 2px; }

/* Stats bar */
.stats-bar { display: flex; gap: 6px; margin-bottom: 10px; flex-wrap: wrap; }
.stat-card { padding: 6px 10px; border: 1px solid var(--line); border-radius: 6px; cursor: pointer; font-size: 12px; background: var(--panel); transition: all .15s; }
.stat-card:hover { border-color: var(--accent); }
.stat-card.active { background: #eef5ff; border-color: var(--accent); color: var(--accent); }
.stat-card b { display: block; font-size: 16px; }
.stat-card span { color: var(--muted); }

/* Search */
.search-input { width: 100%; height: 32px; border: 1px solid var(--line); border-radius: 6px; padding: 0 10px; font: inherit; margin-bottom: 10px; }
.include-toggle { display: flex; align-items: center; gap: 6px; margin: -2px 0 10px; color: var(--muted); font-size: 12px; user-select: none; }
.include-toggle input { margin: 0; }

/* Risk filter bar */
.risk-bar { display: flex; gap: 6px; align-items: center; margin-bottom: 8px; flex-wrap: wrap; }
.risk-label { font-size: 12px; color: var(--muted); }
.risk-btn { padding: 3px 8px; border: 1px solid var(--line); border-radius: 4px; font-size: 11px; background: #fff; cursor: pointer; transition: all .15s; }
.risk-btn:hover { border-color: var(--accent); }
.risk-btn.active { font-weight: 600; border-color: var(--accent); background: #eef5ff; }
.risk-btn.active.high { background: #fee2e2; border-color: #c32f27; color: #991b1b; }
.risk-btn.active.medium { background: #fef9c3; border-color: #9a6700; color: #92400e; }
.risk-btn.active.low { background: #dcfce7; border-color: #16833a; color: #15803d; }
.batch-btn { padding: 3px 10px; border: 1px solid #16833a; border-radius: 4px; font-size: 11px; background: #dcfce7; color: #15803d; cursor: pointer; font-weight: 600; margin-left: auto; }
.batch-btn:hover { background: #16833a; color: #fff; }

/* Model filter */
.model-bar { display: flex; gap: 6px; align-items: center; margin-bottom: 8px; }
.model-btn { padding: 3px 8px; border: 1px solid var(--line); border-radius: 4px; font-size: 11px; background: #fff; cursor: pointer; transition: all .15s; }
.model-btn:hover { border-color: var(--accent); }
.model-btn.active { font-weight: 600; border-color: var(--accent); background: #eef5ff; }
.model-btn.active.mimo { background: #ede9fe; border-color: #7c3aed; color: #6d28d9; }
.model-btn.active.ollama { background: #e0f2fe; border-color: #0284c7; color: #0369a1; }

/* Extraction list */
.ext-list { max-height: calc(100vh - 260px); overflow-y: auto; }
.ext-item { padding: 8px 10px; border: 1px solid transparent; border-radius: 6px; cursor: pointer; margin-bottom: 4px; transition: all .1s; }
.ext-item:hover { background: var(--bg); }
.ext-item.selected { background: #eef5ff; border-color: var(--accent); }
.ext-item.quarantined { opacity: .68; background: #f9fafb; }
.ext-title { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ext-meta { display: flex; gap: 6px; align-items: center; font-size: 11px; color: var(--muted); margin-top: 2px; }

/* Pagination */
.pagination { display: flex; align-items: center; justify-content: center; gap: 8px; margin-top: 10px; font-size: 12px; }
.pagination button { height: 28px; padding: 0 10px; border: 1px solid var(--line); border-radius: 4px; background: #fff; cursor: pointer; font: inherit; }
.pagination button:disabled { opacity: 0.4; cursor: default; }

/* Detail header */
.detail-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }

/* Badges */
.badge { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 999px; }
.badge.large { font-size: 13px; padding: 4px 12px; }
.badge.pending { background: #fef9c3; color: #92400e; }
.badge.approved { background: #dcfce7; color: #15803d; }
.badge.needs_fix { background: #fed7aa; color: #9a3412; }
.badge.rejected { background: #fee2e2; color: #991b1b; }
.badge.quarantined { background: #e5e7eb; color: #374151; }
.model-badge { font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 999px; }
.model-badge.mimo { background: #ede9fe; color: #6d28d9; }
.model-badge.ollama { background: #e0f2fe; color: #0369a1; }

/* Risk badges */
.risk-badge { font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 999px; }
.risk-badge.large { font-size: 12px; padding: 3px 10px; }
.risk-badge.low { background: #dcfce7; color: #15803d; }
.risk-badge.medium { background: #fef9c3; color: #92400e; }
.risk-badge.high { background: #fee2e2; color: #991b1b; }
.header-badges { display: flex; gap: 8px; align-items: center; }

/* Risk reasons */
.risk-reasons { margin-bottom: 16px; background: #fef2f2; border: 1px solid #fecaca; border-radius: 6px; padding: 12px; }
.risk-reasons h3 { color: #991b1b; }
.reason-list { font-size: 12px; }
.reason-item { padding: 3px 0; color: #7f1d1d; border-bottom: 1px solid #fecaca; }
.reason-item:last-child { border-bottom: none; }

/* Field table */
.field-table { border: 1px solid var(--line); border-radius: 6px; margin-bottom: 16px; }
.field-row { display: grid; grid-template-columns: 100px 1fr 1fr 60px; border-bottom: 1px solid var(--line); font-size: 13px; }
.field-row:last-child { border-bottom: none; }
.field-row.header { background: #f1f4f8; font-weight: 600; font-size: 12px; color: var(--muted); }
.field-row.missing .field-extracted { background: #fef2f2; }
.field-name { padding: 8px 10px; color: var(--muted); border-right: 1px solid var(--line); }
.field-current { padding: 8px 10px; color: #374151; border-right: 1px solid var(--line); word-break: break-word; }
.field-extracted { padding: 8px 10px; border-right: 1px solid var(--line); }
.field-conf { padding: 8px 6px; text-align: center; }

/* Inputs in field table */
.full-input { width: 100%; height: 30px; border: 1px solid var(--line); border-radius: 4px; padding: 0 6px; font: inherit; font-size: 13px; }
textarea.full-input { height: auto; padding: 6px; resize: vertical; }
.sm-input { height: 28px; border: 1px solid var(--line); border-radius: 4px; padding: 0 4px; font: inherit; font-size: 12px; }
.xs-input { width: 48px; height: 28px; border: 1px solid var(--line); border-radius: 4px; padding: 0 4px; font: inherit; font-size: 12px; }
.md-input { width: 100px; height: 28px; border: 1px solid var(--line); border-radius: 4px; padding: 0 4px; font: inherit; font-size: 12px; }
.date-obj { display: flex; gap: 4px; align-items: center; flex-wrap: wrap; }

/* Confidence badges */
.conf-badge { font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 999px; }
.conf-badge.high { background: #dcfce7; color: #15803d; }
.conf-badge.medium { background: #fef9c3; color: #92400e; }
.conf-badge.low { background: #fee2e2; color: #991b1b; }

/* List displays */
.list-display { font-size: 12px; }
.list-item { padding: 2px 0; }
.all-authors-toggle { margin-top: 4px; }
.all-authors-list { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
.author-tag { padding: 1px 6px; background: var(--chip); border-radius: 4px; font-size: 11px; }
.link-btn { background: none; border: none; color: var(--accent); cursor: pointer; font: inherit; font-size: 12px; padding: 0; }

/* Evidence */
.section { margin-bottom: 16px; }
.section-title { font-size: 12px; text-transform: uppercase; color: #475467; cursor: pointer; user-select: none; margin-bottom: 6px; }
.evidence-box { background: var(--bg); border: 1px solid var(--line); border-radius: 6px; padding: 10px; font-size: 12px; }
.evidence-item { margin-bottom: 6px; }
.ev-key { font-weight: 600; color: var(--muted); margin-right: 6px; }
.ev-val { color: #374151; word-break: break-word; }

/* Review bar */
.review-bar { display: flex; gap: 8px; align-items: center; padding: 12px 0; border-top: 1px solid var(--line); margin-bottom: 12px; flex-wrap: wrap; }
.note-input { flex: 1; min-width: 200px; height: 34px; border: 1px solid var(--line); border-radius: 6px; padding: 0 10px; font: inherit; }
.review-bar button { height: 34px; padding: 0 16px; border: none; border-radius: 6px; cursor: pointer; font: inherit; font-weight: 600; }
.btn-approve { background: #16833a; color: #fff; }
.btn-fix { background: #9a6700; color: #fff; }
.btn-reject { background: #c32f27; color: #fff; }
.btn-quarantine { background: #6b7280; color: #fff; margin-left: 8px; border: 1px solid #4b5563; }
.btn-quarantine:hover { background: #4b5563; }

/* Quarantine modal */
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.modal-box { background: #fff; border-radius: 10px; padding: 24px; width: 440px; max-width: 90vw; box-shadow: 0 8px 32px rgba(0,0,0,0.18); }
.modal-box h3 { margin: 0 0 8px; font-size: 16px; color: #111827; }
.modal-desc { font-size: 13px; color: #6b7280; margin-bottom: 16px; line-height: 1.5; }
.modal-reasons { display: flex; flex-direction: column; gap: 8px; margin-bottom: 20px; }
.reason-option { display: flex; align-items: flex-start; gap: 8px; font-size: 13px; cursor: pointer; padding: 6px 8px; border-radius: 6px; transition: background .1s; }
.reason-option:hover { background: #f3f4f6; }
.reason-option input { margin-top: 2px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 10px; }
.btn-cancel { height: 34px; padding: 0 16px; border: 1px solid var(--line); border-radius: 6px; background: #fff; cursor: pointer; font: inherit; }
.btn-confirm-quarantine { height: 34px; padding: 0 16px; border: none; border-radius: 6px; background: #c32f27; color: #fff; cursor: pointer; font: inherit; font-weight: 600; }
.btn-confirm-quarantine:disabled { opacity: 0.5; cursor: default; }

/* Raw JSON */
.raw-json { font-size: 11px; font-family: Consolas, monospace; background: var(--bg); border: 1px solid var(--line); border-radius: 6px; padding: 10px; max-height: 300px; overflow: auto; white-space: pre-wrap; word-break: break-word; }

/* Preview panel */
.preview-section { border-top: 2px solid var(--accent); padding-top: 12px; }
.preview-header { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }
.preview-controls { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.ctrl-btn { height: 26px; padding: 0 8px; border: 1px solid var(--line); border-radius: 4px; font-size: 11px; background: #fff; cursor: pointer; }
.ctrl-btn.active { background: var(--accent); color: #fff; border-color: var(--accent); }
.ctrl-btn:disabled { opacity: 0.4; cursor: default; }
.ctrl-btn:active:not(:disabled) { transform: scale(0.95); }
.pdf-toggle { font-weight: 600; }
.preview-search { height: 26px; width: 160px; border: 1px solid var(--line); border-radius: 4px; padding: 0 6px; font: inherit; font-size: 12px; }
.pdf-link { font-size: 11px; color: var(--accent); margin-left: 8px; }
.preview-body { border: 1px solid var(--line); border-radius: 6px; max-height: 500px; overflow: auto; background: #fafbfc; }
.preview-text { font-size: 12px; font-family: Consolas, monospace; padding: 12px; margin: 0; white-space: pre-wrap; word-break: break-word; line-height: 1.6; }
.preview-text :deep(mark) { background: #fef08a; padding: 1px 2px; border-radius: 2px; }


/* Evidence clickable */
.evidence-item.clickable { cursor: pointer; padding: 4px 6px; border-radius: 4px; transition: background .1s; }
.evidence-item.clickable:hover { background: #eef5ff; }
.ev-locate { font-size: 11px; margin-left: 4px; opacity: 0; transition: opacity .15s; }
.evidence-item.clickable:hover .ev-locate { opacity: 1; }

/* Utility */
.muted { color: var(--muted); }
.tiny { font-size: 11px; }
.empty { padding: 24px; text-align: center; color: var(--muted); font-size: 13px; }

@media (max-width: 1180px) {
  .review-layout.with-pdf { grid-template-rows: minmax(0, 1fr) minmax(360px, 46vh); }
  .pdf-drawer { grid-column: 1 / -1; border-left: 0; border-top: 1px solid var(--line); }
}
</style>
