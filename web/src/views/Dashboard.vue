<template>
  <div class="dashboard">
    <section class="hero">
      <div class="hero-copy">
        <div class="hero-kicker"><span></span> Scholar OS · AI 自主性风险研究整理</div>
        <h2>整理证据与分类，<em>梳理研究脉络。</em></h2>
        <p>阅读在外部完成；这里整理原文依据、解释与分类，为综述做准备。</p>
        <div class="hero-actions">
          <router-link to="/research" class="primary-action"><AppIcon name="spark" /> 进入研究整理</router-link>
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
      <div class="metric"><strong>{{ stats.total }}</strong><span>入库文献（含隔离）</span></div>
      <div class="metric"><strong>{{ stats.unread }}</strong><span>未标记已读（旧字段）</span></div>
      <div class="metric"><strong>{{ stats.relations }}</strong><span>文献关系</span></div>
      <div class="metric"><strong>{{ stats.quarantined }}</strong><span>隔离项目</span></div>
    </section>

    <CollectionOverview />
    <div class="dashboard-grid">
      <section class="panel workflow-panel">
        <div class="panel-heading">
          <div><span class="overline">TODAY</span><h3>基础资料维护队列</h3></div>
          <router-link to="/pipeline">查看资料流水线 <span>→</span></router-link>
        </div>

        <!-- 建议下一步：取流程待办中第一个有待办数的阶段（纯前端计算） -->
        <div class="next-step" :class="{ idle: !nextStep }">
          <AppIcon name="spark" />
          <span v-if="nextStep">基础资料待办：<b>{{ nextStep.title }}</b>（{{ nextStep.count }}）</span>
          <span v-else>基础队列暂无待办，可继续整理研究记录</span>
          <router-link v-if="nextStep" :to="nextStep.to" class="next-step-link">前往 →</router-link>
        </div>

        <div class="queue-group">
          <div class="queue-group-title">基础资料待办</div>
          <div class="queue-list">
            <router-link v-for="item in flowItems" :key="item.title" :to="item.to" class="queue-row" :class="{ empty: !item.count }">
              <span class="queue-icon"><AppIcon :name="item.icon" /></span>
              <span class="queue-copy"><strong>{{ item.title }}</strong><small>{{ item.description }}</small></span>
              <b>{{ item.count }}</b><i>→</i>
            </router-link>
          </div>
        </div>

        <div class="queue-group">
          <div class="queue-group-title">库务与兼容入口</div>
          <div class="queue-list">
            <router-link v-for="item in backlogItems" :key="item.title" :to="item.to" class="queue-row" :class="{ empty: !item.count }">
              <span class="queue-icon"><AppIcon :name="item.icon" /></span>
              <span class="queue-copy"><strong>{{ item.title }}</strong><small>{{ item.description }}</small></span>
              <b>{{ item.count }}</b><i>→</i>
            </router-link>
          </div>
          <p class="backlog-note">书目投影只决定目录导出；研究记录以 C 原文与 D 解释的稳定状态为准。另有 {{ backlogExcluded }} 篇解析可用但尚未进入研究库，只是选题候选，是否纳入须按研究目标筛选（{{ backlogAll === null ? '研究库不可读，已进入数未知' : '已进入 ' + backlogAll + ' 篇' }}）。</p>
        </div>
      </section>

      <section class="panel launch-panel">
        <div class="panel-heading"><div><span class="overline">QUICK START</span><h3>继续研究</h3></div></div>
        <router-link to="/research/ontology" class="launch-card featured">
          <span class="launch-icon"><AppIcon name="discovery" /></span>
          <span><strong>查看研究分类体系</strong><small>核对概念定义与内外循环位置</small></span><i>↗</i>
        </router-link>
        <router-link to="/works" class="launch-card">
          <span class="launch-icon"><AppIcon name="library" /></span>
          <span><strong>浏览文献库</strong><small>查找身份、来源与引用导出</small></span><i>↗</i>
        </router-link>
        <router-link to="/metadata-workspace" class="launch-card">
          <span class="launch-icon"><AppIcon name="metadata" /></span>
          <span><strong>批量整理原数据 A</strong><small>按 Work 抽取、补全、复核；无需先建研究批次</small></span><i>↗</i>
        </router-link>
        <router-link to="/relations" class="launch-card">
          <span class="launch-icon"><AppIcon name="relations" /></span>
          <span><strong>维护文献身份关系</strong><small>版本、译本、同一作品与组成关系</small></span><i>↗</i>
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
import { getWorks, getPipelineStats, getDuplicates, getMetadataWorklist } from '../api'
import { DOC_TYPE_LABELS, label } from '../labels'
import AppIcon from '../components/AppIcon.vue'
import CollectionOverview from '../components/CollectionOverview.vue'

const stats = ref({ total: 0, unread: 0, quarantined: 0, relations: 0, docTypes: {} })
const queue = ref({
  inbox: 0, parse: 0, metadata: null, unstaged: 0, stagedWorks: 0,
  intake: 0, duplicates: 0, projectionExportable: 0,
})

// 流程待办：按流水线顺序排列；count 为 0 的行保留但视觉弱化
const flowItems = computed(() => [
  { to: '/inbox', icon: 'ingest', title: '待摄入', description: '确认收件箱来源并建立稳定档案', count: queue.value.inbox },
  { to: '/pipeline', icon: 'pipeline', title: '待解析', description: '将 PDF 转化为可探索的研究材料', count: queue.value.parse },
  { to: '/metadata-workspace', icon: 'metadata', title: '待整理原数据 A', description: '按 Work 批量抽取或补全；不要求研究批次', count: queue.value.metadata ?? '—' },
])

// 书目投影：可导出文献概况（v5 传播 / legacy 迁移）
const backlogItems = computed(() => [
  { to: '/duplicates', icon: 'duplicates', title: '待去重', description: '核对可能重复的 Work 身份', count: queue.value.duplicates },
  { to: '/intake', icon: 'review', title: '旧采集候选待审', description: '兼容发现流程的候选入库复核', count: queue.value.intake },
  { to: '/works', icon: 'metadata', title: '可导出书目投影', description: '存在活动投影（v5 传播或 legacy 迁移）的文献', count: queue.value.projectionExportable },
])
const backlogAll = computed(() => queue.value.stagedWorks)
const backlogExcluded = computed(() => queue.value.unstaged)

const nextStep = computed(() => flowItems.value.find(item => typeof item.count === 'number' && item.count > 0) || null)

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
    const [statsRes, dupRes, metadataRes] = await Promise.allSettled([getPipelineStats(), getDuplicates(), getMetadataWorklist()])
    if (statsRes.status === 'fulfilled') {
      const s = statsRes.value
      queue.value.inbox = s.inbox?.count || 0
      queue.value.parse = s.parse?.pending || 0
      queue.value.unstaged = s.research?.parsed_not_staged || 0
      queue.value.stagedWorks = (s.research?.available === false)
        ? null
        : (s.research?.staged_works ?? 0)
      queue.value.intake = s.intake?.pending || 0
      queue.value.projectionExportable = s.projection?.exportable || 0
    }
    if (dupRes.status === 'fulfilled') queue.value.duplicates = dupRes.value.total_groups || 0
    queue.value.metadata = metadataRes.status === 'fulfilled'
      ? (metadataRes.value.counts?.absent || 0) + (metadataRes.value.counts?.pending || 0)
      : null
  } catch (e) { console.error('Failed to load queue:', e) }
}

onMounted(() => { loadStats(); loadQueue() })
</script>

<style scoped>
.dashboard{width:min(1240px,100%);margin:0 auto}
/* hero 压缩为窄幅横幅，让待办面板成为首屏主角 */
.hero{position:relative;display:grid;grid-template-columns:minmax(0,1.55fr) minmax(200px,.65fr);align-items:center;overflow:hidden;padding:24px 36px;border:1px solid #222522;border-radius:18px;color:#fff;background:radial-gradient(circle at 78% 34%,rgba(47,185,149,.16),transparent 31%),linear-gradient(140deg,#171817 0%,#232522 58%,#112b24 130%);box-shadow:0 14px 36px rgba(28,31,28,.10)}
.hero::after{content:'';position:absolute;inset:0;pointer-events:none;background:linear-gradient(115deg,rgba(255,255,255,.035),transparent 38%)}
.hero-copy{position:relative;z-index:2;max-width:680px}
.hero-kicker{display:flex;align-items:center;gap:9px;color:#99a09c;font-size:10px;font-weight:650;letter-spacing:.08em;text-transform:uppercase}
.hero-kicker span{width:6px;height:6px;border-radius:50%;background:#4bd0aa;box-shadow:0 0 12px rgba(75,208,170,.7)}
.hero h2{margin-top:10px;font-size:clamp(20px,2.2vw,28px);font-weight:520;line-height:1.18;letter-spacing:-.04em}
.hero h2 em{color:#8cdcc5;font-style:normal}
.hero-actions{display:flex;gap:10px;margin-top:14px}
.primary-action,.secondary-action{display:inline-flex;height:34px;align-items:center;gap:8px;padding:0 13px;border-radius:10px;font-size:12px;font-weight:560;transition:transform var(--transition-fast),background var(--transition-fast)}
.primary-action{color:#07291f;background:#85dcc3}
.primary-action:hover{background:#a2e7d3;transform:translateY(-1px)}
.secondary-action{color:#e4e6e3;border:1px solid rgba(255,255,255,.13);background:rgba(255,255,255,.05)}
.secondary-action:hover{background:rgba(255,255,255,.09);transform:translateY(-1px)}
.primary-action .app-icon,.secondary-action .app-icon{width:15px}
.knowledge-orbit{position:relative;z-index:1;width:230px;height:230px;justify-self:end;opacity:.92;transform:scale(.66);transform-origin:center right;margin:-38px 0}
.orbit{position:absolute;inset:25px;border:1px solid rgba(128,224,196,.22);border-radius:50%}
.orbit-two{inset:59px;border-color:rgba(255,255,255,.11)}
.core{position:absolute;top:50%;left:50%;display:grid;width:52px;height:52px;place-items:center;color:#062f25;border-radius:18px;background:linear-gradient(145deg,#a2ead5,#37b895);box-shadow:0 0 44px rgba(58,191,153,.25);transform:translate(-50%,-50%) rotate(8deg)}
.core .app-icon{width:25px;height:25px}
.node{position:absolute;width:8px;height:8px;border:1px solid #76d6ba;border-radius:50%;background:#183c33;box-shadow:0 0 12px rgba(118,214,186,.3)}
.node-one{top:34px;left:63px}
.node-two{right:28px;top:105px}
.node-three{bottom:43px;left:48px}
.knowledge-orbit small{position:absolute;right:18px;bottom:28px;color:#6d8e84;font:9px/1.3 var(--font-mono);letter-spacing:.08em}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);margin:14px 0;padding:0 12px;border:1px solid var(--border);border-radius:15px;background:rgba(255,255,255,.65)}
.metric{position:relative;display:flex;min-height:66px;flex-direction:column;justify-content:center;padding:0 24px}
.metric+.metric::before{content:'';position:absolute;left:0;width:1px;height:32px;background:var(--border)}
.metric strong{font-size:22px;font-weight:610;letter-spacing:-.035em}
.metric span{margin-top:2px;color:var(--text-tertiary);font-size:10px;letter-spacing:.04em}
.dashboard-grid{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(300px,.8fr);gap:18px}
.panel{padding:24px;border:1px solid var(--border);border-radius:17px;background:rgba(255,255,255,.82);box-shadow:var(--shadow-sm)}
.panel-heading{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:14px}
.overline{display:block;margin-bottom:4px;color:var(--text-tertiary);font-size:9px;font-weight:670;letter-spacing:.11em}
.panel-heading h3{font-size:17px;font-weight:610;letter-spacing:-.02em}
.panel-heading>a{margin-top:9px;color:var(--text-secondary);font-size:10px}
.panel-heading>a span{margin-left:4px;color:var(--accent)}
/* 建议下一步 */
.next-step{display:flex;align-items:center;gap:8px;padding:9px 12px;border:1px solid var(--accent-mute);border-radius:11px;background:var(--accent-subtle);color:var(--text-primary);font-size:12px}
.next-step .app-icon{width:14px;color:var(--accent);flex-shrink:0}
.next-step b{font-weight:620}
.next-step.idle{border-color:var(--border);background:var(--bg-page);color:var(--text-tertiary)}
.next-step-link{margin-left:auto;flex-shrink:0;color:var(--accent);font-size:11px;font-weight:560}
/* 待办分组 */
.queue-group{margin-top:14px}
.next-step+.queue-group{margin-top:12px}
.queue-group-title{color:var(--text-tertiary);font-size:10px;font-weight:650;letter-spacing:.08em}
.backlog-note{margin:8px 2px 0;color:var(--text-tertiary);font-size:10px}
.queue-list{margin-top:6px;border-top:1px solid var(--border)}
.queue-row{display:flex;min-height:56px;align-items:center;gap:13px;padding:0 8px;color:inherit;border-bottom:1px solid var(--border);transition:background var(--transition-fast),padding var(--transition-fast)}
.queue-row:hover{margin:0 -8px;padding:0 16px;border-radius:10px;background:#f5f7f4}
.queue-row.empty{opacity:.45}
.queue-icon{display:grid;width:32px;height:32px;flex:0 0 32px;place-items:center;color:var(--text-secondary);border:1px solid var(--border);border-radius:9px;background:var(--bg-page)}
.queue-icon .app-icon{width:15px}
.queue-copy{display:flex;min-width:0;flex:1;flex-direction:column}
.queue-copy strong{font-size:12px;font-weight:590}
.queue-copy small{margin-top:2px;overflow:hidden;color:var(--text-tertiary);font-size:10px;text-overflow:ellipsis;white-space:nowrap}
.queue-row b{min-width:25px;font-size:15px;font-weight:620;text-align:right}
.queue-row i{color:var(--text-tertiary);font-size:12px;font-style:normal}
.launch-panel{display:flex;flex-direction:column}
.launch-card{display:flex;min-height:72px;align-items:center;gap:12px;margin-bottom:9px;padding:12px;color:inherit;border:1px solid var(--border);border-radius:12px;background:#fff;transition:transform var(--transition-fast),border-color var(--transition-fast),box-shadow var(--transition-fast)}
.launch-card:hover{border-color:var(--accent-mute);box-shadow:var(--shadow-sm);transform:translateY(-1px)}
.launch-card.featured{border-color:#b8ddcf;background:linear-gradient(135deg,#edf9f5,#f9fcfa)}
.launch-icon{display:grid;width:35px;height:35px;flex:0 0 35px;place-items:center;color:var(--accent-ink);border-radius:10px;background:var(--accent-subtle)}
.launch-icon .app-icon{width:17px}
.launch-card>span:nth-child(2){display:flex;min-width:0;flex:1;flex-direction:column}
.launch-card strong{font-size:11px;font-weight:600}
.launch-card small{margin-top:3px;color:var(--text-tertiary);font-size:9px}
.launch-card i{color:var(--text-tertiary);font-style:normal}
.type-summary{margin-top:auto;padding-top:16px;border-top:1px solid var(--border)}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{padding:5px 8px;color:var(--text-secondary);border:1px solid var(--border);border-radius:8px;background:var(--bg-page);font-size:9px}
.chip b{margin-left:4px;color:var(--text-primary);font-weight:650}
@media(max-width:1100px){.hero{grid-template-columns:1fr 200px;padding:22px 30px}.dashboard-grid{grid-template-columns:1fr}.launch-panel{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.launch-panel .panel-heading,.launch-panel .type-summary{grid-column:1/-1}.launch-card{margin:0}}
@media(max-width:760px){.hero{grid-template-columns:1fr;padding:20px 24px}.knowledge-orbit{display:none}.metrics{grid-template-columns:repeat(2,1fr)}.metric:nth-child(3)::before{display:none}.metric:nth-child(n+3){border-top:1px solid var(--border)}.launch-panel{display:block}.launch-card{margin-bottom:9px}}
@media(max-width:480px){.hero-actions{align-items:stretch;flex-direction:column}.primary-action,.secondary-action{justify-content:center}.metrics{padding:0}.metric{padding:0 16px}.panel{padding:18px}.queue-copy small{display:none}}
</style>
