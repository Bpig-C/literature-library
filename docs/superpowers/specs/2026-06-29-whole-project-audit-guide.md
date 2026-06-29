# 文献库整体审核指导（双阶段）

> 面向：对整个 `literature_library` 项目做**整体审核**的强代码模型（不是逐任务验收）。
> 性质：**审核的输入与方向**，不是审核结论。给地图和该怀疑什么，不规定"怎么看"——保留审核模型的自由度。
> 配套：总规划 `2026-06-28-three-chain-completeness-plan.md`、操作手册 `2026-06-29-three-chain-runbook.md`。
> 用途：下一步第三方系统性审核验收的**执行规程 + 审核提示词**。第三方可以据此派发子 agent、复核证据、输出阻断/非阻断结论。

## 第三方审核硬约束

1. **不得直接信任本文档事实**：一阶段地图是起点，不是证据。审核 agent 必须先独立扫描代码、路由、前端 API、测试和 DB schema，生成自己的"功能-实现-测试-入口"矩阵，再与本文档对账。
2. **必须派发子 agent 并分工**：至少 4 个并行子 agent：
   - `traceability-agent`：重建功能/文档/实现/测试矩阵，找死端点、孤儿脚本、文档漂移。
   - `backend-data-agent`：审 DB 写入、状态机、事务、幂等、崩溃窗口、collector/inbox 双入口。
   - `frontend-contract-agent`：审 Vue 页面、`web/src/api.js`、路由响应形状、空态/错误态/分页/筛选。
   - `test-security-agent`：审测试假绿、网络/env 泄漏、路径逃逸、密钥泄漏、`except` 吞错。
3. **至少两轮审核**：
   - 第一轮：各子 agent 独立产出 finding，必须附文件行号、命令或复现步骤。
   - 第二轮：交叉复核。每个 finding 必须由另一个 agent 复现或反驳；无法复现的 finding 降级为"待确认"，不得作为阻断项。
   - 汇总轮：汇总 agent 只采纳有证据的 finding，去重、定级、给出验收结论。
4. **审核不得偷懒为"功能可用"**：三链路 smoke 只能证明可达，不能证明安全。最终结论必须回答：哪些输入、时序、异常或并发会让系统撒谎、损坏数据、绕过单核或丢失证据。
5. **所有结论必须可复现**：没有文件行号、DB 查询、命令输出、HTTP 请求/响应、截图或测试补丁之一的结论，一律不得进入最终阻断清单。

## 隔离环境要求

第三方审核默认**只读真实库**。任何会写 DB、移动文件、触发解析、下载 PDF、执行 ingest/promote/resolve/quarantine 的动作，必须在隔离副本中完成。

建议副本布局：

```text
_audit_sandbox/
  literature.sqlite
  works/
  _inbox/
  _duplicates/
  _quarantine/
```

执行要求：

- 复制 `literature.sqlite`、`works/`、`_inbox/`、`_duplicates/`、`_quarantine/` 后再做 destructive smoke。
- 写入类测试必须 patch `api.db.LIBRARY_ROOT`、相关脚本的 `library_root` 或工作目录，确认不会碰真实根目录。
- 网络型 smoke（arxiv/GitHub/MinerU/cloud）必须单独标注"需要网络/密钥/额度"，不能作为 hermetic 自动化测试通过的前提。
- 如果需要验证崩溃窗口，优先用临时 DB + 临时文件树 + monkeypatch/fault injection，不在真实库上手工中断进程。

## 验收判定标准

最终报告必须给出明确结论：

- **PASS**：未发现 P0/P1；P2/P3 已记录且不影响当前验收。
- **CONDITIONAL PASS**：无 P0，但存在 P1；必须列出最小修复清单，修复并复测后才能交付。
- **FAIL**：存在 P0，或核心证据不足导致无法判断数据安全。

严重级别：

- **P0 阻断**：可导致真实库数据损坏/丢失、路径逃逸写出项目根、密钥泄漏、绕过人工审核直接晋升、解析/摄入状态系统性撒谎、跨入口重复写入不可恢复。
- **P1 高危**：单核承诺被绕过、状态机允许非法倒退、崩溃后 DB/磁盘明显不一致、测试依赖真实网络/env 导致假绿、前端关键流程在合法响应下崩溃。
- **P2 中危**：死端点/孤儿脚本/未测 migration、错误提示不足、非核心页面空态异常、幂等性不完整但可人工恢复。
- **P3 低危**：文档漂移、命名混乱、报告可读性、非阻断治理问题。

Finding 必须使用固定格式：

```markdown
### [P1] 标题
- 影响：
- 证据：`path/to/file.py:123` + 关键代码/DB 查询/HTTP 响应/截图
- 复现：
- 实际结果：
- 预期结果：
- 阻断判断：
- 修复建议：
- 复核状态：confirmed by <agent> / disputed / needs-info
```

## 为什么分两阶段

两阶段覆盖**不同的失效类**，互补不冗余：

- **一阶段（可追溯性 / 覆盖）**：功能↔文档↔实现↔测试的**对账**。抓"有实现无文档、有文档无实现、孤儿脚本、规格与代码漂移、有功能无测试、死端点、dead code"。这类启发式镜头抓不到——它假设功能边界清楚，但边界本身可能就错了。
- **二阶段（正确性 / 完整性猎杀）**：状态机非法转换、崩溃窗口、单核被绕过、吞异常、并发损坏、路径逃逸、测试假绿。

**先做一阶段的价值**：给审核模型一张地图，让它知道哪些承重、哪些可疑，二阶段猎杀更准、不浪费时间重新发现清单。

**守则**：一阶段产物是"地图 + 缺口标注"，**不是逐功能验收清单**。验收式清单会把审核拽回"每个功能对不对"——那是二阶段的活，会让一阶段把二阶段框死。一阶段**不下正确性结论**。

---

# 一阶段 · 功能可追溯性地图

> 形式：功能域 → 设计文档 → 实现文件（route/脚本/core/前端）→ 测试 → 状态/缺口。
> `⚠️` = 对账缺口或疑点（一阶段的真正产出，交给二阶段优先怀疑）。

## A. 核心文献库（Phase 0–4 既有基线）

| 功能域 | 设计文档 | 实现（route / 脚本 / core / 前端） | 测试 | 状态/缺口 |
|---|---|---|---|---|
| works 管理 / WorkDetail | `docs/superpowers/specs/2026-06-11-ui-migration-design.md` | `api/routes/works.py`、`api/routes/files.py`；`web/src/views/Works.vue`·`web/src/views/WorkDetail.vue` | `tests/test_api.py` | ✅ |
| relations 关系 | （同上） | `api/routes/relations.py`；`web/src/views/Relations.vue` | `tests/test_api.py` | ✅ |
| duplicates 去重 | `FUTURE_WORK_PLAN.md` P1.0/4 | `api/routes/duplicates.py`；`scripts/literature_dedup.py`·`scripts/dedup_apply.py`·`scripts/dedup_cleanup.py`·`scripts/scan_title_duplicates.py`；`web/src/views/Duplicates.vue` | `tests/test_api.py` | ⚠️ 去重脚本无独立测试（仅 API 层） |
| metadata 抽取/审核 | `FUTURE_WORK_PLAN.md` P3 段 | `api/routes/metadata.py`；`scripts/literature_metadata_extract.py`·`scripts/literature_metadata_rerun.py`·`scripts/backfill_risk.py`；`web/src/views/MetadataReview.vue` | `tests/test_api.py` | ⚠️ `metadata/supersede`、`metadata/agent/queue` 端点无明确 UI 消费方 |
| classification 抽取/审核/tags/vocab | `FUTURE_WORK_PLAN.md` P2/P3 段 | `api/routes/classification.py`；`scripts/literature_classification_extract.py`·`scripts/recompute_classification_ambiguity.py`·`scripts/_batch_classify*.py`；`web/src/views/ClassificationReview.vue` | `tests/test_api.py` | ⚠️ `classification/extractions/batch-approve-with-tag` 端点无对应 api.js 导出？ |
| files content/pdf | — | `api/routes/files.py` | `tests/test_api.py` | ✅ |
| analysis_runs | `docs/superpowers/specs/2026-06-12-reading-methodology-analysis-runs-design.md` | `scripts/literature_analyze.py`·`scripts/migrate_add_analysis_runs.py` | `tests/test_analysis_runs.py` | ⚠️ 5 runs 全 pending，功能未实战 |
| healthcheck / dashboard | — | `scripts/literature_healthcheck.py`·`scripts/literature_dashboard.py` | `tests/test_healthcheck_no_ledger.py`（仅 ledger 回归） | ⚠️ healthcheck 主体逻辑无独立测试 |

## B. parser 解析子系统（P3.5）

| 功能域 | 设计文档 | 实现 | 测试 | 状态/缺口 |
|---|---|---|---|---|
| 二元路由解析（单核） | `docs/superpowers/specs/2026-06-27-parser-subproject-design.md` + 总规划 §2 | **核心** `parser/core/mineru/router.py::route_and_parse`；`parser/core/mineru/pymupdf_client.py`(本地)·`parser/core/mineru/cloud_client.py`(vlm) | `parser/tests/test_routing.py`（不进根 testpaths） | ⚠️ 单核测试在 parser/tests，根套件不覆盖 |
| 解析触发/状态 API+UI | `docs/superpowers/plans/2026-06-28-phaseB-parse.md` | `api/routes/parse.py`；`web/src/views/WorkDetail.vue` 按钮 | `tests/test_parse_api.py` | ✅ |
| 解析 CLI（DB-only） | `docs/superpowers/plans/2026-06-28-phaseD-status-unify.md` | `scripts/literature_batch_parse.py` | `tests/test_batch_parse_cli.py` | ✅ |
| 状态同步 | — | `scripts/migrate_sync_parse_status.py::sync_work_parse_status` | 间接（parse_api / batch_parse_cli） | ✅ |
| ⚠️ 自部署降级路径 | （parser-subproject-design） | `parser/core/mineru/local_client.py`·`web_client.py`·`mineru_op.py`·`base_client.py` | 仅 parser/tests | **疑似 dead code**：cloud+PyMuPDF 已成主路径，self-deploy 是否仍被 active 路径触达？ |

## C. collector 采集子系统（P6）

| 功能域 | 设计文档 | 实现（core / API / CLI / UI） | 测试 | 状态/缺口 |
|---|---|---|---|---|
| 地基（候选层/闸门/桥） | `docs/superpowers/specs/2026-06-27-collector-integration-design.md` + `docs/superpowers/plans/2026-06-28-collector-foundation.md` | `collector/{candidate_store,gate,ingest_bridge,normalize,paths,replace_source,fetch}`；`collector/adapters/{arxiv,github}` | `test_candidate_store*`·`test_gate*`·`test_ingest_bridge`·`test_normalize`·`test_*_adapter`·`test_replace_source`·`test_collector_boundary` | ✅ |
| topics 成熟度闸门 | `docs/superpowers/specs/2026-06-27-collector-retrieval-design.md` + `docs/superpowers/plans/2026-06-29-phaseC-collector-ui.md` | `collector/topics.py`；`api/routes/intake.py`(`/topics`)；CLI `topic`；`web/src/views/TopicsReview.vue` | `test_collection_topics`·`test_intake_api` | ✅（live DB 0 主题，未实战） |
| collect 发现 | 同上 | **核心** `collector/collect.py::collect_once`；`discovery_explicit.py`·`discovery_citation.py`；`api/routes/intake.py`(`/collect`)；CLI `collect` | `test_collect_once`·`test_discovery_*` | ✅ |
| resolve 闸门 | 同上 | `collector/gate.py::resolve_pending`；`api/routes/intake.py`(`/resolve`)；CLI `resolve` | `test_gate_resolve_pending`·`test_intake_api` | ✅ |
| A2 审核+晋升 | `docs/superpowers/plans/2026-06-28-phaseA-intake-review.md` | `api/routes/intake.py`(`/candidates·/stats·/review·/promote`)；CLI `list/promote`；`web/src/views/IntakeReview.vue` | `test_intake_api`(18)·`test_intake_cli`·`test_promote_topic_tags` | ✅ |
| PDF 下载缺口修复 | `docs/superpowers/specs/2026-06-28-collector-pdf-download-fix.md` | `collector/ingest_bridge.py` | `test_ingest_bridge` | ✅ |

## D. ingest inbox 摄入（P4 + Phase B'）

| 功能域 | 设计文档 | 实现 | 测试 | 状态/缺口 |
|---|---|---|---|---|
| inbox 摄入 nucleus | `FUTURE_WORK_PLAN.md` P1/P4 段 | `scripts/literature_ingest.py` | `tests/test_literature_ingest.py`·`test_ingest_no_ledger.py` | ✅ |
| inbox API+UI（Phase B'） | `docs/superpowers/plans/2026-06-29-phaseBp-inbox-ingest.md` | `api/routes/ingest.py`(`/plan`·`/execute`)；`web/src/views/InboxReview.vue`；`web/src/api.js`(`getIngestPlan`/`executeIngest`) | `tests/test_ingest_api.py` | ✅ |

## E. 跨切 / 治理

| 项 | 位置 | 状态/缺口 |
|---|---|---|
| 三链路总规划 + 矩阵 + DoD | `2026-06-28-three-chain-completeness-plan.md` | ✅ 全 ✅ |
| 审核/测试手册 | `2026-06-29-three-chain-runbook.md` | ✅ |
| 单核不变量守卫 | `tests/test_collector_boundary.py`（3 条） | ⚠️ 只守 collector；parser 单核无运行时守卫（仅靠 grep） |
| 测试隔离配置 | `pyproject.toml testpaths=["tests"]` | ✅ |

## 一阶段缺口清单（交给二阶段的优先怀疑对象）

1. **⚠️ 疑似 dead code**：`parser/core/mineru/{local_client,web_client,mineru_op,base_client}.py`（self-deploy 降级路径，cloud+PyMuPDF 成主路径后是否仍被触达？）。
2. **⚠️ 一次性脚本游离**：`scripts/_batch_classify.py`·`_batch_classify_all.py`·`_phase_c_validate.py`（下划线前缀=ad-hoc，按治理约定应进 `_archive/`）。
3. **⚠️ migration/utility 脚本无测试**：`backfill_risk.py`·`recompute_classification_ambiguity.py`·`migrate_backfill_doc_type.py`·`dedup_apply.py`·`dedup_cleanup.py`·`scan_title_duplicates.py`——是否幂等？重跑会坏吗？
4. **⚠️ 端点无 UI/api.js 消费方**：`metadata/supersede`、`metadata/agent/queue`、`classification/extractions/batch-approve-with-tag`——死端点还是预留？
5. **⚠️ parser 单核无运行时守卫**：collector 有 boundary 测试守"不直接写 works"，parser 的"route_and_parse 唯一"只有 grep，无测试在有人复制第二份时自动红。
6. **⚠️ healthcheck/dashboard 主体无测试**：只测"不读 ledger"，其余一致性检查逻辑本身没被测。
7. **⚠️ analysis_runs 全 pending**：实现+有测试，但从未端到端真跑——设计意图与实现是否对得上，未经验证。

> 这些是**起点，不是全部**。二阶段必须跑完全程，缺口只是优先扎进去的对象。

---

# 二阶段 · 启发式猎杀

## 定调（prime directive）

> 这是一个本地文献库：FastAPI + SQLite(WAL) + Vue3，两个子系统（collector 采集、parser 解析）+ 一条 inbox 旁路，都写同一张 `works` 表。**审核目标不是"功能在不在"，而是"数据会不会坏、状态会不会撒谎、单核承诺是不是真的"。** 可以假设功能跑得通——去找那些跑通了但留下隐患的地方。

把注意力从"happy path 正确"挪到"失败路径、并发、状态一致性、承诺兑现"。

## 启发式镜头（每个是一句质问）

1. **"每个状态字段的最坏转换是什么，代码允许它发生吗？"** 全库 ~6 个状态机：`works.parse_status`(unknown/pending/parsing/partial/succeeded/failed)、`works.read_status`(unread/quarantined/...)、`intake_candidates.resolution`(new/exact/title/needs_better_copy)、`review_status`(pending/approved/rejected)、`map_status`(seedling/proposed/mapped)、`metadata_extractions.review_status`。**别看正向转换，去枚举非法/倒退转换，然后 grep 能触发它的写路径。** 例：promote 之后候选还能再 promote 吗？quarantined 的 work 能被解析回填吗？

2. **"每个'单核'函数，第二份拷贝藏在哪？"** 不是 grep `def route_and_parse`（那当然唯一），而是**找逻辑的重复**：有没有第二处手写了同样的分发/去重/SHA256/状态推导？单核承诺的真正考验是"有没有人绕过它"。

3. **"系统在崩溃窗口里会变成什么样？"** SQLite + 多连接（API 一条、CLI 一条、ingest 自开）。找**跨 commit/跨连接的多步写**：写盘成功但 DB 回滚、或 DB 写了但文件没动。典型：解析写了 `content.md` 但 `parse_runs` 没提交；ingest 复制了文件但 `works` 插入失败。

4. **"哪些 `except: pass` / `except Exception` 在吞掉本该让用户知道的失败？"** 全仓 grep `except` + 下一行 `pass`/`continue`。每处问：被吞的异常会不会让状态**静默不一致**（数据在但状态说没在，或反之）。

5. **"文件名/路径从哪进来，能逃逸吗？"** `original_name`、`source_path`、`arxiv_id`、用户丢的 inbox 文件名，都流进 `Path(...)` / `shutil.move` / `open`。**找未净化的字符串拼进文件系统操作的地方**（路径穿越、覆盖 `_archive` 外的文件、覆盖已有 work）。

6. **"前端假设的响应形状，每个后端分支都成立吗？"** 别只看主路径。`GET /api/metadata` 在 `include_quarantined=true/false`、空结果、分页边界时结构一致吗？空数组、null、缺键——前端会不会崩或静默错。

7. **"测试是真在断言，还是在自我证明？"** 三类假绿：① 桩返回什么断言什么（恒真）；② 断言落在 setup 而非行为；③ 依赖真实 env/网络/DB（去掉就红）。**把 `MinerU_API_KEY` 清空、把 `literature.sqlite` 临时移走，再跑全量——暴露的就是 hermetic 缺口。**

8. **"两个写 works 的入口，互相会破坏吗？"** collector（经 `ingest_bridge`，候选闸门）vs inbox（直写）。**SHA256 去重是唯一的交叉守卫**。同内容 PDF 一条走 inbox 一条走 collector，会怎样？`_duplicates/exact_sha256` 与 `intake_candidates` 去重是两套，会不会漏判/双写？

9. **"幂等性：同一个动作跑两遍会怎样？"** 重复 ingest 同 PDF、重复 promote 同候选、重复 trigger 同 work 的解析、重复跑迁移脚本。**好系统幂等；找那些"再跑一次就坏"的地方**（重复 source_files 行、重复 quarantine 移动、parse_runs 主键冲突）。

10. **"`.env`/密钥/网络边界有没有漏到不该漏的层？"** 解析 token、模型 key、外部 API（arxiv/Semantic Scholar/GitHub）调用点。测试是否真桩了网络？有没有把密钥写进日志/错误消息/DB？

11. **"UI 合法操作是否真的覆盖了所有关键状态？"** 用 Playwright 或等价浏览器自动化打开 `/works`、`/works/{id}`、`/metadata`、`/classification`、`/duplicates`、`/relations`、`/intake`、`/topics`、`/inbox`。检查 console error、network 4xx/5xx、空态、筛选、分页、刷新后状态保持。UI 只渲染不报错不够，必须至少点击每个关键写操作的 dry-run/confirm/trigger 前置按钮，并在隔离副本验证响应。

12. **"历史/归档代码会不会被误当 active 入口？"** `_archive/`、`parser/` 内旧 API、`scripts/README.md` 里的旧 `parse_ledger` 说明、静态 dashboard 说明都可能误导后续 agent。审核时区分 active import/route/CLI 入口与历史材料；若历史材料仍被 README/runbook 指向，应作为文档漂移 finding。

## 承重事实（非显然，必须独立验证——别信文档，信代码）

- **解析单核** = `parser/core/mineru/router.py::route_and_parse`；CLI/API/UI 三处都该调它，无一例外。
- **采集单核** = `collector/collect.py::collect_once`；CLI 与 API 都该是薄包装。
- **collector 绝不直接写 `works`**，唯一例外 `collector/replace_source.py`（且只能写 `read_status` 列）。有 boundary 测试守卫——确认守卫**真覆盖所有 `collector/*.py`**，没有"新文件漏在 regex 外"。
- **`literature_parse_runs` 是解析状态唯一源**；`parse_ledger.json` 已废弃归档。active 代码任何对 `parse_ledger` 的读写都是 bug。
- **`works.parse_status`** 由 `sync_work_parse_status` 推导（succeeded 粘性、全 failed→failed、否则 pending）。CLI 路径真调了吗？有没有第二套手算（partial/parsing）会和它打架？
- **两条摄入路径**：collector（候选闸门→`ingest_bridge`）vs inbox（直写）。`ingest_bridge` 内部**复用 ingest nucleus**（临时 inbox 子目录 + 读完即删）——这个"复用"是否真隔离干净？
- **解析输出契约**：`works/{work_id}/parsed/mineru/{source_file_id}/content.md` + `literature_parse_runs.content_md_path`。任何偏离都是隐患。

## 起手危险区（"从这开始挖"，不是"只看这"）

- **`api/routes/metadata.py`** —— 大量 f-string 拼 SQL。查注入面 + status 字符串是否都被引号包住。
- **`scripts/literature_ingest.py`** —— nucleus 硬开 `library_root/literature.sqlite`，不走 `get_conn`。路径可注入性 + 测试隔离靠 patch 路径。
- **`collector/ingest_bridge.py`** —— `library_root` 隐式依赖 `api.db.LIBRARY_ROOT`；临时 inbox 的 `shutil.rmtree` 异常时会不会留垃圾或误删。
- **quarantine 流程**（`metadata.py`/`works.py`）—— 移文件 + 改 `source_files.source_path` + 写 `work_codes` 三处是否原子？中途崩，文件路径与 DB 谁对？
- **`replace_source.py`** —— collector 唯一直写 works 的豁免口，确认**真的只写 read_status**，没有越权列。
- **promote 的 A2 守卫** —— 路由内 inline SQL 查 approved。能绕过吗（TOCTOU：查时 pending、promote 时已变）？
- **CLI 直接当脚本跑**（`python scripts/*.py`）—— sys.path 自补是否每处都齐。
- **裸 `except: pass`** —— grep 全仓逐个问"被吞的会不会造成静默状态分裂"。

## 三个跨切验证动作（亲手做）

1. **清空环境跑测试**：在不移动真实库的前提下运行 `MinerU_API_KEY= MINERU_API_TOKEN= uv run python -m pytest tests/` —— 还绿才是真 hermetic。变红 = 测试纪律 bug（给了假信心）。
2. **单记录全链追踪**：挑一个 `work_id`，只读列全它在 `works`/`source_files`/`literature_parse_runs`/`metadata_extractions`/`classification_extractions`/`duplicate_candidates` 的所有行 + 磁盘 `works/{id}/` 下所有文件，**查一致性**（孤儿文件/行、状态矛盾）。
3. **§2 三连 grep**（快速体检，不是终点）：
   - `grep -rn "def route_and_parse" --include=*.py . | grep -v "_archive\|/docs/"` → 仅 `parser/core/mineru/router.py`
   - `grep -rn "def collect_once" --include=*.py . | grep -v "_archive\|/docs/"` → 仅 `collector/collect.py`
   - `grep -rn "INSERT INTO works" collector/ api/routes/` → 空（works 直写只在 ingest nucleus）

## 最终报告结构

第三方最终输出必须包含：

1. **执行摘要**：PASS / CONDITIONAL PASS / FAIL；阻断项数量；最高风险一句话。
2. **审核范围**：commit/branch、是否使用隔离副本、是否联网、是否有 MinerU/API key、运行的命令。
3. **子 agent 分工与两轮复核记录**：每个子 agent 审了什么，第二轮谁复核谁。
4. **功能追溯矩阵差异**：第三方独立矩阵 vs 本文档地图的差异。
5. **Finding 清单**：按 P0→P3 排序，使用固定 finding schema。
6. **复现附录**：测试命令、HTTP 请求、DB 查询、关键截图/console/network 摘要。
7. **未覆盖/无法判断项**：必须明说原因，例如缺网络、缺密钥、真实库只读、样本不足。
8. **建议修复顺序**：只列和 finding 直接相关的最小修复，不做无关重构建议。

---

## 给审核模型的收尾指令

> "一阶段已替你圈出 7 个起点，但**别局限于此**——二阶段启发式镜头该跑全程，缺口只是优先怀疑对象。
> 功能我相信跑得通。告诉我：**这个系统在什么输入/什么时序下会撒谎或损坏数据——以及你的证据。**"
