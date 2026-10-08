<template>
  <div class="pipeline-layout" :class="{ 'with-pdf': showPdfDrawer }">
    <!-- 左侧：流程阶段列 -->
    <div class="pipeline-main">
    <h1 class="page-title">流程管理</h1>
    <p class="page-desc">摄入建立 Work 身份 → 解析 → <router-link to="/metadata-workspace">按 Work 批量整理 A 元数据</router-link>（参考文献可并行）；按主题研究批次整理 C 原文与 D 解释分类。独立核查和您的判断分别留痕。</p>

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

    <section class="research-handoff metadata-handoff">
      <span class="handoff-kicker">解析后 · 按 Work 独立处理</span>
      <h2>A 原数据工作台</h2>
      <p>从已解析的 Work 批量生成 Agent 抽取、补全或独立复核工单，并由您查看字段、提出质疑或采纳。无需先送入研究库或创建主题批次；参考文献条目可并行整理。研究批次可以另行规划，D 解释须核对其 A 依赖。</p>
      <router-link to="/metadata-workspace">进入元数据工作台 →</router-link>
    </section>

    <div class="stage-arrow">↓ 按研究目标选择文献</div>

    <!-- 进入研究流程（LL-DECOUPLE-20260920：仅准备 C/D 研究来源） -->
    <StageCard
      icon="🧪"
      title="准备主题研究来源"
      description="按研究目标把已解析文献送入研究库，为 C 原文记录和 D 解释分类准备固定来源；A 原数据在 Work 级另行处理"
      :count="stages.researchStage.count"
      stat-label="可选材料"
      :secondary-count="stages.researchStage.stagedWorks"
      secondary-label="已在研究库"
      action-label="送入研究库"
      :selected-count="stages.researchStage.selectedIds.size"
      :loading="stages.researchStage.loading"
      @execute="batchStageResearch"
    >
      <template #filters>
        <input
          v-model="stages.researchStage.filter"
          placeholder="搜索标题..."
          class="filter-input"
        />
        <router-link to="/metadata" class="goto-upload" title="旧元数据审核已退役为只读历史">
          旧书目候选复核（只读归档）→
        </router-link>
      </template>

      <SelectableFileList
        :items="filteredResearchItems"
        :selected-ids="stages.researchStage.selectedIds"
        :loading="stages.researchStage.loading"
        :page="stages.researchStage.page"
        :page-size="20"
        selectable
        @update:selected="stages.researchStage.selectedIds = $event"
        @update:page="stages.researchStage.page = $event"
      >
        <template #item="{ item }">
          <StatusBadge status="pending" size="small" />
          <span class="file-name">{{ item.display_title }}</span>
          <span class="file-meta">解析完成</span>
          <span class="file-meta">{{ formatDate(item.created_at) }}</span>
          <button class="btn-preview" @click.stop="handlePreview(item.work_id || item.id, item.display_title)">预览</button>
          <button class="btn-quarantine-row" @click.stop="openQuarantine(item.work_id || item.id)">隔离</button>
        </template>
      </SelectableFileList>
    </StageCard>

    <div class="stage-arrow">↓</div>
    <section class="research-handoff">
      <span class="handoff-kicker">下一步</span>
      <h2>进入研究批次</h2>
      <p>在研究视图规划批次并生成 C 原文与 D 解释分类工单。A 元数据的抽取、核查和目录传播由 Work 级流程承担；旧抽取/旧分类保留只读归档。</p>
      <router-link to="/research">进入研究视图 →</router-link>
    </section>
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
import { parseSummary } from '../utils/storage-feedback'
import {
  getIngestPlan,
  executeIngest,
  parseStatus,
  parseTrigger,
  getPipelineStats,
  getUnstagedWorks,
  stageWorkToResearch,
  quarantineWork,
  pdfUrl,
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


// 阶段状态
const stages = ref({
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
  researchStage: {
    count: 0,
    stagedWorks: 0,
    loading: false,
    items: [],
    selectedIds: new Set(),
    page: 1,
    filter: '',
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

const filteredResearchItems = computed(() => {
  let items = stages.value.researchStage.items
  if (stages.value.researchStage.filter) {
    const q = stages.value.researchStage.filter.toLowerCase()
    items = items.filter(i => (i.display_title || '').toLowerCase().includes(q))
  }
  return items
})

// 数据加载
async function loadAll() {
  await Promise.allSettled([
    loadIngest(),
    loadParse(),
    loadResearchStage(),
  ])
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

async function loadResearchStage() {
  try {
    const [stats, res] = await Promise.all([
      getPipelineStats(),
      getUnstagedWorks({ per_page: 100, page: stages.value.researchStage.page }),
    ])
    stages.value.researchStage.count = stats.research?.parsed_not_staged ?? res.total ?? 0
    stages.value.researchStage.stagedWorks = stats.research?.staged_works || 0
    stages.value.researchStage.items = (res.items || []).map(item => ({
      ...item,
      id: item.work_id,
      display_title: item.title || item.work_id,
    }))
  } catch (e) {
    console.error('Failed to load research stage:', e)
    showError(new Error(`研究流程阶段加载失败: ${e.message}`))
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
      const result = await parseTrigger({ work_ids: ids })
      clearAllSelections()
      await loadAll()
      // 下一步（元数据抽取）就在本页下一阶段，接力提示不跳转
      notifyNext(parseSummary(result), { label: '继续送入研究库' })
    } catch (e) {
      showError(e)
    } finally {
      stages.value.parse.loading = false
    }
  })
}

async function batchStageResearch() {
  const ids = Array.from(stages.value.researchStage.selectedIds)
  if (!ids.length) return
  showConfirm('送入研究库', `即将把选中的 ${ids.length} 篇解析成功的文献送入研究库（幂等），确定继续？`, async () => {
    confirm.value.show = false
    stages.value.researchStage.loading = true
    try {
      const results = []
      for (const id of ids) {
        try {
          const r = await stageWorkToResearch(id, { batch_mode: 'import_only' })
          results.push({ id, created: r.created })
        } catch (e) {
          results.push({ id, error: e.message || String(e) })
        }
      }
      clearAllSelections()
      await loadAll()
      const ok = results.filter(r => !r.error).length
      const failed = results.length - ok
      if (failed > 0) {
        const lines = results.filter(r => r.error)
          .map(r => `· ${r.id}：${r.error}`)
          .join('\n')
        confirm.value = {
          show: true,
          title: '送入完成（部分失败）',
          message: `成功 ${ok} 篇，失败 ${failed} 篇：
${lines}`,
          action: null,
        }
      } else {
        notifyNext(
          `送入研究库完成：成功 ${ok} 篇；下一步在研究视图规划批次`,
          { label: '进入研究视图', to: '/research' })
      }
    } catch (e) {
      showError(e)
    } finally {
      stages.value.researchStage.loading = false
    }
  })
}

/** 数据刷新后清理所有阶段的选中状态（TD-P3） */
function clearAllSelections() {
  stages.value.ingest.selectedIds = new Set()
  stages.value.parse.selectedIds = new Set()
  stages.value.researchStage.selectedIds = new Set()
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

.research-handoff {
  padding: 22px;
  border: 1px solid var(--accent-mute);
  border-radius: var(--radius-lg);
  background: linear-gradient(135deg, var(--accent-subtle), var(--bg-surface));
}
.handoff-kicker { color: var(--accent); font-size: var(--text-xs); font-weight: 650; letter-spacing: .08em; }
.research-handoff h2 { margin-top: 5px; font-size: var(--text-xl); }
.research-handoff p { margin: 8px 0 14px; color: var(--text-secondary); font-size: var(--text-sm); line-height: 1.7; }
.research-handoff a { display: inline-flex; padding: 7px 12px; color: #fff; border-radius: var(--radius-md); background: var(--accent); font-size: var(--text-sm); }

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
