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
          <button class="btn-execute" @click="doExecute"
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
          <div v-if="!ingests.length" class="empty muted">
            _inbox/ 无可摄入 PDF。把 PDF 放入 &lt;library_root&gt;/_inbox/ 后点「重新扫描」。
          </div>
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
      <div class="detail-panel empty-state" v-else>
        <div class="muted">从左侧选择一项查看摄入详情</div>
      </div>
    </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getIngestPlan, executeIngest } from '../api'

const plan = ref(null)
const selectedIdx = ref(0)
const busy = ref(false)
const leaveInbox = ref(false)

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
    alert(e.message)
  } finally {
    busy.value = false
  }
}

async function doExecute() {
  if (!plan.value || plan.value.summary.ingests === 0 || busy.value) return
  const n = plan.value.summary.ingests
  if (!confirm(`摄入 _inbox/ 中 ${n} 个 PDF？将直写 works 并创建待解析任务。`)) return
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

    alert(msg)
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
.inbox-layout { display: grid; grid-template-columns: 420px 1fr; gap: 16px; }
.list-panel, .detail-panel { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px; }
.page-title { font-size: 18px; margin-bottom: 12px; }
.summary-bar { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }
.filter-bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
.filter-bar label { display: flex; align-items: center; gap: 4px; color: var(--muted); font-size: 12px; }
.filter-bar button { padding: 4px 12px; border-radius: 6px; border: 1px solid var(--line); cursor: pointer; background: var(--panel); }
.filter-bar button:disabled { opacity: .5; cursor: not-allowed; }
.btn-execute { background: var(--accent); color: #fff; border-color: var(--accent); }
.ext-list { display: flex; flex-direction: column; gap: 6px; }
.ext-item { padding: 10px; border: 1px solid var(--line); border-radius: 6px; cursor: pointer; }
.ext-item:hover { background: var(--bg); }
.ext-item.selected { border-color: var(--accent); background: #eef5ff; }
.ext-title { font-weight: 600; word-break: break-all; }
.ext-meta { display: flex; gap: 6px; align-items: center; margin-top: 4px; flex-wrap: wrap; }
.badge { font-size: 12px; padding: 1px 6px; border-radius: 10px; background: var(--chip); }
.badge.ok { background: #e6f4ea; color: var(--ok); }
.badge.dup { background: var(--chip); color: var(--muted); }
.badge.skip { background: #fdecea; color: var(--bad); }
.badge.warn { background: #fff8e1; color: var(--warn); }
.badge.cand { background: #fff8e1; color: var(--warn); }
.muted { color: var(--muted); } .tiny { font-size: 12px; }
.mono { font-family: ui-monospace, Consolas, monospace; word-break: break-all; }
.empty { padding: 20px; text-align: center; }
.detail-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; }
.better-banner { background: #fff8e1; border: 1px solid var(--warn); border-radius: 6px; padding: 8px 10px; margin-top: 12px; color: var(--warn); }
table.kv { width: 100%; border-collapse: collapse; }
table.kv th { text-align: left; width: 110px; color: var(--muted); padding: 4px 8px; vertical-align: top; }
table.kv td { padding: 4px 8px; word-break: break-all; }
.empty-state { display: flex; align-items: center; justify-content: center; color: var(--muted); }
</style>
