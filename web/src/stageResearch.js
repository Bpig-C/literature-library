/** Helpers kept outside WorkDetail so the payload/navigation contract is testable. */
export function normalizeBatchChoice(value) {
  const raw = value && typeof value === 'object' && 'value' in value ? value.value : value
  const normalized = typeof raw === 'string' ? raw.trim() : ''
  return normalized || null
}

export function stagePayload(batchChoice) {
  const batchId = normalizeBatchChoice(batchChoice)
  return batchId
    ? { batch_mode: 'existing_batch', batch_id: batchId }
    : { batch_mode: 'import_only' }
}

export async function submitStageWork(stageRequest, workId, batchChoice) {
  const payload = stagePayload(batchChoice)
  const result = await stageRequest(workId, payload)
  return { payload, result }
}

export function stageSuccessRoute(result) {
  const batch = result?.batch
  if (batch?.round_created && batch.batch_id) {
    return { path: '/research', query: { batch_id: batch.batch_id } }
  }
  return null
}

function backendDetail(error) {
  try {
    const parsed = JSON.parse(error?.detail || '')
    const detail = parsed?.detail
    if (typeof detail === 'string') return detail
    if (detail && typeof detail === 'object') {
      return detail.message || detail.error || JSON.stringify(detail)
    }
    return parsed?.message || ''
  } catch {
    return ''
  }
}

export function stageErrorText(error) {
  const reason = backendDetail(error) || error?.message || String(error)
  return `送入研究库失败：${reason}`
}
