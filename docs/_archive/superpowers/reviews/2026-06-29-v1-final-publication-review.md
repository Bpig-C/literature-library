# 2026-06-29 V1 最终发布审查

> 角色：独立第三方最终审查人。
> 范围：功能闭环、前端产品/设计哲学、文档与维护治理。
> 方法：文档只作为线索；事实以代码、测试、当前数据库 healthcheck 和直接源码检查为准。

## 结论

**有条件通过（CONDITIONAL PASS），尚不建议直接标记为完整 V1 发布通过。**

当前仓库状态未发现 P0：实时文献库 healthcheck 干净，Python 测试通过，parser smoke 收集正常，关键维护脚本可编译，前端生产构建通过。

但在下列 P1 阻断项修复或由项目负责人明确降级之前，我不建议盖“可发布 V1”章。核心原因是：当前数据库虽然干净，但若执行若干正常 UI/API 操作，仍可能重新制造一致性漂移。

> 后续说明：本报告之后的整改结果见 `2026-06-29-v1-final-publication-p1-remediation.md`。该整改报告验证通过后，可取代本文的“有条件通过”结论。

## 审查轮次

- 第一轮：三条独立只读子审查：
  - 功能/API 链路审查。
  - 前端功能与设计哲学审查。
  - 文档与维护治理审查。
- 第二轮：主审查人基于当前代码复核，包含定向源码检查、全量测试/构建/healthcheck，以及对子审查 finding 的冲突消解。

## 已验证命令

```powershell
$env:TMP='D:\02_academic\doctoral\literature_library\.codex_tmp\v1tmp'
$env:TEMP=$env:TMP
.\.venv\Scripts\python.exe -m pytest tests\ -q --basetemp=.codex_tmp\pytest_v1 -p no:cacheprovider
```

结果：**342 passed, 7 skipped, 1 warning**。

```powershell
.\.venv\Scripts\python.exe scripts\healthcheck_library.py --json
```

结果：无 orphan files、phantom DB entries、work dirs without DB rows、status inconsistencies、dangling references 或 repair plan。

```powershell
.\.venv\Scripts\python.exe -m pytest --collect-only -q parser\tests
```

结果：**2 tests collected**。

```powershell
.\.venv\Scripts\python.exe -m py_compile api\path_safety.py scripts\dedup_cleanup.py scripts\healthcheck_library.py
```

结果：通过。

```powershell
npm.cmd run build
```

结果：前端生产构建通过。

## P1 发布阻断项

### P1-01 Quarantine API 会重新制造 source 状态漂移

当前 live DB 是干净的，但正常 quarantine 操作在把文件移入 `_quarantine` 时，没有同步更新 `source_files.status`。

已确认路径：

- `api/routes/works.py:351` 的 `POST /works/{work_id}/quarantine` 会更新 `works.read_status` 和 `source_files.source_path`，但不更新 `source_files.status`。
- `api/routes/works.py:418` 的 restore 会把路径移回，但也没有恢复 `source_files.status`。
- `api/routes/metadata.py:407` 的 metadata quarantine 会移动文件并把 work 标记为 quarantined，但不把 source 标记为 quarantined。
- `api/routes/classification.py:906` 的 classification quarantine 存在同类问题。
- `api/routes/duplicates.py:289` 的 `_move_to_quarantine` 会移动重复隔离文件，但只更新 `source_path`。

风险原因：`scripts/healthcheck_library.py` 明确会把“quarantined work + active source”“active source in _quarantine”“source in _quarantine but status != quarantined”视为一致性问题。因此系统可以在当前通过 healthcheck，但用户执行一次受支持的 UI 操作后变成不健康状态。

建议修复：

- quarantine 端点应把已移动/未移动的 source row 更新为 `status='quarantined'`，并一致设置归档/隔离元数据。
- restore 应把 source 恢复为 `status='active'`。
- metadata/classification quarantine 应委托给 works quarantine nucleus，或完全共享同一套 pre-check 和状态语义。
- 增加测试：执行 quarantine 后运行 `run_healthcheck(...)`，断言无 inconsistencies。

### P1-02 审核页面的 quarantine 语义不一致

`works.quarantine` 会预检查缺失源文件，并在修改 DB 前返回 409；metadata 与 classification quarantine 遇到缺失文件会跳过移动，但仍把 work 标记为 quarantined。

已确认路径：

- 严格路径：`api/routes/works.py:369`。
- 宽松路径：`api/routes/metadata.py:487`、`api/routes/classification.py:975`。

建议修复：所有 quarantine 入口应调用同一个共享函数，并使用同一策略。对治理型工具来说，部分隔离应该是显式状态，而不是偶然副作用。

### P1-03 `needs_better_copy` 存在，但未接入 promote

collector gate 可以产生 `needs_better_copy`，`collector/replace_source.py` 也存在，但 `/api/intake/promote` 会把所有已批准候选都送进 `ingest_bridge.promote`，没有针对“替换隔离 work 的坏源文件”的分支。

已确认路径：

- gate 分类：`collector/gate.py:52`。
- promote 路径：`api/routes/intake.py:137`。
- 替换 helper：`collector/replace_source.py:13`。

次级问题：如果未来直接接入当前 `replace_quarantined_source`，它会插入新的 active source，但不会创建对应的 `literature_parse_runs` pending 行。

建议修复：明确 V1 行为。要么移除/标记 `needs_better_copy` 为后续能力，要么将其接入 promote，并同时创建 parse run 与测试。

### P1-04 前端存在已确认的 V1 UX 问题

已确认问题：

- 嵌套布局：`web/src/App.vue:20` 已经用 `AppLayout` 包住所有路由，但 `web/src/views/IntakeReview.vue:2`、`web/src/views/InboxReview.vue:2`、`web/src/views/TopicsReview.vue:2` 又各自包了一层，可能造成重复侧边栏/布局壳。
- WorkDetail 标题编辑不可靠：`web/src/views/WorkDetail.vue:41` 通过 blur 修改 `work.title`，但 `saveEdit` 提交的是 `web/src/views/WorkDetail.vue:666` 和 `web/src/views/WorkDetail.vue:680` 的 `editForm`。contenteditable 标题未绑定回 `editForm.title`。
- Duplicate quarantine 是高影响操作，会移动文件并隔离组内候选，但 `web/src/views/Duplicates.vue` 缺少二次确认。

建议修复：

- 从 route view 中移除嵌套 `AppLayout`。
- 标题编辑直接绑定 `editForm.title`，或在 blur 时同步更新 `editForm.title`。
- Duplicate quarantine 使用 Naive UI dialog，并显示受影响 work 数量。

## P2 重要后续项

- Classification review 提交整个 edit form，而 metadata review 只提交 diff。需要决定审计日志语义是“提交完整决策状态”还是“提交人工修改字段”，并保持一致。
- WorkDetail 分类标签保存是 delete-then-add，失败时可能留下部分状态。建议改为后端事务式批量端点。
- `GET /api/parse/status?work_id=` 对多源 work 只返回一条 parse row；V1.1 应提供 source 级列表或明确聚合策略。
- Dashboard 尚未展示 metadata/classification/intake 队列压力，因此还不是完整治理控制台。
- `web/README.md` 当时仍是 Vite 默认 README，发布前应替换。
- 多个 active 文档仍引用旧计数或旧脚本名。

## 设计哲学评估

项目已经形成清晰产品形态：**队列优先 -> 证据辅助 -> 人工决策 -> 状态留痕**。

这套哲学适合研究型文献治理系统。当前最强的部分是 metadata review、classification review、duplicate resolution，以及 quarantine/archive 原则。薄弱点是不同审核页面的一致性、危险操作确认、文档生命周期治理。

V1 应把下列原则写入维护不变量：

- SQLite 是逻辑事实源。
- 文件系统移动必须同步 DB 路径与状态。
- 不做破坏性删除；使用 archive/quarantine 并留痕。
- 人工审核动作应可撤销，或明确标记为最终动作。
- 决策旁边应能看到证据。
- collector/parser/ingest 每条链路应保持单一 nucleus，避免重复逻辑。

## 维护文档地图

当时可用的维护文档：

- `README.md`：当前操作者入口和日常流程。当时整体可用，但 ingest 段仍有过期 `parse_ledger.json` 指令。
- `TECHNICAL_OVERVIEW.md`：技术架构与不变量。当时需要刷新：仍把 `scripts/literature_healthcheck.py` 写成 healthcheck 命令，而当前 active checker 是 `scripts/healthcheck_library.py`。
- `FUTURE_WORK_PLAN.md`：未来/更新计划位置，但当时已有旧计数、旧测试总数和 `parse_ledger` 引用。
- `docs/architecture/README.md`：架构文档维护入口。
- `docs/workflows/README.md`：业务流程文档维护入口。
- `docs/workflows/business-flows.md`：业务流图和流程说明。
- `api/docs/architecture.md`、`collector/docs/architecture.md`、`parser/docs/architecture.md`、`scripts/docs/architecture.md`、`web/docs/architecture.md`：子项目架构说明。
- `scripts/healthcheck_library.py`：当前可执行维护/健康检查脚本。
- `_archive/README.md`：根级退役 artifact 的归档说明。
- `parser/_legacy_service/README.md`：parser legacy service 边界说明。

## 文档治理缺口

当时尚无单一权威文档定义：

- 哪些文档是 active；
- 哪些文档是历史实施记录；
- 哪些 specs/plans/reviews 已被取代；
- V1 发布前必须更新哪些文档；
- 旧脚本和临时脚本应如何归档。

已有局部机制有帮助，但不够：

- `_archive/README.md` 解释了部分退役 artifact。
- `parser/_legacy_service/README.md` 解释了退役 parser HTTP 服务。
- `docs/superpowers/plans/` 下部分计划包含历史归档决策。
- 但当时还没有 `docs/DOCUMENT_GOVERNANCE.md`、`docs/README.md` 和 `docs/superpowers/README.md`。

建议的 V1 文档清理：

- 新增 `docs/DOCUMENT_GOVERNANCE.md`，定义当前有效、历史记录、已取代、已废弃等类别。
- 新增 `docs/superpowers/README.md`，说明 dated specs/plans/reviews 是审计轨迹，不总是当前事实。
- 刷新 `FUTURE_WORK_PLAN.md` 为当前路线图，或把旧文件改名为 dated historical plan 并创建新路线图。
- 替换 `web/README.md`。
- 更新过期 `parse_ledger.json` 和 `scripts/literature_healthcheck.py` 引用。
- 为 `scripts/` 定义脚本生命周期表，包含下划线前缀临时脚本。
- 可选：增加 doc lint 命令，标记 active 文档中的 `parse_ledger.json`、旧 MinerU self-deploy 端点和 root-level `scripts/_*.py`。

## 最终建议

当时不建议标记为 **完整 V1 发布 PASS**。

建议先把后端/数据状态标记为健康，并把项目视为 **V1 release candidate**。随后修复 P1-01 到 P1-04，刷新维护文档，再重新运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ -q
.\.venv\Scripts\python.exe scripts\healthcheck_library.py --json
npm.cmd run build
```

这些通过后，可以更有底气地将项目标记为初始 V1。
