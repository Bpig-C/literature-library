# collector 检索实施方案设计

> 日期：2026-06-27
> 状态：设计已讨论确认，待评审
> 上位 spec：`docs/superpowers/specs/2026-06-27-collector-integration-design.md`（集成设计，本 spec 解决其 §13 留下的检索层三个开放问题）
> 关联：`docs/methodology/classification-methodology.md`（库内分类本体，risk_domain/reading_lane 词表来源）
> 参考实现：`D:\03_projects\master\2025_to_2026\electronic_info_manufacturing_corpus\...\ei_corpus_loop_serial_qbatch_001a_hotfix_prompt_runner`（OpenCode executor loop 三层角色模式）

## 1. 背景与范围

集成设计 spec 已确立 collector 的整体架构（候选队列 `intake_candidates` + 两段式预去重闸门 + 四态判别 + A2 人工晋升 + arXiv/GitHub 适配器），但其 §13 留下三个**检索实施层**的开放问题未定：

1. 检索驱动方式（怎么"发现"要收集的文献）
2. GitHub 资产边界（代码仓库进不进 works）
3. 采集与闸门执行节奏（手动 vs 定时；collect/resolve 是否拆步）

本 spec 专门闭合这三个问题。**不重新讨论已定的集成地基**（候选队列、闸门、四态、A2、子模块边界），只在其上补齐"检索实施层"。

### 非目标（本 spec 不做）

- 不改集成 spec 已确认的边界（collector 不直接写 works、队列在库、四态判别、A2 第一版）。
- 不实现本体/词表更新 loop（记为 future work，§8）。
- 不做关键词订阅（b）、多跳引用图、定时 loop 的第一版实现（均记 future work）。

## 2. 关键决策总览

| 问题 | 决策 | 一句话 |
|---|---|---|
| 1 检索驱动 | **两层主题 + 成熟度阶梯 + (a)+(c) 发现** | 收集主题 ↔ 库内本体映射；苗头不进本体；(a) 显式 ID + (c) 引用图 1 跳发现 |
| 1 主题-本体边界 | **collector 绝不扩展词表** | 词表扩展走现有分类维护流程；collector 只记录意图+映射 |
| 1 提案闸门 | **4 判据 + agent 起草、人拍板** | 复用分类审核环；v1 可纯人工，agent 后接 |
| 2 GitHub 边界 | **v1 只收论文/报告 PDF；代码仓库 URL 塞 JSON** | 不建 work_assets 表（v1.1）；跨源去重靠强键 |
| 3 执行节奏 | **v1 手动 CLI；collect/resolve 默认拆两步** | loop 作很近的 v1.1；留 --auto-resolve 链式开关 |

## 3. 问题 1：检索驱动方式

### 3.1 两层主题模型

检索的组织单位是**研究主题**。经核查，库内"主题"已存在于分类本体中，**无需另起一套主题系统**：

- **库内主题（已有）**：分类规范 `docs/methodology/classification-methodology.md` 的可重叠标签字段，主要是 **`risk_domain`**（本体论，"研究哪类风险现象"，如 `reward_hacking`）和部分 **`reading_lane`**（"为什么读"）。这些是 `work_classification_tags` 的 `tag_value`，版本化、向后兼容追加。
- **收集主题（新增）**：collector 侧的"收集意图"，带可迭代的描述与检索查询定义。

两者通过**映射**关联：一个收集主题映射到 1 个或多个库内本体值。例：收集主题「奖励黑客」→ `risk_domain.reward_hacking`。

```
收集主题 (collector 侧)                       库内主题 (works 侧，已有)
─────────────────────────                     ──────────────────────────
collection_topics {                           work_classification_tags
  name: "目标错误泛化"                          tag_group: risk_domain
  description: ← 迭代打磨的研究重心描述          tag_value: reward_hacking ...
  query_def:   显式ID / 种子论文                ↑
  map_status:  seedling|proposed|mapped        │
  mapped_tags: ────────────────────────────────┘  (映射到现有词表值)
}
```

### 3.2 主题成熟度阶梯（苗头不进本体）

并非每个新主题都适合直接进入本体。收集主题有**成熟度阶梯**，由 `map_status` 表达：

| `map_status` | 含义 | 进本体正式流程？ |
|---|---|---|
| `seedling`（苗头） | 一个 hunch，"我老看到这类论文，X 是不是个东西？"——攒着、喂描述，**不提案** | ❌ |
| `proposed`（提案） | 攒够了，正式提议作为本体新成员，带理由与草拟定义 | ✅（走分类维护流程） |
| `mapped` | 对应到现有本体值 | — |

另设正交字段 `lifecycle`（`active` / `paused` / `retired`）表示"是否还在持续收集"，与 `map_status` 独立（一个 `mapped` 主题可以 `retired`：本体值仍在，只是不再主动收集）。

> 现实例子：`目标错误泛化`（goal misgeneralization）当前不在 risk_domain 词表（最接近的 `goal_preservation` 语义不同）。它先以 `seedling` 存在，靠引用图扩出候选；攒够证据后升 `proposed`；人审通过后在分类维护流程里给 risk_domain 追加 `goal_misgeneralization`（向后兼容、零迁移），主题翻 `mapped`。

### 3.3 边界：collector 绝不扩展词表（核心约束）

> collector 只负责**记录收集意图 + 映射关系**，**绝不自行扩展库的本体词表**。词表扩展走现有的分类维护流程。

理由：risk_domain 是库的**本体论知识资产**，扩展它是需要审慎的语义判断（如"目标错误泛化 vs reward_hacking 层级不同"）。让"脏快"的采集端动词表，会污染"干净可审核"的分类本体，违反集成 spec §3 的边界约束。`proposed` 状态只是**提议**，提案的落实发生在分类审核环节。

**`proposed` 的闭环**：收集主题标 `proposed` 后照样收集；候选晋升时，审核环节自然逼出"这个主题该不该成为本体新成员"的判断——要，则走分类维护流程追加词表值，主题 `map_status` 由 `proposed` 翻 `mapped`。**词表扩展是分类审核的产物，不是采集的产物。**

### 3.4 提案闸门：4 判据 + agent 起草、人拍板

`seedling` 升 `proposed`（值得提案）的判据，人和 agent 共用同一把尺子：

- **复现性**：攒到 ≥ N 篇（建议 3-5）独立文献落在其名下，证明非孤例。
- **不可折叠**：塞不进任何现有本体值，语义边界独立。
- **轴正确**：它是现象/本体（→ risk_domain），不是方法（→ method_tags）、不是阅读目的（→ reading_lane）。
- **边界可述**：能写清与邻近术语的区别。

**分工**：信息检索与辨析（现有 37 个 risk_domain 值里哪些相近、文献是否支持其独立性、有无复现）由 **agent 起草**；本体承诺（值不值得在共享词表永久占席、影响今后所有分类统计）由**人拍板**。这与候选晋升 A2、分类抽取审核（`classification_extractions`，source=ai → review_status=pending → 人审）完全同构。

> v1 可**先纯人工**（人手动把 seedling 标 proposed）；agent 起草能力（§7）跑顺后接入，作为按需调用的起草大脑。

### 3.5 发现机制：v1 = (a) 显式 ID + (c) 引用图 1 跳

往 `query_def` 塞什么的三种机制：

- **(a) 显式 ID/URL 列表**：已知要什么，collector 拉元数据+跑闸门。零发现，纯执行。**v1 开放。**
- **(b) 关键词+分类订阅**：按文献"说什么"匹配（关键词 / arXiv 分类 / RSS）。依赖已稳定词汇；seedling 主题没稳定词汇时抓瞎。**v1 不做**，留到主题 `mapped`、词表稳定后接。
- **(c) 引用图扩展**：按文献"和谁连着"匹配。从种子论文出发，遍历 Semantic Scholar / OpenAlex 已建好的引用关系（**无需自建图谱**）：
  - 向前扩（forward）：引用了种子的论文 → 跟进新工作。
  - 向后扩（backward）：种子引用的论文 → 根基/前置工作。
  - 来源：Semantic Scholar Graph API（`/paper/{id}/citations`、`/references`），免费、限流宽松。

**(c) 对词汇漂移免疫**，恰好弥补 seedling 主题没有稳定词汇的短板——只要给对种子，不依赖关键词就能把方向前沿捞回来。**v1 主力发现机制。**

**v1 切法：**
```
(a) 显式 ID 列表     ← 永远开放，零成本
(c) 引用图 1 跳      ← v1 发现主力：种子 → citing + cited（Semantic Scholar）
(b) 关键词订阅        ← v1 不做，留到 mapped 主题
多跳引用图            ← 明确不做（爆炸+噪声），验证 1 跳精度后再说
```

引用图扩出的边可顺势沉淀进现有 `work_relations` 表（发现机制顺带补全库的引用网）。

### 3.6 数据模型

新增 `collection_topics` 表（活在库 DB，与 `intake_candidates` 同源）：

| 字段 | 说明 |
|---|---|
| `id` | 主键，`CT-{hex}` |
| `name` | 主题名（如「目标错误泛化」） |
| `description` | 迭代打磨的研究重心描述（TEXT） |
| `query_def` | JSON：`{explicit_ids:[], seed_paper_ids:[], (keywords/categories 预留)}` |
| `map_status` | `seedling` / `proposed` / `mapped` |
| `lifecycle` | `active` / `paused` / `retired` |
| `mapped_tags` | JSON 数组：`[{group:'risk_domain', value:'reward_hacking'}, ...]`（mapped 时填） |
| `proposed_note` | 提案理由 + 草拟定义 + 邻近值辨析（proposed 时填；agent 起草产物落此） |
| `axis_hint` | 倾向的本体轴：`risk_domain` / `reading_lane`（辅助，不强制） |
| `created_at` / `updated_at` | 时间戳 |

`intake_candidates` 新增字段 `collection_topic_id`（FK → collection_topics，可空）。

**晋升衔接**：候选晋升时，其主题的 `mapped_tags` 作为**建议的 risk_domain/reading_lane 标签**带进新 work，走现有分类审核门禁——collector 不绕过质量门禁。

### 3.7 来源访问模型：纯 API，无动态渲染

v1 的三个来源**全部 API-first，不需要 web-access skill / CDP 动态浏览器渲染**。这是集成 spec §1"反爬深水区（登录态、JS 渲染重度站点）"非目标的具体落地，也使 collector v1 不同于参考项目 ei_corpus_loop（后者要处理 CDP/浏览器/付费库）。

| 来源 | 访问方式 | CDP？ |
|---|---|---|
| arXiv | arXiv API（元数据）+ 直链 PDF（带 User-Agent、保守并发） | 否 |
| GitHub | REST/GraphQL API（repo 元数据、README、releases）+ raw URL 取 PDF | 否 |
| Semantic Scholar | Graph API（`/paper/{id}/citations`、`/references`） | 否 |

**前提（auth，非渲染）**：GitHub API 未认证限 60 次/小时，采集规模下不够——需配 GitHub token（认证后 5000 次/小时），作为 collector 配置项。web-access skill 仅在将来加入"机构官网 / webpage_blog 类来源"（集成 spec 非目标）时才启用。

## 4. 问题 2：GitHub 资产边界

### 4.1 v1 只收论文/报告 PDF

纯代码仓库**不在分类规范的 `primary_doc_type` 词表内**（最接近的 `workflow_artifact` 是本地工作件，语义不对），天然不属于 `works`。

| 情形 | v1 处理 |
|---|---|
| GitHub 上的**论文/报告 PDF** | 是文献 → 走正常 intake → works（GitHub URL 作 source_url） |
| **纯代码仓库** | 不建 work；仓库 URL 记进候选 `raw_meta`，晋升后进 `works.ingest_meta` JSON |

### 4.2 关联资产塞哪 —— v1 塞 JSON，不建表

- ❌ `works.url`：作品自身主 URL，一个作品一个，塞不下独立仓库。
- ❌ `works.contributors`：语义是人/机构（规范 §4.5），塞仓库 URL 是语义污染。
- ✅ **v1：代码仓库 URL 进 `intake_candidates.raw_meta` / `works.ingest_meta` JSON**。零建表、零迁移。
- 🔜 `work_assets` 表**留到 v1.1**：当真需要"列出所有有开源代码的 work"这类查询时再建，届时把 JSON 里的仓库 URL 迁过去。

### 4.3 跨源去重对齐 —— 靠强键，不靠 SHA256

同一篇论文可能 arXiv + GitHub 各有一份。**关键认知：跨源的"同一篇"靠轻量闸门强键判，绝不能靠 SHA256**（不同主机 PDF 字节流通常不同，SHA256 必然不匹配）。

对齐链路：
1. **GitHub 适配器的核心活**：从仓库 README、repo metadata、论文首页抽取 **arXiv ID / DOI**（很多 repo README 就写了 arXiv 链接）。
2. 抽到的强键喂轻量闸门 → 命中已有 arXiv 来源 work → 判 `exact_hit`（跳过）或记为**同一 work 的第二个 `source_file`**（多源，复用现有 source_files）。
3. 若原 arXiv 副本被 quarantine → 走 `needs_better_copy`，GitHub 这份当好副本替换。
4. SHA256 重量闸门只判"同源精确重复"，跨源对齐不指望它。

> 跨源对齐 = 适配器抽取强键 + 现有闸门，**零新增去重逻辑**。

## 5. 问题 3：采集与闸门执行节奏

### 5.1 触发方式：v1 手动 CLI

v1 走**手动 CLI 触发**（`literature_intake.py collect ...`），匹配集成 spec §13.3。理由：最简、可控，引用图扩展本就增量，手动也能跑。

**诚实提醒**：定时 loop 不是"远期"而是"很近的 v1.1"。collector 的 collect/resolve 天然映射 loop 的 action 模型，复用 §7 的 ei_corpus_loop 骨架几乎现成。待手动流程跑顺、A2 审核节奏稳定后即可上。

### 5.2 collect / resolve 默认拆两步

下载耗带宽，应先看判别再决定下不下载：

```
collect  （只元数据，不下载）→ 看 resolution: new / exact_hit / title_candidate / needs_better_copy
   ↓ 人扫一眼判别结果
resolve  （只对要的候选下载 + SHA256 重量闸门）
```

- `collect` 便宜，可宽跑（多主题、多种子一起），先拿四态分布。
- `resolve` 只对真想要的跑：`new`（要晋升）+ `needs_better_copy`（要拉好副本替换）。`exact_hit`/`sha256_duplicate` 无需下载。
- 留 `--auto-resolve` 开关链式跑，**默认拆开**。
- 拆分天然映射 loop 的 `COLLECT` / `RESOLVE` 两个 action，将来接 loop 零摩擦。

> 集成 spec §10 已把 `collect` 和 `resolve` 写成两条命令；本 spec 确认拆分 + 明确"默认分步、可选链式"。

## 6. CLI 规划（在集成 spec §10 基础上补充）

```powershell
# 主题管理
python scripts/literature_intake.py topic add --name "目标错误泛化" --map-status seedling \
    --seeds <seed_arxiv_id_1>,<seed_arxiv_id_2> --description "..."
python scripts/literature_intake.py topic list --map-status seedling
python scripts/literature_intake.py topic propose CT-aaa   # seedling→proposed，(v1.1 可触发 agent 起草)

# 采集：对主题跑 (a)+(c) 发现 + 轻量闸门，不下载
python scripts/literature_intake.py collect --topic CT-aaa
python scripts/literature_intake.py collect --source arxiv --ids 2501.17805   # (a) 显式

# 闸门：对要的候选下载 + SHA256（默认只 resolve new / needs_better_copy）
python scripts/literature_intake.py resolve --topic CT-aaa
python scripts/literature_intake.py resolve --topic CT-aaa --auto-resolve      # 链式

# A2 晋升（集成 spec 已有）
python scripts/literature_intake.py list --resolution new --review-status pending
python scripts/literature_intake.py promote --ids IC-aaa,IC-bbb
```

## 7. Agent 实现参考（复用 ei_corpus_loop 模式）

collector 的"适配器即子 agent"与"提案起草 agent"复用参考项目的**三层角色 loop 模式**：

| 角色 | 工具 | 职责 |
|---|---|---|
| controller | claude_code | 规划、判下一轮 action、审核 |
| executor | opencode（子 agent） | 串行执行单个 action，**不派发子 agent**，自审 |
| runtime | python | 状态管理、subprocess 调 opencode、watchdog、串行约束校验 |

**关键复用件**（来源：`scripts/run_loop.py`、`skills/RESEARCH_EXECUTOR.md`、`config/action_space.yaml`）：

- **executor 行为由 skill 文档约束**：照 `RESEARCH_EXECUTOR.md` 的"防卡死 / 禁止事项 / 审计格式"规范，为 collector 写 `skills/COLLECTOR_EXECUTOR.md`（约束：不编造来源、不规避访问控制、短超时、完成 expected_outputs 即停、自审落审计 JSON）。
- **action 以 JSON 定义注入 prompt**：`state/next_action.json` 风格；collector 的 action 如 `COLLECT_TOPIC` / `RESOLVE_TOPIC` / `DRAFT_PROPOSAL`。
- **subprocess 调用**：`opencode run --agent <name> --dangerously-skip-permissions "<message>"`（flag 在前、message 在后，避开 Windows shim 截断）。
- **状态落 `state/`**：`human_questions.md`、`gaps.md`、`rounds.jsonl`；需人判断时输出 `NEED_HUMAN`，不阻塞。

**映射**：arXiv/GitHub 适配器 = executor agent（跑 `COLLECT_TOPIC`/`RESOLVE_TOPIC`）；提案起草 = executor agent（跑 `DRAFT_PROPOSAL`，产物落 `collection_topics.proposed_note`）。

> v1 先不接 opencode executor（纯 python 适配器 + 人工）；本节是 v1.1 接 loop / agent 时的实现蓝图。

## 8. Future Work

- **本体更新 loop 工程**：seedling→proposed 的提案闸门、agent 起草、复审、词表追加可编排成独立的 controller/executor/runtime 循环（§7 模式），作为 collector 之后的独立 loop 子项目。（记为 project 待办）
- **`work_assets` 表（v1.1）**：当代码资产需要被查询/管理时建表，迁移现有 JSON 仓库 URL。
- **关键词订阅 (b)**：主题 `mapped`、词表稳定后接 arXiv RSS / 分类订阅。
- **多跳引用图**：验证 1 跳精度后开放 2 跳（citing 的 citing）。
- **定时 loop（v1.1）**：collect/resolve 编排成 loop action，复用 ei_corpus_loop 骨架，对接 §7。
- **集成 spec §13.2**（A2 审核入口先 CLI 还是前端页面）与 §13.4（`_batch_classify*.py` 是否 `git rm`）本 spec 不涉及，留待后续。

## 9. 第一版验收标准（补充）

在集成 spec §11 基础上补充：

- [ ] `collection_topics` 表 + 迁移（幂等）；`intake_candidates.collection_topic_id` 字段。
- [ ] 主题管理 CLI：能 add/list/propose；`map_status` 与 `lifecycle` 正确流转。
- [ ] (a) 显式 ID 发现：给定 arXiv ID 列表，能采集元数据 + 写候选 + 跑轻量闸门。
- [ ] (c) 引用图 1 跳：给定种子论文，能调 Semantic Scholar 取 citing + cited，写候选 + 跑轻量闸门。
- [ ] collect/resolve 拆分：`collect` 不下载只跑轻量闸门；`resolve` 默认只对 `new`/`needs_better_copy` 下载 + SHA256；`--auto-resolve` 链式可用。
- [ ] GitHub 适配器：能从 repo 元数据抽 arXiv ID/DOI；命中已有 arXiv work 时判 `exact_hit` 或多源 `source_file`，不新建 work。
- [ ] 代码仓库 URL 进 `raw_meta`/`ingest_meta` JSON，不建 work、不污染 works。
- [ ] collector 绝不写本体词表（边界约束，测试覆盖）。
