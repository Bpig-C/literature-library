export const displayArtifact = { records: {} }
export const ontologyDraft = { concepts: [], natureLabels: {}, locationLabels: {}, sources: [] }
export const conceptById = {}
export function installResearchAssets(payload) {
  if (!payload?.reading?.records || !Array.isArray(payload?.ontology?.concepts)) throw new Error('研究展示资产格式无效')
  for (const key of Object.keys(displayArtifact)) delete displayArtifact[key]
  Object.assign(displayArtifact, payload.reading)
  for (const key of Object.keys(ontologyDraft)) delete ontologyDraft[key]
  Object.assign(ontologyDraft, payload.ontology)
  for (const key of Object.keys(conceptById)) delete conceptById[key]
  for (const concept of ontologyDraft.concepts) conceptById[concept.id] = concept
}
export async function loadResearchAssets() {
  const response = await fetch('/api/research/runtime-assets', { cache: 'no-store' })
  if (!response.ok) {
    let detail = ''
    try { detail = (await response.json()).detail || '' } catch {}
    throw new Error(`研究展示资产未完整恢复（${response.status}）：${typeof detail === 'string' ? detail : JSON.stringify(detail)}`)
  }
  installResearchAssets(await response.json())
}
