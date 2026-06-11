<template>
  <div>
    <h1>总览</h1>
    <div class="stats" v-if="data">
      <div class="stat-card">
        <b>{{ data.total }}</b><span>文献总数</span>
      </div>
      <div class="stat-card">
        <b>{{ data.statuses?.unread || 0 }}</b><span>未读</span>
      </div>
      <div class="stat-card">
        <b>{{ data.statuses?.quarantined || 0 }}</b><span>已隔离</span>
      </div>
      <div class="stat-card">
        <b>{{ data.relations || 0 }}</b><span>关系</span>
      </div>
    </div>
    <div class="section" v-if="data">
      <h3>类型分布</h3>
      <div class="chips">
        <span class="chip" v-for="(count, type) in data.doc_types" :key="type">
          {{ label(DOC_TYPE_LABELS, type) }}: {{ count }}
        </span>
      </div>
    </div>
    <div class="section" v-if="data">
      <h3>语言分布</h3>
      <div class="chips">
        <span class="chip" v-for="(count, lang) in data.languages" :key="lang">
          {{ label(LANGUAGE_LABELS, lang) }}: {{ count }}
        </span>
      </div>
    </div>
    <div class="section">
      <h3>快捷入口</h3>
      <div class="quick-links">
        <router-link to="/works" class="link-card">
          <b>文献管理</b><span>搜索、筛选、编辑元数据</span>
        </router-link>
        <router-link to="/duplicates" class="link-card">
          <b>去重确认</b><span>审查重复候选组</span>
        </router-link>
        <router-link to="/relations" class="link-card">
          <b>关系管理</b><span>查看、新增、删除关联</span>
        </router-link>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getWorks } from '../api'
import { DOC_TYPE_LABELS, LANGUAGE_LABELS, label } from '../labels'

const data = ref(null)

onMounted(async () => {
  const res = await getWorks({ per_page: 1 })
  data.value = res.summary
})
</script>

<style scoped>
h1 { margin-bottom: 16px; font-size: 22px; }
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 10px;
  margin-bottom: 24px;
}
.stat-card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 12px 14px;
}
.stat-card b { display: block; font-size: 24px; }
.stat-card span { color: var(--muted); font-size: 12px; }
.section { margin-bottom: 20px; }
.section h3 { font-size: 14px; color: var(--muted); margin-bottom: 8px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  padding: 4px 10px;
  border-radius: 999px;
  background: var(--chip);
  font-size: 13px;
}
.quick-links { display: flex; gap: 12px; flex-wrap: wrap; }
.link-card {
  display: block; padding: 14px 18px; background: var(--panel); border: 1px solid var(--line);
  border-radius: 8px; text-decoration: none; color: inherit; min-width: 180px; transition: border-color .15s;
}
.link-card:hover { border-color: var(--accent); }
.link-card b { display: block; font-size: 14px; margin-bottom: 4px; }
.link-card span { font-size: 12px; color: var(--muted); }
</style>
