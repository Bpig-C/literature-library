import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import { setupErrorHandler } from './error-handler'
import { loadResearchAssets } from './researchAssets'

const app = createApp(App)

setupErrorHandler(app)

loadResearchAssets().then(() => app.use(router).mount('#app')).catch(error => {
  const root = document.getElementById('app')
  const message = document.createElement('p')
  message.setAttribute('role', 'alert')
  message.textContent = error.message
  root.replaceChildren(message)
})
