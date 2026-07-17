# 用户手册

> 状态：当前权威
> 更新时间：2026-07-05
> 面向对象：主要通过浏览器页面使用文献库的人

本手册只讲“通过界面怎么用”。如果需要命令行批处理，看 [CLI 与自动化手册](cli-manual.md)；如果要派 agent 做长任务，看 [Agent 协作手册](agent-manual.md)。

## 启动与入口

默认端口：

- 后端：`http://localhost:19527`
- 前端：`http://localhost:19528`

日常使用优先打开 Vue SPA 前端。核心页面：

| 页面 | 用途 |
|------|------|
| `/` | 看待办概览和进入各流程 |
| `/pipeline` | 看收件箱、解析、元数据、分类四阶段流水线 |
| `/ingest` | 新文献入库，包含发现检索和本地上传入口 |
| `/topics` | 管理采集主题 |
| `/discovery` | 审核 agent 回填的发现检索命中 |
| `/intake` | 审核采集候选，确认是否进入文献库 |
| `/works` | 浏览正式文献库 |
| `/works/:id` | 单篇文献工作台 |
| `/metadata` | 审核元数据抽取结果，支持字段级重抽 |
| `/classification` | 审核分类抽取结果 |
| `/duplicates` | 处理重复文献候选 |
| `/relations` | 管理文献关系 |
| `/templates` | 管理模板资产；当前元数据字段可编辑 |

侧边栏按四组组织（2026-07-17 Scholar OS 改版）：

- **工作台**：研究总览 `/`、文献库 `/works`
- **探索与处理**：智能探索 `/discovery`、研究主题 `/topics`、文献入库 `/ingest`、处理流程 `/pipeline`
- **审核与组织**：采集审核 `/intake`、元数据审核 `/metadata`、分类审核 `/classification`、重复项 `/duplicates`、文献关系 `/relations`
- **设置**：抽取模板 `/templates`

另外 `/inbox`（收件箱 dry-run 预览与确认）仍是独立路由、可以直接访问，但侧边栏入口已并入“文献入库” `/ingest`。

## 日常主流程

1. 新文献进入：本地 PDF 走 `/ingest` 的收件箱；开放网络检索走 `/topics` 或 `/discovery`。
2. 候选审核：发现检索命中先在 `/discovery` 审核，采集候选再在 `/intake` 审核。
3. 正式入库：批准后的候选进入 `works`，并产生 pending 解析任务。
4. 解析：在 `/pipeline` 或单篇 `/works/:id` 触发解析。
5. 抽取：解析成功后触发元数据抽取和分类抽取。
6. 人工审核：到 `/metadata` 和 `/classification` 审核结果。
7. 回填应用：只有审核批准后的结果才能回填稳定层。

## 发现检索怎么用

发现检索适合“知道主题、名称、标题或网页线索，但还没有稳定 PDF 或 arXiv ID”的材料。

1. 在 `/topics` 创建或选择主题，或直接进入 `/discovery`。
2. 按 `topic` / `name` / `title` / `url` / `composite` 创建 discovery run。
3. 把 run id 交给本地检索 agent。agent 只负责检索和回填 hits。
4. 回到 `/discovery` 审核 hits。接受后只会创建 intake candidate，不会直接写入 `works`。
5. 到 `/intake` 继续审核、resolve 和 promote。

`composite` 模式可以同时提供名称、标题、作者、机构、关键词、已知 URL、偏好域名和排除词，适合信息碎片较多的模型卡、系统卡、技术报告或项目页。

## 单篇文献工作台怎么用

进入 `/works/:id` 后，按顶部 workflow bar 检查：

- 源文件：确认 PDF 是否存在，必要时上传或下载补齐。
- 解析：触发或查看 MinerU/PyMuPDF 解析状态。
- 元数据：触发抽取，之后去 `/metadata` 审核。
- 分类：触发分类抽取，之后去 `/classification` 审核。

日常单篇处理优先用页面按钮；大批量处理再交给 CLI 或 agent。

## 元数据模板怎么用

元数据模板是当前抽取链路的字段资产。

1. 打开 `/templates`。
2. 在“元数据字段”Tab 查看、编辑或新增字段。
3. 保存后，字段会写入 `templates/templates.json`。
4. 新抽取、字段级重抽、prompt 复制和 `/metadata` 审核表都会读取这份模板。
5. 回到 `/metadata`，自定义字段会出现在审核表里，可编辑、复制 prompt 或发起字段级重抽。

字段 `key` 是系统识别名。保存后不要随意改名；如果确实要改名，应作为模板迁移处理，并让 agent 同步检查历史数据和测试。

## 元数据审核怎么用

在 `/metadata` 中：

- `approved`：候选结果可信，可以进入后续回填。
- `needs_fix`：部分可信，需要人工修正或字段级重抽。
- `rejected`：本次抽取不可信，不回填。

单字段不满意时，优先用字段行旁边的“重抽”。系统会先展示 diff 预览，确认后才写入新记录。智能链路不可用时，再用“复制”拿 prompt 做手动降级处理。

## 重要边界

- AI 抽取结果不会直接覆盖 `works` 稳定层，必须经过人工审核。
- 发现检索 agent 只能回填命中，不会自动接受、入库或下载 PDF。
- 分类模板目前仍是预留/只读方向，当前不要把分类词汇发布流程和元数据模板治理混在一起。
- 源 PDF 不要手动移动或删除；隔离、恢复和归档都应通过页面或脚本维护数据库一致性。
