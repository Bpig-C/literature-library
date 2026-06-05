import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 19528,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:19527',
        changeOrigin: true,
      },
    },
  },
})
