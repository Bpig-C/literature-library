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

const routes = [
  { path: '/', component: Dashboard },
  { path: '/works', component: Works },
  { path: '/works/:id', component: WorkDetail, props: true },
  { path: '/duplicates', component: Duplicates },
  { path: '/relations', component: Relations },
  { path: '/metadata', component: MetadataReview },
  { path: '/classification', component: ClassificationReview },
  { path: '/intake', component: IntakeReview },
  { path: '/inbox', component: InboxReview },
  { path: '/topics', component: TopicsReview },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
