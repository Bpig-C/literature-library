<template>
  <div class="dashboard">
    <section class="hero">
      <div class="hero-copy">
        <div class="hero-kicker"><span></span> GPT‑5.6 协作设计的研究工作台</div>
        <h2>从一个问题出发，<br><em>构建你的学术脉络。</em></h2>
        <p>发现相关研究、审阅关键信息，并将可靠证据沉淀为可持续维护的个人文献库。</p>
        <div class="hero-actions">
          <router-link to="/discovery" class="primary-action"><AppIcon name="spark" /> 开始学术探索</router-link>
          <router-link to="/ingest" class="secondary-action"><AppIcon name="ingest" /> 归档新文献</router-link>
        </div>
      </div>
      <div class="knowledge-orbit" aria-hidden="true">
        <div class="orbit orbit-one"></div><div class="orbit orbit-two"></div>
        <div class="core"><AppIcon name="spark" /></div>
        <span class="node node-one"></span><span class="node node-two"></span><span class="node node-three"></span>
        <small>research<br>context</small>
      </div>
    </section>

    <section class="metrics" aria-label="文献库概况">
      <div class="metric"><strong>{{ stats.total }}</strong><span>已归档文献</span></div>
      <div class="metric"><strong>{{ stats.unread }}</strong><span>待读文献</span></div>
      <div class="metric"><strong>{{ stats.relations }}</strong><span>知识关联</span></div>
      <div class="metric"><strong>{{ stats.quarantined }}</strong><span>隔离项目</span></div>
    </section>

    <div class="dashboard-grid">
      <section class="panel workflow-panel">
        <div class="panel-heading">
          <div><span class="overline">TODAY</span><h3>研究处理队列</h3></div>
          <router-link to="/pipeline">查看完整流程 <span>→</span></router-link>
        </div>
        <div class="queue-list">
          <router-link v-for="item in queueItems" :key="item.to" :to="item.to" class="queue-row">
            <span class="queue-icon"><AppIcon :name="item.icon" /></span>
            <span class="queue-copy"><strong>{{ item.title }}</strong><small>{{ item.description }}</small></span>
            <b>{{ item.count }}</b><i>→</i>
          </router-link>
        </div>
      </section>

      <section class="panel launch-panel">
        <div class="panel-heading"><div><span class="overline">QUICK START</span><h3>继续研究</h3></div></div>
        <router-link to="/discovery" class="launch-card featured">
          <span class="launch-icon"><AppIcon name="discovery" /></span>
          <span><strong>探索一个新问题</strong><small>从主题、标题或线索开始</small></span><i>↗</i>
        </router-link>
        <router-link to="/works" class="launch-card">
          <span class="launch-icon"><AppIcon name="library" /></span>
          <span><strong>浏览文献库</strong><small>搜索、筛选和继续阅读</small></span><i>↗</i>
        </router-link>
        <router-link to="/topics" class="launch-card">
          <span class="launch-icon"><AppIcon name="topics" /></span>
          <span><strong>整理研究主题</strong><small>收束问题与证据边界</small></span><i>↗</i>
        </router-link>
        <div v-if="Object.keys(stats.docTypes || {}).length" class="type-summary">
          <span class="overline">COLLECTION</span>
          <div class="chips">
            <span class="chip" v-for="(count, type) in stats.docTypes" :key="type">
              {{ label(DOC_TYPE_LABELS, type) }} <b>{{ count }}</b>
            </span>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { getWorks, getMetadataExtractions, getClassificationExtractions, getIngestPlan, parseStatus, getDuplicates } from '../api'
import { DOC_TYPE_LABELS, label } from '../labels'
import AppIcon from '../components/AppIcon.vue'

const stats = ref({ total: 0, unread: 0, quarantined: 0, relations: 0, docTypes: {} })
const queue = ref({ ingest: 0, parse: 0, metadata: 0, classify: 0, duplicates: 0 })
const queueItems = computed(() => [
  { to: '/inbox', icon: 'ingest', title: '等待入库', description: '确认来源并建立稳定档案', count: queue.value.ingest },
  { to: '/pipeline', icon: 'pipeline', title: '等待解析', description: '将 PDF 转化为可探索的研究材料', count: queue.value.parse },
  { to: '/metadata', icon: 'metadata', title: '元数据审核', description: '校验关键学术信息与出处', count: queue.value.metadata },
  { to: '/classification', icon: 'classify', title: '分类审核', description: '归入研究主题与阅读路径', count: queue.value.classify },
  { to: '/duplicates', icon: 'duplicates', title: '重复项确认', description: '保持知识库清晰且可追溯', count: queue.value.duplicates },
])

async function loadStats() {
  try {
    const worksRes = await getWorks({ per_page: 1 })
    const summary = worksRes.summary || {}
    stats.value.total = summary.total || 0
    stats.value.unread = summary.statuses?.unread || 0
    stats.value.quarantined = summary.statuses?.quarantined || 0
    stats.value.relations = summary.relations || 0
    stats.value.docTypes = summary.doc_types || {}
  } catch (e) { console.error('Failed to load stats:', e) }
}

async function loadQueue() {
  try {
    const [ingestRes, parseRes, metaRes, classRes, dupRes] = await Promise.allSettled([
      getIngestPlan(), parseStatus(), getMetadataExtractions({ status: 'pending', per_page: 1 }),
      getClassificationExtractions({ status: 'pending', per_page: 1 }), getDuplicates({ per_page: 1 }),
    ])
    if (ingestRes.status === 'fulfilled') queue.value.ingest = ingestRes.value.summary?.ingests || 0
    if (parseRes.status === 'fulfilled') queue.value.parse = parseRes.value.pending || 0
    if (metaRes.status === 'fulfilled') queue.value.metadata = metaRes.value.total || 0
    if (classRes.status === 'fulfilled') queue.value.classify = classRes.value.total || 0
    if (dupRes.status === 'fulfilled') queue.value.duplicates = dupRes.value.total || 0
  } catch (e) { console.error('Failed to load queue:', e) }
}

onMounted(() => { loadStats(); loadQueue() })
</script>

<style scoped>
.dashboard{width:min(1240px,100%);margin:0 auto}.hero{position:relative;display:grid;min-height:310px;grid-template-columns:minmax(0,1.55fr) minmax(260px,.65fr);align-items:center;overflow:hidden;padding:48px 54px;border:1px solid #222522;border-radius:22px;color:#fff;background:radial-gradient(circle at 78% 34%,rgba(47,185,149,.16),transparent 31%),linear-gradient(140deg,#171817 0%,#232522 58%,#112b24 130%);box-shadow:0 18px 50px rgba(28,31,28,.12)}.hero::after{content:'';position:absolute;inset:0;pointer-events:none;background:linear-gradient(115deg,rgba(255,255,255,.035),transparent 38%)}.hero-copy{position:relative;z-index:2;max-width:680px}.hero-kicker{display:flex;align-items:center;gap:9px;color:#99a09c;font-size:10px;font-weight:650;letter-spacing:.08em;text-transform:uppercase}.hero-kicker span{width:6px;height:6px;border-radius:50%;background:#4bd0aa;box-shadow:0 0 12px rgba(75,208,170,.7)}.hero h2{margin-top:18px;font-size:clamp(30px,3.2vw,46px);font-weight:520;line-height:1.13;letter-spacing:-.045em}.hero h2 em{color:#8cdcc5;font-style:normal}.hero p{max-width:580px;margin-top:18px;color:#aeb2ae;font-size:14px;line-height:1.75}.hero-actions{display:flex;gap:10px;margin-top:26px}.primary-action,.secondary-action{display:inline-flex;height:42px;align-items:center;gap:8px;padding:0 15px;border-radius:11px;font-size:12px;font-weight:560;transition:transform var(--transition-fast),background var(--transition-fast)}.primary-action{color:#07291f;background:#85dcc3}.primary-action:hover{background:#a2e7d3;transform:translateY(-1px)}.secondary-action{color:#e4e6e3;border:1px solid rgba(255,255,255,.13);background:rgba(255,255,255,.05)}.secondary-action:hover{background:rgba(255,255,255,.09);transform:translateY(-1px)}.primary-action .app-icon,.secondary-action .app-icon{width:15px}.knowledge-orbit{position:relative;z-index:1;width:230px;height:230px;justify-self:end;opacity:.92}.orbit{position:absolute;inset:25px;border:1px solid rgba(128,224,196,.22);border-radius:50%}.orbit-two{inset:59px;border-color:rgba(255,255,255,.11)}.core{position:absolute;top:50%;left:50%;display:grid;width:52px;height:52px;place-items:center;color:#062f25;border-radius:18px;background:linear-gradient(145deg,#a2ead5,#37b895);box-shadow:0 0 44px rgba(58,191,153,.25);transform:translate(-50%,-50%) rotate(8deg)}.core .app-icon{width:25px;height:25px}.node{position:absolute;width:8px;height:8px;border:1px solid #76d6ba;border-radius:50%;background:#183c33;box-shadow:0 0 12px rgba(118,214,186,.3)}.node-one{top:34px;left:63px}.node-two{right:28px;top:105px}.node-three{bottom:43px;left:48px}.knowledge-orbit small{position:absolute;right:18px;bottom:28px;color:#6d8e84;font:9px/1.3 var(--font-mono);letter-spacing:.08em}.metrics{display:grid;grid-template-columns:repeat(4,1fr);margin:18px 0;padding:0 12px;border:1px solid var(--border);border-radius:15px;background:rgba(255,255,255,.65)}.metric{position:relative;display:flex;min-height:78px;flex-direction:column;justify-content:center;padding:0 24px}.metric+.metric::before{content:'';position:absolute;left:0;width:1px;height:32px;background:var(--border)}.metric strong{font-size:22px;font-weight:610;letter-spacing:-.035em}.metric span{margin-top:2px;color:var(--text-tertiary);font-size:10px;letter-spacing:.04em}.dashboard-grid{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(300px,.8fr);gap:18px}.panel{padding:24px;border:1px solid var(--border);border-radius:17px;background:rgba(255,255,255,.82);box-shadow:var(--shadow-sm)}.panel-heading{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:18px}.overline{display:block;margin-bottom:4px;color:var(--text-tertiary);font-size:9px;font-weight:670;letter-spacing:.11em}.panel-heading h3{font-size:17px;font-weight:610;letter-spacing:-.02em}.panel-heading>a{margin-top:9px;color:var(--text-secondary);font-size:10px}.panel-heading>a span{margin-left:4px;color:var(--accent)}.queue-list{border-top:1px solid var(--border)}.queue-row{display:flex;min-height:65px;align-items:center;gap:13px;padding:0 8px;color:inherit;border-bottom:1px solid var(--border);transition:background var(--transition-fast),padding var(--transition-fast)}.queue-row:hover{margin:0 -8px;padding:0 16px;border-radius:10px;background:#f5f7f4}.queue-icon{display:grid;width:32px;height:32px;flex:0 0 32px;place-items:center;color:var(--text-secondary);border:1px solid var(--border);border-radius:9px;background:var(--bg-page)}.queue-icon .app-icon{width:15px}.queue-copy{display:flex;min-width:0;flex:1;flex-direction:column}.queue-copy strong{font-size:12px;font-weight:590}.queue-copy small{margin-top:2px;overflow:hidden;color:var(--text-tertiary);font-size:10px;text-overflow:ellipsis;white-space:nowrap}.queue-row b{min-width:25px;font-size:15px;font-weight:620;text-align:right}.queue-row i{color:var(--text-tertiary);font-size:12px;font-style:normal}.launch-panel{display:flex;flex-direction:column}.launch-card{display:flex;min-height:72px;align-items:center;gap:12px;margin-bottom:9px;padding:12px;color:inherit;border:1px solid var(--border);border-radius:12px;background:#fff;transition:transform var(--transition-fast),border-color var(--transition-fast),box-shadow var(--transition-fast)}.launch-card:hover{border-color:var(--accent-mute);box-shadow:var(--shadow-sm);transform:translateY(-1px)}.launch-card.featured{border-color:#b8ddcf;background:linear-gradient(135deg,#edf9f5,#f9fcfa)}.launch-icon{display:grid;width:35px;height:35px;flex:0 0 35px;place-items:center;color:var(--accent-ink);border-radius:10px;background:var(--accent-subtle)}.launch-icon .app-icon{width:17px}.launch-card>span:nth-child(2){display:flex;min-width:0;flex:1;flex-direction:column}.launch-card strong{font-size:11px;font-weight:600}.launch-card small{margin-top:3px;color:var(--text-tertiary);font-size:9px}.launch-card i{color:var(--text-tertiary);font-style:normal}.type-summary{margin-top:auto;padding-top:16px;border-top:1px solid var(--border)}.chips{display:flex;flex-wrap:wrap;gap:6px}.chip{padding:5px 8px;color:var(--text-secondary);border:1px solid var(--border);border-radius:8px;background:var(--bg-page);font-size:9px}.chip b{margin-left:4px;color:var(--text-primary);font-weight:650}
@media(max-width:1100px){.hero{grid-template-columns:1fr 220px;padding:42px}.dashboard-grid{grid-template-columns:1fr}.launch-panel{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.launch-panel .panel-heading,.launch-panel .type-summary{grid-column:1/-1}.launch-card{margin:0}}@media(max-width:760px){.hero{min-height:0;grid-template-columns:1fr;padding:34px 28px}.knowledge-orbit{display:none}.metrics{grid-template-columns:repeat(2,1fr)}.metric:nth-child(3)::before{display:none}.metric:nth-child(n+3){border-top:1px solid var(--border)}.launch-panel{display:block}.launch-card{margin-bottom:9px}}@media(max-width:480px){.hero-actions{align-items:stretch;flex-direction:column}.primary-action,.secondary-action{justify-content:center}.metrics{padding:0}.metric{padding:0 16px}.panel{padding:18px}.queue-copy small{display:none}}
</style>
