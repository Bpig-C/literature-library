<template>
  <div>
    <h1>关系管理</h1>
    <div class="section">
      <h3>新增关系</h3>
      <div class="form-row">
        <input v-model="form.work_id_a" placeholder="Work ID A" />
        <select v-model="form.relation_type">
          <option value="translation_of">translation_of</option>
          <option value="version_of">version_of</option>
          <option value="same_work">same_work</option>
          <option value="part_of">part_of</option>
          <option value="supersedes">supersedes</option>
          <option value="not_duplicate">not_duplicate</option>
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
          <td><span class="chip">{{ r.relation_type }}</span></td>
          <td>{{ r.confirmed ? '✓' : '' }}</td>
          <td class="note">{{ r.note || '' }}</td>
          <td><button class="del" @click="remove(r)">删除</button></td>
        </tr>
      </tbody>
    </table>
    <div class="empty" v-else>暂无关系</div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getRelations, createRelation, deleteRelation } from '../api'

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
.section h3 { font-size: 14px; color: var(--muted); margin-bottom: 8px; }
.form-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.form-row input, .form-row select {
  height: 34px; border: 1px solid var(--line); border-radius: 6px; padding: 0 10px; font: inherit;
}
.form-row button { height: 34px; padding: 0 14px; background: var(--accent); color: #fff; border: none; border-radius: 6px; cursor: pointer; font: inherit; }
.form-row button:disabled { opacity: 0.4; }
.count { font-size: 12px; color: var(--muted); margin-bottom: 8px; }
table { width: 100%; border-collapse: collapse; background: var(--panel); border: 1px solid var(--line); border-radius: 6px; overflow: hidden; }
th, td { border-bottom: 1px solid var(--line); padding: 8px 10px; text-align: left; }
th { background: #f1f4f8; font-size: 12px; color: #3a4250; }
.chip { display: inline-block; padding: 2px 8px; border-radius: 999px; background: var(--chip); font-size: 12px; }
.note { font-size: 12px; color: var(--muted); max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.del { font-size: 12px; color: var(--bad); border: none; background: none; cursor: pointer; padding: 0 4px; }
.empty { padding: 28px; text-align: center; color: var(--muted); background: var(--panel); border: 1px solid var(--line); border-radius: 6px; }
</style>
