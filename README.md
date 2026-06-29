# 文献库项目说明

本目录是本地文献管理系统的数据根目录，用来保存已经迁移、去重、解析后的文献库。它和阶段规划文档分工不同：

- 本文档：说明当前项目架构、目录含义、日常使用流程和常用命令。
- `D:\02_academic\doctoral\LITERATURE_SYSTEM_PLAN.md`：记录分阶段建设计划、设计背景和后续路线。

当前状态：Phase 0–4 均已完成。138 个 Work、140 个 source PDF 全部解析成功。去重确认 13 组（9 SHA256 自动确认 + 4 标题候选已决策），7 个坏源已隔离。Vue SPA + FastAPI 后端可启动使用。

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
  literature.sqlite    # 主数据库
  pyproject.toml       # Python 项目配置（uv 环境）
  index.json           # 前端/脚本可读的文献索引
  parse_ledger.json    # (已废弃/归档) 解析状态现以 literature_parse_runs 表为准
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

> 现行解析架构（Phase B/E）：**二元路由** `parser/core/mineru/router.py::route_and_parse`——文本层 PDF(born-digital) → PyMuPDF 本地直抽（免费/快）；扫描型/质检不过 → MinerU 官网 cloud vlm API（token 从根 `.env` 的 `MinerU_API_KEY` 读）。旧的自部署 MinerU:18200 + document-parser:18201 两层架构已降级为回滚参考（CLI 归档于 `_archive/`）。完整审核/测试步骤见 `docs/superpowers/specs/2026-06-29-three-chain-runbook.md`。

最常用（解析所有 pending，DB-only 状态源）：

```powershell
python scripts\literature_batch_parse.py --execute
```

<details>
<summary>旧的自部署 MinerU 两层设置（降级参考，cloud 模式不需要）</summary>

短期内不需要常驻 MinerU，因为现有 140 个活跃 PDF 已全部解析成功。只有新增文献、重跑解析或处理疑难 PDF 时才启动。

解析链路分两层：

- MinerU：实际 PDF 解析服务，默认端口 `18200`
- document-parser：本地 FastAPI 封装服务，默认端口 `18201`

启动 document-parser：

```powershell
cd D:\06_tools\document-parser
uv run python main.py
```

如果 MinerU 在远端，先配置：

```powershell
$env:MINERU_SERVER_URL="http://<远端服务器IP>:18200/file_parse"
uv run python main.py
```

健康检查：

```powershell
curl.exe http://127.0.0.1:18201/health
curl.exe http://127.0.0.1:18200/health
```

解析 pending 文献时，在 `D:\06_tools\document-parser` 中运行：

```powershell
uv run python scripts\literature_batch_parse.py --library-root D:\02_academic\doctoral\literature_library --max-workers 1 --limit 3
```

建议保持保守并发：

```text
MINERU_API_MAX_CONCURRENT_REQUESTS=1
MINERU_PROCESSING_WINDOW_SIZE=32
```

</details>

### 3. 查看当前库状态

快速查看 `_inbox` 是否有待摄入 PDF：

```powershell
Get-ChildItem _inbox -Recurse -Filter *.pdf
```

查看摄入脚本会做什么：

```powershell
python scripts\literature_ingest.py --limit 5
```

查看解析 ledger 状态，可直接打开：

```text
parse_ledger.json
```

当前已验证状态是 140 条 `succeeded`。如果新增文献摄入后，会出现新的 `pending` 条目。

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
- `/works/:id` — 文献详情（编辑元数据、查看 content.md、管理关系）
- `/duplicates` — 去重确认（决策按钮、localStorage 持久化）
- `/relations` — 关系管理（新增、删除）
- `/metadata` — 元数据抽取审核（风险分级、原文预览、证据定位、人工编辑、审核回填）
- `/classification` — 分类标签审核（primary_doc_type、risk_domain、method_tags 等）
- `/intake` — 采集候选审核（resolution、review_status、promote）
- `/inbox` — Inbox 摄入 dry-run 预览与确认
- `/topics` — 采集主题管理（成熟度转换、mapped_tags）

### 7. 元数据审核与重抽

当前元数据抽取结果保存在 `metadata_extractions`，不会直接覆盖 `works` 稳定层。推荐流程是先在 SPA 的 `/metadata` 页面审核，再按需要回填。

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
| GET | `/api/metadata/{ext_id}` | 元数据抽取详情 |
| PATCH | `/api/metadata/{ext_id}/review` | 审核抽取结果；人工编辑字段会提升为可回填来源 |
| POST | `/api/metadata/apply-approved` | 回填已批准且未应用的抽取结果 |
| POST | `/api/metadata/batch-approve-low-risk` | 批量批准低风险 pending 记录 |
| GET | `/api/metadata/agent/queue` | agent 修复队列，按风险排序并返回错误模式聚类 |
| POST | `/api/metadata/{ext_id}/supersede` | 使用外部提供的替换字段创建 superseding extraction |
| POST | `/api/metadata/{ext_id}/quarantine` | 从元数据审核页隔离文献 |
| GET | `/api/classification/tags/{work_id}` | 获取文献分类标签 |
| POST | `/api/classification/tags/{work_id}` | 创建分类标签 |
| POST | `/api/classification/tags/{work_id}/batch` | 批量创建分类标签 |
| DELETE | `/api/classification/tags/{tag_id}` | 删除分类标签 |
| PATCH | `/api/classification/tags/{tag_id}/review` | 审核分类标签 |
| GET | `/api/classification/vocab` | 分类词汇表（primary_doc_type、reading_lane 等） |
| GET | `/api/classification/extractions` | 分类抽取列表（按状态/风险筛选） |
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
| POST | `/api/intake/collect` | 按主题/显式 ID 发起采集 |
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
- 不要手动移动 `works` 下的 PDF；让摄入脚本维护 DB、index、ledger 的一致性。
- `_inbox` 是临时入口，`works` 才是永久存储。
- `views` 是自动生成视图，后续应由脚本生成，不建议手动维护。
- 解析失败或坏源文件进入 `_quarantine` 或 `_archive`，不要直接删除。
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
- `scripts\backfill_risk.py`：为已有元数据抽取记录回填风险等级、分数和原因
- `scripts\run_api.py`：启动 FastAPI 后端服务

document-parser 工程中的历史/解析脚本：

- `D:\06_tools\document-parser\scripts\literature_inventory.py`
- `D:\06_tools\document-parser\scripts\literature_migrate.py`
- `D:\06_tools\document-parser\scripts\literature_batch_parse.py`
- `D:\06_tools\document-parser\scripts\literature_cleanup_bad_sources.py`

这些历史脚本已经完成 Phase 0、Phase 2、Phase 2b、Phase 2c。日常新增文献优先使用本目录下的 `scripts\literature_ingest.py`。
