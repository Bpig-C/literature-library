<template>
  <div class="review-layout" :class="{ 'with-pdf': selected && showPdfDrawer }" :style="layoutStyle">
    <!-- Left: list panel -->
    <div class="list-panel" :class="{ collapsed: listCollapsed }">
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
            <span class="model-badge" :class="ext.model_name?.startsWith('mimo') ? 'mimo' : 'ollama'">{{ ext.model_name?.startsWith('mimo') ? 'Mimo' : 'Ollama' }}</span>
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
          <div class="muted tiny">{{ selected.work_id }} · {{ selected.model_name }} · {{ selected.created_at?.slice(0, 19) }}</div>
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
          <div class="field-actions">操作</div>
        </div>
        <div v-for="f in metadataFields" :key="f.key" class="field-row" :class="{ missing: isMissing(f.key) }">
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
            <!-- generic list/json field -->
            <template v-else-if="f.type === 'list'">
              <textarea
                class="full-input mono-input"
                rows="4"
                :value="formatJsonValue(editForm[f.key])"
                @input="updateJsonField(f.key, $event.target.value)"
              ></textarea>
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
          <div class="field-actions">
            <button
              v-if="canRerunField(f)"
              class="field-action-btn rerun"
              :disabled="fieldBusyKey === f.key || rerunApplyLoading"
              :title="`只重抽${f.label}`"
              @click.stop="previewFieldRerun(f)"
            >
              {{ fieldBusyKey === f.key ? '...' : '重抽' }}
            </button>
            <button
              v-if="canRerunField(f)"
              class="field-action-btn copy"
              :disabled="promptBusyKey === f.key"
              :title="`复制${f.label}重抽 prompt`"
              @click.stop="copyFieldPrompt(f)"
            >
              {{ promptBusyKey === f.key ? '...' : '复制' }}
            </button>
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

      <!-- Rerun preview modal -->
      <div v-if="showRerunModal" class="modal-overlay" @click.self="closeRerunModal">
        <div class="modal-box rerun-modal">
          <h3>字段重抽预览</h3>
          <p class="modal-desc">
            只会用新结果覆盖指定字段；其余字段沿用旧抽取。确认后会创建新的 metadata extraction，并把旧记录标记为 superseded。
          </p>
          <div class="rerun-diff-list">
            <div v-for="(diff, key) in rerunPreview?.diff || {}" :key="key" class="rerun-diff-item">
              <div class="rerun-diff-title">
                {{ rerunFieldLabel(key) }}
                <span class="rerun-changed" :class="{ yes: diff.changed }">{{ diff.changed ? '已变化' : '未变化' }}</span>
              </div>
              <div class="rerun-diff-grid">
                <div>
                  <div class="tiny muted">旧值</div>
                  <pre>{{ stringifyValue(diff.old) }}</pre>
                </div>
                <div>
                  <div class="tiny muted">新值</div>
                  <pre>{{ stringifyValue(diff.new) }}</pre>
                </div>
              </div>
            </div>
          </div>
          <div class="modal-actions">
            <button class="btn-cancel" @click="closeRerunModal">取消</button>
            <button class="btn-confirm-rerun" :disabled="rerunApplyLoading" @click="applyRerunPreview">
              {{ rerunApplyLoading ? '写入中...' : '确认写入' }}
            </button>
          </div>
        </div>
      </div>

      <!-- Prompt fallback modal -->
      <div v-if="showPromptModal" class="modal-overlay" @click.self="showPromptModal = false">
        <div class="modal-box prompt-modal">
          <h3>复制重抽 Prompt</h3>
          <p class="modal-desc">剪贴板不可用时，可以从这里手动复制，再交给本地模型或 CLI 处理。</p>
          <textarea class="prompt-textarea" readonly :value="rerunPromptText"></textarea>
          <div class="modal-actions">
            <button class="btn-cancel" @click="showPromptModal = false">关闭</button>
            <button class="btn-confirm-rerun" @click="copyPromptText">再次复制</button>
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
  reviewMetadata,
  batchApproveLowRisk,
  quarantineFromReview,
  previewMetadataRerun,
  applyMetadataRerun,
  getMetadataRerunPrompt,
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
const modelFilter = ref('all')
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
const activePdfWorkId = ref(null)
const pdfPreviewKey = ref(0)
const listWidth = ref(340)
const listPrevWidth = ref(340)
const listCollapsed = ref(false)
const detailWidth = ref(null)
const fieldBusyKey = ref('')
const promptBusyKey = ref('')
const showRerunModal = ref(false)
const rerunPreview = ref(null)
const rerunApplyLoading = ref(false)
const showPromptModal = ref(false)
const rerunPromptText = ref('')
const metadataFields = ref([...DEFAULT_FIELDS])

const confidence = computed(() => selected.value?.confidence_json || {})
const evidence = computed(() => selected.value?.extracted_json?.evidence || {})

const pdfLink = computed(() => selected.value ? pdfUrl(selected.value.work_id) : '#')
const pdfDrawerKey = computed(() => `${activePdfWorkId.value || 'none'}:${pdfPreviewKey.value}`)

const notePlaceholder = computed(() => {
  if (!selected.value) return '审核备注...'
  const model = selected.value.model_name || ''
  const isMimo = model.startsWith('mimo')
  return isMimo
    ? '审核备注（可选）...'
    : '拒绝时请注明原因，Mimo 将重新抽取...'
})

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
}

function apiRerunFieldKey(field) {
  return field.key
}

function canRerunField(field) {
  return Boolean(apiRerunFieldKey(field))
}

function rerunFieldLabel(key) {
  return metadataFields.value.find(f => f.key === key)?.label || key
}

function stringifyValue(value) {
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
  if (modelFilter.value !== 'all') params.model = modelFilter.value
  if (search.value) params.search = search.value
  if (includeQuarantined.value) params.include_quarantined = true
  params.sort = sortKey.value
  params.order = sortDir.value
  const res = await getMetadataExtractions(params)
  extractions.value = res.extractions
  total.value = res.total
  summary.value = res.summary
}

async function doBatchApprove() {
  dialog.warning({
    title: '批量批准',
    content: '确认批量批准所有低风险待审记录？',
    positiveText: '确认',
    negativeText: '取消',
    onPositiveClick: async () => {
      const res = await batchApproveLowRisk()
      message.success(`已批准 ${res.approved} 条，回填 ${res.applied} 条`)
      await loadList()
    },
  })
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
    message.warning('拒绝时请填写原因，便于 Mimo 重新抽取')
    return
  }
  // Validate fields before submission
  if (editForm.value.doi && !/^(10\.\d{4,}\/|doi:)/.test(editForm.value.doi)) {
    message.warning('DOI 格式似乎不正确')
    return
  }
  if (editForm.value.url && !/^https?:\/\//.test(editForm.value.url)) {
    message.warning('URL 需要以 http:// 或 https:// 开头')
    return
  }
  if (editForm.value.arxiv_id && !/^\d{4}\.\d{4,5}(v\d+)?$/.test(editForm.value.arxiv_id)) {
    message.warning('arXiv ID 格式似乎不正确（应为如 2301.12345）')
    return
  }
  const editedFields = {}
  // Build diff: only send fields that changed from original extracted_json
  const orig = selected.value.extracted_json || {}
  for (const f of metadataFields.value) {
    if (f.type === 'date-object') {
      const cur = JSON.stringify(editForm.value[f.key])
      const oth = JSON.stringify(orig[f.key] || orig.date) // fallback for legacy date field
      if (cur !== oth) editedFields[f.key] = editForm.value[f.key]
    } else if (f.type === 'author-list' || f.type === 'inst-list' || f.type === 'contributor-list') {
      // These are read-only, don't send diffs
    } else if (f.type === 'list') {
      if (JSON.stringify(editForm.value[f.key] || []) !== JSON.stringify(orig[f.key] || [])) {
        editedFields[f.key] = editForm.value[f.key]
      }
    } else {
      if (editForm.value[f.key] !== (orig[f.key] || '')) {
        editedFields[f.key] = editForm.value[f.key]
      }
    }
  }
  // 记住当前条位置，审完后自动跳下一条 pending
  const reviewedId = selected.value.id
  const prevIdx = extractions.value.findIndex(e => e.id === reviewedId)
  await reviewMetadata(selected.value.id, {
    review_status: status,
    review_note: reviewNote.value,
    edited_fields: Object.keys(editedFields).length ? editedFields : null,
  })
  await loadList()
  selectNextPending(reviewedId, prevIdx)
}

// 审核完成后自动选中下一条 pending：优先原位置之后，没有则取第一条 pending；无 pending 则清空选中
function selectNextPending(reviewedId, prevIdx) {
  const list = extractions.value
  // 若原位置仍是被审条（如“全部”筛选下未移出列表），从其后一位开始找
  const startIdx = list[prevIdx]?.id === reviewedId ? prevIdx + 1 : prevIdx
  let next = null
  for (let i = Math.max(startIdx, 0); i < list.length; i++) {
    if (list[i].review_status === 'pending') { next = list[i]; break }
  }
  if (!next) next = list.find(e => e.review_status === 'pending') || null
  if (next) selectExtraction(next)
  else selected.value = null
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
    message.error('隔离失败: ' + e.message)
  } finally {
    quarantineLoading.value = false
  }
}

async function previewFieldRerun(field) {
  if (!selected.value || !canRerunField(field)) return
  const apiField = apiRerunFieldKey(field)
  fieldBusyKey.value = field.key
  try {
    const res = await previewMetadataRerun(selected.value.id, [apiField], reviewNote.value.trim())
    rerunPreview.value = res
    showRerunModal.value = true
  } catch (e) {
    message.error(`重抽预览失败: ${e.message || e.detail || '未知错误'}`)
  } finally {
    fieldBusyKey.value = ''
  }
}

function closeRerunModal() {
  if (rerunApplyLoading.value) return
  showRerunModal.value = false
  rerunPreview.value = null
}

async function applyRerunPreview() {
  if (!selected.value || !rerunPreview.value) return
  rerunApplyLoading.value = true
  try {
    const applied = await applyMetadataRerun(
      selected.value.id,
      rerunPreview.value.preview_id,
      rerunPreview.value.new_extraction,
    )
    message.success('字段重抽结果已写入，旧记录已 supersede')
    showRerunModal.value = false
    rerunPreview.value = null
    await loadList()
    const row = extractions.value.find(e => e.id === applied.id) || applied
    selectExtraction(row)
  } catch (e) {
    message.error(`写入重抽结果失败: ${e.message || e.detail || '未知错误'}`)
  } finally {
    rerunApplyLoading.value = false
  }
}

async function copyFieldPrompt(field) {
  if (!selected.value || !canRerunField(field)) return
  const apiField = apiRerunFieldKey(field)
  promptBusyKey.value = field.key
  rerunPromptText.value = ''
  try {
    const res = await getMetadataRerunPrompt(selected.value.id, [apiField], reviewNote.value.trim())
    rerunPromptText.value = res.prompt || ''
    const copied = await copyPromptText()
    if (copied) {
      message.success(`${field.label}重抽 prompt 已复制`)
    } else {
      message.warning('剪贴板不可用，已打开手动复制窗口')
    }
  } catch (e) {
    message.error(`生成 prompt 失败: ${e.message || e.detail || '未知错误'}`)
  } finally {
    promptBusyKey.value = ''
  }
}

async function copyPromptText() {
  if (!rerunPromptText.value) return false
  if (!navigator.clipboard?.writeText) {
    showPromptModal.value = true
    return false
  }
  try {
    await navigator.clipboard.writeText(rerunPromptText.value)
    return true
  } catch {
    showPromptModal.value = true
    return false
  }
}

watch(statusFilter, () => { reset(); riskFilter.value = 'all'; modelFilter.value = 'all'; loadList() })
watch(riskFilter, () => { reset(); loadList() })
watch(modelFilter, () => { reset(); loadList() })
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
.list-panel.collapsed .model-bar,
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

/* Model filter */
.model-bar { display: flex; gap: 6px; align-items: center; margin-bottom: 8px; }
.model-btn { padding: 3px 8px; border: 1px solid var(--border); border-radius: var(--radius-md); font-size: 11px; background: var(--bg-surface); cursor: pointer; transition: all .15s; }
.model-btn:hover { border-color: var(--accent); }
.model-btn.active { font-weight: 600; border-color: var(--accent); background: var(--selected-bg); }
.model-btn.active.mimo { background: var(--accent-subtle); border-color: var(--accent); color: var(--accent); }
.model-btn.active.ollama { background: var(--info-bg); border-color: #0284c7; color: var(--info-fg); }

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
.model-badge { font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 999px; }
.model-badge.mimo { background: var(--accent-subtle); color: var(--accent); }
.model-badge.ollama { background: var(--info-bg); color: var(--info-fg); }

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
