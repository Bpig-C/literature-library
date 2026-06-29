<template>
    <div class="topics-layout">
      <div class="list-panel">
        <h2 class="page-title">主题闸门 <span class="muted tiny">collector 成熟度</span></h2>

        <div class="filter-bar">
          <label>成熟度：
            <select v-model="mapFilter" @change="resetAndReload">
              <option value="">全部</option>
              <option value="seedling">seedling ({{ countByStatus('seedling') }})</option>
              <option value="proposed">proposed ({{ countByStatus('proposed') }})</option>
              <option value="mapped">mapped ({{ countByStatus('mapped') }})</option>
            </select>
          </label>
          <button @click="reload">刷新</button>
        </div>

        <div class="topic-list">
          <div v-for="t in topics" :key="t.id" class="topic-item"
               :class="{ selected: selected?.id === t.id }"
               @click="selected = t">
            <div class="topic-title">{{ t.name }}</div>
            <div class="topic-meta">
              <span class="badge" :class="`m-${t.map_status}`">{{ t.map_status }}</span>
              <span class="badge life">{{ t.lifecycle }}</span>
              <span v-if="t.axis_hint" class="muted tiny">{{ t.axis_hint }}</span>
            </div>
          </div>
          <div v-if="!topics.length" class="empty muted">
            无主题。先用 CLI 建主题：python scripts/literature_intake.py topic add --name ...
          </div>
        </div>
      </div>

      <div class="detail-panel" v-if="selected">
        <div class="detail-header">
          <div>
            <div class="topic-title">{{ selected.name }}</div>
            <div class="muted tiny">{{ selected.id }} · {{ selected.map_status }} / {{ selected.lifecycle }}</div>
          </div>
          <div class="header-badges">
            <span class="badge" :class="`m-${selected.map_status}`">{{ selected.map_status }}</span>
            <span class="badge life">{{ selected.lifecycle }}</span>
          </div>
        </div>

        <table class="kv">
          <tr><th>描述</th><td>{{ selected.description || '—' }}</td></tr>
          <tr><th>轴归属</th><td>{{ selected.axis_hint || '—' }}</td></tr>
          <tr><th>显式 ID</th>
            <td>{{ (selected.query_def?.explicit_ids || []).join(', ') || '—' }}</td></tr>
          <tr><th>种子</th>
            <td>{{ (selected.query_def?.seed_paper_ids || []).join(', ') || '—' }}</td></tr>
          <tr><th>proposed 判据</th>
            <td><pre v-if="selected.proposed_note" class="note">{{ selected.proposed_note }}</pre>
              <span v-else class="muted">—</span></td></tr>
          <tr><th>mapped 标签</th>
            <td>
              <span v-if="selected.mapped_tags" class="tags">
                <span v-for="(tag, i) in selected.mapped_tags" :key="i" class="tag-chip">
                  {{ tag.group }}={{ tag.value }}
                </span>
              </span>
              <span v-else class="muted">—</span>
            </td></tr>
        </table>

        <div class="gate-bar">
          <button class="btn-propose" :disabled="busy || selected.map_status !== 'seedling'"
                  @click="doPropose">
            提案为 proposed
          </button>
          <button class="btn-map" :disabled="busy || selected.map_status !== 'proposed'"
                  @click="doMap">
            映射为 mapped
          </button>
          <button class="btn-collect" :disabled="busy" @click="doCollect">
            按主题发起采集
          </button>
          <button class="btn-resolve" :disabled="busy" @click="doResolve">
            触发 resolve
          </button>
        </div>
        <div class="muted tiny hint">
          proposed 4 判据：复现性 / 不可折叠 / 轴归属 / 边界可述
        </div>
      </div>
      <div class="detail-panel empty-state" v-else>
        <div class="muted">从左侧选择一个主题查看详情</div>
      </div>
    </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import {
  getIntakeTopics,
  transitionTopic,
  collectIntake,
  resolveIntake,
} from '../api'

const topics = ref([])
const selected = ref(null)
const busy = ref(false)
const mapFilter = ref('')

const countByStatus = (s) => topics.value.filter(t => t.map_status === s).length

function resetAndReload() {
  return reload()
}

async function reload() {
  const body = await getIntakeTopics(mapFilter.value ? { map_status: mapFilter.value } : {})
  topics.value = body.topics || []
  if (selected.value) {
    selected.value = topics.value.find(t => t.id === selected.value.id) || null
  }
}

async function doPropose() {
  if (!selected.value || busy.value) return
  const note = prompt(
    'proposed_note：填写 4 判据（复现性 / 不可折叠 / 轴归属 / 边界可述）',
    '复现N篇 / 不可折叠 / 轴 risk_domain / 边界可述'
  )
  if (note === null) return
  if (!note.trim()) { alert('proposed 必须带非空判据（4 criteria）'); return }
  busy.value = true
  try {
    await transitionTopic(selected.value.id, { to_map_status: 'proposed', proposed_note: note })
    await reload()
  } catch (e) {
    alert(e.message)
  } finally {
    busy.value = false
  }
}

async function doMap() {
  if (!selected.value || busy.value) return
  const raw = prompt(
    'mapped_tags：逗号分隔，形如 risk_domain=alignment_fail',
    'risk_domain=alignment_fail'
  )
  if (raw === null) return
  const tags = raw.split(',').map(s => s.trim()).filter(Boolean).map(kv => {
    const [group, value] = kv.split('=').map(x => x.trim())
    return { group: group || 'risk_domain', value: value || kv }
  })
  if (!tags.length) { alert('mapped 必须带 mapped_tags'); return }
  busy.value = true
  try {
    await transitionTopic(selected.value.id, { to_map_status: 'mapped', mapped_tags: tags })
    await reload()
  } catch (e) {
    alert(e.message)
  } finally {
    busy.value = false
  }
}

async function doCollect() {
  if (!selected.value || busy.value) return
  if (!confirm(`按主题 ${selected.value.name} 发起一次采集？(触达网络)`)) return
  busy.value = true
  try {
    const res = await collectIntake({ topic_id: selected.value.id })
    alert(`采集完成：新增 ${res.created} 个候选`)
  } catch (e) {
    alert(e.message)
  } finally {
    busy.value = false
  }
}

async function doResolve() {
  if (busy.value) return
  if (!confirm('对 pending/new/needs_better_copy 候选触发重量闸门 resolve？(下载 + SHA256)')) return
  busy.value = true
  try {
    const res = await resolveIntake({})
    alert(`resolve 完成：处理 ${res.resolved} 个候选`)
  } catch (e) {
    alert(e.message)
  } finally {
    busy.value = false
  }
}

onMounted(reload)
</script>

<style scoped>
.topics-layout { display: grid; grid-template-columns: 380px 1fr; gap: 16px; }
.list-panel, .detail-panel { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px; }
.page-title { font-size: 18px; margin-bottom: 12px; }
.filter-bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
.filter-bar select { padding: 4px 6px; border: 1px solid var(--line); border-radius: 4px; }
.topic-list { display: flex; flex-direction: column; gap: 6px; }
.topic-item { padding: 10px; border: 1px solid var(--line); border-radius: 6px; cursor: pointer; }
.topic-item:hover { background: var(--bg); }
.topic-item.selected { border-color: var(--accent); background: #eef5ff; }
.topic-title { font-weight: 600; }
.topic-meta { display: flex; gap: 6px; align-items: center; margin-top: 4px; flex-wrap: wrap; }
.badge { font-size: 12px; padding: 1px 6px; border-radius: 10px; background: var(--chip); }
.badge.m-seedling { background: #fff8e1; color: var(--warn); }
.badge.m-proposed { background: #e6f4ea; color: var(--ok); }
.badge.m-mapped { background: var(--accent); color: #fff; }
.badge.life { background: var(--chip); color: var(--muted); }
.muted { color: var(--muted); } .tiny { font-size: 12px; }
.empty { padding: 20px; text-align: center; }
.detail-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; }
.header-badges { display: flex; gap: 6px; }
table.kv { width: 100%; border-collapse: collapse; margin-bottom: 12px; }
table.kv th { text-align: left; width: 120px; color: var(--muted); padding: 4px 8px; vertical-align: top; }
table.kv td { padding: 4px 8px; }
.note { background: var(--bg); padding: 6px; border-radius: 4px; font-size: 12px; white-space: pre-wrap; margin: 0; }
.tags { display: flex; flex-wrap: wrap; gap: 4px; }
.tag-chip { font-size: 12px; padding: 1px 6px; border-radius: 10px; background: var(--chip); }
.gate-bar { display: flex; gap: 8px; margin-top: 16px; flex-wrap: wrap; }
.gate-bar button { padding: 6px 14px; border-radius: 6px; border: 1px solid var(--line); cursor: pointer; background: var(--panel); }
.btn-propose { background: #fff8e1; color: var(--warn); border-color: var(--warn); }
.btn-map { background: var(--accent); color: #fff; border-color: var(--accent); }
.btn-collect { background: #e6f4ea; color: var(--ok); border-color: var(--ok); }
.btn-resolve { background: var(--panel); color: var(--text); }
.gate-bar button:disabled { opacity: .5; cursor: not-allowed; }
.hint { margin-top: 8px; }
.empty-state { display: flex; align-items: center; justify-content: center; color: var(--muted); }
</style>
