<template>
  <div class="works-page">
    <div class="page-intro">
      <div>
        <span class="page-kicker">KNOWLEDGE LIBRARY</span>
        <h1>文献库</h1>
        <p>在一个稳定、可追溯的空间中检索与组织研究材料。</p>
      </div>
      <div class="library-count"><strong>{{ totalMatching }}</strong><span>当前结果</span></div>
    </div>
    <div class="toolbar">
      <n-input v-model:value="search" type="text" placeholder="搜索标题、ID、arXiv..." clearable @input="debouncedLoad" style="width: 240px" />
      <n-select v-model:value="statusFilter" :options="STATUS_OPTIONS" style="width: 120px" @update:value="resetAndLoad" />
      <n-select v-model:value="typeFilter" :options="DOC_TYPE_OPTIONS" style="width: 120px" @update:value="resetAndLoad" />
      <n-select v-model:value="langFilter" :options="LANG_OPTIONS" style="width: 100px" @update:value="resetAndLoad" />
      <n-select v-model:value="sortKey" :options="sortOptions" style="width: 120px" @update:value="resetAndLoad" />
      <n-button quaternary @click="toggleSortDir" :title="sortDir === 'desc' ? '降序（最新在前）' : '升序（最旧在前）'">
        {{ sortDir === 'desc' ? '↓ 新→旧' : '↑ 旧→新' }}
      </n-button>
      <n-button quaternary :type="showAdvanced ? 'primary' : 'default'" @click="showAdvanced = !showAdvanced">
        {{ showAdvanced ? '收起筛选' : '高级筛选' }}
      </n-button>
      <n-button quaternary @click="showExportModal = true" title="导出 BibTeX / RIS / 综述矩阵">导出</n-button>
      <router-link to="/metadata-workspace">批量元数据 A →</router-link>
    </div>

    <div class="advanced-filters" v-if="showAdvanced">
      <div class="classified-bar">
        <n-switch v-model:value="classifiedOnly" @update:value="resetAndLoad" />
        <span class="classified-label">仅已分类</span>
        <n-tag v-if="classifiedOnly" type="success" size="small" round>{{ totalMatching }} 篇</n-tag>
        <n-divider vertical />
        <span class="filter-hint">多选筛选为 OR 逻辑（匹配任意一个）</span>
      </div>

      <div class="filter-grid">
        <div class="filter-item">
          <label>主文档类型</label>
          <n-select v-model:value="primaryDocTypeFilter" :options="PRIMARY_DOC_TYPE_OPTIONS" clearable placeholder="全部" @update:value="resetAndLoad" />
        </div>
        <div class="filter-item">
          <label>发布状态</label>
          <n-select v-model:value="publicationStatusFilter" :options="PUBLICATION_STATUS_OPTIONS" clearable placeholder="全部" @update:value="resetAndLoad" />
        </div>
        <div class="filter-item">
          <label>入库状态</label>
          <n-select v-model:value="ingestionStateFilter" :options="INGESTION_STATE_OPTIONS" clearable placeholder="全部" @update:value="resetAndLoad" />
        </div>
        <div class="filter-item">
          <label>优先级</label>
          <n-select v-model:value="priorityFilter" :options="PRIORITY_OPTIONS" clearable placeholder="全部" @update:value="resetAndLoad" />
        </div>
        <div class="filter-item wide">
          <label>风险关联（v5 研究解释）</label>
          <n-select v-model:value="riskFilter" :options="riskOptions" multiple filterable tag clearable placeholder="按 v5 解释中的风险现象筛选" @update:value="resetAndLoad" />
        </div>
        <div class="filter-item">
          <label>风险口径</label>
          <n-select v-model:value="riskScope" :options="RISK_SCOPE_OPTIONS" @update:value="resetAndLoad" />
        </div>
        <div class="filter-item wide" v-if="vocabError">
          <span class="filter-hint">{{ vocabError }}</span>
        </div>
      </div>
    </div>

    <div class="risk-banner" v-if="loadError" role="alert">
      ⚠ {{ loadError }}
    </div>
    <div class="risk-banner muted-banner" v-else-if="riskFilterNote">
      {{ riskFilterNote }}
    </div>

    <div class="count">{{ totalMatching }} / {{ total }} 篇文献</div>

    <div class="table-wrap" v-if="works.length">
      <table>
        <thead>
          <tr>
            <th>标题</th>
            <th>日期</th>
            <th>主类型</th>
            <th>语言</th>
            <th>来源</th>
            <th>解析</th>
            <th>入库</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="w in works" :key="w.id" @click="goToWork(w.id)">
            <td>
              <div class="title">{{ w.title || w.id }}</div>
              <div class="muted tiny">{{ w.id }}</div>
            </td>
            <td>{{ formatDate(w) }}</td>
            <td>{{ label(PRIMARY_DOC_TYPE_LABELS, w.primary_doc_type) || label(DOC_TYPE_LABELS, w.doc_type) }}</td>
            <td>{{ label(LANGUAGE_LABELS, w.language) }}</td>
            <td>
              <span v-if="w.total_source_count > w.source_count" :title="w.source_count + ' 个有效 / ' + (w.total_source_count - w.source_count) + ' 个已归档'">
                {{ w.unique_source_count }}<span class="muted">/{{ w.source_count }}</span>
              </span>
              <span v-else-if="w.source_count !== w.unique_source_count" :title="'去重后 ' + w.unique_source_count + ' 个'">
                {{ w.unique_source_count }}<span class="muted">/{{ w.source_count }}</span>
              </span>
              <span v-else>{{ w.source_count }}</span>
            </td>
            <td :class="'status-' + w.parse_status">{{ label(PARSE_STATUS_LABELS, w.parse_status) }}</td>
            <td :class="'status-' + w.ingestion_state">{{ label(INGESTION_STATE_LABELS, w.ingestion_state) }}</td>
            <td class="actions" @click.stop>
              <router-link class="metadata-action" :to="{ path: '/metadata-workspace', query: { work_id: w.id } }">A 元数据</router-link>
              <n-button v-if="w.read_status !== 'quarantined'" text type="error" size="small" :disabled="readOnly" title="只读部署：写操作被服务端禁用" @click="quarantine(w)">隔离</n-button>
              <n-button v-else text type="success" size="small" :disabled="readOnly" title="只读部署：写操作被服务端禁用" @click="restore(w)">恢复</n-button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <EmptyState v-else icon="search" title="没有匹配的文献" description="尝试调整筛选条件" />
    <n-pagination v-if="totalMatching > perPage" v-model:page="page" :page-count="matchingTotalPages" @update:page="loadData()" />

    <!-- Quarantine Modal -->
    <n-modal v-model:show="showQuarantineModal" preset="card" title="隔离文献" style="width: 420px">
      <p class="modal-desc">确定要隔离「{{ quarantineTarget?.title || quarantineTarget?.id }}」吗？</p>
      <n-input v-model:value="quarantineReason" placeholder="隔离原因（可选）" />
      <template #action>
        <n-button @click="showQuarantineModal = false">取消</n-button>
        <n-button type="error" :loading="quarantineLoading" :disabled="readOnly" @click="confirmQuarantine">确认隔离</n-button>
      </template>
    </n-modal>

    <!-- Export Modal -->
    <n-modal v-model:show="showExportModal" preset="card" title="导出文献" style="width: 440px">
      <p class="modal-desc">仅包含「存在活动书目投影（v5 传播 / legacy 迁移 / 人工修订）且未隔离」的文献。</p>
      <div class="export-group">
        <label>格式</label>
        <n-radio-group v-model:value="exportFormat">
          <n-radio-button value="bibtex">BibTeX</n-radio-button>
          <n-radio-button value="ris">RIS</n-radio-button>
          <n-radio-button value="matrix.csv">综述矩阵 CSV</n-radio-button>
        </n-radio-group>
      </div>
      <div class="export-group">
        <label>范围</label>
        <n-radio-group v-model:value="exportScope">
          <n-radio-button value="filtered">当前搜索与类型筛选</n-radio-button>
          <n-radio-button value="all">全部可导出文献</n-radio-button>
        </n-radio-group>
      </div>
      <template #action>
        <n-button @click="showExportModal = false">取消</n-button>
        <n-button type="primary" @click="doExport">下载</n-button>
      </template>
    </n-modal>
  </div>
</template>

<script setup>

import { useRuntimeMode } from '../composables/useRuntimeMode'
const { readOnly } = useRuntimeMode()
import { computed, ref, onMounted, nextTick } from 'vue'
import { useRouter, onBeforeRouteLeave } from 'vue-router'
import { useMessage, useDialog } from 'naive-ui'
import { usePagination } from '../composables/usePagination'
import { getWorks, quarantineWork, restoreWork, buildExportUrl, getResearchRiskVocab } from '../api'
import { DOC_TYPE_LABELS, PRIMARY_DOC_TYPE_LABELS, LANGUAGE_LABELS, PARSE_STATUS_LABELS, READ_STATUS_LABELS, INGESTION_STATE_LABELS, label } from '../labels'
import EmptyState from '../components/EmptyState.vue'

const router = useRouter()
const message = useMessage()
const dialog = useDialog()

// --- Options ---
const STATUS_OPTIONS = [
  { label: '状态：全部', value: 'all' },
  { label: '未读', value: 'unread' },
  { label: '已隔离', value: 'quarantined' },
]
const DOC_TYPE_OPTIONS = [
  { label: '类型：全部', value: 'all' },
  { label: '论文', value: 'paper' },
  { label: '报告', value: 'report' },
  { label: '系统卡', value: 'system_card' },
  { label: '基准测试', value: 'benchmark' },
  { label: '预印本', value: 'preprint' },
]
const LANG_OPTIONS = [
  { label: '语言：全部', value: 'all' },
  { label: '英文', value: 'en' },
  { label: '中文', value: 'zh' },
]
const PRIMARY_DOC_TYPE_OPTIONS = [
  { type: 'group', label: '功能定位类型（优先）', children: [
    { label: '系统卡/模型卡', value: 'system_model_card' },
    { label: '治理框架', value: 'governance_framework' },
    { label: '标准/指南', value: 'standard_guideline' },
    { label: '基准/数据集论文', value: 'benchmark_dataset_paper' },
    { label: '第三方评估报告', value: 'evaluation_report' },
  ]},
  { type: 'group', label: '文档形态类型', children: [
    { label: '技术报告', value: 'technical_report' },
    { label: '机构报告', value: 'institutional_report' },
    { label: '研究论文', value: 'research_article' },
    { label: '综述/评述', value: 'survey_review' },
    { label: '平台快照', value: 'platform_snapshot' },
    { label: '学位论文', value: 'thesis' },
    { label: '书章', value: 'book_chapter' },
    { label: '网页/博客', value: 'webpage_blog' },
    { label: '其他', value: 'other_literature' },
  ]},
  { type: 'group', label: '存在性标记', children: [
    { label: '工作流产物', value: 'workflow_artifact' },
    { label: '非文献', value: 'not_literature' },
  ]},
]
const PUBLICATION_STATUS_OPTIONS = [
  { label: '已发表', value: 'published' },
  { label: '预印本', value: 'preprint' },
  { label: '工作论文', value: 'working_paper' },
  { label: '草案', value: 'draft' },
  { label: '持续更新文档', value: 'living_document' },
  { label: '机构正式发布', value: 'institutional_release' },
  { label: '网页发布', value: 'webpage_release' },
  { label: '未知', value: 'unknown' },
]
const INGESTION_STATE_OPTIONS = [
  { label: '已核验', value: 'verified' },
  { label: '待核查', value: 'needs_review' },
  { label: '暂留', value: 'provisional' },
  { label: '已排除', value: 'excluded' },
  { label: '已废弃', value: 'deprecated' },
]
const PRIORITY_OPTIONS = [
  { label: '核心必读 (P0)', value: 'P0' },
  { label: '重要 (P1)', value: 'P1' },
  { label: '参考 (P2)', value: 'P2' },
  { label: '边缘 (P3)', value: 'P3' },
  { label: '归档', value: 'archive' },
]

// --- State ---
const works = ref([])
const { page, total, params: paginationParams, reset } = usePagination({ perPage: 50, mode: 'page' })
const totalMatching = ref(0)
const perPage = 50
const matchingTotalPages = computed(() => Math.ceil(totalMatching.value / perPage))
const search = ref('')
const statusFilter = ref('all')
const typeFilter = ref('all')
const langFilter = ref('all')
const showAdvanced = ref(false)
const primaryDocTypeFilter = ref(null)
const publicationStatusFilter = ref(null)
const ingestionStateFilter = ref(null)
const priorityFilter = ref(null)
const riskFilter = ref([])
const riskScope = ref('usable')
const riskOptions = ref([])
const riskFilterNote = ref('')
const loadError = ref('')
const RISK_SCOPE_OPTIONS = [
  { label: '可用基线（已核查稳定）', value: 'usable' },
  { label: '当前候选（含未核查）', value: 'candidate' },
]
const classifiedOnly = ref(false)
const sortKey = ref('created_at')
const sortDir = ref('desc')
const sortOptions = [
  { label: '入库时间', value: 'created_at' },
  { label: '年份', value: 'year' },
  { label: '标题', value: 'title' },
  { label: 'ID', value: 'id' },
]

const showQuarantineModal = ref(false)

// --- Export ---
const showExportModal = ref(false)
const exportFormat = ref('bibtex')
const exportScope = ref('all')

async function doExport() {
  const params = {}
  if (exportScope.value === 'filtered') {
    if (search.value) params.search = search.value
    if (primaryDocTypeFilter.value) params.doc_type = primaryDocTypeFilter.value
    else if (typeFilter.value !== 'all') params.doc_type = typeFilter.value
    // 风险筛选是当前视图的一部分，导出不得静默丢弃（R1 B2）
    if (riskFilter.value.length) {
      params.risk = riskFilter.value
      params.risk_scope = riskScope.value
    }
  }
  showExportModal.value = false
  try {
    const resp = await fetch(buildExportUrl(exportFormat.value, params), {
      credentials: 'include',
    })
    if (!resp.ok) {
      let detail = `导出失败（${resp.status}）`
      try {
        const body = await resp.json()
        const d = body?.detail
        if (typeof d === 'string') detail = d
        else if (d && typeof d === 'object') detail = d.message || d.error || detail
      } catch { /* 非 JSON 错误体保持默认文案 */ }
      message.error(detail)
      return
    }
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `literature-export.${exportFormat.value.includes('matrix') ? 'csv' : exportFormat.value.includes('ris') ? 'ris' : 'bib'}`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    message.success('已开始下载导出文件')
  } catch (e) {
    message.error('导出失败：' + (e.message || e))
  }
}
const quarantineReason = ref('')
const quarantineLoading = ref(false)
const quarantineTarget = ref(null)

let timer = null
function debouncedLoad() {
  clearTimeout(timer)
  timer = setTimeout(() => { reset(); loadData() }, 300)
}

function resetAndLoad() {
  reset()
  loadData()
  loadRiskVocab()
}

function toggleSortDir() {
  sortDir.value = sortDir.value === 'desc' ? 'asc' : 'desc'
  resetAndLoad()
}

function goToWork(id) {
  // Save current filter state for WorkDetail list panel to restore
  const filterState = {
    search: search.value,
    status: statusFilter.value,
    doc_type: typeFilter.value,
    language: langFilter.value,
    sort: sortKey.value,
    order: sortDir.value,
    primary_doc_type: primaryDocTypeFilter.value,
    publication_status: publicationStatusFilter.value,
    ingestion_state: ingestionStateFilter.value,
    priority: priorityFilter.value,
    classified_only: classifiedOnly.value,
    risk: riskFilter.value,
    risk_scope: riskScope.value,
  }
  sessionStorage.setItem('works_filters', JSON.stringify(filterState))
  router.push('/works/' + id)
}

function formatDate(w) {
  try {
    const pdj = w.publication_date_json ? JSON.parse(w.publication_date_json) : null
    if (pdj && typeof pdj === 'object') {
      const parts = []
      if (pdj.year) parts.push(pdj.year)
      if (pdj.month) parts.push(String(pdj.month).padStart(2, '0'))
      if (pdj.day) parts.push(String(pdj.day).padStart(2, '0'))
      if (parts.length > 1) return parts.join('-')
      if (pdj.raw) return pdj.raw
    }
  } catch {}
  return w.year || ''
}

// issue #18：目录查询绑定请求代次——快速切换筛选/翻页时，旧请求的迟到
// 成功不得覆盖新结果，旧失败不得清空已成功的新列表。
let querySequence = 0
async function loadData() {
  const sequence = ++querySequence
  const params = {
    ...paginationParams.value,
    search: search.value,
    status: statusFilter.value,
    doc_type: typeFilter.value,
    language: langFilter.value,
    sort: sortKey.value,
    order: sortDir.value,
  }
  if (primaryDocTypeFilter.value) params.primary_doc_type = primaryDocTypeFilter.value
  if (publicationStatusFilter.value) params.publication_status = publicationStatusFilter.value
  if (ingestionStateFilter.value) params.ingestion_state = ingestionStateFilter.value
  if (priorityFilter.value) params.priority = priorityFilter.value
  if (classifiedOnly.value) params.classified_only = true

  const searchParams = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') {
      searchParams.append(key, value)
    }
  }
  for (const [key, values] of [
    ['risk', riskFilter.value],
  ]) {
    if (values && values.length > 0) {
      for (const v of values) {
        searchParams.append(key, v)
      }
    }
  }
  searchParams.append('risk_scope', riskScope.value)
  const q = searchParams.toString()
  try {
    const res = await getWorks(q ? '?' + q : '')
    if (sequence !== querySequence) return
    riskFilterNote.value = res.risk_filter_note || ''
    loadError.value = ''
    works.value = res.works
    total.value = res.total
    totalMatching.value = res.total_matching
  } catch (e) {
    if (sequence !== querySequence) return
    // R1 B2：风险筛选 fail-closed（503）等错误必须可见，且不得让旧列表
    // 冒充当前筛选结果。
    works.value = []
    totalMatching.value = 0
    riskFilterNote.value = ''
    let text = e?.message || String(e)
    try {
      const d = typeof e?.detail === 'string' ? JSON.parse(e.detail) : e?.detail
      if (d?.detail?.message) text = d.detail.message
      else if (d?.detail && typeof d.detail === 'string') text = d.detail
    } catch { /* detail 非结构化时保持默认文案 */ }
    loadError.value = text
    message.error(text)
  }
}

function quarantine(w) {
  quarantineTarget.value = w
  quarantineReason.value = ''
  quarantineLoading.value = false
  showQuarantineModal.value = true
}

async function confirmQuarantine() {
  if (!quarantineTarget.value || quarantineLoading.value) return
  quarantineLoading.value = true
  try {
    await quarantineWork(quarantineTarget.value.id, quarantineReason.value)
    showQuarantineModal.value = false
    await loadData()
    message.success('已隔离')
  } catch (e) {
    message.error('隔离失败: ' + (e.message || e))
  } finally {
    quarantineLoading.value = false
  }
}

function restore(w) {
  dialog.warning({
    title: '恢复文献',
    content: '确认恢复「' + (w.title || w.id) + '」？',
    positiveText: '恢复',
    negativeText: '取消',
    onPositiveClick: async () => {
      const result = await restoreWork(w.id)
      await loadData()
      message.success('已恢复')
      if (result.read_status_basis === 'legacy_default_unread') message.warning('历史隔离未保存原阅读状态，本次按未读恢复')
    },
  })
}

const vocabError = ref('')
async function loadRiskVocab() {
  vocabError.value = ''
  try {
    const vocab = await getResearchRiskVocab()
    if (vocab.available) {
      const counts = vocab[riskScope.value] || {}
      riskOptions.value = Object.keys(counts).map(v => ({
        label: `${v}（${counts[v]}）`, value: v,
      }))
    } else {
      riskOptions.value = []
      vocabError.value = vocab.error
        ? `研究库词表不可用：${vocab.error}`
        : '研究库暂无解释记录，可手动输入风险现象'
    }
  } catch (e) {
    riskOptions.value = []
    vocabError.value = '研究库词表加载失败：' + (e?.message || e)
  }
}

const listState = { search, statusFilter, typeFilter, langFilter, sortKey, sortDir,
  primaryDocTypeFilter, publicationStatusFilter, ingestionStateFilter, priorityFilter,
  classifiedOnly, riskFilter, riskScope, showAdvanced, page }
onBeforeRouteLeave(to => {
  if (to.path !== '/metadata-workspace') return
  const saved = Object.fromEntries(Object.entries(listState).map(([key, value]) => [key, value.value]))
  window.history.replaceState({ ...window.history.state, worksListState: { values: JSON.parse(JSON.stringify(saved)), scrollY: window.scrollY } }, '')
})
onMounted(async () => {
  const saved = window.history.state?.worksListState
  if (saved?.values) {
    for (const [key, value] of Object.entries(listState)) {
      if (Object.hasOwn(saved.values, key)) value.value = saved.values[key]
    }
  }
  loadRiskVocab()
  await loadData()
  if (saved) {
    await nextTick()
    window.scrollTo({ top: saved.scrollY || 0, behavior: 'instant' })
  }
})
</script>

<style scoped>
.works-page { width: min(1380px, 100%); margin: 0 auto; }
.page-intro { display: flex; align-items: flex-end; justify-content: space-between; margin-bottom: 24px; }
.page-kicker { display: block; margin-bottom: 6px; color: var(--accent); font-size: 9px; font-weight: 680; letter-spacing: .11em; }
.page-intro h1 { margin: 0; font-size: 28px; font-weight: 610; letter-spacing: -.035em; }
.page-intro p { margin-top: 6px; color: var(--text-secondary); font-size: 12px; }
.library-count { display: flex; min-width: 86px; flex-direction: column; align-items: flex-end; padding-left: 20px; border-left: 1px solid var(--border); }
.library-count strong { font-size: 24px; font-weight: 620; letter-spacing: -.04em; }
.library-count span { color: var(--text-tertiary); font-size: 9px; letter-spacing: .05em; }

.page-title {
  font-size: var(--text-2xl);
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: var(--space-4);
}

.toolbar {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
  align-items: center;
  margin-bottom: var(--space-3);
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: rgba(255,255,255,.82);
  box-shadow: var(--shadow-sm);
}

.risk-banner {
  margin: 12px 2px 0;
  padding: 8px 12px;
  border: 1px solid var(--warn, #d9a500);
  border-radius: var(--radius-lg, 8px);
  background: rgba(217, 165, 0, 0.08);
  color: var(--text-primary);
  font-size: var(--text-sm);
}
.risk-banner.muted-banner {
  border-color: var(--border);
  background: rgba(127, 127, 127, 0.06);
}

.count {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  margin: 15px 2px 8px;
}

.advanced-filters {
  background: rgba(255,255,255,.72);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 18px;
  margin-bottom: var(--space-3);
}

.classified-bar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--border);
  margin-bottom: var(--space-3);
}

.classified-label {
  font-size: var(--text-base);
  color: var(--text-primary);
}

.filter-hint {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.filter-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: var(--space-3) var(--space-4);
}

.filter-item {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.filter-item.wide {
  grid-column: span 2;
}

@media (max-width: 900px) {
  .filter-item.wide {
    grid-column: span 1;
  }
}

.filter-item label {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  font-weight: 500;
}

.status-verified { color: var(--ok); }
.status-needs_review { color: var(--warn); }
.status-provisional { color: var(--neutral); }
.status-excluded { color: var(--bad); }
.status-deprecated { color: var(--text-tertiary); }

.table-wrap {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}

table {
  width: 100%;
  border-collapse: collapse;
}

th, td {
  border-bottom: 1px solid var(--border);
  padding: 13px 14px;
  text-align: left;
  vertical-align: top;
}

th {
  background: #f5f5f2;
  font-size: 10px;
  font-weight: 620;
  letter-spacing: .035em;
  color: var(--text-secondary);
  position: sticky;
  top: 0;
}

tr {
  cursor: pointer;
}

tr:hover td {
  background: #f2f8f5;
}

.title {
  font-weight: 570;
  max-width: 500px;
  color: var(--text-primary);
}

.muted { color: var(--text-secondary); }
.tiny { font-size: var(--text-sm); }

.status-unread { color: var(--text-secondary); }
.status-quarantined { color: var(--bad); font-weight: 600; }
.status-succeeded { color: var(--ok); }
.status-failed { color: var(--bad); }

.actions { white-space: nowrap; }
.metadata-action { display: inline-block; margin-right: 16px; }

.export-group { margin-top: 14px; }
.export-group > label { display: block; margin-bottom: 6px; color: var(--text-secondary); font-size: var(--text-sm); }

.modal-desc {
  margin: 0 0 var(--space-4);
  font-size: var(--text-base);
  color: var(--text-secondary);
}

tbody tr:last-child td { border-bottom: 0; }

@media (max-width: 700px) {
  .page-intro { align-items: flex-start; }
  .library-count { display: none; }
  .toolbar :deep(.n-input) { width: 100% !important; }
  .table-wrap { overflow-x: auto; }
  table { min-width: 850px; }
}
</style>
