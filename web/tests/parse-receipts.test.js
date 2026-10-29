import { beforeEach, expect, it } from 'vitest'
import { saveReceipt, archiveReceipt, currentReceipt, receiptHistory } from '../src/utils/parse-receipts'
const key='synthetic-scope'
const receipt=id=>({body:{request_id:id},planId:`PP-${id}`,enqueued:false})
beforeEach(()=>localStorage.clear())
it('late callbacks and stale finish cannot replace or delete a newer request',()=>{
  const old=saveReceipt(key,receipt('old'),null)
  archiveReceipt(key,old)
  const next=saveReceipt(key,receipt('new'),null)
  expect(()=>saveReceipt(key,{...old,enqueued:true},'old')).toThrow()
  expect(()=>archiveReceipt(key,old)).toThrow()
  expect(currentReceipt(key)).toEqual(next)
  expect(receiptHistory(key).map(r=>r.planId)).toEqual(['PP-old','PP-new'])
})
it('another tab cannot replace the active intent; acceptance cannot downgrade enqueue',()=>{
  const old=saveReceipt(key,receipt('old'),null)
  expect(()=>saveReceipt(key,receipt('other'),null)).toThrow()
  saveReceipt(key,{...old,enqueued:true},'old')
  expect(saveReceipt(key,old,'old').enqueued).toBe(true)
})
