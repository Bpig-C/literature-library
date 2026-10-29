import { afterEach, expect, it, vi } from 'vitest'
import { createApp, h, nextTick, ref } from 'vue'
import PipelineView from '../src/views/PipelineView.vue'
import { request } from '../src/api'
vi.mock('../src/api',()=>({request:vi.fn(async path=>path==='/parse/candidates'?{items:[{id:'SF-a',source_file_id:'SF-a',work_id:'W-a',title:'Exact PDF',status:'pending'}],counts:{pending:1}}:{configured:true}),getIngestPlan:vi.fn(async()=>({summary:{},ingests:[]})),getPipelineStats:vi.fn(async()=>({})),getUnstagedWorks:vi.fn(async()=>({items:[]})),executeIngest:vi.fn(),stageWorkToResearch:vi.fn(),quarantineWork:vi.fn(),quarantineFromReview:vi.fn(),quarantineFromClassificationReview:vi.fn(),pdfUrl:vi.fn()}))
vi.mock('../src/error-handler',()=>({showError:vi.fn()}))
vi.mock('../src/composables/useRuntimeMode',()=>({useRuntimeMode:()=>({readOnly:ref(false)})}))
vi.mock('../src/composables/useNextStep',()=>({useNextStep:()=>({notifyNext:vi.fn()})}))
vi.mock('../src/components/ParseQueuePanel.vue',()=>({default:{props:['workIds','sourceIds'],render(){return h('output',{class:'scope'},JSON.stringify({works:this.workIds,sources:this.sourceIds}))}}}))
let app,host
afterEach(()=>{app?.unmount();host?.remove()})
it('real Pipeline lists Source candidates and opens the panel with exact Source and Work scope',async()=>{
  host=document.createElement('div');document.body.append(host)
  app=createApp(PipelineView);app.component('router-link',{render(){return h('span',this.$slots.default?.())}});app.mount(host)
  for(let i=0;i<15;i++){await Promise.resolve();await nextTick()}
  expect(request).toHaveBeenCalledWith('/parse/candidates')
  const card=[...host.querySelectorAll('.stage-card')].find(e=>e.textContent.includes('文档解析'))
  if(!card.querySelector('.item-checkbox')){card.querySelector('.stage-header').click();await nextTick()}
  const box=card.querySelector('.item-checkbox');expect(box).toBeTruthy();box.click();await nextTick()
  card.querySelector('.stage-actions .btn-primary').click();await nextTick()
  expect(JSON.parse(host.querySelector('.scope').textContent)).toEqual({works:['W-a'],sources:['SF-a']})
})
