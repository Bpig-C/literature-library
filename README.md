# 文献库项目说明

本目录是本地文献管理系统的数据根目录，用来保存已经迁移、去重、解析、抽取和审核后的博士研究文献库。项目服务于目标错误泛化、LLM 安全性评估等研究方向。

README 是项目首页和导航页，不再承载完整操作手册。具体流程按角色分流到三类手册。

## 当前状态

当前主链路已经打通：

```text
发现检索 / 本地 PDF
  -> 候选审核
  -> 正式入库 works
  -> 解析
  -> 元数据抽取
  -> 分类抽取
  -> 人工审核
  -> 回填稳定层
  -> 引用导出/综述矩阵（已批准文献）
```

核心状态：

- V1 基础设施、V1.1 前端端到端主流程、V1.2 composite 发现检索、V1.3 知识闭环已完成。
- 主线阶段一（引用导出/综述矩阵）与阶段二（驾驶舱）已于 2026-07-18 完成。
- FastAPI 后端默认端口 `19527`，Vue 3 前端默认端口 `19528`。
- 解析状态以 SQLite `literature_parse_runs` 表为唯一权威。
- 元数据模板已接入真实抽取链路：`/templates` 编辑 `templates/templates.json`，CLI/API/字段级重抽/审核页共同读取 `api/metadata_template.py` loader。
- AI 抽取和发现检索都必须经过人工审核门禁，不直接污染 `works` 稳定层。

## 长期维护文档

完整文档地图见 [docs/README.md](docs/README.md)。长期维护入口如下：

| 文档 | 职责 |
|---|---|
| [用户手册](docs/manuals/user-manual.md) | 浏览器页面怎么用，包括 `/ingest`、`/pipeline`、`/metadata`、`/templates` 等 |
| [CLI 与自动化手册](docs/manuals/cli-manual.md) | 命令行、批处理、API 自动化、测试、健康检查 |
| [Agent 协作手册](docs/manuals/agent-manual.md) | Codex/opencode/本地模型 agent 的边界、派发模板和两轮审核要求 |
| [项目交接指南](docs/HANDOVER_GUIDE.md) | 新会话 30 秒接手、页面清单、当前队列、红线约定 |
| [未来工作计划](FUTURE_WORK_PLAN.md) | 只记录尚未完成或暂缓的任务 |
| [用户问题清单](USER_ISSUES.md) | 用户提出的问题、修复状态和验收记录 |
| [项目历史](docs/PROJECT_HISTORY.md) | 已完成阶段、旧判断和历史证据 |
| [技术总览](TECHNICAL_OVERVIEW.md) | 架构、不变量、数据边界 |
| [文档治理说明](docs/DOCUMENT_GOVERNANCE.md) | 文档状态、归档规则、发布前门禁 |
| [发现检索协议](docs/discovery-agent-protocol.md) | discovery agent 的执行协议和回填格式 |

维护规则：

- 新用户流程写入用户手册。
- 新命令、脚本参数、API 自动化写入 CLI 与自动化手册，并同步 `scripts/README.md`。
- agent 派发、权限边界、长任务协作写入 Agent 协作手册。
- 已完成事实追加项目历史；未完成计划保留在未来工作计划。
- README 只保留项目入口、核心事实和文档导航。

## 快速启动

日常启动后端：

```powershell
uv run python scripts\run_api.py
```

启动前端：

```powershell
cd web
npm run dev
```

打开：

- 前端：`http://localhost:19528`
- API 文档：`http://127.0.0.1:19527/docs`

更多命令见 [CLI 与自动化手册](docs/manuals/cli-manual.md)。

## 目录架构

```text
D:\02_academic\doctoral\literature_library
  _inbox\              # 新 PDF 的临时投递入口
  _duplicates\         # 精确重复文件归档处
  _quarantine\         # 失败、坏源、元数据存疑文件暂存处
  _archive\            # 已归档的历史中间产物和备份
  works\               # 文献永久存储区
  views\               # 自动生成的只读视图（历史，已被 SPA 替代）
  scripts\             # 本地维护脚本
  api\                 # FastAPI 后端
  web\                 # Vue 3 前端 SPA
  tests\               # 测试
  templates\           # 可审查模板资产
  literature.sqlite    # 主数据库
  pyproject.toml       # Python 项目配置
  index.json           # 前端/脚本可读的文献索引
```

`parse_ledger.json` 已废弃并归档；解析状态以 `literature_parse_runs` 表为准。

## 核心概念

`_inbox` 是新文献入口，不是永久存储位置。本地 PDF 可以通过前端 `/ingest` 或 CLI dry-run 预览后确认摄入。

`works` 是稳定物理存储区。每篇文献有一个 `work_id`，例如 `W-arxiv-2501.17805` 或 `W-sha-d35373840d97`。PDF、解析结果、笔记和分析结果都围绕该目录组织。

`literature.sqlite` 是逻辑关系中心，记录 work、source file、解析任务、抽取结果、重复候选、分类标签和文献关系。主题、标签、关系不靠物理文件夹表达。

`templates/templates.json` 是当前可编辑模板资产。元数据字段模板由 `/templates` 页面维护，并通过 `api/metadata_template.py` 接入真实抽取、字段级重抽和审核页动态渲染。

## 主要页面

| 页面 | 用途 |
|---|---|
| `/` | 待办概览和流程入口 |
| `/pipeline` | 收件箱、解析、元数据、分类四阶段流水线 |
| `/ingest` | 新文献入库，包含发现检索和本地上传入口 |
| `/inbox` | 收件箱 dry-run 预览与确认（仍独立可达，导航已并入 `/ingest`） |
| `/topics` | 采集主题管理 |
| `/discovery` | 审核 agent 回填的发现检索命中 |
| `/intake` | 审核采集候选并 promote |
| `/works` | 浏览正式文献库，导出 BibTeX/RIS/综述矩阵 |
| `/works/:id` | 单篇文献工作台 |
| `/metadata` | 元数据抽取审核和字段级重抽 |
| `/classification` | 分类抽取审核 |
| `/templates` | 模板资产管理 |
| `/duplicates` | 重复文献候选处理 |
| `/relations` | 文献关系管理 |

页面级操作说明见 [用户手册](docs/manuals/user-manual.md)。

## 重要边界

- 不要重跑 inventory/migration，除非明确要从原始 `literature_read` 重新构建。
- 不要手动移动 `works` 下的 PDF；摄入、归档、隔离、恢复必须同步数据库。
- `_inbox` 是临时入口，`works` 才是永久存储。
- 新文献摄入后默认只是 `pending`，不会自动启动解析。
- 元数据和分类抽取结果必须先进入审核队列，不能绕过人工审核直接写稳定层。
- 发现检索 agent 只能回填 hits，不能 accept、promote、下载 PDF 或写 `works`。
- 分类模板发布流程仍暂缓；当前不要把 QA-004 和元数据模板治理混在同一阶段。

## 安全约定

- `.env` 已被 `.gitignore` 排除，不提交到 git 仓库。
- 脚本和 agent 只应打印环境变量的键名，不要打印值。
- 密钥建议放在用户级环境变量或密钥管理工具中，而不是项目级 `.env`。
- API 端点不暴露敏感配置；CORS 仅允许本地前端来源。

## 文档收尾检查

文档结构变更后运行：

```powershell
python scripts\check_docs.py
```

如果整理了交接、路线图或 README，建议再按 [Agent 协作手册](docs/manuals/agent-manual.md) 的“状态理解复核模板”派一个只读 agent 复核项目状态，避免文档漂移。
