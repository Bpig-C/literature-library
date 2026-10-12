export const METADATA_PROMPT_MODES = [
  { value: 'auto', label: '自动分流：新建/补全/复核' },
  { value: 'extract', label: '首次抽取' },
  { value: 'complete', label: '补全或修订' },
  { value: 'review', label: '独立复核' },
  { value: 'refresh', label: '版本与外部资源更新' },
]

function line(item) {
  const run = item.parse || {}
  const head = item.metadata_head || {}
  const a = item.assets || {}
  const asset = role => {
    const b = a[role]
    return b ? `${b.identity} role=${role} v${b.version} sha256=${b.sha256} bytes=${b.bytes}` : '-'
  }
  return `- ${item.id} | ${item.title || '标题待核'} | A=${item.status} ${head.id || ''} v${head.version || '-'} (${head.agent_review_status || '-'}, ${head.content_state || '-'}) | 解析=${item.parse_ready ? '可读' : '未就绪'} | source_file=${run.source_file_id || '-'} | parse_run=${run.id || '-'} | PDF=${asset('pdf')} | Markdown=${asset('md')} | JSON=${asset('json')} | 开放反馈=${item.open_feedback_count || 0}`
}

function materialLines(origin, materials) {
  const items = materials?.items || []
  if (!items.length) return `（清单未取得：GET ${origin}/api/materials 获取当前资料闭包及逐项 SHA/bytes）`
  return items.map(m => `- ${m.path} | GET ${origin}${m.url} | bytes=${m.bytes} | sha256=${m.sha256}`).join('\n')
}

export function buildMetadataAgentPrompt(items, schema, origin, { mode = 'auto', focus = '', materials = null } = {}) {
  if (!items?.length) return ''
  const rows = items.map(line).join('\n')
  const selected = items.length
  const modeName = METADATA_PROMPT_MODES.find(row => row.value === mode)?.label || mode
  const codeCommit = schema?.code_commit || '未取得（GET /api/research/schema）'
  return `请作为文献库的 A 层（完整书目元数据）总控 Agent，按 Work 而不是研究主题批次处理以下 ${selected} 篇。先只读预检，再分波生产与独立复核。此文本是可编辑工单，复制本身不领取任务，也不改变记录。

【任务】
模式：${modeName}
用户特别关注：${focus.trim() || '无；按实际缺口逐篇判断'}
服务：${origin}/api/research
执行环境：${schema?.environment_id || '未取得；先查询 /api/research/schema 后再写入'}
部署模式：${schema?.read_only ? '只读部署（read_only=true；非 GET 会被 403 拒绝，生产/提交前必须先确认写权限与权威，403 是部署约束不是流程失败）' : '可写部署（写操作仍须正常任务授权）'}
执行位置：本工单不要求访问服务器本地路径；客户端 Agent 按下方【材料获取】与【客户端远程执行补充】取材。
代码提交：${codeCommit}
release：${schema?.release_id || '-'}（manifest ${schema?.manifest_sha256 || '-'}；材料闭包清单 GET ${origin}/api/materials）
入口：${origin}/metadata-workspace
清单生成时点仅供预检，执行前重新读取头版本、开放反馈、解析版本、当前占用与同 Work 的跨批次成果，不得按本清单静默覆盖。

【所选 Work 与材料（含固定版本资产定位）】
${rows}

【分流与顺序】
1. 入库时只需最小 Work 身份。完整 A 在有可读解析材料后处理，与参考文献 R 可并行；C 原文记录、D 解释与风险分类由主题研究批次安排。A 不要求研究 batch_id，提交时不为 A 新造批次或 Work。
2. 每篇先比对当前 A 头、历史修订、反馈、书目投影、源文件/解析版本及外部核查记录。waiting_parse 停在材料待就绪；excluded/conflict 保持显式决定并报告；稳定且无新证据的 A 复用；无 A 则抽取；有缺项/错误则局部修订；review 模式仅由独立执行上下文核查现有版本。不要为了统一轮次重抽。
3. 从原文完整提取作者（全名单）、原始标题及中文原题/译题来源、摘要及其作者原文/译文/Agent 概述来源、日期事件与引用年份、出处、文献类型、发表状态、卷期页码、语言、DOI/arXiv（含版本）和主页/代码/数据/补充材料及开放条件。原文未报告且需要补查的信息查官方来源，逐项记来源、访问日期和不可达情况；不猜填正式发表、开放状态或机构。
4. 契约与手册材料按下方【材料获取】清单逐项取得并核对 SHA 后使用；不要访问任何服务器本地路径，不要把 litlib-asset:// 虚拟引用当普通 PDF。不要固定截取前 N 字符；按材料类型检查正文、首页、附录和官方网站。用中文写说明，原文引文/专名/受控键保持原样。解析 Markdown 是阅读辅助，表格/公式不清时回查 PDF；不得把另一轮解析文件冒充当前来源。
5. 通过正式 API 或 scripts/litlib.py 提交 work_id 级 metadata record，batch_id 留空，显式记录 submitted_by、environment_id、release_id、expected_head_id/supersedes_id 及关联 feedback_id（如适用）。先做结构检查，再由不同执行上下文的核查者重新阅读材料与外部来源并提交审核；生产者改名不构成独立审核。若无法独立复核，保留待审核，不伪造 approved/stable。版本冲突先重新读取；不直接 SQL 改库。
6. 审核获批后核对目录传播、完整作者和书目投影，传播失败按现有重试入口处理。仅实际影响到依赖 A 的 D 时报告影响并安排定向复核，不重写无关 C/D/R。人工采纳一律保持 pending，由用户在页面读完后决定；用户提出质疑时登记反馈，不能直接覆盖旧记录。
7. 每波 3–4 篇（可按材料难度调整）汇报：keep/create/revise/review/waiting_parse/excluded/conflict、原始证据与外部来源、提交/核查身份、版本状态、反馈和未决项。中高风险争议暂停该篇，不阻塞其他篇；最后逐篇从服务端重新读取状态，不能只信子 Agent 回执。

【材料获取（认证只读；逐项核对 SHA 后使用；直接 HTTP 请求须带 Authorization: Bearer 头）】
契约与手册/技能统一经下方清单获取（清单含 contracts/research-workflow-v1.json 的端点定位与 SHA；GitHub raw 按代码提交仅作备选：https://raw.githubusercontent.com/Bpig-C/literature-library/${codeCommit}/contracts/research-workflow-v1.json）：
${materialLines(origin, materials)}

【客户端远程执行补充】
在非服务器机器上执行本工单时：
1. 只读预检：GET ${origin}/api/research/schema 读取 read_only、environment_id 与代码提交/release 绑定；只读部署下一切非 GET 均为 403，属于部署约束，不重试写入，也不将其当作科学流程失败。
2. 材料：契约从上方 GitHub 原始文件按提交读取；手册/技能按【材料获取】清单经 ${origin}/api/materials/<path> 获取（响应头 X-Litlib-SHA256/X-Litlib-Bytes 必须与清单一致）。
3. 固定版本材料：用 scripts/litlib_remote.py --server ${origin} asset <identity> --role md|json|pdf --version <上方清单该资产列明的精确版本> --max-bytes <明确预算> --output <本地新路径> 获取；身份/角色/版本严格按清单，不猜、不换版本；核对返回 SHA/大小后再使用。
4. 认证与传输：LITLIB_REMOTE_TOKEN（≥32 字符）由受控渠道注入进程环境，不写入本工单、代码或命令行，直接 HTTP 请求（含 /api/materials）须带 Authorization: Bearer 头（litlib_remote 已内置）；litlib_remote.py 本身按代码提交从 https://raw.githubusercontent.com/Bpig-C/literature-library/<提交>/scripts/litlib_remote.py 获取（零第三方依赖，Python ≥3.11）；HTTPS 证书须信任服务端提供的 CA；如客户端代理拦截组网虚拟地址，须对该地址配置 NO_PROXY 绕行（地址见服务端交接说明）。
5. 完整材料获取与提交步骤以服务端确认的写权限为前提；只读阶段仅做预检、读取与汇报。

【交付】
逐 Work 的 A 处理矩阵、版本 ID 与状态、独立复核证据、目录传播结果、来源与缺口、需人阅读判断的重点、页面链接。工程通过不等于科学内容正确或用户采纳。`
}
