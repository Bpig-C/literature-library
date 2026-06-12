# 文献梳理方法论：三层阅读模板与 AnalysisRun 设计

> 日期：2026-06-12
> 状态：设计稿（仅设计，未实现）
> 对应计划：`FUTURE_WORK_PLAN.md` P1.1 分析运行 / P1.2 综述矩阵
> 前置条件：分类系统 Phase 1-3 已完成；138 works 全部有 MinerU `content.md`；metadata/classification 审核闭环可用

---

## 1. 背景与问题

当前文献库已完成采集、解析、元数据抽取与审核、分类标签三个阶段。下一阶段的核心痛点：

1. **阅读分散**：每次看一篇文献的重心都不一样，导致同一篇文献被反复从头读起，没有积累。
2. **审核耗时**：每天审核分类结果时，需要先花时间弄清"这篇在讲什么"，缺少稳定的速览入口。
3. **方向不明**：研究方向（自主性安全）仍在探索中，逐篇深读 138 篇无法回答"下一步往哪走"；需要跨文献的横向综合。

本设计把这三个问题统一为一个机制：**带版本的阅读模板（angle template）+ 可重复的分析运行（AnalysisRun）+ 跨篇综合（synthesis）**。

设计讨论中确认的约束与偏好：

- 三层并重，一次定架构，分步实施。
- 执行层走 opencode / mimocode 等低成本 agent CLI，**模板必须 executor 无关**；本项目只负责模板定义、任务清单、校验和落库。
- 第一批角度来自用户反复提的四类问题：风险定义与分类、评测方法设计、论证结构与结论、风险呈现方式（评级/证据链）。完整的治理角度推迟到有初版解决方案后再立模板。
- 模板生长采用"问题日志驱动"：新角度从重复出现的真实问题中长出来，不拍脑袋新增。

## 2. 设计目标与原则

**目标**

- G1：每篇文献只被"从头读"一次（digest 层），之后所有阅读都是带着明确问题的定向抽取。
- G2：同一个问题（角度）在文献子集上的答案结构一致、可横向比较，直接喂给 P1.2 综述矩阵。
- G3：角度积累到一定覆盖率后，能产出回答"方向在哪"的综合报告（分歧点、空白点、趋势）。
- G4：模板可版本化、可重跑、可审计；换执行工具不需要改架构。

**原则（沿用项目既有约束）**

- 文本入口唯一：所有抽取以 `literature_parse_runs.content_md_path` 指向的 Markdown 为输入，不硬编码 `parsed/content.md` 路径，不直接读 PDF。
- 候选与稳定分离：模型输出先进入运行记录层（`analysis_runs`），审核/抽检后才被矩阵和综合层默认采信。
- 不删除、只 supersede：模板升版重跑时旧结果保留，写 `superseded_by` 链。
- 隔离排除：`read_status='quarantined'` 的 work 不进入任何分析任务清单和综合输入。
- YAGNI：同时活跃的角度模板不超过 5 个；新角度必须由问题日志中的重复问题晋升而来。

## 3. 总体架构：三层一机制

三层不是三套系统，而是同一机制（模板 → 运行 → 审核 → 聚合）的三个实例，靠 `kind` 字段区分：

| 层 | kind | 输入 | 频次 | 产出 | 服务于 |
|---|---|---|---|---|---|
| L1 速览层 | `digest` | 单篇 content.md | 每篇一次，全量 138 | 速览卡片 JSON | 审核提效、子集筛选 |
| L2 角度层 | `angle` | 单篇 content.md | 按角度 × 子集，可随版本重跑 | 结构化角度 JSON | 定向阅读、综述矩阵 |
| L3 综合层 | `synthesis` | 某角度下多篇的 L2 JSON | 角度覆盖率达标后按需跑 | 横向综合报告 | 找方向、综述写作 |

数据流：

```
content.md ──(digest模板)──> digest run ──> ClassificationReview 速览卡片
content.md ──(angle模板×selector)──> angle runs ──┬──> P1.2 综述矩阵
                                                  └──(synthesis模板)──> 综合报告 ──> 方向决策 / 问题日志 ──> 新角度模板
```

闭环的关键在最后一段：综合报告暴露的新问题进入问题日志，重复出现的问题晋升为新角度模板，驱动下一轮定向抽取。

## 4. 模板系统

### 4.1 存放与格式

模板存放在仓库内 `templates/angles/`，一个角度一个 Markdown 文件，文件名 `{angle}@v{N}.md`。模板是**纯文本资产**，任何 agent（opencode/mimocode/Claude/本地脚本）都能读取执行；不依赖任何特定工具的 skill 机制。如果某个执行工具支持 skill 封装，可以另做一层薄 wrapper 指向同一模板文件，但模板本体只此一份。

模板文件结构（YAML frontmatter + 正文 + 内嵌 JSON Schema）：

```markdown
---
angle: risk-definition          # 角度名，全库唯一
version: 1                      # 整数版本，改动问题清单或 schema 必须升版
kind: angle                     # digest / angle / synthesis
selector:                       # 适用文献子集（用既有分类标签表达；digest 为全库）
  tag_groups:
    risk_domain: [scheming, sandbagging, deception, evaluation_awareness, oversight_subversion, autonomy]
  exclude_read_status: [quarantined]
input: full                     # full = 整个 content.md；head:12000 = 前 12000 字符
language: zh                    # 输出语言
---

## 目的
（一段话说明这个角度回答什么问题、结果将用于什么）

## 问题清单
（编号的问题列表，是模板的核心；每个问题对应 schema 中的一个字段）

## 输出要求
- 只输出一个 JSON 对象，符合下方 Schema，不输出解释性正文。
- 每个实质性回答必须附 evidence：原文片段（≤300字）+ 大致位置（章节名或前/中/后部）。
- 文中未涉及的问题，对应字段置 null 并在 not_addressed_fields 中列出；禁止臆测。
- 整体置信度 confidence: high/medium/low；low 时在 confidence_note 说明原因。

## 输出 Schema
```json
{ ... }
```
```

### 4.2 公共输出信封

所有角度模板的 JSON 输出共享一个信封结构，保证矩阵和综合层能统一处理：

```json
{
  "angle": "risk-definition",
  "template_version": 1,
  "work_id": "W-arxiv-xxxx",
  "not_addressed": false,
  "not_addressed_fields": [],
  "confidence": "high",
  "confidence_note": "",
  "fields": { },
  "evidence": { "<field>": {"quote": "", "location": ""} },
  "open_questions": []
}
```

- `not_addressed=true` 表示该文献对这个角度整体无话可说（合法结果，综合层据此统计角度覆盖盲区）。
- `open_questions` 是模板生长机制的输入：执行 agent 在抽取中发现的、问题清单没覆盖但值得问的问题，统一汇入问题日志（见 §8）。

### 4.3 第一批模板清单

| 模板 | kind | 适用子集（selector 草案） | 优先级 |
|---|---|---|---|
| `digest@v1` | digest | 全库（排除 quarantined） | 最先 |
| `risk-definition@v1` | angle | risk_domain 含自主性相关标签 | 第一个试点 |
| `eval-method@v1` | angle | reading_lane=evaluation_method 或 method_tags 含评测类 | 第二 |
| `risk-presentation@v1` | angle | artifact_focus 含 system_card/safety_case/risk_update/transparency_report 等 | 第三 |
| `argument-structure@v1` | angle | 按需手选子集（核心文献 P0/P1） | 第四 |
| `synthesis-{angle}@v1` | synthesis | 对应 angle 的全部已完成 runs | 角度覆盖≥80% 后 |

各模板问题清单草案（实施时细化为正式问题+schema）：

**digest@v1**（速览卡片，固定不重跑，除非解析产物变化）

1. 一句话定位：这是一篇什么文献、解决什么问题（中文，≤50字）。
2. TL;DR：3-5 条要点（中文）。
3. 文献角色：提出框架 / 报告评测结果 / 披露系统信息 / 综述 / 立场论证 / 其他。
4. 核心产出物：框架名 / benchmark 名 / 模型名 / 标准名等具体指称。
5. 与自主性安全的相关度：high/medium/low + 一句话理由。
6. 建议阅读优先级与理由（供人参考，不自动写入 works.priority）。

**risk-definition@v1**（风险定义与分类）

1. 本文显式定义了哪些风险概念？每个概念：名称、定义原文、出处位置。
2. 定义方式是行为式（observable behavior）还是机制式（internal mechanism / 倾向）？
3. 是否提出或采用 taxonomy？结构如何（层级/维度/清单）？
4. 各概念与本库 `risk_domain` 词表的映射（用于横向对齐）。
5. 概念的操作化程度：是否给出可测判据？判据是什么？
6. 作者承认的定义边界/模糊地带。

**eval-method@v1**（评测方法设计）

1. 评测对象：能力（capability）/ 倾向（propensity）/ 部署行为，针对哪些风险。
2. 方法类型（映射 `method_tags`）：benchmark / red teaming / white-box probing / agentic sandbox / 多模型对比等。
3. 任务如何构造？数据来源、规模、是否公开。
4. 指标与判定方式（自动判分 / 人工 / LLM judge）。
5. elicitation 策略：是否考虑 sandbagging / evaluation awareness？怎么处理？
6. 效度威胁与局限：作者自述的 + 文中可见但作者未述的。
7. 主要结果一句话 + 结果对"风险是否可测"的含义。

**risk-presentation@v1**（风险如何被呈现：评级与证据链）

1. 风险被表达成什么形式：等级（如 ASL/危险能力级别）/ 分数 / 定性描述 / 阈值触发？
2. 等级体系的结构：几级、每级语义、升级条件。
3. 从评测结果到风险结论的证据链：claim → evidence → assessment 的链条怎么搭的？
4. 用什么 artifact 承载：system card / safety case / risk update / transparency report？
5. 不确定性如何表达（置信区间、保守假设、"无法排除"措辞等）。
6. 该呈现方式的可比性：跨模型/跨版本/跨机构能不能比？

**argument-structure@v1**（论证结构与结论）

1. 核心主张清单（≤5 条），每条标注：实验结论 / 案例归纳 / 理论推演 / 立场主张。
2. 每条主张的证据强度与关键假设。
3. 作者自认的局限与未决问题（future work）。
4. 该文与本库其他工作的显式对话关系（支持/反驳/扩展了谁）。
5. 对"自主性风险如何被发现和呈现"这一候选方向的连接点。

**synthesis-{angle}@v1**（综合层，每个 angle 一个变体，结构相同）

输入：该 angle 下全部已完成（且未被拒绝）的 L2 JSON。输出：

1. 共识：哪些回答跨文献高度一致。
2. 分歧：同一问题的对立回答，各自代表文献。
3. 空白：`not_addressed` 高频字段、词表中无人覆盖的 risk_domain、无人测的风险。
4. 趋势：按年份的方法/定义演化。
5. 建议深读清单（≤10 篇）+ 理由。
6. 候选研究方向（≤3 个），每个附支撑证据与反对理由。

### 4.4 版本与重跑规则

- 改动问题清单、schema 或输出要求 → `version+1`，新建文件，旧文件保留。
- 升版后由任务清单机制找出"该模板适用但只有旧版本结果"的 work，重跑并将旧 run 标记 `superseded_by`。
- selector 调整不算升版（只影响任务清单，不影响已有结果语义）。
- digest 原则上不升版重跑，除非 content.md 本身被替换（重新解析）。

## 5. 数据落点

### 5.1 新表 `analysis_runs`

沿用 `metadata_extractions` / `classification_extractions` 的既有范式（id 前缀 + extracted_json + review 字段 + supersede 链），迁移脚本命名沿用 `scripts/migrate_add_analysis_runs.py`：

```sql
CREATE TABLE analysis_runs (
  id TEXT PRIMARY KEY,              -- 'AR-' + uuid4().hex[:12]
  kind TEXT NOT NULL,               -- digest / angle / synthesis
  angle TEXT NOT NULL,              -- 角度名，如 risk-definition
  template_version INTEGER NOT NULL,
  work_id TEXT,                     -- L1/L2 必填；L3 为 NULL
  input_work_ids TEXT,              -- L3 输入集合（JSON 数组）；L1/L2 为 NULL
  selector_snapshot TEXT,           -- 运行时 selector 的快照（JSON），保证可追溯
  executor TEXT,                    -- claude / opencode / mimocode / ollama / human
  model_name TEXT,
  input_scope TEXT,                 -- full / head:12000
  input_chars INTEGER,
  extracted_json TEXT NOT NULL,     -- 公共信封 JSON
  confidence TEXT,                  -- 信封中的整体置信度，冗余出来便于筛选
  not_addressed INTEGER DEFAULT 0,
  review_status TEXT DEFAULT 'pending',  -- pending / approved / needs_fix / rejected（沿用既有词表）
  review_note TEXT,
  reviewed_at TEXT,
  review_source TEXT,               -- human / agent / batch
  superseded_by TEXT,
  md_path TEXT,                     -- 双写的 Markdown 文件相对路径
  raw_response TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX idx_analysis_runs_work ON analysis_runs(work_id);
CREATE INDEX idx_analysis_runs_angle ON analysis_runs(angle, template_version);
CREATE INDEX idx_analysis_runs_status ON analysis_runs(review_status);
```

与既有审核语义的差异（有意为之）：

- metadata/classification 的审核是**回填门禁**（approved 才能写 works）；analysis_runs 的审核是**采信标记**——run 本身就是产品，没有"应用到 works"动作，因此无 `applied` 字段。
- 默认 `pending` 不阻塞使用：矩阵和综合层默认纳入 pending+approved，排除 rejected，并在输出中标注未审核比例。审核采用抽检制（见 §7）。

### 5.2 文件双写

- L1/L2：`works/{work_id}/analyses/{date}_{angle}@v{N}.md`（目录已存在）。Markdown 由脚本从 JSON 渲染生成，供人直接翻阅；JSON 为机器层真相，Markdown 是视图。
- L3：`views/synthesis/{date}_{angle}@v{N}.md` + 同名 `.json`。`views/` 沿用"生成产物、不人工维护"的既有约定。
- 与既有约束一致：文件移动/重命名必须同步 `analysis_runs.md_path`。

### 5.3 不新增的东西

- 不建 `collections` 表（属于 P2，本设计用既有分类标签做 selector，足够）。
- 不动 `works` 表（本设计不回填任何字段到稳定层）。
- 不做 L2 结果的字段级编辑界面（第一版用 needs_fix + 重跑代替，见 §7）。

## 6. 执行流程（executor 无关）

### 6.1 职责划分

本项目（仓库内脚本）只负责三件事，全部确定性、可测试：

1. **任务清单生成**：`scripts/literature_analyze.py --plan --angle risk-definition` 按模板 selector 查询符合条件且无当前版本结果的 work，输出任务清单 JSON（work_id、content_md_path、模板路径、输出落点）。
2. **校验与落库**：`--submit <json文件或目录>` 校验信封结构 + 模板 schema + evidence 非空规则，通过则写 `analysis_runs` 并渲染 Markdown 双写；不通过则拒绝并输出原因（供 agent 重试）。
3. **状态查询**：`--status` 输出各角度覆盖率（已跑/适用总数）、版本分布、待重跑清单。

执行 agent（opencode/mimocode/Claude/人）负责中间一步：读任务清单 → 读模板 + content.md → 产出 JSON 到约定目录 `_analysis_outbox/{angle}/{work_id}.json` → 调 `--submit`。约定目录机制让任何工具（包括手工）都能接入，失败可重试，submit 幂等（同 work+angle+version 已有未 superseded 结果时拒绝重复提交，除非 `--force`）。

### 6.2 输入策略

- digest：`head:12000` 字符起步（标题、摘要、引言、结论通常已覆盖；4b 级别模型也能胜任）。若试跑发现结论章节常被截断，再调整为"头部 + 尾部"拼接策略并升版。
- angle：默认 `full`。content.md 超长（>100k 字符）时按模板 frontmatter 的 `input` 字段允许声明分段策略；第一版先不做自动分段，超长文献进入人工处理清单。
- synthesis：输入是 L2 的 JSON 而非原文，体积可控；按 angle 全量拼接。

### 6.3 幂等、重跑与 supersede

- 唯一性约束（逻辑层）：每个 (work_id, angle, template_version) 至多一条未 superseded 的 run。
- 重跑入口统一为：模板升版（批量）、审核标记 needs_fix（单篇）、content.md 变更（单篇）。
- 重跑生成新 run，旧 run 写 `superseded_by`，与 metadata_rerun 的既有模式一致。

## 7. 审核机制

分层分强度，避免重蹈"每条都人工看"的审核负担：

| 层 | 审核策略 | 理由 |
|---|---|---|
| digest | **不设审核流程**。在 ClassificationReview 使用速览卡片时发现错误，一键标 needs_fix 即可触发重跑 | 低风险、仅作参考，错误成本低 |
| angle | **抽检制**：每个角度每批次抽 20%（参照 P1.0d 的抽样思路）；抽检不合格率 >20% 时判定模板问题，修模板升版重跑整批，而不是逐条修结果 | 错误大多是系统性的（模板/模型问题），逐条修是浪费 |
| synthesis | **逐份人工审**：产量低（每角度一份），且直接影响方向决策 | 高影响、低数量 |

抽检的核查重点（写入模板的审查清单，类似 MetadataReview 侧边栏清单）：

- evidence 的 quote 是否真实存在于 content.md（可脚本预检：quote 子串匹配，失配自动标 high risk）。
- `not_addressed` 是否被滥用（明明文中有却说没有）或漏用（臆测填答）。
- 字段与词表映射是否合理（如 risk_domain 映射）。

第一版审核入口走 CLI + 生成的 Markdown 文件（人直接看 `works/{id}/analyses/*.md`，用 `scripts/literature_analyze.py --review <run_id> --mark approved/needs_fix` 写回）；专门的 AnalysisReview 前端页面**推迟**到抽检流程跑通、确认有真实需要后再立项。

## 8. 问题日志与模板生长

`docs/reading_questions.md`，append-only，每条记录：日期、问题、触发文献（work_id）、来源（人工审核中想到 / agent 的 open_questions 汇总）。

晋升规则：

- 同一问题（语义上）出现 ≥3 次 → 候选新角度；先在 5 篇上手工试问，确认答案结构稳定后正式写模板。
- 活跃角度已达 5 个时，新角度晋升必须伴随一个旧角度归档（标记 retired，不再生成新任务，已有结果保留）。
- 每次 synthesis 报告产出后，固定做一次问题日志回顾（报告中的"空白"与"候选方向"天然产生新问题）。

这是整个方法论的自我修正机制：**模板不是预先设计完美的，而是被真实阅读需求迭代出来的。**

## 9. 与现有系统集成

### 9.1 API（最小集，沿用 FastAPI 既有模式）

- `GET /api/works/{work_id}/analyses` — 该 work 的全部 runs（默认排除 superseded）。
- `GET /api/analyses?angle=&kind=&review_status=&template_version=` — 列表查询，供前端与矩阵使用。
- `PATCH /api/analyses/{run_id}/review` — 标记 approved / needs_fix / rejected（语义同 §7）。
- `GET /api/matrix?angle=&fields=&sort=year` — P1.2 矩阵：按 angle 拉取 runs，把信封 `fields` 中指定字段拼成行=work、列=字段的表，输出 JSON（前端渲染）与 Markdown/CSV（导出）。

写入（submit）第一版只走 CLI 脚本，不开 POST 端点，减小 API 面；agent 在本机执行，没有远程提交需求。

### 9.2 前端（最小改动）

- ClassificationReview / WorkDetail 详情区增加 digest 卡片（一句话定位 + TL;DR），数据来自 `GET /api/works/{id}/analyses?angle=digest`。这是 digest 层对"审核提效"目标的直接交付。
- WorkDetail 增加"分析"区块：列出该 work 的 angle runs，点击展开渲染后的 Markdown。
- Matrix 页面属于 P1.2，待 angle 层有真实数据后再做。

**模板管理是否需要前端：模板本体不需要，selector 预览需要。**

- **不做模板编辑器 UI**。模板是版本化的文本资产，由人与 agent 协作撰写、以 Markdown 审阅，比框选字段的表单更快且天然进 git；schema 的字段增删本质是设计行为，不适合 UI 化（YAGNI）。
- **做 selector 预览**，且不新建页面：复用 Works 页，补上 FUTURE_WORK_PLAN 中本就缺失的"标签多选过滤"（按 `work_classification_tags` 的 tag_group/tag_value 组合筛选，后端给 `GET /api/works` 增加标签筛选参数）。模板 frontmatter 的 selector 采用与该 API 相同的查询语义，于是"在 Works 页配好筛选 → 看到命中的具体文献列表 → 把同样的条件写进模板 selector"成为模板设计的标准工作流。CLI `--plan` 输出同一查询的任务清单，两者结果必然一致。
- 收益叠加：这个标签筛选同时服务日常检索和 P1.2 矩阵的子集选择，不是一次性投入。

### 9.3 与 metadata/classification 层的关系（依赖强度与修正回路）

**与 FUTURE_WORK_PLAN 的关系**：本设计替代并细化 P1.1（分析运行）与 P1.2（综述矩阵）。保留其全部骨架（`analysis_runs`、`works/{id}/analyses/` 双写、`literature_analyze.py`、矩阵导出）；新增三层结构、模板版本化、executor 无关提交约定与问题日志机制；收窄一处——`POST /api/works/{id}/analyses` 第一版不做，写入只走 CLI。

**依赖强度：弱依赖，只做路由不做输入。**

- 分析层的文本入口只有 content.md，不读取 metadata/classification 的抽取结果作为分析输入；分类标签错误不影响分析质量本身。
- classification 标签仅用于模板 selector 路由；metadata（年份、标题）仅用于矩阵排序与展示。
- 错误代价不对称：标签"多选进来"便宜（angle 运行返回 not_addressed 即可，顺带修正认知）；"漏选掉"才有成本，对策是 selector 宁宽勿严 + digest 全量卡片的相关度字段兜底（digest 不依赖分类标签）。

**修正回路：只有人工可以跨层写。**

- 精读/分析审核中发现前层错误，通过既有端点修正：classification 标签 CRUD、save-draft、metadata 字段级重抽与 supersede。
- 分析层 agent 永远不自动回写 classification/works，防止低成本模型污染已审核的稳定层；人工修正是唯一跨层写路径。

**分类审核策略：lazy verification。**

分类层是路由表而非研究产出，只需"大体对"。允许批量通过当前积压的分类审核，但批量通过的记录应在 `review_note` 写统一标记（如 `batch-approved-{date}`），使"批量信任"与"人工核实"在数据上可区分；后续精读（从阶段 B 的 10 篇试点开始）按需复核并修正相关记录。现有批量端点只覆盖 ambiguity_score < 20，中高模糊度记录的批量通过需补充带标记的批量入口（脚本或端点参数均可）。

### 9.4 Healthcheck 扩展

- `analysis_runs.md_path` 指向的文件存在且非空。
- 每个 (work_id, angle, template_version) 未 superseded 的 run 唯一。
- quarantined work 没有 pending 任务出现在任务清单中。
- evidence quote 失配率统计（作为模板质量信号）。

## 10. 实施路线（供后续排期，本文档不含实现）

| 阶段 | 内容 | 验证点 |
|---|---|---|
| 0 | 前置清障：① 修复模糊分数重算不一致（见 `docs/issues/2026-06-12-ambiguity-score-inconsistency.md`，含存量重算脚本）；② 带 `review_note` 标记的分类批量通过入口，清空可自动处理的审核积压（lazy verification，§9.3） | ✅ 已完成：重算后批量通过 112 条（tag=`batch-approved-2026-06-13`）；剩余 125 条 pending（106 条缺 evidence，19 条 quarantined）为边界保留项；"批量信任"与"人工核实"在数据上可区分 |
| A | 迁移脚本建表；`templates/angles/` 目录与 `digest@v1` 模板；`literature_analyze.py` 的 plan/submit/status 骨架 + 测试 | 10 篇 digest 试跑 → 人工看卡片质量 → 全量 138 |
| B | Works 页标签多选过滤 + `GET /api/works` 标签筛选参数（selector 预览，§9.2）；`risk-definition@v1` 模板；10 篇试点（选 risk_domain 强相关、你最熟的文献，便于校验质量）；抽检流程首次运行 | 在 Works 页能看到 selector 命中的文献列表；模板校准 1-2 轮后扩大到全子集 |
| C | digest 卡片接入 ClassificationReview；`GET /api/works/{id}/analyses` | 审核一篇文献的前置了解时间显著下降 |
| D | `synthesis-risk-definition@v1` 首份综合报告；问题日志机制启用 | 报告能列出明确的分歧点/空白点/候选方向 |
| E | 其余三个角度模板按需推进；`GET /api/matrix` 与导出（P1.2） | 能导出按年份排序的角度矩阵 |

阶段 B 的 10 篇试点是整个方法论的关键验证：如果"风险定义"角度在你最熟的 10 篇上抽出来的结果你认可，机制就成立；不认可，修的是模板而不是架构。

## 11. 风险与对策

| 风险 | 对策 |
|---|---|
| 低成本 agent 的抽取质量不稳定 | 信封强制 evidence + quote 子串预检；抽检制发现系统性问题修模板而非逐条修；质量要求高的角度（argument-structure）可指定更强 executor |
| 模板设计一次到位的幻觉 | 10 篇试点 + 版本化重跑是常态成本，schema 设计时即假设会升版 |
| 角度膨胀，重蹈分散覆辙 | 活跃角度 ≤5 硬上限 + 问题日志晋升制 |
| 综合报告被未审核的低质量 L2 结果污染 | 矩阵/综合默认排除 rejected 并标注未审核比例；synthesis 逐份人工审 |
| content.md 解析质量差的文献产出垃圾分析 | digest 阶段即可暴露（卡片明显不对 → 走既有 quarantine/重解析流程），等于给解析质量加了一道全量体检 |

## 12. 验收标准

- 全库（排除 quarantined）每篇有一张 digest 卡片，且在审核界面可见。
- 至少 1 个角度模板在 ≥30 篇上产出结构一致的 JSON，抽检合格率 ≥80%。
- 至少 1 份 synthesis 报告，其中列出 ≥3 个跨文献分歧点或空白点，且每条可回溯到具体 run 的 evidence。
- 模板升版重跑后，旧结果可通过 supersede 链追溯。
- 任务清单、submit 校验、覆盖率统计均可由 opencode/mimocode 等外部 agent 无人工介入地调用。
