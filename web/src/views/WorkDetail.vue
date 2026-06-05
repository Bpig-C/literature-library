<template>
  <div v-if="work">
    <div class="topbar">
      <router-link to="/works" class="back">← 返回文献列表</router-link>
    </div>
    <h1 :contenteditable="editing" @blur="e => work.title = e.target.innerText" ref="titleEl">
      {{ work.title || work.id }}
    </h1>
    <div class="muted tiny">{{ work.id }}</div>

    <div class="section">
      <div class="section-header">
        <h3>元数据</h3>
        <button v-if="!editing" @click="startEdit">编辑</button>
        <template v-else>
          <button class="save" @click="saveEdit">保存</button>
          <button @click="cancelEdit">取消</button>
        </template>
        <template v-if="!editing">
          <button v-if="work.read_status !== 'quarantined'" class="quarantine-btn" @click="quarantine">隔离</button>
          <button v-else class="restore-btn" @click="restore">恢复</button>
        </template>
      </div>
      <div class="kv">
        <div>作者</div>
        <div>
          <template v-if="editing">
            <input v-model="editForm.authors_str" placeholder="用分号分隔" />
          </template>
          <template v-else>
            {{ (work.authors || []).join('; ') || '未知' }}
          </template>
        </div>
        <div>年份</div>
        <div>
          <input v-if="editing" v-model.number="editForm.year" type="number" />
          <span v-else>{{ work.year || '' }}</span>
        </div>
        <div>类型</div>
        <div>
          <select v-if="editing" v-model="editForm.doc_type">
            <option value="paper">paper</option>
            <option value="report">report</option>
            <option value="system_card">system_card</option>
            <option value="benchmark">benchmark</option>
            <option value="preprint">preprint</option>
          </select>
          <span v-else>{{ work.doc_type || '' }}</span>
        </div>
        <div>语言</div>
        <div>
          <select v-if="editing" v-model="editForm.language">
            <option value="en">en</option>
            <option value="zh">zh</option>
            <option value="unknown">unknown</option>
          </select>
          <span v-else>{{ work.language || '' }}</span>
        </div>
        <div>arXiv</div><div>{{ work.arxiv_id || '' }}</div>
        <div>DOI</div><div>{{ work.doi || '' }}</div>
        <div>解析状态</div><div :class="'status-' + work.parse_status">{{ work.parse_status }}</div>
        <div>阅读状态</div><div>
          <select v-if="editing" v-model="editForm.read_status">
            <option value="unread">unread</option>
            <option value="quarantined">quarantined</option>
          </select>
          <span v-else>{{ work.read_status }}</span>
        </div>
      </div>
    </div>

    <div class="section" v-if="work.source_files?.length">
      <h3>源文件 <span class="muted" style="font-weight:normal;text-transform:none">({{ uniqueShaCount }} 个有效 / {{ work.source_files.length }} 个原始)</span></h3>
      <div v-for="s in work.source_files" :key="s.id" class="file-item">
        <span class="file-name">{{ s.original_name || s.id }}</span>
        <span class="muted tiny">{{ (s.file_size / 1024).toFixed(0) }} KB</span>
        <span class="chip tiny" v-if="isDuplicateSha(s)">重复</span>
        <a :href="pdfUrl(work.id)" target="_blank" v-if="s.file_ext === '.pdf'">查看 PDF</a>
      </div>
    </div>

    <div class="section" v-if="work.relations?.length">
      <h3>关联文献</h3>
      <div v-for="r in work.relations" :key="r.work_id_a + r.work_id_b + r.relation_type" class="rel-item">
        <router-link :to="'/works/' + (r.work_id_a === work.id ? r.work_id_b : r.work_id_a)">
          {{ r.partner_title }}
        </router-link>
        <span class="chip">{{ r.relation_type }}</span>
        <button class="del" @click="removeRelation(r)">删除</button>
      </div>
    </div>

    <div class="section">
      <h3>添加关联</h3>
      <div class="add-rel">
        <input v-model="newRel.targetId" placeholder="目标 Work ID" />
        <select v-model="newRel.type">
          <option value="translation_of">translation_of</option>
          <option value="version_of">version_of</option>
          <option value="same_work">same_work</option>
          <option value="part_of">part_of</option>
          <option value="supersedes">supersedes</option>
          <option value="not_duplicate">not_duplicate</option>
        </select>
        <button @click="addRelation" :disabled="!newRel.targetId">添加</button>
      </div>
    </div>

    <div class="section" v-if="work.codes?.length">
      <h3>标签</h3>
      <span class="chip" v-for="c in work.codes" :key="c.code">{{ c.code }}: {{ c.reason }}</span>
    </div>

    <div class="section" v-if="work.duplicates?.length">
      <h3>重复候选</h3>
      <div v-for="d in work.duplicates" :key="d.id" class="muted tiny">
        {{ d.group_id }} · {{ d.reason }} · reviewed={{ d.reviewed }}
      </div>
    </div>

    <div class="section" v-if="content">
      <h3>内容预览</h3>
      <pre class="content-preview">{{ content }}</pre>
    </div>
  </div>
  <div v-else class="empty">加载中...</div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getWork, updateWork, createRelation, deleteRelation, quarantineWork, restoreWork, contentUrl, pdfUrl } from '../api'

const props = defineProps(['id'])

const work = ref(null)
const content = ref('')
const editing = ref(false)
const editForm = ref({})
const titleEl = ref(null)
const newRel = ref({ targetId: '', type: 'translation_of' })

const uniqueShaCount = computed(() => {
  if (!work.value?.source_files) return 0
  const shas = new Set(work.value.source_files.map(s => s.content_sha256).filter(Boolean))
  return shas.size
})

function isDuplicateSha(s) {
  if (!work.value?.source_files) return false
  const sameShaCount = work.value.source_files.filter(f => f.content_sha256 === s.content_sha256).length
  return sameShaCount > 1
}

async function loadWork() {
  work.value = await getWork(props.id)
  try {
    const res = await fetch(contentUrl(props.id))
    if (res.ok) content.value = await res.text()
  } catch {}
}

function startEdit() {
  editForm.value = {
    title: work.value.title,
    authors_str: (work.value.authors || []).join('; '),
    year: work.value.year,
    doc_type: work.value.doc_type,
    language: work.value.language,
    read_status: work.value.read_status,
  }
  editing.value = true
}

function cancelEdit() { editing.value = false }

async function saveEdit() {
  const data = { ...editForm.value }
  data.authors = data.authors_str.split(';').map(s => s.trim()).filter(Boolean)
  delete data.authors_str
  await updateWork(props.id, data)
  editing.value = false
  await loadWork()
}

async function addRelation() {
  if (!newRel.value.targetId) return
  await createRelation({
    work_id_a: props.id,
    work_id_b: newRel.value.targetId,
    relation_type: newRel.value.type,
  })
  newRel.value.targetId = ''
  await loadWork()
}

async function removeRelation(r) {
  await deleteRelation({
    work_id_a: r.work_id_a,
    work_id_b: r.work_id_b,
    relation_type: r.relation_type,
  })
  await loadWork()
}

async function quarantine() {
  const reason = prompt('隔离原因（可选）：')
  if (reason === null) return
  await quarantineWork(props.id, reason)
  await loadWork()
}

async function restore() {
  if (!confirm('确认恢复此文献？文件将移回 works 目录。')) return
  await restoreWork(props.id)
  await loadWork()
}

onMounted(loadWork)
</script>

<style scoped>
h1 { font-size: 20px; margin-bottom: 4px; outline: none; }
h1[contenteditable] { border-bottom: 2px solid var(--accent); padding-bottom: 2px; }
.topbar { margin-bottom: 12px; }
.back { font-size: 13px; }
.muted { color: var(--muted); }
.tiny { font-size: 12px; }
.section { margin-top: 20px; padding-top: 16px; border-top: 1px solid var(--line); }
.section h3 { font-size: 13px; text-transform: uppercase; color: #475467; margin-bottom: 8px; }
.section-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.section-header h3 { margin-bottom: 0; }
.kv { display: grid; grid-template-columns: 100px 1fr; gap: 6px 8px; font-size: 13px; }
.kv div:nth-child(odd) { color: var(--muted); }
.kv input, .kv select { height: 28px; border: 1px solid var(--line); border-radius: 4px; padding: 0 8px; font: inherit; }
button { height: 30px; padding: 0 12px; border: 1px solid var(--line); border-radius: 6px; background: #fff; cursor: pointer; font: inherit; }
button.save { background: var(--accent); color: #fff; border-color: var(--accent); }
button.quarantine-btn { color: var(--bad); border-color: var(--bad); }
button.restore-btn { color: var(--ok); border-color: var(--ok); }
button.del { font-size: 12px; color: var(--bad); border: none; background: none; padding: 0 4px; }
.chip { display: inline-block; padding: 2px 8px; border-radius: 999px; background: var(--chip); font-size: 12px; margin-left: 6px; }
.file-item { display: flex; align-items: center; gap: 10px; padding: 6px 0; border-bottom: 1px solid var(--line); }
.file-name { font-weight: 600; }
.rel-item { display: flex; align-items: center; gap: 8px; padding: 6px 0; }
.add-rel { display: flex; gap: 8px; align-items: center; }
.add-rel input, .add-rel select { height: 32px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; font: inherit; }
.content-preview { font-size: 12px; font-family: Consolas, monospace; background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 12px; max-height: 400px; overflow: auto; white-space: pre-wrap; word-break: break-word; }
.status-succeeded { color: var(--ok); font-weight: 600; }
.status-failed { color: var(--bad); font-weight: 600; }
.empty { padding: 28px; text-align: center; color: var(--muted); }
</style>
