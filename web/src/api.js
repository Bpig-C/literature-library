const BASE = '/api'

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`${res.status} ${res.statusText}: ${body}`)
  }
  return res.json()
}

export function getWorks(params = {}) {
  // Support both object params and pre-built query string
  const q = typeof params === 'string' ? params : new URLSearchParams(params).toString()
  return request(`/works${q ? (q.startsWith('?') ? q : '?' + q) : ''}`)
}

export function getWork(id) {
  return request(`/works/${encodeURIComponent(id)}`)
}

export function updateWork(id, data) {
  return request(`/works/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })
}

export function getRelations() {
  return request('/relations')
}

export function createRelation(data) {
  return request('/relations', { method: 'POST', body: JSON.stringify(data) })
}

export function deleteRelation(data) {
  return request('/relations', { method: 'DELETE', body: JSON.stringify(data) })
}

export function getDuplicates() {
  return request('/duplicates')
}

export function getMergePreview(groupId) {
  return request(`/duplicates/${encodeURIComponent(groupId)}/merge-preview`)
}

export function reviewDuplicate(groupId, decision, note = '', primaryWorkId = null) {
  const payload = { decision, note }
  if (primaryWorkId) payload.primary_work_id = primaryWorkId
  return request(`/duplicates/${encodeURIComponent(groupId)}/review`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function quarantineWork(workId, reason = '') {
  return request(`/works/${encodeURIComponent(workId)}/quarantine`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })
}

export function restoreWork(workId) {
  return request(`/works/${encodeURIComponent(workId)}/restore`, {
    method: 'POST',
  })
}

export function contentUrl(workId) {
  return `${BASE}/files/${encodeURIComponent(workId)}/content`
}

export function pdfUrl(workId) {
  return `${BASE}/files/${encodeURIComponent(workId)}/pdf`
}

export function getMetadataExtractions(params = {}) {
  const q = new URLSearchParams(params).toString()
  return request(`/metadata${q ? '?' + q : ''}`)
}

export function getMetadataExtraction(extId) {
  return request(`/metadata/${encodeURIComponent(extId)}`)
}

export function reviewMetadata(extId, data) {
  return request(`/metadata/${encodeURIComponent(extId)}/review`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })
}

export function applyApprovedMetadata() {
  return request('/metadata/apply-approved', { method: 'POST' })
}

export function batchApproveLowRisk() {
  return request('/metadata/batch-approve-low-risk', { method: 'POST' })
}

export function quarantineFromReview(extId, reason) {
  return request(`/metadata/${encodeURIComponent(extId)}/quarantine`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })
}

// Classification tags
export function getTags(workId) {
  return request(`/classification/tags/${encodeURIComponent(workId)}`)
}

export function createTag(workId, data) {
  return request(`/classification/tags/${encodeURIComponent(workId)}`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export function createTagsBatch(workId, tags) {
  return request(`/classification/tags/${encodeURIComponent(workId)}/batch`, {
    method: 'POST',
    body: JSON.stringify({ tags }),
  })
}

export function deleteTag(tagId) {
  return request(`/classification/tags/${encodeURIComponent(tagId)}`, {
    method: 'DELETE',
  })
}

export function reviewTag(tagId, data) {
  return request(`/classification/tags/${encodeURIComponent(tagId)}/review`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })
}

export function getVocab() {
  return request('/classification/vocab')
}

// Classification extractions
export function getClassificationExtractions(params = {}) {
  const q = new URLSearchParams(params).toString()
  return request(`/classification/extractions${q ? '?' + q : ''}`)
}

export function getClassificationExtraction(extId) {
  return request(`/classification/extractions/${encodeURIComponent(extId)}`)
}

export function reviewClassificationExtraction(extId, data) {
  return request(`/classification/extractions/${encodeURIComponent(extId)}/review`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })
}

export function saveClassificationDraft(extId, data) {
  return request(`/classification/extractions/${encodeURIComponent(extId)}/save-draft`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })
}

export function batchApproveLowAmbiguity() {
  return request('/classification/extractions/batch-approve-low-risk', { method: 'POST' })
}

export function quarantineFromClassificationReview(extId, reason) {
  return request(`/classification/extractions/${encodeURIComponent(extId)}/quarantine`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })
}
