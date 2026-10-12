<template>
  <div class="ontology-page">
    <header class="hero">
      <div>
        <span class="kicker">RESEARCH ONTOLOGY</span>
        <h1>研究分类词表·草案</h1>
        <p>把现行词表、试点差异与研究框架讨论放在同一页阅读，同时保留它们不同的事实状态。</p>
      </div>
      <router-link to="/research" class="back-link">返回研究视图</router-link>
    </header>

    <div class="draft-warning"><strong>{{ ontologyDraft.notice }}</strong><span>本页是浏览与维护界面，不会修改研究记录或生产数据。</span></div>
    <div v-if="ontologyDraftResponse?.draft" class="overlay-warning"><strong>当前显示包含词表工作稿 · {{ ontologyDraftResponse.draft.review_status === 'pending' ? '待 Agent 核查' : '仅措辞修改' }}</strong><span>{{ ontologyDraftResponse.draft.review_notice }}</span></div>
    <div v-if="ontologyDraftResponse?.binding_status === 'stale'" class="overlay-warning"><strong>旧词表工作稿未自动套用</strong><span>基础展示配置或机器词表已变化；旧稿仍保留在历史中，需重新核对。</span></div>
    <div class="ontology-edit-toolbar">
      <div><strong>轻量词表工作稿</strong><span>覆盖层优先于页面基线；原机器词表和试点提案保持不变。</span></div>
      <button :disabled="readOnly || !ontologyDraftResponse?.draft || ontologyBusy" :title="readOnly ? '只读部署：写操作被服务端禁用' : ''" type="button" @click="undoOntologyEdit">撤回上次修改</button>
      <small v-if="ontologyMessage">{{ ontologyMessage }}</small>
    </div>
    <details v-if="ontologyDraftResponse?.history?.length" class="ontology-history"><summary>查看词表工作稿历史（{{ ontologyDraftResponse.history.length }}）</summary><ul><li v-for="event in ontologyDraftResponse.history" :key="`${event.revision}-${event.action}`"><span>{{ event.action === 'undo' ? '撤回' : '保存' }}</span><code>r{{ event.revision }} · {{ event.at }}</code></li></ul></details>

    <nav class="section-nav" aria-label="页内导航">
      <a href="#framework">整体框架</a><a href="#vocabulary">概念词表</a><a href="#comparison">来源对照</a><a href="#maintenance">来源与维护</a>
    </nav>

    <section id="framework" class="panel">
      <div class="section-heading"><span>01</span><div><h2>整体框架</h2><p>已实现字段与仍在科学验证的讨论建议分开显示。</p></div></div>
      <div class="status-columns">
        <article class="status-card implemented">
          <small>当前已实现</small>
          <h3>两条独立研究坐标 + 受控概念</h3>
          <ul>
            <li><strong>更新对象：</strong>参数、harness、混合、无更新或不明确。</li>
            <li><strong>研究作用：</strong>测量、诱发、解释、缓解、治理或理论分析。</li>
            <li><strong>风险映射：</strong>12 个现行概念；解释记录另存部署条件、证据边界与分类问题。</li>
            <li>研究对象、实际干预和观察接口不能互相代替：使用 API 不自动等于研究了 harness 优化。</li>
          </ul>
        </article>
        <article class="status-card proposed">
          <small>本轮讨论形成的迭代方向 · 继续验证</small>
          <h3>参数内循环与 harness 外循环</h3>
          <div class="loops">
            <div><strong>参数内循环</strong><span>预训练、后训练、RL、SFT、蒸馏、持续学习等参数变化</span></div>
            <div><strong>harness 外循环</strong><span>上下文、记忆、工具、权限、编排、工作流与监控配置变化</span></div>
          </div>
          <p>两条循环都要记录人类设计反馈，以及外部诱导或指令变化；它们是研究对象坐标，不是风险类别本身。</p>
        </article>
      </div>
      <div class="boundary-grid">
        <div><strong>目标、价值与奖励</strong><span>目标对齐、价值对齐、目标/奖励指定、目标形成与目标泛化分别记录，不凭行为偏离直接选定原因。</span></div>
        <div><strong>形成、更新与表现</strong><span>参数或 harness 更新与纯推理期观察分开；固定系统仍可能在长程执行中累积风险。</span></div>
        <div><strong>运行时与部署</strong><span>覆盖干预、关停、遏制、恢复，以及环境变化、反馈时延、权限、不可逆资源和多智能体耦合。</span></div>
        <div><strong>研究位置与作用</strong><span>“研究发生在哪里”与“研究用于测量、解释还是缓解”等作用分开，避免单标签压平。</span></div>
      </div>
    </section>

    <section id="vocabulary" class="panel">
      <div class="section-heading"><span>02</span><div><h2>概念词表</h2><p>12 个现行基线概念 + 1 个试点新增概念；按概念性质分组，不混成单层标签清单。</p></div></div>
      <div class="position-legend">
        <strong>循环位置是概念层默认研究定位，尚待逐项验证</strong>
        <span>形成／发生 ≠ 表现／观测 ≠ 影响；多选表示可能跨位置，不表示某篇论文已完成相应训练或支架更新。</span>
        <span>“固定参数与 harness·推理/任务执行”是表现环节，不自动算作 harness 更新。</span>
      </div>
      <form v-if="editingConcept" class="ontology-editor" @submit.prevent="saveOntologyEdit">
        <header><div><small>EDITABLE OVERLAY</small><h3>编辑：{{ editingConcept.zh }}</h3></div><button type="button" @click="cancelOntologyEdit">取消</button></header>
        <label><span>修改性质</span><select v-model="ontologyForm.change_kind"><option value="wording">小措辞更改</option><option value="substantive">事实／定义边界／分类位置改动（待核查）</option></select></label>
        <label><span>中文名称</span><input v-model="ontologyForm.zh" /></label>
        <label><span>定义</span><textarea v-model="ontologyForm.definition" rows="3"></textarea></label>
        <label><span>包括（一行一项）</span><textarea v-model="ontologyForm.includes" rows="3"></textarea></label>
        <label><span>不包括（一行一项）</span><textarea v-model="ontologyForm.excludes" rows="3"></textarea></label>
        <fieldset v-for="field in positionFields" :key="field.key">
          <legend>{{ field.label }}</legend>
          <label v-for="(label, key) in ontologyDraft.locationLabels" :key="key"><input v-model="ontologyForm.position[field.key]" type="checkbox" :value="key" /><span>{{ label }}</span></label>
        </fieldset>
        <label><span>循环位置说明</span><textarea v-model="ontologyForm.position.note" rows="2"></textarea></label>
        <div class="ontology-review-request"><strong>请 Agent 核查（仅保存待办）</strong><select v-model="ontologyForm.review_field"><option value="">选择字段</option><option value="zh">中文名称</option><option value="definition">定义</option><option value="includes">包括</option><option value="excludes">不包括</option><option value="position">循环位置</option></select><input v-model="ontologyForm.review_request" placeholder="用一句话说明要核查什么" /></div>
        <footer><button type="submit" :disabled="readOnly || ontologyBusy" :title="readOnly ? '只读部署：写操作被服务端禁用' : ''">保存工作稿</button><button type="button" @click="cancelOntologyEdit">取消</button><span>用户无需填写版本号；保存自动记入历史。</span></footer>
      </form>
      <div v-for="group in conceptGroups" :key="group.key" class="concept-group">
        <h3>{{ group.label }} <small>{{ group.items.length }}</small></h3>
        <div class="table-wrap">
          <table>
            <thead><tr><th>概念</th><th>状态 / 版本差异</th><th>定义</th><th>循环位置（初步定位）</th><th>包括</th><th>不包括</th></tr></thead>
            <tbody>
              <tr v-for="concept in group.items" :key="concept.id">
                <td><strong>{{ concept.zh }}</strong><span>{{ concept.en }}</span><code>{{ concept.id }}</code><button class="concept-edit" type="button" :disabled="readOnly" :title="readOnly ? '只读部署：写操作被服务端禁用' : ''" @click="openOntologyEdit(concept)">编辑工作稿</button></td>
                <td><b :class="concept.pilotOnly ? 'pilot' : 'baseline'">{{ concept.pilotOnly ? '试点新增·继续验证' : '现行基线' }}</b><p v-if="concept.difference">{{ concept.difference }}</p></td>
                <td>{{ concept.definition }}</td>
                <td class="position-cell">
                  <template v-if="concept.position.coverage">
                    <div class="position-row"><strong>作用／覆盖</strong><span><i v-for="key in concept.position.coverage" :key="key">{{ locationLabel(key) }}</i></span></div>
                  </template>
                  <template v-else>
                    <div class="position-row"><strong>形成／发生</strong><span><i v-for="key in concept.position.formation" :key="key">{{ locationLabel(key) }}</i></span></div>
                    <div class="position-row"><strong>表现／观测</strong><span><i v-for="key in concept.position.manifestation" :key="key">{{ locationLabel(key) }}</i></span></div>
                    <div class="position-row"><strong>影响</strong><span><i v-for="key in concept.position.impact" :key="key">{{ locationLabel(key) }}</i></span></div>
                  </template>
                  <p>{{ concept.position.note }}</p>
                </td>
                <td><ul><li v-for="item in concept.includes" :key="item">{{ item }}</li></ul></td>
                <td><ul><li v-for="item in concept.excludes" :key="item">{{ item }}</li></ul></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>

    <section id="released" class="panel">
      <div class="section-heading"><span>02·R</span><div><h2>已发布组合（当前发布包）</h2><p>本区块直接读取发布组合接口：页面展示的概念与受控值即提交校验实际使用的同一份内容。</p></div></div>
      <p v-if="compositionError" class="edit-error">无法读取已发布组合：{{ compositionError }}</p>
      <template v-else-if="releasedComposition">
        <div class="maintenance-note">
          <strong>{{ releasedComposition.release_id }}</strong>
          <p>发布时间 {{ releasedComposition.released_at }} · 契约版本 v{{ releasedComposition.contract_version }} · 已发布概念 {{ releasedComposition.ontology?.concepts?.length || 0 }} 个（本体版本 {{ releasedComposition.ontology?.version }}）· 受控词表 {{ Object.keys(releasedComposition.controlled_vocabularies || {}).length }} 组（§13.4 单一权威，提交校验同源）。</p>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>概念 ID</th><th>名称</th><th>定义</th><th>父概念</th><th>评审卡去向</th></tr></thead>
            <tbody>
              <tr v-for="concept in releasedComposition.ontology?.concepts || []" :key="concept.id">
                <td><code>{{ concept.id }}</code></td>
                <td><strong>{{ concept.label || concept.id }}</strong></td>
                <td>{{ concept.definition }}</td>
                <td><code v-if="concept.parents?.length">{{ concept.parents.join(', ') }}</code><span v-else>—</span></td>
                <td>{{ cardStatusFor(concept.id) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <details class="ontology-history">
          <summary>受控词表（{{ Object.keys(releasedComposition.controlled_vocabularies || {}).length }} 组，提交校验即用此内容）</summary>
          <ul>
            <li v-for="(values, name) in releasedComposition.controlled_vocabularies" :key="name">
              <code>{{ name }}</code>：<span>{{ values.join('、') }}</span>
            </li>
          </ul>
        </details>
      </template>
      <p v-else>正在读取已发布组合…</p>
    </section>

    <section id="comparison" class="panel">
      <div class="section-heading"><span>03</span><div><h2>旧框架、现行实现与讨论建议</h2><p>这是来源对照，不声称完成理论重构，也不声称当前 12 概念完整继承 v1.7。</p></div></div>
      <div class="comparison-grid">
        <article>
          <small>旧 v1.7 · 来源参照</small><h3>自主失控分类框架</h3>
          <p><strong>三维度：</strong>执行自主性、目标偏离、纠偏抵抗。</p>
          <p><strong>四类别：</strong>监督失效、信息遮蔽、实质扩张、外部延伸。</p>
          <p>保留其能力—倾向、行为—机制与归因的区分，以及评估有效性约束。</p>
        </article>
        <article>
          <small>当前已实现</small><h3>12 概念 + 独立研究坐标</h3>
          <p>概念覆盖风险现象、控制条件、证据边界与治理；另以更新对象、研究作用和映射状态定位研究记录。</p>
          <p><strong>关系：</strong>选择性吸收旧框架问题意识，但没有完整继承或一一映射。</p>
        </article>
        <article>
          <small>讨论建议 · 继续验证</small><h3>双循环与条件化风险描述</h3>
          <p>建议同时描述条件与诱因、可观察现象、候选机制、控制响应、后果及证据边界，而不是让双循环独自承担风险分类。</p>
          <p>不把旧 v1.7 的强共现定义施加到所有部署事故，也不把 I/II 是 III/IV 持续前提等争议命题当作已证事实。</p>
        </article>
      </div>
    </section>

    <section id="maintenance" class="panel">
      <div class="section-heading"><span>04</span><div><h2>来源与维护</h2><p>轻量维护，不建立提案审批系统。</p></div></div>
      <div class="maintenance-note">
        <strong>当前维护方式</strong>
        <p>基线名称、定义、概念性质与结构化位置字段仍由同一个中文展示配置维护；浏览器编辑保存到隔离的持久化覆盖层，并自动记录历史，覆盖层显示优先于页面基线。用户无需手工编号版本。工作稿不会发布成机器词表，取消不写入，撤回也不删除审计历史。</p>
      </div>
      <div class="source-list">
        <div v-for="source in ontologyDraft.sources" :key="source.path"><strong>{{ source.label }}</strong><code>{{ source.path }}</code><span>{{ source.role }}</span></div>
      </div>
    </section>
  </div>
</template>

<script setup>

import { useRuntimeMode } from '../composables/useRuntimeMode'
const { readOnly } = useRuntimeMode()
import { computed, onMounted, ref } from 'vue'
import { ontologyDraft } from '../data/research-ontology-draft'
import { getOntologyDraft, saveOntologyDraft, undoOntologyDraft, getReleasedComposition, getOntologyReviewCards } from '../api'

const releasedComposition = ref(null)
const compositionError = ref('')
const reviewCards = ref([])
const cardStatusByConcept = ref({})

const ontologyDraftResponse = ref(null)
const editingConcept = ref(null)
const ontologyBusy = ref(false)
const ontologyMessage = ref('')
const ontologyForm = ref({ change_kind: 'wording', zh: '', definition: '', includes: '', excludes: '', position: {}, review_field: '', review_request: '' })
const displayConcepts = computed(() => ontologyDraft.concepts.map(concept => {
  const override = ontologyDraftResponse.value?.draft?.overrides?.[concept.id]
  if (!override) return concept
  return { ...concept, ...override, position: { ...concept.position, ...(override.position || {}) } }
}))
const conceptGroups = computed(() => Object.entries(ontologyDraft.natureLabels).map(([key, label]) => ({
  key,
  label,
  items: displayConcepts.value.filter(item => item.nature === key),
})))

const positionFields = computed(() => editingConcept.value?.position?.coverage
  ? [{ key: 'coverage', label: '作用／覆盖位置' }]
  : [{ key: 'formation', label: '形成／发生位置' }, { key: 'manifestation', label: '表现／观测位置' }, { key: 'impact', label: '影响位置' }])

function locationLabel(key) {
  return ontologyDraft.locationLabels[key] || '未知／尚未识别'
}

async function loadOntologyOverlay() {
  ontologyMessage.value = ''
  try {
    ontologyDraftResponse.value = await getOntologyDraft()
  } catch (error) {
    ontologyMessage.value = error?.status === 409 ? '试点编辑入口尚未启用；当前只读。' : `无法读取工作稿：${error?.message || '请求失败'}`
  }
}

function openOntologyEdit(concept) {
  editingConcept.value = concept
  const position = {}
  for (const field of concept.position.coverage ? ['coverage'] : ['formation', 'manifestation', 'impact']) position[field] = [...(concept.position[field] || [])]
  position.note = concept.position.note || ''
  ontologyForm.value = {
    change_kind: 'wording', zh: concept.zh, definition: concept.definition,
    includes: (concept.includes || []).join('\n'), excludes: (concept.excludes || []).join('\n'),
    position, review_field: '', review_request: '',
  }
  ontologyMessage.value = ''
  document.getElementById('vocabulary')?.scrollIntoView({ behavior: 'smooth' })
}

function cancelOntologyEdit() {
  editingConcept.value = null
  ontologyMessage.value = '已取消：没有写入任何内容。'
}

async function saveOntologyEdit() {
  if (!editingConcept.value) return
  if (ontologyForm.value.review_request.trim() && !ontologyForm.value.review_field) {
    ontologyMessage.value = '请先选择需要 Agent 核查的具体字段。'
    return
  }
  ontologyBusy.value = true
  try {
    const result = await saveOntologyDraft({
      expected_revision: ontologyDraftResponse.value?.revision || 0,
      concept_id: editingConcept.value.id,
      change_kind: ontologyForm.value.change_kind,
      patch: {
        zh: ontologyForm.value.zh,
        definition: ontologyForm.value.definition,
        includes: ontologyForm.value.includes.split(/\r?\n/).map(item => item.trim()).filter(Boolean),
        excludes: ontologyForm.value.excludes.split(/\r?\n/).map(item => item.trim()).filter(Boolean),
        position: ontologyForm.value.position,
      },
      review_request: ontologyForm.value.review_request.trim()
        ? `[${ontologyForm.value.review_field || '未指定字段'}] ${ontologyForm.value.review_request.trim()}` : '',
    })
    ontologyDraftResponse.value = result
    editingConcept.value = null
    ontologyMessage.value = result.draft?.review_status === 'pending'
      ? '词表工作稿已保存并记入历史；核查待办尚未触发或完成。' : '词表措辞工作稿已保存并记入历史。'
  } catch (error) {
    ontologyMessage.value = `保存失败：${error?.detail || error?.message || '请求失败'}`
  } finally {
    ontologyBusy.value = false
  }
}

async function undoOntologyEdit() {
  if (!ontologyDraftResponse.value?.draft) return
  ontologyBusy.value = true
  try {
    ontologyDraftResponse.value = await undoOntologyDraft(ontologyDraftResponse.value.revision)
    editingConcept.value = null
    ontologyMessage.value = '已撤回上次保存；审计历史仍然保留。'
  } catch (error) {
    ontologyMessage.value = `撤回失败：${error?.detail || error?.message || '请求失败'}`
  } finally {
    ontologyBusy.value = false
  }
}

async function loadReleasedComposition() {
  compositionError.value = ''
  try {
    releasedComposition.value = await getReleasedComposition()
  } catch (error) {
    compositionError.value = error?.message || '请求失败'
  }
  try {
    const cards = await getOntologyReviewCards()
    const byConcept = {}
    for (const card of cards?.cards || []) {
      if (card.id) byConcept[card.id] = `${card.status || '未知'} · ${card.destination || card.card || ''}`
    }
    cardStatusByConcept.value = byConcept
    reviewCards.value = cards?.cards || []
  } catch {
    cardStatusByConcept.value = {}
  }
}

function cardStatusFor(conceptId) {
  return cardStatusByConcept.value[conceptId] || '—'
}

onMounted(() => {
  loadOntologyOverlay()
  loadReleasedComposition()
})
</script>

<style scoped>
.ontology-page { width: min(1480px, 100%); margin: 0 auto; }
.hero { display: flex; align-items: end; justify-content: space-between; gap: 24px; margin-bottom: 18px; }
.kicker { color: var(--accent); font-size: 9px; font-weight: 680; letter-spacing: .11em; }
.hero h1 { margin-top: 5px; font-size: 29px; font-weight: 620; letter-spacing: -.035em; }
.hero p { max-width: 760px; margin-top: 7px; color: var(--text-secondary); font-size: 12px; }
.back-link, .section-nav a { color: var(--accent-ink); font-size: 12px; font-weight: 600; }
.draft-warning { display: flex; flex-direction: column; gap: 4px; padding: 13px 15px; color: var(--warn-fg); border: 1px solid var(--warn-border); border-radius: var(--radius-lg); background: var(--warn-bg); }
.draft-warning strong { font-size: 13px; }.draft-warning span { font-size: 11px; }
.overlay-warning { display: flex; flex-direction: column; gap: 3px; padding: 11px 14px; margin-top: 9px; color: var(--warn-fg); border: 1px solid var(--warn-border); border-radius: var(--radius-md); background: var(--warn-bg); }.overlay-warning strong { font-size: 11px; }.overlay-warning span { font-size: 10px; }
.ontology-edit-toolbar { display: flex; align-items: center; gap: 9px; padding: 10px 12px; margin-top: 9px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-surface); }.ontology-edit-toolbar > div { display: flex; min-width: 0; flex: 1; flex-direction: column; }.ontology-edit-toolbar strong { font-size: 11px; }.ontology-edit-toolbar span { color: var(--text-tertiary); font-size: 10px; }.ontology-edit-toolbar button, .ontology-editor button, .concept-edit { padding: 5px 8px; color: var(--accent-ink); border: 1px solid var(--border-strong); border-radius: var(--radius-sm); background: var(--bg-surface); cursor: pointer; font-size: 9px; }.ontology-edit-toolbar button:disabled { cursor: not-allowed; opacity: .5; }.ontology-edit-toolbar small { color: var(--info-fg); font-size: 9px; }
.ontology-history { padding: 7px 10px; margin-top: 7px; color: var(--text-secondary); font-size: 10px; }.ontology-history summary { cursor: pointer; }.ontology-history ul { padding-left: 0; margin-top: 5px; list-style: none; }.ontology-history li { display: flex; justify-content: space-between; gap: 10px; padding: 4px 0; border-top: 1px solid var(--border); }.ontology-history code { color: var(--text-tertiary); font-size: 8px; }
.section-nav { position: sticky; top: 76px; z-index: 20; display: flex; flex-wrap: wrap; gap: 8px 20px; padding: 12px 4px; background: rgba(247,247,244,.94); backdrop-filter: blur(10px); }
.panel { padding: 20px; margin-top: 14px; border: 1px solid var(--border); border-radius: var(--radius-xl); background: var(--bg-surface); box-shadow: var(--shadow-sm); scroll-margin-top: 130px; }
.section-heading { display: flex; gap: 11px; align-items: flex-start; margin-bottom: 16px; }.section-heading > span { color: var(--accent); font: 10px var(--font-mono); }.section-heading h2 { font-size: 18px; }.section-heading p { margin-top: 3px; color: var(--text-secondary); font-size: 11px; }
.status-columns, .comparison-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.status-card, .comparison-grid article { padding: 15px; border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--bg-page); }.status-card.implemented { border-top: 3px solid var(--ok); }.status-card.proposed { border-top: 3px solid var(--warn); }
article small { color: var(--text-tertiary); font-size: 9px; font-weight: 650; letter-spacing: .05em; } article h3 { margin: 5px 0 9px; font-size: 14px; } article p, article li { color: var(--text-secondary); font-size: 12px; line-height: 1.65; } article ul { padding-left: 18px; }
.loops { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 10px 0; }.loops div { display: flex; flex-direction: column; gap: 4px; padding: 10px; border-radius: var(--radius-md); background: var(--bg-surface); }.loops strong { font-size: 11px; }.loops span { color: var(--text-secondary); font-size: 11px; line-height: 1.55; }
.boundary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 9px; margin-top: 12px; }.boundary-grid div { display: flex; flex-direction: column; gap: 5px; padding: 11px; border-left: 3px solid var(--border-strong); background: var(--bg-page); }.boundary-grid strong { font-size: 11px; }.boundary-grid span { color: var(--text-secondary); font-size: 11px; line-height: 1.55; }
.concept-group + .concept-group { margin-top: 22px; }.concept-group h3 { margin-bottom: 8px; font-size: 14px; }.concept-group h3 small { color: var(--text-tertiary); font-size: 10px; }
.position-legend { display: flex; flex-direction: column; gap: 3px; padding: 11px 13px; margin-bottom: 18px; color: var(--info-fg); border: 1px solid var(--info-border); border-radius: var(--radius-md); background: var(--info-bg); }.position-legend strong { font-size: 11px; }.position-legend span { color: var(--text-secondary); font-size: 10px; }
.ontology-editor { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; padding: 14px; margin-bottom: 18px; border: 1px solid var(--accent-mute); border-radius: var(--radius-lg); background: var(--accent-subtle); }.ontology-editor header, .ontology-editor footer, .ontology-review-request { grid-column: 1 / -1; }.ontology-editor header { display: flex; align-items: center; justify-content: space-between; }.ontology-editor header small { color: var(--accent); font-size: 8px; letter-spacing: .08em; }.ontology-editor header h3 { margin-top: 2px; font-size: 14px; }.ontology-editor label { display: grid; gap: 4px; color: var(--text-secondary); font-size: 10px; }.ontology-editor input, .ontology-editor textarea, .ontology-editor select { width: 100%; padding: 7px 8px; color: var(--text-primary); border: 1px solid var(--border-strong); border-radius: var(--radius-sm); background: var(--bg-surface); font: 11px/1.5 var(--font-sans); }.ontology-editor textarea { resize: vertical; }.ontology-editor fieldset { display: flex; flex-wrap: wrap; align-content: flex-start; gap: 5px; padding: 9px; border: 1px solid var(--accent-mute); border-radius: var(--radius-md); background: rgba(255,255,255,.55); }.ontology-editor legend { padding: 0 4px; color: var(--accent-ink); font-size: 9px; }.ontology-editor fieldset label { display: flex; width: auto; flex-direction: row; align-items: center; gap: 4px; padding: 3px 5px; border: 1px solid var(--border); border-radius: 999px; background: var(--bg-surface); }.ontology-editor fieldset input { width: auto; }.ontology-review-request { display: grid; grid-template-columns: 180px 190px minmax(0, 1fr); align-items: center; gap: 6px; padding: 9px; border-left: 3px solid var(--info); background: var(--info-bg); }.ontology-review-request strong { color: var(--info-fg); font-size: 9px; }.ontology-editor footer { display: flex; align-items: center; gap: 7px; }.ontology-editor footer button:first-child { color: #fff; border-color: var(--accent); background: var(--accent); }.ontology-editor footer span { color: var(--text-tertiary); font-size: 9px; }.concept-edit { margin-top: 7px; }
.table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: var(--radius-lg); } table { width: 100%; min-width: 1450px; border-collapse: collapse; } th, td { padding: 11px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; font-size: 11px; line-height: 1.6; } th { color: var(--text-secondary); background: var(--bg-page); font-size: 10px; } tbody tr:last-child td { border-bottom: 0; } td:first-child { width: 180px; } td:nth-child(2) { width: 210px; } td:nth-child(3) { width: 230px; } td:nth-child(4) { width: 320px; } td strong, td span, td code { display: block; } td span { margin-top: 2px; color: var(--text-secondary); } td code { margin-top: 4px; color: var(--text-tertiary); font-size: 9px; overflow-wrap: anywhere; } td ul { padding-left: 17px; margin: 0; } td b { display: inline-block; padding: 2px 6px; border-radius: 999px; font-size: 9px; }.baseline { color: var(--ok-fg); background: var(--ok-bg); }.pilot { color: var(--warn-fg); background: var(--warn-bg); } td p { margin-top: 6px; color: var(--text-secondary); }
.position-cell { min-width: 300px; }.position-row + .position-row { margin-top: 7px; }.position-row > strong { color: var(--text-secondary); font-size: 9px; }.position-row > span { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 3px; }.position-row i { padding: 2px 6px; color: var(--accent-ink); border: 1px solid var(--accent-mute); border-radius: 999px; background: var(--accent-subtle); font-size: 9px; font-style: normal; line-height: 1.4; }.position-cell p { padding-top: 6px; border-top: 1px dashed var(--border); font-size: 10px; line-height: 1.55; }
.comparison-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.maintenance-note { padding: 13px 15px; margin-bottom: 12px; border-left: 3px solid var(--accent); background: var(--accent-subtle); }.maintenance-note strong { font-size: 12px; }.maintenance-note p { margin-top: 4px; color: var(--text-secondary); font-size: 11px; line-height: 1.6; }
.source-list { display: grid; gap: 1px; background: var(--border); border: 1px solid var(--border); border-radius: var(--radius-md); overflow: hidden; }.source-list div { display: grid; grid-template-columns: 220px minmax(0, 1fr) 190px; gap: 12px; padding: 10px 12px; background: var(--bg-surface); }.source-list strong { font-size: 11px; }.source-list code { overflow-wrap: anywhere; color: var(--text-secondary); font-size: 10px; }.source-list span { color: var(--text-tertiary); font-size: 10px; }
@media (max-width: 900px) { .boundary-grid { grid-template-columns: 1fr 1fr; }.comparison-grid { grid-template-columns: 1fr; }.source-list div { grid-template-columns: 1fr; gap: 3px; } }
@media (max-width: 620px) { .hero { align-items: flex-start; flex-direction: column; }.status-columns, .loops, .boundary-grid, .ontology-editor { grid-template-columns: 1fr; }.panel { padding: 15px; }.section-nav { top: 68px; }.ontology-edit-toolbar { align-items: stretch; flex-direction: column; }.ontology-review-request { grid-template-columns: 1fr; } }
</style>
