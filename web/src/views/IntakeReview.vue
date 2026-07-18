<template>
    <div class="intake-layout">
      <div class="list-panel">
        <h2 class="page-title">采集审核 <span class="muted tiny">collector A2</span></h2>

        <div class="filter-bar">
          <label>审核态：
            <select v-model="reviewFilter" @change="resetAndReload">
              <option value="pending">待审 ({{ stats.review?.pending || 0 }})</option>
              <option value="approved">已批准 ({{ stats.review?.approved || 0 }})</option>
              <option value="rejected">已拒绝 ({{ stats.review?.rejected || 0 }})</option>
              <option value="">全部</option>
            </select>
          </label>
          <label>判别：
            <select v-model="resolutionFilter" @change="resetAndReload">
              <option value="">全部</option>
              <option v-for="r in RESOLUTIONS" :key="r.key" :value="r.key">
                {{ r.label }} ({{ stats.resolution?.[r.key] || 0 }})
              </option>
            </select>
          </label>
          <input v-model="search" placeholder="搜标题/arXiv/ID" @keyup.enter="resetAndReload" class="search-input" />
          <button @click="reload">刷新</button>
        </div>

        <div class="ext-list">
          <div v-for="c in candidates" :key="c.id" class="ext-item"
               :class="{ selected: selected?.id === c.id, better: c.resolution === 'needs_better_copy' }"
               @click="selected = c">
            <div class="ext-title">{{ c.title || c.arxiv_id || c.id }}</div>
            <div class="ext-meta">
              <span class="badge" :class="resClass(c.resolution)">{{ resLabel(c.resolution) }}</span>
              <StatusBadge :status="c.review_status" size="small" :label="reviewLabel(c.review_status)" />
              <span class="muted tiny">{{ c.source_type }} · {{ c.arxiv_id || c.url_canonical }}</span>
            </div>
          </div>
          <EmptyState v-if="!candidates.length" icon="inbox" title="无候选" description="先用 CLI：python scripts/literature_intake.py collect --ids <arxiv_id>" />
        </div>

        <div class="pager" v-if="total > perPage">
          <button :disabled="page <= 1" @click="page--; reload()">上一页</button>
          <span class="muted tiny">{{ page }} / {{ Math.ceil(total / perPage) }}</span>
          <button :disabled="page * perPage >= total" @click="page++; reload()">下一页</button>
        </div>
      </div>

      <div class="detail-panel" v-if="selected">
        <div class="detail-header">
          <div>
            <div class="ext-title">{{ selected.title || selected.id }}</div>
            <div class="muted tiny">{{ selected.id }} · {{ selected.source_type }} · {{ selected.collected_at?.slice(0,19) }}</div>
          </div>
          <div class="header-badges">
            <span class="badge" :class="resClass(selected.resolution)">{{ resLabel(selected.resolution) }}</span>
            <StatusBadge :status="selected.review_status" size="small" :label="reviewLabel(selected.review_status)" />
          </div>
        </div>

        <!-- ====== 来源追溯卡片 ====== -->
        <div class="provenance-card" v-if="provenance">
          <div class="provenance-label">📎 来源追溯</div>

          <!-- 发现检索 -->
          <div v-if="provenance.type === 'discovery'" class="provenance-body">
            <div class="prov-channel">
              <span class="prov-icon">🔍</span>
              <span>来自<strong>发现检索</strong></span>
            </div>
            <table class="prov-kv" v-if="provenance.run || provenance.query || provenance.topicName">
              <tr v-if="provenance.run">
                <th>检索运行</th>
                <td>
                  <router-link :to="`/discovery?run_id=${provenance.discoveryRunId}`" class="prov-link">
                    {{ provenance.run.name || provenance.discoveryRunId }}
                  </router-link>
                  <span class="muted tiny">{{ provenance.run.created_at?.slice(0,16) }}</span>
                </td>
              </tr>
              <tr v-if="provenance.query">
                <th>检索词</th>
                <td><code class="prov-query">{{ provenance.query }}</code></td>
              </tr>
              <tr v-if="provenance.topicName">
                <th>关联主题</th>
                <td>{{ provenance.topicName }}</td>
              </tr>
              <tr v-if="provenance.snippet">
                <th>命中摘要</th>
                <td class="prov-snippet">{{ provenance.snippet }}</td>
              </tr>
            </table>
            <div class="muted tiny prov-loading" v-else-if="provenance.loading">正在加载运行记录…</div>
          </div>

          <!-- 直接采集 -->
          <div v-else-if="provenance.type === 'collect'" class="provenance-body">
            <div class="prov-channel">
              <span class="prov-icon">📥</span>
              <span>来自<strong>直接采集</strong></span>
              <span class="badge prov-source-badge">{{ selected.source_type }}</span>
            </div>
            <table class="prov-kv">
              <tr v-if="provenance.arxivId">
                <th>arXiv ID</th>
                <td><a :href="`https://arxiv.org/abs/${provenance.arxivId}`" target="_blank" rel="noopener noreferrer">{{ provenance.arxivId }}</a></td>
              </tr>
              <tr v-if="provenance.repoUrl">
                <th>仓库地址</th>
                <td><a :href="provenance.repoUrl" target="_blank" rel="noopener noreferrer">{{ provenance.repoUrl }}</a></td>
              </tr>
              <tr v-if="provenance.topicName">
                <th>关联主题</th>
                <td>{{ provenance.topicName }}</td>
              </tr>
            </table>
          </div>

          <!-- 手动 / 其他 -->
          <div v-else class="provenance-body">
            <div class="prov-channel">
              <span class="prov-icon">❓</span>
              <span>来源未知（无完整追溯信息）</span>
            </div>
          </div>
        </div>

        <div class="better-banner" v-if="selected.resolution === 'needs_better_copy'">
          ⚠ needs_better_copy：命中隔离中的 work
          <span v-if="selected.matched_work_id">（{{ selected.matched_work_id }}）</span>——晋升会用好副本替换。
        </div>

        <table class="kv">
          <tr><th>arXiv</th><td>{{ selected.arxiv_id || '—' }}</td></tr>
          <tr><th>DOI</th><td>{{ selected.doi || '—' }}</td></tr>
          <tr><th>来源 URL</th><td><a :href="selected.url_canonical" target="_blank" rel="noopener noreferrer">{{ selected.url_canonical }}</a></td></tr>
          <tr><th>命中 work</th><td>
            <router-link v-if="selected.matched_work_id" :to="`/works/${selected.matched_work_id}`">{{ selected.matched_work_id }}</router-link>
            <span v-else>—</span>
          </td></tr>
          <tr><th>主题</th><td>{{ selected.topic_name || '—' }}</td></tr>
          <tr><th>状态</th><td>{{ selected.status }} / {{ selected.resolution }}</td></tr>
          <tr><th>PDF</th><td>
            <span v-if="selected.local_pdf_path && selectedIsDuplicate" class="pdf-duplicate">⚠ 已缓存（重复，不可晋升）</span>
            <span v-else-if="selected.local_pdf_path" class="pdf-ok">✅ 已下载</span>
            <span v-else class="pdf-missing">❌ 未下载</span>
          </td></tr>
        </table>

        <!-- PDF 操作栏：未下载时提供下载 / 上传入口 -->
        <div class="pdf-action-bar" v-if="!selected.local_pdf_path">
          <div class="pdf-action-buttons">
            <button class="btn-download-pdf" :disabled="busy || pdfDownloading" @click="doDownloadPdf" title="自动从 arXiv 等来源下载 PDF">
              <span v-if="pdfDownloading">⏳ 下载中…</span>
              <span v-else>📥 自动下载 PDF</span>
            </button>
            <label class="btn-upload-pdf" :class="{ disabled: busy || pdfUploading }" title="手动上传 PDF 文件（agent 转换后的 PDF 或本地文件）">
              <span v-if="pdfUploading">⏳ 上传中…</span>
              <span v-else>📤 上传 PDF</span>
              <input type="file" accept=".pdf" :disabled="busy || pdfUploading" @change="onPdfFileSelected" style="display:none" />
            </label>
          </div>
          <!-- 内联状态反馈（不依赖顶部通知） -->
          <div class="pdf-inline-feedback" v-if="pdfFeedback.msg" :class="pdfFeedback.type">
            {{ pdfFeedback.msg }}
          </div>
        </div>

        <!-- 已下载时也显示一行提示 -->
        <div class="pdf-action-bar pdf-done-bar" :class="{ duplicate: selectedIsDuplicate }" v-else>
          <span v-if="selectedIsDuplicate" class="pdf-duplicate">⚠ PDF 已缓存，但为重复项</span>
          <span v-else class="pdf-ok">✅ PDF 已就绪</span>
          <span class="muted tiny">{{ selected.local_pdf_path }}</span>
        </div>

        <details v-if="selected.raw_meta" class="raw">
          <summary>来源原始元数据</summary>
          <pre>{{ JSON.stringify(selected.raw_meta, null, 2) }}</pre>
        </details>

        <div class="review-bar">
          <button class="btn-approve" :disabled="busy || selectedIsDuplicate" @click="onApprove" title="批准后可晋升为正式文献">批准</button>
          <button class="btn-reject" :disabled="busy" @click="doReview('rejected')">拒绝</button>
          <button class="btn-promote" :disabled="busy || promotableCount === 0" @click="showPromoteConfirm">
            晋升已批准 ({{ promotableCount }})
          </button>
        </div>
        <div class="muted tiny" v-if="selected.ingested_work_id">
          已晋升为
          <router-link :to="`/works/${selected.ingested_work_id}`">{{ selected.ingested_work_id }}</router-link>
        </div>
      </div>
      <EmptyState v-else icon="search" title="选择一个候选查看详情" />
    </div>

    <!-- 确认对话框 -->
    <ConfirmDialog
      v-model:show="showConfirmDialog"
      :title="confirmTitle"
      :message="confirmMessage"
      type="warn"
      @confirm="confirmAction?.()"
    />
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { getIntakeCandidates, getIntakeStats, reviewCandidate, promoteCandidates, resolveIntake, uploadCandidatePdf, getDiscoveryRun, getIntakeTopics } from '../api'
import { showError } from '../error-handler'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import StatusBadge from '../components/StatusBadge.vue'
import EmptyState from '../components/EmptyState.vue'

const RESOLUTIONS = [
  { key: 'new', label: '新文献' },
  { key: 'exact_hit', label: '精确命中' },
  { key: 'title_candidate', label: '标题疑似' },
  { key: 'needs_better_copy', label: '需好副本' },
  { key: 'sha256_duplicate', label: 'SHA256重复' },
  { key: 'fetch_failed', label: '下载失败' },
  { key: 'pending', label: '待判别' },
]
const RES_LABEL = Object.fromEntries(RESOLUTIONS.map(r => [r.key, r.label]))
const REVIEW_LABEL = { pending: '待审', approved: '已批准', rejected: '已拒绝' }
const DUPLICATE_RESOLUTIONS = new Set(['exact_hit', 'title_candidate', 'needs_better_copy', 'sha256_duplicate'])

const candidates = ref([])
const stats = ref({})
const total = ref(0)
const page = ref(1)
const perPage = 20
const reviewFilter = ref('pending')
const resolutionFilter = ref('')
const search = ref('')
const selected = ref(null)
const busy = ref(false)

// PDF 操作状态（内联反馈）
const pdfDownloading = ref(false)
const pdfUploading = ref(false)
const pdfFeedback = ref({ msg: '', type: '' })  // type: 'ok' | 'warn' | 'err' | ''

// ConfirmDialog state
const showConfirmDialog = ref(false)
const confirmTitle = ref('')
const confirmMessage = ref('')
const confirmAction = ref(null)

const resLabel = k => RES_LABEL[k] || k
const resClass = k => `res-${k}`
const reviewLabel = k => REVIEW_LABEL[k] || k

// approved 且尚未 ingested 的候选数（批量晋升按钮的可用/计数依据）
const promotableCount = computed(() =>
  candidates.value.filter(c => c.review_status === 'approved' && c.resolution === 'new' && !c.ingested_work_id).length
)
const selectedIsDuplicate = computed(() =>
  selected.value ? DUPLICATE_RESOLUTIONS.has(selected.value.resolution) : false
)

// ====== 来源追溯 (Provenance) ======
const discoveryRunCache = ref({})   // { runId: { name, created_at, input_json } }
const topicCache = ref([])          // [{ id, name }, ...]

/** 从 raw_meta + 顶层字段解析来源追溯信息 */
const provenance = computed(() => {
  const c = selected.value
  if (!c) return null

  const meta = typeof c.raw_meta === 'string' ? (() => { try { return JSON.parse(c.raw_meta) } catch { return {} } })() : (c.raw_meta || {})

  // --- 发现检索 ---
  if (meta.discovery_run_id) {
    const runId = meta.discovery_run_id
    return {
      type: 'discovery',
      discoveryRunId: runId,
      query: meta.query || '',
      snippet: meta.snippet ? (meta.snippet.length > 200 ? meta.snippet.slice(0, 200) + '…' : meta.snippet) : '',
      topicId: meta.topic_id || c.collection_topic_id || '',
      run: discoveryRunCache.value[runId] || null,
      loading: !discoveryRunCache.value[runId] && !discoveryRunCache.value[`_loading_${runId}`],
    }
  }

  // --- 直接采集（arxiv / github / web）---
  if (!meta.discovery_run_id) {
    return {
      type: 'collect',
      arxivId: c.arxiv_id || (meta.arxiv_id || ''),
      repoUrl: meta.repo_url || '',
      topicId: c.collection_topic_id || meta.topic_id || '',
      topicName: resolveTopicName(c.collection_topic_id || meta.topic_id || ''),
    }
  }

  return { type: 'unknown' }
})

function resolveTopicName(topicId) {
  if (!topicId) return ''
  const t = topicCache.value.find(x => x.id === topicId)
  return t?.name || topicId
}

// 当选中项变化且有 discovery_run_id 时，自动加载运行详情
watch(selected, async (c) => {
  if (!c) return
  const meta = typeof c.raw_meta === 'string' ? (() => { try { return JSON.parse(c.raw_meta) } catch { return {} } })() : (c.raw_meta || {})
  if (meta.discovery_run_id && !discoveryRunCache.value[meta.discovery_run_id]) {
    const runId = meta.discovery_run_id
    discoveryRunCache.value[`_loading_${runId}`] = true  // 防止重复加载标记
    try {
      const runData = await getDiscoveryRun(runId)
      discoveryRunCache.value[runId] = runData
    } catch (e) {
      console.warn('[IntakeReview] 无法加载发现检索运行记录:', runId, e)
    } finally {
      delete discoveryRunCache.value[`_loading_${runId}`]
    }
  }
}, { immediate: true })

// 加载主题列表（用于解析主题名）
async function loadTopics() {
  try {
    const res = await getIntakeTopics({ per_page: 200 })
    topicCache.value = res.topics || res || []
  } catch (e) {
    console.warn('[IntakeReview] 加载主题列表失败:', e)
  }
}

function resetAndReload() {
  page.value = 1
  return reload()
}

async function reload() {
  try {
    const params = {
      review_status: reviewFilter.value,
      page: page.value,
      per_page: perPage,
    }
    if (resolutionFilter.value) params.resolution = resolutionFilter.value
    if (search.value && search.value.trim()) params.search = search.value.trim()
    const qs = new URLSearchParams(params).toString()
    console.log('[IntakeReview] requesting:', `/api/intake/candidates?${qs}`)
    const body = await getIntakeCandidates(params)
    console.log('[IntakeReview] API response raw:', JSON.stringify(body).slice(0, 300))
    console.log('[IntakeReview] API response:', { total: body?.total, count: body?.candidates?.length })
    candidates.value = body.candidates ?? []
    total.value = body.total ?? 0
    if (selected.value) {
      selected.value = candidates.value.find(c => c.id === selected.value.id) || null
    }
    await loadStats()
  } catch (e) {
    console.error('[IntakeReview] reload failed:', e)
    showError(e)
  }
}

async function loadStats() {
  stats.value = await getIntakeStats()
}

async function doReview(status) {
  if (!selected.value || busy.value) return
  busy.value = true
  try {
    await reviewCandidate(selected.value.id, status)
    await reload()
  } catch (e) {
    showError(e)
  } finally {
    busy.value = false
  }
}

function showPromoteConfirm() {
  const targets = candidates.value
    .filter(c => c.review_status === 'approved' && c.resolution === 'new' && !c.ingested_work_id)
    .map(c => c.id)
  if (!targets.length) { showError(new Error('没有可晋升的已批准候选')); return }
  confirmTitle.value = '批量晋升'
  confirmMessage.value = `晋升 ${targets.length} 个候选为 work？`
  confirmAction.value = () => doPromote(targets)
  showConfirmDialog.value = true
}

async function doPromote(targets) {
  showConfirmDialog.value = false
  busy.value = true
  try {
    const res = await promoteCandidates(targets)
    const failed = res.failed?.length || 0
    window.__naive_message?.success(`晋升 ${res.promoted?.length || 0} 个${failed ? `，失败 ${failed} 个` : ''}`)
    await reload()
  } catch (e) {
    showError(e)
  } finally {
    busy.value = false
  }
}

/** 自动下载 PDF：触发 heavy_gate（从 arXiv 等来源下载） */
async function doDownloadPdf() {
  if (!selected.value || busy.value || pdfDownloading.value) return
  pdfDownloading.value = true
  pdfFeedback.value = { msg: '', type: '' }
  try {
    const res = await resolveIntake({ ids: [selected.value.id] })
    const result = res.results?.[0]
    if (result) {
      if (result.resolution === 'sha256_duplicate') {
        pdfFeedback.value = { msg: '⚠️ PDF 已下载，但与库内已有文献重复（SHA256）', type: 'warn' }
        window.__naive_message?.warning('PDF 已下载，但 SHA256 与库内已有文献重复（已标记为重复）')
      } else if (result.resolution === 'fetch_failed') {
        pdfFeedback.value = { msg: '❌ 下载失败：无法获取 PDF URL，可尝试手动上传', type: 'err' }
        window.__naive_message?.error('自动下载失败：无法获取 PDF URL。可尝试手动上传。')
      } else {
        pdfFeedback.value = { msg: '✅ PDF 下载成功', type: 'ok' }
        window.__naive_message?.success('PDF 下载成功 ✅')
      }
    } else {
      pdfFeedback.value = { msg: '⏳ 处理完成，请查看结果', type: '' }
      window.__naive_message?.info('处理完成，请查看结果')
    }
    await reload() // 刷新以更新 local_pdf_path
  } catch (e) {
    pdfFeedback.value = { msg: '❌ 下载出错：' + (e.message || '网络异常'), type: 'err' }
    showError(e)
  } finally {
    pdfDownloading.value = false
  }
}

/** 手动上传 PDF（agent 转换后的 PDF 或本地文件） */
async function onPdfFileSelected(event) {
  const file = event.target.files?.[0]
  if (!file || !selected.value || pdfUploading.value) return
  // 重置 input 以便重复选择同一文件
  event.target.value = ''
  pdfUploading.value = true
  pdfFeedback.value = { msg: '', type: '' }
  try {
    const res = await uploadCandidatePdf(selected.value.id, file)
    const isDup = res.resolution === 'sha256_duplicate'
    pdfFeedback.value = { msg: isDup ? '⚠️ 上传成功（SHA256重复）' : '✅ PDF 上传成功', type: isDup ? 'warn' : 'ok' }
    window.__naive_message?.success(`PDF 上传成功 (${isDup ? '⚠️ SHA256重复' : '✅ 新文献'})`)
    await reload()
  } catch (e) {
    pdfFeedback.value = { msg: '❌ 上传失败：' + (e.message || '网络异常'), type: 'err' }
    showError(e)
  } finally {
    pdfUploading.value = false
  }
}

/** 批准前检查：无 PDF 时引导先下载 */
function onApprove() {
  if (!selected.value || busy.value) return
  if (selectedIsDuplicate.value) {
    window.__naive_message?.warning('该候选已命中重复，不应批准晋升。')
    return
  }
  // 有 PDF → 直接批准
  if (selected.value.local_pdf_path) {
    return doReview('approved')
  }
  // 无 PDF → 引导下载（不提供跳过选项）
  confirmTitle.value = '⚠️ 请先下载 PDF'
  confirmMessage.value =
    '该文献尚未下载 PDF 文件。\n' +
    '晋升为正式文献时必须有 PDF，否则会报错。\n\n' +
    '请点击「📥 下载 PDF」完成后再批准。\n' +
    '如果自动下载失败，可手动上传 PDF。'
  // 只提供"我知道了"按钮，关闭后用户回到操作区点下载
  confirmAction.value = null  // 不执行任何操作，纯提示
  showConfirmDialog.value = true
}

const route = useRoute()

onMounted(async () => {
  await reload()
  loadTopics()
  // 支持 /intake?selected=IC-xxx 深链（如 Pipeline 迷你列表跳转）
  const sel = route.query.selected
  if (sel) {
    let hit = candidates.value.find(c => c.id === sel)
    if (!hit && reviewFilter.value) {
      // 目标可能不在当前筛选内，清空筛选后再找
      reviewFilter.value = ''
      page.value = 1
      await reload()
      hit = candidates.value.find(c => c.id === sel)
    }
    if (hit) selected.value = hit
  }
})
</script>

<style scoped>
.intake-layout {
  display: grid;
  grid-template-columns: 380px 1fr;
  gap: 16px;
  height: calc(100vh - 60px);
}
.list-panel {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  padding: var(--space-4);
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
.detail-panel {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  padding: var(--space-4);
  overflow-y: auto;
}
.page-title { font-size: 18px; margin-bottom: 12px; }
.filter-bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
.filter-bar select, .search-input { padding: 4px 6px; border: 1px solid var(--border); border-radius: var(--radius-md); }
.ext-list { display: flex; flex-direction: column; gap: 6px; }
.ext-item { padding: 10px; border: 1px solid var(--border); border-radius: var(--radius-lg); cursor: pointer; }
.ext-item:hover { background: var(--bg-muted); }
.ext-item.selected { border-color: var(--accent); background: var(--selected-bg); }
.ext-item.better { border-left: 3px solid var(--warn); }
.ext-title { font-weight: 600; }
.ext-meta { display: flex; gap: 6px; align-items: center; margin-top: 4px; flex-wrap: wrap; }
.badge { font-size: 12px; padding: 1px 6px; border-radius: 10px; background: var(--bg-muted); }
.badge.res-new { background: var(--ok-bg); color: var(--ok); }
.badge.res-exact_hit, .badge.res-sha256_duplicate { background: var(--bg-muted); color: var(--text-secondary); }
.badge.res-title_candidate { background: var(--warn-bg); color: var(--warn); }
.badge.res-needs_better_copy { background: var(--bad-bg); color: var(--bad); }
.badge.res-fetch_failed { background: var(--bg-muted); color: var(--bad); }
.badge.review.pending { background: var(--bg-muted); }
.badge.review.approved { background: var(--ok-bg); color: var(--ok); }
.badge.review.rejected { background: var(--bad-bg); color: var(--bad); }
.muted { color: var(--text-secondary); } .tiny { font-size: 12px; }
.empty { padding: 20px; text-align: center; }
.pager { display: flex; gap: 8px; align-items: center; justify-content: center; margin-top: 12px; }
.detail-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; }
.header-badges { display: flex; gap: 6px; }
.better-banner { background: var(--warn-bg); border: 1px solid var(--warn); border-radius: var(--radius-lg); padding: 8px 10px; margin-bottom: 12px; color: var(--warn); }
table.kv { width: 100%; border-collapse: collapse; margin-bottom: 12px; }
table.kv th { text-align: left; width: 110px; color: var(--text-secondary); padding: 4px 8px; vertical-align: top; }
table.kv td { padding: 4px 8px; }
.raw pre { background: var(--bg-muted); padding: 8px; border-radius: var(--radius-md); font-size: 12px; overflow-x: auto; }
.review-bar { display: flex; gap: 8px; margin-top: 16px; }
.review-bar button { padding: 6px 14px; border-radius: var(--radius-lg); border: 1px solid var(--border); cursor: pointer; background: var(--bg-surface); }
.btn-approve { background: var(--ok-bg); color: var(--ok); border-color: var(--ok); }
.btn-reject { background: var(--bad-bg); color: var(--bad); border-color: var(--bad); }
.btn-promote { background: var(--accent); color: #fff; border-color: var(--accent); }
.review-bar button:disabled { opacity: .5; cursor: not-allowed; }
.empty-state { display: flex; align-items: center; justify-content: center; color: var(--text-secondary); }

/* PDF 状态与操作 */
.pdf-ok { color: var(--ok); font-weight: 600; }
.pdf-missing { color: var(--warn); }
.pdf-duplicate { color: var(--warn); font-weight: 600; }
.pdf-action-bar {
  display: flex;
  gap: 10px;
  margin-top: 12px;
  padding: 10px;
  background: var(--bg-muted);
  border-radius: var(--radius-lg);
  border: 1px dashed var(--border);
}
.btn-download-pdf, .btn-upload-pdf {
  display: inline-flex;
  align-items: center;
  padding: 8px 16px;
  border-radius: var(--radius-lg);
  cursor: pointer;
  font-size: var(--text-sm);
  transition: all var(--transition-fast);
}
.btn-download-pdf {
  background: var(--accent-subtle);
  color: var(--accent);
  border: 1px solid var(--accent);
}
.btn-download-pdf:hover:not(:disabled) {
  background: var(--accent);
  color: #fff;
}
.btn-upload-pdf {
  background: var(--bg-surface);
  color: var(--text-primary);
  border: 1px solid var(--border);
}
.btn-uploadPdf:hover:not(.disabled) {
  background: var(--bg-muted);
  border-color: var(--accent);
}
.btn-upload-pdf.disabled {
  opacity: .5;
  cursor: not-allowed;
}
.pdf-action-buttons {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.pdf-inline-feedback {
  font-size: 12px;
  padding: 4px 10px;
  border-radius: var(--radius-md);
  margin-top: 6px;
  width: 100%;
  box-sizing: border-box;
  line-height: 1.5;
}
.pdf-inline-feedback.ok { background: var(--ok-bg); color: var(--ok); }
.pdf-inline-feedback.warn { background: var(--warn-bg); color: var(--warn); }
.pdf-inline-feedback.err { background: var(--bad-bg); color: var(--bad); }
.pdf-done-bar {
  border-style: solid;
  border-color: var(--ok);
}
.pdf-done-bar.duplicate {
  border-color: var(--warn);
  background: var(--warn-bg);
}

/* ====== 来源追溯卡片 (Provenance) ====== */
.provenance-card {
  background: var(--accent-alpha-subtle, rgba(59, 130, 246, 0.06));
  border: 1px solid var(--accent-subtle, rgba(59, 130, 246, 0.2));
  border-radius: var(--radius-lg);
  margin-bottom: 12px;
  overflow: hidden;
}
.provenance-label {
  font-size: 12px;
  font-weight: 600;
  padding: 6px 10px;
  background: var(--accent-subtle, rgba(59, 130, 246, 0.1));
  color: var(--accent, #3b82f6);
  letter-spacing: 0.5px;
}
.provenance-body { padding: 8px 10px; }
.prov-channel {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  font-size: 13px;
}
.prov-icon { font-size: 15px; }
.prov-source-badge {
  font-size: 11px;
  background: var(--bg-muted);
  text-transform: uppercase;
}
table.prov-kv {
  width: 100%;
  border-collapse: collapse;
  margin-top: 4px;
}
table.prov-kv th {
  text-align: left;
  width: 80px;
  color: var(--text-secondary);
  font-size: 12px;
  padding: 2px 8px 2px 0;
  vertical-align: top;
  white-space: nowrap;
}
table.prov-kv td {
  padding: 2px 0;
  font-size: 13px;
}
.prov-link {
  color: var(--accent);
  font-weight: 500;
}
.prov-link:hover { text-decoration: underline; }
.prov-query {
  background: var(--bg-muted);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 12px;
}
.prov-snippet {
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.5;
  max-height: 60px;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
}
.prov-loading { margin-top: 4px; }
</style>
