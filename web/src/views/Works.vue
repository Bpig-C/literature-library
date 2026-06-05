<template>
  <div>
    <h1>文献</h1>
    <div class="toolbar">
      <input v-model="search" type="search" placeholder="搜索标题、ID、arXiv..." @input="debouncedLoad" />
      <select v-model="statusFilter" @change="loadData">
        <option value="all">状态：全部</option>
        <option value="unread">未读</option>
        <option value="quarantined">已隔离</option>
      </select>
      <select v-model="typeFilter" @change="loadData">
        <option value="all">类型：全部</option>
        <option value="paper">paper</option>
        <option value="report">report</option>
        <option value="system_card">system_card</option>
        <option value="benchmark">benchmark</option>
        <option value="preprint">preprint</option>
      </select>
      <select v-model="langFilter" @change="loadData">
        <option value="all">语言：全部</option>
        <option value="en">en</option>
        <option value="zh">zh</option>
      </select>
    </div>
    <div class="count">{{ totalMatching }} / {{ total }} 篇文献</div>
    <div class="table-wrap" v-if="works.length">
      <table>
        <thead>
          <tr>
            <th>标题</th>
            <th>年份</th>
            <th>类型</th>
            <th>语言</th>
            <th>来源</th>
            <th>解析</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="w in works" :key="w.id" @click="$router.push('/works/' + w.id)">
            <td>
              <div class="title">{{ w.title || w.id }}</div>
              <div class="muted tiny">{{ w.id }}</div>
            </td>
            <td>{{ w.year || '' }}</td>
            <td>{{ w.doc_type || '' }}</td>
            <td>{{ w.language || '' }}</td>
            <td>
              <span v-if="w.total_source_count > w.source_count" :title="w.source_count + ' 个有效 / ' + (w.total_source_count - w.source_count) + ' 个已归档'">
                {{ w.unique_source_count }}<span class="muted">/{{ w.source_count }}</span>
              </span>
              <span v-else-if="w.source_count !== w.unique_source_count" :title="'去重后 ' + w.unique_source_count + ' 个'">
                {{ w.unique_source_count }}<span class="muted">/{{ w.source_count }}</span>
              </span>
              <span v-else>{{ w.source_count }}</span>
            </td>
            <td :class="'status-' + w.parse_status">{{ w.parse_status }}</td>
            <td :class="'status-' + w.read_status">{{ w.read_status }}</td>
            <td class="actions" @click.stop>
              <button v-if="w.read_status !== 'quarantined'" class="act-btn quarantine" @click="quarantine(w)">隔离</button>
              <button v-else class="act-btn restore" @click="restore(w)">恢复</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="empty" v-else>没有匹配的文献</div>
    <div class="pager" v-if="totalMatching > perPage">
      <button :disabled="page <= 1" @click="page--; loadData()">上一页</button>
      <span>{{ page }} / {{ Math.ceil(totalMatching / perPage) }}</span>
      <button :disabled="page >= Math.ceil(totalMatching / perPage)" @click="page++; loadData()">下一页</button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getWorks, quarantineWork, restoreWork } from '../api'

const works = ref([])
const total = ref(0)
const totalMatching = ref(0)
const page = ref(1)
const perPage = 50
const search = ref('')
const statusFilter = ref('all')
const typeFilter = ref('all')
const langFilter = ref('all')

let timer = null
function debouncedLoad() {
  clearTimeout(timer)
  timer = setTimeout(() => { page.value = 1; loadData() }, 300)
}

async function loadData() {
  const res = await getWorks({
    search: search.value,
    status: statusFilter.value,
    doc_type: typeFilter.value,
    language: langFilter.value,
    page: page.value,
    per_page: perPage,
  })
  works.value = res.works
  total.value = res.total
  totalMatching.value = res.total_matching
}

async function quarantine(w) {
  const reason = prompt('隔离原因（可选）：')
  if (reason === null) return
  await quarantineWork(w.id, reason)
  await loadData()
}

async function restore(w) {
  if (!confirm('确认恢复 ' + (w.title || w.id) + '？')) return
  await restoreWork(w.id)
  await loadData()
}

onMounted(loadData)
</script>

<style scoped>
h1 { margin-bottom: 12px; font-size: 22px; }
.toolbar {
  display: flex; gap: 8px; flex-wrap: wrap;
  margin-bottom: 10px;
}
.toolbar input, .toolbar select {
  height: 34px; border: 1px solid var(--line); border-radius: 6px;
  padding: 0 10px; font: inherit; background: #fff;
}
.count { font-size: 12px; color: var(--muted); margin-bottom: 8px; }
.table-wrap {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 6px;
  overflow: hidden;
}
table { width: 100%; border-collapse: collapse; }
th, td { border-bottom: 1px solid var(--line); padding: 8px 10px; text-align: left; vertical-align: top; }
th { background: #f1f4f8; font-size: 12px; color: #3a4250; position: sticky; top: 0; }
tr { cursor: pointer; }
tr:hover td { background: #eef5ff; }
.title { font-weight: 600; max-width: 500px; }
.muted { color: var(--muted); }
.tiny { font-size: 12px; }
.status-unread { color: var(--muted); }
.status-quarantined { color: var(--bad); font-weight: 600; }
.status-succeeded { color: var(--ok); }
.status-failed { color: var(--bad); }
.actions { white-space: nowrap; }
.act-btn { height: 26px; padding: 0 8px; border-radius: 4px; font-size: 12px; border: 1px solid var(--line); background: #fff; cursor: pointer; font: inherit; }
.act-btn.quarantine { color: var(--bad); border-color: var(--bad); }
.act-btn.restore { color: var(--ok); border-color: var(--ok); }
.empty { padding: 28px; text-align: center; color: var(--muted); background: var(--panel); border: 1px solid var(--line); border-radius: 6px; }
.pager { display: flex; justify-content: center; align-items: center; gap: 12px; margin-top: 12px; }
.pager button { height: 32px; padding: 0 12px; border: 1px solid var(--line); border-radius: 6px; background: #fff; cursor: pointer; font: inherit; }
.pager button:disabled { opacity: 0.4; cursor: default; }
</style>
