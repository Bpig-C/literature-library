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
  const q = new URLSearchParams(params).toString()
  return request(`/works${q ? '?' + q : ''}`)
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

export function reviewDuplicate(groupId, data) {
  return request(`/duplicates/${encodeURIComponent(groupId)}/review`, {
    method: 'POST',
    body: JSON.stringify(data),
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
