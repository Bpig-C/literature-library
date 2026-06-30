# 文档治理说明

> 状态：当前权威文档
> 更新时间：2026-06-29

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

- `README.md`：操作者入口与日常命令。
- `TECHNICAL_OVERVIEW.md`：系统架构、不变量和当前限制。
- `FUTURE_WORK_PLAN.md`：当前路线图与 V1.1+ 待办队列。
- `docs/PROJECT_HISTORY.md`：已完成阶段、历史路线和旧判断的汇总入口。
- `docs/architecture/README.md`：架构文档索引与维护规则。
- `docs/workflows/README.md`：业务流程文档索引与维护规则。
- `docs/superpowers/README.md`：dated specs/plans/reviews 的索引和状态规则。
- `scripts/README.md`：脚本生命周期与操作命令。
- `web/README.md`：前端开发与产品界面说明。

## 发布前文档门禁

发布前运行文档漂移检查，并逐条分类命中结果：

```powershell
rg -n "parse_ledger|literature_healthcheck|D:\\\\06_tools\\\\document-parser|18200|18201|scripts/_|待确认|未实现|待评审" README.md TECHNICAL_OVERVIEW.md FUTURE_WORK_PLAN.md docs scripts web -S
```

允许出现的命中：

- 明确描述历史工作的 specs、plans、reviews。
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
