<template>
  <aside class="pdf-drawer">
    <div class="pdf-drawer-header">
      <div>
        <div class="pdf-title">PDF</div>
        <div class="muted tiny">{{ workId }}</div>
      </div>
      <div class="pdf-actions">
        <a :href="url" target="_blank" rel="noopener" class="pdf-link">Open</a>
        <button type="button" class="ctrl-btn" @click.stop="closeDrawer">Close</button>
      </div>
    </div>

    <div class="pdf-toolbar">
      <button type="button" class="ctrl-btn" :disabled="pageNumber <= 1 || loading" @click="goToPage(pageNumber - 1)">Prev</button>
      <span class="pdf-page">{{ pageNumber }} / {{ pageCount || '-' }}</span>
      <button type="button" class="ctrl-btn" :disabled="pageNumber >= pageCount || loading" @click="goToPage(pageNumber + 1)">Next</button>
      <button type="button" class="ctrl-btn" :disabled="scale <= 0.6 || loading" @click="setScale(scale - 0.15)">-</button>
      <span class="pdf-page">{{ Math.round(scale * 100) }}%</span>
      <button type="button" class="ctrl-btn" :disabled="scale >= 2.4 || loading" @click="setScale(scale + 0.15)">+</button>
    </div>

    <div ref="scrollEl" class="pdf-body">
      <div v-if="loading" class="pdf-status">Loading PDF...</div>
      <div v-else-if="error" class="pdf-status error">
        {{ error }}
        <a :href="url" target="_blank" rel="noopener">Open PDF</a>
      </div>
      <canvas v-show="!loading && !error" ref="canvasEl" class="pdf-canvas"></canvas>
    </div>
  </aside>
</template>

<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import * as pdfjsLib from 'pdfjs-dist'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.mjs?url'

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl

const props = defineProps({
  url: { type: String, required: true },
  workId: { type: String, required: true },
})

const emit = defineEmits(['close'])

const canvasEl = ref(null)
const scrollEl = ref(null)
const loading = ref(false)
const error = ref('')
const pageNumber = ref(1)
const pageCount = ref(0)
const scale = ref(1.15)

let pdfDoc = null
let loadTask = null
let renderTask = null
let loadToken = 0
let renderToken = 0

watch(
  () => [props.url, props.workId],
  () => loadPdf(),
  { immediate: true },
)

onBeforeUnmount(() => {
  const token = ++loadToken  // invalidate any in-flight load
  renderToken += 1           // invalidate any in-flight render
  cancelRender()
  if (loadTask) { try { loadTask.destroy() } catch {} loadTask = null }
  if (pdfDoc) { try { pdfDoc.destroy() } catch {} pdfDoc = null }
})

async function loadPdf() {
  const token = ++loadToken
  renderToken += 1
  cancelRender()
  if (loadTask) loadTask.destroy()
  if (pdfDoc) pdfDoc.destroy()
  clearCanvas()

  loading.value = true
  error.value = ''
  pageNumber.value = 1
  pageCount.value = 0
  pdfDoc = null

  try {
    loadTask = pdfjsLib.getDocument({ url: props.url })
    const nextDoc = await loadTask.promise
    if (token !== loadToken) {
      nextDoc.destroy()
      return
    }
    pdfDoc = nextDoc
    pageCount.value = pdfDoc.numPages
    await renderPage()
  } catch (e) {
    if (token === loadToken && e?.name !== 'RenderingCancelledException') {
      error.value = e?.message || 'Failed to load PDF.'
    }
  } finally {
    if (token === loadToken) loading.value = false
  }
}

async function renderPage() {
  if (!pdfDoc || !canvasEl.value) return
  const token = ++renderToken
  cancelRender()

  loading.value = true
  error.value = ''
  await nextTick()

  try {
    const page = await pdfDoc.getPage(pageNumber.value)
    if (token !== renderToken) return

    const viewport = page.getViewport({ scale: scale.value })
    const canvas = canvasEl.value
    const context = canvas.getContext('2d')
    const outputScale = window.devicePixelRatio || 1

    canvas.width = Math.floor(viewport.width * outputScale)
    canvas.height = Math.floor(viewport.height * outputScale)
    canvas.style.width = `${Math.floor(viewport.width)}px`
    canvas.style.height = `${Math.floor(viewport.height)}px`

    renderTask = page.render({
      canvasContext: context,
      viewport,
      transform: outputScale !== 1 ? [outputScale, 0, 0, outputScale, 0, 0] : null,
    })
    await renderTask.promise
    scrollEl.value?.scrollTo({ top: 0, left: 0 })
  } catch (e) {
    if (e?.name !== 'RenderingCancelledException') {
      error.value = e?.message || 'Failed to render PDF page.'
    }
  } finally {
    if (token === renderToken) loading.value = false
  }
}

function cancelRender() {
  if (renderTask) {
    renderTask.cancel()
    renderTask = null
  }
}

function clearCanvas() {
  const canvas = canvasEl.value
  if (!canvas) return
  const context = canvas.getContext('2d')
  if (context) context.clearRect(0, 0, canvas.width, canvas.height)
  canvas.width = 0
  canvas.height = 0
  canvas.style.width = ''
  canvas.style.height = ''
}

function goToPage(nextPage) {
  pageNumber.value = Math.min(Math.max(nextPage, 1), pageCount.value || 1)
  renderPage()
}

function setScale(nextScale) {
  scale.value = Math.min(Math.max(nextScale, 0.6), 2.4)
  renderPage()
}

function closeDrawer() {
  emit('close')
}
</script>

<style scoped>
.pdf-drawer { border-left: 1px solid var(--line); background: #f8fafc; display: flex; flex-direction: column; min-width: 0; height: 100%; overflow: hidden; }
.pdf-drawer-header { height: 52px; flex: 0 0 auto; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 10px; border-bottom: 1px solid var(--line); background: #fff; }
.pdf-title { font-size: 13px; font-weight: 700; color: #111827; }
.pdf-actions { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
.pdf-toolbar { height: 38px; flex: 0 0 auto; display: flex; align-items: center; gap: 6px; padding: 6px 10px; border-bottom: 1px solid var(--line); background: #fff; }
.pdf-page { min-width: 48px; text-align: center; font-size: 11px; color: #475467; }
.pdf-body { flex: 1 1 auto; min-height: 0; overflow: auto; padding: 14px; background: #e5e7eb; }
.pdf-canvas { display: block; margin: 0 auto; background: #fff; box-shadow: 0 2px 12px rgba(15, 23, 42, 0.18); }
.pdf-status { padding: 16px; font-size: 13px; color: #475467; }
.pdf-status.error { color: #991b1b; }
.pdf-status a { margin-left: 6px; color: var(--accent); }
.ctrl-btn { height: 26px; padding: 0 8px; border: 1px solid var(--line); border-radius: 4px; font-size: 11px; background: #fff; cursor: pointer; }
.ctrl-btn:disabled { opacity: 0.4; cursor: default; }
.pdf-link { font-size: 11px; color: var(--accent); }
.muted { color: var(--muted); }
.tiny { font-size: 11px; }
</style>
