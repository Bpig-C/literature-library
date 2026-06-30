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
          <button @click="showCreateForm = true" class="btn-create">新建主题</button>
        </div>

        <div class="topic-list">
          <div v-for="t in topics" :key="t.id" class="topic-item"
               :class="{ selected: selected?.id === t.id }"
               @click="selected = t; loadDiscoveryRuns()">
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
                <span v-for="(tag, i) in selected.mapped_tags" :key="i"
                      class="tag-chip" :class="{ 'tag-unknown': !isVocabValue(tag.group, tag.value) }">
                  {{ tag.group }}={{ tag.value }}
                  <span v-if="!isVocabValue(tag.group, tag.value)" class="tag-warn">?</span>
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
                  @click="openMapModal">
            映射为 mapped
          </button>
          <button class="btn-collect" :disabled="busy" @click="doCollect">
            按主题发起采集
          </button>
          <button class="btn-resolve" :disabled="busy" @click="doResolve">
            触发 resolve
          </button>
        </div>
        <div class="gate-bar">
          <button class="btn-discovery" :disabled="busy" @click="doDiscoveryPlan">
            生成检索方案
          </button>
          <router-link :to="`/discovery?topic_id=${selected.id}`" class="btn-view-discovery">
            查看发现结果
          </router-link>
        </div>
        <div v-if="discoveryRuns.length" class="discovery-runs-section">
          <div class="section-title" @click="showDiscoveryRuns = !showDiscoveryRuns">
            最近发现检索 {{ showDiscoveryRuns ? '[-]' : '[+]' }}
          </div>
          <div v-if="showDiscoveryRuns" class="discovery-runs-list">
            <div v-for="run in discoveryRuns" :key="run.id" class="discovery-run-item">
              <span class="run-mode">{{ run.mode }}</span>
              <code class="run-id">{{ run.id }}</code>
              <span class="run-status" :class="run.status">{{ run.status }}</span>
              <span class="muted tiny">{{ run.created_at?.slice(0, 16) }}</span>
            </div>
          </div>
        </div>
        <div class="muted tiny hint">
          proposed 4 判据：复现性 / 不可折叠 / 轴归属 / 边界可述
        </div>
      </div>
      <div class="detail-panel empty-state" v-else>
        <div class="muted">从左侧选择一个主题查看详情</div>
      </div>

      <!-- 新建主题表单 -->
      <div v-if="showCreateForm" class="create-modal-overlay" @click.self="showCreateForm = false">
        <div class="create-modal">
          <h3>新建采集主题</h3>
          <div class="form-group">
            <label>主题名称 *</label>
            <input v-model="createForm.name" placeholder="如: AI Safety Governance Frameworks" />
          </div>
          <div class="form-group">
            <label>描述</label>
            <textarea v-model="createForm.description" placeholder="主题描述..." rows="3"></textarea>
          </div>
          <div class="form-group">
            <label>显式 arXiv ID（逗号分隔）</label>
            <input v-model="createForm.explicit_ids_str" placeholder="2501.00001, 2501.00002" />
          </div>
          <div class="form-group">
            <label>种子文献 ID（逗号分隔）</label>
            <input v-model="createForm.seed_paper_ids_str" placeholder="W-arxiv-2501.00001" />
          </div>
          <div class="form-group">
            <label>轴归属</label>
            <input v-model="createForm.axis_hint" placeholder="如: risk_domain" />
          </div>
          <div class="form-group">
            <label>关联标签</label>
            <div class="tag-picker-row">
              <select v-model="tagPicker.group" @change="tagPicker.value = ''">
                <option v-for="g in vocabGroups" :key="g" :value="g">{{ g }}</option>
              </select>
              <select v-model="tagPicker.value">
                <option value="" disabled>选择值…</option>
                <option v-for="v in createVocabValues" :key="v" :value="v">{{ v }}</option>
              </select>
              <input v-model="tagPicker.customValue" placeholder="或自定义值…" />
              <button type="button" @click="addCreateTag" class="btn-add-tag-sm">+</button>
            </div>
            <div v-if="createForm.tags.length" class="map-tags-list" style="margin-top: 6px;">
              <span v-for="(tag, i) in createForm.tags" :key="i" class="tag-chip">
                {{ tag.group }}={{ tag.value }}
                <span v-if="tag._proposed" class="tag-warn" title="proposed_new">?</span>
                <button class="btn-remove-tag" @click="removeCreateTag(i)">×</button>
              </span>
            </div>
          </div>

          <!-- P1-3: 高级线索折叠区 -->
          <details class="advanced-clues-section">
            <summary>高级线索（可选）</summary>
            <div class="form-group">
              <label>关键词（逗号分隔）</label>
              <textarea v-model="createForm.keywords" rows="2" placeholder="如: reward hacking, goal misgeneralization"></textarea>
            </div>
            <div class="form-group">
              <label>作者（逗号分隔）</label>
              <textarea v-model="createForm.authors" rows="2" placeholder="如: Alice Smith, Bob Jones"></textarea>
            </div>
            <div class="form-group">
              <label>机构（逗号分隔）</label>
              <textarea v-model="createForm.institutions" rows="2" placeholder="如: OpenAI, DeepMind"></textarea>
            </div>
            <div class="form-group">
              <label>已知名称（逗号分隔）</label>
              <textarea v-model="createForm.known_names" rows="2" placeholder="如: GPT-4, Claude"></textarea>
            </div>
            <div class="form-group">
              <label>已知标题（逗号分隔）</label>
              <textarea v-model="createForm.known_titles" rows="2" placeholder="如: Scaling Laws for Neural Language Models"></textarea>
            </div>
            <div class="form-group">
              <label>已知 URL（逗号分隔）</label>
              <textarea v-model="createForm.known_urls" rows="2" placeholder="如: https://arxiv.org/abs/2001.08361"></textarea>
            </div>
            <div class="form-group">
              <label>偏好域名（逗号分隔）</label>
              <textarea v-model="createForm.preferred_domains" rows="2" placeholder="如: arxiv.org, openreview.net"></textarea>
            </div>
            <div class="form-group">
              <label>排除词（逗号分隔）</label>
              <textarea v-model="createForm.exclude_terms" rows="2" placeholder="如: reddit, forum, news"></textarea>
            </div>
          </details>
          <div class="form-actions">
            <button @click="showCreateForm = false" class="btn-cancel">取消</button>
            <button @click="doCreateTopic" :disabled="!createForm.name || busy" class="btn-submit">创建</button>
          </div>
        </div>
      </div>

      <!-- 映射标签 modal -->
      <div v-if="showMapModal" class="create-modal-overlay" @click.self="showMapModal = false">
        <div class="create-modal">
          <h3>映射为 mapped — {{ selected?.name }}</h3>
          <div class="form-group">
            <label>标签分组</label>
            <select v-model="mapForm.group" @change="mapForm.value = ''">
              <option v-for="g in vocabGroups" :key="g" :value="g">{{ g }}</option>
            </select>
          </div>
          <div class="form-group">
            <label>标签值</label>
            <select v-model="mapForm.value">
              <option value="" disabled>请选择…</option>
              <option v-for="v in vocabValues" :key="v" :value="v">{{ v }}</option>
            </select>
          </div>
          <button class="btn-add-tag" :disabled="!mapForm.value" @click="addMapTag">添加一条映射</button>

          <div v-if="mapTags.length" class="map-tags-list">
            <div v-for="(tag, i) in mapTags" :key="i" class="map-tag-item">
              <span class="tag-chip">{{ tag.group }}={{ tag.value }}</span>
              <button class="btn-remove-tag" @click="removeMapTag(i)">×</button>
            </div>
          </div>
          <div v-else class="muted tiny" style="margin-bottom: 12px;">
            尚未添加任何映射标签，请从上方选择后点击"添加"
          </div>

          <div class="form-actions">
            <button @click="showMapModal = false" class="btn-cancel">取消</button>
            <button @click="doMap" :disabled="!mapTags.length || busy" class="btn-submit">提交映射</button>
          </div>
        </div>
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
  createTopic,
  getVocab,
  discoveryPlan,
  discoveryRun,
  getDiscoveryRuns,
} from '../api'

const topics = ref([])
const selected = ref(null)
const busy = ref(false)
const mapFilter = ref('')
const showCreateForm = ref(false)
const createForm = ref({
  name: '',
  description: '',
  explicit_ids_str: '',
  seed_paper_ids_str: '',
  axis_hint: '',
  tags: [],
  // P1-3: rich query_def fields
  keywords: '',
  authors: '',
  institutions: '',
  known_names: '',
  known_titles: '',
  known_urls: '',
  preferred_domains: '',
  exclude_terms: '',
})
const tagPicker = ref({ group: 'risk_domain', value: '', customValue: '' })
const showMapModal = ref(false)
const vocab = ref(null)
const mapForm = ref({ group: 'risk_domain', value: '' })
const mapTags = ref([])
const discoveryRuns = ref([])
const showDiscoveryRuns = ref(false)

const countByStatus = (s) => topics.value.filter(t => t.map_status === s).length

const vocabGroups = ['risk_domain', 'reading_lane', 'method_tags']

const vocabValues = computed(() => {
  if (!vocab.value) return []
  const g = mapForm.value.group
  const node = vocab.value[g] || vocab.value.groups?.[g]
  if (Array.isArray(node)) return node
  if (node && typeof node === 'object') return Object.keys(node)
  return []
})

function isVocabValue(group, value) {
  if (!vocab.value || !Object.keys(vocab.value).length) return true
  const node = vocab.value[group] || vocab.value.groups?.[group]
  if (!node) return false
  if (Array.isArray(node)) return node.includes(value)
  if (typeof node === 'object') return value in node
  return false
}

const createVocabValues = computed(() => {
  if (!vocab.value) return []
  const g = tagPicker.value.group
  const node = vocab.value[g] || vocab.value.groups?.[g]
  if (Array.isArray(node)) return node
  if (node && typeof node === 'object') return Object.keys(node)
  return []
})

function addCreateTag() {
  const g = tagPicker.value.group
  // 优先使用自定义值，否则使用下拉选中的值
  const custom = (tagPicker.value.customValue || '').trim()
  const v = custom || tagPicker.value.value
  if (!g || !v) { alert('请选择分组和值（或填写自定义值）'); return }
  if (createForm.value.tags.some(t => t.group === g && t.value === v)) {
    alert('该标签已添加，请勿重复'); return
  }
  const inVocab = isVocabValue(g, v)
  createForm.value.tags.push({ group: g, value: v, status: inVocab ? 'approved' : 'proposed_new', _proposed: !inVocab })
  tagPicker.value.value = ''
  tagPicker.value.customValue = ''
}

function removeCreateTag(idx) {
  createForm.value.tags.splice(idx, 1)
}

async function ensureVocabLoaded(showAlert = false) {
  if (vocab.value && Object.keys(vocab.value).length) return true
  try {
    vocab.value = await getVocab()
    return true
  } catch (e) {
    vocab.value = null
    if (showAlert) {
      alert('标签词表加载失败，下拉选项将为空：' + e.message)
    }
    return false
  }
}

async function openMapModal() {
  if (!selected.value || busy.value) return
  await ensureVocabLoaded(true)
  mapTags.value = []
  mapForm.value = { group: 'risk_domain', value: '' }
  showMapModal.value = true
}

function addMapTag() {
  const g = mapForm.value.group
  const v = mapForm.value.value
  if (!g || !v) return
  if (mapTags.value.some(t => t.group === g && t.value === v)) {
    alert('该标签已添加，请勿重复')
    return
  }
  mapTags.value.push({ group: g, value: v })
  mapForm.value.value = ''
}

function removeMapTag(idx) {
  mapTags.value.splice(idx, 1)
}

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
  if (!mapTags.value.length) { alert('mapped 必须带 mapped_tags'); return }
  busy.value = true
  try {
    await transitionTopic(selected.value.id, { to_map_status: 'mapped', mapped_tags: mapTags.value })
    showMapModal.value = false
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

// P1-3: Parse comma-separated fields into arrays for query_def
function parseList(str) {
  if (!str) return []
  return str.split(',').map(s => s.trim()).filter(Boolean)
}

function buildQueryDef() {
  const qd = {}
  const fields = {
    keywords: createForm.value.keywords,
    authors: createForm.value.authors,
    institutions: createForm.value.institutions,
    known_names: createForm.value.known_names,
    known_titles: createForm.value.known_titles,
    known_urls: createForm.value.known_urls,
    preferred_domains: createForm.value.preferred_domains,
    exclude_terms: createForm.value.exclude_terms,
  }
  for (const [key, val] of Object.entries(fields)) {
    const list = parseList(val)
    if (list.length) qd[key] = list
  }
  return qd
}

async function doCreateTopic() {
  if (!createForm.value.name || busy.value) return
  busy.value = true
  try {
    const payload = {
      name: createForm.value.name,
      description: createForm.value.description,
      axis_hint: createForm.value.axis_hint || null,
    }
    if (createForm.value.explicit_ids_str) {
      payload.explicit_ids = createForm.value.explicit_ids_str.split(',').map(s => s.trim()).filter(Boolean)
    }
    if (createForm.value.seed_paper_ids_str) {
      payload.seed_paper_ids = createForm.value.seed_paper_ids_str.split(',').map(s => s.trim()).filter(Boolean)
    }
    // P1-3: Build query_def from rich clues
    const qd = buildQueryDef()
    if (Object.keys(qd).length) {
      payload.query_def = qd
    }
    if (createForm.value.tags.length) {
      payload.mapped_tags = createForm.value.tags.map(t => ({ group: t.group, value: t.value }))
    }
    await createTopic(payload)
    showCreateForm.value = false
    createForm.value = { name: '', description: '', explicit_ids_str: '', seed_paper_ids_str: '', axis_hint: '', tags: [], keywords: '', authors: '', institutions: '', known_names: '', known_titles: '', known_urls: '', preferred_domains: '', exclude_terms: '' }
    await reload()
  } catch (e) {
    alert(e.message)
  } finally {
    busy.value = false
  }
}

async function doDiscoveryPlan() {
  if (!selected.value || busy.value) return
  busy.value = true
  try {
    const plan = await discoveryPlan({ mode: 'topic', topic_id: selected.value.id })
    const run = await discoveryRun({
      mode: 'topic',
      input: { mode: 'topic', topic_id: selected.value.id },
      plan,
      executor: 'agent:web-access',
      topic_id: selected.value.id,
    })
    alert(`检索方案已生成并创建 run：${run.run_id}，${(plan.queries || []).length} 条查询`)
    await loadDiscoveryRuns()
  } catch (e) {
    alert(e.message)
  } finally {
    busy.value = false
  }
}

async function loadDiscoveryRuns() {
  if (!selected.value) return
  try {
    const res = await getDiscoveryRuns({ topic_id: selected.value.id, per_page: 5 })
    discoveryRuns.value = res.runs || []
  } catch {
    discoveryRuns.value = []
  }
}

onMounted(() => {
  reload()
  ensureVocabLoaded(false)
})
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

/* Create topic modal */
.btn-create { background: var(--accent); color: #fff; border: none; padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 13px; }
.btn-create:hover { opacity: 0.9; }
.create-modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex;
  align-items: center; justify-content: center; z-index: 1000;
}
.create-modal {
  background: #fff; border-radius: 8px; padding: 24px; width: 460px;
  max-width: 90vw; box-shadow: 0 8px 32px rgba(0,0,0,0.18);
}
.create-modal h3 { margin: 0 0 16px; font-size: 16px; }
.form-group { margin-bottom: 12px; }
.form-group label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; }
.form-group input, .form-group textarea {
  width: 100%; padding: 8px 10px; border: 1px solid var(--line); border-radius: 6px;
  font-size: 13px; font-family: inherit;
}
.form-group textarea { resize: vertical; }

/* P1-3: Advanced clues section */
.advanced-clues-section {
  margin-bottom: 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 8px;
}
.advanced-clues-section summary {
  cursor: pointer;
  font-size: 13px;
  color: var(--accent);
  font-weight: 500;
  padding: 4px 0;
}
.advanced-clues-section summary:hover {
  opacity: 0.8;
}
.advanced-clues-section[open] summary {
  margin-bottom: 8px;
}

.form-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.btn-cancel { padding: 6px 14px; border-radius: 6px; border: 1px solid var(--line); cursor: pointer; background: var(--panel); }
.btn-submit { padding: 6px 14px; border-radius: 6px; border: none; cursor: pointer; background: var(--accent); color: #fff; }
.btn-submit:disabled { opacity: .5; cursor: not-allowed; }

/* Map tag modal */
.btn-add-tag {
  padding: 6px 14px; border-radius: 6px; border: 1px solid var(--accent);
  cursor: pointer; background: var(--accent); color: #fff; font-size: 13px;
  margin-bottom: 12px;
}
.btn-add-tag:disabled { opacity: .5; cursor: not-allowed; }
.tag-picker-row { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.tag-picker-row select, .tag-picker-row input { flex: 1; min-width: 100px; padding: 6px 8px; border: 1px solid var(--line); border-radius: 4px; font-size: 13px; }
.btn-add-tag-sm {
  width: 28px; height: 28px; border-radius: 50%; border: 1px solid var(--accent);
  background: var(--accent); color: #fff; cursor: pointer; font-size: 16px;
  display: flex; align-items: center; justify-content: center; padding: 0; flex-shrink: 0;
}
.btn-add-tag-sm:disabled { opacity: .5; cursor: not-allowed; }
.map-tags-list { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.map-tag-item { display: flex; align-items: center; gap: 4px; }
.btn-remove-tag {
  width: 18px; height: 18px; border-radius: 50%; border: none;
  background: #e74c3c; color: #fff; cursor: pointer; font-size: 12px;
  display: flex; align-items: center; justify-content: center; padding: 0;
}
.tag-unknown { background: #fce4ec; color: #c62828; }
.tag-warn { margin-left: 2px; font-weight: 700; }
.form-group select {
  width: 100%; padding: 8px 10px; border: 1px solid var(--line); border-radius: 6px;
  font-size: 13px; font-family: inherit; background: var(--panel);
}

/* Discovery buttons */
.btn-discovery { background: #ede9fe; color: #6d28d9; border-color: #7c3aed; }
.btn-view-discovery {
  display: inline-flex; align-items: center; padding: 6px 14px; border-radius: 6px;
  border: 1px solid var(--accent); color: var(--accent); font-size: 13px;
  text-decoration: none; cursor: pointer; background: #eef5ff;
}
.btn-view-discovery:hover { background: var(--accent); color: #fff; text-decoration: none; }

/* Discovery runs section */
.discovery-runs-section { margin-top: 12px; }
.section-title { font-size: 12px; text-transform: uppercase; color: #475467; cursor: pointer; user-select: none; margin-bottom: 6px; }
.discovery-runs-list { display: flex; flex-direction: column; gap: 4px; }
.discovery-run-item { display: flex; gap: 8px; align-items: center; padding: 6px 8px; border: 1px solid var(--line); border-radius: 4px; font-size: 12px; }
.run-mode { font-weight: 600; color: var(--accent); }
.run-id { font-family: Consolas, monospace; color: #475467; }
.run-status { font-size: 11px; padding: 1px 6px; border-radius: 10px; background: var(--chip); }
.run-status.planned { background: #fef9c3; color: #92400e; }
.run-status.running { background: #e0f2fe; color: #0369a1; }
.run-status.succeeded { background: #dcfce7; color: #15803d; }
.run-status.failed { background: #fee2e2; color: #991b1b; }
</style>
