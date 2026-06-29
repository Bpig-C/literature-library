# 业务流程图

> 最后更新：2026-06-29  
> 范围：用户浏览器操作、智能体 CLI 操作、API 自动化操作，以及跨 `web`、`api`、`collector`、`parser`、`scripts` 的协作。

## 总览

![业务流程总览](../architecture/diagrams/business-overview.svg)

这张总览按代码事实区分两个层次：

- **技术入库点**：`ingest` 或 `collector -> ingest_bridge -> ingest` 写入 `works`、`source_files`，并创建 `literature_parse_runs(pending)`。从数据库角度，这时已经进入文献库。
- **治理推荐顺序**：摄入后先做一轮基础去重/关系/隔离审核；解析和元数据回填后，可以继续重跑标题候选扫描并补做去重审核。当前代码没有强制“去重已审核”作为解析或抽取门禁；元数据和分类抽取脚本实际门禁是 `literature_parse_runs.status='succeeded'` 且存在 `content_md_path`。
- **去重输入来源**：当前 active 代码里的去重候选主要来自强键、SHA256、标题规范化后的 Jaccard 相似度；没有发现 active 去重逻辑直接读取 `content.md`。但元数据审核可能回填 `works.title`，因此解析/抽取之后再做标题去重重扫是合理的治理动作。
- **新增子项目融入点**：`collector` 是上游候选入口，批准后复用 ingest 链路；`parser` 是摄入后的解析服务，生成后续抽取所需的 `content.md`。

## 流程一：采集候选到正式文献

![采集候选到正式文献](../architecture/diagrams/flow-collector-promote.svg)

> 边界：collector 不直接写 `works`；批准后的候选经 `ingest_bridge` 进入同一个 ingest 核心链路。

## 流程二：用户浏览器摄入新 PDF

![用户浏览器摄入新 PDF](../architecture/diagrams/flow-inbox-ingest.svg)

## 流程三：去重、关系与隔离治理

![去重、关系与隔离治理](../architecture/diagrams/flow-dedup.svg)

## 流程四：解析触发与 content.md 生成

![解析触发与 content.md 生成](../architecture/diagrams/flow-cli-parse.svg)

## 流程五：元数据/分类抽取与审核

![元数据/分类抽取与审核](../architecture/diagrams/flow-review.svg)
