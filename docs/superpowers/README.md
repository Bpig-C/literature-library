# Superpowers 规格、计划与审核索引

> 状态：当前索引
> 更新时间：2026-06-29

本目录保存文献库的执行治理轨迹，包括带日期的设计规格、实施计划和第三方审核报告。这些文件都是有价值的证据，但多数文档在对应阶段结束后会转为历史记录。

判断当前行为时，应优先核对代码、测试、`scripts/healthcheck_library.py` 和 `docs/DOCUMENT_GOVERNANCE.md` 中列出的当前有效文档。

## 目录角色

| 目录 | 角色 | 当前性规则 |
|---|---|---|
| `specs/` | 设计规格和审核指导。 | 只有被当前索引或当前路线图指向的带日期规格，才可视作当前依据。 |
| `plans/` | 任务拆解和阶段实施计划。 | 已完成计划是历史记录；不要把未勾选任务框当作当前事实。 |
| `reviews/` | 审核报告、整改方案/结果、交接文档和发布评审。 | 较新的 review 在包含验证证据时，可取代旧 finding。 |

## 当前发布证据

- `reviews/2026-06-29-v1-final-publication-review.md`：独立 V1 发布审查；最初为“有条件通过”，等待 P1 阻断项清除。
- `reviews/2026-06-29-v1-final-publication-p1-remediation.md`：P1 整改结果，将 V1 阻断状态升级为“通过”。
- `specs/2026-06-29-three-chain-runbook.md`：CLI/API/UI 三链路验证手册。
- `specs/2026-06-28-three-chain-completeness-plan.md`：三链路完整性设计和验收矩阵。使用时应结合后续整改 review，因为旧段落可能描述整改前状态。

## 历史但仍有价值

- 早期 parser、collector、Phase B/C/D 和全项目审核计划属于历史实施记录。
- 带日期 specs/plans 中对 `parse_ledger.json`、自部署 MinerU 端口或 `document-parser` 的旧引用，通常是在描述 V1 前迁移路径。不要把它们复制到当前操作文档中。

## 维护规则

新增 review 或 plan 时：

- 文件名包含日期。
- 标明状态：`当前有效`、`历史记录`、`已取代` 或 `草案`。
- 尽量链接实现 commit 或验证命令。
- 如果新文档改变了当前发布证据，必须同步更新本 README。
