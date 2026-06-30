# 文献库未来工作计划

> 状态：当前路线图
> 更新时间：2026-06-30
> 当前基线：V1 发布阻断项已清零；V1.1 前端端到端主流程已完成。最近复核：`pytest tests\ -q` 通过，`scripts/healthcheck_library.py --json` 五类问题全空，`npm.cmd run build` 通过。V1 详见 `docs/superpowers/reviews/2026-06-29-v1-final-publication-p1-remediation.md`，V1.1 主流程详见 `docs/superpowers/reviews/2026-06-30-v1.1-frontend-end-to-end-flow-result.md`。

本文档只记录尚未完成、需要继续规划或实施的工作。已完成阶段、旧判断和历史路线迁移到 `docs/PROJECT_HISTORY.md`；分阶段细节保留在 `docs/superpowers/plans/` 与 `docs/superpowers/reviews/`。

## 维护原则

- 当前事实以代码、测试、healthcheck 和 active 文档为准，不以历史计划为准。
- 新增任务进入本文档前，应确认不是已有历史计划中的已完成项。
- 完成后的任务应迁移到 `docs/PROJECT_HISTORY.md` 或对应 review/result 文档，不长期留在未来计划中。
- V1.1 任务应优先保持小而可验收：明确目标、涉及入口、测试/验证命令、回滚方式。

## 规划层级

`FUTURE_WORK_PLAN.md` 不是具体实施方案，而是路线图和优先级判断。它回答：

- 哪些方向值得继续做；
- 为什么做；
- 大致优先级如何；
- 做到什么程度可以进入下一阶段实施。

具体任务实施方案应单独成文，通常放在 `docs/superpowers/plans/`，例如 `2026-xx-xx-v1.1-*.md`。实施方案应回答：

- 本阶段的明确目标和非目标；
- 涉及哪些模块、接口、文档和数据迁移；
- 如何分工给 agent/subagent；
- 每一步的测试要求和验收口径；
- 至少两轮复核方式；
- 完成后哪些内容要迁移到 `docs/PROJECT_HISTORY.md` 或 review/result 文档。

因此，合理结构是：

- `FUTURE_WORK_PLAN.md`：长期方向 + V1.1/V1.2 优先级。
- `docs/superpowers/plans/*.md`：某一阶段的可执行实施方案。
- `docs/superpowers/reviews/*.md`：阶段完成后的审核、整改和验收结果。
- `docs/PROJECT_HISTORY.md`：已完成阶段的汇总入口。

## 当前近期重点

V1.1 前端端到端主流程已经完成并迁移到历史记录。后续路线图不再把“前端发现/投递 -> 入库 -> 解析 -> 元数据抽取 -> 分类抽取 -> 审核”作为待办项维护；相关证据见：

- `docs/superpowers/plans/2026-06-30-v1.1-frontend-end-to-end-flow.md`
- `docs/superpowers/reviews/2026-06-30-v1.1-frontend-end-to-end-flow-result.md`
- `docs/PROJECT_HISTORY.md`

当前新的高优先级缺口是：用户在主题页填写主题/检索词之后，系统仍缺少受约束的广泛发现与检索方案能力，尤其无法自然覆盖模型卡、系统卡、机构技术报告、官网报告页等没有 arXiv ID 或弱引用关系的材料。

## 长期维护型知识资产

这些内容可以独立于系统功能长期存在，并会随着阅读、抽取和领域理解持续演化。它们不应被当作一次性开发任务处理。

### A. 元数据抽取模板

定位：长期维护的抽取规范，用于定义模型从 `content.md` / PDF 证据中抽取哪些字段、如何判断置信度、如何记录证据、哪些字段允许自动回填。

为什么需要长期维护：

- 文献类型越多，元数据字段和边界情况越多。
- 不同来源 PDF 的结构差异会暴露新的抽取失败模式。
- 审核中积累的人工修正应反哺模板，而不是只停留在单条记录。

后续方向：

- 建立元数据抽取模板版本号。
- 将字段定义、证据要求、风险规则、回填语义写成可审查文档。
- 从 MetadataReview 的 rejected / needs_fix / supersede 案例中定期提炼模板改进项。
- 将模板变更与抽取脚本、测试 fixture 和审核界面同步。

优先级：高。它直接影响后续所有文献的结构化质量。

### B. 文献分类规范与审核模板

定位：固定研究领域内的分类本体、标签规范、审核准则和争议处理规则。

为什么需要长期维护：

- 当前项目不是通用文献库，而是服务于特定博士研究领域。
- 领域边界、方法标签、风险域、阅读优先级会随着研究推进逐步稳定。
- 分类审核不只是 UI 功能，更是研究方法的一部分。

后续方向：

- 将分类标签、标量字段、多值标签的定义与例子写成规范。
- 为容易混淆的标签建立判别规则和反例。
- 从 ClassificationReview 的高模糊度、人工改动和 rejected 案例中定期更新规范。
- 分类规范变更需要同步 `classification_vocab.py`、`labels.js`、测试和审核说明。

优先级：高。它决定文献库能否形成稳定、可复用的领域地图。

### C. 采集与检索模板

定位：指导 collector 如何从主题、关键词、机构、作者、仓库和种子文献出发，持续发现候选文献。

当前状态：

- 采集目前主要复用分类/主题体系进行候选发现和闸门判断。
- V1 更重视人工闸门、小批量验证和去重安全，而不是大规模自动抓取。
- 当前按主题采集主要读取 `query_def.explicit_ids` / `seed_paper_ids`，不把主题名直接当作开放搜索词，因此对模型卡、系统卡、机构技术报告、官网报告页、弱引用关系材料覆盖不足。

后续方向：

- 将用户填写的主题名、描述、轴归属和种子材料转换为可审核的检索词与检索方案；主题既是用户输入入口，也是后端/agent 起草检索计划的上下文。
- 增加按机构、作者、关键词、主题词、项目/仓库线索、模型/系统卡名称、官方发布页、技术报告标题的检索策略。
- 检索来源不应只依赖固定 URL allowlist。第一版应同时覆盖：
  - 通用 Web 搜索，用于发现未知官网、发布页、PDF、模型卡和系统卡；
  - 官方/机构域名搜索，用于提高可信度和降低噪声；
  - GitHub / Hugging Face / OpenAlex / Crossref / Semantic Scholar 等结构化来源，用于能结构化查询的场景；
  - 用户显式给定 URL / DOI / arXiv / GitHub / 官网入口，用于可控补充。
- 设计上应支持两种执行方式：后端 Python/CLI 读取主题并生成检索任务；或由 agent 调用 web-access 等检索能力，形成候选结果后再写回系统。
- 在自动执行前，可先引入“检索方案起草”步骤：由 agent 或本地模型根据主题生成 query、目标来源、URL/domain 线索、排除词、候选上限和判断准则，用户确认后再跑。
- 建立“广泛发现 -> 轻闸门 -> 重闸门 -> intake 审核 -> ingest”的可解释流程。
- 将低质量来源、重复来源、坏 PDF、需要好副本等反馈写回采集策略。

优先级：高。它直接决定普通用户能否从“填写主题/检索词”走到真实候选，尤其补足模型卡、系统卡、技术报告等不适合 arXiv ID 或引用图发现的材料。实施方案需要单独打磨，不应草率做成无限制关键词抓取。

## V1.1 优先队列

### 1. 受约束广泛发现与检索方案 V1.1

这是当前采集链路最需要补齐的能力之一：用户在 TopicsReview 里填写主题/检索词后，系统应能帮助形成可执行、可审核的检索方案，并把发现结果送回候选池，而不是要求用户必须先知道 arXiv ID 或种子文献。

具体实施方案见：`docs/superpowers/plans/2026-06-30-v1.1-constrained-discovery.md`。

目标：

- 扩展主题采集的设计：主题名、描述、axis_hint、人工补充关键词都可作为检索方案输入，但不能直接变成无限制全网抓取。
- 支持固定字段检索入口：按已知名称、标题、URL、DOI、arXiv ID 等字段查找目标材料；名称/标题检索不应被迫包装成主题检索。
- 设计“检索方案起草 -> 用户确认/调整 -> 执行检索 -> 结果回填候选 -> intake 审核”的流程。
- 支持 agent/CLI 两种执行路径：后端 Python 可按主题读取配置并触发检索；agent 可调用 web-access 等能力检索网页，再把结构化结果写回系统。
- 覆盖非论文或弱引用材料：模型卡、系统卡、机构技术报告、官网报告页、GitHub/Hugging Face 项目材料、没有 arXiv ID 的 PDF/HTML 报告。
- 检索方案必须包含 query、目标来源/域名线索、通用搜索策略、排除词、候选上限、可信度理由、去重 key 和是否允许进入 intake 的判断准则。
- 检索结果必须保留来源 URL、命中 query、title/snippet、发现理由、来源类型和原始证据；默认只进候选，不自动 promote。

验证：

- 用一个模型卡/系统卡主题和一个机构技术报告主题跑小样本，证明不依赖 arXiv ID 也能产生可审核候选。
- 候选为空、噪声过高、来源不可信、重复命中时有明确反馈。
- 搜索结果不会直接污染 `works`；仍经 intake 审核和现有去重闸门。
- 实施方案需包含至少两轮 review：一轮查搜索漂移/来源污染，一轮查数据落点/回归风险。

### 2. 元数据抽取模板 V1.1

先把元数据抽取模板作为独立维护资产固化下来，避免抽取经验只散落在脚本、prompt 和审核结果里。

目标：

- 梳理当前 metadata 字段、证据要求、风险分级、回填语义。
- 定义模板版本号和变更记录方式。
- 建立从 MetadataReview 人工修正反哺模板的流程。
- 增加最小 fixture，覆盖常见文献类型和已知失败模式。

验证：

- 模板文档、脚本参数、测试 fixture、审核页面说明一致。
- 新增或更新测试能证明旧失败模式被覆盖。

### 3. 分类规范与审核模板 V1.1

把分类本体从“代码中的词表”提升为“可维护的领域规范”。

目标：

- 明确标量字段和多值标签的定义、例子、反例。
- 梳理高模糊度分类案例，沉淀判别规则。
- 建立分类规范变更流程：文档 -> vocab -> labels -> 测试 -> 审核页面。
- 明确人工审核时“保存草稿”“批准”“拒绝”“隔离”的语义。

验证：

- `classification_vocab.py`、`labels.js` 和规范文档一致。
- 高模糊度案例可在测试或审核样例中复现。

### 4. 分类标签事务式保存

当前 WorkDetail 多值分类标签保存仍是前端按 diff 执行 delete-then-add。若中途失败，可能留下部分写入状态。

目标：

- 新增后端批量/事务式标签保存端点。
- 前端 WorkDetail 改为一次提交完整多值标签变更。
- 失败时不产生部分状态，或返回可恢复的明确错误。

验证：

- 增加后端事务测试。
- 覆盖非法 tag、部分失败、空列表、重复 tag 等边界。

### 5. Parse status 多源语义

`GET /api/parse/status?work_id=` 对多源 work 的语义需要明确：返回 source 级列表，还是返回聚合状态。

目标：

- 定义多源 work 的状态聚合规则。
- 如保留单条返回，文档必须说明选择规则。
- 如返回列表，前端 WorkDetail 需要展示每个 source 的状态。

验证：

- 使用 fixture DB 覆盖单源、多源、active+archived 混合场景。

### 6. Dashboard 队列压力面板

Dashboard 目前更像导航入口，尚未成为治理控制台。

目标：

- 展示 metadata、classification、intake、inbox、duplicates 的待办数量。
- 明确区分“阻断项”“建议处理”“历史信息”。
- 每个数字能跳转到对应筛选页面。

验证：

- 前端构建通过。
- API summary 数据有 fixture 测试或页面 smoke。

### 7. 审核日志语义统一

metadata review 倾向提交 diff，classification review 倾向提交完整表单。两者审计语义不完全一致。

目标：

- 明确审核记录保存的是“完整确认状态”还是“人工修改字段”。
- metadata 与 classification 审核备注、review_source、reviewed_at、applied 语义一致。
- 文档更新到 `TECHNICAL_OVERVIEW.md` 或子项目架构文档。

验证：

- 覆盖 approve、needs_fix、reject、draft、batch approve 的审计字段。

### 8. `needs_better_copy` 替换源文件链路

V1 中 `needs_better_copy` promote 已被安全拒绝，避免误创建重复 work。V1.1 可考虑接入真正替换链路。

目标：

- promote 识别 `needs_better_copy` 后替换隔离 work 的坏源文件，而不是创建新 work。
- `replace_quarantined_source` 必须创建新的 `literature_parse_runs(status='pending')`。
- 替换后 work、source_files、work_codes、parse_runs、healthcheck 状态一致。

验证：

- 覆盖好副本替换、缺失 PDF、重复 sha、parse run 创建、healthcheck 零问题。

### 9. 文档治理自动化

当前已经有 `docs/DOCUMENT_GOVERNANCE.md` 和 `docs/superpowers/README.md`，但文档门禁仍靠人工 grep。

目标：

- 增加一个轻量文档检查脚本或测试。
- 检查 active 文档中是否出现禁止性旧入口：`parse_ledger.json` 当前状态源、默认 `D:\06_tools\document-parser`、当前 healthcheck 指向旧脚本、root-level `scripts/_*.py`。
- 输出允许命中与需处理命中的分类。

验证：

- 脚本在当前仓库运行通过。
- 后续 CI 或发布前 runbook 可直接调用。

### 10. 引用导出与综述矩阵

引用导出和综述矩阵仍是研究工作流的重要缺口。

目标：

- 支持 BibTeX/RIS 导出。
- 定义综述矩阵导出的字段来源和筛选条件。
- 与 `analysis_runs`、分类标签、metadata 审核状态对齐。

验证：

- 使用 fixture 数据生成稳定导出。
- 覆盖缺失 DOI、arXiv、中文标题、多作者等边界。

## 暂不进入 V1.1 的候选项

- 完整前端上传并创建 work 的能力：当前 `_inbox` + `/inbox` 已满足 V1 使用。
- 移动端完整适配：当前项目主要是本地桌面研究工具。
- 自动化大规模采集调度：collector 仍应以人工闸门和小批量验证为优先。
- 无约束大规模自动检索和自动入库：受约束广泛发现可进入 V1.1 方案设计，但不能跳过检索方案确认、候选审核和去重闸门。
