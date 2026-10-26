<template>
  <div class="record-detail-page" :class="{'has-evidence':evidenceOpen}">
    <header class="detail-header">
      <router-link :to="{path:'/research',query:{batch_id:batchId}}">← 返回研究批次</router-link>
      <h1>{{ work?.title || workId }}</h1>
      <p>{{ workId }} · 批次 {{ batchId || '未指定' }} <button @click="load" :disabled="loading">刷新记录</button></p>
    </header>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="loading">正在读取当前记录…</p>
    <div v-if="record" class="detail-layout" :class="{'section-nav-collapsed':sectionNavCollapsed}">
      <nav aria-label="研究记录分区" :class="{collapsed:sectionNavCollapsed}">
        <button class="section-nav-toggle" type="button" :aria-label="sectionNavCollapsed ? '展开分区目录' : '收起分区目录'" :title="sectionNavCollapsed ? '展开分区目录' : '收起分区目录'" @click="sectionNavCollapsed=!sectionNavCollapsed">{{ sectionNavCollapsed ? '›' : '‹' }}</button>
        <strong>当前：{{ activeLabel }}</strong>
        <button v-for="item in sections" :key="item.id" :class="{active:active===item.id}" :aria-current="active===item.id ? 'location' : undefined" @click="jump(item.id)">{{ item.label }}</button>
        <small>右侧独立滚动；点击分区直接定位。</small>
      </nav>
      <main ref="scrollArea" class="record-scroll" aria-label="研究记录内容" tabindex="0" @scroll="updateSection">
        <section id="record-overview" class="overview">
          <h2>状态与来源</h2>
          <p v-for="[label,row] in [['原文记录',record.source_record],['解释记录',record.interpretation]]" :key="label"><strong>{{ label }}</strong> · {{ row?.id || '尚未生成' }} · v{{ row?.version }} · {{ stateLabel(row?.content_state) }} · 独立审查 {{ row?.agent_review_status }} · 人工 {{ row?.human_adoption_status }}</p>
          <p>稳定与人工认可分别记录；新发现的质疑仍需处理，不能仅凭稳定状态推断内容无误。</p>
          <div v-if="feedbackError" class="open-feedback feedback-error" role="alert">
            <strong>质疑清单读取失败</strong>：{{ feedbackError }}
            <button @click="load" :disabled="loading">重试</button>
            <small>正文可读；上方“反馈”区按实际协议另行核对，未读取成功不等于没有质疑。</small>
          </div>
          <div v-else-if="feedback.length" class="open-feedback"><strong>本篇仍有 {{ feedback.length }} 条未闭环质疑</strong><ul><li v-for="item in feedback" :key="item.id">{{ item.layer }} · {{ item.explicit_claim }}（{{ item.id }}）</li></ul></div>
          <p><router-link :to="`/works/${encodeURIComponent(workId)}`">查看文献元数据与文件 →</router-link></p>
          <details><summary>来源与版本标识</summary><pre>{{ JSON.stringify({source:record.source,snapshot:record.snapshot},null,2) }}</pre></details>
        </section>
        <ResearchRecordReadable :record="record" @evidence-state="handleEvidenceState" />
        <section id="record-comparison" class="overview">
          <h2>引用与跨篇比较</h2>
          <button @click="loadComparison('citations')">查看该文献引用图</button>
          <button @click="loadComparison('comparison')">查看批次跨篇比较</button>
          <p v-if="comparisonError" role="alert">{{ comparisonError }}</p>
          <details v-if="comparison" open><summary>查询结果（保留候选/核验状态）</summary><pre>{{ JSON.stringify(comparison,null,2) }}</pre></details>
        </section>
      </main>
    </div>
    <!-- 悬浮任务入口（工单工作包 C）：不遮挡主要内容 -->
    <AgentTaskFab v-if="record" :record="record" initial-mode="organize" />
  </div>
</template>
<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { queryResearch, getWork, getWorkCitations, getBatchComparison, listResearchFeedback } from '../api'
import ResearchRecordReadable from '../components/research/ResearchRecordReadable.vue'
import AgentTaskFab from '../components/research/AgentTaskFab.vue'
const route=useRoute(), record=ref(null),work=ref(null),error=ref(''),loading=ref(false),scrollArea=ref(null)
const active=ref('record-overview'),comparison=ref(null),comparisonError=ref('')
const feedback=ref([])
const evidenceOpen=ref(false),sectionNavCollapsed=ref(false)
const batchId=computed(()=>String(route.query.batch_id || ''))
const workId=computed(()=>String(route.params.workId || ''))
const sections=[{id:'record-overview',label:'状态与来源'},{id:'record-agent-prompt',label:'Agent 任务提示词'},{id:'record-source',label:'原文记录'},{id:'record-interpretation',label:'解释与分类'},{id:'research-draft-editor',label:'建议修改（工作稿）'},{id:'record-evidence',label:'逐条证据'},{id:'record-feedback',label:'质疑与建议'},{id:'record-comparison',label:'引用与跨篇比较'}]
const activeLabel=computed(()=>sections.find(s=>s.id===active.value)?.label || '')
const stateLabel=s=>({stable:'稳定',needs_review:'待核查',needs_completion:'待补全'}[s]||s)
let sequence=0, comparisonRequest=0
const feedbackError=ref('')
async function load(){
  const token=++sequence;error.value='';comparison.value=null;record.value=null;feedback.value=[];feedbackError.value='';loading.value=true
  comparisonRequest++  // 使在途的旧引用/比较请求失效（issue #18）
  if(!batchId.value){error.value='请从研究批次进入，链接需要保留批次信息。';loading.value=false;return}
  try{
    // 主数据=研究记录+Work 元数据；反馈是辅助读取，单独处理（issue #20：
    // 反馈失败不得让已成功的主记录不可读）。
    const [result,detail]=await Promise.all([queryResearch({batch_id:batchId.value,work_id:workId.value,...(route.query.source_id?{source_id:String(route.query.source_id)}:{}),limit:50}),getWork(workId.value)])
    if(token!==sequence)return
    const items=result.items || []
    if(items.length!==1)throw new Error(items.length?'本篇有多个来源，请从批次中的具体记录进入。':'该批次未找到本篇研究记录。')
    record.value={...items[0],batch_id:batchId.value};work.value=detail
    await nextTick();jump('record-overview')
  }catch(e){if(token===sequence)error.value=e.message}finally{if(token===sequence)loading.value=false}
  try{
    const notes=await listResearchFeedback({work_id:workId.value})
    if(token!==sequence)return
    feedback.value=(notes.items||[]).filter(item=>item.status!=='closed')
  }catch(e){if(token===sequence)feedbackError.value=e?.message||'反馈清单读取失败'}
}
function jump(id){const root=scrollArea.value,element=root?.querySelector(`#${id}`);if(root&&element){root.scrollTo({top:element.getBoundingClientRect().top-root.getBoundingClientRect().top+root.scrollTop-12,behavior:'instant'});active.value=id}}
function updateSection(){const root=scrollArea.value;if(!root)return;let current=sections[0].id;for(const s of sections){const e=root.querySelector(`#${s.id}`);if(e&&e.getBoundingClientRect().top<=root.getBoundingClientRect().top+100)current=s.id}active.value=current}
function handleEvidenceState(value){evidenceOpen.value=value;if(value)sectionNavCollapsed.value=true}
// issue #18：引用图/跨篇比较绑定当前记录与请求代次，上一篇的迟到响应
// 不得覆盖当前页。
async function loadComparison(kind){
  const request=++comparisonRequest
  const targetWork=workId.value, targetBatch=batchId.value
  comparisonError.value=''
  try{
    const result=await(kind==='citations'?getWorkCitations(targetWork):getBatchComparison(targetBatch))
    if(request!==comparisonRequest)return
    comparison.value=result
  }catch(e){
    if(request!==comparisonRequest)return
    comparisonError.value=e?.message||'查询失败'
  }
}
onMounted(load)
watch(()=>route.fullPath,load)
</script>
<style scoped>
.record-detail-page{max-width:1400px;margin:auto;min-width:0;transition:padding-right var(--transition-normal),max-width var(--transition-normal)}.record-detail-page.has-evidence{max-width:none;padding-right:clamp(456px,calc(46vw + 16px),776px)}.detail-header h1{font-size:21px;margin:10px 0;overflow-wrap:anywhere}.detail-header p{font-size:12px;color:var(--text-secondary)}
.detail-layout{display:grid;grid-template-columns:170px minmax(0,1fr);gap:16px;margin-top:14px;height:calc(100dvh - 210px);min-height:380px}
nav{display:flex;flex-direction:column;gap:6px;overflow-y:auto;min-width:0}.detail-layout.section-nav-collapsed{grid-template-columns:42px minmax(0,1fr)}nav.collapsed strong,nav.collapsed small,nav.collapsed button:not(.section-nav-toggle){display:none}.section-nav-toggle{font-size:20px;line-height:1;padding:6px}.section-nav-toggle+strong{margin-top:4px}nav strong{font-size:12px;margin-bottom:8px}nav small{font-size:11px;color:var(--text-secondary);margin-top:12px}
button{cursor:pointer;padding:8px 10px;background:var(--bg-surface);color:var(--text-primary);border:1px solid var(--border);border-radius:6px}nav button{text-align:left}.active{color:var(--accent-ink);background:var(--info-bg);border-color:var(--info-border)}
.record-scroll{overflow-y:scroll;overflow-x:hidden;scrollbar-gutter:stable;scrollbar-width:auto;scrollbar-color:#7d918b #e6ece9;padding:0 16px 60px 0;min-width:0;position:relative}.record-scroll::-webkit-scrollbar{width:13px}.record-scroll::-webkit-scrollbar-thumb{background:#7d918b;border:3px solid #e6ece9;border-radius:8px}.record-scroll::-webkit-scrollbar-track{background:#e6ece9}
.overview{padding:16px;border:1px solid var(--border);border-radius:8px;margin-bottom:15px;background:var(--bg-surface);overflow-wrap:anywhere}.overview h2{font-size:16px}.overview p{font-size:12px;line-height:1.7}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px}
.open-feedback{padding:10px;background:var(--warn-bg);color:var(--warn-fg);font-size:12px;line-height:1.7}
.feedback-error{background:#fdeee9;color:#8c3a22;border-left:3px solid #b3402a}
.record-scroll :deep(.layer-title){position:sticky;top:0;z-index:2;background:var(--bg-surface);padding:10px 0}.record-scroll :deep(.readable-layer){scroll-margin-top:12px}
@media(max-width:900px){.record-detail-page.has-evidence{padding-right:0}}
@media(max-width:760px){.detail-layout,.detail-layout.section-nav-collapsed{grid-template-columns:1fr;grid-template-rows:auto minmax(0,1fr);height:calc(100dvh - 190px)}nav,nav.collapsed{flex-direction:row;overflow-x:auto;flex-wrap:nowrap}nav.collapsed button:not(.section-nav-toggle){display:block}nav button{flex:0 0 auto}nav strong,nav small{display:none}.detail-header h1{font-size:16px}}
</style>
