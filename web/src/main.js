import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import { setupErrorHandler } from './error-handler'

const app = createApp(App)

setupErrorHandler(app)

app.use(router).mount('#app')
