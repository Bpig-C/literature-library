import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from './views/Dashboard.vue'
import Works from './views/Works.vue'
import WorkDetail from './views/WorkDetail.vue'
import Duplicates from './views/Duplicates.vue'
import Relations from './views/Relations.vue'

const routes = [
  { path: '/', component: Dashboard },
  { path: '/works', component: Works },
  { path: '/works/:id', component: WorkDetail, props: true },
  { path: '/duplicates', component: Duplicates },
  { path: '/relations', component: Relations },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
