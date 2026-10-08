<template>
  <section class="coverage-panel" aria-label="文献处理态势">
    <header><div><small>COLLECTION COVERAGE</small><h3>文献处理态势</h3></div><button @click="load" :disabled="loading">{{ loading ? '加载中…' : '刷新' }}</button></header>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-else-if="data">
      <div class="coverage-flow">
        <router-link to="/works"><span>01 · 已入库</span><strong>{{ data.works }}<small>篇</small></strong><p>正常 {{ data.active_works }} · 隔离 {{ data.quarantined_works }}</p></router-link>
        <router-link to="/pipeline"><span>02 · 正常文献有可用解析</span><strong>{{ data.parsed_works }}<small> / {{ data.active_works }} 篇</small></strong><progress :value="data.parsed_works" :max="data.active_works || 1" aria-label="正常文献解析覆盖率"/><p>其余 {{ data.without_usable_parse }} 篇尚无匹配的可用解析</p></router-link>
        <div><span>03 · 解析质量核查</span><strong class="quality-note">按批次查看</strong><p>文件存在与内容正确分开统计；全库质量结论尚未汇总。</p></div>
      </div>
      <p class="scope">按文献去重计数；{{ data.sources }} 份来源文件，正常文献中有 {{ data.active_sources }} 份活跃来源，其中 {{ data.parsed_sources }} 份匹配成功解析且 Markdown 文件存在。仅检查文件存在，不代表图表、公式或参考文献完整。</p>
      <h4>研究纳入与核查</h4>
      <p v-if="!data.research.available">{{ data.research.error || '研究库尚未配置。' }}</p>
      <p v-else-if="!data.research.batches.length">尚无研究批次。</p>
      <div class="batch-grid">
        <router-link v-for="batch in data.research.batches" :key="batch.id" :to="{path:'/research',query:{batch_id:batch.id}}" class="batch-card" :class="{ historical: batch.is_current_round === false }">
          <strong>{{ batch.name || batch.id }}</strong><small>{{ batch.id }}</small>
          <p class="round-state">{{ batch.is_current_round === false ? `历史轮次 · 后继 ${batch.successor_batch_ids?.[0] || '已存在'}` : `当前轮次 · ${batchStatus(batch.status)}` }}</p>
          <div class="batch-counts"><span>纳入 <b>{{ batch.works }}</b></span><span>原文记录 <b>{{ batch.source_records }}</b></span><span>解释记录 <b>{{ batch.interpretations }}</b></span><span>解释待回查 <b>{{ batch.stale }}</b></span></div>
          <div v-if="batch.usable_items !== undefined" class="batch-counts"><span>可用基线 <b>{{ batch.usable_items }}</b></span><span v-for="(n, state) in batch.interpretation_content_states" :key="state">{{ contentLabel(state) }} <b>{{ n }}</b></span></div>
          <p>解析质量：已通过 {{ batch.parse_quality.passed || 0 }} · 未检查 {{ batch.parse_quality.unchecked || 0 }} · 未通过 {{ batch.parse_quality.failed || 0 }}（按批次材料计）</p>
          <p>原文 Agent 审阅通过 {{ batch.source_reviewed }} 条 · 查看批次 →</p>
        </router-link>
      </div>
      <p v-if="data.research.consumption_rule" class="scope">{{ data.research.consumption_rule }}</p>
      <div class="citation-status">
        <h4>参考文献引用图谱 · {{ citationTitle }}</h4>
        <p v-if="data.research.citation_graph?.available">
          正式研究库现有引用对象 {{ data.research.citation_graph.references }} 条、已匹配 {{ data.research.citation_graph.matched_references }} 条、引用边 {{ data.research.citation_graph.edges }} 条，其中已核验 {{ data.research.citation_graph.verified_edges }} 条。引用对象从候选到匹配需快照原文锚点证据。
        </p>
        <p v-else>当前研究库尚未初始化引用图谱表。</p>
        <p>另有 {{ relationCount }} 条版本、译本等文献身份关系；这些关系不是论文引用边。</p>
        <router-link to="/relations">查看文献身份关系 →</router-link>
      </div>
    </template>
    <p v-else>正在读取文献处理状态…</p>
  </section>
</template>
<script setup>
import { computed, onMounted, ref } from 'vue'
const data = ref(null), error = ref(''), loading = ref(false)
const relationCount = computed(() => Object.values(data.value?.relations || {}).reduce((a,b)=>a+b,0))
const citationTitle = computed(() => {
  const graph = data.value?.research?.citation_graph
  if (!graph?.available) return '尚未初始化'
  return graph.verified_edges > 0 ? '已有正式核验边' : '链路已就绪，正式库暂无数据'
})
const CONTENT_LABELS = { needs_completion: '待补全', needs_review: '待审查', stable: '稳定' }
function contentLabel(state) { return CONTENT_LABELS[state] || state }
const BATCH_STATUS_LABELS = { planned: '待执行', running: '执行中', completed: '已完成', completed_with_errors: '完成但有异常', failed: '失败' }
function batchStatus(status) { return BATCH_STATUS_LABELS[status] || status || '状态未记录' }
async function load() {
  loading.value=true; error.value=''
  try {
    const response=await fetch('/api/overview')
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    data.value=await response.json()
  } catch { error.value='暂时无法读取处理态势，请点击刷新重试。' }
  finally { loading.value=false }
}
onMounted(load)
</script>
<style scoped>
.coverage-panel{padding:24px;margin:22px 0;border:1px solid var(--border);border-radius:16px;background:var(--bg-surface)}
header{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:18px}header small{font-size:10px;color:var(--accent);letter-spacing:.08em}h3{font-size:20px;margin-top:5px}button{padding:7px 14px;border:1px solid var(--border);border-radius:8px;background:var(--bg-page);cursor:pointer}
.coverage-flow{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.coverage-flow>a,.coverage-flow>div{padding:18px;border-radius:12px;background:var(--bg-page);color:var(--text-primary);text-decoration:none;min-width:0}.coverage-flow span{font-size:12px;color:var(--text-secondary)}.coverage-flow strong{display:block;font-size:30px;margin:12px 0}.coverage-flow strong small{font-size:13px;font-weight:400;margin-left:6px}.coverage-flow .quality-note{font-size:21px}p{font-size:12px;line-height:1.8;color:var(--text-secondary);margin:8px 0}progress{width:100%;height:9px;accent-color:var(--accent)}.scope{margin:14px 0 22px}h4{font-size:14px;margin-bottom:10px}.batch-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,360px),1fr));gap:12px}.batch-card{display:block;padding:16px;border:1px solid var(--border);border-radius:12px;color:var(--text-primary);text-decoration:none}.batch-card.historical{opacity:.72}.batch-card>small{display:block;color:var(--text-tertiary);margin:5px 0 8px;overflow-wrap:anywhere}.round-state{font-weight:600;color:var(--accent);margin-bottom:12px}.batch-card.historical .round-state{color:var(--text-tertiary)}.batch-counts{display:flex;flex-wrap:wrap;gap:12px;font-size:12px}.batch-counts b{font-size:18px;margin-left:4px}.citation-status{border-top:1px solid var(--border);margin-top:22px;padding-top:18px}.citation-status a{font-size:12px;color:var(--accent)}
@media(max-width:850px){.coverage-flow{grid-template-columns:1fr}.coverage-panel{padding:16px}}
</style>
