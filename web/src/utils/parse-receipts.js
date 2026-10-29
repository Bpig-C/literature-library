// The scope lock serializes tabs; identity checks also reject detached callbacks.
// No receipt is erased: archiving closes the active pointer, retaining history.
export function withReceiptLock(key, operation) {
  if (!navigator.locks?.request) throw new Error('浏览器不支持安全的跨标签页回执锁，请使用 CLI')
  return navigator.locks.request(key, operation)
}
export function currentReceipt(key) { return JSON.parse(localStorage.getItem(key) || 'null') }
export function saveReceipt(key, value, expected) {
  const current = currentReceipt(key)
  if ((current?.body.request_id || null) !== expected) throw new Error('解析请求已在另一面板变化，请关闭后重新打开')
  const merged = { ...value, enqueued: !!(value.enqueued || current?.enqueued) }
  localStorage.setItem(`${key}:request:${value.body.request_id}`, JSON.stringify(merged))
  localStorage.setItem(key, JSON.stringify(merged))
  return merged
}
export function archiveReceipt(key, value) {
  if (currentReceipt(key)?.body.request_id !== value.body.request_id) throw new Error('当前请求已变化，保留新回执')
  localStorage.setItem(`${key}:request:${value.body.request_id}`, JSON.stringify({ ...value, archived: true }))
  localStorage.removeItem(key)
}
export function receiptHistory(key) {
  const result = []
  for (let i=0; i<localStorage.length; i++) {
    const name=localStorage.key(i)
    if (name.startsWith(`${key}:request:`)) {
      const value=JSON.parse(localStorage.getItem(name))
      if (value.planId) result.push(value)
    }
  }
  return result
}
