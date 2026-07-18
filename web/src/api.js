const BASE = '/api'

/**
 * API 错误类，用于统一错误处理
 * @typedef {'NETWORK_ERROR'|'TIMEOUT'|'SERVER_ERROR'|'CLIENT_ERROR'|'PARSE_ERROR'} ApiErrorCode
 */
export class ApiError extends Error {
  /**
   * @param {object} params
   * @param {ApiErrorCode} params.code - 错误分类
   * @param {string} params.message - 用户友好消息
   * @param {number} [params.status] - HTTP 状态码
   * @param {string} [params.detail] - 原始错误详情
   */
  constructor({ code, message, status = 0, detail = '' }) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.detail = detail
  }
}

export class TimeoutError extends ApiError {
  constructor(timeout = 30000) {
    super({
      code: 'TIMEOUT',
      message: `请求超时（${timeout / 1000}秒）`,
      detail: `Request timed out after ${timeout}ms`,
    })
    this.name = 'TimeoutError'
    this.timeout = timeout
  }
}

function classifyError(error, status) {
  if (error.name === 'TimeoutError' || error.name === 'AbortError') {
    if (error instanceof TimeoutError) return error
    return new ApiError({ code: 'TIMEOUT', message: '请求已取消', detail: error.message })
  }
  if (error instanceof ApiError) return error
  if (error instanceof TypeError && error.message.includes('fetch')) {
    return new ApiError({ code: 'NETWORK_ERROR', message: '网络连接失败，请检查网络', detail: error.message })
  }
  if (status >= 500) {
    return new ApiError({ code: 'SERVER_ERROR', message: `服务器错误 (${status})`, status, detail: error.message })
  }
  if (status >= 400) {
    return new ApiError({ code: 'CLIENT_ERROR', message: `请求错误 (${status})`, status, detail: error.message })
  }
  return new ApiError({ code: 'NETWORK_ERROR', message: '网络连接失败', detail: error.message })
}

/**
 * 核心请求函数
 * @param {string} path - API 路径
 * @param {object} [options] - fetch 选项
 * @param {AbortSignal} [options.signal] - 外部 AbortSignal
 * @param {number} [options.timeout=30000] - 超时时间(ms)
 * @returns {{ data: Promise, cancel: () => void }}
 */
export async function request(path, options = {}) {
  const { timeout = 30000, signal: externalSignal, ...fetchOptions } = options

  let timeoutId
  let controller
  let signal = externalSignal

  if (!signal) {
    controller = new AbortController()
    signal = controller.signal
    timeoutId = setTimeout(() => controller.abort(), timeout)
  } else {
    timeoutId = setTimeout(() => {
      if (controller) controller.abort()
    }, timeout)
  }

  try {
    const isFormData = fetchOptions.body instanceof FormData
    const defaultHeaders = isFormData ? {} : { 'Content-Type': 'application/json' }
    const res = await fetch(`${BASE}${path}`, {
      headers: { ...defaultHeaders, ...fetchOptions.headers },
      signal,
      ...fetchOptions,
    })

    clearTimeout(timeoutId)

    if (!res.ok) {
      const body = await res.text()
      throw new ApiError({
        code: res.status >= 500 ? 'SERVER_ERROR' : 'CLIENT_ERROR',
        message: `${res.status} ${res.statusText}`,
        status: res.status,
        detail: body,
      })
    }

    try {
      return await res.json()
    } catch (e) {
      throw new ApiError({
        code: 'PARSE_ERROR',
        message: '响应解析失败',
        detail: e.message,
      })
    }
  } catch (error) {
    clearTimeout(timeoutId)
    if (error instanceof ApiError) throw error
    throw classifyError(error, 0)
  }
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

export function previewMetadataRerun(extId, fields, review_note = '') {
  return request(`/metadata/${encodeURIComponent(extId)}/rerun-preview`, {
    method: 'POST',
    timeout: 360000,
    body: JSON.stringify({ fields, review_note }),
  })
}

export function applyMetadataRerun(extId, previewId, newExtraction) {
  return request(`/metadata/${encodeURIComponent(extId)}/rerun-apply`, {
    method: 'POST',
    body: JSON.stringify({ preview_id: previewId, new_extraction: newExtraction }),
  })
}

export function getMetadataRerunPrompt(extId, fields, review_note = '') {
  const params = { fields: fields.join(',') }
  if (review_note) params.review_note = review_note
  const q = new URLSearchParams(params).toString()
  return request(`/metadata/${encodeURIComponent(extId)}/rerun-prompt?${q}`)
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

// ---- Intake (collector A2 review) ----
export function getIntakeCandidates(params = {}) {
  const q = new URLSearchParams(params).toString()
  return request(`/intake/candidates${q ? '?' + q : ''}`)
}

export function getIntakeStats() {
  return request('/intake/stats')
}

export function resolveIntake(data = {}) {
  return request('/intake/resolve', { method: 'POST', body: JSON.stringify(data) })
}

/** 为候选记录上传 PDF（非 arXiv 来源 / agent 手动绑定） */
export function uploadCandidatePdf(candidateId, file) {
  const formData = new FormData()
  formData.append('file', file)
  return request(`/intake/candidates/${encodeURIComponent(candidateId)}/upload-pdf`, {
    method: 'POST',
    body: formData,
    // 不设 Content-Type，让浏览器自动带 multipart/form-data + boundary
  })
}

export function reviewCandidate(id, review_status, note = '') {
  return request(`/intake/candidates/${encodeURIComponent(id)}/review`, {
    method: 'PATCH', body: JSON.stringify({ review_status, note }),
  })
}

export function promoteCandidates(ids) {
  return request('/intake/promote', { method: 'POST', body: JSON.stringify({ ids }) })
}

export function getIntakeTopics(params = {}) {
  const q = new URLSearchParams(params).toString()
  return request(`/intake/topics${q ? '?' + q : ''}`)
}

// 主题成熟度闸门(seedling→proposed→mapped): POST /intake/topics
// body 形状对齐 api/routes/intake.py 的 TopicTransitionBody(id + to_map_status/...)
export function transitionTopic(id, body) {
  return request('/intake/topics', {
    method: 'POST',
    body: JSON.stringify({ id, ...body }),
  })
}

// 按主题发起一次采集(委托 collect_once): POST /intake/collect
export function collectIntake(body) {
  return request('/intake/collect', { method: 'POST', body: JSON.stringify(body) })
}

// 创建新主题: POST /intake/topics/create
export function createTopic(body) {
  return request('/intake/topics/create', { method: 'POST', body: JSON.stringify(body) })
}

// ---- Parse (P3.5 document-parser trigger) ----
export function parseTrigger(payload) {
  return request('/parse/trigger', { method: 'POST', body: JSON.stringify(payload) })
}

export function parseStatus(workId) {
  return request(`/parse/status${workId ? '?work_id=' + encodeURIComponent(workId) : ''}`)
}

// ---- Ingest (inbox 手动摄入, P3.5/B') ----
export function getIngestPlan(params = {}) {
  const q = new URLSearchParams(params).toString()
  return request(`/ingest/plan${q ? '?' + q : ''}`)
}

export function executeIngest(body = {}) {
  return request('/ingest/execute', { method: 'POST', body: JSON.stringify(body) })
}

/**
 * 上传 PDF 文件到收件箱（multipart/form-data）
 * @param {File[]} files - 浏览器 File 对象数组
 * @returns {Promise<object>} { ok, uploaded, ingested, summary }
 */
export async function uploadFiles(files) {
  const formData = new FormData()
  files.forEach(f => formData.append('files', f))

  // multipart 不设置 Content-Type，让浏览器自动加 boundary
  const res = await fetch(`${BASE}/ingest/upload`, {
    method: 'POST',
    body: formData,
    timeout: 120000,
  })

  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new ApiError({
      code: res.status >= 500 ? 'SERVER_ERROR' : 'CLIENT_ERROR',
      message: `上传失败 (${res.status}): ${text.slice(0, 200)}`,
      status: res.status,
      detail: text,
    })
  }

  return res.json()
}

/** Pipeline 流程管理页专用统计 */
export function getPipelineStats() {
  return request('/pipeline/stats')
}

/** 待元数据抽取的 works 列表（解析成功但无 metadata_extraction 记录） */
export function getPendingMetadataWorks(params = {}) {
  const q = new URLSearchParams(params).toString()
  return request(`/pipeline/pending-metadata${q ? '?' + q : ''}`)
}

/** 待分类抽取的 works 列表（元数据已批准但无 classification_extraction 记录） */
export function getPendingClassifyWorks(params = {}) {
  const q = new URLSearchParams(params).toString()
  return request(`/pipeline/pending-classification${q ? '?' + q : ''}`)
}

// ---- Extraction triggers (Phase 1: thin adapters) ----
export function triggerMetadataExtraction(body = {}) {
  return request('/metadata/extract', { method: 'POST', body: JSON.stringify(body) })
}

export function triggerClassificationExtraction(body = {}) {
  return request('/classification/extract', { method: 'POST', body: JSON.stringify(body) })
}

// ---- Discovery (V1.1 受约束广泛发现与检索) ----
export function discoveryPlan(payload) {
  return request('/discovery/plan', { method: 'POST', body: JSON.stringify(payload) })
}

export function discoveryCompositePlan(payload) {
  return request('/discovery/composite-plan', { method: 'POST', body: JSON.stringify(payload) })
}

export function discoveryRun(payload) {
  return request('/discovery/run', { method: 'POST', body: JSON.stringify(payload) })
}

export function getDiscoveryRuns(params = {}) {
  const q = new URLSearchParams(params).toString()
  return request(`/discovery/runs${q ? '?' + q : ''}`)
}

export function getDiscoveryRun(runId) {
  return request(`/discovery/runs/${encodeURIComponent(runId)}`)
}

export function getDiscoveryHits(params = {}) {
  const q = new URLSearchParams(params).toString()
  return request(`/discovery/hits${q ? '?' + q : ''}`)
}

export function postDiscoveryHits(runId, hits) {
  return request(`/discovery/runs/${encodeURIComponent(runId)}/hits`, {
    method: 'POST', body: JSON.stringify(hits),
  })
}

export function acceptDiscoveryHit(hitId, review_note = '') {
  return request(`/discovery/hits/${encodeURIComponent(hitId)}/accept`, {
    method: 'POST',
    body: JSON.stringify({ review_note }),
  })
}

export function rejectDiscoveryHit(hitId, review_note = '') {
  return request(`/discovery/hits/${encodeURIComponent(hitId)}/reject`, {
    method: 'POST',
    body: JSON.stringify({ review_note }),
  })
}

export function batchAcceptDiscoveryHits(hitIds) {
  return request('/discovery/hits/batch-accept', { method: 'POST', body: JSON.stringify({ hit_ids: hitIds }) })
}

/**
 * 构造导出下载 URL（阶段一：引用导出 + 综述矩阵）
 * @param {'bibtex'|'ris'|'matrix.csv'} format
 * @param {object} params - 可选筛选：search / doc_type / tag / work_ids
 */
export function buildExportUrl(format, params = {}) {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') q.append(k, v)
  })
  const qs = q.toString()
  return `${BASE}/export/${format}${qs ? '?' + qs : ''}`
}
