# 文档总目录

> 状态：当前索引
> 更新时间：2026-07-05

这里是项目文档体系的总入口。README 只保留项目首页和核心概念；具体使用、协作、路线、历史和治理从这里分流。

## 先按你的角色进入

| 角色 | 首选文档 | 用途 |
|------|----------|------|
| 浏览器用户 | [manuals/user-manual.md](manuals/user-manual.md) | 页面入口、日常流程、审核与模板操作 |
| CLI/自动化操作者 | [manuals/cli-manual.md](manuals/cli-manual.md) | 脚本、API、批处理、测试和健康检查 |
| Agent/协调者 | [manuals/agent-manual.md](manuals/agent-manual.md) | agent 边界、任务派发、两轮审核、交接格式 |
| 新接手项目的人 | [HANDOVER_GUIDE.md](HANDOVER_GUIDE.md) | 30 秒速览、当前状态、页面清单、遗留问题 |
| 规划下一步的人 | [FUTURE_WORK_PLAN.md](../FUTURE_WORK_PLAN.md) | 当前路线图、暂缓项、下一步候选 |
| 查问题状态的人 | [USER_ISSUES.md](../USER_ISSUES.md) | 用户问题、修复状态、验收记录 |
| 查历史证据的人 | [PROJECT_HISTORY.md](PROJECT_HISTORY.md) | 已完成阶段、旧判断、历史路线 |

## 当前权威文档

| 文档 | 职责 |
|------|------|
| [README.md](../README.md) | 项目首页、目录结构、核心概念、文档导航 |
| [manuals/README.md](manuals/README.md) | 三类使用手册索引 |
| [TECHNICAL_OVERVIEW.md](../TECHNICAL_OVERVIEW.md) | 系统架构、不变量、数据边界 |
| [FUTURE_WORK_PLAN.md](../FUTURE_WORK_PLAN.md) | 未完成路线图和优先级 |
| [USER_ISSUES.md](../USER_ISSUES.md) | 问题状态和验收 |
| [HANDOVER_GUIDE.md](HANDOVER_GUIDE.md) | 交接与快速接手 |
| [DOCUMENT_GOVERNANCE.md](DOCUMENT_GOVERNANCE.md) | 文档状态、归档和发布前门禁 |
| [architecture/README.md](architecture/README.md) | 架构文档索引 |
| [workflows/README.md](workflows/README.md) | 业务流程文档索引 |
| [superpowers/README.md](superpowers/README.md) | 当前 specs/plans/reviews 索引和状态规则 |
| [_archive/README.md](_archive/README.md) | 归档文档索引 |

## 专题文档

| 文档 | 何时阅读 |
|------|----------|
| [discovery-agent-protocol.md](discovery-agent-protocol.md) | 派 agent 执行发现检索和回填 hits |
| [methodology/classification-methodology.md](methodology/classification-methodology.md) | 查分类方法论、标签语义和研究分类规则 |
| [maintain_doc/mineru-ops.md](maintain_doc/mineru-ops.md) | 查 MinerU 运维和旧解析链路回退参考 |

## 写文档放哪里

| 你要写什么 | 放哪里 |
|------------|--------|
| 用户页面怎么用 | `docs/manuals/user-manual.md` |
| CLI/API/测试怎么跑 | `docs/manuals/cli-manual.md` 和 `scripts/README.md` |
| agent 如何协作、派发、审核 | `docs/manuals/agent-manual.md` |
| 架构事实、不变量、数据边界 | `TECHNICAL_OVERVIEW.md` 或 `docs/architecture/` |
| 流程图和业务链路 | `docs/workflows/` |
| 当前未完成计划 | `FUTURE_WORK_PLAN.md` |
| 用户问题与修复验收 | `USER_ISSUES.md` |
| 已完成阶段总结 | `docs/PROJECT_HISTORY.md` |
| 阶段性计划、审核、结果 | `docs/superpowers/`，完成或取代后归档到 `docs/_archive/` |

## 不要这样做

- 不要把新的长期说明散落到 `docs/` 根目录，除非它是当前权威入口。
- 不要把历史计划当作当前任务说明；历史材料默认只作证据。
- 不要在 README 复制三类手册的大段内容；README 只保留摘要和链接。
- 不要新增 `docs/plans/`、`docs/reviews/`、`docs/uperpowers/` 这类散落目录；阶段性材料统一走 `docs/superpowers/`。
