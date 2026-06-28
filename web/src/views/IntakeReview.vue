<template>
  <AppLayout>
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
              <span class="badge review" :class="c.review_status">{{ reviewLabel(c.review_status) }}</span>
              <span class="muted tiny">{{ c.source_type }} · {{ c.arxiv_id || c.url_canonical }}</span>
            </div>
          </div>
          <div v-if="!candidates.length" class="empty muted">无候选。先用 CLI：python scripts/literature_intake.py collect --ids &lt;arxiv_id&gt;</div>
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
            <span class="badge review" :class="selected.review_status">{{ reviewLabel(selected.review_status) }}</span>
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
        </table>

        <details v-if="selected.raw_meta" class="raw">
          <summary>来源原始元数据</summary>
          <pre>{{ JSON.stringify(selected.raw_meta, null, 2) }}</pre>
        </details>

        <div class="review-bar">
          <button class="btn-approve" :disabled="busy" @click="doReview('approved')">批准</button>
          <button class="btn-reject" :disabled="busy" @click="doReview('rejected')">拒绝</button>
          <button class="btn-promote" :disabled="busy || promotableCount === 0" @click="doPromote">
            晋升已批准 ({{ promotableCount }})
          </button>
        </div>
        <div class="muted tiny" v-if="selected.ingested_work_id">
          已晋升为
          <router-link :to="`/works/${selected.ingested_work_id}`">{{ selected.ingested_work_id }}</router-link>
        </div>
      </div>
      <div class="detail-panel empty-state" v-else>
        <div class="muted">从左侧选择一个候选查看详情</div>
      </div>
    </div>
  </AppLayout>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import AppLayout from '../components/AppLayout.vue'
import { getIntakeCandidates, getIntakeStats, reviewCandidate, promoteCandidates } from '../api'

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

const resLabel = k => RES_LABEL[k] || k
const resClass = k => `res-${k}`
const reviewLabel = k => REVIEW_LABEL[k] || k

// approved 且尚未 ingested 的候选数（批量晋升按钮的可用/计数依据）
const promotableCount = computed(() =>
  candidates.value.filter(c => c.review_status === 'approved' && !c.ingested_work_id).length
)

function resetAndReload() {
  page.value = 1
  return reload()
}

async function reload() {
  const body = await getIntakeCandidates({
    review_status: reviewFilter.value,
    resolution: resolutionFilter.value || undefined,
    search: search.value || undefined,
    page: page.value,
    per_page: perPage,
  })
  candidates.value = body.candidates
  total.value = body.total
  if (selected.value) {
    selected.value = candidates.value.find(c => c.id === selected.value.id) || null
  }
  await loadStats()
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
    alert(e.message)
  } finally {
    busy.value = false
  }
}

async function doPromote() {
  // 取所有 review_status=approved 且尚未 ingested 的候选
  const targets = candidates.value
    .filter(c => c.review_status === 'approved' && !c.ingested_work_id)
    .map(c => c.id)
  if (!targets.length) { alert('没有可晋升的已批准候选'); return }
  if (!confirm(`晋升 ${targets.length} 个候选为 work？`)) return
  busy.value = true
  try {
    const res = await promoteCandidates(targets)
    const failed = res.failed?.length || 0
    alert(`晋升 ${res.promoted?.length || 0} 个${failed ? `，失败 ${failed} 个` : ''}`)
    await reload()
  } catch (e) {
    alert(e.message)
  } finally {
    busy.value = false
  }
}

onMounted(reload)
</script>

<style scoped>
.intake-layout { display: grid; grid-template-columns: 380px 1fr; gap: 16px; }
.list-panel, .detail-panel { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px; }
.page-title { font-size: 18px; margin-bottom: 12px; }
.filter-bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
.filter-bar select, .search-input { padding: 4px 6px; border: 1px solid var(--line); border-radius: 4px; }
.ext-list { display: flex; flex-direction: column; gap: 6px; }
.ext-item { padding: 10px; border: 1px solid var(--line); border-radius: 6px; cursor: pointer; }
.ext-item:hover { background: var(--bg); }
.ext-item.selected { border-color: var(--accent); background: #eef5ff; }
.ext-item.better { border-left: 3px solid var(--warn); }
.ext-title { font-weight: 600; }
.ext-meta { display: flex; gap: 6px; align-items: center; margin-top: 4px; flex-wrap: wrap; }
.badge { font-size: 12px; padding: 1px 6px; border-radius: 10px; background: var(--chip); }
.badge.res-new { background: #e6f4ea; color: var(--ok); }
.badge.res-exact_hit, .badge.res-sha256_duplicate { background: var(--chip); color: var(--muted); }
.badge.res-title_candidate { background: #fff8e1; color: var(--warn); }
.badge.res-needs_better_copy { background: #fdecea; color: var(--bad); }
.badge.res-fetch_failed { background: var(--chip); color: var(--bad); }
.badge.review.pending { background: var(--chip); }
.badge.review.approved { background: #e6f4ea; color: var(--ok); }
.badge.review.rejected { background: #fdecea; color: var(--bad); }
.muted { color: var(--muted); } .tiny { font-size: 12px; }
.empty { padding: 20px; text-align: center; }
.pager { display: flex; gap: 8px; align-items: center; justify-content: center; margin-top: 12px; }
.detail-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; }
.header-badges { display: flex; gap: 6px; }
.better-banner { background: #fff8e1; border: 1px solid var(--warn); border-radius: 6px; padding: 8px 10px; margin-bottom: 12px; color: var(--warn); }
table.kv { width: 100%; border-collapse: collapse; margin-bottom: 12px; }
table.kv th { text-align: left; width: 110px; color: var(--muted); padding: 4px 8px; vertical-align: top; }
table.kv td { padding: 4px 8px; }
.raw pre { background: var(--bg); padding: 8px; border-radius: 4px; font-size: 12px; overflow-x: auto; }
.review-bar { display: flex; gap: 8px; margin-top: 16px; }
.review-bar button { padding: 6px 14px; border-radius: 6px; border: 1px solid var(--line); cursor: pointer; background: var(--panel); }
.btn-approve { background: #e6f4ea; color: var(--ok); border-color: var(--ok); }
.btn-reject { background: #fdecea; color: var(--bad); border-color: var(--bad); }
.btn-promote { background: var(--accent); color: #fff; border-color: var(--accent); }
.review-bar button:disabled { opacity: .5; cursor: not-allowed; }
.empty-state { display: flex; align-items: center; justify-content: center; color: var(--muted); }
</style>
