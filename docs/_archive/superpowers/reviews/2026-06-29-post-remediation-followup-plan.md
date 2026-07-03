# 整改后第三方复核遗留问题解决方案

> 日期：2026-06-29  
> 来源报告：`docs/superpowers/reviews/2026-06-29-post-remediation-third-party-review.md`  
> 目标：补齐最终验收前的剩余闸门。本文只覆盖 post-remediation 复核发现的残留问题，不重复上一轮已闭环事项。  
> 当前结论：未发现 P0；保留 **CONDITIONAL PASS**。最终验收前必须先关闭 `P1-POST-01`，并处理 P2/P3 交付边界。

## 0. 执行规则

1. 真实 `literature.sqlite`、`works/`、`_archive/`、`_quarantine/` 默认只读。任何 repair/migration 必须先输出 dry-run 计划，再由用户确认后显式 `--apply`。
2. 所有反向用例优先使用临时 DB、`tmp_path` 和仓库内 `.codex_tmp`，不得写死 `/tmp`、`C:\Users\...\Temp` 或系统根目录。
3. 修复完成后必须更新 `docs/superpowers/reviews/2026-06-29-whole-project-third-party-audit-remediation-result.md` 或追加新的最终复核记录，不能继续声称“全部闭环”而不解释本轮 POST findings。
4. 完成后工作区必须可解释：要么提交，要么明确哪些文件应忽略/删除/另行提交。

## 1. P1-POST-01 分类审核仍可绕过词表写入任意 tag

### 问题

`api/routes/classification.py` 的直接 tag 创建 API 已调用 `validate_tag_value()`，但分类 extraction 审核批准路径仍可能把 `extracted_json` 或人工 `edited_fields` 中的非法 tag 写入 `work_classification_tags`。

受影响路径：

- `review_extraction`
- `batch_approve_low_ambiguity`
- `batch_approve_with_tag`
- 前端 `web/src/views/ClassificationReview.vue` 的多选控件仍允许 `tag` 自由输入。

### 目标

任何写入 `work_classification_tags` 的路径都必须通过同一套词表校验。非法 tag 不能进入正式标签表。

### 建议改法

1. 在后端抽出共享写入 helper，例如：
   - `_validate_extracted_tags(extracted: dict) -> list[dict]`
   - `_insert_classification_tags(conn, work_id, extracted, confidence, evidence, now, *, source)`
2. helper 覆盖 tag groups：
   - `reading_lane`
   - `artifact_focus`
   - `risk_domain`
   - `method_tags`
3. 对每个值调用 `validate_tag_value(group, value)`。
4. 非法值处理策略二选一，推荐方案 A：
   - 方案 A：整次审核/批量应用返回 HTTP 400，错误中列出非法 group/value，不写任何 scalar 或 tag。
   - 方案 B：跳过非法 tag，记录 `review_note/fix_action`，但不能静默成功。若选 B，必须清楚记录跳过数量和原因。
5. 前端 `ClassificationReview.vue` 固定词表多选去掉 `tag` 自由输入；保留 `filterable` 可以搜索，但不能创建新值。
6. 如果模型历史抽取中已有非法值，审核页应展示 warning，并要求修正后才能 approve/apply。

### 测试要求

新增或扩展测试，覆盖：

1. `PATCH /api/classification/extractions/{ext_id}/review`：`edited_fields` 中含非法 `reading_lane` / `method_tags`，应 400 或跳过且不落 `work_classification_tags`。
2. 同一路径中 `extracted_json` 原始模型输出含非法 tag，approve 时不得写入。
3. `POST /api/classification/extractions/batch-approve-low-risk`：候选中含非法 tag，不得污染标签表。
4. `POST /api/classification/extractions/batch-approve-with-tag`：同上。
5. 合法 tag 仍能正常写入。

### 验收

反向 payload 中的：

```text
__FREE_TAG_SHOULD_NOT_PERSIST__
__BAD_METHOD__
```

不得出现在 `work_classification_tags`。

## 2. P2-POST-01 metadata/classification quarantine 未复用安全文件名逻辑

### 问题

`works` 主入口已经用 `_safe_dest_name()` 拒绝恶意 `original_name`，但 metadata/classification 审核页 quarantine 入口仍先做 `Path(original_name).name`，导致 `../evil.pdf` 被静默剥成 `evil.pdf` 并成功隔离。

### 目标

三个 quarantine 入口文件名策略一致。脏 `original_name` 不应被静默清洗成功。

### 建议改法

1. 把 `api/routes/works.py` 中 `_sanitize_filename()`、`_safe_dest_name()`、`_unique_dest()` 移到共享模块，例如：
   - `api/path_safety.py`
   - 或 `api/routes/_file_moves.py`
2. `works.py`、`metadata.py`、`classification.py` 全部复用共享 helper。
3. metadata/classification quarantine 遇到非法 `original_name` 时返回 422，不移动文件、不更新 DB。
4. 统一目标文件已存在时的 `_unique_dest()` 行为，避免覆盖。

### 测试要求

为 metadata/classification quarantine 入口新增临时 DB + 临时文件树测试：

1. `original_name="../evil.pdf"` 返回 422，源文件仍在原处，DB 未变。
2. `original_name="C:\\tmp\\evil.pdf"` 返回 422。
3. `original_name="a/b.pdf"` 或 `"..\\evil.pdf"` 返回 422。
4. `original_name=NULL` 使用 `source_path.name` 正常隔离。
5. `original_name != basename(source_path)` 时 DB 路径和实际移动路径一致。

## 3. P2-POST-02 全量测试不是仓库内可干净复现的绿

### 问题

`tests/test_batch_parse_cli.py` fixture 写死 `/tmp/x.pdf`、`/tmp/out/content.md`。在 Windows/sandbox 下会解析到根目录 `\tmp\out` 并触发权限问题。

### 目标

全量 `tests/` 在仓库内可干净复现，不依赖系统 `/tmp` 或用户级临时目录权限。

### 建议改法

1. 修改 `tests/test_batch_parse_cli.py`：
   - 用 `tmp_path / "x.pdf"` 代替 `/tmp/x.pdf`。
   - 用 `tmp_path / "out" / "content.md"` 代替 `/tmp/out/content.md`。
   - 如果 DB 中需要字符串路径，写入 `str(tmp_path / ...)`。
2. 检查其他测试中是否仍有硬编码 `/tmp/`、`\tmp\`、`C:\Users\...\Temp`。
3. 在验收命令中固定仓库内 basetemp：

```powershell
uv run python -m pytest tests/ --basetemp=.codex_tmp/pytest_full -p no:cacheprovider
```

4. `.codex_tmp/` 应加入 `.gitignore` 或确认已被忽略。

### 测试要求

至少运行：

```powershell
uv run python -m pytest tests/test_batch_parse_cli.py --basetemp=.codex_tmp/pytest_batch -p no:cacheprovider
uv run python -m pytest tests/ --basetemp=.codex_tmp/pytest_full -p no:cacheprovider
```

## 4. P2-POST-03 真实库 quarantine/source_files 状态不一致

### 问题

只读查询发现 16 条：

```text
works.read_status='quarantined' AND source_files.status='active'
```

且文件实际位于 `_quarantine/...`。

### 目标

定义并执行可审计的真实库治理策略，让 quarantine 状态和 source file 状态口径一致。

### 需要先做的产品/数据口径决定

二选一：

1. **推荐：新增或使用 `source_files.status='quarantined'`。**  
   语义最清楚，但需要确认现有 API 是否只认 `active/archived`。
2. **保守：将 quarantined work 下位于 `_quarantine` 的 source_files 标为 `archived`，并写 `archive_reason='quarantined'`。**  
   更贴近当前 `archive_*` 字段，但会把隔离和归档混在一起。

### 建议改法

1. 新增 repair 脚本或扩展 `scripts/healthcheck_library.py`：
   - 默认只读输出待修复 rows。
   - `--apply` 才更新 DB。
   - 更新前打印 work_id、source_file_id、旧状态、新状态、路径。
2. `works.py` 的 quarantine/restore 新行为也要同步更新 `source_files.status/archive_*`，否则真实库修完后新操作又会制造不一致。
3. `restore` 时恢复 source status 为 `active`，并清理或保留 archive 字段需要明确。

### 测试要求

1. 临时库构造 quarantined work + active source in `_quarantine`，healthcheck 能报告。
2. `--apply` 后状态按选定策略更新。
3. `restore` 后 source file 状态回到可被详情页/列表正确识别的状态。

## 5. P2-POST-04 healthcheck phantom 口径误报归档/隔离路径

### 问题

当前 healthcheck 只扫描 `works/*/source/*`，再把所有 DB `source_path` 与这个集合比对。结果是 `_archive`、`_quarantine` 中实际存在的 DB 路径会被误报为 `phantom_db_entries`。

### 目标

`phantom_db_entries` 只表示 DB 指向的文件不存在。归档/隔离区路径应进入单独状态口径检查。

### 建议改法

1. phantom 判断改为：

```python
if not Path(source_path).exists():
    phantom_db_entries.append(...)
```

2. 另设分类报告：
   - `active_source_outside_works`
   - `quarantined_work_active_source`
   - `archived_status_inside_works`
   - `quarantine_path_status_mismatch`
3. orphan 扫描仍可扫描 `works/*/source/*`，但要明确 orphan 是“活跃 source 区未入库文件”，不是全库所有未入库文件。
4. 如果要扫描 `_archive` / `_quarantine` 中未入库文件，应分开命名，例如 `untracked_archive_files`、`untracked_quarantine_files`。

### 测试要求

1. DB `source_path` 指向存在的 `_quarantine/...` 文件，不应进入 phantom。
2. DB `source_path` 指向不存在文件，应进入 phantom。
3. active source 指向 `_quarantine` 应进入状态不一致，而不是 phantom。
4. `works/*/source/orphan.pdf` 仍被报告为 orphan。

## 6. P3-POST-01 工作区交付边界不清

### 问题

当前工作区存在：

- 已提交但未 push：`master...origin/master [ahead 2]`。
- 未提交修改：`scripts/run_api.py`、`web/vite.config.js`。
- 未跟踪文档目录：`api/docs/`、`collector/docs/`、`docs/architecture/`、`docs/workflows/`、`parser/docs/`、`scripts/docs/`、`web/docs/`。
- 大文件风险：`parser/docs/archive/latest_changes.diff` 约 1.7 MB。

### 目标

最终验收时工作区干净，且每个产物都有明确归属。

### 建议改法

1. `scripts/run_api.py` 和 `web/vite.config.js`：
   - 若保留为正式开发体验改进，补 README 启动说明后提交。
   - 若只是手动验证临时修改，回退或另行记录。
2. 未跟踪 docs 目录：
   - 逐目录检查内容来源。
   - 架构/工作流文档如果是正式产物，纳入提交。
   - 大体积 `latest_changes.diff` 若只是临时归档，不纳入提交；加入 `.gitignore` 或删除。
3. 最终执行：

```powershell
git status --short --branch
git log --oneline origin/master..HEAD
```

并在结果文档中说明：已提交哪些、未 push 几个 commit、是否有故意未提交文件。

## 7. 最终验收命令

完成所有 POST findings 后运行：

```powershell
uv run python -m pytest tests/ --basetemp=.codex_tmp/pytest_full -p no:cacheprovider
$env:MinerU_API_KEY=''; $env:MinerU_API_TOKEN=''; uv run python -m pytest tests/ --basetemp=.codex_tmp/pytest_hermetic -p no:cacheprovider
npm.cmd run build
.\.venv\Scripts\python.exe -m py_compile scripts\dedup_cleanup.py scripts\healthcheck_library.py
.\.venv\Scripts\python.exe -m pytest --collect-only -q parser\tests
```

并补充只读真实库诊断：

```powershell
.\.venv\Scripts\python.exe scripts\healthcheck_library.py --json
```

如果需要真实库 repair，必须先输出 dry-run 计划，并由用户确认后再执行 `--apply`。

## 8. 最终结果文档要求

完成后新建或更新：

```text
docs/superpowers/reviews/2026-06-29-post-remediation-followup-result.md
```

必须包含：

1. 每个 POST finding 的状态：fixed / documented / needs-decision。
2. 修改文件清单。
3. 新增测试清单。
4. 所有验收命令结果。
5. 真实库 healthcheck 结果；若未执行 repair，明确说明。
6. 工作区交付状态：未提交、已提交未 push、未跟踪文件处理策略。
