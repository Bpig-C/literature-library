<template>
  <div>
    <h1>关系管理</h1>
    <div class="section">
      <h3>新增关系</h3>
      <div class="form-row">
        <input v-model="form.work_id_a" placeholder="Work ID A" />
        <select v-model="form.relation_type">
          <option value="translation_of">翻译版本</option>
          <option value="version_of">版本关系</option>
          <option value="same_work">同一作品</option>
          <option value="part_of">组成部分</option>
          <option value="supersedes">取代</option>
          <option value="not_duplicate">非重复</option>
        </select>
        <input v-model="form.work_id_b" placeholder="Work ID B" />
        <button @click="addRelation" :disabled="!form.work_id_a || !form.work_id_b">添加</button>
      </div>
    </div>
    <div class="count">{{ relations.length }} 条关系</div>
    <table v-if="relations.length">
      <thead>
        <tr>
          <th>A</th>
          <th></th>
          <th>B</th>
          <th>类型</th>
          <th>确认</th>
          <th>备注</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in relations" :key="r.work_id_a + r.work_id_b + r.relation_type">
          <td>
            <router-link :to="'/works/' + r.work_id_a">{{ r.work_id_a_title }}</router-link>
          </td>
          <td>→</td>
          <td>
            <router-link :to="'/works/' + r.work_id_b">{{ r.work_id_b_title }}</router-link>
          </td>
          <td><span class="chip">{{ label(RELATION_TYPE_LABELS, r.relation_type) }}</span></td>
          <td>{{ r.confirmed ? '✓' : '' }}</td>
          <td class="note">{{ r.note || '' }}</td>
          <td><button class="del" @click="remove(r)">删除</button></td>
        </tr>
      </tbody>
    </table>
    <EmptyState v-if="!relations.length" icon="data" title="暂无关系" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getRelations, createRelation, deleteRelation } from '../api'
import { RELATION_TYPE_LABELS, label } from '../labels'
import EmptyState from '../components/EmptyState.vue'

const relations = ref([])
const form = ref({ work_id_a: '', work_id_b: '', relation_type: 'translation_of' })

async function loadData() {
  const res = await getRelations()
  relations.value = res.relations
}

async function addRelation() {
  await createRelation(form.value)
  form.value = { work_id_a: '', work_id_b: '', relation_type: 'translation_of' }
  await loadData()
}

async function remove(r) {
  await deleteRelation({
    work_id_a: r.work_id_a,
    work_id_b: r.work_id_b,
    relation_type: r.relation_type,
  })
  await loadData()
}

onMounted(loadData)
</script>

<style scoped>
h1 { margin-bottom: 16px; font-size: 22px; }
.section { margin-bottom: 20px; }
.section h3 { font-size: 14px; color: var(--text-secondary); margin-bottom: 8px; }
.form-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.form-row input, .form-row select {
  height: 34px; border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 0 10px; font: inherit;
}
.form-row button { height: 34px; padding: 0 14px; background: var(--accent); color: #fff; border: none; border-radius: var(--radius-lg); cursor: pointer; font: inherit; }
.form-row button:disabled { opacity: 0.4; }
.count { font-size: 12px; color: var(--text-secondary); margin-bottom: 8px; }
table { width: 100%; border-collapse: collapse; background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); overflow: hidden; }
th, td { border-bottom: 1px solid var(--border); padding: 8px 10px; text-align: left; }
th { background: var(--bg-muted); font-size: 12px; color: var(--text-secondary); }
.chip { display: inline-block; padding: 2px 8px; border-radius: 999px; background: var(--bg-muted); font-size: 12px; }
.note { font-size: 12px; color: var(--text-secondary); max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.del { font-size: 12px; color: var(--bad); border: none; background: none; cursor: pointer; padding: 0 4px; }
.empty { padding: 28px; text-align: center; color: var(--text-secondary); background: var(--bg-surface); border: 1px solid var(--border); border-radius: 6px; }
</style>
