import { afterEach, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'
import InboxReview from '../src/views/InboxReview.vue'
import { getIngestPlan, executeIngest } from '../src/api'

vi.mock('../src/api', () => ({ getIngestPlan: vi.fn(), executeIngest: vi.fn(), uploadFiles: vi.fn() }))
vi.mock('../src/error-handler', () => ({ showError: vi.fn() }))
vi.mock('../src/composables/useNextStep', () => ({ useNextStep: () => ({ notifyNext: vi.fn() }) }))
let app, host
async function settle() { for (let i = 0; i < 10; i++) await Promise.resolve(); await nextTick(); await new Promise(resolve => setTimeout(resolve, 60)) }
async function mount(count) {
  getIngestPlan.mockResolvedValue({ summary: { ingests: count }, ingests: [], exact_duplicates: [] })
  host = document.createElement('div'); document.body.append(host)
  app = createApp(InboxReview); app.mount(host); await settle()
}
afterEach(() => { app?.unmount(); host?.remove(); vi.clearAllMocks() })

it('enables inbox confirmation for pending PDFs and cancellation never executes ingestion', async () => {
  await mount(2)
  const button = host.querySelector('.btn-execute')
  expect(button.disabled).toBe(false)
  expect(button.textContent).toContain('(2)')
  button.click(); await settle()
  expect(document.querySelector('.confirm-message').textContent).toContain('2')
  document.querySelector('.btn-cancel').click(); await settle()
  expect(document.querySelector('.confirm-dialog')).toBeNull()
  expect(executeIngest).not.toHaveBeenCalled()
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
