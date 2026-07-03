# 文献库全量第三方测试与审核报告

> 日期：2026-06-29  
> 范围：`literature_library` 当前工作区  
> 方式：两阶段审核 + 子 agent 并行首轮 + 主线程第二轮复核  
> 结论：**CONDITIONAL PASS**。未发现 P0；存在多项 P1，修复并复测前不建议作为第三方验收 PASS。

## 0. 执行声明

本次审核没有把 `docs/superpowers/specs/2026-06-29-whole-project-audit-guide.md` 当事实来源，只作为怀疑清单。事实来源为代码、路由、前端入口、测试、临时 SQLite 复现和只读真实库查询。

真实库保持只读。所有会写 DB/文件的复现均使用临时目录或临时 SQLite；未对真实 `literature.sqlite`、`works/`、`_inbox/` 执行破坏性操作。

## 1. 两阶段覆盖

### 阶段一：可追溯性与事实地图

已重建以下事实入口：

- 后端主路由挂载：`api/main.py` 挂载 works、relations、duplicates、files、metadata、classification、intake、parse、ingest 共 9 组 API。
- 前端路由：`web/src/router.js` 暴露 `/`、`/works`、`/works/:id`、`/duplicates`、`/relations`、`/metadata`、`/classification`、`/intake`、`/inbox`、`/topics`。
- 根测试配置：`pyproject.toml` 仅收集 `tests/`，不收集 `parser/tests/`。
- live SQLite schema：已只读列出核心表，包括 `works`、`source_files`、`literature_parse_runs`、`metadata_extractions`、`classification_extractions`、`intake_candidates`、`collection_topics` 等。
- 维护脚本与孤儿风险：重点扫描 `scripts/*`、collector、parser/core、api/routes。

阶段一发现已经进入后文 P1/P2/P3 列表，包括：文档矩阵漂移、未消费端点、危险孤儿脚本、缺测试端点、parser 子项目测试被默认排除等。

### 阶段二：正确性、状态、失败路径与安全猎杀

重点审计了：

- 状态机：`works.parse_status`、`works.read_status`、`intake_candidates.status/review_status/resolution`。
- DB/文件系统崩溃窗口：ingest、quarantine、duplicates merge。
- 单核承诺：`route_and_parse`、`collect_once`、collector 不直接写 works。
- SQL 注入与路径边界：metadata/classification summary SQL、files API、collector promote path。
- 测试假绿：真实 DB 快照依赖、按数据存在性 skip、parser/tests 排除。
- 前端契约：WorkDetail 分类保存、Works/ClassificationReview 分页与筛选、ClassificationReview 模糊度按钮。

## 2. 子 Agent 分工与第二轮复核

首轮派发 4 个只读子 agent：

- `traceability-agent`：功能/文档/实现/测试矩阵，死端点、孤儿脚本、文档漂移。
- `backend-data-agent`：SQLite、状态机、崩溃窗口、幂等、collector/inbox 双入口。
- `frontend-contract-agent`：Vue 与 API 契约、空态、分页、关键操作。
- `test-security-agent`：SQL/path/env/测试假绿/历史 ledger 残留。

第二轮复核由主线程完成。已亲自确认的 finding 标为 `confirmed`；只做代码证据复核、未运行动态复现的标为 `code-confirmed`；需后续产品判断的标为 `needs-decision`。

## 3. 自动化与构建结果

### 后端测试

```text
uv run python -m pytest tests/
213 passed, 6 skipped, 1 warning
```

### Hermetic 测试

```text
MinerU_API_KEY= MINERU_API_TOKEN= uv run python -m pytest tests/
213 passed, 6 skipped, 1 warning
```

说明：`uv run` 首次在沙箱内访问用户级 uv cache 被拒，后续按审批运行成功；后来某次审批因额度限制被拒，主线程改用项目内 `.venv\Scripts\python.exe` 执行临时库复现。

### 前端构建

```text
npm.cmd run build
vite build succeeded
```

警告：主 JS chunk 超过 500 kB，属于性能/工程治理问题，不作为阻断项。

### parser 子项目测试收集

```text
.\.venv\Scripts\python.exe -m pytest --collect-only -q parser\tests
62 tests collected, 3 collection errors
```

错误包括旧 `Ledger` import 与 `parser/scripts` import 路径不一致。根测试绿跑不会覆盖这些错误。

## 4. Findings

### P1-01 SQL 注入导致 summary 统计撒谎

- 状态：confirmed
- 影响：外部请求可污染 metadata/classification 的 summary 统计，导致审核 UI 和自动判断看到错误数量。主列表参数化，但 summary 绕过参数化。
- 证据：
  - `api/routes/metadata.py:102`：`risk_status_filter = "" if status == "all" else f"AND me.review_status = '{status}'"`
  - `api/routes/classification.py:352`：`ambiguity_status_filter = "" if status == "all" else f"AND ce.review_status = '{status}'"`
  - `api/routes/classification.py:363`：`priority_status_filter` 同类拼接。
- 复现：临时复制 DB 后请求：

```text
/api/metadata?status=' OR 1=1 -- 
/api/classification/extractions?status=' OR 1=1 -- 
```

- 实际结果：列表 `total=0`，但 summary 被扩大为全量/异常计数。例如 metadata risk/model summary 从 0 变为 260；classification ambiguity/priority summary 变为 373。
- 预期：非法 status 应 400，或所有 SQL 使用参数化并不改变 summary。
- 建议：对 `status` 做白名单校验；summary SQL 改参数化；补注入回归测试。

### P1-02 `works` quarantine/restore 路径处理会 500 或写错 DB 路径

- 状态：confirmed
- 影响：隔离/恢复核心治理流程会在合法历史数据 `original_name=NULL` 时直接 500；当 `original_name` 与 `source_path.name` 不同，文件实际移动位置与 DB 写入路径不一致。
- 证据：
  - `api/routes/works.py:368`：`dest = quarantine_dir / s["original_name"] or src.name`
  - `api/routes/works.py:382`：DB 写 `quarantine_dir / src.name`
  - `api/routes/works.py:423`、`api/routes/works.py:436` restore 同类问题。
- 复现：临时 DB 构造 `source_files.original_name=NULL`，请求 `POST /api/works/W-audit-null-original/quarantine`。
- 实际结果：`TypeError: unsupported operand type(s) for /: 'WindowsPath' and 'NoneType'`。
- 预期：统一使用 `dest = dir / (original_name or src.name)`，并把同一个 `dest` 写入 DB。
- 建议：抽 `move_source_files_to_quarantine()` nucleus；补 `original_name NULL` 和 `original_name != basename(source_path)` 测试。

### P1-03 Fresh schema 初始化不完整，`/api/works` 无法运行

- 状态：confirmed
- 影响：从空库或测试 fresh DB 只调用 ingest 核心 schema 初始化后，主 API 会崩溃；说明 schema 真相不统一。
- 证据：
  - `scripts/literature_ingest.py:291-302` 创建 `source_files` 时没有 `status`、`archived_at`、`archive_path`、`archive_reason`。
  - `api/routes/works.py:158` 查询 `source_files WHERE status = 'active'`。
  - `api/routes/works.py:209` 详情页同样依赖 `status='active'`。
- 复现：临时库调用 `ensure_core_schema()`，补最少 `work_relations` 表后请求 `/api/works`。
- 实际结果：`sqlite3.OperationalError: no such column: status`。
- 预期：fresh schema 与 live schema 一致，或 API 对旧 schema 有迁移/兼容。
- 建议：把 source_files archive/status 字段纳入核心 schema；增加 migration；补 fresh DB API 测试。

### P1-04 `scripts/dedup_cleanup.py` 不可编译

- 状态：confirmed
- 影响：事故修复/重复源清理脚本在需要时无法运行，破坏治理工具可信度。
- 证据：
  - `scripts/dedup_cleanup.py:11` 已有 `from __future__ import annotations`
  - `scripts/dedup_cleanup.py:19` 第二次出现 `from __future__ import annotations`
- 复现：

```text
.\.venv\Scripts\python.exe -m py_compile scripts\dedup_cleanup.py
```

- 实际结果：`SyntaxError: from __future__ imports must occur at the beginning of the file`
- 预期：脚本至少可编译，并有 dry-run 测试。
- 建议：删除重复 import；补 `py_compile` 或 smoke test。

### P1-05 ingest 文件复制与 DB commit 存在崩溃窗口

- 状态：code-confirmed
- 影响：进程在文件复制后、DB commit 前崩溃，会留下 DB 不知道的物理文件；重跑时可能产生 orphan/重复文件。
- 证据：
  - `scripts/literature_ingest.py:884` 先 `copy_planned_files(plan)`
  - `scripts/literature_ingest.py:885` 后 `insert_db_rows(...)`
  - `scripts/literature_ingest.py:842` DB commit 在 `insert_db_rows` 内部。
- 复现设计：临时库 monkeypatch `insert_db_rows` 在 copy 后抛异常；检查 `works/{id}/source` 已有文件但 DB 无 `source_files`。
- 预期：引入 staged manifest、两阶段状态、或 healthcheck/repair 检测 orphan。
- 建议：至少增加 healthcheck 项；长期改为可恢复 ingest transaction。

### P1-06 WorkDetail 分类保存不是原子操作，可能部分落库后失败

- 状态：code-confirmed
- 影响：用户编辑分类时，标量字段可能已保存、旧标签已删除，但新标签因非法值失败，造成状态不同步/标签丢失。
- 证据：
  - `web/src/views/WorkDetail.vue:181/192/203/214` 的 `n-select` 开启 `tag`，允许词表外输入。
  - `web/src/views/WorkDetail.vue:700-719` 先 `updateWork`，再逐个 delete/create tag，无事务、无回滚、无 try/catch。
  - `api/routes/classification.py:67` 后端对非法 tag 400。
- 复现设计：在详情页删除一个已有标签，再输入词表外标签保存。
- 预期：前端禁止词表外值，或后端提供事务化批量更新 endpoint。
- 建议：去掉 `tag` 自由输入；或新增 `PUT /classification/tags/{work_id}/replace` 原子替换。

### P2-01 Files API 信任 DB 路径，可读取库外文件

- 状态：confirmed
- 影响：若 SQLite 行被恶意或错误写入库外路径，`/api/files/{work_id}/content` 会读取任意本地文本文件；PDF 端点同理可返回库外文件。
- 证据：
  - `api/routes/files.py:27` 直接 `Path(run["content_md_path"])`
  - `api/routes/files.py:31` 直接 `read_text`
  - `api/routes/files.py:47-52` 直接 `FileResponse(source_path)`
- 复现：临时 DB 把 `content_md_path` 指向临时根下 `outside-secret.txt`，请求 `/api/files/W-file/content`。
- 实际结果：HTTP 200 返回 `AUDIT_OUTSIDE_CONTENT`。
- 建议：限制路径必须位于 `LIBRARY_ROOT/works` 或明确 allowlist 内；用 `resolve().relative_to(...)` 校验。

### P2-02 collector promote 路径边界不足

- 状态：confirmed
- 影响：`intake_candidates.local_pdf_path` 如果被污染为绝对路径或 `..` 相对路径，promote 会复制库外文件进 ingest。
- 证据：
  - `collector/paths.py:18-21` 绝对路径直接返回；相对路径只做 `api.db.LIBRARY_ROOT / p`。
  - `collector/ingest_bridge.py:36-47` resolved path 后直接 `shutil.copy2`。
- 复现：调用 `resolve_pdf_path("../outside-audit.pdf")`，解析结果在库根外。
- 建议：所有 candidate PDF 路径必须 resolve 后校验在 `LIBRARY_ROOT/_collector_cache` 或允许目录内。

### P2-03 已 ingested 的 approved candidate 可重复 promote

- 状态：confirmed
- 影响：不幂等。已晋升候选再次 promote 会尝试重新复制 PDF，遇到 exact duplicate 后 `plan.ingests` 为空，返回失败而不是既有结果。
- 证据：
  - `api/routes/intake.py:151-166` promote guard 只筛 `review_status='approved'`。
  - `collector/ingest_bridge.py:99-102` promote 后只改 `status='ingested'`，不改 `review_status`。
  - 真实库只读查询存在 `IC-c2e8477f status=ingested review_status=approved ingested_work_id=W-arxiv-1706.03762`。
- 建议：promote guard 排除 `status='ingested'`；已 ingested 直接返回 `ingested_work_id`。

### P2-04 parser 子项目测试被默认绿跑隐藏，且单独收集失败

- 状态：confirmed
- 影响：根测试绿不能代表 parser 子项目健康；旧 ledger 期测试残留会误导后续维护。
- 证据：
  - `pyproject.toml` 设置 `testpaths=["tests"]`。
  - 单独收集 `parser/tests` 有 3 个错误：`Ledger` import 不存在、`scripts.literature_inventory` import 不存在。
- 建议：要么归档旧 parser/tests，要么修复并纳入独立 CI profile。

### P2-05 测试依赖真实 DB 快照并大量 skip，存在假绿

- 状态：confirmed
- 证据：
  - `tests/test_api.py:26` 复制真实 `literature.sqlite`
  - `tests/test_analysis_runs.py:31` 复制真实 `literature.sqlite`
  - 多处 `self.skipTest("No ...")` / `pytest.skip("No eligible ...")`
- 影响：测试结果依赖当前私有数据形态，不能稳定证明行为。
- 建议：将关键测试迁移到最小 fixture DB；只保留少量 live snapshot smoke。

### P2-06 当前真实库已有若干一致性症状

- 状态：confirmed by read-only query
- 结果：
  - `works.parse_status` 与成功 parse runs 当前总体一致。
  - 存在 1 个 `approved + ingested` candidate。
  - 多个 `read_status='quarantined'` work 的 `source_files.status` 仍为 `active`，但路径在 `_quarantine`。
  - 抽样 500 个 source_files 中有 6 个 `source_path` 指向不存在文件。
- 建议：新增 healthcheck 检查 `source_path exists`、`quarantine path/status`、`candidate idempotency`。

### P2-07 文档/API 矩阵漂移

- 状态：code-confirmed
- 证据：
  - `TECHNICAL_OVERVIEW.md` 仍描述较少 API/页面。
  - 事实代码中 `api/main.py` 挂载 9 组 API，`web/src/router.js` 有 10 个页面路由。
  - README API 表缺 classification、intake、parse、ingest、duplicates merge-preview 等。
- 建议：修复 README/TECHNICAL_OVERVIEW，避免第三方或后续 agent 按旧地图操作。

### P2-08 若干后端端点有测试但无前端封装/入口

- 状态：needs-decision
- 端点：
  - `GET /metadata/agent/queue`
  - `POST /metadata/{ext_id}/supersede`
  - `POST /classification/extractions/batch-approve-with-tag`
- 证据：后端和测试存在，但 `web/src/api.js` 没有对应封装。
- 判断：如果这些是保留给脚本/API 用户，则不是缺陷；如果是人工审核工作流，应补 UI 或标注为 API-only。

### P2-09 `duplicates/{group_id}/merge-preview` 缺测试覆盖

- 状态：code-confirmed
- 证据：
  - `api/routes/duplicates.py:311` 实现。
  - `web/src/views/Duplicates.vue:271` UI 调用。
  - 现有 duplicate 测试覆盖 list/review，未覆盖 merge-preview。
- 建议：补 404、正常推荐 primary、空候选场景测试。

### P2-10 前端筛选与分页状态有合法空页问题

- 状态：code-confirmed
- 影响：用户在高页码切换筛选，UI 可能显示空态，即使第一页有结果。
- 证据：
  - `web/src/views/Works.vue` 多个筛选 `@update:value="loadData"`，未 reset page。
  - `web/src/views/ClassificationReview.vue:24` 状态切换直接 `loadList()`。
- 建议：所有筛选变更调用 reset，再加载。

### P2-11 WorkDetail 左侧列表多选筛选编码错误

- 状态：code-confirmed
- 影响：从 Works 带多选筛选进入 WorkDetail 后，左侧列表可能与原列表不一致。
- 证据：Works 用重复 query 参数；WorkDetail 将数组交给 `URLSearchParams(params)`，会编码为逗号字符串。
- 建议：复用 Works 的 append 多值逻辑。

### P3-01 `.env` 在共享工作区可读

- 状态：code-confirmed
- 说明：未入 git，但本地共享 agent 可读。不要在报告/日志打印 token。
- 建议：审核期间只读键名；必要时把密钥移到用户级 secret store。

### P3-02 前端 build 大 chunk

- 状态：confirmed
- 证据：Vite build 提示部分 chunk 超过 500 kB。
- 建议：后续做路由级 code splitting，非当前验收阻断。

### P3-03 ClassificationReview 模糊度按钮只改 UI 状态

- 状态：code-confirmed
- 证据：
  - `web/src/views/ClassificationReview.vue:9-16` 设置 `ambFilter`
  - `web/src/views/ClassificationReview.vue:554-560` 请求参数未使用 `ambFilter`
- 建议：若按钮语义是过滤，补请求参数和后端支持；若只是统计高亮，改 UI 文案。

## 5. 未覆盖或限制

- 未触网跑 arxiv/GitHub/MinerU/cloud smoke；网络/额度不是本轮目标。
- 未对真实库执行修复、迁移、promote、ingest、quarantine。
- 未启动真实 dev server 做 Playwright 页面点击；前端本轮完成 build 与代码契约审计。
- 子 agent 完成后工具无法继续寻址其中一个已完成 agent，所以第二轮复核由主线程执行并以临时复现为准。

## 6. 建议修复顺序

1. 修 P1 SQL 注入：status 白名单 + summary 参数化 + 回归测试。
2. 修 quarantine/restore：统一 path nucleus，修 `original_name` NULL，补 DB/磁盘一致性测试。
3. 修 fresh schema：补 `source_files.status/archive_*` 等字段和迁移测试。
4. 修 `dedup_cleanup.py` 编译错误并补 dry-run smoke。
5. 为 ingest/quarantine 增加 healthcheck/repair，至少能发现 orphan 文件和 DB/磁盘分裂。
6. 修 WorkDetail 分类保存原子性或禁用自由 tag。
7. 补 files/collector path boundary 校验。
8. 修 promote 幂等性。
9. 处理 parser/tests：归档旧测试或拆独立 profile。
10. 更新 README/TECHNICAL_OVERVIEW 与缺失测试。

## 7. 验收结论

本轮全量测试显示：功能主链路和根自动化测试总体可运行，但系统在安全边界、schema 一致性、DB/文件系统一致性和若干人工审核 UI 工作流上存在 P1 风险。

因此本轮结论为：

```text
CONDITIONAL PASS
```

修复 P1 后，应至少重跑：

```text
uv run python -m pytest tests/
MinerU_API_KEY= MINERU_API_TOKEN= uv run python -m pytest tests/
npm.cmd run build
.\.venv\Scripts\python.exe -m py_compile scripts\dedup_cleanup.py
```

并新增针对 SQL 注入、fresh schema、quarantine NULL/path mismatch、files path boundary、promote idempotency 的回归测试。
