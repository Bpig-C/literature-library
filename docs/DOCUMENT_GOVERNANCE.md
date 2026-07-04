# 文档治理说明

> 状态：当前权威文档
> 更新时间：2026-07-05

本仓库同时保存“当前操作文档”和“历史设计/审核证据”。不要把所有带日期的文档都当成当前事实；当前行为必须以代码、测试、当前数据库健康检查和当前有效文档共同验证。

## 文档状态

新增长期文档时，建议显式标注下列状态：

| 状态 | 含义 | 维护动作 |
|---|---|---|
| `当前权威` | 当前操作、架构或维护权威。 | 发布前必须与代码同步。 |
| `当前索引` | 指向当前有效文档与历史文档的索引。 | 新增、归档、取代文档时同步更新。 |
| `历史记录` | 已完成的计划、审核或审计轨迹。可作背景，不具当前约束力。 | 除非补状态说明，不要为了“更新事实”重写历史记录。 |
| `已取代` | 已被新文档或实现取代。 | 标明替代文档或替代代码入口。 |
| `回退参考` | 非默认路径，但可用于回滚或少数特殊场景。 | 必须明确标注，避免被误用为日常流程。 |
| `已归档` | 已退出当前路径。 | 放入 `_archive/`、`scripts/_archive/` 或有说明的 legacy 目录。 |
| `草案` | 尚未接受的草案。 | 不可单独作为发布证据。 |

## 当前维护地图

- `README.md`：项目首页、核心概念和文档导航；不承载全部使用细节。
- `docs/README.md`：文档体系总目录，按角色、职责和写入位置分流。
- `docs/manuals/README.md`：三类使用手册索引。
- `docs/manuals/user-manual.md`：浏览器用户手册，维护 UI 页面、日常流程、人工审核边界。
- `docs/manuals/cli-manual.md`：CLI/自动化手册，维护脚本、API、测试、健康检查和批处理命令。
- `docs/manuals/agent-manual.md`：Agent 协作手册，维护 agent 边界、派发方式、两轮审核和交接格式。
- `TECHNICAL_OVERVIEW.md`：系统架构、不变量和当前限制。
- `FUTURE_WORK_PLAN.md`：当前路线图与 V1.1+ 待办队列。
- `USER_ISSUES.md`：用户问题、修复状态与验收记录。
- `docs/HANDOVER_GUIDE.md`：当前交接、页面清单、关键遗留和最新审计线索。
- `docs/PROJECT_HISTORY.md`：已完成阶段、历史路线和旧判断的汇总入口。
- `docs/architecture/README.md`：架构文档索引与维护规则。
- `docs/workflows/README.md`：业务流程文档索引与维护规则。
- `docs/superpowers/README.md`：dated specs/plans/reviews 的索引和状态规则。
- `docs/_archive/README.md`：已归档文档索引；只作历史查证入口。
- `scripts/README.md`：脚本生命周期与操作命令。
- `web/README.md`：前端开发与产品界面说明。

## 读者分层

| 读者 | 首选入口 | 不应承担的内容 |
|------|----------|----------------|
| 不确定该看哪里的人 | `docs/README.md` | 不替代具体手册和专题文档 |
| 浏览器用户 | `docs/manuals/user-manual.md` | 不写批处理脚本细节，不写 agent 派发规范 |
| CLI/自动化操作者 | `docs/manuals/cli-manual.md` | 不写页面逐步点击说明，不写历史路线 |
| Agent/协调者 | `docs/manuals/agent-manual.md` | 不替代具体协议文档，不记录全部历史完成流水 |
| 项目接手者 | `docs/HANDOVER_GUIDE.md` | 不作为路线图，不堆所有命令细节 |
| 规划者 | `FUTURE_WORK_PLAN.md` | 不记录已完成实施细节 |
| 审核/追溯者 | `docs/PROJECT_HISTORY.md`、`docs/superpowers/README.md` | 不作为当前操作入口 |

新增当前操作说明时，先判断读者角色，再放入对应手册。README 只链接和摘要，不复制大段正文。

## 发布前文档门禁

发布前运行文档漂移检查，并逐条分类命中结果：

```powershell
rg -n "parse_ledger|literature_healthcheck|D:\\\\06_tools\\\\document-parser|18200|18201|scripts/_|待确认|未实现|待评审" README.md TECHNICAL_OVERVIEW.md FUTURE_WORK_PLAN.md docs scripts web -S
```

允许出现的命中：

- 明确描述历史工作的 specs、plans、reviews，尤其是 `docs/_archive/` 下的归档材料。
- 已标注 `fallback` 且说明不是默认路径的文档。
- legacy/fallback 分支中的源码注释。

active 文档中不允许出现的命中：

- 把 `parse_ledger.json` 当作当前状态源来读写的说明。
- 把 `D:\06_tools\document-parser` 当作默认解析路径的说明。
- 把 `scripts/literature_healthcheck.py` 当作当前健康检查入口的说明。
- 留在 `scripts/` 根目录下、看起来像 active 入口的 `scripts/_*.py` 一次性脚本。

## 脚本生命周期

active 脚本应直接位于 `scripts/` 下，并在 `scripts/README.md` 中说明。

一次性脚本或阶段性脚本必须二选一：

- 移到 `scripts/_archive/` 并加简短说明；
- 若是根级 legacy artifact，则移到 `_archive/`。

不要让新的 `scripts/_*.py` 文件长期留在 `scripts/` 根目录，看起来像当前入口。

## 当前不变量

- SQLite（`literature.sqlite`）是逻辑事实源。
- 解析状态以 `literature_parse_runs` 为准；`parse_ledger.json` 仅为历史产物。
- 文件移动必须同步数据库路径与 `source_files.status`。
- 源文件不直接删除；统一走归档或隔离。
- collector 晋升必须经过 `collector.ingest_bridge`，除非有明确记录的例外。
- parser 执行必须经过 `parser/core/mineru/router.py::route_and_parse`。
