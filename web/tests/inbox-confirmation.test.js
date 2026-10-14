import { afterEach, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'
import InboxReview from '../src/views/InboxReview.vue'
import { getIngestPlan, executeIngest } from '../src/api'

vi.mock('../src/api', () => ({ getIngestPlan: vi.fn(), executeIngest: vi.fn(), uploadFiles: vi.fn() }))
vi.mock('../src/error-handler', () => ({ showError: vi.fn() }))
vi.mock('../src/composables/useNextStep', () => ({ useNextStep: () => ({ notifyNext: vi.fn() }) }))
// useRuntimeMode is fail-closed: absent overview keeps the UI read-only.
// Tests stub the module directly because jsdom lacks a controllable fetch.
vi.mock('../src/composables/useRuntimeMode', () => {
  const mode = { readOnly: true }
  return { useRuntimeMode: () => mode, __mode: mode }
})
let app, host
async function settle() { for (let i = 0; i < 10; i++) await Promise.resolve(); await nextTick(); await new Promise(resolve => setTimeout(resolve, 60)) }
async function mount(count) {
  getIngestPlan.mockResolvedValue({ summary: { ingests: count }, ingests: [], exact_duplicates: [] })
  host = document.createElement('div'); document.body.append(host)
  app = createApp(InboxReview); app.mount(host); await settle()
}
afterEach(() => { app?.unmount(); host?.remove(); vi.clearAllMocks() })

it('enables inbox confirmation for pending PDFs on a writable deployment and cancellation never executes ingestion', async () => {
  const { __mode } = await import('../src/composables/useRuntimeMode')
  __mode.readOnly = false
  try {
    await mount(2)
    const button = host.querySelector('.btn-execute')
    expect(button.disabled).toBe(false)
    expect(button.textContent).toContain('(2)')
    button.click(); await settle()
    expect(document.querySelector('.confirm-message').textContent).toContain('2')
    document.querySelector('.btn-cancel').click(); await settle()
    expect(document.querySelector('.confirm-dialog')).toBeNull()
    expect(executeIngest).not.toHaveBeenCalled()
  } finally { __mode.readOnly = true }
})

it('disables inbox confirmation with no ingestible PDFs', async () => {
  await mount(0)
  const button = host.querySelector('.btn-execute')
  expect(button.disabled).toBe(true)
  expect(button.textContent).toContain('(0)')
  button.click(); await settle()
  expect(document.querySelector('.confirm-dialog')).toBeNull()
  expect(executeIngest).not.toHaveBeenCalled()
})

it('keeps inbox confirmation disabled on a read-only deployment even with pending PDFs', async () => {
  await mount(2)
  const button = host.querySelector('.btn-execute')
  expect(button.disabled).toBe(true)
  button.click(); await settle()
  expect(document.querySelector('.confirm-dialog')).toBeNull()
  expect(executeIngest).not.toHaveBeenCalled()
})
