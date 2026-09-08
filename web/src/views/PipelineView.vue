<template>
  <div class="pipeline-layout" :class="{ 'with-pdf': showPdfDrawer }">
    <!-- 左侧：流程阶段列 -->
    <div class="pipeline-main">
    <h1 class="page-title">流程管理</h1>
    <p class="page-desc">选择性推进文献处理流水线</p>

    <!-- 发现检索审核 -->
    <StageCard
      icon="🔎"
      title="发现检索审核"
      description="审核发现检索命中的文献，接受或拒绝后进入采集审核"
      :count="stages.discovery.pendingCount"
      stat-label="待审命中"
      :secondary-count="stages.discovery.totalRuns"
      secondary-label="总运行数"
      action-label="前往审核"
      review-route="/discovery"
      :action-disabled="false"
      @execute="$router.push('/discovery')"
    >
      <template #default>
        <div v-if="stages.discovery.recentRuns.length" class="review-mini-list">
          <div
            v-for="run in stages.discovery.recentRuns"
            :key="run.id"
            class="review-mini-item"
            @click="$router.push({ path: '/discovery', query: { run_id: run.id } })"
          >
            <StatusBadge :status="run.status" size="small" />
            <span class="mini-title">{{ runSummary(run) }}</span>
            <span class="muted tiny">{{ run.created_at?.slice(0, 10) }}</span>
          </div>
        </div>
        <EmptyState v-else icon="data" title="暂无检索运行记录" />
      </template>
    </StageCard>

    <div class="stage-arrow">↓</div>

    <!-- 采集审核 -->
    <StageCard
      icon="✅"
      title="采集审核"
      description="审核候选文献是否纳入正式库（来源：发现检索接受 / 主题闸门采集 / 手动上传）"
      :count="stages.intakeReview.pendingCount"
      stat-label="待审"
      :secondary-count="stages.intakeReview.approvedCount"
      secondary-label="已批准待晋升"
      action-label="前往审核"
      review-route="/intake"
      :action-disabled="false"
      @execute="$router.push('/intake')"
    >
      <template #default>
        <div v-if="stages.intakeReview.recentCandidates.length" class="review-mini-list">
          <div
            v-for="c in stages.intakeReview.recentCandidates"
            :key="c.id"
            class="review-mini-item"
            @click="$router.push({ path: '/intake', query: { selected: c.id } })"
          >
            <StatusBadge :status="c.review_status" size="small" />
            <span class="mini-title">{{ c.title || c.arxiv_id || c.id }}</span>
            <span class="mini-source muted tiny">{{ c.source_type }}</span>
          </div>
        </div>
        <EmptyState v-else icon="inbox" title="暂无待审候选" description="通过发现检索或主题闸门采集文献后在此显示" />
      </template>
    </StageCard>

    <div class="stage-arrow">↓</div>

    <!-- 收件箱摄入 -->
    <StageCard
      icon="📥"
      title="收件箱摄入"
      description="摄入 _inbox/ 中的文件到文献库（PDF 放入 _inbox 后可在此或收件箱页扫描）"
      :count="stages.ingest.count"
      stat-label="待摄入"
      action-label="摄入选中"
      :selected-count="stages.ingest.selectedIds.size"
      :loading="stages.ingest.loading"
      @execute="batchIngest"
    >
      <template #filters>
        <router-link to="/inbox" class="goto-upload" target="_blank">
          前往 收件箱 页面（扫描 / 确认摄入）→
        </router-link>
        <input
          v-model="stages.ingest.filter"
          placeholder="搜索文件名..."
          class="filter-input"
        />
        <select v-model="stages.ingest.sortBy" class="filter-select">
          <option value="name">按名称</option>
          <option value="size">按大小</option>
          <option value="time">按时间</option>
        </select>
      </template>

      <SelectableFileList
        :items="filteredIngestFiles"
        :selected-ids="stages.ingest.selectedIds"
        :loading="stages.ingest.loading"
        :page="stages.ingest.page"
        :page-size="20"
        @update:selected="stages.ingest.selectedIds = $event"
        @update:page="stages.ingest.page = $event"
      >
        <template #item="{ item }">
          <span class="file-name">{{ item.filename }}</span>
          <span class="file-meta">{{ formatSize(item.size) }}</span>
          <span class="file-meta">{{ formatDate(item.modified_at) }}</span>
          <button class="btn-preview" @click.stop="handlePreview(item.work_id || item.id, item.filename)">预览</button>
        </template>
      </SelectableFileList>
    </StageCard>

    <div class="stage-arrow">↓</div>

    <!-- 文档解析 -->
    <StageCard
      icon="📄"
      title="文档解析"
      description="使用 MinerU 将 PDF 转换为可读文本"
      :count="stages.parse.count"
      stat-label="待解析"
      action-label="解析选中"
      :selected-count="stages.parse.selectedIds.size"
      :loading="stages.parse.loading"
      :action-disabled="stages.parse.statusFilter !== 'pending'"
      @execute="batchParse"
    >
      <template #stats>
        <span v-if="stages.parse.running > 0" class="stat-badge running">
          解析中: {{ stages.parse.running }}
        </span>
      </template>

      <template #filters>
        <div class="filter-tags">
          <button
            v-for="s in parseStatuses"
            :key="s.key"
            class="tag-btn"
            :class="{ active: stages.parse.statusFilter === s.key }"
            @click="stages.parse.statusFilter = s.key; stages.parse.selectedIds = new Set()"
          >
            {{ s.label }}
          </button>
        </div>
        <input
          v-model="stages.parse.filter"
          placeholder="搜索标题..."
          class="filter-input"
        />
      </template>

      <SelectableFileList
        :items="filteredParseFiles"
        :selected-ids="stages.parse.selectedIds"
        :loading="stages.parse.loading"
        :page="stages.parse.page"
        :page-size="20"
        :selectable="stages.parse.statusFilter === 'pending'"
        @update:selected="stages.parse.selectedIds = $event"
        @update:page="stages.parse.page = $event"
      >
        <template #item="{ item }">
          <StatusBadge :status="item.status" size="small" />
          <span class="file-name">{{ item.title || item.work_id }}</span>
          <span class="file-meta">{{ formatDate(item.created_at) }}</span>
          <button class="btn-preview" @click.stop="handlePreview(item.work_id || item.id, item.title || item.work_id)">预览</button>
          <button v-if="stages.parse.statusFilter === 'pending'" class="btn-quarantine-row" @click.stop="openQuarantine(item.work_id || item.id)">隔离</button>
        </template>
      </SelectableFileList>
    </StageCard>

    <div class="stage-arrow">↓</div>

    <!-- 元数据抽取 -->
    <StageCard
      icon="🏷️"
      title="元数据抽取"
      description="使用 LLM 从文本中提取标题、作者、摘要等元数据"
      :count="stages.metadata.count"
      stat-label="待抽取"
      :secondary-count="stages.metadata.pendingReview"
      secondary-label="待审核"
      action-label="抽取选中"
      review-route="/metadata"
      :selected-count="stages.metadata.selectedIds.size"
      :loading="stages.metadata.loading"
      :action-disabled="stages.metadata.statusFilter !== 'extract'"
      @execute="batchMetadata"
    >
      <template #filters>
        <div class="filter-tags">
          <button
            v-for="s in metadataStatuses"
            :key="s.key"
            class="tag-btn"
            :class="{ active: stages.metadata.statusFilter === s.key }"
            @click="stages.metadata.statusFilter = s.key; stages.metadata.selectedIds = new Set(); loadMetadata()"
          >
            {{ s.label }}
          </button>
        </div>
        <input
          v-model="stages.metadata.filter"
          placeholder="搜索标题..."
          class="filter-input"
        />
      </template>

      <SelectableFileList
        :items="filteredMetadataItems"
        :selected-ids="stages.metadata.selectedIds"
        :loading="stages.metadata.loading"
        :page="stages.metadata.page"
        :page-size="20"
        :selectable="stages.metadata.statusFilter === 'extract'"
        @update:selected="stages.metadata.selectedIds = $event"
        @update:page="stages.metadata.page = $event"
      >
        <template #item="{ item }">
          <!-- 待抽取模式：显示解析状态 + 标题 -->
          <template v-if="item._source === 'extract'">
            <StatusBadge status="pending" size="small" />
            <span class="file-name">{{ item.display_title }}</span>
            <span class="file-meta">解析完成</span>
            <span class="file-meta">{{ formatDate(item.created_at) }}</span>
            <button class="btn-preview" @click.stop="handlePreview(item.work_id || item.id, item.display_title)">预览</button>
            <button class="btn-quarantine-row" @click.stop="openQuarantine(item.work_id || item.id)">隔离</button>
          </template>
          <!-- 审核模式：显示审核状态、标题和时间 -->
          <template v-else>
            <StatusBadge :status="item.status" size="small" />
            <span class="file-name">{{ item.display_title }}</span>
            <span class="file-meta">{{ formatDate(item.created_at) }}</span>
            <button class="btn-preview" @click.stop="handlePreview(item.work_id || item.id, item.display_title)">预览</button>
          </template>
        </template>
      </SelectableFileList>
    </StageCard>

    <div class="stage-arrow">↓</div>

    <!-- 分类抽取 -->
    <StageCard
      icon="📋"
      title="分类抽取"
      description="使用 LLM 从文本中提取研究领域、方法标签等分类信息"
      :count="stages.classify.count"
      stat-label="待抽取"
      :secondary-count="stages.classify.pendingReview"
      secondary-label="待审核"
      action-label="抽取选中"
      review-route="/classification"
      :selected-count="stages.classify.selectedIds.size"
      :loading="stages.classify.loading"
      :action-disabled="stages.classify.statusFilter !== 'extract'"
      @execute="batchClassify"
    >
      <!-- 分类前置条件提示（告知，非阻断）：有已解析未批准元数据积压时提醒 -->
      <template #notice>
        <div v-if="stages.classify.metaUnapproved > 0" class="stage-notice">
          ⚠ 建议先完成元数据审核（还有 {{ stages.classify.metaUnapproved }} 篇已解析未批准元数据）
        </div>
      </template>
      <template #filters>
        <div class="filter-tags">
          <button
            v-for="s in classifyStatuses"
            :key="s.key"
            class="tag-btn"
            :class="{ active: stages.classify.statusFilter === s.key }"
            @click="stages.classify.statusFilter = s.key; stages.classify.selectedIds = new Set(); loadClassify()"
          >
            {{ s.label }}
          </button>
        </div>
        <div class="filter-tags">
          <button
            v-for="a in ambiguityLevels"
            :key="a.key"
            class="tag-btn"
            :class="{ active: stages.classify.ambiguityFilter === a.key }"
            @click="stages.classify.ambiguityFilter = a.key"
          >
            {{ a.label }}
          </button>
        </div>
        <input
          v-model="stages.classify.filter"
          placeholder="搜索标题..."
          class="filter-input"
        />
      </template>

      <SelectableFileList
        :items="filteredClassifyItems"
        :selected-ids="stages.classify.selectedIds"
        :loading="stages.classify.loading"
        :page="stages.classify.page"
        :page-size="20"
        :selectable="stages.classify.statusFilter === 'extract'"
        @update:selected="stages.classify.selectedIds = $event"
        @update:page="stages.classify.page = $event"
      >
        <template #item="{ item }">
          <!-- 待抽取模式 -->
          <template v-if="item._source === 'extract'">
            <StatusBadge status="pending" size="small" />
            <span class="file-name">{{ item.display_title }}</span>
            <span class="file-meta">元数据已批准</span>
            <span class="file-meta">{{ formatDate(item.created_at) }}</span>
            <button class="btn-preview" @click.stop="handlePreview(item.work_id || item.id, item.display_title)">预览</button>
            <button class="btn-quarantine-row" @click.stop="openQuarantine(item.work_id || item.id)">隔离</button>
          </template>
          <!-- 审核模式 -->
          <template v-else>
            <StatusBadge :status="item.status" size="small" />
            <span class="file-name">{{ item.display_title }}</span>
            <span class="amb-badge" :class="ambLevel(item.ambiguity_score)">
              {{ ambLabel(item.ambiguity_score) }}
            </span>
            <button class="btn-preview" @click.stop="handlePreview(item.work_id || item.id, item.display_title)">预览</button>
          </template>
        </template>
      </SelectableFileList>
    </StageCard>
    </div><!-- /pipeline-main -->

    <!-- 右侧：PDF 预览抽屉 -->
    <PdfPreviewDrawer
      v-if="showPdfDrawer"
      :url="activePdfUrl"
      :work-id="activePdfWorkId"
      :key="`${activePdfWorkId || 'none'}:${pdfPreviewKey}`"
      @close="closePdf"
    >
      <template #title>
        {{ previewTitle }}
        <router-link
          v-if="activePdfWorkId"
          :to="`/works/${activePdfWorkId}`"
          class="drawer-detail-link"
          @click.stop
        >
          查看详情 →
        </router-link>
      </template>
      <template #extra>
        <button class="btn-quarantine-drawer" @click="openQuarantine(activePdfWorkId)">
          隔离此文献
        </button>
      </template>
    </PdfPreviewDrawer>

    <!-- 确认对话框（覆盖层，放在最外层） -->
    <ConfirmDialog
      v-model:show="confirm.show"
      :title="confirm.title"
      :message="confirm.message"
      type="info"
      @confirm="confirm.action?.()"
    />

    <!-- 隔离弹窗 -->
    <div v-if="showQuarantineModal" class="quarantine-overlay" @click.self="closeQuarantine">
      <div class="quarantine-modal">
        <h3>隔离文献</h3>
        <p>该文献将从所有流程阶段中移除（标记为 quarantined），不会影响其他文献。</p>

        <label class="q-label">选择隔离原因：</label>
        <div class="q-reasons">
          <label
            v-for="r in QUARANTINE_REASONS"
            :key="r.key"
            class="q-reason-item"
            :class="{ active: quarantineReason === r.key }"
          >
            <input
              type="radio"
              :value="r.key"
              v-model="quarantineReason"
            />
            {{ r.label }}
          </label>
        </div>

        <div class="q-actions">
          <button class="btn-cancel" @click="closeQuarantine">取消</button>
          <button
            class="btn-confirm-q"
            :disabled="!quarantineReason || quarantineLoading"
            @click="doQuarantine()"
          >
            {{ quarantineLoading ? '处理中...' : '确认隔离' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, defineAsyncComponent } from 'vue'
import {
  getIngestPlan,
  executeIngest,
  parseStatus,
  parseTrigger,
  getMetadataExtractions,
  triggerMetadataExtraction,
  getClassificationExtractions,
  triggerClassificationExtraction,
  getPipelineStats,
  getPendingMetadataWorks,
  getPendingClassifyWorks,
  quarantineWork,
  pdfUrl,
  getIntakeStats,
  getDiscoveryHits,
} from '../api'
import { showError } from '../error-handler'
import { formatSize, formatDate } from '../composables/useFormatUtils'
import { usePdfDrawer } from '../composables/usePdfDrawer'
import { useQuarantine } from '../composables/useQuarantine'
import { useNextStep } from '../composables/useNextStep'
import StageCard from '../components/StageCard.vue'
import SelectableFileList from '../components/SelectableFileList.vue'
import StatusBadge from '../components/StatusBadge.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'
const PdfPreviewDrawer = defineAsyncComponent(() => import('../components/PdfPreviewDrawer.vue'))

// 筛选选项
const parseStatuses = [
  { key: 'pending', label: '待解析' },
  { key: '', label: '全部' },
  { key: 'failed', label: '失败' },
  { key: 'running', label: '运行中' },
]

const metadataStatuses = [
  { key: 'extract', label: '待抽取' },
  { key: 'pending', label: '待审核' },
  { key: 'approved', label: '已批准' },
  { key: 'rejected', label: '已拒绝' },
  { key: '', label: '全部' },
]

const classifyStatuses = [
  { key: 'extract', label: '待抽取' },
  { key: 'pending', label: '待审核' },
  { key: 'approved', label: '已批准' },
  { key: 'rejected', label: '已拒绝' },
  { key: '', label: '全部' },
]

const ambiguityLevels = [
  { key: '', label: '全部模糊度' },
  { key: 'high', label: '高' },
  { key: 'medium', label: '中' },
  { key: 'low', label: '低' },
]

// 阶段状态
const stages = ref({
  discovery: {
    pendingCount: 0,
    totalRuns: 0,
    recentRuns: [],
    loading: false,
  },
  intakeReview: {
    pendingCount: 0,
    approvedCount: 0,
    rejectedCount: 0,
    recentCandidates: [],
    loading: false,
  },
  ingest: {
    count: 0,
    loading: false,
    files: [],
    selectedIds: new Set(),
    page: 1,
    filter: '',
    sortBy: 'name',
  },
  parse: {
    count: 0,
    running: 0,
    loading: false,
    files: [],
    selectedIds: new Set(),
    page: 1,
    filter: '',
    statusFilter: 'pending',
  },
  metadata: {
    count: 0,
    pendingReview: 0,
    loading: false,
    items: [],
    selectedIds: new Set(),
    page: 1,
    filter: '',
    statusFilter: 'extract',
  },
  classify: {
    count: 0,
    pendingReview: 0,
    metaUnapproved: 0,
    loading: false,
    items: [],
    selectedIds: new Set(),
    page: 1,
    filter: '',
    statusFilter: 'extract',
    ambiguityFilter: '',
  },
})

const confirm = ref({ show: false, title: '', message: '', action: null })

// 流程接力提示（阶段完成 → 下一步引导）
const { notifyNext } = useNextStep()

// PDF 预览抽屉
const { showPdfDrawer, activePdfWorkId, pdfPreviewKey, openPdf, closePdf } = usePdfDrawer()
const activePdfUrl = ref('')
// 当前预览的文件标题（用于抽屉显示）
const previewTitle = ref('')

function handlePreview(workId, title) {
  previewTitle.value = title || workId
  activePdfUrl.value = pdfUrl(workId)
  openPdf(workId)
}

// 快速隔离（从 Pipeline 直接隔离不相关的文献）
const {
  QUARANTINE_REASONS,
  showQuarantineModal,
  quarantineReason,
  quarantineLoading,
  openQuarantine,
  closeQuarantine,
  doQuarantine,
} = useQuarantine({
  type: 'work',
  onSuccess: () => loadAll(),
})

function showConfirm(title, message, action) {
  confirm.value = { show: true, title, message, action }
}

// 计算属性：筛选后的数据
const filteredIngestFiles = computed(() => {
  let files = stages.value.ingest.files
  if (stages.value.ingest.filter) {
    const q = stages.value.ingest.filter.toLowerCase()
    files = files.filter(f => f.filename.toLowerCase().includes(q))
  }
  const sortBy = stages.value.ingest.sortBy
  files = [...files].sort((a, b) => {
    if (sortBy === 'size') return (b.size || 0) - (a.size || 0)
    if (sortBy === 'time') return new Date(b.modified_at) - new Date(a.modified_at)
    return a.filename.localeCompare(b.filename)
  })
  return files
})

const filteredParseFiles = computed(() => {
  let files = stages.value.parse.files
  if (stages.value.parse.statusFilter) {
    files = files.filter(f => f.status === stages.value.parse.statusFilter)
  }
  if (stages.value.parse.filter) {
    const q = stages.value.parse.filter.toLowerCase()
    files = files.filter(f => (f.title || f.work_id).toLowerCase().includes(q))
  }
  return files
})

const filteredMetadataItems = computed(() => {
  let items = stages.value.metadata.items
  if (stages.value.metadata.filter) {
    const q = stages.value.metadata.filter.toLowerCase()
    items = items.filter(i => (i.display_title || '').toLowerCase().includes(q))
  }
  return items
})

const filteredClassifyItems = computed(() => {
  let items = stages.value.classify.items
  if (stages.value.classify.ambiguityFilter) {
    items = items.filter(i => ambLevel(i.ambiguity_score) === stages.value.classify.ambiguityFilter)
  }
  if (stages.value.classify.filter) {
    const q = stages.value.classify.filter.toLowerCase()
    items = items.filter(i => (i.display_title || '').toLowerCase().includes(q))
  }
  return items
})

// 模糊度工具
function ambLevel(score) {
  if (score >= 50) return 'high'
  if (score >= 20) return 'medium'
  return 'low'
}

function ambLabel(score) {
  const level = ambLevel(score)
  return level === 'high' ? '高' : level === 'medium' ? '中' : '低'
}

// 数据加载
async function loadAll() {
  await Promise.allSettled([
    loadDiscovery(),
    loadIntakeReview(),
    loadIngest(),
    loadParse(),
    loadMetadata(),
    loadClassify(),
  ])
}

async function loadDiscovery() {
  try {
    const res = await getDiscoveryHits({ verification_status: 'unverified', per_page: 1 })
    stages.value.discovery.pendingCount = res.total || 0
    // 获取总运行次数 + 最近 5 条运行记录用于内嵌列表
    const runsRes = await getDiscoveryRuns({ per_page: 5 })
    stages.value.discovery.totalRuns = runsRes.total || 0
    stages.value.discovery.recentRuns = runsRes.runs || []
  } catch (e) {
    console.error('Failed to load discovery stats:', e)
  }
}

async function loadIntakeReview() {
  try {
    const stats = await getIntakeStats()
    stages.value.intakeReview.pendingCount = stats.review?.pending || 0
    stages.value.intakeReview.approvedCount = stats.review?.approved || 0
    stages.value.intakeReview.rejectedCount = stats.review?.rejected || 0
    // 获取最近 5 条待审候选用于内嵌列表
    import('../api').then(async ({ getIntakeCandidates }) => {
      try {
        const cands = await getIntakeCandidates({ review_status: 'pending', per_page: 5, page: 1 })
        stages.value.intakeReview.recentCandidates = cands.candidates || []
      } catch (err) { /* 静默 */ }
    })
  } catch (e) {
    console.error('Failed to load intake review stats:', e)
  }
}

// 运行记录摘要（复用 DiscoveryReview 的逻辑）
function runSummary(run) {
  const input = run?.input_json || {}
  return input.name || input.title || input.known_url || input.url || run?.id || '—'
}

async function loadIngest() {
  try {
    const res = await getIngestPlan()
    stages.value.ingest.count = res.summary?.ingests || 0
    stages.value.ingest.files = res.files || res.ingests || []
  } catch (e) {
    console.error('Failed to load ingest:', e)
    showError(new Error(`收件箱加载失败: ${e.message}`))
  }
}

async function loadParse() {
  try {
    const res = await parseStatus()
    stages.value.parse.count = res.pending || 0
    stages.value.parse.running = res.running || 0
    stages.value.parse.files = res.pending_files || []
  } catch (e) {
    console.error('Failed to load parse:', e)
    showError(new Error(`解析状态加载失败: ${e.message}`))
  }
}

async function loadMetadata() {
  try {
    // 统一从 stats 接口获取准确的"待抽取"+"待审核"数量
    const stats = await getPipelineStats()
    stages.value.metadata.count = stats.metadata?.pending_extract || 0
    stages.value.metadata.pendingReview = stats.metadata?.pending_review || 0

    // 列表数据根据当前选中的标签决定
    if (stages.value.metadata.statusFilter === 'extract') {
      // 待抽取：查询 works 表中解析成功但无 metadata_extraction 记录的文件
      const res = await getPendingMetadataWorks({
        per_page: 100,
        page: stages.value.metadata.page,
      })
      // 统一为 work_id 字段供 SelectableFileList 选中使用
      stages.value.metadata.items = (res.items || []).map(item => ({
        ...item,
        _source: 'extract',       // 标记来源，用于模板区分显示
        id: item.work_id,         // SelectableFileList 用 id 做选中 key
        display_title: item.title || item.work_id,
      }))
    } else {
      // 审核模式：查 metadata_extractions 表（待审核/已批准/已拒绝/全部）
      const res = await getMetadataExtractions({
        status: stages.value.metadata.statusFilter || undefined,
        per_page: 100,
      })
      stages.value.metadata.items = (res.extractions || res.items || []).map(item => ({
        ...item,
        _source: 'review',
        id: item.work_id || item.id,
        display_title: item.work_title || item.work_id,
      }))
    }
  } catch (e) {
    console.error('Failed to load metadata:', e)
    showError(new Error(`元数据加载失败: ${e.message}`))
  }
}

async function loadClassify() {
  try {
    const stats = await getPipelineStats()
    stages.value.classify.count = stats.classification?.pending_extract || 0
    stages.value.classify.pendingReview = stats.classification?.pending_review || 0
    // 分类前置条件提示用：已解析但未批准元数据的积压数
    stages.value.classify.metaUnapproved = stats.backlog?.metadata_unapproved || 0

    if (stages.value.classify.statusFilter === 'extract') {
      // 待抽取：元数据已批准但无 classification_extraction 记录
      const res = await getPendingClassifyWorks({
        per_page: 100,
        page: stages.value.classify.page,
      })
      stages.value.classify.items = (res.items || []).map(item => ({
        ...item,
        _source: 'extract',
        id: item.work_id,
        display_title: item.title || item.work_id,
      }))
    } else {
      // 审核模式
      const res = await getClassificationExtractions({
        status: stages.value.classify.statusFilter || undefined,
        per_page: 100,
      })
      stages.value.classify.items = (res.extractions || res.items || []).map(item => ({
        ...item,
        _source: 'review',
        id: item.work_id || item.id,
        display_title: item.work_title || item.work_id,
      }))
    }
  } catch (e) {
    console.error('Failed to load classify:', e)
    showError(new Error(`分类加载失败: ${e.message}`))
  }
}

// 批量操作
async function batchIngest() {
  const ids = Array.from(stages.value.ingest.selectedIds)
  if (!ids.length) return
  showConfirm('批量摄入', `即将摄入选中的 ${ids.length} 个文件，确定继续？`, async () => {
    confirm.value.show = false
    stages.value.ingest.loading = true
    try {
      await executeIngest({ file_ids: ids })
      clearAllSelections()
      await loadAll()
      // 下一步（文档解析）就在本页下一阶段，接力提示不跳转
      notifyNext(`摄入完成：${ids.length} 个文件已入库，可以继续文档解析`, { label: '继续文档解析' })
    } catch (e) {
      showError(e)
    } finally {
      stages.value.ingest.loading = false
    }
  })
}

async function batchParse() {
  const ids = Array.from(stages.value.parse.selectedIds)
  if (!ids.length) return
  showConfirm('批量解析', `即将解析选中的 ${ids.length} 个文档，确定继续？`, async () => {
    confirm.value.show = false
    stages.value.parse.loading = true
    try {
      await parseTrigger({ work_ids: ids })
      clearAllSelections()
      await loadAll()
      // 下一步（元数据抽取）就在本页下一阶段，接力提示不跳转
      notifyNext('解析已触发，完成后可继续元数据抽取', { label: '继续元数据抽取' })
    } catch (e) {
      showError(e)
    } finally {
      stages.value.parse.loading = false
    }
  })
}

async function batchMetadata() {
  const ids = Array.from(stages.value.metadata.selectedIds)
  if (!ids.length) return
  showConfirm('批量元数据抽取', `即将对选中的 ${ids.length} 个文档进行元数据抽取，确定继续？`, async () => {
    confirm.value.show = false
    stages.value.metadata.loading = true
    try {
      // 后端 trigger 接受 work_ids 数组或 all_pending 布尔值
      await triggerMetadataExtraction({ work_ids: ids })
      clearAllSelections()
      await loadAll()
      notifyNext('元数据抽取已触发，完成后请前往审核', { label: '去元数据审核', to: '/metadata' })
    } catch (e) {
      showError(e)
    } finally {
      stages.value.metadata.loading = false
    }
  })
}

async function batchClassify() {
  const ids = Array.from(stages.value.classify.selectedIds)
  if (!ids.length) return
  showConfirm('批量分类抽取', `即将对选中的 ${ids.length} 个文档进行分类抽取，确定继续？`, async () => {
    confirm.value.show = false
    stages.value.classify.loading = true
    try {
      await triggerClassificationExtraction({ work_ids: ids })
      clearAllSelections()
      await loadAll()
      notifyNext('分类抽取已触发，完成后请前往审核', { label: '去分类审核', to: '/classification' })
    } catch (e) {
      showError(e)
    } finally {
      stages.value.classify.loading = false
    }
  })
}

/** 数据刷新后清理所有阶段的选中状态（TD-P3） */
function clearAllSelections() {
  stages.value.ingest.selectedIds = new Set()
  stages.value.parse.selectedIds = new Set()
  stages.value.metadata.selectedIds = new Set()
  stages.value.classify.selectedIds = new Set()
}

onMounted(loadAll)
</script>

<style scoped>
/* 外层容器：左右双栏 */
.pipeline-layout {
  display: flex;
  gap: 0;
  max-width: 100%;
  height: calc(100vh - 80px);
}

/* 左侧：流程阶段（可滚动） */
.pipeline-main {
  flex: 1 1 0;
  min-width: 0;
  overflow-y: auto;
  padding: var(--space-6);
  max-width: 860px;
}

/* 有 PDF 时左侧不撑满 */
.pipeline-layout.with-pdf .pipeline-main {
  flex: 1 1 55%;
}

.page-title {
  font-size: var(--text-2xl);
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: var(--space-2);
}

.page-desc {
  font-size: var(--text-md);
  color: var(--text-secondary);
  margin-bottom: var(--space-6);
}

.stage-arrow {
  text-align: center;
  font-size: 20px;
  color: var(--text-tertiary);
  padding: var(--space-3) 0;
}

/* 阶段卡头提示条（warn 色系，告知非阻断） */
.stage-notice {
  padding: var(--space-2) var(--space-5);
  font-size: var(--text-xs);
  background: var(--warn-bg);
  color: var(--warn-fg);
  border-bottom: 1px solid var(--warn);
}

/* 筛选组件 */
.filter-input {
  flex: 1;
  min-width: 150px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  background: var(--bg-surface);
  color: var(--text-primary);
}

.filter-input:focus {
  outline: none;
  border-color: var(--accent);
}

.goto-upload {
  display: inline-flex;
  align-items: center;
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-sm);
  color: var(--accent);
  border: 1px solid var(--accent);
  border-radius: var(--radius-md);
  background: var(--accent-subtle);
  text-decoration: none;
  white-space: nowrap;
  transition: all var(--transition-fast);
}
.goto-upload:hover {
  background: var(--accent);
  color: #fff;
  text-decoration: none;
}

/* 审核卡片跳转链接 */
.goto-link {
  font-size: var(--text-xs);
  color: var(--accent);
  text-decoration: none;
  white-space: nowrap;
}
.goto-link:hover {
  text-decoration: underline;
}

.intake-extra {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

/* 审核卡片内嵌列表 */
.review-mini-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 8px;
}
.review-mini-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background var(--transition-fast);
  font-size: var(--text-xs);
}
.review-mini-item:hover {
  background: var(--bg-muted);
}
.mini-title {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
  color: var(--text-primary);
}
.mini-source {
  flex-shrink: 0;
}

.filter-select {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  background: var(--bg-surface);
  color: var(--text-primary);
}

.filter-tags {
  display: flex;
  gap: var(--space-1);
  flex-wrap: wrap;
}

.tag-btn {
  padding: var(--space-1) var(--space-3);
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--bg-surface);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.tag-btn:hover {
  border-color: var(--accent-mute);
  color: var(--text-primary);
}

.tag-btn.active {
  background: var(--accent-subtle);
  border-color: var(--accent);
  color: var(--accent);
  font-weight: 500;
}

/* 文件行样式 */
.file-name {
  flex: 1;
  font-size: var(--text-sm);
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.file-meta {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  white-space: nowrap;
}


.stat-badge.running {
  background: var(--info-bg);
  color: var(--info-fg);
}

/* 模糊度 badge */
.amb-badge {
  padding: 1px 6px;
  border-radius: 999px;
  font-size: var(--text-xs);
  font-weight: 500;
}

.amb-badge.high {
  background: var(--bad-bg);
  color: var(--bad-fg);
}

.amb-badge.medium {
  background: var(--warn-bg);
  color: var(--warn-fg);
}

.amb-badge.low {
  background: var(--ok-bg);
  color: var(--ok-fg);
}

/* 预览按钮 */
.btn-preview {
  flex-shrink: 0;
  padding: 2px 10px;
  font-size: var(--text-xs);
  color: var(--accent);
  background: var(--accent-subtle);
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all var(--transition-fast);
}
.btn-preview:hover {
  background: var(--accent);
  color: #fff;
}

/* 行内隔离按钮 */
.btn-quarantine-row {
  flex-shrink: 0;
  padding: 2px 10px;
  font-size: var(--text-xs);
  color: var(--bad-fg, #993C1D);
  background: var(--bad-bg, #FAECE7);
  border: 1px solid var(--bad-border, #F0997B);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all var(--transition-fast);
}
.btn-quarantine-row:hover {
  filter: brightness(0.95);
}

/* PDF 抽屉内的链接和隔离按钮 */
.drawer-detail-link {
  font-size: var(--text-xs);
  color: var(--accent);
  text-decoration: none;
  margin-left: auto;
  white-space: nowrap;
}
.drawer-detail-link:hover {
  text-decoration: underline;
}

.btn-quarantine-drawer {
  padding: var(--space-1) var(--space-3);
  font-size: var(--text-sm);
  color: var(--bad-fg, #993C1D);
  background: var(--bad-bg, #FAECE7);
  border: 1px solid var(--bad-border, #F0997B);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-fast);
}
.btn-quarantine-drawer:hover {
  filter: brightness(0.95);
}

/* 隔离弹窗 */
.quarantine-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.quarantine-modal {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: var(--space-5);
  width: min(480px, 90vw);
  max-height: 80vh;
  overflow-y: auto;
  box-shadow: var(--shadow-lg, 0 8px 30px rgba(0,0,0,0.15));
}
.quarantine-modal h3 {
  margin: 0 0 var(--space-2);
  font-size: var(--text-lg);
  color: var(--text-primary);
}
.quarantine-modal > p {
  margin: 0 0 var(--space-4);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  line-height: 1.6;
}
.q-label {
  display: block;
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--text-primary);
  margin-bottom: var(--space-2);
}
.q-reasons {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-bottom: var(--space-5);
}
.q-reason-item {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-fast);
  font-size: var(--text-sm);
  color: var(--text-secondary);
}
.q-reason-item:hover {
  border-color: var(--accent-mute);
  background: var(--bg-muted);
}
.q-reason-item.active {
  border-color: var(--accent);
  background: var(--accent-subtle);
  color: var(--text-primary);
}
.q-reason-item input[type="radio"] {
  margin-top: 3px;
  accent-color: var(--accent);
  cursor: pointer;
}
.q-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3);
}
.btn-cancel {
  padding: var(--space-2) var(--space-4);
  font-size: var(--text-sm);
  background: var(--bg-muted);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  cursor: pointer;
}
.btn-confirm-q {
  padding: var(--space-2) var(--space-4);
  font-size: var(--text-sm);
  background: var(--bad-bg, #FAECE7);
  border: 1px solid var(--bad-border, #F0997B);
  border-radius: var(--radius-md);
  color: var(--bad-fg, #993C1D);
  font-weight: 500;
  cursor: pointer;
}
.btn-confirm-q:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@media (max-width: 640px) {
  .filter-input,
  .filter-select {
    width: 100%;
  }
}
</style>
