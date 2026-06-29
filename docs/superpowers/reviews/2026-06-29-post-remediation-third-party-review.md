# 2026-06-29 整改后第三方复核报告

复核对象：当前 `master` 工作区，参考提交 `f35aeab fix: remediate all P1/P2/P3 third-party audit findings` 及用户提供的整改说明。

复核原则：整改说明仅作为导航，结论以当前代码、测试、真实 DB 只读检查和反向用例为准。

## 结论

**CONDITIONAL PASS / 未达到“全部 P1/P2/P3 已闭环”的最终验收口径。**

本轮未发现 P0。原 P1 中 SQL 注入、`/api/files` 路径边界、collector 路径边界、fresh schema、治理脚本编译、promote 幂等、parser 测试收集等关键项已有明显修复证据；但仍发现 1 个 P1、多个 P2/P3 残留，主要集中在分类审核标签词表绕过、metadata/classification quarantine 入口未复用安全文件名逻辑、测试环境不可干净复现、真实库治理状态仍不一致、healthcheck 口径漂移、未提交产物边界不清。

## 验证摘要

通过项：

- `npm.cmd run build`：通过。
- `.venv\Scripts\python.exe -m py_compile scripts\dedup_cleanup.py scripts\healthcheck_library.py`：通过。
- `.venv\Scripts\python.exe -m pytest --collect-only -q parser\tests`：2 tests collected。
- 重点整改回归子集：`77 passed, 1 skipped, 1 warning`。
- 清空 `MinerU_API_KEY` / `MINERU_API_TOKEN` 后，同一重点整改回归子集：`77 passed, 1 skipped, 1 warning`。

未通过/有条件通过项：

- `.venv\Scripts\python.exe -m pytest tests\ -q --basetemp=.codex_tmp\pytest_full -p no:cacheprovider`：`286 passed, 10 skipped, 2 failed, 1 warning`。
- 2 个失败均来自 `tests/test_batch_parse_cli.py`，测试 fixture 写死 `/tmp/x.pdf`、`/tmp/out/content.md`，在 Windows/sandbox 下变成 `\tmp\out\content.md` 并触发 `Permission denied`。
- 首次未指定 `--basetemp` 时，pytest 默认临时目录落到 `C:\Users\QR\AppData\Local\Temp\pytest-of-QR`，沙箱拒绝访问。这是环境限制，但也说明测试通过声明需要注明执行权限/临时目录前提。

## 已确认修复

- SQL status 注入：`api/security.py` 提供 `validate_status` / `build_status_filter`，metadata/classification 列表入口已调用，回归用例通过。
- 文件读取路径逃逸：`api/routes/files.py` 将 DB 路径限制在 `LIBRARY_ROOT/works` 下，重点回归通过。
- collector 路径逃逸：`collector/paths.py` 将相对/绝对路径限制在库根和允许子目录内，重点回归通过。
- works 主入口 quarantine/restore：`api/routes/works.py` 增加 `_sanitize_filename` / `_safe_dest_name` / `_unique_dest`，对 `None`、路径穿越、绝对路径、缺失文件和路径一致性有测试覆盖。
- fresh schema：相关测试通过。
- `dedup_cleanup.py`、`healthcheck_library.py` 可编译。
- parser 旧测试归档后，`parser/tests` 当前只收集 smoke 2 条，不再隐藏 import 错误。
- `intake/promote` 已有已入库候选的幂等返回逻辑。

## 残留问题

### P1-POST-01 分类审核仍可绕过词表写入任意 tag

证据：

- 直接创建 tag 的 API 在 `api/routes/classification.py` 中调用 `validate_tag_value`。
- 但分类 extraction 审核批准路径在写入 `work_classification_tags` 时没有调用 `validate_tag_value`，涉及 `review_extraction`、`batch_approve_low_ambiguity`、`batch_approve_with_tag` 三条写入路径。
- `web/src/views/ClassificationReview.vue` 的多选控件仍启用 `tag`，允许审核时输入非词表值。

反向用例结果：

```text
invalid_tag_review_status 200 {"ok":true,"applied":1}
persisted_tags [
  {"tag_group": "reading_lane", "tag_value": "__FREE_TAG_SHOULD_NOT_PERSIST__"},
  {"tag_group": "method_tags", "tag_value": "__BAD_METHOD__"}
]
```

影响：即使 `WorkDetail` 直接编辑入口禁用了自由 tag，分类审核页/模型抽取审核仍能污染正式分类标签表，破坏词表治理与后续筛选统计。

建议：后端所有写入 `work_classification_tags` 的 extraction apply/batch apply 路径统一调用 `validate_tag_value`；前端 `ClassificationReview` 对固定词表多选移除 `tag`；新增回归测试覆盖“edited_fields/model extracted_json 中包含非法 tag 时必须 400 或跳过并记录错误”。

### P2-POST-01 metadata/classification quarantine 未复用 works 安全文件名逻辑

证据：

- `api/routes/works.py` 的主 quarantine/restore 使用 `_safe_dest_name`，会拒绝 `../evil.pdf`。
- `api/routes/metadata.py` 与 `api/routes/classification.py` 的审核页 quarantine 仍使用 `Path(original_name).name` 后再检查 `..`，会先把 `../evil.pdf` 剥成 `evil.pdf`，导致脏 `original_name` 未被拒绝。

反向用例结果：

```text
classification_quarantine_traversal 200 ... _quarantine\W-class-q\evil.pdf True
metadata_quarantine_traversal 200 ... _quarantine\W-meta-q\evil.pdf True
```

影响：当前未复现路径逃逸，但三个 quarantine 入口行为不一致，且会把异常 DB 数据静默“清洗后成功”，不符合原整改目标中“original_name 安全校验/路径一致性”的强验收口径。

建议：metadata/classification quarantine 直接复用 `api.routes.works._safe_dest_name` 和 `_unique_dest`，或抽到共享 helper；增加 metadata/classification 入口的 `../evil.pdf`、`C:\tmp\evil.pdf`、`a/b.pdf`、缺失文件回归测试。

### P2-POST-02 全量测试不是仓库内可干净复现的绿

证据：

- 当前沙箱内全量 `tests/` 为 `286 passed, 10 skipped, 2 failed`。
- 失败点在 `tests/test_batch_parse_cli.py` 的 fixture 写死 Unix 风格绝对路径 `/tmp/x.pdf`、`/tmp/out`，Windows 下解析为根目录 `\tmp\out`，受限环境无法写入。

影响：整改报告中的“288 passed”可能依赖更宽权限或特定 OS/临时目录，第三方验收无法直接复现。

建议：测试 fixture 改用 `tmp_path / "x.pdf"`、`tmp_path / "out"`；不要在 DB fixture 中写死 `/tmp`；CI/验收命令固定 `--basetemp` 或设置仓库内 `TMP/TEMP`。

### P2-POST-03 真实库仍有 quarantine/source_files 状态不一致

只读查询结果：

```text
quarantined_active_count 16
```

这些记录均为 `works.read_status='quarantined'`，但 `source_files.status='active'`，且文件实际存在于 `_quarantine/...`。

影响：默认列表、统计、healthcheck 和后续归档/恢复逻辑可能出现语义漂移。整改说明中的“quarantine/restore 路径一致性”只覆盖新 API 行为，未完成真实库状态收敛。

建议：提供只读预览 + 显式 apply 的数据迁移脚本，将 quarantined work 下已在 `_quarantine` 的 source_files 标为 `archived` 或定义清晰的 quarantine status；同步更新 API 统计口径和 healthcheck。

### P2-POST-04 healthcheck 的 phantom 口径会误报归档/隔离路径

证据：

- `scripts/healthcheck_library.py` 只扫描 `works/*/source/*` 作为磁盘路径集合。
- 随后将所有 DB `source_files.source_path` 与该集合比较，因此 `_archive`、`_quarantine` 下实际存在的 DB 路径也会被列为 `phantom_db_entries`。

本轮只读 healthcheck 返回：

```text
orphan_files: 1
phantom_db_entries: 39
status_inconsistencies: 16
```

影响：healthcheck 结果无法直接作为治理验收依据，容易把“路径在归档/隔离区”误报为“DB 指向缺失文件”。

建议：按 `source_files.status` 和路径前缀分层扫描 `works`、`_archive`、`_quarantine`；phantom 应以 `Path(source_path).exists()` 为准，再单独报告“归档/隔离状态口径不一致”。

### P3-POST-01 工作区交付边界不清

当前状态：

- `master...origin/master [ahead 2]`。
- 未提交修改：`scripts/run_api.py`、`web/vite.config.js`，用于端口/代理可配置化。
- 未跟踪文档目录：`api/docs/`、`collector/docs/`、`docs/architecture/`、`docs/workflows/`、`parser/docs/`、`scripts/docs/`、`web/docs/`。
- `parser/docs/archive/latest_changes.diff` 约 1.7 MB，若纳入提交需确认是否必要。

影响：第三方验收无法判断这些产物是整改组成部分、临时验证辅助，还是应忽略的生成物。

建议：明确提交/忽略策略。端口配置若作为正式开发体验改进，应补文档并提交；未跟踪 docs 若是架构产物，应纳入提交并剔除大体积无关 archive diff，或加入 `.gitignore`/清理。

## 建议验收闸门

在最终验收前至少补齐：

1. 修复 P1-POST-01，并新增 extraction apply/batch apply 非法 tag 回归测试。
2. 修复 P2-POST-01，并新增 metadata/classification quarantine 原始文件名恶意值测试。
3. 修复 `tests/test_batch_parse_cli.py` 的 `/tmp` 假路径，确保 Windows/sandbox 下全量 `tests/` 可复现绿。
4. 明确真实库 quarantine source status 的治理策略，并让 healthcheck 能区分真实缺失与归档/隔离路径。
5. 清理或提交当前未提交/未跟踪产物，形成可验收的干净工作区。

