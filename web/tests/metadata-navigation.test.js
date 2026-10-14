import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createApp, h, nextTick } from 'vue'
import { createRouter, createWebHistory, RouterView } from 'vue-router'
import MetadataWorkspace from '../src/views/MetadataWorkspace.vue'
import Works from '../src/views/Works.vue'
import * as api from '../src/api'

vi.mock('../src/api', () => ({ getMetadataWorklist: vi.fn(), getMetadataWorkDetail: vi.fn(),
  getResearchSchema: vi.fn(), getMaterials: vi.fn(), openMetadataFeedback: vi.fn(), adoptMetadataRecord: vi.fn(),
  getWorks: vi.fn(), getResearchRiskVocab: vi.fn(), quarantineWork: vi.fn(), restoreWork: vi.fn(), buildExportUrl: vi.fn() }))
vi.mock('naive-ui', () => ({ useMessage: () => ({ error: vi.fn(), success: vi.fn() }), useDialog: () => ({ warning: vi.fn() }) }))
vi.mock('../src/error-handler', () => ({ showError: vi.fn() }))
vi.mock('../src/composables/useRuntimeMode', () => ({ useRuntimeMode: () => ({ readOnly: { value: false } }) }))
vi.mock('../src/composables/useNextStep', () => ({ useNextStep: () => ({ notifyNext: vi.fn() }) }))
let app, router, host
const items = [{ id: 'W-one', title: 'First paper', status: 'absent', parse_ready: true },
  { id: 'W-two', title: 'Second paper', status: 'absent', parse_ready: true }]
const empty = id => ({ work_id: id, records: [], feedback: [] })
async function settle() { for (let i = 0; i < 25; i++) await Promise.resolve(); await new Promise(resolve => setTimeout(resolve, 0)); await nextTick() }
beforeEach(() => {
  window.history.replaceState(null, '', '/')
  if (!Element.prototype.scrollIntoView) Element.prototype.scrollIntoView = () => {}
  vi.spyOn(Element.prototype, 'scrollIntoView').mockImplementation(() => {})
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
  api.getMetadataWorklist.mockResolvedValue({ items, counts: { absent: 2 } })
  api.getResearchSchema.mockResolvedValue({})
  api.getMaterials.mockResolvedValue({ available: true, items: [] })
  api.getMetadataWorkDetail.mockImplementation(id => Promise.resolve(empty(id)))
  api.getResearchRiskVocab.mockResolvedValue({ available: true, usable: {} })
  api.getWorks.mockResolvedValue({ works: [{ ...items[0], read_status: 'unread' }], total: 100, total_matching: 100 })
})
afterEach(() => { app?.unmount(); router?.options.history.destroy(); host?.remove(); vi.restoreAllMocks(); vi.clearAllMocks() })
async function mount(url) {
  router = createRouter({ history: createWebHistory(), routes: [
    { path: '/works', component: Works }, { path: '/metadata-workspace', component: MetadataWorkspace },
    { path: '/:pathMatch(.*)*', component: { render: () => null } },
  ] })
  await router.push(url); await router.isReady()
  app = createApp({ render: () => h(RouterView) }); app.use(router)
  app.component('n-input', { props: ['value'], emits: ['update:value', 'input'], render() {
    return h('input', { value: this.value, onInput: e => { this.$emit('update:value', e.target.value); this.$emit('input', e.target.value) } })
  } })
  app.component('n-pagination', { props: ['page'], emits: ['update:page'], render() {
    return h('button', { class: 'next-page', onClick: () => this.$emit('update:page', this.page + 1) }, 'Next page')
  } })
  app.component('n-modal', { props: ['show'], render() { return this.show ? h('div', this.$slots.default?.()) : null } })
  for (const name of ['n-button','n-select','n-switch','n-tag','n-divider','n-radio-group','n-radio-button']) {
    app.component(name, { render() { return h(name === 'n-button' ? 'button' : 'div', this.$slots.default?.()) } })
  }
  host = document.createElement('div'); document.body.append(host); app.mount(host); await settle()
}
it('makes a deep-linked empty A detail visible and focused without producing metadata', async () => {
  await mount('/metadata-workspace?work_id=W-one')
  const section = host.querySelector('.detail-box')
  expect(section.textContent).toContain('First paper')
  expect(section.textContent).toContain('尚无 A 记录')
  expect(section.scrollIntoView).toHaveBeenCalled()
  expect(document.activeElement).toBe(section)
  expect(api.openMetadataFeedback).not.toHaveBeenCalled()
})
it('shows an unknown Work explicitly, closes the deep link, and offers a safe direct-entry return', async () => {
  await mount('/metadata-workspace?work_id=W-missing')
  expect(host.querySelector('.detail-box').textContent).toContain('未找到 Work W-missing')
  expect(api.getMetadataWorkDetail).not.toHaveBeenCalled()
  host.querySelector('.detail-heading button:last-child').click(); await settle()
  expect(router.currentRoute.value.query.work_id).toBeUndefined()
  expect(host.querySelector('.detail-box')).toBeNull()
  await router.replace('/metadata-workspace?work_id=W-one'); await settle()
  host.querySelector('.detail-heading button').click(); await settle()
  expect(router.currentRoute.value.path).toBe('/works')
})
it('ignores an older response when the requested Work changes on the same page', async () => {
  let resolveFirst
  api.getMetadataWorkDetail.mockImplementation(id => id === 'W-one'
    ? new Promise(resolve => { resolveFirst = resolve }) : Promise.resolve(empty(id)))
  await mount('/metadata-workspace?work_id=W-one')
  await router.replace('/metadata-workspace?work_id=W-two'); await settle()
  resolveFirst({ ...empty('W-one'), records: [{ id: 'OLD', payload: {}, version: 1 }] }); await settle()
  expect(host.querySelector('.detail-box').textContent).toContain('Second paper')
  expect(host.querySelector('.detail-box').textContent).not.toContain('OLD')
})
it('restores the source list filters, page and scroll after returning from A', async () => {
  await mount('/works')
  const input = host.querySelector('.toolbar input'); input.value = 'First'; input.dispatchEvent(new Event('input', { bubbles: true }))
  await new Promise(resolve => setTimeout(resolve, 350)); await settle()
  host.querySelector('.next-page').click(); await settle()
  Object.defineProperty(window, 'scrollY', { value: 180, configurable: true })
  host.querySelector('.metadata-action').click(); await settle()
  expect(router.currentRoute.value.path).toBe('/metadata-workspace')
  host.querySelector('.detail-heading button').click()
  await new Promise(resolve => setTimeout(resolve, 20)); await settle()
  expect(router.currentRoute.value.path).toBe('/works')
  expect(host.querySelector('.toolbar input').value).toBe('First')
  expect(api.getWorks.mock.calls.at(-1)[0]).toContain('page=2')
  expect(window.scrollTo).toHaveBeenLastCalledWith({ top: 180, behavior: 'instant' })
  Object.defineProperty(window, 'scrollY', { value: 0, configurable: true })
})
