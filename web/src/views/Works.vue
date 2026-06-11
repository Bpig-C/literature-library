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
        <option value="paper">论文</option>
        <option value="report">报告</option>
        <option value="system_card">系统卡</option>
        <option value="benchmark">基准测试</option>
        <option value="preprint">预印本</option>
      </select>
      <select v-model="langFilter" @change="loadData">
        <option value="all">语言：全部</option>
        <option value="en">英文</option>
        <option value="zh">中文</option>
      </select>
      <button class="toggle-advanced" @click="showAdvanced = !showAdvanced">
        {{ showAdvanced ? '收起筛选' : '高级筛选' }}
      </button>
    </div>
    <div class="advanced-filters" v-if="showAdvanced">
      <div class="filter-row">
        <label>主文档类型</label>
        <select v-model="primaryDocTypeFilter" @change="loadData">
          <option :value="null">全部</option>
          <optgroup label="机构自述类">
            <option value="system_model_card">系统卡/模型卡</option>
            <option value="technical_report">技术报告</option>
            <option value="governance_framework">治理框架</option>
          </optgroup>
          <optgroup label="评估类">
            <option value="evaluation_report">第三方评估报告</option>
            <option value="benchmark_dataset_paper">基准/数据集论文</option>
          </optgroup>
          <optgroup label="规范类">
            <option value="standard_guideline">标准/指南</option>
          </optgroup>
          <optgroup label="报告类">
            <option value="institutional_report">机构报告</option>
            <option value="platform_snapshot">平台快照</option>
          </optgroup>
          <optgroup label="学术类">
            <option value="research_article">研究论文</option>
            <option value="survey_review">综述/评述</option>
            <option value="thesis">学位论文</option>
          </optgroup>
          <optgroup label="网页类">
            <option value="webpage_blog">网页/博客</option>
          </optgroup>
          <optgroup label="管理类">
            <option value="workflow_artifact">工作流产物</option>
            <option value="not_literature">非文献</option>
            <option value="other_literature">其他</option>
          </optgroup>
        </select>
      </div>
      <div class="filter-row">
        <label>发布状态</label>
        <select v-model="publicationStatusFilter" @change="loadData">
          <option :value="null">全部</option>
          <option value="published">已发表</option>
          <option value="preprint">预印本</option>
          <option value="working_paper">工作论文</option>
          <option value="draft">草案</option>
          <option value="living_document">持续更新文档</option>
          <option value="institutional_release">机构正式发布</option>
          <option value="webpage_release">网页发布</option>
          <option value="unknown">未知</option>
        </select>
      </div>
      <div class="filter-row">
        <label>入库状态</label>
        <select v-model="ingestionStateFilter" @change="loadData">
          <option :value="null">全部</option>
          <option value="verified">已核验</option>
          <option value="needs_review">待核查</option>
          <option value="provisional">暂留</option>
          <option value="excluded">已排除</option>
          <option value="deprecated">已废弃</option>
        </select>
      </div>
      <div class="filter-row">
        <label>优先级</label>
        <select v-model="priorityFilter" @change="loadData">
          <option :value="null">全部</option>
          <option value="P0">核心必读</option>
          <option value="P1">重要</option>
          <option value="P2">参考</option>
          <option value="P3">边缘</option>
          <option value="archive">归档</option>
        </select>
      </div>
      <div class="filter-row">
        <label>阅读用途</label>
        <select v-model="readingLaneFilter" @change="loadData">
          <option :value="null">全部</option>
          <option value="framework_taxonomy">框架与分类</option>
          <option value="evaluation_method">评测方法</option>
          <option value="governance_method">治理方法</option>
          <option value="system_transparency">系统透明度</option>
          <option value="model_technical_profile">模型技术特征</option>
          <option value="institutional_landscape">机构生态</option>
          <option value="safety_case_method">安全论证</option>
          <option value="interpretability_method">可解释性</option>
          <option value="background_theory">理论背景</option>
          <option value="literature_mapping">文献综述</option>
          <option value="workflow_support">工作流支持</option>
        </select>
      </div>
    </div>
    <div class="count">{{ totalMatching }} / {{ total }} 篇文献</div>
    <div class="table-wrap" v-if="works.length">
      <table>
        <thead>
          <tr>
            <th>标题</th>
            <th>年份</th>
            <th>主类型</th>
            <th>语言</th>
            <th>来源</th>
            <th>解析</th>
            <th>入库</th>
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
            <td>{{ label(PRIMARY_DOC_TYPE_LABELS, w.primary_doc_type) || label(DOC_TYPE_LABELS, w.doc_type) }}</td>
            <td>{{ label(LANGUAGE_LABELS, w.language) }}</td>
            <td>
              <span v-if="w.total_source_count > w.source_count" :title="w.source_count + ' 个有效 / ' + (w.total_source_count - w.source_count) + ' 个已归档'">
                {{ w.unique_source_count }}<span class="muted">/{{ w.source_count }}</span>
              </span>
              <span v-else-if="w.source_count !== w.unique_source_count" :title="'去重后 ' + w.unique_source_count + ' 个'">
                {{ w.unique_source_count }}<span class="muted">/{{ w.source_count }}</span>
              </span>
              <span v-else>{{ w.source_count }}</span>
            </td>
            <td :class="'status-' + w.parse_status">{{ label(PARSE_STATUS_LABELS, w.parse_status) }}</td>
            <td :class="'status-' + w.ingestion_state">{{ label(INGESTION_STATE_LABELS, w.ingestion_state) }}</td>
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
import { DOC_TYPE_LABELS, PRIMARY_DOC_TYPE_LABELS, LANGUAGE_LABELS, PARSE_STATUS_LABELS, READ_STATUS_LABELS, INGESTION_STATE_LABELS, label } from '../labels'

const works = ref([])
const total = ref(0)
const totalMatching = ref(0)
const page = ref(1)
const perPage = 50
const search = ref('')
const statusFilter = ref('all')
const typeFilter = ref('all')
const langFilter = ref('all')
const showAdvanced = ref(false)
const primaryDocTypeFilter = ref(null)
const publicationStatusFilter = ref(null)
const ingestionStateFilter = ref(null)
const priorityFilter = ref(null)
const readingLaneFilter = ref(null)

let timer = null
function debouncedLoad() {
  clearTimeout(timer)
  timer = setTimeout(() => { page.value = 1; loadData() }, 300)
}

async function loadData() {
  const params = {
    search: search.value,
    status: statusFilter.value,
    doc_type: typeFilter.value,
    language: langFilter.value,
    page: page.value,
    per_page: perPage,
  }
  if (primaryDocTypeFilter.value) params.primary_doc_type = primaryDocTypeFilter.value
  if (publicationStatusFilter.value) params.publication_status = publicationStatusFilter.value
  if (ingestionStateFilter.value) params.ingestion_state = ingestionStateFilter.value
  if (priorityFilter.value) params.priority = priorityFilter.value
  if (readingLaneFilter.value) params.reading_lane = readingLaneFilter.value
  const res = await getWorks(params)
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
.toggle-advanced { height: 34px; padding: 0 12px; border-radius: 6px; border: 1px solid var(--line); background: #f8fafc; cursor: pointer; font: inherit; font-size: 13px; color: #4a5568; }
.toggle-advanced:hover { background: #eef2f7; }
.advanced-filters {
  display: flex; flex-wrap: wrap; gap: 10px; padding: 12px;
  background: #f8fafc; border: 1px solid var(--line); border-radius: 6px;
  margin-bottom: 10px;
}
.filter-row { display: flex; flex-direction: column; gap: 4px; }
.filter-row label { font-size: 11px; color: #6b7280; font-weight: 500; }
.filter-row select, .filter-row input { height: 30px; border: 1px solid var(--line); border-radius: 4px; padding: 0 8px; font: inherit; font-size: 12px; background: #fff; }
.status-verified { color: var(--ok); }
.status-needs_review { color: #d97706; }
.status-provisional { color: #6b7280; }
.status-excluded { color: var(--bad); }
.status-deprecated { color: #9ca3af; }
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
