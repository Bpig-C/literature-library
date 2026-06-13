<template>
  <div>
    <h1>去重确认</h1>
    <div class="toolbar">
      <select v-model="typeFilter">
        <option value="all">类型：全部</option>
        <option value="exact_sha256">SHA256 完全相同</option>
        <option value="title_candidate">标题相似</option>
      </select>
      <select v-model="statusFilter">
        <option value="needsreview">需审查</option>
        <option value="all">状态：全部</option>
        <option value="pending">未决策</option>
        <option value="confirmed">已自动确认</option>
      </select>
      <input v-model="search" placeholder="搜索标题、ID..." />
    </div>

    <div class="stats-bar">
      <div class="stat-card"><b>{{ filtered.length }}</b><span>重复组</span></div>
      <div class="stat-card"><b>{{ filteredAutoCount }}</b><span>已自动确认</span></div>
      <div class="stat-card"><b>{{ filtered.length - filteredAutoCount }}</b><span>需审查</span></div>
    </div>

    <div v-for="g in filtered" :key="g.id" class="group-card">
      <div class="group-header">
        <div>
          <span class="group-id">{{ g.id }}</span>
          <span class="chip">{{ g.duplicate_type === 'exact_sha256' ? 'SHA256 相同' : '标题相似' }}</span>
          <span class="muted tiny">{{ g.candidates.length }} 个来源 · {{ g.work_ids.length }} 个作品</span>
        </div>
        <span :class="'badge ' + badgeClass(g)">{{ badgeText(g) }}</span>
      </div>

        <div class="cand-grid">
        <div v-for="c in g.candidates" :key="c.id" class="cand-card">
          <div class="cand-title">{{ c.work_title || c.work_id }}</div>
          <div class="cand-meta">
            <div>ID: {{ c.work_id }}</div>
            <div v-if="c.work_year">年份: {{ c.work_year }}</div>
            <div v-if="c.work_doc_type">类型: {{ c.work_doc_type }}</div>
            <div v-if="c.work_language">语言: {{ c.work_language }}</div>
            <div v-if="c.work_arxiv_id">arXiv: <a :href="'https://arxiv.org/abs/' + c.work_arxiv_id" target="_blank">{{ c.work_arxiv_id }}</a></div>
            <div v-if="c.work_doi">DOI: <a :href="'https://doi.org/' + c.work_doi" target="_blank">{{ c.work_doi }}</a></div>
          </div>
          <div class="cand-signals">
            <span v-if="c.source_file_size" class="signal" title="文件大小">📄 {{ formatSize(c.source_file_size) }}</span>
            <span class="signal" title="已审核标签数">🏷️ {{ c.tag_count }}</span>
            <span v-if="c.score" class="signal" title="相似度">📊 {{ (c.score * 100).toFixed(0) }}%</span>
          </div>
          <div class="cand-source">{{ c.source_original_name || '' }}</div>
        </div>
      </div>

      <div v-if="g.auto_confirmed" class="auto-msg">
        ✓ 已自动确认：SHA256 完全相同，属于同一作品的不同来源文件
      </div>
      <div v-else class="decision-section">
        <div v-for="pair in pairs(g)" :key="pair.key" class="pair-row">
          <div class="pair-label">{{ pair.label }}</div>
          <div class="decision-btns">
            <button
              v-for="dt in DECISION_TYPES" :key="dt[0]"
              :class="{ selected: decisions[pair.key]?.type === dt[0] }"
              @click="setDecision(pair.key, dt[0])"
            >{{ dt[1] }}</button>
            <button class="skip-btn" @click="setDecision(pair.key, 'skip')">跳过</button>
          </div>
        </div>
      </div>
    </div>

    <div class="empty" v-if="!filtered.length">没有匹配的重复组</div>

    <div class="cmd-bar" v-if="Object.keys(decisions).length">
      <span class="muted">已决策 {{ Object.keys(decisions).length }} 项</span>
      <button class="export-btn" @click="exportJSON">导出 dedup_reviews.json</button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getDuplicates } from '../api'

const DECISION_TYPES = [
  ['same_work', '同一作品'],
  ['not_duplicate', '非重复'],
  ['version_of', '版本关系'],
  ['translation_of', '翻译关系'],
  ['supersedes', '取代关系'],
  ['part_of', '部分关系'],
  ['quarantine', '隔离'],
]

const STORAGE_KEY = 'literature_dedup_decisions'
const allGroups = ref([])
const typeFilter = ref('all')
const statusFilter = ref('needsreview')
const search = ref('')
const decisions = ref({})

// Restore from localStorage
try {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved) decisions.value = JSON.parse(saved)
} catch {}

function saveDecisions() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(decisions.value)) } catch {}
}

const filtered = computed(() => {
  return allGroups.value.filter(g => {
    if (typeFilter.value !== 'all' && g.duplicate_type !== typeFilter.value) return false
    if (statusFilter.value === 'needsreview') {
      if (g.auto_confirmed) return false
      const hasUnreviewed = g.candidates.some(c => !c.reviewed)
      if (!hasUnreviewed) return false
    }
    if (statusFilter.value === 'confirmed' && !g.auto_confirmed) return false
    if (search.value) {
      const q = search.value.toLowerCase()
      const haystack = g.candidates.map(c =>
        [c.work_id, c.work_title, c.source_original_name, g.id].join(' ')
      ).join(' ').toLowerCase()
      if (!haystack.includes(q)) return false
    }
    return true
  })
})

const filteredAutoCount = computed(() => filtered.value.filter(g => g.auto_confirmed).length)

function pairs(g) {
  if (g.duplicate_type === 'exact_sha256') {
    return [{ key: 'group:' + g.id, label: '这组是同一文献？' }]
  }
  const wids = g.work_ids
  const result = []
  for (let i = 0; i < wids.length; i++) {
    for (let j = i + 1; j < wids.length; j++) {
      const tA = g.candidates.find(c => c.work_id === wids[i])?.work_title || wids[i]
      const tB = g.candidates.find(c => c.work_id === wids[j])?.work_title || wids[j]
      result.push({ key: 'pair:' + wids[i] + '|' + wids[j], label: tA + ' → ' + tB })
    }
  }
  return result
}

function setDecision(key, type) {
  decisions.value[key] = { type, note: '', timestamp: new Date().toISOString() }
  saveDecisions()
}

function badgeClass(g) {
  if (g.auto_confirmed) return 'confirmed'
  const keys = pairs(g).map(p => p.key)
  const allDecided = keys.every(k => decisions.value[k])
  return allDecided ? 'decided' : 'pending'
}

function badgeText(g) {
  if (g.auto_confirmed) return '已自动确认'
  const keys = pairs(g).map(p => p.key)
  const allDecided = keys.every(k => decisions.value[k])
  return allDecided ? '已决策' : '待决策'
}

function formatSize(bytes) {
  if (!bytes) return ''
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

function exportJSON() {
  const items = []
  for (const [key, d] of Object.entries(decisions.value)) {
    if (d.type === 'skip') continue
    const entry = { key, decision_type: d.type, note: d.note || '', timestamp: d.timestamp }
    if (key.startsWith('group:')) {
      entry.group_id = key.slice(6)
    } else if (key.startsWith('pair:')) {
      const [a, b] = key.slice(5).split('|')
      entry.work_id_a = a
      entry.work_id_b = b
    }
    items.push(entry)
  }
  const blob = new Blob([JSON.stringify({ decisions: items }, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'dedup_reviews.json'
  a.click()
  URL.revokeObjectURL(url)
}

onMounted(async () => {
  const res = await getDuplicates()
  allGroups.value = res.groups
})
</script>

<style scoped>
h1 { margin-bottom: 12px; font-size: 22px; }
.toolbar { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.toolbar select, .toolbar input {
  height: 34px; border: 1px solid var(--line); border-radius: 6px; padding: 0 10px; font: inherit;
}
.stats-bar { display: flex; gap: 10px; margin-bottom: 16px; }
.stat-card { background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 8px 14px; }
.stat-card b { display: block; font-size: 20px; }
.stat-card span { color: var(--muted); font-size: 12px; }
.group-card { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; margin-bottom: 14px; }
.group-header { display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; background: #f1f4f8; border-bottom: 1px solid var(--line); flex-wrap: wrap; gap: 6px; }
.group-id { font-weight: 650; font-size: 15px; }
.chip { display: inline-block; padding: 2px 8px; border-radius: 999px; background: var(--chip); font-size: 12px; margin: 0 4px; }
.muted { color: var(--muted); }
.tiny { font-size: 12px; }
.badge { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 999px; }
.badge.confirmed { background: #dcfce7; color: #15803d; }
.badge.decided { background: #d1fae5; color: #065f46; }
.badge.pending { background: #fef9c3; color: #92400e; }
.cand-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 10px; padding: 12px 14px; }
.cand-card { border: 1px solid var(--line); border-radius: 6px; padding: 10px 12px; background: #fafbfc; }
.cand-title { font-weight: 600; margin-bottom: 4px; word-break: break-word; }
.cand-meta { font-size: 12px; color: var(--muted); }
.cand-source { font-size: 12px; color: #475467; margin-top: 4px; word-break: break-all; }
.cand-signals { display: flex; gap: 8px; margin-top: 6px; flex-wrap: wrap; }
.signal { font-size: 11px; color: #374151; background: #f3f4f6; padding: 2px 6px; border-radius: 4px; }
.auto-msg { padding: 10px 14px; color: #065f46; font-size: 13px; border-top: 1px solid var(--line); }
.decision-section { padding: 12px 14px; border-top: 1px solid var(--line); }
.pair-row { margin-bottom: 10px; }
.pair-label { font-size: 12px; font-weight: 600; color: var(--muted); margin-bottom: 4px; }
.decision-btns { display: flex; gap: 6px; flex-wrap: wrap; }
.decision-btns button { padding: 4px 10px; border-radius: 999px; font-size: 12px; border: 1px solid var(--line); background: #fff; cursor: pointer; transition: all .15s; }
.decision-btns button.selected { color: #fff; font-weight: 600; background: var(--accent); border-color: var(--accent); }
.skip-btn { color: var(--muted) !important; border-style: dashed !important; }
.empty { padding: 28px; text-align: center; color: var(--muted); background: var(--panel); border: 1px solid var(--line); border-radius: 6px; }
.cmd-bar { display: flex; align-items: center; gap: 12px; padding: 12px 14px; margin-top: 16px; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }
.export-btn { height: 34px; padding: 0 16px; background: var(--accent); color: #fff; border: none; border-radius: 6px; cursor: pointer; font: inherit; }
</style>
