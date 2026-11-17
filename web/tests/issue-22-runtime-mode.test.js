// Regression tests for #22: runtime-mode initialization must not present an
// unconfirmed deployment as confirmed read-only, and a failed first read must
// stay recoverable (dedupe in-flight, bounded timeout, retry entry, automatic
// re-check when later consumers mount).
import { beforeEach, afterEach, it, expect, vi } from 'vitest'
import { createApp, h, nextTick, defineComponent } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'

const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }
async function settle() { for (let i = 0; i < 12; i++) { await Promise.resolve(); await nextTick() } }

let app, host, fetchMock

// The composable keeps module-level singleton state; every case needs a fresh
// instance together with a freshly imported AppLayout so both share it.
async function fresh() {
  vi.resetModules()
  const composable = await import('../src/composables/useRuntimeMode')
  const { default: AppLayout } = await import('../src/components/AppLayout.vue')
  return { useRuntimeMode: composable.useRuntimeMode, AppLayout }
}

async function mount(AppLayout) {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:pathMatch(.*)*', component: AppLayout }] })
  await router.push('/')
  host = document.createElement('div'); document.body.append(host)
  app = createApp({ render: () => h(AppLayout) })
  app.use(router); app.mount(host); await settle()
}

const ok = body => Promise.resolve({ ok: true, status: 200, json: async () => body })
const http = status => Promise.resolve({ ok: false, status, json: async () => ({}) })

beforeEach(() => {
  localStorage.clear()
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => {
  app?.unmount(); host?.remove()
  vi.unstubAllGlobals(); vi.restoreAllMocks()
})

it('slow writable response: no confirmed-readonly banner while pending or after unlock', async () => {
  const pending = deferred()
  fetchMock.mockReturnValue(pending.promise)
  const { AppLayout } = await fresh(); await mount(AppLayout)
  expect(fetchMock).toHaveBeenCalledWith('/api/mode', expect.anything())
  expect(host.textContent).not.toContain('远程只读部署')
  expect(host.textContent).not.toContain('只读模式')
  pending.resolve({ ok: true, status: 200, json: async () => ({ read_only: false }) })
  await settle()
  expect(host.textContent).not.toContain('只读模式')
})

it('first 401 / 503 / network refusal / bad JSON / missing field all land in recoverable error, never as confirmed readonly', async () => {
  const cases = [
    ['401', http(401)],
    ['503', http(503)],
    ['network', Promise.reject(new TypeError('Failed to fetch'))],
    ['bad-json', Promise.resolve({ ok: true, status: 200, json: async () => { throw new SyntaxError('bad json') } })],
    ['missing-field', ok({ remote_writes_enabled: true })],
  ]
  for (const [name, result] of cases) {
    fetchMock.mockReturnValueOnce(result)
    const { AppLayout, useRuntimeMode } = await fresh(); await mount(AppLayout)
    const { readOnly, mode } = useRuntimeMode()
    await settle()
    expect(mode.value, name).toBe('error')
    expect(readOnly.value, name).toBe(true)
    expect(host.textContent, name).toContain('无法确认部署的运行模式')
    expect(host.textContent, name).not.toContain('远程只读部署')
    app?.unmount(); host?.remove(); app = null; host = null
  }
})

it('error banner retry button recovers to writable and clears the banner', async () => {
  fetchMock.mockReturnValueOnce(http(503)).mockReturnValueOnce(ok({ read_only: false, remote_writes_enabled: true }))
  const { AppLayout, useRuntimeMode } = await fresh(); await mount(AppLayout)
  await settle()
  expect(host.textContent).toContain('无法确认部署的运行模式')
  const retry = [...host.querySelectorAll('button')].find(b => b.textContent.includes('重试'))
  expect(retry).toBeTruthy()
  retry.click(); await settle()
  const { readOnly, mode } = useRuntimeMode()
  expect(mode.value).toBe('writable'); expect(readOnly.value).toBe(false)
  expect(host.textContent).not.toContain('无法确认部署的运行模式')
  expect(host.textContent).not.toContain('只读模式')
})

it('after an error, a later consumer (route switch / remount) re-checks automatically and recovers', async () => {
  fetchMock.mockReturnValueOnce(Promise.reject(new TypeError('offline')))
  const { useRuntimeMode } = await fresh()
  const first = useRuntimeMode()
  await settle()
  expect(first.mode.value).toBe('error')
  // Move past the retry debounce, then a later consumer of the same shared state.
  const realNow = Date.now()
  vi.spyOn(Date, 'now').mockReturnValue(realNow + 4000)
  fetchMock.mockReturnValueOnce(ok({ read_only: false }))
  const { readOnly, mode } = useRuntimeMode()
  await settle()
  expect(mode.value).toBe('writable'); expect(readOnly.value).toBe(false)
})

it('in-flight dedupe: concurrent consumers trigger exactly one mode request', async () => {
  const pending = deferred()
  fetchMock.mockReturnValue(pending.promise)
  const { useRuntimeMode } = await fresh()
  useRuntimeMode(); useRuntimeMode(); useRuntimeMode()
  const a = useRuntimeMode(); const b = useRuntimeMode()
  await settle()
  expect(fetchMock).toHaveBeenCalledTimes(1)
  pending.resolve({ ok: true, status: 200, json: async () => ({ read_only: false }) })
  await settle()
  expect(a.readOnly.value).toBe(false); expect(b.readOnly.value).toBe(false)
})

it('confirmed read-only deployment keeps the deterministic banner and write protection', async () => {
  fetchMock.mockReturnValue(ok({ read_only: true, remote_writes_enabled: false }))
  const { AppLayout, useRuntimeMode } = await fresh(); await mount(AppLayout)
  const { readOnly, mode } = useRuntimeMode()
  await settle()
  expect(mode.value).toBe('readonly'); expect(readOnly.value).toBe(true)
  expect(host.textContent).toContain('只读模式')
  expect(host.textContent).toContain('远程只读部署')
  expect(host.textContent).toContain('403')
})

it('a request that never resolves times out into the recoverable error state', async () => {
  vi.useFakeTimers()
  try {
    fetchMock.mockImplementation((_url, { signal }) => new Promise((_res, reject) => {
      signal.addEventListener('abort', () => reject(new Error('aborted')))
    }))
    const { AppLayout, useRuntimeMode } = await fresh()
    const loading = useRuntimeMode()
    await settle()
    expect(loading.mode.value).toBe('unknown')
    await vi.advanceTimersByTimeAsync(10000)
    await settle()
    expect(loading.mode.value).toBe('error')
    expect(loading.readOnly.value).toBe(true)
  } finally {
    vi.useRealTimers()
  }
})

it('write gating stays fail-closed for consumers until the server confirms writable', async () => {
  const pending = deferred()
  fetchMock.mockReturnValueOnce(pending.promise)
  const { useRuntimeMode } = await fresh()
  const gate = defineComponent({
    template: '<button type="button" :disabled="readOnly">提交</button>',
    setup() { const { readOnly } = useRuntimeMode(); return { readOnly } },
  })
  host = document.createElement('div'); document.body.append(host)
  app = createApp(gate); app.mount(host); await settle()
  const button = host.querySelector('button')
  expect(button.disabled).toBe(true) // unknown state keeps writes disabled
  pending.resolve({ ok: true, status: 200, json: async () => ({ read_only: false }) })
  await settle()
  expect(button.disabled).toBe(false)
})
