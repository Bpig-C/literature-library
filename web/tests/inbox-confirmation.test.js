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
  if (!getIngestPlan.getMockImplementation()) getIngestPlan.mockResolvedValue({ summary: { ingests: count }, ingests: [], exact_duplicates: [] })
  host = document.createElement('div'); document.body.append(host)
  app = createApp(InboxReview); app.mount(host); await settle()
}
afterEach(() => { app?.unmount(); host?.remove(); vi.resetAllMocks() })

it('enables inbox confirmation for pending PDFs on a writable deployment and cancellation never executes ingestion', async () => {
  const { __mode } = await import('../src/composables/useRuntimeMode')
  __mode.readOnly = false
  try {
    await mount(2)
    const input = host.querySelector('.purpose-field textarea')
    input.value = '用于综述'; input.dispatchEvent(new Event('input')); await settle()
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

it('requires a nonblank purpose on a writable deployment', async () => {
  const { __mode } = await import('../src/composables/useRuntimeMode')
  __mode.readOnly = false
  try {
    await mount(1)
    expect(host.querySelector('.btn-execute').disabled).toBe(true)
    const input = host.querySelector('.purpose-field textarea')
    input.value = '   '; input.dispatchEvent(new Event('input')); await settle()
    expect(host.querySelector('.btn-execute').disabled).toBe(true)
  } finally { __mode.readOnly = true }
})

it('allows a pure duplicate batch to append a purpose and sends the required fields', async () => {
  const { __mode } = await import('../src/composables/useRuntimeMode')
  __mode.readOnly = false
  getIngestPlan.mockResolvedValue({summary:{ingests:0,exact_duplicates:1},ingests:[],exact_duplicates:[{existing_work_id:'W-old',existing_source_file_id:'SF-old',original_name:'existing.pdf'}]})
  executeIngest.mockResolvedValue({summary:{ingests:0,exact_duplicates:1},purpose_notes:{purposes_saved:1}})
  try {
    await mount(0)
    const input = host.querySelector('.purpose-field textarea')
    input.value = '  用于案例分析  '; input.dispatchEvent(new Event('input')); await settle()
    expect(host.textContent).toContain('W-old')
    expect(host.querySelector('.btn-execute').disabled).toBe(false)
    host.querySelector('.btn-execute').click(); await settle()
    document.querySelector('.btn-confirm').click(); await settle()
    expect(executeIngest).toHaveBeenCalledWith(expect.objectContaining({purpose:'用于案例分析',request_id:expect.any(String)}))
  } finally { __mode.readOnly = true }
})
