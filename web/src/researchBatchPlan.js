export const RESEARCH_BATCH_TARGET_MODES = [
  { value: 'source-and-interpretation', label: '原文记录 + 解释与分类' },
  { value: 'source-only', label: '仅原文记录（解释不适用）' },
]

export const DEFAULT_BATCH_SELECTION_FOCUS =
  '筛选与 AI 自主性失控风险直接相关、能够支持风险分类与研究脉络整理的材料。优先关注欺骗与策略性行为、评估感知、能力隐藏、目标错误泛化、奖励篡改、工具权限扩张、自我复制、关停规避，以及对这些风险有实质章节的综合报告。'

export const DEFAULT_BATCH_SELECTION_EXCLUSIONS =
  '排除只有通用能力、常规安全或产品说明，且没有自主性风险实证、机制、评估或重要综述内容的材料；尤其不要仅因标题含“安全”“系统卡”就纳入国内外通用模型系统卡。重复版本只保留适合本轮处理的主版本。'

function cleanPromptValue(value, fallback) {
  const text = String(value || '').trim()
  return text || fallback
}

export function buildBatchSelectionAgentPrompt({
  origin = 'http://localhost:19528',
  focus = DEFAULT_BATCH_SELECTION_FOCUS,
  exclusions = DEFAULT_BATCH_SELECTION_EXCLUSIONS,
  desiredCount = 12,
  releaseId = '',
  stagedSourceCount = null,
} = {}) {
  const baseUrl = String(origin || 'http://localhost:19528').replace(/\/$/, '')
  const count = Math.max(1, Number.parseInt(desiredCount, 10) || 12)
  const releaseNote = releaseId
    ? `当前页面取得的正式发布包是 ${releaseId}；建批前仍须通过 API 重新读取并核对。`
    : '页面尚未取得正式发布包；建批前必须通过 API 读取当前正式发布包。'
  const sourceNote = Number.isFinite(Number(stagedSourceCount))
    ? `当前搜索入口可见约 ${Number(stagedSourceCount)} 条已进入研究库的来源，这只是候选池的一部分，不能代替对书目库和解析结果的筛选。`
    : '不要把已进入研究库的来源误当成全部候选；还要检查已解析但尚未送入研究库的材料。'

  return `你在本地项目 D:\\02_academic\\doctoral\\literature_library 中工作。请为 Scholar OS 规划一个新的研究批次，目标规模约 ${count} 篇。

研究目标：
${cleanPromptValue(focus, DEFAULT_BATCH_SELECTION_FOCUS)}

排除与降级条件：
${cleanPromptValue(exclusions, DEFAULT_BATCH_SELECTION_EXCLUSIONS)}

工作原则：
1. 先只读筛选，不要立即创建批次、领取任务、提交原文记录或解释记录。
2. 标题和书目元数据只能用于召回，不能单独作为纳入依据。对疑似相关材料选择性查看摘要、目录和解析后的 Markdown 关键段落；不要按固定字符数截断，也不要求把所有候选全文通读一遍。
3. 把候选分为“核心纳入”“背景/综合材料”“需抽样确认”“排除”四档。每篇至少列出 work_id、标题、当前解析/入库状态、档位、证据依据和纳入或排除理由。通用系统卡若没有本研究所需的实质内容，应明确排除。
4. 检查重复 Work、预印本/正式版及同一材料的多版本关系，说明保留哪个版本；不要为同一文献新建重复 Work。
5. ${sourceNote}
6. 先向用户提交建议清单、建议批次名称、预计篇数和仍需人工决定的问题，并等待用户明确确认。未获确认不得写库。

用户确认后的执行规则：
1. 仅处理确认清单。用 GET ${baseUrl}/api/works?per_page=200&page=1 分页查看书目库，用 GET ${baseUrl}/api/pipeline/unstaged-works?per_page=200&page=1 查看已解析但尚未送入研究库的材料。确认纳入后，通过 POST ${baseUrl}/api/research/works/{work_id}/stage，JSON body 为 {"batch_mode":"import_only"}，将其送入研究库；不得直接写 SQLite。
2. 用 GET ${baseUrl}/api/research/search?q=&limit=200 取得 source_id，用 GET ${baseUrl}/api/research/sources/{source_id} 逐篇选择最新且匹配当前解析内容的 snapshot_id。
3. 用 GET ${baseUrl}/api/research/releases/current 取得并固定正式 release。${releaseNote}
4. 在真正写入前，把最终 source_ids、snapshot_ids、release_id、批次名称和 targets 展示给用户复核。默认 targets 为 source_record=required、interpretation=required；元数据 A 与参考文献 R 由后续工单处理，不冒充本批次 C/D 完成门。
5. 用户确认后只调用一次 POST ${baseUrl}/api/research/batches/plan；使用稳定 request_key，网络重试复用同一 key。创建完成即停止，不自动领取任务，不开始抽取。
6. 最终报告 batch_id、纳入/排除清单、各材料固定的 snapshot、release、未决项。任何失败都如实报告，不用旧分类流程兜底。

先从 /api/research/schema 核对代码目录与手册技能材料根目录；从材料根目录阅读 docs/CURRENT_STATE.md、docs/workflows/research-organization.md、docs/manuals/agent-manual.md 和 contracts/research-workflow-v1.json。第一轮只给筛选结果，不执行写操作。`
}

export function makeBatchRequestKey(now = Date.now(), nonce = '') {
  const suffix = nonce || (globalThis.crypto?.randomUUID?.() || Math.random().toString(16).slice(2))
  return `ui-research-batch-${now}-${suffix}`
}

export function chooseDefaultSnapshot(snapshots = []) {
  if (!snapshots.length) return null
  return [...snapshots].sort((a, b) => {
    const version = Number(b.version || 0) - Number(a.version || 0)
    if (version) return version
    return String(b.created_at || '').localeCompare(String(a.created_at || ''))
  })[0]
}

export function validateBatchDraft({ name, sourceIds, snapshotIds, releaseId }) {
  if (!String(name || '').trim()) return '请填写批次名称。'
  if (!sourceIds?.length) return '请至少选择一篇已经进入研究库的文献。'
  const missing = sourceIds.filter(id => !snapshotIds?.[id])
  if (missing.length) return `以下来源尚未选择固定快照：${missing.join('、')}`
  if (!releaseId) return '当前正式发布包尚未取得，不能创建会漂移的批次。'
  return ''
}

export function buildBatchPlanPayload({
  name, sourceIds, snapshotIds, releaseId, requestKey, targetMode = 'source-and-interpretation',
}) {
  const error = validateBatchDraft({ name, sourceIds, snapshotIds, releaseId })
  if (error) throw new Error(error)
  return {
    request_key: requestKey,
    name: String(name).trim(),
    source_ids: [...sourceIds],
    snapshot_ids: Object.fromEntries(sourceIds.map(id => [id, snapshotIds[id]])),
    release_id: releaseId,
    targets: {
      source_record: 'required',
      interpretation: targetMode === 'source-only' ? 'not_applicable' : 'required',
    },
  }
}
