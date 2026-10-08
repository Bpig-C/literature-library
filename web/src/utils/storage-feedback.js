export async function readMaterial(response) {
  if (!response.ok) {
    let detail
    try { detail = await response.json() } catch { detail = null }
    const message = typeof detail?.detail === 'string' ? detail.detail : `HTTP ${response.status}`
    throw new Error(`正文读取失败：${message}。请重试或核查材料状态。`)
  }
  return response.text()
}

export function parseSummary(result) {
  const succeeded = Number(result?.succeeded || 0)
  const failed = Number(result?.failed || 0)
  if (!succeeded || failed) {
    throw new Error(`解析成功 ${succeeded} 篇，失败 ${failed} 篇；请查看各篇解析状态后重试失败项。`)
  }
  return `解析成功 ${succeeded} 篇，可继续送入研究库`
}

export function freezeMaterialSelection(selection) {
  if (!selection?.parse_run_id || !selection?.source_file_id || !Number.isInteger(selection.version) || selection.version < 1) {
    throw new Error('材料版本选择无效，请重新加载。')
  }
  return Object.freeze({ parse_run_id: selection.parse_run_id, source_file_id: selection.source_file_id, version: selection.version })
}
