# 业务流程图

> 最后更新：2026-06-29  
> 范围：用户浏览器操作、智能体 CLI 操作、API 自动化操作，以及跨 `web`、`api`、`collector`、`parser`、`scripts` 的协作。

## 总览

![业务流程总览](../architecture/diagrams/business-overview.svg)

这张总览按代码事实区分两个层次：

- **技术入库点**：`ingest` 或 `collector -> ingest_bridge -> ingest` 写入 `works`、`source_files`，并创建 `literature_parse_runs(pending)`。从数据库角度，这时已经进入文献库。
- **SHA256 精确重复**：在 ingest 内部硬拦截，重复文件直接归档到 `_duplicates/exact_sha256`，不进入后续流程。
- **标题重复治理**：ingest 会生成 Jaccard 标题相似候选写入 `duplicate_groups`/`duplicate_candidates`，但不阻塞入库。审核可在摄入后或元数据回填 title 后迭代进行。
- **元数据/分类抽取门禁**：`literature_parse_runs.status='succeeded'` 且存在 `content_md_path`，与去重审核状态无关。

## 流程一：采集候选到正式文献

![采集候选到正式文献](../architecture/diagrams/flow-collector-promote.svg)

> 边界：collector 不直接写 `works`；批准后的候选经 `ingest_bridge` 进入同一个 ingest 核心链路。

## 流程二：用户浏览器摄入新 PDF

![用户浏览器摄入新 PDF](../architecture/diagrams/flow-inbox-ingest.svg)

## 流程三：标题重复治理

![标题重复治理](../architecture/diagrams/flow-dedup.svg)

## 流程四：解析触发与 content.md 生成

![解析触发与 content.md 生成](../architecture/diagrams/flow-cli-parse.svg)

## 流程五：元数据/分类抽取与审核

![元数据/分类抽取与审核](../architecture/diagrams/flow-review.svg)
