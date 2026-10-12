/**
 * Agent 任务提示词生成（工单 LL-UX-EVIDENCE-20260914 工作包 C）。
 *
 * 三种任务模式共用同一上下文装配逻辑（文献详情页与研究详情页的入口、
 * 内嵌入口与悬浮入口都复用这里）：
 * - organize:   整理/补全文献（原单篇研究整理任务）
 * - feedback:   处理反馈（质疑/建议修改 → 修订/有据保留/仍无法确定）
 * - parse-check: 检查解析或展示问题（含解析纠错登记入口）
 *
 * 上下文只带“能实际取得的”信息；取不到的明确写“未取得”，不猜测。
 */

const MISSING = '未取得，请先核对；不要猜测'

export const AGENT_TASK_MODES = [
  { value: 'organize', label: '整理/补全文献' },
  { value: 'feedback', label: '处理反馈' },
  { value: 'parse-check', label: '检查解析或展示问题' },
]

export const BATCH_AGENT_TASK_MODES = [
  { value: 'full', label: '批次 C/D/R 完整整理' },
  { value: 'resume', label: '断点续跑（自动识别）' },
  { value: 'metadata-references', label: '补参考文献与 A 依赖核查' },
  { value: 'targeted-revision', label: '定向修订 / 轻量补跑' },
  { value: 'review-only', label: '独立复核现有结果' },
]

/** 两条既定核查规则（随公共上下文进入每个提示词，不只留在单篇扩展里）。 */
const COMMON_REVIEW_RULES = `【两条既定核查规则（对所有任务生效）】
1. 没有观察到某种更新，不证明存在另一形成机制；“未观察到 X”不得写成“X 通过 Y 形成/未发生”。
2. 每次修订必须逐字段审查删除差异，包括具名扩展（extensions）；所有删除必须给出明确理由，静默丢弃具名扩展视为缺陷。`

/** 反馈处理提示词的六条硬性要求（工单 §5）。 */
const FEEDBACK_HARD_REQUIREMENTS = `【处理反馈的硬性要求】
1. 先读取最新版本、占用（租约/心跳）与全部未闭环反馈及其依赖，避免并发覆盖同一记录。
2. 回查固定原文快照与必要原件后再判断；用户意见是待核实问题，不自动视为正确答案。
3. 逐条反馈给出三种结论之一：需修订 / 有据保留（retained_with_evidence，须附快照锚点证据）/ 仍无法确定（unresolved）；不能猜填。
4. 修订时逐字段检查新旧差异，具名扩展同样在保全范围内；所有删除须有明确理由。
5. 通过现有服务提交（接口或 scripts/litlib.py），显式绑定环境、版本（supersedes 当前头）、发布包与对应反馈（feedback_id）；执行对应类型的独立核查与闭环；不直接 SQL 改状态。
6. 返回实际改动、证据、状态、剩余问题和页面入口；不代用户作人工采纳。`

/** 把反馈/解析纠错清单渲染进提示词（选中项在前）。 */
function renderFeedbackSection(feedbackItems, parseIssues) {
  const lines = []
  if (feedbackItems?.length) {
    lines.push('【待处理反馈（含历史版本登记，状态以服务端为准）】')
    for (const item of feedbackItems) {
      const target = `${item.layer}:${item.target_id}${item.target_version != null ? ` v${item.target_version}` : ''}`
      const revision = item.formal_revision_id ? `；已关联修订 ${item.formal_revision_id}` : ''
      lines.push(`- [${item.status}] ${item.id} @ ${target} · ${item.explicit_claim}${revision}${item.detail ? ` · 补充：${item.detail}` : ''}`)
    }
  }
  if (parseIssues?.length) {
    lines.push('【待处理解析纠错登记（状态机：open→candidate→verified→adopted）】')
    for (const item of parseIssues) {
      lines.push(`- [${item.status}] ${item.id} @ 快照 ${item.base_snapshot_id} 偏移 ${item.start_offset}–${item.end_offset}（${item.location_status}）· ${item.problem} · 建议：${item.suggestion || '未提供'}`)
    }
  }
  if (!lines.length) lines.push('【待处理反馈】当前没有读取到未闭环反馈；如用户口述了新问题，先按下方登记要求补录，再处理。')
  return lines.join('\n')
}

/** 固定版本资产定位行；assets 由 /api/research/query 逐条携带。 */
function assetLineOf(assets, role) {
  const b = assets?.[role]
  return b ? `${b.identity} role=${role} v${b.version} sha256=${b.sha256} bytes=${b.bytes}` : '未登记（报缺口，不猜版本）'
}

/** 公共上下文：Work、来源、批次、快照、头、解析路径、页面入口。 */
function buildContextBlock(record, work, schema, origin, batchIdOverride) {
  const source = record.source || {}
  const snapshot = record.snapshot || {}
  const workId = source.work_id || work?.id || record.work_id
  const parseId = snapshot.parse_run_id || source.parse_run_id
  // 新解析不是本记录绑定解析的替身：必须按 id+source_file 匹配
  const parse = work?.parse_runs?.find(item => item.id === parseId && item.source_file_id === source.source_file_id)
  const batchId = batchIdOverride || record.batch_id
  const binding = row => row ? `${row.id}；版本 ${row.version}；定义 ${row.schema_version || MISSING}；状态 ${row.content_state || MISSING}` : '尚未生成'
  const root = (source.source_path || '').replace(/\\/g, '/').match(/^(.*)\/works\//)?.[1]
  const assets = record.assets || {}
  const assetLine = role => assetLineOf(assets, role)
  return `论文：${work?.title || workId || MISSING}
Work ID：${workId || MISSING}
批次：${batchId || MISSING}
批次钉定发布包 release_id：${record.batch_release_id || MISSING}（缺失时先回查实际批次，不得以最新发布包代替）
研究来源：${source.id || MISSING}
source_file_id：${source.source_file_id || MISSING}
parse_run_id：${parseId || MISSING}
原文快照：${snapshot.id || MISSING}；版本 ${snapshot.version ?? MISSING}
快照 SHA256：${snapshot.content_sha256 || MISSING}
原文记录：${binding(record.source_record)}
解释记录：${binding(record.interpretation)}
本体版本：${record.interpretation?.ontology_version || MISSING}
执行环境：${schema?.environment_id || MISSING}
API：${origin}/api/research
页面：${origin}/research/records/${encodeURIComponent(workId || '')}${batchId ? `?batch_id=${encodeURIComponent(batchId)}${source.id ? `&source_id=${encodeURIComponent(source.id)}` : ''}` : ''}
文献页：${workId ? `${origin}/works/${encodeURIComponent(workId)}` : MISSING}

【固定版本材料定位（identity/role/version 来自服务端登记，不猜不换）】
PDF：${assetLine('pdf')}
Markdown：${assetLine('md')}
JSON：${assetLine('json')}
固定快照读取（C 层原文）：${source.id && snapshot.id ? `${origin}/api/research/sources/${encodeURIComponent(source.id)}/text?snapshot_id=${encodeURIComponent(snapshot.id)}` : MISSING}
材料/手册/契约获取：GET ${origin}/api/materials（逐项带 sha256/bytes；响应头 X-Litlib-SHA256/X-Litlib-Bytes 必须与清单一致）
资产读取：litlib_remote.py --server ${origin} asset <identity> --role <pdf|md|json> --version <上行列明的版本> --max-bytes <预算> --output <本地新路径>（--server 在 asset 子命令之前）；服务器本地路径与 litlib-asset:// 虚拟引用不适用于客户端执行
证据 quote/offset 必须对齐固定快照（Unicode 码点偏移，含 
；渲染后的 HTML/DOM 偏移不是原文字符偏移）。不能将另一轮或最新解析静默替换当前绑定。资产未取得时明确报缺口，不自行生成路径。`
}

function commonSkills(origin, schema) { return `【通用技能与填写要求】
契约与手册经认证端点获取：GET ${origin}/api/materials（清单含 contracts/research-workflow-v1.json、docs 手册与全部 skills 及各自 SHA/bytes；也可按 schema.code_commit 从 GitHub 原始文件取得，逐项核对 SHA）。
按任务读取 skills/litlib-batch/SKILL.md、skills/litlib-extract/SKILL.md、skills/litlib-interpret/SKILL.md、skills/litlib-review/SKILL.md 及其必要引用文件（同清单获取）。不要从不可变资产 URI 推导本地项目目录，不访问服务器本地路径。
先读取实际批次钉定的发布包/任务与当前定义；接口或 scripts/litlib.py 是提交入口。CLI 必须显式绑定已核对的环境，不直接 SQL 改记录或审核状态。
复用已有 Work ID、PDF、解析和历史。回看旧修订、工作稿与反馈；若记录已更新，先核对差异再做新修订，不把旧卡片当最新记录。
Agent 撰写的说明字段使用中文；论文/模型专名、稳定编号、受控键、原文引文及定位保留原样。每项实质判断保留对应证据，缺口不得猜填。
由另一名独立 Agent 回看固定原文与依赖，不得换身份自审。无法安排独立核查时交付待核查版本；不能伪造 stable 或人工采纳。
保存、复制或生成本提示词都不表示任务已派发或已开始执行。` }

/**
 * 生成任务提示词。
 * options: { mode='organize', focus='', feedbackItems=[], parseIssues=[], batchId=null }
 */
export function buildResearchAgentPrompt(record, work, schema, origin, options = {}) {
  const mode = options.mode || 'organize'
  const context = buildContextBlock(record, work, schema, origin, options.batchId)
  const focus = (options.focus || '').trim()
  const focusBlock = focus ? `我特别关注的问题：${focus}\n` : '我特别关注的问题：（请在这里补充；也可保留为空）\n'
  const parts = []
  parts.push(`【部署模式与执行位置】
部署模式：${schema ? (schema.read_only ? '只读部署（read_only=true；非 GET 会被 403 拒绝，403 是部署约束不是流程失败，不重试写入）' : '可写部署（写操作仍须正常任务授权）') : '未知（schema 未取得；一律按只读处理，先 GET /api/research/schema 确认）'}
执行位置：本工单不要求访问服务器本地路径。取材通道（全部经 ${origin}，直接 HTTP 请求须带 Authorization: Bearer 头，litlib_remote 已内置）：①契约 GET ${origin}/api/materials/contracts/research-workflow-v1.json（备选：https://raw.githubusercontent.com/Bpig-C/literature-library/${schema?.code_commit || '<先 GET /api/research/schema 取代码提交>'}/contracts/research-workflow-v1.json）；②手册/技能 清单 GET ${origin}/api/materials，逐项核对 X-Litlib-SHA256/X-Litlib-Bytes；③固定版本资产用 litlib_remote.py --server ${origin} asset <identity> --role md|json|pdf --version <工单/清单列明的精确版本> --max-bytes <预算> --output <本地新路径>，身份/版本不猜不换。litlib_remote.py 本身按 ${schema?.code_commit ? 'https://raw.githubusercontent.com/Bpig-C/literature-library/' + schema.code_commit + '/scripts/litlib_remote.py' : '<先取 schema.code_commit，再从同路径取得>'} 获取（零第三方依赖，Python ≥3.11）。认证：LITLIB_REMOTE_TOKEN 由受控渠道注入进程环境；HTTPS 须信任服务端 CA；客户端代理拦截组网虚拟地址时须对该地址配置 NO_PROXY 绕行（地址见服务端交接说明）。只读阶段仅做预检、读取与汇报。`)

  if (mode === 'organize') {
    parts.push(`请对以下文献开展单篇研究整理，开始前核对任务范围；已有 Agent 正在处理时，不要重复领取或并发改写同一记录。

【可修改的任务范围】
本次目标：检查缺口，按当前批次发布定义补全 C 原文记录、D 解释与分类，并交由独立 Agent 核查；A 元数据按 Work 独立处理，必要时从元数据工作台衔接。
${focusBlock}仅处理本篇，不批量处理其他论文，不修改程序、迁移数据库或发布新本体，不替用户记录人工采纳。

【当前卡片上下文：执行前重新确认是否已被其他 Agent 更新】
${context}`)
    parts.push(`根据材料类型阅读全文或遍历相关章节、方法、结果、图表与附录，不固定截取前若干字符。报告未读/未报告/解析缺失的真实覆盖状态。
元数据区分日期事件、版本、摘要来源与开放资源；原文按研究单元记录作者定义、条件、主张、结果及局限；解释区分观察和推断、能力和自然倾向、形成/表现/影响，绑定风险概念和参数/harness 坐标。
逐研究单元先判定实际更新：few-shot/in-context 提示不等于参数训练；部署/测试环境变化不等于 harness 更新。内/外对齐概念也不等于参数/harness 双循环。混合论文按 scope_refs 拆分 association；只有确有不同干预时才用相应坐标，不能把整篇归成唯一参数更新。
证据锚点逐字匹配仅说明定位正确；核查者还须逐字段检查引文是否支持完整清单/数值/机制，不能以同章节引文代替具体支撑。覆盖声明必须与实际抽取的章节/单元相符。
元数据外部核查单列执行结果：正式出版/DOI、版本日期、开放资源在原文未报告时，按授权访问官方来源补查并记录访问日期和来源；无法访问则标记未核查，交付不得称已完成外部核查。原始 arXiv 基础编号与文件版本 vN 分别保留，不用编号推导结果冒充官方发布日期。`)
  } else if (mode === 'feedback') {
    parts.push(`请处理以下文献的研究反馈（质疑/建议修改），开始前核对任务范围与占用；已有 Agent 正在处理时，不要重复领取或并发改写同一记录。

【可修改的任务范围】
本次目标：逐条核实反馈，给出 需修订 / 有据保留 / 仍无法确定 的结论；需修订的通过现有服务完成正式修订、独立核查与反馈闭环。不直接替用户记录人工采纳，不把“已提交修订”冒充“已纠正”。
${focusBlock}
${renderFeedbackSection(options.feedbackItems, options.parseIssues)}

【当前卡片上下文：执行前重新确认是否已被其他 Agent 更新】
${context}`)
    parts.push(FEEDBACK_HARD_REQUIREMENTS)
  } else {
    parts.push(`请检查以下文献的解析与展示问题，开始前核对任务范围；已有 Agent 正在处理时，不要重复领取或并发改写同一记录。

【可修改的任务范围】
本次目标：区分“渲染错误”（只修展示层，不改快照）与“解析内容错误”（对照原件登记解析纠错并走修正流程）。渲染缺陷不虚构论文内容修订；解析纠错不得把解释意见掺入解析文本，不修改作者原文语义。
${focusBlock}
${renderFeedbackSection(options.feedbackItems, options.parseIssues)}

【当前卡片上下文：执行前重新确认是否已被其他 Agent 更新】
${context}

【解析纠错最小流程（服务端已支持，禁止 SQL 直改）】
所有纠错写请求必须携带上方实际 environment_id；读取失败须先重新取得环境身份。候选写携 expected_candidate_version（首次为0）；verify/adopt 均携当前 candidate_version，verify note 必须非空并说明原件定位与依据。候选替换后原审核不继承；GET 单条详情查看候选历史，列表提供当前候选版本。缺字插入用 problem_quote="" 且 start_offset=end_offset；删除用 replacement_text=""。
1. 对具体解析版本（base_snapshot_id）、段落/表格/公式登记问题：POST /research/parse-corrections，保存原始定位（quote+码点偏移）、问题描述与建议；重复引文须给偏移钉住具体一处，不允许默认取第一处。
2. 提交局部修正候选：POST /research/parse-corrections/{id}/candidate，记录基础版本、前后差异、依据与执行者；旧解析资产与已引用快照保持可查。
3. 独立核对原件后核查：POST /research/parse-corrections/{id}/verify（核查者不得与提交者同身份）；未核查不得采用。
4. 采用生成新快照（POST .../adopt，旧快照不变）；下游通过现有 POST /research/source-records（supersedes 当前头、绑定新快照）重新提交并重新核查锚点。GET .../impact 提供受影响证据的重定位分析：唯一/可复核匹配是辅助定位，重复或不匹配的如实待核查，不得继承旧偏移冒充有效。`)
  }

  parts.push(commonSkills(origin, schema))
  parts.push(COMMON_REVIEW_RULES)

  parts.push(`【交付】
返回当前记录编号/版本/状态、主要改动、证据与未决项、页面链接，以及需要用户理解或判断的具体字段。工程运行成功不等于科学结论通过。`)
  return parts.join('\n\n')
}

function compactBatchRow(row) {
  const source = row?.source || {}
  const snapshot = row?.snapshot || {}
  const sourceRecord = row?.source_record
  const interpretation = row?.interpretation
  const describe = value => value
    ? `${value.id} v${value.version ?? '?'} / ${value.content_state || '状态未提供'} / ${value.agent_review_status || '审查状态未提供'} / ${value.validity_status || '有效性未提供'}`
    : '尚未生成'
  const assets = row?.assets || {}
  const asset = role => {
    const b = assets[role]
    return b ? `${b.identity} role=${role} v${b.version} sha256=${b.sha256} bytes=${b.bytes}` : '未登记（报缺口，不猜版本）'
  }
  return `- ${source.work_id || 'Work ID 未取得'}；source=${source.id || '未取得'}；snapshot=${snapshot.id || '未取得'}@${snapshot.content_sha256 || 'hash 未取得'}；C原文=${describe(sourceRecord)}；D解释=${describe(interpretation)}；PDF=${asset('pdf')}；Markdown=${asset('md')}；JSON=${asset('json')}；A元数据按 Work 从元数据工作台查询，R参考文献从正式接口查询`
}

const BATCH_MODE_INSTRUCTIONS = {
  full: `本次是主题批次的 C/D/R 完整整理。A 元数据按 Work 独立处理；如缺少稳定 A，在元数据工作台另列待办并协调 Agent，不把它伪装为批次写入。若预检发现已有稳定记录，不得覆盖；转为逐篇断点续跑。`,
  resume: `本次是断点续跑。先为每篇建立 A/C/D/R 状态矩阵，只处理缺失、needs_completion、needs_review、stale、开放反馈或依赖已变化的部分。稳定且依赖未变化的层必须复用，不为满足统一轮数而重写。`,
  'metadata-references': `本次处理 R 参考文献链并核查 A 依赖。A 的批量抽取/补全请从元数据工作台生成独立 Work 级工单；现有稳定 C/D 保持不动。若 A 更新影响 D 钉定，先影响分析，再做有据的定向修订与独立核查。`,
  'targeted-revision': `本次是定向修订。先读取用户给出的字段、本体、定义、反馈或解析变更，执行影响分析；只修订受影响的记录和字段。字段拆分/废弃要保留旧版本与迁移状态，不把结构升版变成全库无差别重抽。`,
  'review-only': `本次只做独立复核。不得由核查者改写后再批准自己的结果；发现问题时登记反馈/needs_revision 并给出证据，另交生产者修订。不得代替人工采纳。`,
}

/** 批次级 Agent 工单：界面只生成可编辑文本，不领取任务或修改记录。 */
export function buildResearchBatchAgentPrompt(batch, rows, schema, origin, options = {}) {
  const mode = options.mode || 'resume'
  const focus = (options.focus || '').trim() || '无额外限定；按当前模式和实际状态矩阵执行。'
  const manifest = (rows || []).map(compactBatchRow).join('\n') || '- 批次条目未取得；停止写入并先修复读取。'
  const returned = rows?.length || 0
  const total = Number(options.total ?? batch?.works ?? returned)
  const coverageWarning = returned < total
    ? `警告：界面只取得 ${returned}/${total} 条。执行前必须从正式任务包取得完整清单，不能把未返回条目当作不存在。`
    : `界面取得 ${returned}/${total} 条；执行时仍须用正式任务包重新确认。`

  return `请作为本研究批次的总控 Agent，按固定快照和当前发布包组织批量处理。先只读预检，再分波执行；已有 Agent 占用的条目不得并发改写。

【部署模式与执行位置】
部署模式：${schema ? (schema.read_only ? '只读部署（read_only=true；非 GET 会被 403 拒绝，403 是部署约束不是流程失败，不重试写入）' : '可写部署（写操作仍须正常任务授权）') : '未知（schema 未取得；一律按只读处理，先 GET /api/research/schema 确认）'}
执行位置：本工单不要求访问服务器本地路径。取材通道（全部经 ${origin}，直接 HTTP 请求须带 Authorization: Bearer 头，litlib_remote 已内置）：①契约 GET ${origin}/api/materials/contracts/research-workflow-v1.json（备选：https://raw.githubusercontent.com/Bpig-C/literature-library/${schema?.code_commit || '<先 GET /api/research/schema 取代码提交>'}/contracts/research-workflow-v1.json）；②手册/技能 清单 GET ${origin}/api/materials，逐项核对 X-Litlib-SHA256/X-Litlib-Bytes；③固定版本资产用 litlib_remote.py --server ${origin} asset <identity> --role md|json|pdf --version <工单/清单列明的精确版本> --max-bytes <预算> --output <本地新路径>，身份/版本不猜不换。litlib_remote.py 本身按 ${schema?.code_commit ? 'https://raw.githubusercontent.com/Bpig-C/literature-library/' + schema.code_commit + '/scripts/litlib_remote.py' : '<先取 schema.code_commit，再从同路径取得>'} 获取（零第三方依赖，Python ≥3.11）。认证：LITLIB_REMOTE_TOKEN 由受控渠道注入进程环境；HTTPS 须信任服务端 CA；客户端代理拦截组网虚拟地址时须对该地址配置 NO_PROXY 绕行（地址见服务端交接说明）。只读阶段仅做预检、读取与汇报。

【批次与模式】
批次名称：${batch?.name || '未取得'}
batch_id：${batch?.id || options.batchId || '未取得'}
批次状态：${batch?.status || '未取得'}
parent_batch_id：${batch?.parent_batch_id || '无'}
release_id：${batch?.release_id || '未取得；必须先回查，不能自动改用最新发布包'}
执行环境：${schema?.environment_id || '未取得；停止写入并先核对'}
任务模式：${BATCH_AGENT_TASK_MODES.find(item => item.value === mode)?.label || mode}
用户特别关注：${focus}
${BATCH_MODE_INSTRUCTIONS[mode] || BATCH_MODE_INSTRUCTIONS.resume}

【四条内容线及依赖】
1. A 元数据：按 Work 独立于本研究批次组织；本工单只回查当前 A 头与 D 的依赖。缺 A 或需补全时到 ${origin}/metadata-workspace 生成批量工单，不为了本批次重抽稳定 A。
2. C 原文遵循记录：基于固定快照记录研究单元、定义、背景/条件、方法、观察、作者主张、结果、局限和未决项；不混入研究者解释。
3. D 解释与分类：只能基于已核查的 C 及钉定 A，区分观察与推断、能力与自然倾向、形成/表现/影响以及参数/harness 双循环坐标。
4. R 参考文献：候选条目提取只依赖解析快照，可与 A/C 并行；候选身份匹配使用 DOI/arXiv/标题与版本关系，引用边必须有固定快照锚点并由独立身份核验。不得凭相似标题静默绑定。

【批次当前清单（只作生成时快照；行内已列各文献固定版本 PDF/Markdown/JSON 的 identity/role/version/sha/bytes，与 snapshot SHA 对账，取材版本以此为准、不猜不换）】
${coverageWarning}
${manifest}

【执行流程】
1. 从 ${origin}/api/research/schema、${origin}/api/overview 和批次 task-package 重新核对 environment_id、release_id、定义 SHA、完整条目、A/C/D/R 当前头、未闭环反馈、lease/heartbeat、expected_head_id 与解析质量。生成提示词不会领取任务；真正开始时才使用唯一 worker_owner 领取。
2. 形成逐篇状态矩阵，列出 keep / create / revise / review / blocked 及理由。禁止把“表存在”“锚点逐字匹配”当作内容完整。
3. 先用 2 篇校准；通过后每波 3–4 篇。生产者可并行，核查者必须使用不同身份并重新读取固定快照与依赖。总控统一管理 lease、heartbeat、attempt、operation_id、expected head 和冲突恢复。
4. 每层允许基于核查意见修订，但不得为了满足轮数机械重写。配额耗尽仍有中高风险问题时隔离该篇，继续其他安全条目。
5. 所有正式写入通过现有 API 或 scripts/litlib.py；禁止直接 SQL 改记录、审查状态或人工采纳。版本冲突时重新读取 head，不覆盖他人结果。
6. 每波 reconcile，并报告成功、待修订、阻塞、未处理和下一波；最终逐项查库核实 active/stable/approved 与依赖关系，不能采信子 Agent 的口头汇报。

${commonSkills(origin, schema)}

${COMMON_REVIEW_RULES}

【交付】
交付批次状态矩阵、每篇 A/C/D/R 结果与版本、独立核查者、反馈闭环、引用匹配/核验统计、真实未决项、失败与恢复记录、页面链接。人工采纳保持 pending，交给用户判断。`
}
