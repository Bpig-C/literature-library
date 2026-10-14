import { afterEach, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'
import History from '../src/components/IngestPurposeHistory.vue'
import { getIngestNotes, appendIngestNote } from '../src/api'
vi.mock('../src/api',()=>({getIngestNotes:vi.fn(),appendIngestNote:vi.fn()}))
vi.mock('../src/error-handler',()=>({showError:vi.fn()}))
vi.mock('../src/composables/useRuntimeMode',()=>({useRuntimeMode:()=>({readOnly:false})}))
let app,host
async function settle(){for(let i=0;i<20;i++)await Promise.resolve();await nextTick()}
afterEach(()=>{app?.unmount();host?.remove();vi.resetAllMocks()})
it('shows history and retains the same request ID when an append fails then retries',async()=>{
  getIngestNotes.mockResolvedValue({notes:[{id:'IN-old',purpose:'原用途',created_at:'2026-01-01'}]})
  appendIngestNote.mockRejectedValueOnce(new Error('temporary')).mockResolvedValueOnce({ok:true})
  host=document.createElement('div');document.body.append(host)
  app=createApp(History,{workId:'W-one'});app.mount(host);await settle()
  expect(host.textContent).toContain('原用途')
  const input=host.querySelector('textarea');input.value='新用途';input.dispatchEvent(new Event('input'));await settle()
  host.querySelector('button').click();await settle()
  expect(input.value).toBe('新用途')
  host.querySelector('button').click();await settle()
  expect(appendIngestNote.mock.calls[0]).toEqual(appendIngestNote.mock.calls[1])
  expect(input.value).toBe('')
})
