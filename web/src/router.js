import { createRouter, createWebHistory } from 'vue-router'

const Dashboard = () => import('./views/Dashboard.vue')
const Works = () => import('./views/Works.vue')
const WorkDetail = () => import('./views/WorkDetail.vue')
const Duplicates = () => import('./views/Duplicates.vue')
const Relations = () => import('./views/Relations.vue')
const MetadataReview = () => import('./views/MetadataReview.vue')
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
  {
    path: '/',
    name: 'dashboard',
    component: Dashboard,
    meta: { title: '总览', icon: 'dashboard', group: '文献' },
  },
  {
    path: '/works',
    name: 'works',
    component: Works,
    meta: { title: '文献库', icon: 'library', group: '文献' },
  },
  {
    path: '/works/:id',
    name: 'work-detail',
    component: WorkDetail,
    props: true,
    meta: { title: '文献详情', parent: 'works', group: '文献' },
  },
  {
    path: '/pipeline',
    name: 'pipeline',
    component: PipelineView,
    meta: { title: '流程管理', icon: 'pipeline', group: '流程' },
  },
  {
    path: '/topics',
    name: 'topics',
    component: TopicsReview,
    meta: { title: '主题闸门', icon: 'topics', group: '流程' },
  },
  {
    path: '/ingest',
    name: 'ingest',
    component: IngestHub,
    meta: { title: '文献入库', icon: 'ingest', group: '流程' },
  },
  {
    path: '/discovery',
    name: 'discovery',
    component: DiscoveryReview,
    meta: { title: '发现检索', icon: 'discovery', group: '流程' },
  },
  {
    path: '/inbox',
    name: 'inbox',
    component: InboxReview,
    meta: { title: '收件箱', icon: 'inbox', group: '流程' },
  },
  {
    path: '/intake',
    name: 'intake',
    component: IntakeReview,
    meta: { title: '采集审核', icon: 'intake', group: '流程' },
  },
  {
    path: '/classification',
    name: 'classification',
    component: ClassificationReview,
    meta: { title: '分类审核', icon: 'classification', group: '流程' },
  },
  {
    path: '/metadata',
    name: 'metadata',
    component: MetadataReview,
    meta: { title: '元数据审核', icon: 'metadata', group: '流程' },
  },
  {
    path: '/duplicates',
    name: 'duplicates',
    component: Duplicates,
    meta: { title: '去重', icon: 'duplicates', group: '工具' },
  },
  {
    path: '/relations',
    name: 'relations',
    component: Relations,
    meta: { title: '关系图', icon: 'relations', group: '工具' },
  },
  {
    path: '/templates',
    name: 'templates',
    component: TemplateManage,
    meta: { title: '模板管理', icon: 'template', group: '系统' },
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
