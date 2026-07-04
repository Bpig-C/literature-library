# Agent 协作手册

> 状态：当前权威
> 更新时间：2026-07-05
> 面向对象：Codex/opencode/本地模型 agent，以及负责派发子 agent 的协调者

本项目的 agent 不是单人脚本执行器，而是多人协作式维护者。默认要求：先读当前文档，明确边界，实施后至少两轮审核，最后同步代码、测试和文档。

## 开始前必读

按任务类型读取：

| 任务类型 | 必读文档 |
|----------|----------|
| 快速了解项目 | `README.md`、`docs/HANDOVER_GUIDE.md` |
| 用户界面流程 | `docs/manuals/user-manual.md`、`web/README.md` |
| CLI/批处理/验证 | `docs/manuals/cli-manual.md`、`scripts/README.md` |
| 架构或事实源变更 | `TECHNICAL_OVERVIEW.md`、`docs/architecture/README.md` |
| 路线图和优先级 | `FUTURE_WORK_PLAN.md` |
| 问题状态和验收 | `USER_ISSUES.md` |
| 已完成历史 | `docs/PROJECT_HISTORY.md` |
| 发现检索 agent | `docs/discovery-agent-protocol.md` |

不要把 `docs/_archive/` 下的旧计划当作当前事实；它们只是历史证据。

## 协作边界

通用边界：

- 不能回滚用户或其他 agent 的未授权改动。
- 不能绕过人工审核门禁直接污染稳定层。
- 不能把历史路径、旧脚本或过时方案重新写成当前入口。
- 改功能时必须同步相应的使用手册、路线图或历史记录。

发现检索 agent 边界：

- 只能读取 run plan、执行检索、回填 `discovery_hits`。
- 不能 accept、promote、写 `works`、改 ontology vocab、下载或摄入 PDF。
- 必须遵守 `docs/discovery-agent-protocol.md`。

元数据模板/重抽 agent 边界：

- 批量处理直接读取 `templates/templates.json` 和 `api/metadata_template.py`。
- 不要从前端复制 prompt 作为批量入口；前端复制只用于单条降级。
- 字段级重抽使用 `scripts\literature_metadata_rerun.py --fields ... --rerun` 或对应 API。
- 重抽结果进入 `metadata_extractions` 审计链，不能直接覆盖 `works`。

## 推荐派发方式

中大型任务建议至少拆成三类子 agent：

| 子 agent | 职责 |
|----------|------|
| 实施 agent | 按任务修改代码/文档，提供自测命令 |
| 文档 agent | 分块更新 README、手册、路线图、历史记录或 issue |
| 审核 agent | 独立阅读 diff、复跑关键测试、查文档/代码是否漂移 |

审核至少两轮：

1. 第一轮：代码事实审核。检查实现是否真的满足需求、有没有边界漏洞、测试是否覆盖。
2. 第二轮：文档和交接审核。检查 README、手册、计划、issue、历史记录是否互相一致。

## 交付格式

交付时至少说明：

- 改了哪些文件。
- 解决了哪个用户问题或计划项。
- 跑了哪些验证命令，结果是什么。
- 哪些风险或限制仍然存在。
- 哪些文档已经同步，哪些历史文档只是证据不再维护。

## 状态理解复核模板

每次完成一轮文档整理、交接整理或路线图重排后，建议先派一个只读子 agent 使用下面模板复核项目状态。该 agent 不应修改文件，只输出理解和疑点，用来发现文档漂移。

```text
你是 literature_library 项目的新接手 agent。请只做项目状态理解，不做代码或文档修改。

工作目录：D:\02_academic\doctoral\literature_library

请按顺序读取：
1. README.md
2. docs/README.md
3. docs/HANDOVER_GUIDE.md
4. docs/manuals/agent-manual.md
5. FUTURE_WORK_PLAN.md
6. USER_ISSUES.md
7. docs/PROJECT_HISTORY.md 最近 2026-07-04/05 相关章节

输出：
- 你理解的项目目标和当前主流程
- 当前已完成的关键能力
- 当前下一步最应该做什么，哪些明确暂缓
- 你看到的文档体系结构和每类文档职责
- 你发现的疑点、矛盾或需要复核的地方
- 不要修改任何文件，不要提交，只做状态理解报告
```

## 给下一轮实施 agent 的提示词模板

```text
你是 literature_library 项目的协作 agent。请先读取：
1. README.md
2. docs/HANDOVER_GUIDE.md
3. docs/manuals/agent-manual.md
4. 与本任务相关的 docs/manuals/user-manual.md 或 docs/manuals/cli-manual.md
5. FUTURE_WORK_PLAN.md 和 USER_ISSUES.md 中对应条目

任务目标：
<写清楚本轮只做什么>

非目标：
<写清楚本轮不做什么，例如暂不做 QA-004 分类模板>

要求：
- 先给出你读到的当前事实和风险。
- 如果任务较大，请派发子 agent：实施、文档、审核至少三类。
- 审核至少两轮：一轮代码事实，一轮文档一致性。
- 实施后运行相关测试、healthcheck、前端 build 或说明无法运行的原因。
- 不要回滚其他人的改动，不要绕过人工审核门禁。
- 完成后同步 README/手册/FUTURE_WORK_PLAN/USER_ISSUES/PROJECT_HISTORY 中需要更新的部分。
```

## 文档同步规则

- 新页面或用户流程变化：更新 `docs/manuals/user-manual.md`。
- 新 CLI 参数、脚本或验证命令变化：更新 `docs/manuals/cli-manual.md` 和 `scripts/README.md`。
- agent 边界或派发方式变化：更新本手册和相关协议文档。
- 已完成的重要阶段：追加 `docs/PROJECT_HISTORY.md`。
- 仍未完成或暂缓的方向：更新 `FUTURE_WORK_PLAN.md`。
- 用户提出的问题、修复状态和验收口径：更新 `USER_ISSUES.md`。
