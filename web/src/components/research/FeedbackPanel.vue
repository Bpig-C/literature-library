<template>
  <section class="feedback-panel" data-testid="feedback-panel">
    <div class="layer-title">
      <div><span>FEEDBACK</span><h3>质疑与建议修改</h3></div>
      <code>{{ workId || '无文献' }}</code>
    </div>
    <p class="feedback-intro">
      针对字段提出质疑或附上建议改写；二者都不直接替代正式结论，也不改变人工采纳。
      已登记内容在保存、刷新、重新打开后均可读回；闭环需正式修订经独立核查，或给出有据保留结论。
      页面显示缺陷关联实际修复与复验，不要求虚构论文内容修订。
    </p>

    <!-- 已登记内容：反馈 + 解析纠错（状态以服务端为准） -->
    <div class="existing">
      <div class="existing-head">
        <strong>本篇已登记（{{ openFeedbackCount + openCorrectionCount }} 条未闭环 / 共 {{ feedbackItems.length + correctionItems.length }} 条）</strong>
        <button type="button" class="mini" @click="loadAll" :disabled="loadingList">刷新</button>
      </div>
      <ul v-if="feedbackItems.length" class="record-list">
        <li v-for="item in feedbackItems" :key="item.id" :class="{ closed: item.status === 'closed' }">
          <div class="record-head">
            <code>{{ item.id }}</code>
            <span class="kind-chip">{{ layerLabel(item.layer) }}</span>
            <span class="feedback-status" :class="feedbackStatusClass(item.status)">{{ feedbackStatusLabel(item.status) }}</span>
          </div>
          <p class="record-claim">{{ item.explicit_claim }}</p><button type="button" class="mini" @click="selectedFeedbackId = item.id">为此问题生成 Agent 任务</button>
          <p v-if="item.detail" class="record-meta">补充：{{ item.detail }}</p>
          <p v-if="item.on_ancestor_record" class="record-meta">
            登记于早期版本 <code>{{ item.target_id }}</code> v{{ item.target_version }}（质疑随记录链持续可见）
          </p>
          <p v-if="item.formal_revision_id" class="record-meta">
            正式修订：<code>{{ item.formal_revision_id }}</code><span v-if="item.status !== 'closed'">（尚未完成独立核查）</span>
          </p>
          <p v-if="item.status === 'closed'" class="record-meta">结论：{{ feedbackOutcomeLabel(item.outcome) }}<span v-if="item.resolution_note">——{{ item.resolution_note }}</span></p>
        </li>
      </ul>
      <ul v-if="correctionItems.length" class="record-list">
        <li v-for="item in correctionItems" :key="item.id" :class="{ closed: ['adopted', 'withdrawn'].includes(item.status) }">
          <div class="record-head">
            <code>{{ item.id }}</code>
            <span class="kind-chip">解析原文纠错</span>
            <span class="feedback-status is-pending">{{ correctionStatusLabel(item.status) }}</span>
          </div>
          <p class="record-claim">{{ item.problem }}</p><button type="button" class="mini" @click="selectedFeedbackId = item.id">为此问题生成 Agent 任务</button>
          <p class="record-meta">
            定位：快照 <code>{{ item.base_snapshot_id }}</code> 偏移 {{ item.start_offset }}–{{ item.end_offset }}（{{ locationLabel(item.location_status) }}）
            <template v-if="item.adopted_snapshot_id">；已生成新快照 <code>{{ item.adopted_snapshot_id }}</code>（下游采用需经现有提交流程另行完成）</template>
          </p>
          <p v-if="item.suggestion" class="record-meta">建议：{{ item.suggestion }}</p>
        </li>
      </ul>
      <p v-if="!feedbackItems.length && !correctionItems.length" class="empty-value">暂无登记。</p>
      <p v-if="listError" class="form-error" role="alert">{{ listError }}</p>
    </div>

    <AgentTaskPanel v-if="selectedFeedbackId" :record="record" initial-mode="feedback" :selected-feedback-id="selectedFeedbackId" />
    <p v-if="message" class="form-message" role="status">{{ message }}</p>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>

    <form class="feedback-form" @submit.prevent="submit">
      <label><span>问题对象（决定登记到哪条链路）</span>
        <select v-model="kind" data-testid="feedback-kind">
          <option value="interpretation">解释与分类字段</option>
          <option value="source_record">原文记录字段/单元</option>
          <option value="metadata">元数据</option>
          <option value="parse">解析原文（登记解析纠错）</option>
          <option value="page_display">页面显示问题</option>
          <option value="agent_judge">不确定——请 Agent 判断</option>
        </select>
      </label>

      <div v-if="kind === 'interpretation' || kind === 'source_record'" class="grid2">
        <label><span>目标字段/单元（可选）</span>
          <select v-model="fieldKey"><option v-if="fieldKey && !fieldOptions.some(o => o.value === fieldKey)" :value="fieldKey">{{ fieldKey }}</option>
            <option value="">（整条记录或未指明字段）</option>
            <option v-for="opt in fieldOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
          </select>
        </label>
        <p class="target-info">目标：<code>{{ target?.id }}</code> · v{{ target?.version }} · {{ stateLabel(target) }}</p>
      </div>

      <div v-if="kind === 'metadata'" class="grid2">
        <p class="target-info">
          <template v-if="metadataHead">目标：<code>{{ metadataHead.id }}</code> · v{{ metadataHead.version }} · {{ metadataHead.content_state || '状态未提供' }}</template>
          <template v-else>目标：当前元数据记录头未取得（该篇可能尚无 RMR）；可先选“请 Agent 判断”。</template>
        </p>
        <label><span>元数据字段（可选）</span><input v-model="fieldKey" type="text" placeholder="例如 venue、publication_date" /></label>
      </div>

      <div v-if="kind === 'parse'" class="grid2">
        <label><span>问题块类型</span>
          <select v-model="parseBlock">
            <option value="段落">段落</option><option value="表格">表格</option>
            <option value="公式">公式</option><option value="图注">图注</option><option value="其他">其他</option>
          </select>
        </label>
        <p class="target-info">目标：快照 <code>{{ snapshotId }}</code>（{{ parseRouteNote }}）</p>
      </div>

      <label v-if="kind === 'parse'"><span>解析原文中的逐字引文（替换/删除须逐字一致；补缺字可留空并填相同起止偏移）</span>
        <textarea v-model="parseQuote" rows="2" placeholder="从「解析源码」视图原样复制问题片段"></textarea>
      </label>
      <div v-if="kind === 'parse'" class="grid2">
        <label><span>起始偏移（可选，Unicode 码点；留空则须全文唯一）</span><input v-model="parseStart" type="text" inputmode="numeric" placeholder="例如 12345" /></label>
        <label><span>结束偏移（可选，默认=起始+引文长度）</span><input v-model="parseEnd" type="text" inputmode="numeric" /></label>
      </div>

      <label><span>{{ kind === 'page_display' ? '页面显示问题描述（必填）' : '问题描述（必填；说明哪里有误、证据为何不足）' }}</span>
        <textarea v-model="claim" rows="3" data-testid="feedback-claim"
          :placeholder="kind === 'agent_judge' ? '用一句话描述你注意到的问题；系统不猜测目标，交给 Agent 先判断' : '例如：§3.1 中 train25 的盾牌计数与 Table 1 不一致'"></textarea>
      </label>

      <label v-if="kind !== 'parse' && kind !== 'agent_judge'"><span>建议改写（可选；不直接替代正式结论）</span>
        <textarea v-model="suggestion" rows="2" placeholder="给出你认为正确的表述，供 Agent 核对后决定是否修订"></textarea>
      </label>
      <label v-if="kind === 'parse'"><span>修正建议（可选；正式修正以对照原件后的候选版为准）</span>
        <textarea v-model="suggestion" rows="2"></textarea>
      </label>

      <div class="form-actions">
        <button v-if="kind !== 'agent_judge'" type="submit" :disabled="busy || !canSubmit" data-testid="feedback-submit">
          {{ kind === 'parse' ? '登记解析纠错' : '登记问题' }}
        </button>
        <button v-else type="button" :disabled="!claim.trim()" data-testid="feedback-agent-judge" @click="generateJudgePrompt">
          生成“请 Agent 判断”提示词
        </button>
      </div>
      <p class="completeness-note">{{ completenessNote }}</p>
    </form>

    <div v-if="judgePrompt" class="judge-prompt">
      <strong>请 Agent 判断（不会写入研究数据；复制后交给本地 Agent）</strong>
      <textarea v-model="judgePrompt" rows="10"></textarea>
      <div class="form-actions">
        <button type="button" @click="copyJudge">复制提示词</button>
      </div>
      <p v-if="judgeCopyStatus" role="status">{{ judgeCopyStatus }}</p>
    </div>
  </section>
</template>

<script setup>
// 工单工作包 B：统一反馈流程。复用现有 research_feedback 体系（layer:
// interpretation/source_record/metadata/page_display）与解析纠错登记（工作包 E），
// 不生造服务不能消费的记录层值；“请 Agent 判断”只生成提示词，不落库。
import { computed, ref, watch } from 'vue'
import {
  listResearchFeedback, openResearchFeedback, getMetadataHead,
  listParseCorrections, openParseCorrection, getResearchSchema,
} from '../../api'
import AgentTaskPanel from './AgentTaskPanel.vue'
import { buildResearchAgentPrompt } from '../../researchAgentPrompt'

const props = defineProps({ record: { type: Object, required: true } })
defineExpose({ refresh: loadAll, selectTarget })
function selectTarget(layer, field = '', action = '质疑') {
  kind.value = layer; fieldKey.value = field
  message.value = `正在${action}：${field || layer}`
}


const feedbackItems = ref([])
const selectedFeedbackId = ref('')
const correctionItems = ref([])
const metadataHead = ref(null)
const loadingList = ref(false)
const listError = ref('')
const kind = ref('interpretation')
const fieldKey = ref('')
const claim = ref('')
const suggestion = ref('')
const parseBlock = ref('段落')
const parseQuote = ref('')
const parseStart = ref('')
const parseEnd = ref('')
const busy = ref(false)
const message = ref('')
const error = ref('')
const judgePrompt = ref('')
const judgeCopyStatus = ref('')

const workId = computed(() => props.record?.source?.work_id || props.record?.work_id || '')
const batchId = computed(() => props.record?.batch_id || '')
const snapshotId = computed(() => props.record?.snapshot?.id || '')

const FIELD_OPTIONS = {
  interpretation: [
    { value: 'statement', label: '核心命题 statement' },
    { value: 'scope', label: '范围 scope' },
    { value: 'reasoning', label: '推理依据 reasoning' },
    { value: 'support_boundary', label: '支撑边界 support_boundary' },
    { value: 'ontology_keys', label: '分类标签 ontology_keys' },
    { value: 'mapping_status', label: '映射状态 mapping_status' },
    { value: 'associations', label: '关联声明 associations' },
    { value: 'extensions', label: '具名扩展 extensions' },
    { value: 'unresolved', label: '未决项 unresolved' },
  ],
  source_record: [
    { value: 'units', label: '研究单元（在下一条说明具体单元）' },
    { value: 'definitions', label: '定义/操作化判据' },
    { value: 'conditions', label: '条件' },
    { value: 'methods', label: '方法' },
    { value: 'author_claims', label: '作者主张' },
    { value: 'observations', label: '观察结果' },
    { value: 'limitations', label: '局限' },
    { value: 'gaps', label: '覆盖缺口 gaps' },
    { value: 'extensions', label: '具名扩展 extensions' },
  ],
}
const fieldOptions = computed(() => FIELD_OPTIONS[kind.value] || [])

const target = computed(() => kind.value === 'source_record'
  ? props.record?.source_record
  : props.record?.interpretation)

const parseRouteNote = computed(() => props.record?.snapshot?.parse_run_id
  ? `绑定解析 ${props.record.snapshot.parse_run_id}`
  : '解析路线未取得')

const openFeedbackCount = computed(() => feedbackItems.value.filter(i => i.status !== 'closed').length)
const openCorrectionCount = computed(() => correctionItems.value.filter(i => !['adopted', 'withdrawn'].includes(i.status)).length)

const canSubmit = computed(() => {
  if (!claim.value.trim()) return false
  if (kind.value === 'metadata' && !metadataHead.value) return false
  if (kind.value === 'parse' && (!snapshotId.value || (!parseQuote.value && !(parseStart.value !== '' && parseStart.value === parseEnd.value)))) return false
  return Boolean(target.value || kind.value === 'metadata' || kind.value === 'page_display' || kind.value === 'parse')
})

const completenessNote = computed(() => {
  switch (kind.value) {
    case 'interpretation':
    case 'source_record':
      return '完成条件：正式修订经独立审核生效，或有据保留；保存建议或提交修订不等于已解决。'
    case 'metadata':
      return '元数据修正走 RMR 修订链并同步目录；登记后待 Agent 处理。'
    case 'parse':
      return '完成条件：候选修正版经独立核对并采用生成新快照，下游记录另行重新提交绑定；解析纠错不借用分类修订号假装完成。'
    case 'page_display':
      return '完成条件：页面修复并复验；不要求论文内容修订。'
    default:
      return '此模式不写入研究数据；由 Agent 先判断问题对象，再在对应链路登记处理。'
  }
})

watch(() => [props.record?.batch_id, workId.value], () => { loadAll() }, { immediate: true })

async function loadAll() {
  if (!workId.value) return
  loadingList.value = true
  listError.value = ''
  try {
    const [fb, corr, meta] = await Promise.allSettled([
      listResearchFeedback({ work_id: workId.value }),
      listParseCorrections({ work_id: workId.value }),
      getMetadataHead(workId.value),
    ])
    feedbackItems.value = fb.status === 'fulfilled' ? (fb.value?.items || []) : []
    correctionItems.value = corr.status === 'fulfilled' ? (corr.value?.items || []) : []
    metadataHead.value = meta.status === 'fulfilled' ? meta.value : null
    if (fb.status === 'rejected' || corr.status === 'rejected') {
      listError.value = '部分反馈清单读取失败，当前计数不完整，请刷新重试。'
    }
  } finally {
    loadingList.value = false
  }
}

function detailText() {
  const parts = []
  if (fieldKey.value) parts.push(`字段/单元：${fieldKey.value}`)
  if (suggestion.value.trim()) parts.push(`建议改写：${suggestion.value.trim()}`)
  parts.push('完成条件：正式修订经独立审核生效，或有据保留；不自动改变正式结论或人工采纳。')
  return parts.join('；')
}

async function submit() {
  busy.value = true
  message.value = ''
  error.value = ''
  try {
    if (kind.value === 'parse') {
      const start = parseInt(parseStart.value, 10)
      const end = parseInt(parseEnd.value, 10)
      const schema = await getResearchSchema()
      if (!schema.environment_id) throw new Error('环境身份未取得，禁止登记解析纠错')
      const response = await openParseCorrection({
        environment_id: schema.environment_id,
        work_id: workId.value,
        source_id: props.record?.source?.id,
        base_snapshot_id: snapshotId.value,
        block: parseBlock.value,
        problem: claim.value.trim(),
        suggestion: suggestion.value.trim(),
        problem_quote: parseQuote.value,
        start_offset: Number.isFinite(start) ? start : undefined,
        end_offset: Number.isFinite(end) ? end : undefined,
        reported_by: 'web-ui',
      })
      message.value = `解析纠错已登记（${response.correction_id}，定位：${response.location_status}）；下一步由 Agent 对照原件提交候选修正版。`
      parseQuote.value = ''; parseStart.value = ''; parseEnd.value = ''
    } else {
      const layer = kind.value
      await openResearchFeedback({
        layer,
        target_id: layer === 'metadata' ? metadataHead.value?.id : (layer === 'page_display' ? workId.value : target.value?.id),
        explicit_claim: claim.value.trim(),
        detail: detailText(),
        work_id: workId.value,
        batch_id: batchId.value || undefined,
        target_version: layer === 'metadata'
          ? metadataHead.value?.version
          : (layer === 'page_display' ? undefined : target.value?.version),
      })
      message.value = '已登记为“待处理”；刷新后仍可读回。闭环结论将在上方清单回显，页面不会自动标记为已纠正。'
      claim.value = ''; suggestion.value = ''
    }
    await loadAll()
  } catch (e) {
    error.value = `提交失败：${e?.detail?.message || e?.detail || e?.message || '请求失败'}`
  } finally {
    busy.value = false
  }
}

async function generateJudgePrompt() {
  judgePrompt.value = buildResearchAgentPrompt(props.record, null, null, window.location.origin, {
    mode: 'feedback',
    focus: `【请 Agent 先判断问题对象与链路】${claim.value.trim()}\n用户不确定该问题属于元数据、原文记录、解释分类、解析原文还是页面显示；请先回查固定原文判断归属，再按对应链路登记并处理；不要猜填目标。`,
    batchId: batchId.value || null,
    feedbackItems: feedbackItems.value.filter(i => i.status !== 'closed'),
    parseIssues: correctionItems.value.filter(i => !['adopted', 'withdrawn'].includes(i.status)),
  })
  judgeCopyStatus.value = ''
}

async function copyJudge() {
  try {
    await navigator.clipboard.writeText(judgePrompt.value)
    judgeCopyStatus.value = '已复制。'
  } catch {
    judgeCopyStatus.value = '浏览器未允许自动复制，请在文本框内全选后手动复制。'
  }
}

function layerLabel(layer) {
  return {
    interpretation: '解释与分类', source_record: '原文记录', metadata: '元数据',
    unit: '研究单元', ontology: '本体', page_display: '页面显示',
  }[layer] || layer
}
function feedbackStatusLabel(status) {
  return { open: '待处理', formal_revision_created: '已提交正式修订（待核查）', closed: '已闭环' }[status] || status
}
function feedbackStatusClass(status) {
  return { open: 'is-open', formal_revision_created: 'is-pending', closed: 'is-closed' }[status] || ''
}
function feedbackOutcomeLabel(outcome) {
  return {
    corrected: '已纠正（修订经独立核查后生效）', partially_corrected: '部分纠正',
    retained_with_evidence: '有据保留（原文维持）', unresolved: '仍无法确定（如实记录）',
  }[outcome] || outcome || '已闭环'
}
function correctionStatusLabel(status) {
  return {
    open: '已登记（待候选）', candidate: '候选修正版（待核查）', verified: '已核查（待采用）',
    rejected: '候选被否决', adopted: '已采用（新快照已生成）', withdrawn: '已撤回',
  }[status] || status
}
function locationLabel(status) {
  return { exact: '登记偏移逐字匹配', 'unique-assisted': '唯一逐字匹配辅助定位', ambiguous: '重复待核查', unmatched: '未匹配待核查' }[status] || status
}
function stateLabel(row) {
  if (!row) return '尚未生成'
  return { stable: '稳定', needs_review: '待审查', needs_completion: '待补全' }[row.content_state] || row.content_state || '状态未提供'
}
</script>

<style scoped>
.feedback-panel { min-width: 0; display: flex; flex-direction: column; gap: 10px; }
.layer-title { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }
.layer-title span { color: var(--text-tertiary); font-size: 9px; letter-spacing: .08em; }
.layer-title h3 { margin: 1px 0 0; font-size: 15px; }
.layer-title code { overflow-wrap: anywhere; color: var(--text-tertiary); font-size: 9px; }
.feedback-intro { margin: 0; color: var(--text-tertiary); font-size: 11px; line-height: 1.7; }
.existing { display: flex; flex-direction: column; gap: 8px; }
.existing-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.existing-head strong { font-size: 11px; color: var(--text-secondary); }
.mini { padding: 3px 9px; border: 1px solid var(--border-strong); border-radius: 5px; background: var(--bg-surface); cursor: pointer; font-size: 10px; }
.record-list { display: grid; gap: 8px; padding: 0; margin: 0; list-style: none; }
.record-list li { display: flex; flex-direction: column; gap: 4px; padding: 10px 12px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-page); }
.record-list li.closed { opacity: .72; }
.record-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.record-head code { overflow-wrap: anywhere; color: var(--text-tertiary); font-size: 9px; }
.kind-chip { padding: 1px 7px; border: 1px solid var(--border-strong); border-radius: 999px; font-size: 9px; color: var(--text-secondary); }
.feedback-status { padding: 2px 7px; border-radius: var(--radius-sm); font-size: 9px; font-weight: 620; }
.feedback-status.is-open { color: var(--warn-fg); background: var(--warn-bg); }
.feedback-status.is-pending { color: var(--info-fg); background: var(--info-bg); }
.feedback-status.is-closed { color: var(--text-secondary); border: 1px solid var(--border-strong); background: var(--bg-surface); }
.record-claim { margin: 0; font-size: 12px; line-height: 1.6; }
.record-meta { margin: 0; color: var(--text-secondary); font-size: 10px; line-height: 1.6; }
.record-meta code { overflow-wrap: anywhere; font-size: 9px; }
.feedback-form { display: grid; gap: 8px; padding-top: 10px; border-top: 1px solid var(--border); }
.feedback-form label { display: grid; gap: 4px; color: var(--text-secondary); font-size: 10px; }
.feedback-form textarea, .feedback-form select, .feedback-form input { width: 100%; box-sizing: border-box; padding: 7px 8px; color: var(--text-primary); border: 1px solid var(--border-strong); border-radius: var(--radius-sm); background: var(--bg-surface); font: 11px/1.55 var(--font-sans); }
.feedback-form textarea { resize: vertical; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; align-items: end; }
.target-info { margin: 0; color: var(--text-tertiary); font-size: 10px; line-height: 1.6; overflow-wrap: anywhere; }
.target-info code { font-size: 9px; }
.form-actions { display: flex; gap: 7px; }
.form-actions button { padding: 6px 10px; color: #fff; border: 1px solid var(--accent); border-radius: var(--radius-sm); background: var(--accent); cursor: pointer; font-size: 10px; font-weight: 620; }
.form-actions button:disabled { cursor: not-allowed; opacity: .5; }
.form-message { margin: 0; padding: 8px 10px; color: var(--info-fg); background: var(--info-bg); border-radius: var(--radius-sm); font-size: 10px; line-height: 1.6; }
.form-error { margin: 0; padding: 8px 10px; color: var(--warn-fg); background: var(--warn-bg); border-radius: var(--radius-sm); font-size: 10px; line-height: 1.6; overflow-wrap: anywhere; }
.completeness-note { margin: 0; color: var(--text-tertiary); font-size: 10px; line-height: 1.6; }
.judge-prompt { display: grid; gap: 6px; padding: 10px; border: 1px solid var(--warn-border); border-radius: var(--radius-md); background: var(--warn-bg); }
.judge-prompt strong { font-size: 11px; color: var(--warn-fg); }
.judge-prompt textarea { width: 100%; box-sizing: border-box; resize: vertical; padding: 8px; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--bg-surface); font: 11px/1.6 var(--font-sans); }
.judge-prompt .form-actions button { color: var(--accent-ink); border-color: var(--border-strong); background: var(--bg-surface); }
.judge-prompt p { margin: 0; font-size: 10px; }
@media (max-width: 720px) { .grid2 { grid-template-columns: 1fr; } }
</style>
