import { createRouter, createWebHistory } from 'vue-router'

const Dashboard = () => import('./views/Dashboard.vue')
const Works = () => import('./views/Works.vue')
const WorkDetail = () => import('./views/WorkDetail.vue')
const ResearchView = () => import('./views/ResearchView.vue')
const ResearchRecordPage = () => import('./views/ResearchRecordPage.vue')
const ResearchOntologyDraft = () => import('./views/ResearchOntologyDraft.vue')
const Duplicates = () => import('./views/Duplicates.vue')
const Relations = () => import('./views/Relations.vue')
const MetadataReview = () => import('./views/MetadataReview.vue')
const MetadataWorkspace = () => import('./views/MetadataWorkspace.vue')
const ClassificationReview = () => import('./views/ClassificationReview.vue')
const IntakeReview = () => import('./views/IntakeReview.vue')
const InboxReview = () => import('./views/InboxReview.vue')
const TopicsReview = () => import('./views/TopicsReview.vue')
const DiscoveryReview = () => import('./views/DiscoveryReview.vue')
const IngestHub = () => import('./views/IngestHub.vue')
const PipelineView = () => import('./views/PipelineView.vue')
const TemplateManage = () => import('./views/TemplateManage.vue')
const NotFound = () => import('./views/NotFound.vue')

const routes = [
  { path: '/research/records/:workId', name: 'research-record', component: ResearchRecordPage, meta: { title: '研究记录详情', parent: 'research', group: '工作台' } },
  {
    path: '/',
    name: 'dashboard',
    component: Dashboard,
    meta: { title: '总览', icon: 'dashboard', group: '工作台' },
  },
  {
    path: '/works',
    name: 'works',
    component: Works,
    meta: { title: '文献库', icon: 'library', group: '工作台' },
  },
  {
    path: '/works/:id',
    name: 'work-detail',
    component: WorkDetail,
    props: true,
    meta: { title: '文献详情', parent: 'works', group: '工作台' },
  },
  {
    path: '/metadata-workspace',
    name: 'metadata-workspace',
    component: MetadataWorkspace,
    meta: { title: '元数据工作台', icon: 'metadata', group: '文献准备' },
  },
  {
    path: '/research',
    name: 'research',
    component: ResearchView,
    meta: { title: '研究视图', icon: 'research', group: '工作台' },
  },
  {
    path: '/research/ontology',
    name: 'research-ontology-draft',
    component: ResearchOntologyDraft,
    meta: { title: '研究分类词表·草案', parent: 'research', group: '工作台' },
  },
  {
    path: '/pipeline',
    name: 'pipeline',
    component: PipelineView,
    meta: { title: '处理流程', icon: 'pipeline', group: '文献准备' },
  },
  {
    path: '/topics',
    name: 'topics',
    component: TopicsReview,
    meta: { title: '主题闸门（旧）', icon: 'topics', group: '维护与旧流程' },
  },
  {
    path: '/ingest',
    name: 'ingest',
    component: IngestHub,
    meta: { title: '文献入库', icon: 'ingest', group: '文献准备' },
  },
  {
    path: '/discovery',
    name: 'discovery',
    component: DiscoveryReview,
    meta: { title: '辅助检索（旧）', icon: 'discovery', group: '维护与旧流程' },
  },
  {
    path: '/inbox',
    name: 'inbox',
    component: InboxReview,
    meta: { title: '收件箱', icon: 'inbox', group: '文献准备' },
  },
  {
    path: '/intake',
    name: 'intake',
    component: IntakeReview,
    meta: { title: '候选入库复核', icon: 'intake', group: '维护与旧流程' },
  },
  {
    path: '/classification',
    name: 'classification',
    component: ClassificationReview,
    meta: { title: '历史分类（只读）', icon: 'classification', group: '维护与旧流程' },
  },
  {
    path: '/metadata',
    name: 'metadata',
    component: MetadataReview,
    meta: { title: '书目候选复核', icon: 'metadata', group: '维护与旧流程' },
  },
  {
    path: '/duplicates',
    name: 'duplicates',
    component: Duplicates,
    meta: { title: '去重', icon: 'duplicates', group: '库务' },
  },
  {
    path: '/relations',
    name: 'relations',
    component: Relations,
    meta: { title: '关系图', icon: 'relations', group: '库务' },
  },
  {
    path: '/templates',
    name: 'templates',
    component: TemplateManage,
    meta: { title: '旧抽取模板', icon: 'template', group: '维护与旧流程' },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: NotFound,
    meta: { title: '页面未找到' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫: 设置页面标题 + 日志
router.beforeEach((to, from) => {
  const title = to.meta?.title ? `${to.meta.title} · Scholar OS` : 'Scholar OS'
  document.title = title
  if (import.meta.env.DEV) {
    console.log(`[Router] ${from.path} -> ${to.path}`)
  }
})

export default router
