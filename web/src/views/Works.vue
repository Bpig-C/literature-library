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
      <n-select v-model:value="sortKey" :options="sortOptions" style="width: 160px" @update:value="loadData" />
      <button class="sort-dir-btn" @click="toggleSortDir" :title="sortDir === 'desc' ? '降序（最新在前）' : '升序（最旧在前）'">
        {{ sortDir === 'desc' ? '↓ 新→旧' : '↑ 旧→新' }}
      </button>
      <button class="toggle-advanced" @click="showAdvanced = !showAdvanced">
        {{ showAdvanced ? '收起筛选' : '高级筛选' }}
      </button>
    </div>
    <div class="advanced-filters" v-if="showAdvanced">
      <div class="filter-row classified-toggle">
        <button :class="['toggle-btn', { active: classifiedOnly }]" @click="classifiedOnly = !classifiedOnly; loadData()">
          {{ classifiedOnly ? '✓ 已分类' : '已分类' }} {{ classifiedOnly ? totalMatching : '' }}
        </button>
        <button v-if="classifiedOnly" class="toggle-btn" @click="classifiedOnly = false; loadData()">显示全部</button>
      </div>
      <div class="filter-row">
        <label>主文档类型</label>
        <select v-model="primaryDocTypeFilter" @change="loadData">
          <option :value="null">全部</option>
          <optgroup label="功能定位类型（优先）">
            <option value="system_model_card">系统卡/模型卡 (system_model_card)</option>
            <option value="governance_framework">治理框架 (governance_framework)</option>
            <option value="standard_guideline">标准/指南 (standard_guideline)</option>
            <option value="benchmark_dataset_paper">基准/数据集论文 (benchmark_dataset_paper)</option>
            <option value="evaluation_report">第三方评估报告 (evaluation_report)</option>
          </optgroup>
          <optgroup label="文档形态类型">
            <option value="technical_report">技术报告 (technical_report)</option>
            <option value="institutional_report">机构报告 (institutional_report)</option>
            <option value="research_article">研究论文 (research_article)</option>
            <option value="survey_review">综述/评述 (survey_review)</option>
            <option value="platform_snapshot">平台快照 (platform_snapshot)</option>
            <option value="thesis">学位论文 (thesis)</option>
            <option value="book_chapter">书章 (book_chapter)</option>
            <option value="webpage_blog">网页/博客 (webpage_blog)</option>
            <option value="other_literature">其他 (other_literature)</option>
          </optgroup>
          <optgroup label="存在性标记">
            <option value="workflow_artifact">工作流产物 (workflow_artifact)</option>
            <option value="not_literature">非文献 (not_literature)</option>
          </optgroup>
        </select>
      </div>
      <div class="filter-row">
        <label>发布状态</label>
        <select v-model="publicationStatusFilter" @change="loadData">
          <option :value="null">全部</option>
          <option value="published">已发表 (published)</option>
          <option value="preprint">预印本 (preprint)</option>
          <option value="working_paper">工作论文 (working_paper)</option>
          <option value="draft">草案 (draft)</option>
          <option value="living_document">持续更新文档 (living_document)</option>
          <option value="institutional_release">机构正式发布 (institutional_release)</option>
          <option value="webpage_release">网页发布 (webpage_release)</option>
          <option value="unknown">未知 (unknown)</option>
        </select>
      </div>
      <div class="filter-row">
        <label>入库状态</label>
        <select v-model="ingestionStateFilter" @change="loadData">
          <option :value="null">全部</option>
          <option value="verified">已核验 (verified)</option>
          <option value="needs_review">待核查 (needs_review)</option>
          <option value="provisional">暂留 (provisional)</option>
          <option value="excluded">已排除 (excluded)</option>
          <option value="deprecated">已废弃 (deprecated)</option>
        </select>
      </div>
      <div class="filter-row">
        <label>优先级</label>
        <select v-model="priorityFilter" @change="loadData">
          <option :value="null">全部</option>
          <option value="P0">核心必读 (P0)</option>
          <option value="P1">重要 (P1)</option>
          <option value="P2">参考 (P2)</option>
          <option value="P3">边缘 (P3)</option>
          <option value="archive">归档 (archive)</option>
        </select>
      </div>
      <div class="filter-row">
        <label>阅读用途</label>
        <select v-model="readingLaneFilter" multiple @change="loadData">
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
      <div class="filter-row">
        <label>风险领域</label>
        <select v-model="riskDomainFilter" multiple @change="loadData">
          <option value="jailbreak_resistance">越狱抵抗</option>
          <option value="self_preservation">自我保护</option>
          <option value="deception_honesty">欺骗与诚实</option>
          <option value="power_seeking">权力寻求</option>
          <option value="oversight_evasion">监督规避</option>
          <option value="situational_awareness">情境感知</option>
          <option value="goal_misgeneralization">目标误泛化</option>
          <option value="value_alignment">价值对齐</option>
          <option value="multi_agent_safety">多智能体安全</option>
          <option value="other">其他</option>
        </select>
      </div>
      <div class="filter-row">
        <label>关注对象</label>
        <select v-model="artifactFocusFilter" multiple @change="loadData">
          <option value="audit_finding">审计发现</option>
          <option value="benchmark">基准测试</option>
          <option value="capability_profile">能力画像</option>
          <option value="dataset">数据集</option>
          <option value="empirical_finding">实证发现</option>
          <option value="eval_suite">评测套件</option>
          <option value="evaluation_framework">评测框架</option>
          <option value="framework">框架</option>
          <option value="framework_proposal">框架提案</option>
          <option value="governance">治理</option>
          <option value="guideline">指南</option>
          <option value="model">模型</option>
          <option value="model_card">模型卡</option>
          <option value="policy_analysis">政策分析</option>
          <option value="risk_assessment">风险评估</option>
          <option value="risk_management">风险管理</option>
          <option value="safety_case_argument">安全论证</option>
          <option value="safety_report">安全报告</option>
          <option value="standard">标准</option>
          <option value="theoretical_contribution">理论贡献</option>
          <option value="tool_release">工具发布</option>
          <option value="transparency">透明度</option>
          <option value="trend">趋势</option>
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
    <n-pagination v-if="totalMatching > perPage" v-model:page="page" :page-count="matchingTotalPages" @update:page="loadData()" />

    <!-- Quarantine Modal -->
    <div v-if="showQuarantineModal" class="modal-overlay" @click.self="showQuarantineModal = false">
      <div class="modal-box">
        <h3>隔离文献</h3>
        <p class="modal-desc">确定要隔离「{{ quarantineTarget?.title || quarantineTarget?.id }}」吗？</p>
        <div class="modal-reason">
          <label>隔离原因（可选）</label>
          <input v-model="quarantineReason" placeholder="例如：内容无关、404 页面..." />
        </div>
        <div class="modal-actions">
          <button class="btn-cancel" @click="showQuarantineModal = false">取消</button>
          <button class="btn-confirm" :disabled="quarantineLoading" @click="confirmQuarantine">
            {{ quarantineLoading ? '处理中...' : '确认隔离' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { useMessage, useDialog } from 'naive-ui'
import { usePagination } from '../composables/usePagination'
import { getWorks, quarantineWork, restoreWork } from '../api'
import { DOC_TYPE_LABELS, PRIMARY_DOC_TYPE_LABELS, LANGUAGE_LABELS, PARSE_STATUS_LABELS, READ_STATUS_LABELS, INGESTION_STATE_LABELS, label } from '../labels'

const message = useMessage()
const dialog = useDialog()

const works = ref([])
const { page, total, params: paginationParams, reset } = usePagination({ perPage: 50, mode: 'page' })
const totalMatching = ref(0)
const perPage = 50
const matchingTotalPages = computed(() => Math.ceil(totalMatching.value / perPage))
const search = ref('')
const statusFilter = ref('all')
const typeFilter = ref('all')
const langFilter = ref('all')
const showAdvanced = ref(false)
const primaryDocTypeFilter = ref(null)
const publicationStatusFilter = ref(null)
const ingestionStateFilter = ref(null)
const priorityFilter = ref(null)
const readingLaneFilter = ref([])
const riskDomainFilter = ref([])
const artifactFocusFilter = ref([])
const classifiedOnly = ref(false)
const sortKey = ref('created_at')
const sortDir = ref('desc')
const sortOptions = [
  { label: '入库时间', value: 'created_at' },
  { label: '年份', value: 'year' },
  { label: '标题', value: 'title' },
  { label: 'ID', value: 'id' },
]

const showQuarantineModal = ref(false)
const quarantineReason = ref('')
const quarantineLoading = ref(false)
const quarantineTarget = ref(null)

let timer = null
function debouncedLoad() {
  clearTimeout(timer)
  timer = setTimeout(() => { reset(); loadData() }, 300)
}

function toggleSortDir() {
  sortDir.value = sortDir.value === 'desc' ? 'asc' : 'desc'
  loadData()
}

async function loadData() {
  const params = {
    ...paginationParams.value,
    search: search.value,
    status: statusFilter.value,
    doc_type: typeFilter.value,
    language: langFilter.value,
    sort: sortKey.value,
    order: sortDir.value,
  }
  if (primaryDocTypeFilter.value) params.primary_doc_type = primaryDocTypeFilter.value
  if (publicationStatusFilter.value) params.publication_status = publicationStatusFilter.value
  if (ingestionStateFilter.value) params.ingestion_state = ingestionStateFilter.value
  if (priorityFilter.value) params.priority = priorityFilter.value
  if (classifiedOnly.value) params.classified_only = true

  // Build URLSearchParams manually to support array params
  const searchParams = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') {
      searchParams.append(key, value)
    }
  }
  // Multi-value tag filters
  for (const [key, values] of [
    ['reading_lane', readingLaneFilter.value],
    ['risk_domain', riskDomainFilter.value],
    ['artifact_focus', artifactFocusFilter.value],
  ]) {
    if (values && values.length > 0) {
      for (const v of values) {
        searchParams.append(key, v)
      }
    }
  }
  const q = searchParams.toString()
  const res = await getWorks(q ? '?' + q : '')
  works.value = res.works
  total.value = res.total
  totalMatching.value = res.total_matching
}

function quarantine(w) {
  quarantineTarget.value = w
  quarantineReason.value = ''
  quarantineLoading.value = false
  showQuarantineModal.value = true
}

async function confirmQuarantine() {
  if (!quarantineTarget.value || quarantineLoading.value) return
  quarantineLoading.value = true
  try {
    await quarantineWork(quarantineTarget.value.id, quarantineReason.value)
    showQuarantineModal.value = false
    await loadData()
    message.success('已隔离')
  } catch (e) {
    message.error('隔离失败: ' + (e.message || e))
  } finally {
    quarantineLoading.value = false
  }
}

function restore(w) {
  dialog.warning({
    title: '恢复文献',
    content: '确认恢复「' + (w.title || w.id) + '」？',
    positiveText: '恢复',
    negativeText: '取消',
    onPositiveClick: async () => {
      await restoreWork(w.id)
      await loadData()
      message.success('已恢复')
    },
  })
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
.sort-dir-btn { height: 34px; padding: 0 10px; border-radius: 6px; border: 1px solid var(--line); background: #f8fafc; cursor: pointer; font: inherit; font-size: 13px; color: #4a5568; white-space: nowrap; }
.sort-dir-btn:hover { background: #eef2f7; }
.advanced-filters {
  display: flex; flex-wrap: wrap; gap: 10px; padding: 12px;
  background: #f8fafc; border: 1px solid var(--line); border-radius: 6px;
  margin-bottom: 10px;
}
.classified-toggle {
  width: 100%; flex-direction: row; align-items: center; gap: 8px;
  padding-bottom: 8px; border-bottom: 1px solid var(--line); margin-bottom: 4px;
}
.toggle-btn {
  height: 30px; padding: 0 12px; border-radius: 4px; border: 1px solid var(--line);
  background: #fff; cursor: pointer; font: inherit; font-size: 12px; color: #4a5568;
}
.toggle-btn.active {
  background: var(--accent, #3b82f6); color: #fff; border-color: var(--accent, #3b82f6);
}
.filter-row { display: flex; flex-direction: column; gap: 4px; }
.filter-row label { font-size: 11px; color: #6b7280; font-weight: 500; }
.filter-row select, .filter-row input { height: 30px; border: 1px solid var(--line); border-radius: 4px; padding: 0 8px; font: inherit; font-size: 12px; background: #fff; }
.filter-row select[multiple] { height: auto; min-height: 60px; padding: 4px; }
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
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.modal-box { background: #fff; border-radius: 8px; padding: 24px; width: 420px; max-width: 90vw; box-shadow: 0 8px 32px rgba(0,0,0,0.18); }
.modal-box h3 { margin: 0 0 8px; font-size: 16px; }
.modal-desc { margin: 0 0 16px; font-size: 13px; color: #6b7280; }
.modal-reason label { display: block; font-size: 12px; color: #6b7280; margin-bottom: 4px; }
.modal-reason input { width: 100%; height: 34px; border: 1px solid var(--line); border-radius: 6px; padding: 0 10px; font: inherit; box-sizing: border-box; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.btn-cancel { height: 32px; padding: 0 14px; border: 1px solid var(--line); border-radius: 6px; background: #fff; cursor: pointer; font: inherit; font-size: 13px; }
.btn-confirm { height: 32px; padding: 0 14px; border: none; border-radius: 6px; background: var(--bad, #dc2626); color: #fff; cursor: pointer; font: inherit; font-size: 13px; }
.btn-confirm:disabled { opacity: 0.5; cursor: default; }
</style>
