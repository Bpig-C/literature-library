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
  return `- ${item.id} | ${item.title || '标题待核'} | A=${item.status} ${head.id || ''} v${head.version || '-'} (${head.agent_review_status || '-'}, ${head.content_state || '-'}) | 解析=${item.parse_ready ? '可读' : '未就绪'} | source_file=${run.source_file_id || '-'} | parse_run=${run.id || '-'} | Markdown=${run.content_md_path || '-'} | JSON=${run.content_json_path || '-'} | PDF=${run.source_path || '-'} | 开放反馈=${item.open_feedback_count || 0}`
}

export function buildMetadataAgentPrompt(items, schema, origin, { mode = 'auto', focus = '' } = {}) {
  if (!items?.length) return ''
  const rows = items.map(line).join('\n')
  const selected = items.length
  const modeName = METADATA_PROMPT_MODES.find(row => row.value === mode)?.label || mode
  return `请作为文献库的 A 层（完整书目元数据）总控 Agent，按 Work 而不是研究主题批次处理以下 ${selected} 篇。先只读预检，再分波生产与独立复核。此文本是可编辑工单，复制本身不领取任务，也不改变记录。

【任务】
模式：${modeName}
用户特别关注：${focus.trim() || '无；按实际缺口逐篇判断'}
服务：${origin}/api/research
执行环境：${schema?.environment_id || '未取得；先查询 /api/research/schema 后再写入'}
代码目录：${schema?.code_root || '未取得；先查询 /api/research/schema'}
手册与技能材料根目录：${schema?.runtime_materials_root || '未取得；先查询 /api/research/schema'}
入口：${origin}/metadata-workspace
清单生成时点仅供预检，执行前重新读取头版本、开放反馈、解析版本、当前占用与同 Work 的跨批次成果，不得按本清单静默覆盖。

【所选 Work 与材料】
${rows}

【分流与顺序】
1. 入库时只需最小 Work 身份。完整 A 在有可读解析材料后处理，与参考文献 R 可并行；C 原文记录、D 解释与风险分类由主题研究批次安排。A 不要求研究 batch_id，提交时不为 A 新造批次或 Work。
2. 每篇先比对当前 A 头、历史修订、反馈、书目投影、源文件/解析版本及外部核查记录。waiting_parse 停在材料待就绪；excluded/conflict 保持显式决定并报告；稳定且无新证据的 A 复用；无 A 则抽取；有缺项/错误则局部修订；review 模式仅由独立执行上下文核查现有版本。不要为了统一轮次重抽。
3. 从原文完整提取作者（全名单）、原始标题及中文原题/译题来源、摘要及其作者原文/译文/Agent 概述来源、日期事件与引用年份、出处、文献类型、发表状态、卷期页码、语言、DOI/arXiv（含版本）和主页/代码/数据/补充材料及开放条件。原文未报告且需要补查的信息查官方来源，逐项记来源、访问日期和不可达情况；不猜填正式发表、开放状态或机构。
4. 从代码目录读取 contracts/research-workflow-v1.json；从材料根目录读取 docs/manuals/agent-manual.md、skills/litlib-extract/SKILL.md、skills/litlib-review/SKILL.md，再按发布定义构造 A payload。不要固定截取前 N 字符；按材料类型检查正文、首页、附录和官方网站。用中文写说明，原文引文/专名/受控键保持原样。解析 Markdown 是阅读辅助，表格/公式不清时回查 PDF；不得把另一轮解析文件冒充当前来源。
5. 通过正式 API 或 scripts/litlib.py 提交 work_id 级 metadata record，batch_id 留空，显式记录 submitted_by、environment_id、release_id、expected_head_id/supersedes_id 及关联 feedback_id（如适用）。先做结构检查，再由不同执行上下文的核查者重新阅读材料与外部来源并提交审核；生产者改名不构成独立审核。若无法独立复核，保留待审核，不伪造 approved/stable。版本冲突先重新读取；不直接 SQL 改库。
6. 审核获批后核对目录传播、完整作者和书目投影，传播失败按现有重试入口处理。仅实际影响到依赖 A 的 D 时报告影响并安排定向复核，不重写无关 C/D/R。人工采纳一律保持 pending，由用户在页面读完后决定；用户提出质疑时登记反馈，不能直接覆盖旧记录。
7. 每波 3–4 篇（可按材料难度调整）汇报：keep/create/revise/review/waiting_parse/excluded/conflict、原始证据与外部来源、提交/核查身份、版本状态、反馈和未决项。中高风险争议暂停该篇，不阻塞其他篇；最后逐篇从服务端重新读取状态，不能只信子 Agent 回执。

【交付】
逐 Work 的 A 处理矩阵、版本 ID 与状态、独立复核证据、目录传播结果、来源与缺口、需人阅读判断的重点、页面链接。工程通过不等于科学内容正确或用户采纳。`
}
