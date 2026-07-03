# 2026-06-29 第三方复核交接说明

接手对象：新的规划 agent / 本地整改规划负责人。

交接目的：继续推进“整改后第三方复核”发现的问题闭环。请不要把此前整改说明或本交接说明直接当作事实；它们只能作为索引。最终判断必须以当前代码、测试、真实 DB 只读检查和可复现反向用例为准。

## 当前仓库状态

- 工作目录：`D:\02_academic\doctoral\literature_library`
- 当前分支：`master`
- 当前分支相对 `origin/master`：ahead 2
- 已知主整改提交：`f35aeab fix: remediate all P1/P2/P3 third-party audit findings`
- 已知审核/整改文档提交：`60e65be docs(audit): add third-party audit report and remediation plan`

当前仍有未提交/未跟踪内容：

- 未提交修改：
  - `scripts/run_api.py`
  - `web/vite.config.js`
- 未跟踪文档/报告：
  - `docs/superpowers/reviews/2026-06-29-post-remediation-third-party-review.md`
  - `docs/superpowers/reviews/2026-06-29-third-party-audit-handoff-to-next-planner.md`
  - `api/docs/`
  - `collector/docs/`
  - `docs/architecture/`
  - `docs/workflows/`
  - `parser/docs/`
  - `scripts/docs/`
  - `web/docs/`

注意：不要随意 revert 上述改动。先判断它们是否属于正式交付、临时验证辅助或应加入忽略规则。

## 关键文档索引

- 原第三方审核报告：`docs/superpowers/reviews/2026-06-29-whole-project-third-party-audit-report.md`
- 整改方案：`docs/superpowers/reviews/2026-06-29-whole-project-third-party-audit-remediation-plan.md`
- 整改结果说明：`docs/superpowers/reviews/2026-06-29-whole-project-third-party-audit-remediation-result.md`
- 整改后第三方复核报告：`docs/superpowers/reviews/2026-06-29-post-remediation-third-party-review.md`
- 本交接说明：`docs/superpowers/reviews/2026-06-29-third-party-audit-handoff-to-next-planner.md`

## 已确认的正向修复

以下结论已通过代码审阅和重点回归验证：

- SQL 注入入口：`api/security.py` 增加 `validate_status` / `build_status_filter`，metadata/classification 列表入口已接入。
- 文件读取路径边界：`api/routes/files.py` 限制 DB 路径只能解析到 `LIBRARY_ROOT/works` 下。
- collector 路径边界：`collector/paths.py` 限制路径必须在库根和允许子目录内。
- works 主入口 quarantine/restore：`api/routes/works.py` 增加 `_sanitize_filename` / `_safe_dest_name` / `_unique_dest`。
- fresh schema：相关测试通过。
- `scripts/dedup_cleanup.py` 和 `scripts/healthcheck_library.py` 可编译。
- parser 测试收敛：`parser/tests` 当前只收集 smoke 2 条。
- intake promote：已入库候选有幂等返回逻辑。

## 当前第三方复核结论

结论为：**CONDITIONAL PASS，但不能支持“所有 P1/P2/P3 已完全闭环”的最终验收说法。**

未发现 P0。仍有 1 个 P1 和多个 P2/P3 残留，应作为下一阶段整改规划的主线。

## 必须优先处理的问题

### P1-POST-01 分类审核仍可绕过词表写入任意 tag

事实依据：

- `api/routes/classification.py` 中直接创建 tag 的 API 调用了 `validate_tag_value`。
- 但 extraction 审核批准路径写入 `work_classification_tags` 时没有调用 `validate_tag_value`。
- 涉及路径至少包括：
  - `review_extraction`
  - `batch_approve_low_ambiguity`
  - `batch_approve_with_tag`
- `web/src/views/ClassificationReview.vue` 中固定词表多选仍启用了 `tag`，可输入自定义值。

已复现反向用例：

```text
invalid_tag_review_status 200 {"ok":true,"applied":1}
persisted_tags [
  {"tag_group": "reading_lane", "tag_value": "__FREE_TAG_SHOULD_NOT_PERSIST__"},
  {"tag_group": "method_tags", "tag_value": "__BAD_METHOD__"}
]
```

建议目标：

- 后端所有写入 `work_classification_tags` 的 extraction apply / batch apply 路径统一调用 `validate_tag_value`。
- 非法 tag 的处理策略要明确：建议拒绝本次审核并返回 400，避免静默丢字段。
- 前端 `ClassificationReview.vue` 对固定词表多选移除 `tag`。
- 新增测试覆盖：
  - 单条 extraction review 中非法 tag 被拒绝。
  - batch approve 中非法 tag 不得写入正式表。
  - WorkDetail 固定词表路径保持可用。

### P2-POST-01 metadata/classification quarantine 未复用 works 安全文件名逻辑

事实依据：

- `api/routes/works.py` 主入口会对 `../evil.pdf` 返回 422。
- `api/routes/metadata.py` 和 `api/routes/classification.py` 审核页 quarantine 仍先 `Path(original_name).name`，再检查 `..`。
- 这会把 `../evil.pdf` 剥成 `evil.pdf` 并继续成功。

已复现反向用例：

```text
classification_quarantine_traversal 200 ... _quarantine\W-class-q\evil.pdf True
metadata_quarantine_traversal 200 ... _quarantine\W-meta-q\evil.pdf True
```

建议目标：

- 将 works 中 `_sanitize_filename` / `_safe_dest_name` / `_unique_dest` 抽到共享 helper，或至少在 metadata/classification 入口复用同一逻辑。
- 对 metadata/classification quarantine 增加回归：
  - `original_name = None` 可用。
  - `original_name = "../evil.pdf"` 返回 422 且不移动文件、不改 DB。
  - `original_name = "C:\\tmp\\evil.pdf"` 返回 422。
  - source file 缺失时不应半更新 DB。

### P2-POST-02 全量测试不是仓库内可干净复现的绿

事实依据：

- 使用仓库内临时目录运行：

```powershell
$env:TMP='D:\02_academic\doctoral\literature_library\.codex_tmp\tmp2'
$env:TEMP=$env:TMP
.\.venv\Scripts\python.exe -m pytest tests\ -q --basetemp=.codex_tmp\pytest_full -p no:cacheprovider
```

结果：

```text
286 passed, 10 skipped, 2 failed, 1 warning
```

失败来自：

- `tests/test_batch_parse_cli.py::test_run_one_writes_db_and_syncs_work_status`
- `tests/test_batch_parse_cli.py::test_sync_failure_does_not_rollback_parse_runs`

原因：

- 测试 fixture 写死 `/tmp/x.pdf`、`/tmp/out/content.md`。
- Windows/sandbox 下解析成 `\tmp\out\content.md`，写根目录触发 `Permission denied`。

建议目标：

- 测试 fixture 改用 `tmp_path / "x.pdf"` 和 `tmp_path / "out"`。
- DB 中的 `source_path` / `output_dir` 使用 fixture 生成的实际路径。
- 全量测试命令固定使用仓库内 `--basetemp`，避免外部临时目录权限影响。

### P2-POST-03 真实库仍有 quarantine/source_files 状态不一致

只读查询结果：

```text
quarantined_active_count 16
```

含义：

- 16 条记录满足 `works.read_status='quarantined' AND source_files.status='active'`。
- 文件实际存在于 `_quarantine/...`。

影响：

- API 统计、列表筛选、healthcheck、restore/归档策略可能出现口径漂移。

建议目标：

- 先写只读预览脚本或扩展 healthcheck，列出所有待修数据。
- 明确定义 quarantine 下 source_files 的合法状态：是 `archived`、新增 `quarantined`，还是仍保留 `active` 但所有统计都排除。
- 如果采用迁移修复，必须先备份 DB，并以显式 `--apply` 执行。

### P2-POST-04 healthcheck phantom 口径漂移

事实依据：

- `scripts/healthcheck_library.py` 只扫描 `works/*/source/*`。
- 但它拿所有 DB `source_files.source_path` 与该集合比较，导致 `_archive` / `_quarantine` 下实际存在的路径也被报为 phantom。

本轮只读结果：

```text
orphan_files: 1
phantom_db_entries: 39
status_inconsistencies: 16
```

建议目标：

- phantom 判断应以 `Path(source_path).exists()` 为主。
- 对 `works`、`_archive`、`_quarantine` 分区扫描，分别报告：
  - 真实缺失文件。
  - DB 状态与路径分区不一致。
  - 磁盘孤儿文件。

### P3-POST-01 工作区交付边界不清

建议目标：

- 判断 `scripts/run_api.py` 和 `web/vite.config.js` 的端口可配置化是否纳入正式提交。
- 判断未跟踪 docs 是否纳入提交。
- 特别检查 `parser/docs/archive/latest_changes.diff`，体积约 1.7 MB，通常不应无审查直接纳入。

## 已验证命令

通过：

```powershell
npm.cmd run build
```

```powershell
.\.venv\Scripts\python.exe -m py_compile scripts\dedup_cleanup.py scripts\healthcheck_library.py
```

```powershell
.\.venv\Scripts\python.exe -m pytest --collect-only -q parser\tests
```

```powershell
$env:TMP='D:\02_academic\doctoral\literature_library\.codex_tmp\tmp'
$env:TEMP=$env:TMP
.\.venv\Scripts\python.exe -m pytest tests\test_security_injection.py tests\test_quarantine_restore.py tests\test_files_path_boundary.py tests\test_collector_paths.py tests\test_promote_idempotent.py tests\test_fresh_schema.py tests\test_healthcheck.py tests\test_sample_db_api.py -q --basetemp=.codex_tmp\pytest -p no:cacheprovider
```

结果：`77 passed, 1 skipped, 1 warning`

清空 MinerU 环境变量后重点回归同样通过：

```powershell
$env:MinerU_API_KEY=''
$env:MINERU_API_TOKEN=''
```

未通过：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ -q --basetemp=.codex_tmp\pytest_full -p no:cacheprovider
```

结果：`286 passed, 10 skipped, 2 failed, 1 warning`

## 建议下一阶段分工

最多 4 个子 agent，并要求两轮复核。

### Agent A：分类词表闭环

范围：

- `api/routes/classification.py`
- `api/classification_vocab.py`
- `web/src/views/ClassificationReview.vue`
- 相关测试

任务：

- 所有 extraction apply/batch apply 写 tag 前校验词表。
- 前端移除固定词表多选的自由输入。
- 增加非法 tag 回归。

### Agent B：quarantine 入口一致性

范围：

- `api/routes/works.py`
- `api/routes/metadata.py`
- `api/routes/classification.py`
- 相关测试

任务：

- 抽共享安全文件名 helper。
- metadata/classification quarantine 复用 works 逻辑。
- 覆盖恶意 `original_name`、缺失文件、不半更新 DB。

### Agent C：测试可复现性与 healthcheck

范围：

- `tests/test_batch_parse_cli.py`
- `scripts/healthcheck_library.py`
- healthcheck 测试

任务：

- 消除 `/tmp` 写死路径。
- 修正 healthcheck phantom 口径。
- 增加 archive/quarantine 路径存在但不应 phantom 的测试。

### Agent D：真实库治理与交付边界

范围：

- 只读 DB 检查脚本或 healthcheck 扩展。
- 未提交/未跟踪文件梳理。
- 最终整改结果文档。

任务：

- 输出真实库不一致记录清单。
- 提供显式 `--apply` 修复计划，不默认写库。
- 判断 docs 和端口配置是否提交。

## 两轮复核要求

第一轮：

- 每个 agent 自测并提交结果。
- 规划负责人运行重点回归和对应反向用例。

第二轮：

- 由非实施 agent 交叉复核。
- 必须重新执行：
  - 全量 `tests/`
  - 重点安全/路径/词表回归
  - `npm run build`
  - parser collect
  - `py_compile`
  - healthcheck 只读

最终输出：

- 新整改结果文档。
- 命令结果摘要。
- 残留问题列表。
- 是否达到最终 PASS 的明确结论。

