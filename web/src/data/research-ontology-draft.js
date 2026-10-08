import { ontologyDraft, conceptById } from '../researchAssets'
export { ontologyDraft, conceptById }
export function ontologyConceptDisplay(id, version = '') {
  const concept = conceptById[id]
  const versionLabel = version || (concept?.pilotOnly ? ontologyDraft.pilotVersion : ontologyDraft.baselineVersion)
  return { id, zh: concept?.zh || '未收录中文标签', nature: concept ? ontologyDraft.natureLabels[concept.nature] : '未说明', version: versionLabel || '未说明' }
}
