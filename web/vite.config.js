import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import AutoImport from 'unplugin-auto-import/vite'
import { NaiveUiResolver } from 'unplugin-vue-components/resolvers'
import { visualizer } from 'rollup-plugin-visualizer'

const apiTarget = process.env.LITLIB_API_TARGET || 'http://127.0.0.1:19527'

export default defineConfig({
  plugins: [
    vue(),
    Components({ resolvers: [NaiveUiResolver()] }),
    AutoImport({ imports: [{ from: 'naive-ui', imports: ['useMessage', 'useDialog'] }] }),
    visualizer({ open: false, filename: 'bundle-report.html' }),
  ],
  server: {
    port: 19528,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
})
