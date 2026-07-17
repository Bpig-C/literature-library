# 系统架构图

> 最后更新：2026-06-30  
> 范围：`literature_library` 根项目及 `api`、`web`、`collector`、`parser`、`scripts` 子项目。

## 维护边界

这张图是系统级总图，用来回答“谁和谁协作、数据从哪里进出、哪些组件是稳定契约”。内部实现细节分别维护在：

- `api/docs/architecture.md`
- `collector/docs/architecture.md`
- `parser/docs/architecture.md`
- `web/docs/architecture.md`
- `scripts/docs/architecture.md`

## 系统总图

> 2026-07-17 起，系统总图升级为 three.js 交互式 3D 架构图（含架构总览与流程 A/B 动画导览，节点可点击查看职责）：
> **[scholar-os-architecture.html](scholar-os-architecture.html)**（浏览器直接打开即可，three.js 已本地化到 `vendor/`）。
> 原 SVG 总图已归档至 `docs/_archive/architecture/diagrams-2026-06/system-architecture.svg`，仅作历史快照。

## 主流水线视角

```text
Topic Gate (collection_topics + query_def)
  -> Discovery (plan → run → hits → accept)          ← V1.1/V1.2 发现检索层
     -> accept_hit_to_intake() 唯一桥梁
  -> intake_candidates (pending)
  -> ingest / ingest_bridge
  -> 技术入库：works + source_files + literature_parse_runs(pending)
  -> 基础去重/关系/隔离审核（可先做，但不是解析硬门禁）
  -> parser 解析：content.md / content.json
  -> 元数据抽取 -> 元数据审核 -> 回填 works
  -> 可基于回填后的 works.title 重跑标题重复扫描
  -> 分类抽取 -> 分类审核 -> 回填 works + work_classification_tags
```

注意：这是一条推荐治理顺序，不是所有步骤的硬门禁。代码层面，Discovery 是可选前置层——用户也可以跳过它，直接通过 `_inbox` 摄入或 Topic → Collect 路径进入候选池。解析消费 `literature_parse_runs(pending)`；元数据和分类抽取以解析成功并存在 `content_md_path` 为入口条件。去重治理可以在摄入后先做，也可以在元数据回填标题后迭代重扫。

## 运行时组件

| 组件 | 主要目录 | 职责 | 主要契约 |
| --- | --- | --- | --- |
| Vue SPA | `web/` | 浏览器操作入口：文献、详情、去重、关系、元数据、分类、采集、inbox、主题 | 通过 `/api` 调 FastAPI |
| FastAPI | `api/` | 对 UI 和 agent 暴露文献库 API，封装 DB 与文件操作 | `api/routes/*.py` |
| Collector | `collector/` | 发现检索、规范化、下载、门控、候选审核、提升入库 | `discovery` API（plan/run/hits/accept）、`intake` API、采集 CLI、SQLite 表 |
| Parser | `parser/` | PDF/文档解析，输出 `content.md` 和结构化产物 | `parser/core/mineru/*`、可选 Agent API |
| Scripts | `scripts/` | 日常维护、迁移、摄入、解析、抽取、分析、健康检查 | argparse CLI |
| SQLite | `literature.sqlite` | 逻辑关系中心 | `works`、`source_files`、`literature_parse_runs`、`metadata_extractions`、`analysis_runs` 等 |
| 文件区 | `_inbox/`、`works/`、`_archive/`、`_quarantine/`、`_duplicates/`、`_collector_cache/` | 物理 PDF、解析产物、归档、隔离、采集缓存 | 文件路径必须与 DB 同步 |

## 核心约束

- SQLite 是逻辑中心，文件系统只保存物理文件和产物。
- 新 PDF 先进入 `_inbox`，再由 ingest 流程复制到 `works/{work_id}/source`。
- inbox 摄入是可信源旁路，直接写 `works`；collector 摄入必须先落候选，经审核后通过 `ingest_bridge` 复用 ingest 核心。
- **Discovery 是只读发现层**：agent 只能回填 `discovery_hits`，accept 后通过唯一桥梁函数进入 intake 候选池；不自动 promote/写 works/改 ontology/下载 PDF。
- Discovery 与 Collect 边界清晰：前者是"检索计划与命中证据池"（关键词/多信号），后者是"已知 ID 采集"（arXiv/GitHub/DOI）；两者不得互相隐式触发。
- 解析状态以 `literature_parse_runs` 为准，`parse_ledger.json` 属历史产物。
- `MinerU selfdeploy` 是降级兼容路径，当前主链路是 PyMuPDF 本地直抽或 MinerU cloud VLM。
- 模型抽取结果先进入审核表，批准后才回填稳定层。
- 所有删除类操作优先归档或隔离，不直接删除源文件。
