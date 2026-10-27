import { beforeEach, afterEach, it, expect, vi } from 'vitest'
import { createApp, h, nextTick, ref } from 'vue'
import ParseQueuePanel from '../src/components/ParseQueuePanel.vue'
import { request } from '../src/api'
vi.mock('../src/api', () => ({ request: vi.fn() }))
vi.mock('../src/composables/useRuntimeMode', () => ({ useRuntimeMode: () => ({ readOnly: ref(false) }) }))
let app, host
const plan = { items: [{ work_id: 'W-a', source_file_id: 'SF-a' }], excluded: [], sha256: 'frozen', selection: { backend: 'vlm' } }
const queued = { plan_id: 'PP-a', action: 'queued', tasks: [{ id: 'PQ-a', state: 'waiting', phase: 'poll', source_file_id: 'SF-a' }], budget: {}, remaining: [] }
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }
async function settle() { for (let i = 0; i < 12; i++) { await Promise.resolve(); await nextTick() } }
async function mount() { host = document.createElement('div'); document.body.append(host); app = createApp({ render: () => h(ParseQueuePanel, { workIds: ['W-a'], sources: [{ id: 'SF-a' }] }) }); app.mount(host); await settle() }
const button = text => [...host.querySelectorAll('button')].find(b => b.textContent.includes(text))
async function click(text) { button(text).click(); await settle() }
beforeEach(() => {
  localStorage.clear(); vi.resetAllMocks()
  request.mockImplementation(async path => {
    if (path.endsWith('/scheduler')) return { configured: true }
    if (path === '/parse/plan') return structuredClone(plan)
    if (path === '/parse/plans') return { plan_id: 'PP-a' }
    return structuredClone(queued)
  })
})
afterEach(() => { app?.unmount(); host?.remove() })

it('previews before writes, freezes explicit Source and budgets, reports queued rather than complete', async () => {
  await mount()
  expect(request.mock.calls.every(([, options]) => !options?.method)).toBe(true)
  const source = host.querySelectorAll('select')[1]; source.value = 'SF-a'; source.dispatchEvent(new Event('change')); await settle()
  await click('预览解析范围')
  expect(JSON.parse(request.mock.calls.find(([path]) => path === '/parse/plan')[1].body).source_file_ids).toEqual(['SF-a'])
  expect(request.mock.calls.some(([path]) => path === '/parse/plans')).toBe(false)
  await click('确认预算并入队')
  const body = JSON.parse(request.mock.calls.find(([path]) => path === '/parse/plans')[1].body)
  expect(body).toMatchObject({ max_items: 1, max_submissions: 1, max_pages: 100 })
  expect(host.textContent).toContain('已入队，尚未全部完成')
  expect(host.textContent).toContain('PQ-a')
  expect(request.mock.calls.some(([path]) => path === '/parse/trigger')).toBe(false)
})

it('lost acceptance response replays exactly the persisted request after remount; no automatic POST', async () => {
  let attempts = 0
  const initial = request.getMockImplementation()
  request.mockImplementation((path, options) => path === '/parse/plans' && ++attempts === 1 ? Promise.reject(new Error('timeout')) : initial(path, options))
  await mount(); await click('预览解析范围'); await click('确认预算并入队')
  const first = request.mock.calls.find(([path]) => path === '/parse/plans')[1].body
  app.unmount(); host.remove(); await mount()
  expect(attempts).toBe(1)
  await click('使用原请求继续入队')
  expect(request.mock.calls.filter(([path]) => path === '/parse/plans').map(([, options]) => options.body)).toEqual([first, first])
})

it('lost enqueue response keeps the same plan and never accepts a second one', async () => {
  let attempts = 0
  const initial = request.getMockImplementation()
  request.mockImplementation((path, options) => path.endsWith('/enqueue') && ++attempts === 1 ? Promise.reject(new Error('timeout')) : initial(path, options))
  await mount(); await click('预览解析范围'); await click('确认预算并入队')
  await click('使用原请求继续入队')
  expect(request.mock.calls.filter(([path]) => path === '/parse/plans')).toHaveLength(1)
  expect(request.mock.calls.filter(([path]) => path.endsWith('/enqueue')).map(([path]) => path)).toEqual(['/async/parse/plans/PP-a/enqueue', '/async/parse/plans/PP-a/enqueue'])
})

it('closing during acceptance retains the receipt but does not initiate enqueue', async () => {
  const pending = deferred(), initial = request.getMockImplementation()
  request.mockImplementation((path, options) => path === '/parse/plans' ? pending.promise : initial(path, options))
  await mount(); await click('预览解析范围'); await click('确认预算并入队')
  app.unmount(); pending.resolve({ plan_id: 'PP-a' }); await settle()
  expect(request.mock.calls.some(([path]) => path.endsWith('/enqueue'))).toBe(false)
  expect(JSON.parse(localStorage.getItem('litlib.parse.pending:["W-a"]')).planId).toBe('PP-a')
})

it('failure or exhausted budget never appears as successful completion', async () => {
  const initial = request.getMockImplementation()
  request.mockImplementation((path, options) => path.endsWith('/enqueue') ? Promise.resolve({ ...queued, action: 'budget_exhausted', tasks: [{ id: 'PQ-a', state: 'blocked_budget' }] }) : initial(path, options))
  await mount(); await click('预览解析范围'); await click('确认预算并入队')
  expect(host.textContent).toContain('达到预算上限')
  expect(button('完成并返回')).toBeUndefined()
})

it('cannot submit when durable browser storage fails', async () => {
  await mount(); await click('预览解析范围')
  const storage = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('storage unavailable') })
  await click('确认预算并入队')
  expect(request.mock.calls.some(([path]) => path === '/parse/plans')).toBe(false)
  expect(host.textContent).toContain('storage unavailable')
  storage.mockRestore()
})
