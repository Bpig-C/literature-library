# 开源文献收集项目 ↔ 文献库 集成设计

> 日期：2026-06-27
> 状态：设计已讨论确认，待评审
> 关联：`README.md`、`TECHNICAL_OVERVIEW.md`、`FUTURE_WORK_PLAN.md`（P3 摄入后解析自动化、P4 前端上传）、`docs/superpowers/specs/2026-06-12-reading-methodology-analysis-runs-design.md`
> 上位设计：`D:\02_academic\doctoral\LITERATURE_SYSTEM_PLAN.md`

## 1. 背景与目标

文献库项目已具备稳定的"存储 → 解析 → 元数据 → 分类 → 分析"主干闭环，但**入口端不顺畅**：新增文献依赖 `_inbox` + 命令行，且去重只在**入库之后**发生。与此同时，一个独立的"开源文献/项目收集"诉求正在形成：从 arXiv、GitHub、机构站点等外部来源持续采集文献，并决定哪些值得进库。

本设计解决两个项目的对接问题。核心诉求：

1. 收集到的文献要能**入库**。
2. 入库前要能**利用已有库做去重分辨**，判断是否是新文献，避免重复采集、重复解析、重复占用存储。
3. 整个系统是**人和 AI 共用**的：人能审核，AI（agent）能操控。

### 设计目标

- 让"是否新文献"的判别**前移到入库前**，补上库目前缺失的能力。
- **不另起平行系统**：尽可能复用现有去重、隔离、摄入、审核体系，保持 works 为唯一真相源。
- collector 作为本仓库的**子模块**，同机运行，共享 `literature.sqlite`，但不直接写 `works`。

### 非目标（第一版不做）

- 远程/分布式采集（第一版仅同机本地运行）。
- 自动晋升入库（第一版走 A2 人工批量确认，A1 自动化留待验证可行后再开）。
- arXiv + GitHub 以外的来源（网页、PubMed 等）。
- 反爬深水区（登录态、JS 渲染重度站点）。

## 2. 关键决策（已确认）

| 决策点 | 选择 | 理由 |
|---|---|---|
| 对接方式 | 候选队列 + 预去重闸门 | 补上"入库前去重"，不重复实现匹配逻辑 |
| 队列归属 | **队列在库**（`intake_candidates` 表） | works 生命周期延伸，单一真相源 |
| 项目边界 | collector 作为**子模块**（同仓库） | 共享 schema/去重函数/模型配置，避免两个真相源 |
| 运行环境 | 同机运行，共享 SQLite | 单事务完成判别，无跨进程一致性风险 |
| 判别范围 | 全四态：exact_hit / title_candidate / needs_better_copy / SHA256 | SHA256 闸门复用现有逻辑，零成本 |
| 晋升策略（第一版） | **A2 人工批量确认**晋升 | 可控优先，验证可行后再开 A1 自动化 |
| 来源范围（第一版） | **arXiv + GitHub** | arXiv ID 是天然强查重键；GitHub 覆盖项目类资产 |

## 3. 架构与边界

```text
┌──────────────────────────────────────────────────────────────┐
│  literature_library（本仓库，单一真相源）                       │
│                                                               │
│  ┌─────────────────────┐        ┌─────────────────────────┐  │
│  │ collector/（子模块）  │        │ 现有库核心               │  │
│  │ • arXiv 适配器       │        │ works / source_files    │  │
│  │ • GitHub 适配器      │        │ duplicate_groups        │  │
│  │ • PDF 拉取           │  写候选 │ metadata / classification│  │
│  │ • 规范化（arXiv/DOI） │───────▶│ _quarantine（坏副本）    │  │
│  └─────────────────────┘        └─────────────────────────┘  │
│         │                                  ▲                  │
│         ▼                                  │                  │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ intake_candidates（新表）+ 预去重闸门（新能力）           │  │
│  │ 轻量闸门(元数据查重) ─▶ 下载 ─▶ 重量闸门(SHA256查重)    │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
                       共享 literature.sqlite
```

**核心边界约束**：

- collector **只负责采集 + 投递候选**，写 `intake_candidates`，**绝不直接写 `works`**。
- 候选晋升为 work 永远走库的闸门和审核门禁（第一版为人工批量确认）。
- collector 可以"脏"可以"快"（采集失败的候选就标 failed），库核心永远保持干净可审核。

## 4. 数据模型

### intake_candidates（新表）

候选队列。collector 写 `pending`，闸门写 `resolution`，审核写 `review_status`。

| 字段 | 说明 |
|---|---|
| `id` | 主键，格式 `IC-{hex}` |
| `source_type` | `arxiv` / `github` |
| `source_url` | 采集来源原始 URL |
| `title` | 候选标题（采集时拿到） |
| `arxiv_id` | 规范化 arXiv ID（可空） |
| `doi` | DOI（可空） |
| `url_canonical` | 规范化后的论文/资产主页 URL |
| `fetched_sha256` | 下载后的文件哈希（下载后填） |
| `local_pdf_path` | 下载的临时 PDF 路径（相对 library root） |
| `resolution` | 闸门判别结果：`pending` / `new` / `exact_hit` / `title_candidate` / `needs_better_copy` / `sha256_duplicate` / `fetch_failed` |
| `matched_work_id` | 命中的已有 work（若有） |
| `status` | `pending` / `resolved` / `ingested` / `skipped` / `superseded_quarantine` |
| `review_status` | `pending` / `approved` / `rejected`（复用审核语义，A2 流程用） |
| `review_note` | 审核备注 |
| `collected_at` | 采集时间 |
| `resolved_at` | 闸门判别时间 |
| `ingested_work_id` | 晋升后生成的 work_id（可空） |
| `raw_meta` | JSON：采集来源返回的原始元数据（arXiv API 响应、GitHub API 响应等），供审核参考 |

**索引**：`source_type`、`arxiv_id`、`doi`、`resolution`、`status`、`review_status`。

**唯一性**：`(source_type, url_canonical)` 唯一，避免同来源重复投递。

### 与现有表的关系

- 晋升时：`intake_candidates` → 复用 `literature_ingest.py` → 生成 `works` + `source_files` + `literature_parse_runs`(pending) + `parse_ledger` 条目。晋升后 `status='ingested'`，`ingested_work_id` 回填。
- `needs_better_copy` 命中 quarantined work 时：不新建 work，而是**替换**该 work 的源文件（见 §6）。

## 5. 两段式闸门与四态判别

闸门分两段，因为候选在两个时间点手里的信息不同：

| 阶段 | 手里有什么 | 查重依据 | 作用 |
|---|---|---|---|
| **轻量闸门**（采集时） | URL / 标题 / arXiv / DOI（未下载 PDF） | 元数据查 works | 决定**要不要下载全文** |
| **重量闸门**（下载后） | 已有 PDF 文件 | SHA256 查 source_files | 决定下载来的文件**是否精确重复** |

### 判别流程

```text
候选进入 intake_candidates (resolution=pending)
   │
   ▼
【轻量闸门】规范化 arXiv/DOI/标题 → 查 works
   │
   ├── arXiv/DOI 精确命中 active work ───────────▶ exact_hit / skipped
   ├── arXiv/DOI/标题 命中 quarantined work ────▶ needs_better_copy ★
   ├── 标题模糊相似（阈值内）但强键不匹配 ────────▶ title_candidate
   │                                            （进 duplicate_groups 人工队列）
   └── 无任何匹配 ─▶ new ─▶ collector 下载 PDF
                                   │
                                   ▼
                         【重量闸门】SHA256 查 source_files
                                   │
                                   ├── 命中 ─▶ sha256_duplicate / skipped
                                   └── 未命中 ─▶ 待晋升（走 A2 人工确认）
```

### 判别优先级（强 → 弱）

1. **arXiv ID 精确匹配**（规范化后）→ exact_hit
2. **DOI 精确匹配**（规范化后）→ exact_hit
3. **SHA256 精确匹配**（下载后）→ sha256_duplicate
4. **规范化标题模糊匹配**（相似度阈值，需可调）→ title_candidate
5. 以上都不命中 → new

### needs_better_copy 的特殊语义

当候选的 arXiv/DOI/标题命中一个 **quarantined** work（即"坏副本"）时，判别为 `needs_better_copy`。这正是 [[phase4-dedup-and-quarantine]] "坏副本≠坏文献"约束的激活：研究方向条目还在，只是副本坏了，collector 应优先去拉个好副本回来**替换**，而不是新建条目。

## 6. 与现有体系的衔接（本设计的核心收益）

| 新闸门态 | 复用的现有机制 | 新增工作量 |
|---|---|---|
| exact_hit | 读 `works.arxiv_id` / `works.doi` 索引 | 仅规范化函数 + 查询 |
| title_candidate | **复用** `duplicate_groups` + Duplicates 页面 + `scan_title_duplicates.py` | 候选转为 duplicate_candidate 的桥接 |
| sha256_duplicate | **复用** `literature_ingest.py` 现有 exact_sha256 去重逻辑 | 调用即可 |
| needs_better_copy | **复用** quarantine 体系 + restore | 新增"替换 quarantined work 源文件"动作 |
| new → work 晋升 | **复用** `literature_ingest.py` + parse pending + metadata 审核 | 桥接 + A2 审核页 |

**几乎没有新建平行系统**——闸门主要是把现有去重能力"前移 + 编排"。

### needs_better_copy 替换流程（草稿）

1. 闸门判 `needs_better_copy`，`matched_work_id` 指向 quarantined work。
2. A2 审核确认后，collector 下载好副本到 `local_pdf_path`。
3. 新增动作"替换源文件"：把好副本放入 `works/{work_id}/source/`，更新 `source_files`，`works.read_status` 从 `quarantined` 恢复，清除 `bad_source` code，归档旧坏副本到 `_archive/`。
4. **不重新建 work_id**，元数据/解析历史/分类标签全部保留。若新副本需要重新解析，走正常 parse pending。

## 7. A2 人工批量晋升流程（第一版）

第一版不走自动晋升。所有 `resolution=new` 的候选都进入人工审核队列：

1. collector 采集 + 闸门判别后，`new` 候选停在 `status=resolved, review_status=pending`。
2. 新增审核入口（前端页面或 CLI 列表），展示候选的 source_url、标题、arXiv/DOI、来源元数据、（可选）PDF 预览。
3. 人批量勾选 → `approve` / `reject`。
4. 批量 approved 的候选执行晋升：复用摄入逻辑生成 work，回填 `ingested_work_id`，`status=ingested`。
5. 晋升后的 work 自动进入现有 metadata/分类审核门禁（候选只负责"进库"，不绕过质量门禁）。

**晋升后状态留痕**：`works` 新增可选字段 `provenance`（`collector` / `inbox` / `manual`），标记来源，便于后续审计。第一版可先用 `ingest_meta` JSON 记录，不急着加列。

**A1 自动化触发条件**（验证后再开）：当 A2 流程连续 N 批 approved 率 > 阈值、且某来源（如 arXiv）查重稳定性确认后，可对该来源开自动晋升。

## 8. 来源适配器（第一版：arXiv + GitHub）

### arXiv 适配器

- 输入：arXiv ID 列表 / 关键词 / 分类（cs.AI 等）/ RSS。
- 利用 arXiv API（或现有 `nature-academic-search` 类工具）获取元数据：标题、作者、arXiv ID、DOI（若有）、abstract、PDF URL。
- 规范化 arXiv ID（去版本号 `v1`、统一格式）→ 这是天然强查重键，轻量闸门几乎可 100% 判重。
- 下载 PDF（保守并发，复用 document-parser 的并发约束经验）。

### GitHub 适配器

- 输入：仓库 URL 列表 / 主题搜索 / awesome 列表解析。
- GitHub 项目类资产与论文不同：可能没有 arXiv ID/DOI，查重主要靠**仓库 URL 规范化** + README 标题。
- 资产类型可能是 PDF（论文）、代码仓库、技术报告。`intake_candidates.raw_meta` 保留 GitHub API 响应。
- **查重策略调整**：GitHub 来源的轻量闸门以 `url_canonical`（规范化仓库 URL）为主键查 `works.url`，标题模糊匹配为辅。

> GitHub 适配器的复杂度高于 arXiv（资产形态多样），第一版建议先只支持"GitHub 上的论文 PDF / 技术报告"，仓库代码本身是否进库需单独讨论（可能不进 works，而作为 work 的关联资产）。

## 9. collector 子模块结构（建议）

```text
literature_library/
  collector/                 # 新子模块
    __init__.py
    adapters/
      arxiv.py               # arXiv 采集 + 规范化
      github.py              # GitHub 采集 + 规范化
    fetch.py                 # PDF 下载（保守并发）
    normalize.py             # arXiv/DOI/URL 规范化（闸门与适配器共用）
    gate.py                  # 预去重闸门（轻量 + 重量）
    ingest_bridge.py         # 候选 → work 晋升桥接（调用现有摄入逻辑）
    cli.py                   # collector CLI
  scripts/
    literature_intake.py     # 闸门 + 晋升管理 CLI（与现有脚本命名一致）
    migrate_add_intake_candidates.py  # 建表迁移
```

> collector 模块独立，但 `gate.py` / `ingest_bridge.py` **依赖**现有 `literature_ingest.py`、`literature_dedup.py` 的函数，不复制逻辑。

## 10. API / CLI 规划

### CLI（第一版优先）

```powershell
# 采集：从 arXiv 拉一批候选，写 intake_candidates，跑轻量闸门
python scripts/literature_intake.py collect --source arxiv --ids 2501.17805,2602.21012

# 跑闸门（对 pending 候选判别 + 下载 new 候选 + SHA256 重量闸门）
python scripts/literature_intake.py resolve --limit 20

# 列出待晋升（A2 审核）
python scripts/literature_intake.py list --resolution new --review-status pending

# 批量晋升（A2）
python scripts/literature_intake.py promote --ids IC-aaa,IC-bbb
```

### API（第二版，复用 P4 上传 API 基础）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/intake/candidates` | 候选列表（按 resolution/review_status 筛选） |
| POST | `/api/intake/candidates` | 手动投递候选（人或 agent） |
| POST | `/api/intake/resolve` | 触发闸门判别 |
| POST | `/api/intake/promote` | 批量晋升 approved 候选 |
| GET | `/api/intake/stats` | 采集统计（new/duplicate/quarantined 命中数） |

## 11. 第一版验收标准

- [ ] `intake_candidates` 表 + 迁移脚本（幂等）+ healthcheck 检查。
- [ ] arXiv 适配器：给定 arXiv ID 列表，能采集元数据 + 写候选 + 轻量闸门判别。
- [ ] 轻量闸门：arXiv/DOI 精确命中已有 work 时正确判 `exact_hit`；标题模糊命中判 `title_candidate`；命中 quarantined work 判 `needs_better_copy`。
- [ ] 重量闸门：下载后 SHA256 命中已有 source_files 时判 `sha256_duplicate`。
- [ ] A2 人工晋升：CLI 能列出 `new` 候选、批量 approved 后正确生成 work（复用摄入逻辑），`ingested_work_id` 回填，DB/index/ledger 一致。
- [ ] needs_better_copy 替换：能替换 quarantined work 的源文件并恢复 read_status。
- [ ] collector 不直接写 `works`（边界约束，测试覆盖）。
- [ ] healthcheck 覆盖候选与 work 的一致性、孤立 PDF、重复晋升防护。

## 12. 与现有路线的关系

本设计与 `FUTURE_WORK_PLAN.md` 的关系：

- **吸收并扩展 P3（摄入后解析自动化）**：晋升后的 work 复用 P3 的 parse pending 链路。建议 P3 与 collector 第一版同步推进，因为候选晋升后立即需要解析。
- **早于 P4（前端上传）但复用其成果**：第一版用 CLI；P4 的 `POST /api/works` / intake API 可在 collector 第二版承接。
- **与 P5（外部元数据补全）协同**：arXiv 适配器采集的元数据天然补全了 P5 想做的 arXiv/CrossRef 增强，候选的 `raw_meta` 可直接喂给 metadata 审核。
- **独立于 P1.1/P1.2（分析/矩阵）**：collector 不影响已有分析链路，只是为它持续喂数据。

建议在 `FUTURE_WORK_PLAN.md` 新增一节 **P1.5（或独立编号）：开源文献收集与预去重闸门**，与本 spec 互引。

## 13. 待决问题（评审时讨论）

1. **GitHub 仓库代码资产**是否进 works，还是作为 work 的关联资产（新表 `work_assets`）？第一版建议只收 GitHub 上的论文/报告 PDF。
2. **A2 审核入口**：第一版先做 CLI 列表，还是直接做前端页面（复用 MetadataReview 模式）？
3. **collector 采集频率/触发**：手动 CLI 触发，还是定时任务（cron/loop）？第一版建议手动。
4. 已跟踪的两个划痕脚本 `scripts/_batch_classify.py`、`_batch_classify_all.py` 是否一并归档（需 `git rm`）。
