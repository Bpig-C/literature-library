<template>
  <div class="metadata-space">
    <header class="intro">
      <div><small>WORK 级基础书目</small><h1>元数据工作台</h1>
        <p>入库建立 Work 身份；解析后由 Agent 按 Work 批量抽取或补全 A，独立核查后回到这里由您阅读、质疑或采纳。无需先建研究批次。</p></div>
      <button type="button" @click="load" :disabled="loading">{{ loading ? '读取中…' : '刷新状态' }}</button>
    </header>
    <p v-if="error" class="alert">{{ error }}</p>
    <div class="flow"><router-link to="/ingest">文献入库 / Work ID</router-link> <b>→</b> <router-link to="/pipeline">文档解析</router-link> <b>→</b> 本页 A 元数据（参考文献 R 可并行）；<router-link to="/research">主题研究批次</router-link>可另行规划 C 原文与 D 解释分类。</div>
    <section v-if="detailItem" ref="detailSection" class="detail-box" tabindex="-1" aria-labelledby="metadata-detail-heading">
      <div class="detail-heading"><h2 id="metadata-detail-heading">{{ detailItem.title || detailItem.id }} · A 记录</h2><div><button type="button" @click="returnToWorks">返回文献列表</button><button type="button" @click="closeDetail">关闭</button></div></div>
      <p v-if="detailLoading">读取记录…</p><p v-else-if="detailError" class="alert">{{ detailError }}</p>
      <template v-else-if="detail">
        <p v-if="!detail.records.length">尚无 A 记录。可选中此 Work 生成 Agent 首次抽取工单。</p>
        <details v-for="record in detail.records" :key="record.id" class="record" :open="record.id === detail.current_head_id">
          <summary>{{ record.id === detail.current_head_id ? '当前头 · ' : '历史版本 · ' }}{{ record.id }} · v{{ record.version }} · {{ record.validity_status }} / {{ record.content_state }} / {{ record.agent_review_status }} / 人工 {{ record.human_adoption_status }}</summary>
          <p>创建 {{ record.created_at }} · 发布包 {{ record.release_id || '未绑定' }} · 来源批次 {{ record.batch_id || 'Work 级，无研究批次' }}</p>
          <div v-for="(value,key) in record.payload" :key="key" class="field"><strong>{{ fieldLabel(key) }}<small>{{ key }}</small></strong><pre>{{ pretty(value) }}</pre></div>
        </details>
        <h3>质疑与修订</h3><p v-if="!detail.feedback.length">暂无 A 反馈。</p>
        <div v-for="feedback in detail.feedback" :key="feedback.id" class="feedback">{{ feedback.id }} · {{ feedback.status }}{{ feedback.outcome ? ' / ' + feedback.outcome : '' }} · {{ feedback.explicit_claim }}<small>{{ feedback.detail }}</small></div>
        <div v-if="detail.records.length" class="human-actions">
          <h3>您的判断</h3><p class="hint">反馈只登记问题，Agent 按工单回查并生成修订；采纳只在您读过已稳定且独立核查通过的当前版本后操作。</p>
          <textarea v-model="feedbackText" rows="3" placeholder="指出 A 元数据的具体问题或缺漏"></textarea>
          <button type="button" :disabled="readOnly || !feedbackText.trim() || writing" title="只读部署：写操作被服务端禁用" @click="submitFeedback">登记质疑</button>
          <div class="adoption"><input v-model="actorId" placeholder="您的操作身份（必填）" /><input v-model="adoptionNote" placeholder="判断依据/备注" /><button type="button" :disabled="readOnly || writing || !actorId.trim() || !currentAdoptable" title="只读部署：写操作被服务端禁用" @click="adopt('adopted')">采纳当前 A</button><button type="button" :disabled="readOnly || writing || !actorId.trim()" title="只读部署：写操作被服务端禁用" @click="adopt('rejected')">不采纳</button></div>
          <p v-if="actionMessage">{{ actionMessage }}</p>
        </div>
      </template>
    </section>
    <div class="counts" v-if="data">
      <span v-for="(n,key) in data.counts" :key="key">{{ stateLabel(key) }} <strong>{{ n }}</strong></span>
    </div>
    <div class="controls">
      <input v-model="search" type="search" placeholder="筛选标题或 Work ID" aria-label="筛选文献" />
      <select v-model="filter" aria-label="筛选元数据状态"><option value="all">全部状态</option><option v-for="key in stateKeys" :key="key" :value="key">{{ stateLabel(key) }}</option></select>
      <label><input v-model="includeStable" type="checkbox" /> 允许勾选稳定 A 供复核/定向更新</label>
      <button type="button" @click="selectActionable">选中本页待办</button>
      <button type="button" @click="selected=[]">清空选择</button>
    </div>
    <p class="hint">清单只读，勾选不会派发任务。隔离、冲突、未解析的 Work 不参与批量抽取；如需处理请先解决前置问题。</p>
    <p class="hint">筛选结果 {{ filtered.length }} 篇 · 第 {{ page }} / {{ pageCount }} 页（每页 25 篇）。跨页选择会保留；生成工单只包含已选 Work。</p>
    <div class="table-wrap"><table><thead><tr><th>选择</th><th>文献</th><th>解析材料</th><th>A 状态</th><th>操作</th></tr></thead>
      <tbody><tr v-for="item in paged" :key="item.id">
        <td><input type="checkbox" :checked="selected.includes(item.id)" :disabled="!canSelect(item)" :aria-label="`选择 ${item.id}`" @change="toggle(item.id)" /></td>
        <td><strong>{{ item.title || '标题待核' }}</strong><small>{{ item.id }}</small></td>
        <td>{{ item.parse_ready ? 'Markdown 可读' : '待解析或文件缺失' }}<small v-if="item.parse?.id">{{ item.parse.id }}</small></td>
        <td><span class="state" :class="item.status">{{ stateLabel(item.status) }}</span><small v-if="item.metadata_head">{{ item.metadata_head.id }} · v{{ item.metadata_head.version }} · {{ item.metadata_head.agent_review_status }} · 人工 {{ item.metadata_head.human_adoption_status }}</small><small v-if="item.open_feedback_count">开放质疑 {{ item.open_feedback_count }} 条</small></td>
        <td><button type="button" @click="showDetail(item)">查看 A 与反馈</button><router-link :to="`/works/${encodeURIComponent(item.id)}`">文献详情</router-link></td>
      </tr></tbody></table><p v-if="!filtered.length" class="empty">没有符合条件的 Work。</p></div>
    <div class="pager"><button type="button" :disabled="page<=1" @click="page--">上一页</button><span>第 {{ page }} / {{ pageCount }} 页</span><button type="button" :disabled="page>=pageCount" @click="page++">下一页</button></div>

    <section class="prompt-box">
      <h2>批量 Agent 工单 <small>已选 {{ selected.length }} 篇</small></h2>
      <p v-if="schemaError" class="alert" role="alert">研究环境（schema）读取失败：{{ schemaError }}。A 清单不受影响；工单须绑定执行环境，生成已禁用。点上方“刷新状态”重试。</p>
      <p v-else-if="!schema" class="hint">研究环境（schema）尚未取得：工单须绑定执行环境，取得前生成保持禁用。</p>
      <div class="prompt-controls"><select v-model="mode" aria-label="选择工单模式"><option v-for="entry in METADATA_PROMPT_MODES" :key="entry.value" :value="entry.value">{{ entry.label }}</option></select>
        <input v-model="focus" placeholder="补充您特别关注的字段/问题（可留空）" />
        <button type="button" @click="generate" :disabled="!selected.length || !schema || !!schemaError" :title="schemaError ? 'schema 未取得，工单缺少执行环境绑定' : (!schema ? 'schema 尚未取得，工单缺少执行环境绑定' : '')">生成可编辑工单</button>
        <button type="button" @click="copy" :disabled="!prompt">{{ copied ? '已复制' : '复制工单' }}</button></div>
      <p class="hint">“自动分流”适合新旧记录混合的批量任务；独立复核与人工采纳是不同步骤。生成后的内容可以自行修改再交给外部 Agent。</p>
      <textarea v-model="prompt" rows="17" aria-label="可编辑的元数据 Agent 工单" placeholder="选中 Work 后生成提示词"></textarea>
    </section>


  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getMetadataWorklist, getMetadataWorkDetail, getResearchSchema, getMaterials, openMetadataFeedback, adoptMetadataRecord } from '../api'
import { useRuntimeMode } from '../composables/useRuntimeMode'

const { readOnly } = useRuntimeMode()
import { buildMetadataAgentPrompt, METADATA_PROMPT_MODES } from '../metadataAgentPrompt'

const route = useRoute()
const router = useRouter()
const detailSection = ref(null)
let detailRequest = 0
const data = ref(null), schema = ref(null), materialsList = ref(null), loading = ref(false), error = ref(''), schemaError = ref('')
const search = ref(''), filter = ref('all'), includeStable = ref(false), selected = ref([])
const mode = ref('auto'), focus = ref(''), prompt = ref(''), copied = ref(false)
const detailItem = ref(null), detail = ref(null), detailLoading = ref(false), detailError = ref('')
const feedbackText = ref(''), actorId = ref(''), adoptionNote = ref(''), writing = ref(false), actionMessage = ref('')
const stateKeys = ['waiting_parse','absent','pending','stable','excluded','conflict','quarantined']
const stateLabels = { waiting_parse:'待解析', absent:'待抽取', pending:'待核查/修订', stable:'稳定可复用', excluded:'已排除', conflict:'身份冲突', quarantined:'已隔离' }
const stateLabel = key => stateLabels[key] || key
const items = computed(() => data.value?.items || [])
const filtered = computed(() => items.value.filter(item => (filter.value === 'all' || item.status === filter.value) && (!search.value || `${item.id} ${item.title}`.toLowerCase().includes(search.value.toLowerCase()))))
const page = ref(1)
const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / 25)))
const paged = computed(() => filtered.value.slice((page.value - 1) * 25, page.value * 25))
watch([search, filter], () => { page.value = 1 })
function canSelect(item) { return item.parse_ready && item.read_status !== 'quarantined' && !['excluded','conflict'].includes(item.status) && (includeStable.value || item.status !== 'stable') }
function toggle(id) { selected.value = selected.value.includes(id) ? selected.value.filter(x => x !== id) : [...selected.value,id] }
function selectActionable() { selected.value = [...new Set([...selected.value,...paged.value.filter(canSelect).map(item => item.id)])] }
let loadSeq = 0
async function load() {
  // 审计 F6：整轮加载使用代次守卫。重叠刷新时，前一轮的迟到清单/schema/
  // materials（无论成功或失败）不得覆盖新一轮已生效的结果。
  const seq = ++loadSeq
  loading.value = true; error.value = ''; schemaError.value = ''
  schema.value = null; materialsList.value = null; prompt.value = ''; copied.value = false
  // issue #20：A 工作清单是主数据；schema/materials 是辅助读取。辅助失败
  // 不得阻断清单与按 work_id 打开 A 详情；schema 缺失时禁用工单生成并说明。
  try {
    const list = await getMetadataWorklist()
    if (seq !== loadSeq) return
    data.value = list
    selected.value = selected.value.filter(id => list.items.some(item => item.id === id && canSelect(item)))
    await openRequestedDetail()
  } catch (e) { if (seq === loadSeq) error.value = `A 清单暂不可用：${e.detail || e.message}` }
  finally { if (seq === loadSeq) loading.value = false }
  await Promise.allSettled([
    getResearchSchema().then(value => { if (seq === loadSeq) schema.value = value },
      reason => { if (seq === loadSeq) schemaError.value = reason?.detail || reason?.message || '读取失败' }),
    getMaterials().then(value => { if (seq === loadSeq) materialsList.value = value },
      () => { if (seq === loadSeq) materialsList.value = null }),
  ])
}
async function focusDetail() {
  await nextTick()
  detailSection.value?.scrollIntoView({ block: 'start' })
  detailSection.value?.focus({ preventScroll: true })
}
async function openRequestedDetail() {
  const id = typeof route.query.work_id === 'string' ? route.query.work_id : ''
  if (!id) { detailRequest++; detailItem.value = null; detail.value = null; return }
  const item = items.value.find(row => row.id === id)
  if (item) return showDetail(item)
  detailRequest++; detailItem.value = { id }; detail.value = null; detailLoading.value = false
  detailError.value = `当前清单中未找到 Work ${id}。请返回文献列表核对。`
  await focusDetail()
}
async function showDetail(item) {
  if (route.query.work_id !== item.id) {
    await router.replace({ query: { ...route.query, work_id: item.id } })
    return
  }
  const request = ++detailRequest
  detailItem.value = item; detail.value = null; detailError.value = ''; detailLoading.value = true; actionMessage.value = ''
  await focusDetail()
  try { const result = await getMetadataWorkDetail(item.id); if (request === detailRequest) detail.value = result }
  catch (e) { if (request === detailRequest) detailError.value = e.detail || e.message }
  finally { if (request === detailRequest) detailLoading.value = false }
}
function closeDetail() {
  detailRequest++; detailItem.value = null; detail.value = null; detailError.value = ''; detailLoading.value = false
  router.replace({ query: { ...route.query, work_id: undefined } })
}
function returnToWorks() {
  if (/^\/works(?:\?|$)/.test(window.history.state?.back || '')) router.back()
  else router.push('/works')
}
// 审计 F5：generate 与按钮同一守卫——schema 未取得（含读取中）时不得生成
// 缺少执行环境绑定的工单，即使按钮状态被绕过。
function generate() { if (!schema.value) return; prompt.value = buildMetadataAgentPrompt(items.value.filter(item => selected.value.includes(item.id)), schema.value, window.location.origin, { mode:mode.value, focus:focus.value, materials:materialsList.value }); copied.value = false }
async function copy() { try { await navigator.clipboard.writeText(prompt.value); copied.value = true } catch { copied.value = false; alert('复制失败，请在文本框中手动全选复制') } }
function pretty(value) { return typeof value === 'string' ? value : JSON.stringify(value, null, 2) }
const fieldLabels = { original_title:'原始标题', title_translations:'中文及其他译题', authors:'完整作者', doi:'DOI', arxiv:'arXiv 编号', document_type:'文献类型', language:'语言', date_events:'日期事件', citation_year:'引用年份', original_abstracts:'作者原始摘要', descriptive_overview:'Agent 概述', resources:'主页、代码、数据与补充材料', supports:'字段来源与依据', missing_notes:'缺口与待核查', related_versions:'相关版本', resource_observations:'资源实测', extensions:'扩展记录' }
const fieldLabel = key => fieldLabels[key] || key
const currentAdoptable = computed(() => { const r = detail.value?.records?.[0]; return r?.agent_review_status === 'approved' && r?.content_state === 'stable' && r?.validity_status === 'active' })
async function submitFeedback() { const r = detail.value?.records?.[0]; if (!r) return; writing.value = true;
  try { await openMetadataFeedback({ layer:'metadata', target_id:r.id, target_version:r.version, work_id:detailItem.value.id, explicit_claim:feedbackText.value.trim() }); feedbackText.value = ''; await showDetail(detailItem.value); actionMessage.value = '质疑已登记；请生成补全/修订工单交给 Agent 处理。' }
  catch (e) { actionMessage.value = e.detail || e.message } finally { writing.value = false }
}
async function adopt(decision) { const r = detail.value?.records?.[0]; if (!r) return; writing.value = true;
  try { await adoptMetadataRecord(r.id, { decision, actor_id:actorId.value.trim(), note:adoptionNote.value.trim() }); await showDetail(detailItem.value); actionMessage.value = decision === 'adopted' ? '已记录您的采纳判断。' : '已记录不采纳判断。' }
  catch (e) { actionMessage.value = e.detail || e.message } finally { writing.value = false }
}
watch(includeStable, value => { if (!value) selected.value = selected.value.filter(id => items.value.find(item => item.id === id)?.status !== 'stable') })
watch(() => route.query.work_id, () => { if (data.value) openRequestedDetail() })
onMounted(load)
</script>

<style scoped>
.metadata-space{max-width:1480px;margin:auto;color:#263330}.intro,.detail-heading{display:flex;justify-content:space-between;align-items:flex-start;gap:20px}.intro h1{margin:4px 0}.intro p{max-width:950px;line-height:1.7}.intro small{color:#468475;letter-spacing:.12em}.metadata-space button,.metadata-space select,.metadata-space input,.metadata-space textarea{font:inherit}.metadata-space button{border:1px solid #c7d8d2;border-radius:8px;background:#fff;padding:7px 12px;cursor:pointer}.metadata-space button:disabled{opacity:.5;cursor:not-allowed}.flow,.hint{background:#edf5f1;border-radius:9px;padding:12px 16px;line-height:1.6}.flow b{padding:0 10px;color:#377e68}.counts,.controls,.prompt-controls,.adoption{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:16px 0}.counts span{border:1px solid #d9e7e1;border-radius:8px;padding:9px 13px;background:#fff}.controls input[type=search]{min-width:290px}.controls input:not([type=checkbox]),.controls select,.prompt-controls input,.prompt-controls select,.adoption input{border:1px solid #ccd8d3;border-radius:7px;padding:8px;min-height:38px}.prompt-controls input{flex:1;min-width:260px}.table-wrap{overflow:auto;background:#fff;border:1px solid #e0e6e2;border-radius:10px}.table-wrap table{width:100%;border-collapse:collapse;min-width:850px}.table-wrap th,.table-wrap td{padding:11px 12px;text-align:left;border-bottom:1px solid #edf0ee;vertical-align:top}.table-wrap small,.feedback small{display:block;color:#71827a;margin-top:4px;overflow-wrap:anywhere}.table-wrap td strong{display:block}.table-wrap td:last-child{white-space:nowrap}.table-wrap td:last-child>*{margin-right:10px}.state{font-weight:600}.state.stable{color:#177759}.state.pending,.state.conflict{color:#a56a23}.state.waiting_parse,.state.excluded{color:#777}.prompt-box,.detail-box{background:#fff;border:1px solid #dfe9e3;border-radius:12px;padding:18px;margin-top:22px}.prompt-box h2,.detail-box h2{margin:0}.prompt-box h2 small{font-weight:400;color:#71827a}.prompt-box textarea,.human-actions textarea{width:100%;box-sizing:border-box;border:1px solid #cbd9d1;border-radius:8px;padding:12px;line-height:1.55;resize:vertical}.alert{background:#fff1ea;color:#8c3a22;padding:12px;border-radius:8px}.record{border-top:1px solid #e2e8e5;margin-top:16px;padding-top:12px}.record h3 span{font-size:.8em;font-weight:400;color:#678}.record>p{color:#74827a}.field{display:grid;grid-template-columns:190px minmax(0,1fr);border-top:1px solid #eef1ef;padding:9px 0}.field strong{overflow-wrap:anywhere}.field pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:0;font:inherit}.feedback{padding:10px;border-bottom:1px solid #edf0ee}.human-actions{border-top:1px solid #dfe9e3;margin-top:18px}.empty{padding:24px;text-align:center}
@media(max-width:760px){.intro{display:block}.field{display:block}.controls input[type=search]{min-width:0;width:100%}}
.pager{display:flex;align-items:center;gap:12px;margin:12px 0}.record summary{cursor:pointer;font-weight:600;padding:8px 0}.field strong small{display:block;font-weight:400;color:#819087}.state.quarantined{color:#777}
.detail-heading > div { display: flex; gap: 8px; flex-wrap: wrap; }
.detail-box { scroll-margin-top: 70px; }
</style>
