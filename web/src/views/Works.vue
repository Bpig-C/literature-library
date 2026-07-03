<template>
  <div>
    <h1>文献</h1>
    <div class="toolbar">
      <n-input v-model:value="search" type="text" placeholder="搜索标题、ID、arXiv..." clearable @input="debouncedLoad" style="width: 240px" />
      <n-select v-model:value="statusFilter" :options="STATUS_OPTIONS" style="width: 120px" @update:value="resetAndLoad" />
      <n-select v-model:value="typeFilter" :options="DOC_TYPE_OPTIONS" style="width: 120px" @update:value="resetAndLoad" />
      <n-select v-model:value="langFilter" :options="LANG_OPTIONS" style="width: 100px" @update:value="resetAndLoad" />
      <n-select v-model:value="sortKey" :options="sortOptions" style="width: 120px" @update:value="resetAndLoad" />
      <n-button quaternary @click="toggleSortDir" :title="sortDir === 'desc' ? '降序（最新在前）' : '升序（最旧在前）'">
        {{ sortDir === 'desc' ? '↓ 新→旧' : '↑ 旧→新' }}
      </n-button>
      <n-button quaternary :type="showAdvanced ? 'primary' : 'default'" @click="showAdvanced = !showAdvanced">
        {{ showAdvanced ? '收起筛选' : '高级筛选' }}
      </n-button>
    </div>

    <div class="advanced-filters" v-if="showAdvanced">
      <div class="classified-bar">
        <n-switch v-model:value="classifiedOnly" @update:value="resetAndLoad" />
        <span class="classified-label">仅已分类</span>
        <n-tag v-if="classifiedOnly" type="success" size="small" round>{{ totalMatching }} 篇</n-tag>
        <n-divider vertical />
        <span class="filter-hint">多选筛选为 OR 逻辑（匹配任意一个）</span>
      </div>

      <div class="filter-grid">
        <div class="filter-item">
          <label>主文档类型</label>
          <n-select v-model:value="primaryDocTypeFilter" :options="PRIMARY_DOC_TYPE_OPTIONS" clearable placeholder="全部" @update:value="resetAndLoad" />
        </div>
        <div class="filter-item">
          <label>发布状态</label>
          <n-select v-model:value="publicationStatusFilter" :options="PUBLICATION_STATUS_OPTIONS" clearable placeholder="全部" @update:value="resetAndLoad" />
        </div>
        <div class="filter-item">
          <label>入库状态</label>
          <n-select v-model:value="ingestionStateFilter" :options="INGESTION_STATE_OPTIONS" clearable placeholder="全部" @update:value="resetAndLoad" />
        </div>
        <div class="filter-item">
          <label>优先级</label>
          <n-select v-model:value="priorityFilter" :options="PRIORITY_OPTIONS" clearable placeholder="全部" @update:value="resetAndLoad" />
        </div>
        <div class="filter-item wide">
          <label>阅读用途</label>
          <n-select v-model:value="readingLaneFilter" :options="READING_LANE_OPTIONS" multiple filterable clearable placeholder="全部" @update:value="resetAndLoad" />
        </div>
        <div class="filter-item wide">
          <label>风险领域</label>
          <n-select v-model:value="riskDomainFilter" :options="RISK_DOMAIN_OPTIONS" multiple filterable clearable placeholder="全部" @update:value="resetAndLoad" />
        </div>
        <div class="filter-item wide">
          <label>关注对象</label>
          <n-select v-model:value="artifactFocusFilter" :options="ARTIFACT_FOCUS_OPTIONS" multiple filterable clearable placeholder="全部" @update:value="resetAndLoad" />
        </div>
      </div>
    </div>

    <div class="count">{{ totalMatching }} / {{ total }} 篇文献</div>

    <div class="table-wrap" v-if="works.length">
      <table>
        <thead>
          <tr>
            <th>标题</th>
            <th>日期</th>
            <th>主类型</th>
            <th>语言</th>
            <th>来源</th>
            <th>解析</th>
            <th>入库</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="w in works" :key="w.id" @click="goToWork(w.id)">
            <td>
              <div class="title">{{ w.title || w.id }}</div>
              <div class="muted tiny">{{ w.id }}</div>
            </td>
            <td>{{ formatDate(w) }}</td>
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
              <n-button v-if="w.read_status !== 'quarantined'" text type="error" size="small" @click="quarantine(w)">隔离</n-button>
              <n-button v-else text type="success" size="small" @click="restore(w)">恢复</n-button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <EmptyState v-else icon="search" title="没有匹配的文献" description="尝试调整筛选条件" />
    <n-pagination v-if="totalMatching > perPage" v-model:page="page" :page-count="matchingTotalPages" @update:page="loadData()" />

    <!-- Quarantine Modal -->
    <n-modal v-model:show="showQuarantineModal" preset="card" title="隔离文献" style="width: 420px">
      <p class="modal-desc">确定要隔离「{{ quarantineTarget?.title || quarantineTarget?.id }}」吗？</p>
      <n-input v-model:value="quarantineReason" placeholder="隔离原因（可选）" />
      <template #action>
        <n-button @click="showQuarantineModal = false">取消</n-button>
        <n-button type="error" :loading="quarantineLoading" @click="confirmQuarantine">确认隔离</n-button>
      </template>
    </n-modal>
  </div>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage, useDialog } from 'naive-ui'
import { usePagination } from '../composables/usePagination'
import { getWorks, quarantineWork, restoreWork } from '../api'
import { DOC_TYPE_LABELS, PRIMARY_DOC_TYPE_LABELS, LANGUAGE_LABELS, PARSE_STATUS_LABELS, READ_STATUS_LABELS, INGESTION_STATE_LABELS, label } from '../labels'
import EmptyState from '../components/EmptyState.vue'

const router = useRouter()
const message = useMessage()
const dialog = useDialog()

// --- Options ---
const STATUS_OPTIONS = [
  { label: '状态：全部', value: 'all' },
  { label: '未读', value: 'unread' },
  { label: '已隔离', value: 'quarantined' },
]
const DOC_TYPE_OPTIONS = [
  { label: '类型：全部', value: 'all' },
  { label: '论文', value: 'paper' },
  { label: '报告', value: 'report' },
  { label: '系统卡', value: 'system_card' },
  { label: '基准测试', value: 'benchmark' },
  { label: '预印本', value: 'preprint' },
]
const LANG_OPTIONS = [
  { label: '语言：全部', value: 'all' },
  { label: '英文', value: 'en' },
  { label: '中文', value: 'zh' },
]
const PRIMARY_DOC_TYPE_OPTIONS = [
  { type: 'group', label: '功能定位类型（优先）', children: [
    { label: '系统卡/模型卡', value: 'system_model_card' },
    { label: '治理框架', value: 'governance_framework' },
    { label: '标准/指南', value: 'standard_guideline' },
    { label: '基准/数据集论文', value: 'benchmark_dataset_paper' },
    { label: '第三方评估报告', value: 'evaluation_report' },
  ]},
  { type: 'group', label: '文档形态类型', children: [
    { label: '技术报告', value: 'technical_report' },
    { label: '机构报告', value: 'institutional_report' },
    { label: '研究论文', value: 'research_article' },
    { label: '综述/评述', value: 'survey_review' },
    { label: '平台快照', value: 'platform_snapshot' },
    { label: '学位论文', value: 'thesis' },
    { label: '书章', value: 'book_chapter' },
    { label: '网页/博客', value: 'webpage_blog' },
    { label: '其他', value: 'other_literature' },
  ]},
  { type: 'group', label: '存在性标记', children: [
    { label: '工作流产物', value: 'workflow_artifact' },
    { label: '非文献', value: 'not_literature' },
  ]},
]
const PUBLICATION_STATUS_OPTIONS = [
  { label: '已发表', value: 'published' },
  { label: '预印本', value: 'preprint' },
  { label: '工作论文', value: 'working_paper' },
  { label: '草案', value: 'draft' },
  { label: '持续更新文档', value: 'living_document' },
  { label: '机构正式发布', value: 'institutional_release' },
  { label: '网页发布', value: 'webpage_release' },
  { label: '未知', value: 'unknown' },
]
const INGESTION_STATE_OPTIONS = [
  { label: '已核验', value: 'verified' },
  { label: '待核查', value: 'needs_review' },
  { label: '暂留', value: 'provisional' },
  { label: '已排除', value: 'excluded' },
  { label: '已废弃', value: 'deprecated' },
]
const PRIORITY_OPTIONS = [
  { label: '核心必读 (P0)', value: 'P0' },
  { label: '重要 (P1)', value: 'P1' },
  { label: '参考 (P2)', value: 'P2' },
  { label: '边缘 (P3)', value: 'P3' },
  { label: '归档', value: 'archive' },
]
const READING_LANE_OPTIONS = [
  { label: '框架与分类', value: 'framework_taxonomy' },
  { label: '评测方法', value: 'evaluation_method' },
  { label: '治理方法', value: 'governance_method' },
  { label: '系统透明度', value: 'system_transparency' },
  { label: '模型技术特征', value: 'model_technical_profile' },
  { label: '机构生态', value: 'institutional_landscape' },
  { label: '安全论证', value: 'safety_case_method' },
  { label: '可解释性', value: 'interpretability_method' },
  { label: '理论背景', value: 'background_theory' },
  { label: '文献综述', value: 'literature_mapping' },
  { label: '工作流支持', value: 'workflow_support' },
]
const RISK_DOMAIN_OPTIONS = [
  { label: '越狱抵抗', value: 'jailbreak_resistance' },
  { label: '自我保护', value: 'self_preservation' },
  { label: '欺骗', value: 'deception' },
  { label: '策略性欺骗', value: 'scheming' },
  { label: '能力隐藏', value: 'sandbagging' },
  { label: '评测意识', value: 'evaluation_awareness' },
  { label: '信息遮蔽', value: 'information_concealment' },
  { label: '影响操纵', value: 'persuasion' },
  { label: '错误信息', value: 'misinformation' },
  { label: '自主性', value: 'autonomy' },
  { label: '自复制', value: 'self_replication' },
  { label: '资源获取', value: 'resource_acquisition' },
  { label: '目标守护', value: 'goal_preservation' },
  { label: '隐蔽行动', value: 'covert_action' },
  { label: '监控规避', value: 'oversight_subversion' },
  { label: '自主AI研发', value: 'autonomous_ai_rnd' },
  { label: '多智能体串谋', value: 'multi_agent_collusion' },
  { label: '破坏行为', value: 'sabotage' },
  { label: '权力寻求', value: 'power_seeking' },
  { label: '网络攻击', value: 'cyber_offense' },
  { label: '网络安全', value: 'cybersecurity' },
  { label: '生物安全', value: 'biosecurity' },
  { label: '化学安全', value: 'chemical_security' },
  { label: '双重用途', value: 'dual_use' },
  { label: '奖励黑客', value: 'reward_hacking' },
  { label: '自主复制', value: 'autonomous_replication' },
  { label: '系统性风险', value: 'systemic_risk' },
  { label: '分布性风险', value: 'distributional_risk' },
  { label: '生物风险', value: 'bio_risk' },
  { label: '对齐税', value: 'alignment_tax' },
  { label: '灾难性风险', value: 'catastrophic_risk' },
  { label: '滥用', value: 'misuse' },
  { label: '治理失效', value: 'governance_risk' },
  { label: '模型行为', value: 'model_behavior' },
  { label: '隐私', value: 'privacy' },
  { label: '公平性', value: 'fairness' },
  { label: '鲁棒性', value: 'robustness' },
  { label: '安全论证有效性', value: 'safety_case_validity' },
  { label: '未知', value: 'unknown' },
]
const ARTIFACT_FOCUS_OPTIONS = [
  { label: '审计发现', value: 'audit_finding' },
  { label: '基准测试', value: 'benchmark' },
  { label: '能力画像', value: 'capability_profile' },
  { label: '数据集', value: 'dataset' },
  { label: '实证发现', value: 'empirical_finding' },
  { label: '评测套件', value: 'eval_suite' },
  { label: '评测套件', value: 'evaluation_suite' },
  { label: '评测框架', value: 'evaluation_framework' },
  { label: '框架', value: 'framework' },
  { label: '框架提案', value: 'framework_proposal' },
  { label: '治理', value: 'governance' },
  { label: '指南', value: 'guideline' },
  { label: '模型', value: 'model' },
  { label: '模型卡', value: 'model_card' },
  { label: '系统卡', value: 'system_card' },
  { label: '分类法', value: 'taxonomy' },
  { label: '度量指标', value: 'metric' },
  { label: '政策分析', value: 'policy_analysis' },
  { label: '政策', value: 'policy' },
  { label: '风险评估', value: 'risk_assessment' },
  { label: '风险更新', value: 'risk_update' },
  { label: '风险管理', value: 'risk_management' },
  { label: '安全论证', value: 'safety_case_argument' },
  { label: '安全论证', value: 'safety_case' },
  { label: '安全报告', value: 'safety_report' },
  { label: '透明度报告', value: 'transparency_report' },
  { label: '透明度', value: 'transparency' },
  { label: '可解释性发现', value: 'interpretability_finding' },
  { label: '可解释性', value: 'interpretability' },
  { label: '可监控性', value: 'monitorability' },
  { label: '审计', value: 'audit' },
  { label: '红队测试', value: 'red_teaming' },
  { label: '标准', value: 'standard' },
  { label: '理论贡献', value: 'theoretical_contribution' },
  { label: '工具发布', value: 'tool_release' },
  { label: '排行榜', value: 'leaderboard' },
  { label: '平台', value: 'platform' },
  { label: '趋势', value: 'trend' },
  { label: '文献索引', value: 'literature_index' },
  { label: '工作流缓存', value: 'workflow_cache' },
]

// --- State ---
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

function resetAndLoad() {
  reset()
  loadData()
}

function toggleSortDir() {
  sortDir.value = sortDir.value === 'desc' ? 'asc' : 'desc'
  resetAndLoad()
}

function goToWork(id) {
  // Save current filter state for WorkDetail list panel to restore
  const filterState = {
    search: search.value,
    status: statusFilter.value,
    doc_type: typeFilter.value,
    language: langFilter.value,
    sort: sortKey.value,
    order: sortDir.value,
    primary_doc_type: primaryDocTypeFilter.value,
    publication_status: publicationStatusFilter.value,
    ingestion_state: ingestionStateFilter.value,
    priority: priorityFilter.value,
    classified_only: classifiedOnly.value,
    reading_lane: readingLaneFilter.value,
    risk_domain: riskDomainFilter.value,
    artifact_focus: artifactFocusFilter.value,
  }
  sessionStorage.setItem('works_filters', JSON.stringify(filterState))
  router.push('/works/' + id)
}

function formatDate(w) {
  try {
    const pdj = w.publication_date_json ? JSON.parse(w.publication_date_json) : null
    if (pdj && typeof pdj === 'object') {
      const parts = []
      if (pdj.year) parts.push(pdj.year)
      if (pdj.month) parts.push(String(pdj.month).padStart(2, '0'))
      if (pdj.day) parts.push(String(pdj.day).padStart(2, '0'))
      if (parts.length > 1) return parts.join('-')
      if (pdj.raw) return pdj.raw
    }
  } catch {}
  return w.year || ''
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

  const searchParams = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') {
      searchParams.append(key, value)
    }
  }
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
.page-title {
  font-size: var(--text-2xl);
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: var(--space-4);
}

.toolbar {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
  align-items: center;
  margin-bottom: var(--space-3);
}

.count {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  margin-bottom: var(--space-2);
}

.advanced-filters {
  background: var(--bg-muted);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--space-3);
}

.classified-bar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--border);
  margin-bottom: var(--space-3);
}

.classified-label {
  font-size: var(--text-base);
  color: var(--text-primary);
}

.filter-hint {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.filter-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: var(--space-3) var(--space-4);
}

.filter-item {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.filter-item.wide {
  grid-column: span 2;
}

@media (max-width: 900px) {
  .filter-item.wide {
    grid-column: span 1;
  }
}

.filter-item label {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  font-weight: 500;
}

.status-verified { color: var(--ok); }
.status-needs_review { color: var(--warn); }
.status-provisional { color: var(--neutral); }
.status-excluded { color: var(--bad); }
.status-deprecated { color: var(--text-tertiary); }

.table-wrap {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

table {
  width: 100%;
  border-collapse: collapse;
}

th, td {
  border-bottom: 1px solid var(--border);
  padding: var(--space-2) var(--space-3);
  text-align: left;
  vertical-align: top;
}

th {
  background: var(--bg-muted);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  position: sticky;
  top: 0;
}

tr {
  cursor: pointer;
}

tr:hover td {
  background: var(--accent-subtle);
}

.title {
  font-weight: 600;
  max-width: 500px;
  color: var(--text-primary);
}

.muted { color: var(--text-secondary); }
.tiny { font-size: var(--text-sm); }

.status-unread { color: var(--text-secondary); }
.status-quarantined { color: var(--bad); font-weight: 600; }
.status-succeeded { color: var(--ok); }
.status-failed { color: var(--bad); }

.actions { white-space: nowrap; }

.modal-desc {
  margin: 0 0 var(--space-4);
  font-size: var(--text-base);
  color: var(--text-secondary);
}
</style>
