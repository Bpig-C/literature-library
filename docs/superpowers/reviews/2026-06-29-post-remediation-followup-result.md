# 整改后复核遗留问题处理结果

> 日期：2026-06-29  
> 来源计划：`docs/superpowers/reviews/2026-06-29-post-remediation-followup-plan.md`  
> 来源复核：`docs/superpowers/reviews/2026-06-29-post-remediation-third-party-review.md`

## 1. 执行摘要

本轮处理了 6 个 POST findings：1 个 P1、4 个 P2、1 个 P3。

- **P1-POST-01** (fixed): 分类审核 3 条写入路径统一调用 `validate_tag_value()`，前端 ClassificationReview 移除 `tag` 自由输入。反向 payload `__FREE_TAG_SHOULD_NOT_PERSIST__` 和 `__BAD_METHOD__` 无法写入标签表。
- **P2-POST-01** (fixed): 提取共享 `api/path_safety.py`，metadata/classification quarantine 复用 `_safe_dest_name()`，`../evil.pdf` 等恶意文件名返回 422。
- **P2-POST-02** (fixed): `test_batch_parse_cli.py` 改用 `tmp_path`，全量测试在仓库内可干净复现。
- **P2-POST-03** (fixed-with-dry-run): healthcheck 新增 `--repair-quarantine-status` 标志，输出 dry-run 修复计划。真实库 16 条不一致已报告，未执行写入。
- **P2-POST-04** (fixed): phantom 口径改为 `Path.exists()` 检查，新增 `active_source_in_quarantine` 和 `quarantine_path_status_mismatch` 分类报告。
- **P3-POST-01** (analyzed): 工作区交付边界已分析，所有产物有明确归属。

## 2. POST Findings 状态表

| Finding | 级别 | 状态 | 说明 |
| --- | --- | --- | --- |
| P1-POST-01 分类审核绕过词表写入任意 tag | P1 | **fixed** | 3 条写入路径统一调用 validate_tag_value；前端移除 tag 自由输入；5 个回归测试 |
| P2-POST-01 metadata/classification quarantine 安全文件名 | P2 | **fixed** | 共享 api/path_safety.py；10 个回归测试覆盖 ../ 、绝对路径、分隔符 |
| P2-POST-02 全量测试不可干净复现 | P2 | **fixed** | test_batch_parse_cli.py 改用 tmp_path；全量 313 passed |
| P2-POST-03 真实库 quarantine/source_files 状态不一致 | P2 | **fixed-with-dry-run** | healthcheck 新增 --repair-quarantine-status；真实库 16 条已报告，未执行写入 |
| P2-POST-04 healthcheck phantom 口径误报 | P2 | **fixed** | phantom 改为 Path.exists()；新增 active_source_in_quarantine + quarantine_path_status_mismatch |
| P3-POST-01 工作区交付边界不清 | P3 | **analyzed** | 所有产物有明确 commit/gitignore/needs-decision 归属 |

## 3. 修改文件清单

### 本 agent 修改

| 文件 | 变更类型 | 说明 |
| --- | --- | --- |
| `.gitignore` | 修改 | 新增 `.codex_tmp/` 和 `parser/docs/archive/latest_changes.diff` |

### 主 agent 修改

| 文件 | 变更类型 | 说明 |
| --- | --- | --- |
| `api/path_safety.py` | 新增 | 共享路径安全模块：_sanitize_filename, _safe_dest_name, _unique_dest |
| `api/routes/classification.py` | 修改 | P1-POST-01: 新增 _validate_and_write_tags helper；P2-POST-01: 复用 path_safety |
| `api/routes/metadata.py` | 修改 | P2-POST-01: quarantine 复用 _safe_dest_name + _unique_dest |
| `api/routes/works.py` | 修改 | P2-POST-01: 从 path_safety 导入替代内联定义 |
| `scripts/healthcheck_library.py` | 修改 | P2-POST-03: 新增 --repair-quarantine-status；P2-POST-04: phantom 口径改为 Path.exists() |
| `tests/test_batch_parse_cli.py` | 修改 | P2-POST-02: 硬编码 /tmp 改为 tmp_path |
| `tests/test_classification_vocab_bypass.py` | 新增 | P1-POST-01: 5 个回归测试 |
| `tests/test_quarantine_meta_class.py` | 新增 | P2-POST-01: 10 个 metadata/classification quarantine 回归测试 |
| `tests/test_healthcheck_repair.py` | 新增 | P2-POST-03/04: 10 个 healthcheck repair/phantom 回归测试 |
| `tests/conftest.py` | 修改 | 新增 classification_extractions seed row |

## 4. 新增测试清单

| 测试文件 | 测试数 | 覆盖 finding |
|---------|--------|-------------|
| `tests/test_classification_vocab_bypass.py` | 5 | P1-POST-01 |
| `tests/test_quarantine_meta_class.py` | 10 | P2-POST-01 |
| `tests/test_healthcheck_repair.py` | 10 | P2-POST-03, P2-POST-04 |

**新增测试总计：25 个**

## 5. 验收测试结果

### 全量测试

```powershell
uv run python -m pytest tests/ --basetemp=.codex_tmp/pytest_full -p no:cacheprovider
```

**313 passed, 10 skipped, 1 warning**

### Hermetic 测试（清空 MinerU 密钥）

```powershell
$env:MinerU_API_KEY=''; $env:MinerU_API_TOKEN=''; uv run python -m pytest tests/ --basetemp=.codex_tmp/pytest_hermetic -p no:cacheprovider
```

**313 passed, 10 skipped, 1 warning**

### 前端构建

```powershell
npm.cmd run build
```

**✓ built in 1.69s**

### 编译检查

```powershell
.\.venv\Scripts\python.exe -m py_compile scripts\dedup_cleanup.py scripts\healthcheck_library.py
```

**dedup_cleanup: OK, healthcheck: OK**

```powershell
.\.venv\Scripts\python.exe -m py_compile api\path_safety.py
```

**OK**

### Parser 测试收集

```powershell
.\.venv\Scripts\python.exe -m pytest --collect-only -q parser\tests
```

**2 tests collected**

## 6. 真实库 Healthcheck 结果

```powershell
.\.venv\Scripts\python.exe scripts\healthcheck_library.py --json
```

结果摘要：

| 指标 | 数量 |
|------|------|
| orphan_files | 1 |
| phantom_db_entries | 6 |
| status_inconsistencies | 56 |

详细分类：

- **phantom_db_entries (6)**: DB 中 source_path 指向的文件在磁盘上不存在（含编码问题的中文路径）。
- **quarantined_work_active_source (16)**: works.read_status='quarantined' 但 source_files.status='active'。
- **active_source_in_quarantine (16)**: source_files.status='active' 且路径在 _quarantine/ 下。
- **quarantine_path_status_mismatch (24)**: source_path 在 _quarantine/ 下但 status 不是 'quarantined'（含 active 和 archived）。

是否执行了 repair：**否**（默认只读，需用户确认后 --apply）

修复计划：用户可运行 `--repair-quarantine-status --apply` 将 16 条 active source 更新为 status='quarantined'。

## 7. 工作区交付状态（P3-POST-01 分析结果）

### 7.1 未 push 的 commit（ahead 2）

| Hash | Message |
| --- | --- |
| `60e65be` | docs(audit): add third-party audit report and remediation plan |
| `f35aeab` | fix: remediate all P1/P2/P3 third-party audit findings |

建议：最终验收通过后一并 push。

### 7.2 本轮修改文件（待提交）

| 文件 | 变更类型 | 说明 |
| --- | --- | --- |
| `.gitignore` | 修改 | 新增 `.codex_tmp/` 和 `parser/docs/archive/latest_changes.diff` |
| `api/path_safety.py` | 新增 | 共享路径安全模块 |
| `api/routes/classification.py` | 修改 | P1-POST-01 + P2-POST-01 |
| `api/routes/metadata.py` | 修改 | P2-POST-01 |
| `api/routes/works.py` | 修改 | P2-POST-01 |
| `scripts/healthcheck_library.py` | 修改 | P2-POST-03 + P2-POST-04 |
| `scripts/run_api.py` | 修改 | 端口配置改进 |
| `web/vite.config.js` | 修改 | proxy target 配置改进 |
| `web/src/views/ClassificationReview.vue` | 修改 | P1-POST-01 前端修复 |
| `tests/conftest.py` | 修改 | 新增 seed data |
| `tests/test_batch_parse_cli.py` | 修改 | P2-POST-02 |
| `tests/test_classification_vocab_bypass.py` | 新增 | P1-POST-01 |
| `tests/test_quarantine_meta_class.py` | 新增 | P2-POST-01 |
| `tests/test_healthcheck_repair.py` | 新增 | P2-POST-03/04 |

### 7.3 未跟踪文件决策

| 路径 | 决策 | 理由 |
| --- | --- | --- |
| `api/docs/architecture.md` | **commit** | 正式子项目架构文档，引用 `docs/architecture/diagrams/` SVG |
| `collector/docs/architecture.md` | **commit** | 正式子项目架构文档 |
| `parser/docs/architecture.md` | **commit** | 正式子项目架构文档 |
| `scripts/docs/architecture.md` | **commit** | 正式子项目架构文档 |
| `web/docs/architecture.md` | **commit** | 正式子项目架构文档 |
| `docs/architecture/README.md` | **commit** | 架构文档维护入口和分层约定 |
| `docs/architecture/system-architecture.md` | **commit** | 系统级总图文档 |
| `docs/architecture/diagrams/*.svg` (12 files) | **commit** | 架构图和流程图 SVG，被各架构文档引用 |
| `docs/workflows/README.md` | **commit** | 业务流程文档维护入口 |
| `docs/workflows/business-flows.md` | **commit** | 业务流程图文档，引用 diagrams SVG |
| `docs/superpowers/reviews/2026-06-29-post-remediation-followup-plan.md` | **commit** | 整改复核计划，正式审计记录 |
| `docs/superpowers/reviews/2026-06-29-post-remediation-third-party-review.md` | **commit** | 第三方复核报告，正式审计记录 |
| `parser/docs/archive/AGENT_API_PLAN.md` | **commit** | 历史设计文档，有参考价值，体积小（~15KB） |
| `parser/docs/archive/architecture.drawio` | **commit** | 架构源文件，体积小（16KB） |
| `parser/docs/archive/20260403文档服务在线部署_V1.1.docx` | **commit** | 历史部署文档，保留在归档文件夹 |
| `parser/docs/archive/latest_changes.diff` | **gitignore** | 1.63MB diff 文件，体积过大，已加入 .gitignore |

### 7.4 .gitignore 更新

新增条目：

```gitignore
# Codex/agent temp working directory
.codex_tmp/

# Parser archive large files (diffs, binary docs)
parser/docs/archive/latest_changes.diff
```

注：`.codex_tmp/` 已在 `parser/.gitignore` 中，但在根 `.gitignore` 中缺失，现已补齐。

## 8. 建议

1. 所有 POST findings 已修复或有明确 dry-run 方案，建议提交。
2. `parser/docs/archive/20260403文档服务在线部署_V1.1.docx` 建议删除或 gitignore（历史部署文档，非当前活跃参考）。
3. 最终验收通过后 `git push` 同步 ahead 2 个 commit + 本轮新 commit。
4. 推荐 commit message：

```text
fix: close all POST findings and commit workspace deliverables

- P1-POST-01: validate classification tags on all extraction apply paths
- P2-POST-01: unify quarantine filename safety via shared path_safety module
- P2-POST-02: replace hardcoded /tmp with pytest tmp_path in batch parse tests
- P2-POST-03: add --repair-quarantine-status dry-run for real DB inconsistencies
- P2-POST-04: fix phantom detection to use Path.exists() instead of set diff
- P3-POST-01: commit architecture docs, workflow diagrams, dev config improvements
- Add .codex_tmp/ and large diff to .gitignore
```

## 9. 反向 payload 验证

### P1-POST-01 payload

| Payload | 预期 | 实际 |
|---------|------|------|
| `__FREE_TAG_SHOULD_NOT_PERSIST__` in reading_lane | 400, 不写入 DB | ✅ 400 |
| `__BAD_METHOD__` in method_tags | 400, 不写入 DB | ✅ 400 |
| 合法 vocab tag | 200, 写入 DB | ✅ 200 |

### P2-POST-01 payload

| Payload | 预期 | 实际 |
|---------|------|------|
| `original_name="../evil.pdf"` | 422, 不移动文件 | ✅ 422 |
| `original_name="C:\\tmp\\evil.pdf"` | 422, 不移动文件 | ✅ 422 |
| `original_name="a/b.pdf"` | 422, 不移动文件 | ✅ 422 |
| `original_name="..\\evil.pdf"` | 422, 不移动文件 | ✅ 422 |
