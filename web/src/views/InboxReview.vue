<template>
    <div class="inbox-layout">
      <div class="list-panel">
        <h2 class="page-title">收件箱摄入 <span class="muted tiny">inbox manual ingest</span></h2>

        <div class="summary-bar" v-if="plan">
          <span class="badge ok">待摄入 {{ plan.summary.ingests }}</span>
          <span class="badge dup" v-if="plan.summary.exact_duplicates">精确重复 {{ plan.summary.exact_duplicates }}</span>
          <span class="badge skip" v-if="plan.summary.skipped">跳过 {{ plan.summary.skipped }}</span>
          <span class="badge warn" v-if="plan.summary.warnings">警告 {{ plan.summary.warnings }}</span>
          <span class="badge cand" v-if="plan.summary.title_duplicate_candidates">疑似重复 {{ plan.summary.title_duplicate_candidates }}</span>
        </div>

        <div class="filter-bar">
          <label>
            <input type="checkbox" v-model="leaveInbox" />
            摄入后保留 _inbox 原文件（默认移至 _archive/ingested_inbox/）
          </label>
          <button @click="reload" :disabled="busy">重新扫描</button>
          <button class="btn-execute" @click="showExecuteConfirm"
                  :disabled="busy || !plan || plan.summary.ingests === 0">
            确认摄入{{ plan ? ` (${plan.summary.ingests})` : '' }}
          </button>
        </div>

        <div class="ext-list">
          <div v-for="(item, idx) in ingests" :key="item.content_sha256 || idx" class="ext-item"
               :class="{ selected: selectedIdx === idx }"
               @click="selectedIdx = idx">
            <div class="ext-title">{{ item.original_name }}</div>
            <div class="ext-meta">
              <span class="muted tiny">{{ item.work_id }}</span>
              <span class="muted tiny">{{ formatSize(item.file_size) }}</span>
              <span class="badge dup" v-if="item.existing_work">已有 work</span>
              <span class="badge cand" v-if="item.title_duplicate_candidates?.length">
                疑似×{{ item.title_duplicate_candidates.length }}
              </span>
            </div>
          </div>
          <EmptyState v-if="!ingests.length" icon="inbox" title="无可摄入 PDF" description="把 PDF 放入 <library_root>/_inbox/ 后点「重新扫描」。" />
        </div>
      </div>

      <div class="detail-panel" v-if="selected">
        <div class="detail-header">
          <div>
            <div class="ext-title">{{ selected.original_name }}</div>
            <div class="muted tiny">{{ selected.work_id }} · {{ selected.source_file_id }}</div>
          </div>
        </div>
        <table class="kv">
          <tr><th>work_id</th><td>
            <router-link v-if="selected.existing_work" :to="`/works/${selected.work_id}`">{{ selected.work_id }}</router-link>
            <span v-else>{{ selected.work_id }} <span class="muted tiny">(新建)</span></span>
          </td></tr>
          <tr><th>标题</th><td>{{ selected.metadata?.title || '—' }}</td></tr>
          <tr><th>作者</th><td>{{ (selected.metadata?.authors || []).join('; ') || '—' }}</td></tr>
          <tr><th>年份</th><td>{{ selected.metadata?.year || '—' }}</td></tr>
          <tr><th>arXiv</th><td>{{ selected.metadata?.arxiv_id || '—' }}</td></tr>
          <tr><th>DOI</th><td>{{ selected.metadata?.doi || '—' }}</td></tr>
          <tr><th>类型</th><td>{{ selected.metadata?.doc_type || '—' }}</td></tr>
          <tr><th>语言</th><td>{{ selected.metadata?.language || '—' }}</td></tr>
          <tr><th>元数据态</th><td>{{ selected.metadata?.metadata_status || '—' }}</td></tr>
          <tr><th>文件大小</th><td>{{ formatSize(selected.file_size) }}</td></tr>
          <tr><th>SHA256</th><td class="mono tiny">{{ selected.content_sha256 }}</td></tr>
        </table>

        <div class="better-banner" v-if="selected.title_duplicate_candidates?.length">
          ⚠ 标题疑似已有 work：
          <span v-for="(c, i) in selected.title_duplicate_candidates" :key="i">
            <router-link :to="`/works/${c.work_id}`">{{ c.work_id }}</router-link>
            <span class="muted tiny">(score {{ c.score }})</span>{{ i < selected.title_duplicate_candidates.length - 1 ? '、' : '' }}
          </span>
        </div>
      </div>
      <EmptyState v-else icon="search" title="选择一项查看摄入详情" />
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
import { ref, computed, onMounted } from 'vue'
import { getIngestPlan, executeIngest } from '../api'
import { showError } from '../error-handler'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import StatusBadge from '../components/StatusBadge.vue'
import EmptyState from '../components/EmptyState.vue'

const plan = ref(null)
const selectedIdx = ref(0)
const busy = ref(false)
const leaveInbox = ref(false)

// ConfirmDialog state
const showConfirmDialog = ref(false)
const confirmTitle = ref('')
const confirmMessage = ref('')
const confirmAction = ref(null)

const ingests = computed(() => plan.value?.ingests || [])
const selected = computed(() => ingests.value[selectedIdx.value] || null)

function formatSize(bytes) {
  if (!bytes && bytes !== 0) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

async function reload() {
  if (busy.value) return
  busy.value = true
  try {
    plan.value = await getIngestPlan()
    if (selectedIdx.value >= ingests.value.length) selectedIdx.value = 0
  } catch (e) {
    showError(e)
  } finally {
    busy.value = false
  }
}

function showExecuteConfirm() {
  if (!plan.value || plan.value.summary.ingests === 0 || busy.value) return
  const n = plan.value.summary.ingests
  confirmTitle.value = '确认摄入'
  confirmMessage.value = `摄入 _inbox/ 中 ${n} 个 PDF？将直写 works 并创建待解析任务。`
  confirmAction.value = () => doExecute()
  showConfirmDialog.value = true
}

async function doExecute() {
  showConfirmDialog.value = false
  busy.value = true
  try {
    const res = await executeIngest({ leave_inbox: leaveInbox.value })
    const s = res.summary || {}
    const ingested = s.ingests ?? 0
    const dups = s.exact_duplicates ?? 0
    const skipped = s.skipped ?? 0

    let msg = `摄入完成：${ingested} 个新文献`
    if (dups) msg += `，跳过 ${dups} 个精确重复`
    if (skipped) msg += `，跳过 ${skipped} 个错误`

    // Show links to newly created works
    if (res.ingests?.length) {
      msg += '\n\n新文献：'
      for (const item of res.ingests.slice(0, 5)) {
        msg += `\n- ${item.work_id}`
      }
      if (res.ingests.length > 5) {
        msg += `\n... 共 ${res.ingests.length} 篇`
      }
    }

    window.__naive_message?.success(msg)
    await reload()
  } catch (e) {
    showError(e)
  } finally {
    busy.value = false
  }
}

onMounted(reload)
</script>

<style scoped>
.inbox-layout { display: grid; grid-template-columns: 420px 1fr; gap: 16px; }
.list-panel, .detail-panel { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-xl); padding: var(--space-4); }
.page-title { font-size: 18px; margin-bottom: 12px; }
.summary-bar { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }
.filter-bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
.filter-bar label { display: flex; align-items: center; gap: 4px; color: var(--text-secondary); font-size: 12px; }
.filter-bar button { padding: 4px 12px; border-radius: var(--radius-lg); border: 1px solid var(--border); cursor: pointer; background: var(--bg-surface); }
.filter-bar button:disabled { opacity: .5; cursor: not-allowed; }
.btn-execute { background: var(--accent); color: #fff; border-color: var(--accent); }
.ext-list { display: flex; flex-direction: column; gap: 6px; }
.ext-item { padding: 10px; border: 1px solid var(--border); border-radius: var(--radius-lg); cursor: pointer; }
.ext-item:hover { background: var(--bg-muted); }
.ext-item.selected { border-color: var(--accent); background: var(--selected-bg); }
.ext-title { font-weight: 600; word-break: break-all; }
.ext-meta { display: flex; gap: 6px; align-items: center; margin-top: 4px; flex-wrap: wrap; }
.badge { font-size: 12px; padding: 1px 6px; border-radius: 10px; background: var(--bg-muted); }
.badge.ok { background: var(--ok-bg); color: var(--ok); }
.badge.dup { background: var(--bg-muted); color: var(--text-secondary); }
.badge.skip { background: var(--bad-bg); color: var(--bad); }
.badge.warn { background: var(--warn-bg); color: var(--warn); }
.badge.cand { background: var(--warn-bg); color: var(--warn); }
.muted { color: var(--text-secondary); } .tiny { font-size: 12px; }
.mono { font-family: ui-monospace, Consolas, monospace; word-break: break-all; }
.empty { padding: 20px; text-align: center; }
.detail-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; }
.better-banner { background: var(--warn-bg); border: 1px solid var(--warn); border-radius: var(--radius-lg); padding: 8px 10px; margin-top: 12px; color: var(--warn); }
table.kv { width: 100%; border-collapse: collapse; }
table.kv th { text-align: left; width: 110px; color: var(--text-secondary); padding: 4px 8px; vertical-align: top; }
table.kv td { padding: 4px 8px; word-break: break-all; }
.empty-state { display: flex; align-items: center; justify-content: center; color: var(--text-secondary); }
</style>
