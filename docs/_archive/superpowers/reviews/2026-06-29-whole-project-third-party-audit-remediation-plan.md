# 文献库全量第三方审核整改方案

> 日期：2026-06-29  
> 来源报告：`docs/superpowers/reviews/2026-06-29-whole-project-third-party-audit-report.md`  
> 用途：供后续模型/agent 按项实施修复。本文不替代审核报告，只把 findings 转换为可执行方案、测试要求和复核流程。  
> 总原则：先修 P1 阻断项，再修安全边界与一致性 P2，最后处理文档、性能和产品判断项。

## 0. 执行与派发规则

### 0.1 工作方式

1. 每个修复项应由实施 agent 先阅读原审核报告对应 finding，再阅读本文对应方案。
2. 涉及真实 `literature.sqlite`、`works/`、`_inbox/`、`_quarantine/` 的操作默认只读；复现和测试使用临时目录、临时 SQLite 或 fixture DB。
3. 每个修复 PR/提交至少包含：
   - 代码修复。
   - 对应回归测试或明确说明为何不能自动化。
   - 本文中验收命令的执行结果。
4. 审核和汇总至少两轮：
   - 第一轮：实施 agent 自查，重点检查边界条件和测试是否真的覆盖失败路径。
   - 第二轮：独立 review agent 复核，不能只看测试绿，要对照原 finding 做反向复现。

### 0.2 建议子 agent 分工

- `backend-security-agent`：P1-01、P2-01、P2-02。
- `backend-data-consistency-agent`：P1-02、P1-03、P1-05、P2-03、P2-06。
- `frontend-contract-agent`：P1-06、P2-08、P2-10、P2-11、P3-03。
- `test-infra-agent`：P1-04、P2-04、P2-05、P2-09。
- `docs-release-agent`：P2-07、P3-01、P3-02 以及最终整改汇总。

每个 agent 完成后输出：修改文件、测试命令、剩余风险、是否需要迁移真实库。

### 0.3 总体验收命令

P1 修复完成后至少运行：

```text
uv run python -m pytest tests/
MinerU_API_KEY= MINERU_API_TOKEN= uv run python -m pytest tests/
npm.cmd run build
.\.venv\Scripts\python.exe -m py_compile scripts\dedup_cleanup.py
```

若修复 parser 子项目，还应运行：

```text
.\.venv\Scripts\python.exe -m pytest --collect-only -q parser\tests
```

## 1. P1 阻断项整改

### P1-01 SQL 注入导致 summary 统计撒谎

目标：非法 `status` 不得进入 SQL；metadata/classification 列表和 summary 使用同一套过滤语义。

建议改法：

1. 在 `api/routes/metadata.py` 和 `api/routes/classification.py` 中为 `status` 建立白名单，例如 `all`、`pending`、`approved`、`rejected`、`superseded` 等实际业务状态。
2. 非白名单值直接返回 HTTP 400，错误信息说明允许值。
3. summary SQL 不再拼接字符串。可采用两种方式之一：
   - 动态拼接固定 SQL 片段，但所有外部值进入参数列表。
   - 构造公共 `build_review_status_filter(status)`，返回 `(sql_fragment, params)`。
4. 列表查询、risk summary、model summary、ambiguity summary、priority summary 必须共用同一过滤参数。

测试要求：

1. 对 `/api/metadata?status=' OR 1=1 --` 断言 HTTP 400。
2. 对 `/api/classification/extractions?status=' OR 1=1 --` 断言 HTTP 400。
3. 对合法 status 断言列表 total 与 summary 过滤范围一致。
4. 对 `status=all` 断言不过滤。

复核重点：

- 搜索 `review_status = '{status}'`、`f"AND`、`format(status)`，确认没有残留外部值拼接 SQL。
- 不要只修列表，summary 是本 finding 的核心。

### P1-02 `works` quarantine/restore 路径处理会 500 或写错 DB 路径

目标：隔离/恢复时文件实际移动路径与 DB 写入路径完全一致；`original_name=NULL` 和 `original_name != basename(source_path)` 都能正确处理。

建议改法：

1. 在 `api/routes/works.py` 抽出小函数：
   - `safe_source_display_name(row, fallback_path)`：返回 `original_name or Path(source_path).name`。
   - `move_source_file(src, dest_dir, preferred_name)`：计算唯一目标路径、执行移动、返回实际 `Path`。
2. quarantine 使用 `dest = quarantine_dir / (original_name or src.name)`，不要写成 `quarantine_dir / original_name or src.name`。
3. DB 更新必须写入实际移动后的 `dest`，不能重新用 `src.name` 推导。
4. restore 同理：恢复目标路径应先计算，再移动，再把同一目标路径写回 DB。
5. 若目标文件已存在，应定义稳定策略：报 409、生成去重文件名，或要求人工处理。建议优先生成唯一文件名并记录日志，避免覆盖。

测试要求：

1. `source_files.original_name=NULL` 时 quarantine 不 500，DB 路径等于实际文件路径。
2. `original_name != Path(source_path).name` 时 quarantine 后 DB 路径等于实际文件路径。
3. restore 覆盖上述两个场景。
4. 文件缺失时返回可解释错误，不留下半更新 DB。

复核重点：

- 同一事务中先移动文件还是先写 DB 需要明确失败策略。
- 所有路径字段更新必须使用实际 `Path`，不能二次推导。

### P1-03 Fresh schema 初始化不完整，`/api/works` 无法运行

目标：新建空库经过核心 schema 初始化后，主 API 至少可以启动并返回空列表，不因缺列崩溃。

建议改法：

1. 在 `scripts/literature_ingest.py::ensure_core_schema()` 创建 `source_files` 时补齐 live schema 需要的字段：
   - `status`
   - `archived_at`
   - `archive_path`
   - `archive_reason`
2. 给 `status` 设置默认值 `active`，历史数据迁移时 NULL 也补为 `active`。
3. 增加幂等 migration，启动或 schema ensure 时执行：
   - 检查缺失列。
   - `ALTER TABLE source_files ADD COLUMN ...`。
   - 必要时补默认值。
4. 明确 schema 真相来源。建议把 core schema 与 API 依赖列放在同一模块或同一测试中校验。

测试要求：

1. 临时空库调用 `ensure_core_schema()` 后，请求 `/api/works` 返回 200。
2. 临时旧 schema 缺这些列时，migration 后 `/api/works` 返回 200。
3. 已有行迁移后 `source_files.status` 默认为 `active`。

复核重点：

- 不要只改 API 兼容旧列缺失；schema 漂移会继续污染后续测试。
- migration 必须幂等，多次执行不报错。

### P1-04 `scripts/dedup_cleanup.py` 不可编译

目标：脚本可编译、可 dry-run，事故时能安全运行。

建议改法：

1. 删除第二个 `from __future__ import annotations`。
2. 检查文件顶部 import 顺序，确保 future import 位于 docstring 后、其他语句前。
3. 如果脚本已有 CLI 参数，补一个最小 dry-run smoke test；如果没有测试框架入口，至少加入 `py_compile` 测试。

测试要求：

```text
.\.venv\Scripts\python.exe -m py_compile scripts\dedup_cleanup.py
```

建议新增：

```text
.\.venv\Scripts\python.exe -m pytest tests/ -k dedup_cleanup
```

复核重点：

- 只修编译错误不等于治理脚本可信。若脚本会写 DB/文件，dry-run 必须默认不破坏。

### P1-05 ingest 文件复制与 DB commit 存在崩溃窗口

目标：至少能检测并修复 DB 不知道的 orphan 文件；长期目标是 ingest 可恢复。

短期建议改法：

1. 新增 healthcheck/repair 子命令或脚本，扫描：
   - `works/*/source/*` 中没有对应 `source_files.source_path` 的文件。
   - `source_files.source_path` 指向不存在文件的行。
   - work 目录存在但 DB 无 work 的异常。
2. healthcheck 默认只读输出；repair 必须显式 `--apply`。
3. ingest 流程在 copy 后、DB commit 前写入 staged manifest，例如 `.ingest-staging.json`，commit 成功后删除。
4. healthcheck 识别残留 manifest，给出恢复建议。

长期建议改法：

1. 引入两阶段 ingest 状态：`planned` -> `files_copied` -> `committed`。
2. DB 先写 planned/staging rows，再复制文件，再事务更新为 active。
3. 崩溃恢复时按 staging 状态补偿或清理。

测试要求：

1. monkeypatch `insert_db_rows` 在 copy 后抛异常，断言 healthcheck 能发现 orphan 文件。
2. `source_files.source_path` 指向不存在文件时，healthcheck 能发现。
3. repair 模式需在临时目录验证，不碰真实库。

复核重点：

- 本项可先以 healthcheck 关闭验收风险，但必须在文档中标注长期重构未完成。

### P1-06 WorkDetail 分类保存不是原子操作，可能部分落库后失败

目标：分类保存不会出现“标量字段已保存、旧标签已删、新标签失败”的半成功状态。

优先建议改法：

1. 前端先去掉 `WorkDetail.vue` 中分类相关 `n-select` 的自由 `tag` 输入。
2. 保存前校验所有标签必须来自后端词表。
3. 对当前多步保存增加 try/catch；任一步失败时提示用户重新加载，不显示“保存成功”。

更完整改法：

1. 后端新增原子 endpoint，例如 `PUT /classification/tags/{work_id}/replace`。
2. 请求体包含所有分类字段和标签集合。
3. 后端在一个 DB transaction 中：
   - 校验标签合法性。
   - 更新 work 标量字段。
   - 删除旧标签。
   - 插入新标签。
4. 任一步失败则 rollback。
5. 前端改为一次调用该 endpoint。

测试要求：

1. 非法标签保存返回 400，旧标签不被删除。
2. 合法标签保存后，标量字段和标签集合同时更新。
3. 前端禁用词表外输入或在提交前阻止。

复核重点：

- 如果只前端禁用自由 tag，仍要考虑 API 直接调用的半成功风险。验收时至少要记录这是短期方案还是完整方案。

## 2. P2 重要项整改

### P2-01 Files API 信任 DB 路径，可读取库外文件

目标：files API 只能返回库根允许范围内的文件。

建议改法：

1. 在 `api/routes/files.py` 增加路径校验函数：
   - `resolved = path.resolve()`
   - `resolved.relative_to((LIBRARY_ROOT / "works").resolve())`
   - 不在允许目录内则返回 403 或 404。
2. 对 markdown content、PDF source、其他 file response 共用该函数。
3. 如果业务确实允许 `_inbox` 或 `_collector_cache`，必须显式加入 allowlist，不要允许任意绝对路径。

测试要求：

1. DB 路径指向库外文件时，content/PDF 端点不返回文件内容。
2. DB 路径指向正常 `works/` 文件时仍可返回。
3. `..`、符号链接、大小写路径差异都走 `resolve()` 后判断。

### P2-02 collector promote 路径边界不足

目标：promote 只能消费 collector 允许目录内的候选 PDF。

建议改法：

1. 修改 `collector/paths.py::resolve_pdf_path()`：
   - 相对路径基于 `LIBRARY_ROOT` 或 collector cache 解析后必须 `resolve()`。
   - 绝对路径也必须校验在 allowlist 内。
2. 建议 allowlist 仅包含 `LIBRARY_ROOT/_collector_cache` 和明确的 `_inbox` 候选目录。
3. 不符合边界的路径抛业务异常，API 返回 400。

测试要求：

1. `../outside-audit.pdf` 被拒绝。
2. 绝对库外路径被拒绝。
3. 正常 cache 内 PDF 可 promote。

### P2-03 已 ingested 的 approved candidate 可重复 promote

目标：promote 幂等。已 ingested 的 candidate 再次 promote 返回已有 work，而不是失败。

建议改法：

1. 在 `api/routes/intake.py` promote guard 中先判断：
   - `status='ingested'` 且 `ingested_work_id` 非空：直接返回成功响应，标注 `already_ingested=true`。
   - `status='ingested'` 但无 `ingested_work_id`：返回 409 或进入 healthcheck 修复。
2. 新 promote 成功后同步更新 `review_status` 或至少保证 guard 不会重复处理同一条。
3. API 响应保持兼容，避免前端因字段缺失崩溃。

测试要求：

1. approved + pending candidate 首次 promote 成功。
2. approved + ingested + ingested_work_id 再次 promote 返回同一个 work_id。
3. ingested 但缺 work_id 返回可解释错误。

### P2-04 parser 子项目测试被默认绿跑隐藏，且单独收集失败

目标：parser 测试状态透明，不再被根测试绿掩盖。

两种可选方案：

方案 A：修复并纳入独立 profile。

1. 修正 `parser/tests` 中旧 `Ledger` import。
2. 修正 `parser/scripts` import 路径。
3. 在 CI 或本地文档中增加 `pytest parser/tests` profile。

方案 B：归档旧测试。

1. 将不可维护旧测试移入 `parser/tests_legacy/` 或文档化为历史参考。
2. 在 README/TECHNICAL_OVERVIEW 明确 parser 测试当前状态。
3. 新增至少一组 parser core smoke test 到根 `tests/` 或独立 profile。

测试要求：

```text
.\.venv\Scripts\python.exe -m pytest --collect-only -q parser\tests
```

复核重点：

- 不允许保持“根测试绿但 parser/tests 收集失败”这种模糊状态。

### P2-05 测试依赖真实 DB 快照并大量 skip，存在假绿

目标：关键行为测试不依赖私人真实库形态。

建议改法：

1. 为 API 测试建立最小 fixture DB builder，覆盖 works、source_files、parse runs、metadata、classification、duplicates、intake 的必要字段。
2. 把关键测试从复制真实 `literature.sqlite` 改为使用 fixture DB。
3. 保留少量 live snapshot smoke，但这些测试必须标记清楚，例如 `@pytest.mark.live_snapshot`。
4. 对 `skipTest("No ...")` 逐个分类：
   - 关键路径：改 fixture，不允许 skip。
   - 真实数据 smoke：保留 skip，但不作为验收证明。

测试要求：

1. 删除或减少关键测试中的数据存在性 skip。
2. 在空真实库或无私有 DB 的环境下，核心测试仍可运行。

### P2-06 当前真实库已有若干一致性症状

目标：提供只读诊断和显式 repair 流程，先发现，再由用户决定是否修复真实库。

建议改法：

1. 新增 `scripts/healthcheck_library.py` 或合并到现有治理脚本，默认只读检查：
   - `source_files.source_path` 是否存在。
   - `works.read_status='quarantined'` 时 `source_files.status/path` 是否一致。
   - `intake_candidates.status/review_status/ingested_work_id` 是否自洽。
   - orphan physical files。
2. 输出机器可读 JSON 和人类可读摘要。
3. repair 必须使用 `--apply`，并在执行前打印计划。

测试要求：

1. 临时库构造缺文件、quarantine 状态错配、approved+ingested candidate，healthcheck 能发现。
2. 不带 `--apply` 不写任何文件和 DB。

### P2-07 文档/API 矩阵漂移

目标：README 和技术概览与实际 API/页面入口一致。

建议改法：

1. 更新 README API 表，补齐：
   - works
   - relations
   - duplicates，包括 merge-preview
   - files
   - metadata
   - classification
   - intake
   - parse
   - ingest
2. 更新 `TECHNICAL_OVERVIEW.md`：
   - 后端 9 组 API。
   - 前端 10 个页面路由。
   - 数据库核心表和状态机。
   - 测试范围限制，特别是 parser/tests 状态。
3. 增加一份轻量事实地图生成/校验脚本是加分项，但非必须。

验收要求：

- 文档中的 API/页面数量与 `api/main.py`、`web/src/router.js` 一致。

### P2-08 若干后端端点有测试但无前端封装/入口

目标：明确这些端点是 API-only 还是人工审核 UI 的一部分。

需要产品判断的端点：

- `GET /metadata/agent/queue`
- `POST /metadata/{ext_id}/supersede`
- `POST /classification/extractions/batch-approve-with-tag`

方案 A：标注 API-only。

1. 在 README/TECHNICAL_OVERVIEW 中列入 API-only 端点。
2. `web/src/api.js` 不补封装。
3. 测试保持后端覆盖即可。

方案 B：补前端封装和入口。

1. 在 `web/src/api.js` 增加函数封装。
2. 在对应审核页面加入入口或批量操作。
3. 增加前端状态处理：loading、error、empty、success。

验收要求：

- 不能继续处于“后端存在但没人知道是否应有 UI”的状态。

### P2-09 `duplicates/{group_id}/merge-preview` 缺测试覆盖

目标：UI 依赖的 merge-preview 有后端回归测试。

建议测试：

1. 不存在 group_id 返回 404。
2. 正常 duplicate group 返回推荐 primary 和候选列表。
3. 空候选或异常 group 返回可解释错误。
4. 如果有权限/状态限制，也要覆盖非可合并状态。

验收要求：

```text
uv run python -m pytest tests/ -k merge_preview
```

### P2-10 前端筛选与分页状态有合法空页问题

目标：筛选条件改变时 page 重置为 1，避免用户看到假空态。

建议改法：

1. 在 `web/src/views/Works.vue` 增加统一函数 `resetAndLoad()`：
   - `page.value = 1`
   - `loadData()`
2. 所有筛选控件 `@update:value` 改为调用该函数。
3. `ClassificationReview.vue` 状态切换同理，先 reset page，再加载。

测试要求：

1. 单元测试或手动验证：在第 N 页切换筛选，自动回第一页。
2. URL/query 同步逻辑如存在，也要同步 page。

### P2-11 WorkDetail 左侧列表多选筛选编码错误

目标：WorkDetail 左侧列表的查询参数编码与 Works 页面一致。

建议改法：

1. 抽出公共 query builder，例如 `appendMultiValueParams(searchParams, key, values)`。
2. Works 和 WorkDetail 共同使用：
   - 多值参数重复 append：`?status=a&status=b`
   - 不使用逗号字符串：`?status=a,b`
3. 增加测试或最小断言，确保数组编码为重复参数。

验收要求：

- 从 Works 多选筛选进入 WorkDetail，左侧列表与原列表结果一致。

## 3. P3 治理项整改

### P3-01 `.env` 在共享工作区可读

目标：避免 agent 或日志泄露密钥。

建议改法：

1. 审核和自动化脚本只允许打印环境变量键名，不打印值。
2. 文档中说明 `.env` 不应放共享工作区；建议迁移到用户级 secret store 或系统环境变量。
3. 检查 `.gitignore` 确认 `.env`、`.env.*` 不入库。

验收要求：

- 搜索日志、报告、测试输出中无 token 值。

### P3-02 前端 build 大 chunk

目标：降低首包体积，非阻断。

建议改法：

1. 对页面路由做懒加载 code splitting。
2. 检查大依赖是否能按页面拆分。
3. 必要时配置 Vite `manualChunks`。

验收要求：

- `npm.cmd run build` 成功。
- chunk 警告减少或文档化保留原因。

### P3-03 ClassificationReview 模糊度按钮只改 UI 状态

目标：按钮语义与实际行为一致。

方案 A：按钮是过滤器。

1. 前端请求参数带上 `ambFilter`。
2. 后端 classification 列表支持模糊度过滤。
3. summary 与列表语义一致。

方案 B：按钮只是统计高亮。

1. 修改 UI 文案，避免用户以为列表被过滤。
2. 不改后端。

验收要求：

- 点击按钮后的列表变化或不变化必须符合文案。

## 4. 推荐实施顺序

### 第一批：必须先做

1. P1-01 SQL 注入。
2. P1-02 quarantine/restore 路径一致性。
3. P1-03 fresh schema。
4. P1-04 dedup_cleanup 编译。

完成后运行 P1 总体验收命令。

### 第二批：关闭数据一致性和安全边界

1. P1-05 healthcheck/orphan 检测。
2. P2-01 files path boundary。
3. P2-02 collector path boundary。
4. P2-03 promote 幂等。
5. P2-06 healthcheck 扩展。

### 第三批：前端契约与测试可信度

1. P1-06 WorkDetail 分类保存。
2. P2-09 merge-preview 测试。
3. P2-10 分页筛选 reset。
4. P2-11 多选 query 编码。
5. P2-04/P2-05 parser 与 fixture 测试治理。

### 第四批：文档、产品判断与工程治理

1. P2-07 文档/API 矩阵。
2. P2-08 API-only 或 UI 入口判断。
3. P3-01 secret 暴露治理。
4. P3-02 chunk 拆分。
5. P3-03 模糊度按钮语义。

## 5. 最终复核清单

整改完成后，由独立 review agent 做第二轮复核，至少检查：

1. 原报告所有 P1 是否有对应测试。
2. SQL 注入 payload 是否不能影响 summary。
3. quarantine/restore 在 `original_name=NULL` 和名称不一致时是否 DB/磁盘一致。
4. fresh DB 是否能跑 `/api/works`。
5. files/collector 是否不能越界读取或复制库外文件。
6. promote 已 ingested candidate 是否幂等。
7. 根测试绿是否仍掩盖 parser/tests 收集失败；若保留失败，是否已明确归档或标注。
8. README/TECHNICAL_OVERVIEW 是否与实际路由一致。
9. 所有修复是否没有对真实库做破坏性写入。

最终结论文档建议新建：

```text
docs/superpowers/reviews/2026-06-29-whole-project-third-party-audit-remediation-result.md
```

其中逐项记录：已修复、测试命令、失败项、未决产品判断、真实库是否需要人工 repair。
