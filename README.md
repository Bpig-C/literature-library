# 文献库项目说明

本目录是本地文献管理系统的数据根目录，用来保存已经迁移、去重、解析后的文献库。README 是项目总入口，不再承担全部使用细节；具体操作按读者角色分流到三类手册。

- 本文档：说明当前项目定位、目录结构、核心概念和文档入口。
- `docs/manuals/user-manual.md`：浏览器用户手册。
- `docs/manuals/cli-manual.md`：CLI/自动化手册。
- `docs/manuals/agent-manual.md`：agent 协作手册。
- `FUTURE_WORK_PLAN.md`：只记录后续尚未完成的维护计划。
- `docs/PROJECT_HISTORY.md`：记录已完成阶段、历史路线和旧判断。

## 长期维护文档

后续维护时优先读取这些文档；其余带日期的计划、审核和实验材料默认视作历史证据，已集中归档到 `docs/_archive/`。

| 文档 | 用途 | 维护要求 |
|---|---|---|
| `README.md` | 项目首页、目录结构、核心概念和文档导航。 | 文档入口、主流程或长期维护文档变化时同步更新。 |
| `docs/manuals/README.md` | 三类使用手册索引。 | 新增、拆分或合并手册时同步更新。 |
| `docs/manuals/user-manual.md` | 浏览器用户手册：页面入口、日常流程、人工审核边界。 | UI 页面、用户流程或模板页面行为变化时同步更新。 |
| `docs/manuals/cli-manual.md` | CLI/自动化手册：脚本、API、测试、批处理命令。 | 脚本参数、验证命令、API 自动化入口变化时同步更新。 |
| `docs/manuals/agent-manual.md` | Agent 协作手册：边界、派发方式、两轮审核、交接格式。 | agent 权限边界、任务派发或审核流程变化时同步更新。 |
| `TECHNICAL_OVERVIEW.md` | 系统架构、不变量、数据边界。 | 架构或事实源变化时同步更新。 |
| `FUTURE_WORK_PLAN.md` | 当前未完成路线图和下一步候选；想掌握“接下来做什么”优先看这里。 | 完成任务后移动到历史记录或标记完成。 |
| `USER_ISSUES.md` | 用户提出的问题、状态与验收记录。 | 每次修复或确认后更新状态。 |
| `docs/HANDOVER_GUIDE.md` | 当前交接、页面清单、已知遗留；想快速接手项目优先看这里。 | 大轮次交接或功能批量完成后更新。 |
| `docs/PROJECT_HISTORY.md` | 已完成阶段、历史路线和旧判断；想确认“某功能是否已完成”看这里。 | 只追加重大完成记录，不作为当前待办。 |
| `docs/DOCUMENT_GOVERNANCE.md` | 文档状态、归档和发布前门禁规则。 | 文档体系变化时同步更新。 |
| `docs/superpowers/README.md` | 当前审核证据和 dated docs 索引。 | 新增/归档 review、plan、spec 时同步更新。 |
| `docs/_archive/README.md` | 已归档文档索引。 | 归档文件时同步更新分类说明。 |

## 三类使用手册

| 你是谁 | 先看哪个 |
|---|---|
| 通过浏览器管理文献、审核抽取结果 | [用户手册](docs/manuals/user-manual.md) |
| 通过命令行跑摄入、解析、抽取、测试和健康检查 | [CLI 与自动化手册](docs/manuals/cli-manual.md) |
| 派发 Codex/opencode/本地模型执行长任务、审核或批处理 | [Agent 协作手册](docs/manuals/agent-manual.md) |

团队协作时，先按角色读对应手册，再回到 `FUTURE_WORK_PLAN.md` 看下一步做什么，去 `USER_ISSUES.md` 查问题状态，最后用 `docs/PROJECT_HISTORY.md` 查历史完成证据。

当前状态：V1.1 前端端到端主流程和受约束发现检索已打通。FastAPI + Vue SPA 可从前端完成“发现/检索 -> hit 回填 -> 候选审核 -> 摄入/入库 -> 解析 -> 元数据抽取 -> 分类抽取 -> 人工审核 -> 回填/应用”的主链路；解析状态以 SQLite `literature_parse_runs` 为唯一权威。模板管理已成为元数据抽取资产入口：`/templates` 编辑 `templates/templates.json`，真实元数据抽取 CLI/API/rerun 均读取 `api/metadata_template.py` loader，`/metadata` 审核表也会按模板字段动态渲染。V1 发布审查见 `docs/_archive/superpowers/reviews/2026-06-29-v1-final-publication-p1-remediation.md`，V1.1 主流程完成报告见 `docs/_archive/superpowers/reviews/2026-06-30-v1.1-frontend-end-to-end-flow-result.md`，发现检索 agent 协议见 `docs/discovery-agent-protocol.md`。

## 目录架构

```text
D:\02_academic\doctoral\literature_library
  _inbox\              # 新 PDF 的临时投递入口
  _duplicates\         # 精确重复文件归档处
  _quarantine\         # 失败、坏源、元数据存疑文件暂存处
  _archive\            # 已归档的历史中间产物和备份
  works\               # 文献永久存储区
  views\               # 自动生成的只读视图（历史，已被 SPA 替代）
  scripts\             # 本文献库本地维护脚本
  api\                 # FastAPI 后端（Phase 3b）
  web\                 # Vue 3 前端 SPA（Phase 3b）
  tests\               # 本地维护脚本测试
  templates\           # 可审查模板资产（metadata baseline、analysis angle 模板等）
  literature.sqlite    # 主数据库
  pyproject.toml       # Python 项目配置（uv 环境）
  index.json           # 前端/脚本可读的文献索引
  # parse_ledger.json 已废弃并归档；解析状态以 literature_parse_runs 表为准
```

## 核心概念

`_inbox` 是新文献的入口，不是永久存储位置。可以手动把 PDF 放进去，也可经前端 `/inbox`（InboxReview）页 dry-run 预览后确认摄入。执行摄入后，新 PDF 会复制到 `works\{work_id}\source\`，`_inbox` 中的原始投递文件会归档到 `_archive\ingested_inbox\`。

`works` 是稳定物理存储区。每篇文献有一个 `work_id`，例如 `W-arxiv-2501.17805` 或 `W-sha-d35373840d97`。PDF、MinerU 解析结果、笔记、分析结果都围绕这个目录组织。

`literature.sqlite` 是逻辑关系中心，记录 Work、source 文件、解析产物、重复候选、文献关系等。主题、标签、关系不靠物理文件夹表达，而是进入数据库。

解析任务状态以 `literature.sqlite` 的 `literature_parse_runs` 表为唯一权威（Phase D 状态源统一）。新增文献摄入后会先以 `pending` 状态写入该表，等需要解析时再触发（CLI `literature_batch_parse.py` / API `POST /api/parse/trigger` / UI WorkDetail 按钮）。`parse_ledger.json` 是历史文件镜像，已废弃并归档至 `_archive/`，不再读写。

## 日常流程

### 1. 新增 PDF 入库

把新 PDF 放入：

```text
D:\02_academic\doctoral\literature_library\_inbox
```

先做 dry-run，检查计划：

```powershell
python scripts\literature_ingest.py
```

确认无误后执行：

```powershell
python scripts\literature_ingest.py --execute
```

摄入脚本会做这些事：

- 扫描 `_inbox` 中的 PDF
- 计算 sha256
- 精确重复文件移入 `_duplicates\exact_sha256`
- 新文件复制到 `works\{work_id}\source\`
- `_inbox` 原始投递文件归档到 `_archive\ingested_inbox\`
- 写入 `literature.sqlite`（含 `literature_parse_runs` 新增 `pending` 解析行）
- 更新 `index.json`

如果希望执行摄入后仍保留 `_inbox` 原文件，可加：

```powershell
python scripts\literature_ingest.py --execute --leave-inbox
```

### 2. 解析新增 PDF

> 现行解析架构（Phase B/E）：**二元路由** `parser/core/mineru/router.py::route_and_parse`——文本层 PDF(born-digital) → PyMuPDF 本地直抽（免费/快）；扫描型/质检不过 → MinerU 官网 cloud vlm API（token 从根 `.env` 的 `MinerU_API_KEY` 读）。旧的自部署 MinerU:18200 + document-parser:18201 两层架构已降级为回滚参考（CLI 归档于 `_archive/`）。完整审核/测试步骤见 `docs/_archive/superpowers/specs/2026-06-29-three-chain-runbook.md`。

最常用（解析所有 pending，DB-only 状态源）：

```powershell
python scripts\literature_batch_parse.py --execute
```

旧的自部署 MinerU / document-parser 两层链路只保留为回滚参考，不是 V1 默认路径。相关历史说明在 `docs/maintain_doc/mineru-ops.md` 和 `_archive/README.md`，日常不要从 `D:\06_tools\document-parser` 触发解析。

### 3. 查看当前库状态

快速查看 `_inbox` 是否有待摄入 PDF：

```powershell
Get-ChildItem _inbox -Recurse -Filter *.pdf
```

查看摄入脚本会做什么：

```powershell
python scripts\literature_ingest.py --limit 5
```

查看解析状态：

```powershell
python scripts\healthcheck_library.py --json
```

如果需要查看具体 pending/succeeded/failed 行，请查询 SQLite 的 `literature_parse_runs` 表，或使用 API `GET /api/parse/status?work_id=...`。

### 4. 运行本地脚本测试

```powershell
python -m unittest tests.test_literature_ingest -v
```

API 与元数据审核相关测试：

```powershell
uv run python -m pytest tests/test_api.py
```

### 5. 生成只读文献台账（历史，已被 SPA 替代）

生成本地 HTML 台账：

```powershell
python scripts\literature_dashboard.py
```

生成结果：

```text
D:\02_academic\doctoral\literature_library\views\library_dashboard.html
```

这个页面是 Phase 3 的最小可用只读入口，不需要启动后端服务。可以直接用浏览器打开，支持：

- 统计当前 works、active source、content.md、重复候选数量
- 按标题、作者、Work ID、arXiv、DOI 搜索
- 按解析状态、文献类型、语言筛选
- 查看每篇文献的 PDF 路径、`content.md` 路径、sha256、解析产物、重复候选和文献关系

现在推荐使用 Vue SPA（见下方"启动 Vue SPA"）。

### 6. 启动 Vue SPA（Phase 3b）

项目包含 FastAPI 后端和 Vue 3 前端，提供文献管理界面（搜索、编辑元数据、关系管理、去重确认、隔离/恢复）。

**环境准备（使用 uv）：**

```powershell
# 安装 Python 依赖
uv sync

# 安装前端依赖
cd web
npm install
cd ..
```

**启动后端（端口 19527）：**

```powershell
uv run python scripts\run_api.py
```

API 文档：http://127.0.0.1:19527/docs

**启动前端（端口 19528）：**

```powershell
cd web
npm run dev
```

访问 http://localhost:19528

**主要页面：**

- `/` — 总览仪表盘
- `/works` — 文献列表（搜索、筛选、分页）
- `/works/:id` — 文献详情（源文件 -> 解析 -> 元数据 -> 分类 workflow bar，编辑元数据、查看 content.md、管理关系）
- `/duplicates` — 去重确认（决策按钮、localStorage 持久化）
- `/relations` — 关系管理（新增、删除）
- `/metadata` — 元数据抽取审核（按模板字段动态渲染、风险分级、原文预览、证据定位、人工编辑、字段级重抽、审核回填）
- `/templates` — 模板管理（元数据字段资产；保存后影响真实元数据抽取 CLI/API/rerun）
- `/classification` — 分类标签审核（primary_doc_type、risk_domain、method_tags 等）
- `/intake` — 采集候选审核（resolution、review_status、promote）
- `/inbox` — Inbox 摄入 dry-run 预览与确认
- `/topics` — 采集主题管理（新建主题、成熟度转换、mapped_tags、按主题采集）
- `/discovery` — 受约束发现检索（plan/run/hit 审核，agent 回填入口）

### 7. 前端端到端主流程（V1.1 推荐）

V1.1 后，日常使用优先走 Vue SPA，而不是把 CLI 命令串起来手工执行。

推荐流程：

1. 在 `/topics` 新建或选择采集主题，填写显式 arXiv ID、种子文献 ID 或主题说明后发起采集。
2. 在 `/intake` 审核候选，确认 resolution、review_status 后 promote 为正式 work。
3. 如果是本地 PDF 投递，先进入 `/inbox` 做 dry-run 预览，再确认摄入。
4. 进入 `/works/:id`，按照 workflow bar 依次检查源文件、触发解析、触发元数据抽取、触发分类抽取。
5. 从 workflow bar 的“去审核”进入 `/metadata` 或 `/classification`，审核 pending 候选并批准/修正/拒绝。
6. 审核通过后，元数据按只填空字段策略回填 `works`；分类标签进入受控词表和人工审核边界，不绕过审核门禁。

当前边界：

- 元数据和分类抽取仍是同步触发，依赖本地 LLM / MiMo 服务可用性；大批量抽取应继续走脚本或后续任务队列。
- 前端主流程已覆盖日常单篇/小批量使用，但不包含大规模自动检索调度、完整后台任务队列、引用导出和综述矩阵。

### 8. 受约束发现检索（V1.2）

发现检索用于处理"我知道一个主题/名称/标题/URL，但还不知道具体 arXiv ID 或 PDF 在哪里"的场景，例如模型卡、系统卡、机构技术报告、官网报告页、项目页等弱引用材料。

V1.2 新增 **composite 多信号组合模式**：允许用户同时提供名称、作者、机构、关键词、已知 URL 等多种线索，agent 综合这些信号生成更精准的检索方案，解决单一模式输入信息量不足的问题。

推荐流程：

1. 在 `/topics` 新建或选择主题，或直接进入 `/discovery` 按 `topic` / `name` / `title` / `url` / `composite` 创建 discovery run。
2. `topic` / `name` / `title` / `composite` 会生成 `planned` run 和 `search_plan_json`；`url` 模式会创建 manual run/hit。
3. 把 run id 交给本地模型/agent，并要求它先读取 `docs/discovery-agent-protocol.md`。agent 只执行检索并回填 hits，不 accept、不 promote、不写 `works`。
4. agent 通过 `POST /api/discovery/runs/{run_id}/hits` 回填 JSON 数组。
5. 回到 `/discovery` 审核 hits。接受有效命中后，系统只创建 `intake_candidates(resolution='pending')`。
6. 到 `/intake` 继续 resolve、review、promote；后续再走 `/works/:id` 的解析、元数据抽取和分类抽取。

给本地模型的最小固定指令：

```text
你是 literature_library 的 discovery-search agent。
工作目录：D:\02_academic\doctoral\literature_library
必须先读取：docs/discovery-agent-protocol.md
输入：run_id={DR-xxxx}

严格按照 run.search_plan_json 检索并回填 hits：
- 如果 mode 是 composite：综合 names/titles/authors/keywords/institutions 等多种信号设计检索策略。
- 每条 hit 输出 title、url、source_type、snippet、reason、confidence、query、primary_source、content_type、verification_status。
- 必须加载 web-access skill 并严格遵循其指引（域名白名单、频率限制、访问控制等约束）。
通过 POST /api/discovery/runs/{DR-xxxx}/hits 回填 JSON 数组。
回填后停止；不要 accept、promote、写 works、改 ontology vocab、下载 PDF 或摄入文件。
```

当前边界：

- V1.2 支持 `topic` / `name` / `title` / `url` / `composite` 五种 discovery 模式。
- **composite 模式 [V1.2 新增]**：可同时提供 names、titles、authors、institutions、keywords、known_urls、preferred_domains、exclude_terms、artifact_type_hint、max_results、freeform_note 等多种信号，详见 `docs/discovery-agent-protocol.md` 的 "Composite Input Schema" 章节。
- DOI、arXiv、GitHub URL 不作为 discovery mode；arXiv/GitHub 仍走现有 intake collect 链路，DOI 可先按 title/name 检索。
- 检索结果默认只是候选 hit，不会直接污染 `works`。
- composite 是增量功能，完全向后兼容旧模式。

### 9. 元数据审核与重抽

当前元数据抽取结果保存在 `metadata_extractions`，不会直接覆盖 `works` 稳定层。推荐流程是先在 SPA 的 `/metadata` 页面审核，再按需要回填。

元数据模板已经是当前抽取链路的事实源：在 `/templates` 的“元数据字段”Tab 修改字段后，会保存到 `templates/templates.json`；后端通过 `api/metadata_template.py` 合并默认模板和自定义模板。新的元数据抽取、字段级重抽、prompt 复制和 `/metadata` 审核表都会读取同一份模板。新增字段只要保存成功，就可以在后续抽取/重抽中出现，也会在审核页作为可编辑字段展示。

#### 9.1 前端用户怎么用

1. 打开 `/templates`，在“元数据字段”Tab 查看或编辑字段。字段 `key` 是系统识别名，保存后不要随意改名；如果确实要改名，应把它当成一次模板迁移。
2. 新增字段后，回到 `/metadata` 审核页。审核表会按当前模板动态展示字段；自定义字段支持编辑、复制 prompt 和字段级重抽。
3. 对单个字段不满意时，优先点字段行旁边的“重抽”。系统会先生成预览 diff，确认后才写入新的 `metadata_extractions`，并把旧记录标为 superseded。
4. 如果本地模型/API 暂时不可用，可以点“复制”拿到带 field focus 的 prompt，交给人工或外部模型手动处理；手动结果再通过审核页编辑或 API supersede 写回。
5. 人工编辑过的模板字段会被视为已确认字段，`confidence_json[field]` 会提升为 `high`；批准后才能进入回填流程。

#### 9.2 Agent/CLI 批量怎么用

Agent 做批量抽取或批量重抽时，不需要从界面复制 prompt。正确做法是先读本文档、`scripts/README.md`、`templates/templates.json` 和 `api/metadata_template.py` 的字段定义，然后直接调用 CLI 或 HTTP API。界面的“复制 prompt”只是给单条人工降级场景用的。

推荐边界：

- 批量新增/调整元数据字段：优先让 agent 修改 `templates/templates.json`，或调用 `POST /api/templates/metadata`；改完必须跑测试和前端构建。
- 批量抽取新文献：使用 `scripts\literature_metadata_extract.py` 或 `POST /api/metadata/extract`。
- 批量重抽已存在候选：使用 `scripts\literature_metadata_rerun.py`。`--fields` 支持模板中的自定义字段 key；脚本会校验字段白名单。
- 批量审核修复队列：先查 `GET /api/metadata/agent/queue` 或 CLI 队列，再按风险/错误模式分批处理；不要绕过人工审核直接写 `works`。
- 自动化/CI 风格验证：至少跑后端相关测试、健康检查和前端构建，确认模板、审核页和 CLI 没有漂移。

审核状态语义：

- `approved`：候选值可回填 `works`。默认只填空字段，不覆盖已有人工字段，不自动回填 `year`。
- `needs_fix`：候选值部分可用但需要修正。人工编辑过的字段会被视为已确认，`confidence_json[field]` 会提升为 `high`，批准后可回填。
- `rejected`：本次抽取不可信或不适用，不回填；可供 agent 后续聚类错误模式。

常用命令：

```powershell
# 查看 needs_fix 队列和错误模式聚类
python scripts\literature_metadata_rerun.py --status needs_fix --limit 20

# 查看某篇 work 的抽取历史
python scripts\literature_metadata_rerun.py --work-id W-arxiv-xxxx

# 对指定 extraction 真重抽，写入新的 metadata_extractions，并让旧记录 superseded
python scripts\literature_metadata_rerun.py --ext-id ME-xxxx --rerun

# 字段级重抽：模型仍返回完整 JSON，但系统只用新结果覆盖指定字段
python scripts\literature_metadata_rerun.py --ext-id ME-xxxx --fields title,date,url --rerun

# 自定义字段级重抽：字段 key 来自 /templates 或 templates\templates.json
python scripts\literature_metadata_rerun.py --ext-id ME-xxxx --fields journal,artifact_version --rerun

# 预览重抽结果，不写数据库
python scripts\literature_metadata_rerun.py --ext-id ME-xxxx --fields url --rerun --no-write --json
```

本地模型默认配置在脚本中：

```text
Ollama URL: http://localhost:11435
Model: qwen3:4b-instruct-2507-q4_K_M
```

如果需要使用其他模型或服务：

```powershell
python scripts\literature_metadata_rerun.py --ext-id ME-xxxx --rerun --url http://localhost:11435 --model qwen3:4b-instruct-2507-q4_K_M
```

**API 端点：**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/works` | 文献列表（支持搜索、筛选、分页） |
| GET | `/api/works/{id}` | 文献详情 |
| PATCH | `/api/works/{id}` | 更新文献元数据 |
| POST | `/api/works/{id}/quarantine` | 隔离文献 |
| POST | `/api/works/{id}/restore` | 恢复隔离文献 |
| GET | `/api/relations` | 所有关系 |
| POST | `/api/relations` | 新增关系 |
| DELETE | `/api/relations` | 删除关系 |
| GET | `/api/duplicates` | 重复组列表 |
| POST | `/api/duplicates/{group_id}/review` | 标记重复组已审查 |
| GET | `/api/duplicates/{group_id}/merge-preview` | 预览合并推荐（得分、推荐主条目） |
| GET | `/api/files/{work_id}/content` | 获取 content.md 原文 |
| GET | `/api/files/{work_id}/pdf` | 获取 PDF 文件 |
| GET | `/api/metadata` | 元数据抽取审核队列 |
| POST | `/api/metadata/extract` | 触发元数据抽取（指定 work_ids 或小批量） |
| GET | `/api/metadata/{ext_id}` | 元数据抽取详情 |
| PATCH | `/api/metadata/{ext_id}/review` | 审核抽取结果；人工编辑字段会提升为可回填来源 |
| POST | `/api/metadata/apply-approved` | 回填已批准且未应用的抽取结果 |
| POST | `/api/metadata/batch-approve-low-risk` | 批量批准低风险 pending 记录 |
| GET | `/api/metadata/agent/queue` | agent 修复队列，按风险排序并返回错误模式聚类 |
| GET | `/api/metadata/{ext_id}/rerun-prompt` | 生成字段级重抽 prompt（前端“复制”使用） |
| POST | `/api/metadata/{ext_id}/rerun-preview` | 字段级重抽预览，不直接写库 |
| POST | `/api/metadata/{ext_id}/rerun-apply` | 确认预览并创建 superseding extraction |
| POST | `/api/metadata/{ext_id}/supersede` | 使用外部提供的替换字段创建 superseding extraction |
| POST | `/api/metadata/{ext_id}/quarantine` | 从元数据审核页隔离文献 |
| GET | `/api/templates` | 模板概览，含元数据/分类/Discovery 当前状态 |
| GET | `/api/templates/metadata/schema` | 元数据模板字段 schema |
| POST | `/api/templates/metadata` | 保存元数据字段模板并自动备份 |
| POST | `/api/templates/metadata/reset` | 恢复元数据默认模板 |
| GET | `/api/classification/tags/{work_id}` | 获取文献分类标签 |
| POST | `/api/classification/tags/{work_id}` | 创建分类标签 |
| POST | `/api/classification/tags/{work_id}/batch` | 批量创建分类标签 |
| DELETE | `/api/classification/tags/{tag_id}` | 删除分类标签 |
| PATCH | `/api/classification/tags/{tag_id}/review` | 审核分类标签 |
| GET | `/api/classification/vocab` | 分类词汇表（primary_doc_type、reading_lane 等） |
| GET | `/api/classification/extractions` | 分类抽取列表（按状态/风险筛选） |
| POST | `/api/classification/extract` | 触发分类抽取（指定 work_ids 或小批量） |
| GET | `/api/classification/extractions/{ext_id}` | 分类抽取详情 |
| PATCH | `/api/classification/extractions/{ext_id}/save-draft` | 保存分类抽取草稿 |
| PATCH | `/api/classification/extractions/{ext_id}/review` | 审核分类抽取结果 |
| POST | `/api/classification/extractions/batch-approve-low-risk` | 批量批准低歧义分类抽取 |
| POST | `/api/classification/extractions/batch-approve-with-tag` | 批量批准并打标签 |
| POST | `/api/classification/extractions/{ext_id}/quarantine` | 从分类审核页隔离文献 |
| GET | `/api/intake/candidates` | 采集候选列表（筛选、分页） |
| GET | `/api/intake/stats` | 采集统计（按 resolution / review_status） |
| POST | `/api/intake/resolve` | 触发 SHA256 门控解析 |
| PATCH | `/api/intake/candidates/{candidate_id}/review` | 审核采集候选 |
| POST | `/api/intake/promote` | 批量提升已批准候选为正式文献 |
| GET | `/api/intake/topics` | 采集主题列表 |
| POST | `/api/intake/topics` | 主题成熟度转换 |
| POST | `/api/intake/topics/create` | 新建采集主题 |
| POST | `/api/intake/collect` | 按主题/显式 ID 发起采集 |
| POST | `/api/discovery/plan` | 生成 discovery search plan，不创建 run |
| POST | `/api/discovery/run` | 创建 discovery run |
| GET | `/api/discovery/runs` | 发现检索 run 列表 |
| GET | `/api/discovery/runs/{run_id}` | 查看单个 run 和 search plan |
| POST | `/api/discovery/runs/{run_id}/hits` | agent 回填 discovery hits |
| GET | `/api/discovery/hits` | 发现检索命中列表 |
| POST | `/api/discovery/hits/{hit_id}/accept` | 接受单个 hit 并创建 intake candidate |
| POST | `/api/discovery/hits/batch-accept` | 批量接受 hits 并创建 intake candidates |
| POST | `/api/discovery/hits/{hit_id}/reject` | 拒绝 hit 并记录审核备注 |
| GET | `/api/parse/status` | 解析状态汇总或单篇查询 |
| POST | `/api/parse/trigger` | 触发解析（指定 work_ids 或 all_pending） |
| GET | `/api/ingest/plan` | 摄入 dry-run 预览 |
| POST | `/api/ingest/execute` | 执行摄入 |

### API-Only Endpoints（无前端入口）

以下端点仅用于编程/脚本调用，前端 SPA 中无对应 UI：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/metadata/agent/queue` | Agent 修复队列，按风险排序并返回错误模式聚类，供自动化脚本消费 |
| POST | `/api/metadata/{ext_id}/supersede` | 使用外部提供的替换字段创建 superseding extraction，供脚本/API 调用（模型重抽请用 CLI） |
| POST | `/api/classification/extractions/batch-approve-with-tag` | 按自定义模糊度阈值批量批准分类抽取，并写入统一审核备注标签，供批量处理脚本调用 |

## 重要约定

- 不要重跑 inventory/migration，除非明确要从原始 `literature_read` 重新构建。
- 不要手动移动 `works` 下的 PDF；让摄入、归档、隔离、恢复脚本维护 DB 路径和 `source_files.status` 的一致性。
- `_inbox` 是临时入口，`works` 才是永久存储。
- `views` 是自动生成视图，后续应由脚本生成，不建议手动维护。
- 解析失败或坏源文件进入 `_quarantine` 或 `_archive`，不要直接删除。隔离和恢复必须同步 `source_files.source_path` 与 `source_files.status`。
- 新文献摄入后默认只是 `pending`，不会自动启动 MinerU。

## 安全约定

- `.env` 已被 `.gitignore` 排除，不会提交到 git 仓库。
- 脚本和 agent 只应打印环境变量的键名（key），不要打印值（value）。
- 在共享工作区中，建议将密钥（如 `MinerU_API_KEY`）存放在用户级环境变量或密钥管理工具中，而非项目级 `.env` 文件。
- API 端点不暴露敏感配置；CORS 仅允许 `localhost:19528`。

## 已有脚本

当前文献库本地脚本：

- `scripts\literature_ingest.py`：Phase 1 `_inbox` 摄入 MVP
- `scripts\literature_dashboard.py`：Phase 3 只读文献台账生成器（已被 SPA 替代）
- `scripts\literature_dedup.py`：Phase 4 去重分析，生成去重候选组
- `scripts\dedup_apply.py`：Phase 4 将去重决策应用到数据库
- `scripts\literature_metadata_extract.py`：基于 MinerU `content.md` 的元数据抽取与可选回填
- `scripts\literature_metadata_rerun.py`：审核修正队列查询、字段级重抽、supersede 审计链写入
- `scripts\literature_classification_extract.py`：基于 `content.md` 的分类候选抽取与可选回填
- `scripts\literature_discovery.py`：受约束发现检索 plan/run/hit/accept/reject CLI，配合 `/discovery` 和 `docs/discovery-agent-protocol.md` 使用
- `scripts\backfill_risk.py`：为已有元数据抽取记录回填风险等级、分数和原因
- `scripts\run_api.py`：启动 FastAPI 后端服务

历史/归档脚本：

- `_archive/`：旧 parser CLI、历史 ledger 备份和确认无 active 引用的根级脚本。
- `scripts/_archive/`：一次性 phase helper 或早期批处理脚本。
- `parser/_legacy_service/`：休眠的旧 parser HTTP 服务边界。

日常新增文献优先使用本仓库内的 `scripts\literature_ingest.py`、`scripts\literature_batch_parse.py`、前端 `/inbox`、以及 FastAPI `/api/ingest/*` / `/api/parse/*`。
