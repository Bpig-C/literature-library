# 业务流程图

> 最后更新：2026-07-17
> 范围：用户浏览器操作、智能体 CLI 操作、API 自动化操作，以及跨 `web`、`api`、`collector`、`parser`、`scripts` 的协作。
> ⚠️ 流程图已升级为 three.js 交互导览：**[scholar-os-architecture.html](../architecture/scholar-os-architecture.html)**（流程 A = 本地入库路径，流程 B = 发现检索路径，动画逐步播放，节点可点击查看职责）。原 7 张 SVG 流程图已归档至 `docs/_archive/architecture/diagrams-2026-06/`，仅作历史快照；本文保留流程的文字契约部分。

## 总览

这张总览按代码事实区分两个层次：

- **技术入库点**：`ingest` 或 `collector -> ingest_bridge -> ingest` 写入 `works`、`source_files`，并创建 `literature_parse_runs(pending)`。从数据库角度，这时已经进入文献库。
- **SHA256 精确重复**：在 ingest 内部硬拦截，重复文件直接归档到 `_duplicates/exact_sha256`，不进入后续流程。
- **标题重复治理**：ingest 会生成 Jaccard 标题相似候选写入 `duplicate_groups`/`duplicate_candidates`，但不阻塞入库。审核可在摄入后或元数据回填 title 后迭代进行。
- **元数据/分类抽取门禁**：`literature_parse_runs.status='succeeded'` 且存在 `content_md_path`，与去重审核状态无关。

## 流程一：采集候选到正式文献

> 图示：交互导览「流程 B」。边界：collector 不直接写 `works`；批准后的候选经 `ingest_bridge` 进入同一个 ingest 核心链路。

## 流程二：用户浏览器摄入新 PDF

> 图示：交互导览「流程 A」。

## 流程三：标题重复治理

> 图示：交互导览架构总览中 works → 去重治理 旁路。

## 流程四：解析触发与 content.md 生成

> 图示：交互导览「解析 PARSE」分区。

## 流程五：元数据/分类抽取与审核

> 图示：交互导览「AI 抽取 / 审核 REVIEW」分区。

#### 5.1 元数据模板动态链路

元数据字段模板的事实源是 `templates/templates.json`，运行时由 `api/metadata_template.py` 合并默认模板和自定义模板。三条入口必须保持一致：

| 入口 | 用户/agent 行为 | 写入点 | 门禁 |
|------|-----------------|--------|------|
| UI 模板维护 | 用户在 `/templates` 编辑元数据字段 | `templates/templates.json` | 保存前由 `api/routes/templates.py` 校验字段结构 |
| UI 审核重抽 | 用户在 `/metadata` 编辑字段、点“重抽”或“复制” | `metadata_extractions` 新记录 + supersede 链 | 预览确认后才写库；批准后才可回填 `works` |
| Agent/CLI 批量处理 | agent 读取模板定义并调用 `literature_metadata_extract.py` / `literature_metadata_rerun.py` | `metadata_extractions` | `--fields` 校验模板字段白名单；不绕过人工审核 |

界面的“复制 prompt”只用于单条降级处理。批量 agent 不应从界面复制 prompt，而应直接按 `README.md` §9 和 `scripts/README.md` 调用 CLI/API。

## 流程六：主题驱动发现检索

> 图示：交互导览「流程 B」前半段。边界：Discovery 是"检索计划与命中证据池"，不直接写 works/intake/ontology；accept 后经唯一桥梁函数进入 intake 候选池，再走标准闸门链路。

#### 6.1 三模块关系概要

| 模块 | 角色 | 数据表 | 核心操作 |
|------|------|--------|----------|
| Topic Gate | **前置输入源** & 成熟度管理 | collection_topics | 管理 query_def、触发 plan/run |
| Discovery | 受约束的发现检索 | discovery_runs + discovery_hits | Agent 回填 hits、人工审核 accept/reject |
| Intake | 候选审核闸门 | intake_candidates | light_gate → heavy_gate → A2 review → promote |

**关键理解**：Topic Gate 不是后置分类器，而是 Discovery 的结构化输入来源。

#### 6.2 推荐数据流

```
TopicsReview (/topics) 创建/选择 topic
  ↓ topic_id + query_def
POST /api/discovery/plan 或 /api/discovery/composite-plan
  ↓ search_plan_json
POST /api/discovery/run → discovery_runs
  ↓ Agent 按 plan 执行检索
POST /api/discovery/runs/{id}/hits → discovery_hits
  ↓ 用户在 DiscoveryReview (/discovery) 审核
POST /api/discovery/hits/{id}/accept → accept_hit_to_intake()
  ↓ intake_candidates (resolution='pending', review_status='pending')
  ↓ light_gate → heavy_gate → A2 review (approved)
POST /api/intake/promote → ingest_bridge → works
```

#### 6.3 支持的输入模式

| 模式 | 触发方式 | 说明 |
|------|----------|------|
| topic | TopicsReview → 生成方案 | 基于 topic.query_def 生成计划 |
| name | 手动输入名称 | 按模型名/系统名检索 |
| title | 手动输入标题关键词 | 按标题短语检索 |
| url | 手动输入 URL | 创建 manual hit |
| composite (V1.2) | 复合表单多字段输入 | names+titles+authors+institutions+keywords+known_urls+... 组合查询 |

#### 6.4 硬约束（V1.1/V1.2 不变）

- Agent 只能回填 discovery_hits
- 不自动 accept、promote、写 works、改 ontology vocab、下载 PDF
- Hit 只通过 POST /api/discovery/runs/{id}/hits 回填
- Accept 后只创建 intake_candidates(resolution='pending')
- Title-only hit 不能批量接受
- 已知 URLs 仅作 source_hint，不自动创建 hit
- DOI/arXiv/GitHub 不作为自动 discovery mode

#### 6.5 与 Collect 的区别

| 维度 | Discovery | Collect |
|------|-----------|---------|
| 目的 | 从开放网络**检索发现**未知文献 | 按**已知 ID** 采集已有文献 |
| 输入 | 关键词/名称/多信号组合 | arXiv ID / GitHub URL / DOI |
| 输出 | discovery_hits（证据池） | 直接进入 intake_candidates |
| 审核 | 必须人工 accept | 经 gate 后 review |
| 自动化程度 | Agent 执行检索 | 半自动采集 |
| 典型场景 | "找关于 X 的所有相关论文" | "采集 arXiv:xxxx 这篇论文" |

#### 6.6 替代路径：Direct Collect

用户可以跳过 Discovery，直接从 Topic 发起 Collect：
```
TopicsReview → POST /api/intake/collect → intake_candidates
```
这条路径绕过 Discovery，直接进入 Intake 候选池。适用于已知精确 ID 的场景。
