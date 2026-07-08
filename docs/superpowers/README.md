# Superpowers 规格、计划与审核索引

> 状态：当前索引
> 更新时间：2026-07-05

本目录只保留仍需当前维护或最近一轮复核的 superpowers 文档。已完成阶段的规格、计划和审核证据集中归档到 `docs/_archive/superpowers/`，避免后续维护者把旧任务清单或旧 finding 当成当前事实。

判断当前行为时，应优先核对代码、测试、`scripts/healthcheck_library.py`、`docs/README.md`、`docs/DOCUMENT_GOVERNANCE.md` 和 README 中列出的长期维护文档。

## 目录角色

| 目录 | 当前用途 | 规则 |
|---|---|---|
| `specs/` | 新增且仍有效的设计规格和审核指导。 | 当前为空；历史规格在 `docs/_archive/superpowers/specs/`。 |
| `plans/` | 新增且尚未完成的任务拆解和阶段实施计划。 | 当前为空；完成后归档到 `docs/_archive/superpowers/plans/`。 |
| `reviews/` | 最近一轮仍需参考的审核、整改或交接复核。 | 只保留当前最新审核；旧审核在 `docs/_archive/superpowers/reviews/`。 |

## 当前有效审查

- `reviews/2026-07-05-system-calibration.md`：系统定位与使用闭环校准。4 个独立子 agent 审计（文档/流程/数据模型/代码风险）+ 交叉复核，产出系统定位一页纸、日常流程图、字段状态字典、2 周路线图。
- `reviews/2026-07-03-handover-audit.md`：对 2026-07-02/03 交接内容、代码变更和文档一致性的复核记录。

## 历史归档入口

- `docs/_archive/superpowers/specs/`：已完成或已取代的设计规格、验证手册和审查清单。
- `docs/_archive/superpowers/plans/`：已完成或已取代的实施计划、handoff 和任务拆解。
- `docs/_archive/superpowers/reviews/`：历史发布审查、阶段审核、整改结果和实验审计材料。

## 维护规则

新增 review、plan 或 spec 时：

- 文件名包含日期。
- 在文件开头标明状态：`当前有效`、`历史记录`、`已取代` 或 `草案`。
- 尽量链接实现 commit、验证命令或代码入口。
- 阶段完成后，把对应 dated 文档移入 `docs/_archive/superpowers/`，并同步更新本 README 与 `docs/_archive/README.md`。
