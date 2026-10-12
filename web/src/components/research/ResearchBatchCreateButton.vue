<template>
  <n-button secondary type="primary" data-testid="create-research-batch" :disabled="readOnly" title="只读部署：写操作被服务端禁用" @click="openPlanner">
    ＋ 新建研究批次
  </n-button>

  <n-modal v-model:show="show" preset="card" title="新建研究批次" class="batch-create-modal"
    style="width: min(860px, 94vw)">
    <div class="batch-form">
      <n-alert type="info" :show-icon="false">
        批次会固定本轮文献、解析快照和定义发布包。创建后不会自动执行 Agent，也不会改写已有记录。
      </n-alert>

      <label>
        <span>批次名称</span>
        <n-input v-model:value="name" placeholder="例如：自主性风险基准研究第一轮" />
      </label>

      <label>
        <span>正式完成范围</span>
        <n-radio-group v-model:value="targetMode">
          <n-radio-button v-for="item in RESEARCH_BATCH_TARGET_MODES" :key="item.value" :value="item.value">
            {{ item.label }}
          </n-radio-button>
        </n-radio-group>
        <small>本批次以 C 原文记录、D 解释与分类为完成门。完整 A 元数据请到 <router-link to="/metadata-workspace">Work 级元数据工作台</router-link> 批量安排；R 参考文献可在解析后并行处理，不以本批次完成状态代替其覆盖状态。</small>
      </label>

      <details class="agent-selection">
        <summary>
          <span><strong>文献太多？让 Agent 先筛选</strong><small>生成可编辑工单；生成与复制均不会写数据库</small></span>
          <em>按目标选文</em>
        </summary>
        <div class="agent-selection-body">
          <label>
            <span>本批研究目标</span>
            <n-input v-model:value="selectionFocus" type="textarea" :rows="3" />
          </label>
          <div class="selection-row">
            <label>
              <span>建议规模</span>
              <n-input-number v-model:value="desiredCount" :min="1" :max="100" />
            </label>
            <p>Agent 会先给出核心、背景、待确认、排除四档清单。你确认后，它再通过正式接口送入研究库并创建批次，无需逐篇勾选。</p>
          </div>
          <label>
            <span>排除与降级条件</span>
            <n-input v-model:value="selectionExclusions" type="textarea" :rows="2" />
          </label>
          <div class="prompt-actions">
            <n-button @click="generateSelectionPrompt">生成/刷新提示词</n-button>
            <n-button type="primary" secondary :disabled="!selectionPrompt" @click="copySelectionPrompt">复制提示词</n-button>
            <small v-if="promptStatus">{{ promptStatus }}</small>
          </div>
          <n-input v-if="selectionPrompt" v-model:value="selectionPrompt" type="textarea"
            :rows="14" aria-label="批次选文 Agent 提示词" />
        </div>
      </details>

      <section class="source-picker">
        <header>
          <div><strong>选择已经进入研究库的文献</strong><small>支持 Work ID、来源文件名和正文关键词搜索</small></div>
          <span>{{ selectedSourceIds.length }} 篇已选</span>
        </header>
        <div class="source-search">
          <n-input v-model:value="sourceQuery" clearable placeholder="留空显示最近来源；输入后搜索"
            @keyup.enter="loadSources" />
          <n-button :loading="sourcesLoading" @click="loadSources">搜索</n-button>
        </div>
        <n-select v-model:value="selectedSourceIds" :options="sourceOptions" multiple filterable clearable
          :max-tag-count="'responsive'" placeholder="选择一篇或多篇文献" @update:value="hydrateSelected" />
        <small v-if="sourceStatus" :class="{ error: sourceFailed }">{{ sourceStatus }}</small>
      </section>

      <section v-if="selectedSourceIds.length" class="snapshot-list">
        <header><strong>固定本轮快照</strong><small>有多个快照时默认选择最新版本，可手动更改</small></header>
        <article v-for="sourceId in selectedSourceIds" :key="sourceId">
          <div>
            <strong>{{ sourceTitle(sourceId) }}</strong>
            <code>{{ sourceId }}</code>
          </div>
          <n-select v-if="sourceDetails[sourceId]?.snapshots?.length"
            v-model:value="snapshotIds[sourceId]" :options="snapshotOptions(sourceId)"
            aria-label="固定快照" />
          <n-tag v-else-if="detailsLoading[sourceId]" size="small">读取快照…</n-tag>
          <n-tag v-else type="error" size="small">没有可用快照</n-tag>
        </article>
      </section>

      <section class="release-card">
        <span>钉定发布包</span>
        <div v-if="release"><code>{{ release.id }}</code><small>{{ release.note || '当前正式发布包' }}</small></div>
        <n-tag v-else-if="loading" size="small">读取中…</n-tag>
        <n-tag v-else type="error" size="small">未取得</n-tag>
      </section>

      <n-alert v-if="error" type="error" :show-icon="false">{{ error }}</n-alert>
      <div class="actions">
        <n-button @click="show = false">取消</n-button>
        <n-button type="primary" :loading="submitting" :disabled="readOnly || !canSubmit" :title="readOnly ? '只读部署：写操作被服务端禁用' : ''" @click="createBatch">
          创建并进入批次
        </n-button>
      </div>
    </div>
  </n-modal>
</template>

<script setup>

import { useRuntimeMode } from '../../composables/useRuntimeMode'
const { readOnly } = useRuntimeMode()
import { computed, reactive, ref } from 'vue'
import {
  getCurrentResearchRelease,
  getResearchSource,
  planResearchBatch,
  searchResearchSources,
} from '../../api'
import {
  DEFAULT_BATCH_SELECTION_EXCLUSIONS,
  DEFAULT_BATCH_SELECTION_FOCUS,
  RESEARCH_BATCH_TARGET_MODES,
  buildBatchSelectionAgentPrompt,
  buildBatchPlanPayload,
  chooseDefaultSnapshot,
  makeBatchRequestKey,
  validateBatchDraft,
} from '../../researchBatchPlan'

const emit = defineEmits(['created'])
const show = ref(false)
const loading = ref(false)
const submitting = ref(false)
const name = ref('')
const targetMode = ref('source-and-interpretation')
const sourceQuery = ref('')
const sourcesLoading = ref(false)
const sourcePool = ref([])
const selectedSourceIds = ref([])
const sourceDetails = reactive({})
const detailsLoading = reactive({})
const snapshotIds = reactive({})
const release = ref(null)
const requestKey = ref('')
const error = ref('')
const sourceStatus = ref('')
const sourceFailed = ref(false)
const selectionFocus = ref(DEFAULT_BATCH_SELECTION_FOCUS)
const selectionExclusions = ref(DEFAULT_BATCH_SELECTION_EXCLUSIONS)
const desiredCount = ref(12)
const selectionPrompt = ref('')
const promptStatus = ref('')

function displayDate() {
  const date = new Date()
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

function sourceLabel(source) {
  return `${source.original_name || source.citation_key || source.work_id || source.id} · ${source.work_id || '无 Work ID'} · ${source.id}`
}

const sourceOptions = computed(() => {
  const rows = new Map(sourcePool.value.map(item => [item.id, item]))
  for (const id of selectedSourceIds.value) {
    const source = sourceDetails[id]?.source
    if (source) rows.set(id, source)
  }
  return [...rows.values()].map(source => ({ label: sourceLabel(source), value: source.id }))
})

const canSubmit = computed(() => !loading.value && !submitting.value && !validateBatchDraft({
  name: name.value,
  sourceIds: selectedSourceIds.value,
  snapshotIds,
  releaseId: release.value?.id,
}))

function apiErrorText(caught) {
  return caught?.detail || caught?.message || '请求失败'
}

function generateSelectionPrompt() {
  selectionPrompt.value = buildBatchSelectionAgentPrompt({
    origin: window.location.origin,
    focus: selectionFocus.value,
    exclusions: selectionExclusions.value,
    desiredCount: desiredCount.value,
    releaseId: release.value?.id,
    stagedSourceCount: sourcePool.value.length,
  })
  promptStatus.value = '已生成。可直接修改，也可复制给本地 Agent。'
}

async function copySelectionPrompt() {
  try {
    await navigator.clipboard.writeText(selectionPrompt.value)
    promptStatus.value = '已复制。Agent 第一轮只会提交选文清单，等待你确认后才建批。'
  } catch (caught) {
    promptStatus.value = '自动复制失败，请在下方文本框中全选复制。'
  }
}

async function openPlanner() {
  show.value = true
  error.value = ''
  if (!name.value) name.value = `研究批次 ${displayDate()}`
  if (!requestKey.value) requestKey.value = makeBatchRequestKey()
  if (release.value && sourcePool.value.length) return
  loading.value = true
  try {
    const [currentRelease] = await Promise.all([
      getCurrentResearchRelease(),
      loadSources(),
    ])
    release.value = currentRelease
  } catch (caught) {
    error.value = `无法准备建批信息：${apiErrorText(caught)}`
  } finally {
    loading.value = false
  }
}

async function loadSources() {
  sourcesLoading.value = true
  sourceFailed.value = false
  sourceStatus.value = ''
  try {
    const response = await searchResearchSources(sourceQuery.value.trim(), 200)
    sourcePool.value = response.items || []
    sourceStatus.value = `找到 ${sourcePool.value.length} 条已进入研究库的来源。未找到的文献需先完成解析并送入研究库。`
  } catch (caught) {
    sourceFailed.value = true
    sourceStatus.value = `来源读取失败：${apiErrorText(caught)}`
    throw caught
  } finally {
    sourcesLoading.value = false
  }
}

async function hydrateSelected() {
  const pending = selectedSourceIds.value.filter(id => !sourceDetails[id] && !detailsLoading[id])
  await Promise.all(pending.map(async id => {
    detailsLoading[id] = true
    try {
      const detail = await getResearchSource(id)
      sourceDetails[id] = detail
      const snapshot = chooseDefaultSnapshot(detail.snapshots || [])
      if (snapshot && !snapshotIds[id]) snapshotIds[id] = snapshot.id
    } catch (caught) {
      error.value = `无法读取来源 ${id} 的快照：${apiErrorText(caught)}`
    } finally {
      detailsLoading[id] = false
    }
  }))
}

function sourceTitle(sourceId) {
  const source = sourceDetails[sourceId]?.source || sourcePool.value.find(item => item.id === sourceId)
  return source?.original_name || source?.work_id || sourceId
}

function snapshotOptions(sourceId) {
  return (sourceDetails[sourceId]?.snapshots || [])
    .slice().sort((a, b) => Number(b.version || 0) - Number(a.version || 0))
    .map(snapshot => ({
      value: snapshot.id,
      label: `v${snapshot.version ?? '?'} · ${snapshot.id} · ${snapshot.parse_quality || '质量未检查'}`,
    }))
}

async function createBatch() {
  error.value = ''
  await hydrateSelected()
  const validation = validateBatchDraft({
    name: name.value,
    sourceIds: selectedSourceIds.value,
    snapshotIds,
    releaseId: release.value?.id,
  })
  if (validation) {
    error.value = validation
    return
  }
  submitting.value = true
  try {
    const payload = buildBatchPlanPayload({
      name: name.value,
      sourceIds: selectedSourceIds.value,
      snapshotIds,
      releaseId: release.value.id,
      requestKey: requestKey.value,
      targetMode: targetMode.value,
    })
    const batch = await planResearchBatch(payload)
    show.value = false
    emit('created', batch)
    // 成功后才换幂等键；网络不确定时保留旧键，重复提交不会建重复批次。
    requestKey.value = ''
    name.value = ''
    selectedSourceIds.value = []
    for (const key of Object.keys(snapshotIds)) delete snapshotIds[key]
  } catch (caught) {
    error.value = `创建失败：${apiErrorText(caught)}`
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.batch-form{display:grid;gap:14px}.batch-form>label,.agent-selection-body>label,.selection-row>label{display:grid;gap:6px}.batch-form>label>span,.agent-selection label>span,.source-picker strong,.snapshot-list>header strong{font-size:12px;font-weight:620}.batch-form small{color:var(--text-tertiary);font-size:10px;line-height:1.5}.agent-selection{overflow:hidden;border:1px solid color-mix(in srgb,var(--accent) 34%,var(--border));border-radius:var(--radius-lg);background:color-mix(in srgb,var(--accent) 4%,var(--bg-card))}.agent-selection summary{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px;cursor:pointer;list-style:none}.agent-selection summary::-webkit-details-marker{display:none}.agent-selection summary>span{display:grid;gap:2px}.agent-selection summary strong{font-size:12px}.agent-selection summary em{color:var(--accent-ink);font-size:10px;font-style:normal}.agent-selection-body{display:grid;gap:11px;padding:0 12px 12px;border-top:1px solid var(--border)}.agent-selection-body>label:first-child{padding-top:12px}.selection-row{display:grid;grid-template-columns:150px 1fr;align-items:end;gap:12px}.selection-row p{margin:0;color:var(--text-secondary);font-size:10px;line-height:1.6}.prompt-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.prompt-actions small{margin-left:auto}.source-picker,.snapshot-list{display:grid;gap:9px;padding:12px;border:1px solid var(--border);border-radius:var(--radius-lg);background:var(--bg-page)}.source-picker header,.snapshot-list>header{display:flex;align-items:center;justify-content:space-between;gap:10px}.source-picker header div,.snapshot-list>header{min-width:0}.source-picker header div{display:grid;gap:2px}.source-picker header>span{color:var(--accent-ink);font-size:11px}.source-search{display:grid;grid-template-columns:1fr auto;gap:7px}.source-picker>small.error{color:var(--bad-fg)}.snapshot-list article{display:grid;grid-template-columns:minmax(220px,1fr) minmax(300px,1fr);align-items:center;gap:12px;padding:9px 0;border-top:1px solid var(--border)}.snapshot-list article>div{display:grid;gap:3px;min-width:0}.snapshot-list article strong{overflow:hidden;font-size:11px;text-overflow:ellipsis;white-space:nowrap}.snapshot-list code{color:var(--text-tertiary);font-size:9px}.release-card{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 12px;border-left:3px solid var(--accent);background:var(--bg-page)}.release-card>span{color:var(--text-secondary);font-size:11px}.release-card>div{display:grid;justify-items:end;gap:2px}.release-card code{font-size:11px}.actions{display:flex;justify-content:flex-end;gap:8px}@media(max-width:720px){.snapshot-list article,.selection-row{grid-template-columns:1fr}.source-picker header,.snapshot-list>header{align-items:flex-start;flex-direction:column}.prompt-actions small{margin-left:0;width:100%}}
</style>
