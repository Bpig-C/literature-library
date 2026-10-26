// 2026-10-25 issue 批次回归（#16 展示受益 / #18 异步身份绑定 / #20 辅助读取失败边界）。
// 全部使用合成数据与 mocked api；不触网、不写库。
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createApp, h, nextTick } from 'vue'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import WorkDetail from '../src/views/WorkDetail.vue'
import Works from '../src/views/Works.vue'
import ResearchView from '../src/views/ResearchView.vue'
import ResearchRecordPage from '../src/views/ResearchRecordPage.vue'
import MetadataWorkspace from '../src/views/MetadataWorkspace.vue'
import * as api from '../src/api'

vi.mock('../src/api', () => ({
  getWorks: vi.fn(), getWork: vi.fn(), getOverview: vi.fn(),
  getResearchWork: vi.fn(), getResearchWorkProfile: vi.fn(), updateWork: vi.fn(),
  createRelation: vi.fn(), deleteRelation: vi.fn(), quarantineWork: vi.fn(),
  restoreWork: vi.fn(), contentUrl: vi.fn(() => '/api/content'), pdfUrl: vi.fn(() => ''),
  workImageUrl: vi.fn(() => ''), mergedContentUrl: vi.fn(() => '/api/merged'),
  workDetailJsonUrl: vi.fn(() => '/api/detail.json'), parseTrigger: vi.fn(),
  stageWorkToResearch: vi.fn(), getMaterialSelection: vi.fn(),
  getPdfSelection: vi.fn(), getMetadataWorklist: vi.fn(), getMetadataWorkDetail: vi.fn(),
  getResearchSchema: vi.fn(), getMaterials: vi.fn(), openMetadataFeedback: vi.fn(),
  adoptMetadataRecord: vi.fn(), getResearchUsable: vi.fn(), queryResearch: vi.fn(),
  getWorkCitations: vi.fn(), getBatchComparison: vi.fn(), listResearchFeedback: vi.fn(),
  getResearchRiskVocab: vi.fn(), buildExportUrl: vi.fn(),
}))
vi.mock('naive-ui', () => ({
  useMessage: () => ({ error: vi.fn(), success: vi.fn(), info: vi.fn(), warning: vi.fn() }),
  useDialog: () => ({ warning: vi.fn() }),
}))
vi.mock('../src/error-handler', () => ({ showError: vi.fn() }))
vi.mock('../src/composables/useRuntimeMode', () => ({ useRuntimeMode: () => ({ readOnly: { value: false } }) }))
vi.mock('../src/composables/useNextStep', () => ({ useNextStep: () => ({ notifyNext: vi.fn() }) }))
vi.mock('../src/utils/storage-feedback', () => ({ readMaterial: vi.fn(async () => ''), freezeMaterialSelection: vi.fn(v => v) }))
vi.mock('../src/components/IngestPurposeHistory.vue', () => ({ default: { render: () => h('div') } }))
vi.mock('../src/components/ResizeHandle.vue', () => ({ default: { render: () => h('div') } }))
vi.mock('../src/components/EmptyState.vue', () => ({ default: { render: () => h('div') } }))
vi.mock('../src/components/research/AgentTaskFab.vue', () => ({ default: { render: () => h('div') } }))
vi.mock('../src/components/research/FeedbackPanel.vue', () => ({ default: { render: () => h('div') } }))
vi.mock('../src/components/research/ResearchRecordReadable.vue', () => ({ default: { props: ['record'], render: () => h('div') } }))

let app, router, host
function deferred() {
  let resolve, reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}
async function settle() {
  for (let i = 0; i < 30; i++) await Promise.resolve()
  await new Promise(resolve => setTimeout(resolve, 0))
  await nextTick()
}
beforeEach(() => {
  window.history.replaceState(null, '', '/')
  if (!Element.prototype.scrollIntoView) Element.prototype.scrollIntoView = () => {}
  vi.spyOn(Element.prototype, 'scrollIntoView').mockImplementation(() => {})
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
  window.fetch = vi.fn(() => Promise.reject(new Error('网络不可用（合成）')))
  api.getMaterialSelection.mockResolvedValue({})
})
afterEach(() => {
  app?.unmount(); router = null; host?.remove(); host = null
  vi.restoreAllMocks(); vi.clearAllMocks(); delete window.fetch
})

const stubs = {
  'n-button': { render() { return h('button', this.$slots.default?.()) } },
  'n-input': { props: ['value'], emits: ['update:value', 'input'], render() {
    return h('input', { value: this.value, onInput: e => {
      this.$emit('update:value', e.target.value); this.$emit('input', e.target.value)
    } })
  } },
  'n-select': { render() { return h('div', this.$slots.default?.()) } },
  'n-tag': { render() { return h('span', this.$slots.default?.()) } },
  'n-spin': { render() { return h('div') } },
  'n-modal': { props: ['show'], render() { return this.show ? h('div', this.$slots.default?.()) : null } },
  'n-pagination': { render() { return h('div') } },
  'n-radio-group': { render() { return h('div', this.$slots.default?.()) } },
  'n-radio-button': { render() { return h('button', this.$slots.default?.()) } },
  'n-alert': { render() { return h('div', this.$slots.default?.()) } },
}
async function mount(url, routes) {
  router = createRouter({ history: createMemoryHistory(), routes })
  await router.push(url); await router.isReady()
  app = createApp({ render: () => h(RouterView) }); app.use(router)
  for (const [name, stub] of Object.entries(stubs)) app.component(name, stub)
  host = document.createElement('div'); document.body.append(host); app.mount(host)
  await settle()
}

const routesFor = {
  '/works/:id': { path: '/works/:id', component: WorkDetail, props: true },
  '/works': { path: '/works', component: Works },
  '/research': { path: '/research', component: ResearchView },
  '/research/records/:workId': { path: '/research/records/:workId', component: ResearchRecordPage },
  '/metadata-workspace': { path: '/metadata-workspace', component: MetadataWorkspace },
}

function workFixture(id, extra = {}) {
  return {
    id, title: `Title ${id}`, authors: ['Alice'], year: 2026, language: 'en',
    read_status: 'unread', parse_status: 'succeeded', source_files: [],
    parse_runs: [], relations: [], codes: [], duplicates: [],
    research_summary: { available: true, staged: false },
    ...extra,
  }
}

// ------------------------------------------------------------------ #16

it('issue #16: staged=false with an approved stable A head renders the A status, not “尚无记录”', async () => {
  api.getWork.mockImplementation(id => Promise.resolve(workFixture(id, {
    research_summary: {
      available: true, staged: false,
      metadata_head: { id: 'RM-1', version: 2, agent_review_status: 'approved',
                       content_state: 'stable', validity_status: 'active' },
    },
  })))
  api.getWorks.mockResolvedValue({ works: [], total_matching: 0 })
  api.getOverview.mockResolvedValue({ research: { batches: [] } })
  api.getResearchWorkProfile.mockResolvedValue({ metadata: {} })
  await mount('/works/W-a', [routesFor['/works/:id']])
  expect(host.querySelector('.detail-panel').textContent).toContain('Title W-a')
  expect(host.textContent).toContain('approved · v2')
  expect(host.textContent).toContain('已核查稳定')
})

// ------------------------------------------------------------------ #18

it('issue #18: switching works — late profile/research responses of the previous work never overwrite the current page', async () => {
  const slowProfileA = deferred(), slowResearchA = deferred()
  api.getWork.mockImplementation(id => Promise.resolve(workFixture(id)))
  api.getWorks.mockResolvedValue({ works: [], total_matching: 0 })
  api.getOverview.mockResolvedValue({ research: { batches: [] } })
  api.getResearchWorkProfile.mockImplementation(id =>
    id === 'W-a' ? slowProfileA.promise : Promise.resolve({
      metadata: { records: [{ id: 'RM-B' }], head_record_id: 'RM-B' },
      sources: [], source_records: [], interpretations: [], references: {}, feedback: { open: [] },
    }))
  api.getResearchWork.mockImplementation((id) =>
    id === 'W-a' ? slowResearchA.promise
      : Promise.resolve({ items: [{ id: 'R-B', work_id: 'W-b', source: { work_id: 'W-b', citation_key: 'cite-b' } }] }))
  await mount('/works/W-a?batch_id=B1', [routesFor['/works/:id']])
  expect(api.getResearchWorkProfile).toHaveBeenCalledWith('W-a')
  await router.push('/works/W-b?batch_id=B1'); await settle()
  expect(api.getResearchWorkProfile).toHaveBeenCalledWith('W-b')
  // A 的谱系与研究卡迟到：不得覆盖 B 的页面状态。
  slowProfileA.resolve({ metadata: { records: [{ id: 'RM-A' }], head_record_id: 'RM-A' } })
  slowResearchA.resolve({ items: [{ id: 'R-A', work_id: 'W-a', source: { work_id: 'W-a', citation_key: 'cite-a' } }] })
  await settle()
  expect(host.querySelector('.detail-panel').textContent).toContain('Title W-b')
  expect(host.textContent).toContain('RM-B')
  expect(host.textContent).not.toContain('RM-A')
  const cards = [...host.querySelectorAll('.research-card')]
  expect(cards.length).toBe(1)
  expect(cards[0].textContent).toContain('cite-b')
  expect(cards[0].textContent).not.toContain('cite-a')
})

it('issue #18: a failed work load clears the previous work instead of showing it as the current one', async () => {
  api.getWork.mockImplementation(id => id === 'W-a'
    ? Promise.resolve(workFixture(id))
    : Promise.reject(new Error('HTTP 500')))
  api.getWorks.mockResolvedValue({ works: [], total_matching: 0 })
  api.getOverview.mockResolvedValue({ research: { batches: [] } })
  api.getResearchWorkProfile.mockResolvedValue({ metadata: {} })
  api.getResearchWork.mockResolvedValue({ items: [] })
  await mount('/works/W-a', [routesFor['/works/:id']])
  expect(host.querySelector('.detail-panel').textContent).toContain('Title W-a')
  await router.push('/works/W-b'); await settle()
  // 路由已是 B：不得把 A 的标题/A 状态当成本篇展示；给出页面级错误与重试。
  expect(host.querySelector('.detail-panel .work-layout, .detail-panel')).toBeTruthy()
  expect(host.textContent).not.toContain('Title W-a')
  expect(host.textContent).toContain('读取失败')
  expect(host.textContent).toContain('W-b')
})

it('issue #18: Works list — a slow earlier query response cannot overwrite or clear the current results', async () => {
  const slowInitial = deferred()
  let call = 0
  api.getWorks.mockImplementation(() => {
    call += 1
    return call === 1 ? slowInitial.promise : Promise.resolve({
      works: [{ id: 'W-new', title: 'New result', read_status: 'unread' }], total: 1, total_matching: 1,
    })
  })
  api.getResearchRiskVocab.mockResolvedValue({ available: true, usable: {} })
  await mount('/works', [routesFor['/works']])
  // 初始查询挂起；输入搜索触发防抖后的第二次（快）查询。
  const search = host.querySelector('input[placeholder*="搜索"]')
  search.value = 'new'
  search.dispatchEvent(new Event('input'))
  await new Promise(resolve => setTimeout(resolve, 360))
  await settle()
  expect(host.textContent).toContain('New result')
  // 初始慢查询迟到成功：不覆盖新结果。
  slowInitial.resolve({ works: [{ id: 'W-old', title: 'Old result', read_status: 'unread' }], total: 1, total_matching: 1 })
  await settle()
  expect(host.textContent).toContain('New result')
  expect(host.textContent).not.toContain('Old result')
})

it('issue #18: record page comparison — the previous record’s late citation response cannot land on the new record', async () => {
  const slowCitationsA = deferred()
  api.queryResearch.mockResolvedValue({ items: [{ id: 'R-1', work_id: 'W-a' }] })
  api.getWork.mockImplementation(id => Promise.resolve(workFixture(id)))
  api.listResearchFeedback.mockResolvedValue({ items: [] })
  api.getWorkCitations.mockImplementation(id => id === 'W-a' ? slowCitationsA.promise
    : Promise.resolve({ edges: [{ id: 'edge-b' }] }))
  await mount('/research/records/W-a?batch_id=B1', [routesFor['/research/records/:workId']])
  const buttons = [...host.querySelectorAll('button')]
  buttons.find(b => b.textContent.includes('查看该文献引用图'))?.click()
  await settle()
  await router.push('/research/records/W-b?batch_id=B1'); await settle()
  const bButtons = [...host.querySelectorAll('button')]
  bButtons.find(b => b.textContent.includes('查看该文献引用图'))?.click()
  await settle()
  slowCitationsA.resolve({ edges: [{ id: 'edge-a' }] })
  await settle()
  expect(host.textContent).toContain('edge-b')
  expect(host.textContent).not.toContain('edge-a')
})

// ------------------------------------------------------------------ #20

it('issue #20: ResearchView keeps successful rows when only the /usable summary fails', async () => {
  api.queryResearch.mockResolvedValue({ items: [{ id: 'R-1', work_id: 'W-a' }], total: 1 })
  api.getResearchUsable.mockRejectedValue(new Error('HTTP 503'))
  await mount('/research?batch_id=B1', [routesFor['/research']])
  expect(host.textContent).toContain('W-a')
  expect(host.textContent).not.toContain('研究数据暂时不可用')
  expect(host.textContent).toContain('可用基线读取失败')
  expect(host.textContent).toContain('未确认')
})

it('issue #20: MetadataWorkspace keeps the A worklist when only the schema read fails and disables prompt generation', async () => {
  api.getMetadataWorklist.mockResolvedValue({
    items: [{ id: 'W-a', title: 'Kept work', status: 'absent', parse_ready: true }],
    counts: { absent: 1 },
  })
  api.getResearchSchema.mockRejectedValue(new Error('HTTP 503'))
  api.getMaterials.mockResolvedValue({ available: true, items: [] })
  api.getMetadataWorkDetail.mockResolvedValue({ work_id: 'W-a', records: [], feedback: [] })
  await mount('/metadata-workspace?work_id=W-a', [routesFor['/metadata-workspace']])
  expect(host.textContent).toContain('Kept work')
  expect(host.textContent).toContain('尚无 A 记录')
  expect(host.textContent).toContain('研究环境（schema）读取失败')
  const generate = [...host.querySelectorAll('button')]
    .find(b => b.textContent.includes('生成可编辑工单'))
  expect(generate.disabled).toBe(true)
})

it('issue #20: record page stays readable when only the feedback list fails', async () => {
  api.queryResearch.mockResolvedValue({ items: [{ id: 'R-1', work_id: 'W-a' }] })
  api.getWork.mockImplementation(id => Promise.resolve(workFixture(id)))
  api.listResearchFeedback.mockRejectedValue(new Error('HTTP 503'))
  await mount('/research/records/W-a?batch_id=B1', [routesFor['/research/records/:workId']])
  expect(host.querySelector('.record-detail-page').textContent).toContain('Title W-a')
  expect(host.querySelector('.detail-layout')).toBeTruthy()
  expect(host.textContent).toContain('质疑清单读取失败')
  expect(host.textContent).toContain('正文可读')
})
