import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from './views/Dashboard.vue'
import Works from './views/Works.vue'
import WorkDetail from './views/WorkDetail.vue'
import Duplicates from './views/Duplicates.vue'
import Relations from './views/Relations.vue'
import MetadataReview from './views/MetadataReview.vue'
import ClassificationReview from './views/ClassificationReview.vue'
import IntakeReview from './views/IntakeReview.vue'

const routes = [
  { path: '/', component: Dashboard },
  { path: '/works', component: Works },
  { path: '/works/:id', component: WorkDetail, props: true },
  { path: '/duplicates', component: Duplicates },
  { path: '/relations', component: Relations },
  { path: '/metadata', component: MetadataReview },
  { path: '/classification', component: ClassificationReview },
  { path: '/intake', component: IntakeReview },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
