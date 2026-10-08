<template>
  <Teleport to="body">
  <div v-if="open" class="evidence-dock" @keydown.esc="$emit('close')">
  <aside class="evidence-sidebar" role="complementary" aria-label="证据回查侧栏">
    <header class="sidebar-head">
      <strong>证据回查（固定快照）</strong>
      <button type="button" class="close-btn" aria-label="关闭证据侧栏" @click="$emit('close')">×</button>
    </header>

    <div v-if="!currentEvidence" class="sidebar-body">
      <p class="empty-value">该证据不可用：缺少快照定位参数。</p>
    </div>
    <div v-else class="sidebar-body">
      <div v-if="markdownView" class="markdown-section">
        <div class="markdown-toolbar"><strong>固定快照 · Markdown</strong><button type="button" @click="scrollToEvidence">回到证据位置</button><small>{{ markdownView.precision === 'text' ? '逐字高亮' : '高亮证据所在内容块；精确引文见下方' }}</small></div>
        <div ref="markdownArea" class="snapshot-markdown" v-html="markdownView.html"></div>
      </div>
      <!-- 同一 claim 的多条证据切换 -->
      <div v-if="evidenceList.length > 1" class="evidence-switch">
        <span>同一判断的第 {{ activeIndex + 1 }} / {{ evidenceList.length }} 条证据</span>
        <div>
          <button type="button" :disabled="activeIndex === 0" @click="activeIndex--">← 上一条</button>
          <button type="button" :disabled="activeIndex >= evidenceList.length - 1" @click="activeIndex++">下一条 →</button>
        </div>
      </div>

      <p class="claim-line"><span>所属判断：</span>{{ claimText || '（未提供）' }}</p>

      <!-- 定位失败 / 非精确回查时如实说明，不用看似精确的错误高亮替代 -->
      <p v-if="loadError" class="state-note is-error">快照读取失败：{{ loadError }}。以下仅显示登记的逐字引文。</p>
      <p v-else-if="locateState === 'offset-mismatch'" class="state-note is-warn">
        登记偏移处内容与逐字引文不一致（快照可能已变化或登记有误）。不做看似精确的高亮，以下提供逐字引文供回查。
      </p>
      <p v-else-if="locateState === 'unmatched'" class="state-note is-warn">
        逐字引文在快照中未找到（可能来自旧版快照或登记有误）。仅显示逐字引文，待核查。
      </p>
      <p v-else-if="occurrenceTotal > 1" class="state-note">
        该引文在快照中出现 {{ occurrenceTotal }} 处；当前按记录锚点定位第 {{ occurrenceIndex }} 处，非全文第一处。
      </p>

      <blockquote v-if="textWindow" class="quote-window" data-testid="evidence-window">
        <span class="ctx">{{ textWindow.before }}</span><mark>{{ textWindow.quote }}</mark><span class="ctx">{{ textWindow.after }}</span>
      </blockquote>
      <blockquote v-else class="quote-window" data-testid="evidence-quote-only">
        <mark>{{ currentEvidence.quote || '（未提供逐字引文）' }}</mark>
      </blockquote>
      <p v-if="textWindow" class="truncation-note">
        <template v-if="textWindow?.beforeOmitted">← 前文已截断，</template><template v-else>← 自文首起，</template>
        <template v-if="textWindow?.afterOmitted">后文已截断 →</template><template v-else>至文末 →</template>
      </p>

      <dl class="anchor-facts">
        <dt>绑定快照</dt>
        <dd><code>{{ currentEvidence.snapshot_id }}</code> · v{{ currentEvidence.snapshot_version ?? '?' }}</dd>
        <dt>偏移约定</dt>
        <dd>Unicode 码点（含 \r），由服务端按 content[start:end] == quote 校验；侧栏高亮已按码点换算，渲染 DOM 偏移不等同原文字符偏移。</dd>
        <dt>登记偏移</dt>
        <dd><code>{{ currentEvidence.start_offset }}–{{ currentEvidence.end_offset ?? '?' }}</code>
          <span v-if="occurrenceTotal > 1">（第 {{ occurrenceIndex }} / {{ occurrenceTotal }} 处）</span></dd>
        <template v-if="currentEvidence.locator && Object.keys(currentEvidence.locator).length">
          <dt>回查定位</dt>
          <dd><code v-for="(value, key) in currentEvidence.locator" :key="key">{{ key }}={{ value }}</code>
            <span v-if="locatorKindLabel">（{{ locatorKindLabel }}）</span></dd>
        </template>
      </dl>

      <p v-if="locatorPrecisionNote" class="state-note is-warn">{{ locatorPrecisionNote }}</p>
      <p class="verify-note">引文按登记快照逐字显示；如需阅读全文，请使用文献页的解析版渲染或原件 PDF，不把解析文本当作 PDF 原件。</p>
    </div>
  </aside>
  </div>
  </Teleport>
</template>

<script setup>
// 证据侧栏：字段/claim 的“查看证据”展开固定快照中对应段落与引文高亮。
// 关键约束：一律按证据自身绑定的 snapshot_id 取文本（旧证据不静默指向最新快照）；
// 高亮位置按登记偏移优先，偏移与引文不符时降级为逐字引文展示。
import { computed, ref, watch, nextTick, onBeforeUnmount } from 'vue'
import { renderEvidenceMarkdown } from '../../utils/evidenceMarkdown'
import { getResearchSourceText } from '../../api'
import { cpOffsetToJsIndex, findQuoteOccurrence, countQuoteOccurrences, snapshotWindow } from '../../utils/offsets'

const props = defineProps({
  open: { type: Boolean, default: false },
  // { evidence: {...}, list: [...], claimText }
  payload: { type: Object, default: null },
})
const emit = defineEmits(['close', 'state-change'])

const activeIndex = ref(0)
const snapshotCache = ref({})
const loadError = ref('')

const evidenceList = computed(() => props.payload?.list?.length ? props.payload.list : (props.payload?.evidence ? [props.payload.evidence] : []))
const currentEvidence = computed(() => evidenceList.value[activeIndex.value] || props.payload?.evidence || null)
const claimText = computed(() => props.payload?.claimText || '')

watch(() => [props.open, props.payload], () => { activeIndex.value = 0; loadError.value = '' })
watch(() => props.open, value => emit('state-change', value), { immediate: true })

// 缓存：同一快照文本一次会话内只取一次；按 snapshot_id 而非“当前快照”取。
const snapshotTextOf = computed(() => (snapshotId) => snapshotCache.value[snapshotId] ?? null)

const currentSnapshot = computed(() => {
  const ev = currentEvidence.value
  if (!ev?.snapshot_id) return null
  return snapshotCache.value[ev.snapshot_id] ?? null
})

const markdownArea = ref(null)
const markdownView = computed(() => {
  const text = currentSnapshot.value?.content_text
  return text && currentEvidence.value ? renderEvidenceMarkdown(text, currentEvidence.value) : null
})
function scrollToEvidence() {
  const root = markdownArea.value
  const target = root?.querySelector('.evidence-exact, .evidence-target')
  if (root && target) root.scrollTop = target.getBoundingClientRect().top - root.getBoundingClientRect().top + root.scrollTop - 36
}
watch(markdownView, async () => { await nextTick(); scrollToEvidence() })
let sizeObserver
watch(markdownArea, element => {
  sizeObserver?.disconnect()
  if (!element || typeof ResizeObserver === 'undefined') return
  let width = 0
  sizeObserver = new ResizeObserver(() => {
    if (element.clientWidth !== width) { width = element.clientWidth; scrollToEvidence() }
  })
  sizeObserver.observe(element)
})
onBeforeUnmount(() => { sizeObserver?.disconnect(); emit('state-change', false) })

const textWindow = computed(() => {
  const ev = currentEvidence.value
  const snap = currentSnapshot.value
  if (!ev?.quote || !snap?.content_text) return null
  const located = locateOffsets(snap.content_text, ev)
  if (!located) return null
  return snapshotWindow(snap.content_text, located.start, located.end, 240)
})

function locateOffsets(content, ev) {
  const start = ev.start_offset
  const end = ev.end_offset
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start || end > [...content].length) return null
  const at = cpOffsetToJsIndex(content, start)
  const quoteLen = cpOffsetToJsIndex(content, end ?? start) - at
  const declared = content.slice(at, at + quoteLen)
  if (ev.quote && declared === ev.quote) return { start, end: end ?? start }

  return null
}

const locateState = computed(() => {
  const ev = currentEvidence.value
  const snap = currentSnapshot.value
  if (!ev?.quote) return 'no-quote'
  if (!snap?.content_text) return 'loading'
  const start = ev.start_offset
  if (start !== undefined && start !== null) {
    const at = cpOffsetToJsIndex(snap.content_text, start)
    const end = ev.end_offset ?? start
    const declared = snap.content_text.slice(at, cpOffsetToJsIndex(snap.content_text, end))
    if (declared === ev.quote && locateOffsets(snap.content_text, ev)) return 'exact'
  }
  return start !== undefined && start !== null ? 'offset-mismatch' : 'unmatched'
})

const occurrenceIndex = computed(() => {
  const ev = currentEvidence.value
  const snap = currentSnapshot.value
  if (!ev?.quote || !snap?.content_text) return ev?.locator?.occurrence ?? 1
  if (locateState.value !== 'exact') return '?'
  const total = countQuoteOccurrences(snap.content_text, ev.quote)
  for (let i = 1; i <= total; i++) {
    if (findQuoteOccurrence(snap.content_text, ev.quote, i)?.start === ev.start_offset) return i
  }
  return '?'
})
const occurrenceTotal = computed(() => {
  const ev = currentEvidence.value
  const snap = currentSnapshot.value
  if (!ev?.quote || !snap?.content_text) return 1
  return Math.max(1, countQuoteOccurrences(snap.content_text, ev.quote))
})

const LOCATOR_KIND_LABELS = {
  text_offset: '文本偏移', page: '页码', figure_region: '图表区域',
  html_anchor: 'HTML 锚点', markdown_line: 'Markdown 行号',
}
const locatorKindLabel = computed(() => LOCATOR_KIND_LABELS[currentEvidence.value?.locator?.kind] || null)

const locatorPrecisionNote = computed(() => {
  const kind = currentEvidence.value?.locator?.kind
  if (kind === 'figure_region') {
    return '该证据仅登记到图表区域（页码+坐标），未提供区域画面裁切；下方高亮为该区域的逐字图注文本，精确到文本块。请在原件 PDF 中按页核对。'
  }
  if (kind === 'page' && currentEvidence.value?.locator_verification?.page_text_correspondence !== 'exact') {
    return '该证据登记到页码级：解析未提供 page_offsets，页码与文本位置未精确对应；下方为逐字引文而非页内定位。'
  }
  return ''
})

watch(
  () => [props.open, currentEvidence.value?.snapshot_id],
  async ([open, snapshotId]) => {
    loadError.value = ''
    if (!open || !snapshotId || snapshotCache.value[snapshotId]) return
    try {
      const row = await getResearchSourceText(currentEvidence.value.source_id, snapshotId)
      snapshotCache.value = { ...snapshotCache.value, [snapshotId]: row }
    } catch (e) {
      if (snapshotId === currentEvidence.value?.snapshot_id) loadError.value = e?.detail || e?.message || '请求失败'
    }
  },
  { immediate: true },
)
</script>

<style scoped>
.evidence-dock { position: fixed; top: var(--topbar-height); right: 0; bottom: 0; z-index: 90; width: clamp(440px, 46vw, 760px); box-sizing: border-box; }
.evidence-sidebar { position: relative; display: flex; flex-direction: column; width: 100%; height: 100%; min-height: 0; overflow: hidden; background: var(--bg-surface); border-left: 1px solid var(--border-strong); box-shadow: -8px 0 24px rgba(0, 0, 0, .12); }
.sidebar-head { flex-shrink: 0; display: flex; align-items: center; justify-content: space-between; padding: 12px 14px; border-bottom: 1px solid var(--border); }
.sidebar-head strong { font-size: 13px; }
.close-btn { padding: 4px 10px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-page); cursor: pointer; font-size: 14px; }
.sidebar-body { min-height: 0; flex: 1; display: flex; flex-direction: column; gap: 10px; overflow-y: auto; padding: 12px 14px 40px; font-size: 12px; }
.evidence-switch { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 7px 9px; border: 1px solid var(--info-border); border-radius: 6px; background: var(--info-bg); font-size: 11px; }
.evidence-switch button { margin-left: 6px; padding: 3px 8px; border: 1px solid var(--border-strong); border-radius: 5px; background: var(--bg-surface); cursor: pointer; font-size: 11px; }
.evidence-switch button:disabled { cursor: not-allowed; opacity: .5; }
.claim-line { margin: 0; line-height: 1.6; }
.claim-line span { color: var(--text-tertiary); }
.quote-window { margin: 0; padding: 10px 12px; border: 1px solid var(--border); border-left: 3px solid var(--accent-mute); border-radius: 6px; background: var(--bg-page); font: 11px/1.7 var(--font-mono); white-space: pre-wrap; overflow-wrap: anywhere; max-height: 46dvh; overflow-y: auto; }
.quote-window mark { background: rgba(255, 213, 79, .45); padding: 0 2px; border-radius: 2px; }
.quote-window .ctx { color: var(--text-secondary); }
.truncation-note { margin: 0; color: var(--text-tertiary); font-size: 10px; }
.anchor-facts { display: grid; grid-template-columns: 84px minmax(0, 1fr); gap: 0; border-top: 1px solid var(--border); margin: 0; }
.anchor-facts dt { padding: 7px 8px; background: var(--bg-page); color: var(--text-secondary); border-bottom: 1px solid var(--border); font-size: 10px; }
.anchor-facts dd { margin: 0; padding: 7px 8px; border-bottom: 1px solid var(--border); font-size: 11px; line-height: 1.6; overflow-wrap: anywhere; }
.anchor-facts code { font-size: 10px; overflow-wrap: anywhere; }
.anchor-facts dd code + code { margin-left: 8px; }
.state-note { margin: 0; padding: 8px 10px; border-radius: 6px; font-size: 11px; line-height: 1.6; background: var(--info-bg); color: var(--info-fg); }
.state-note.is-warn { background: var(--warn-bg); color: var(--warn-fg); }
.state-note.is-error { background: var(--error-bg, var(--warn-bg)); color: var(--error-fg, var(--warn-fg)); }
.verify-note { margin: 0; color: var(--text-tertiary); font-size: 10px; line-height: 1.6; }
.empty-value { color: var(--text-tertiary); }
.markdown-section { flex: 0 0 auto; min-width: 0; }
.sidebar-body > * { flex-shrink: 0; }
.markdown-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; padding-bottom: 8px; }
.markdown-toolbar button { cursor: pointer; }
.snapshot-markdown { height: 52dvh; overflow: auto; scrollbar-gutter: stable; border: 1px solid var(--border); padding: 14px; font-size: 14px; line-height: 1.8; overflow-wrap: anywhere; }
.snapshot-markdown :deep(.snapshot-block) { padding: 2px 8px; }
.snapshot-markdown :deep(.evidence-target) { background: #fff4c2; color: #242424; border-left: 4px solid #dba522; }
.snapshot-markdown :deep(mark.evidence-exact) { background: #ffda55; color: #111; }
.snapshot-markdown :deep(.md-table-wrap) { overflow-x: auto; }
.snapshot-markdown :deep(table) { border-collapse: collapse; min-width: 500px; }
.snapshot-markdown :deep(td), .snapshot-markdown :deep(th) { border: 1px solid #b9c5c0; padding: 6px; }
.snapshot-markdown :deep(img) { max-width: 100%; }
.snapshot-markdown :deep(pre) { overflow: auto; }
@media (max-width: 900px) { .evidence-dock { top: 0; z-index: 10000; width: 100vw; } .evidence-sidebar { width: 100vw; height: 100dvh; } .snapshot-markdown { height: 48dvh; padding: 6px; } }
</style>
