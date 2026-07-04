# 使用手册入口

> 状态：当前索引
> 更新时间：2026-07-05

本目录按使用者角色维护当前操作手册。README 仍是项目总入口；这里负责把“人怎么点界面、脚本怎么跑、agent 怎么协作”拆开，避免三类说明混在一起。

如果你不确定某份文档该看或该写到哪里，先回到 [文档总目录](../README.md)。

## 三类手册

| 手册 | 面向对象 | 回答的问题 |
|------|----------|------------|
| [用户手册](user-manual.md) | 主要通过浏览器 SPA 使用文献库的人 | 页面在哪里、日常流程怎么走、哪些动作需要人工审核 |
| [CLI 与自动化手册](cli-manual.md) | 本地命令操作者、CI/自动化脚本、需要批处理的 agent | 环境怎么启动、脚本怎么跑、验证命令是什么 |
| [Agent 协作手册](agent-manual.md) | Codex/opencode/本地模型 agent 及派发子 agent 的协调者 | agent 能做什么、不能做什么、怎么交接、怎么做两轮审核 |

## 维护原则

- 用户流程变化时，先更新 `user-manual.md`，再按需更新 README 的页面清单。
- CLI 参数、测试命令或批处理入口变化时，先更新 `cli-manual.md` 和 `scripts/README.md`。
- agent 权限边界、交接格式、审核轮次或任务派发方式变化时，先更新 `agent-manual.md` 和相关协议文档。
- 新增、拆分或合并手册时，同步更新 `docs/README.md` 和根 `README.md` 的文档入口。
- 历史完成记录仍写入 `docs/PROJECT_HISTORY.md`；未来计划仍写入 `FUTURE_WORK_PLAN.md`；问题和验收状态仍写入 `USER_ISSUES.md`。
