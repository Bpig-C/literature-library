# 整改后遗留问题 — 独立复核报告（第三方审核者）

> 日期：2026-06-29
> 角色：第三方审核者（非实施方）。本报告由独立 agent 撰写，**不采信实施模型自述**，所有结论均附本 agent 本轮亲自执行的命令/文件/行号证据。
> 复核对象：实施模型声称 "所有 POST findings 已修复"（见 `2026-06-29-post-remediation-followup-result.md`）。
> 复核依据计划：`2026-06-29-post-remediation-followup-plan.md`。

## 0. 最终结论

**CONDITIONAL PASS → 可升 PASS（条件：用户提交并 push 本轮改动）。**

- 1 个 P1 + 4 个 P2 的代码/测试类发现**全部独立验证为真实修复**（fixed）。
- 真实库 `literature.sqlite` **本轮全程只读，零写入**（已用库指纹前后比对铁证）。
- 唯一未闭环的是 P3-POST-01（交付边界）——实施方选择"分析归类、留给用户提交"，符合计划 §0 规则 3 的允许路径，但意味着"工作区干净"这一闸门**尚未达成**，需用户做一次 commit/push。

> 升 PASS 的唯一前置：执行一次 commit + push（见 §6 建议）。代码侧无阻塞。

## 1. 验收命令独立复跑结果

以下命令均由本 agent 在本轮亲自执行（非引用实施方输出）。

| 命令 | 结果 | 证据 |
| --- | --- | --- |
| `uv run python -m pytest tests/ --basetemp=.codex_tmp/pytest_full` | **313 passed, 10 skipped** | exit 0，本 agent 后台运行确认 |
| `MinerU_API_KEY='' MinerU_API_TOKEN='' pytest tests/`（hermetic） | **313 passed, 10 skipped** | exit 0 |
| `pytest tests/test_classification_vocab_bypass.py test_quarantine_meta_class.py test_healthcheck_repair.py` | **25 passed** | 3 个新文件 25 个用例全过 |
| `npm.cmd run build`（须在 `web/` 下） | **✓ built in 886ms** | 根目录无 package.json；须 `cd web` |
| `py_compile scripts/dedup_cleanup.py scripts/healthcheck_library.py api/path_safety.py` | **OK** | exit 0 |
| `pytest --collect-only -q parser/tests` | **2 collected** | exit 0 |
| `scripts/healthcheck_library.py --json`（只读） | orphan 1 / phantom 6 / status_inconsistencies 56 / **applied_fixes 0** | DB 未写 |

## 2. 逐项独立验证

### P1-POST-01 分类审核绕过词表写入任意 tag — ✅ FIXED

- **后端 helper 真实存在且逻辑正确**：`api/routes/classification.py:51` `_validate_and_write_tags` 先对全部 tag group 逐值 `validate_tag_value`，**收集所有非法值后统一 `raise HTTPException(400)` 列出非法项，通过后才 INSERT**（classification.py:67-100）。非法 tag 物理上无法落库。
- **三条 apply 路径均调用该 helper**：`review_extraction`（:612）、`batch_approve_low_ambiguity`（:727）、`batch_approve_with_tag`（:851）。直接 tag 创建 API（:124）亦单独校验。
- **前端移除自由 tag 输入**：`web/src/views/ClassificationReview.vue` 的 el-select 用 `filterable`（可搜索，:202/:217/:226）但**无 `allow-create`/`create-tag`**（grep 全文无命中 → 无法新建值）；并新增 `invalid-tags-banner`（:185）+ 词表校验（:425/:540）。
- **反向测试真实有效**：`tests/test_classification_vocab_bypass.py` 用实际 payload `__FREE_TAG_SHOULD_NOT_PERSIST__`（reading_lane）、`__BAD_METHOD__`（method_tags）、`__INVALID_BATCH_TAG__`/`__INVALID_ARTIFACT__`，断言 **400 且 `work_classification_tags` 无残留**（:64/:83/:174/:216），同时验证合法 tag 仍 200 写入。非摆设。5/5 过。

### P2-POST-01 quarantine 安全文件名未复用 — ✅ FIXED

- **共享模块真实**：`api/path_safety.py` 的 `_sanitize_filename`（:14）拒绝绝对路径、含 `..`、含 `/` 或 `\` 的名字，统一 `HTTPException(422)`；`_safe_dest_name`（:34）、`_unique_dest`（:42）齐备。
- **三个路由全部复用**（grep 铁证）：`classification.py:965`、`metadata.py:491`、`works.py:374/:441` 均 `from ..path_safety import`。策略一致。
- **测试**：`tests/test_quarantine_meta_class.py` 10 用例覆盖 `../evil.pdf`、绝对路径、分隔符、NULL→basename、basename 一致性。随 25 测试批次 10/10 过。

### P2-POST-02 全量测试不可干净复现 — ✅ FIXED

- **源码核实**：通读 `tests/test_batch_parse_cli.py`，全部路径用 `tmp_path / "x.pdf"`、`tmp_path / "out" / "content.md"`、`str(tmp_path/...)`（:30-33/:64），**无写死的 `/tmp` 文件创建**。
- 其余 tests/ 内出现的 `/tmp` 字符串（test_collector_paths/test_fresh_schema/test_parse_api）仅为 source_path 字符串测试值或路径解析安全用例，**不创建实际文件**，不属本发现范围。
- 全量 313 passed，仓库内 `.codex_tmp` 复现干净。

### P2-POST-03 真实库 quarantine/source 状态不一致 — ✅ FIXED-WITH-DRY-RUN（真实库零写入）

- **dry-run 标志存在**：`scripts/healthcheck_library.py` `--repair-quarantine-status`（:246/:320），默认 `dry_run`。
- **本 agent 独立铁证（库指纹前后比对）**：
  - 写前：`source_files` status = `('active', 137), ('archived', 22)`
  - 执行 `healthcheck_library.py --repair-quarantine-status --json`（**不带 --apply**）→ `applied_fixes=[]`（空），`repair_plan=16`
  - 写后：`('active', 137), ('archived', 22)` —— **完全一致**
- 真实库本轮**未被修改**。16 条 `quarantined_work_active_source` 已报告，用户须显式 `--apply` 才会更新 `source_files.status='quarantined'`。

### P2-POST-04 healthcheck phantom 口径误报 — ✅ FIXED

- **phantom 改用真实存在性检查**：`scripts/healthcheck_library.py:147` `if not resolved.exists(): result.phantom_db_entries.append(p)` —— 不再是集合差集。归档/隔离区真实存在的 DB 路径不再误报。
- **新增独立分类**：`active_source_in_quarantine`（:181）、`quarantine_path_status_mismatch`（:194）。
- 本 agent `--json` 实测：phantom 仅 6（真实缺失/编码路径），不再被 `_archive`/`_quarantine` 路径污染。
- `tests/test_healthcheck_repair.py` 10 用例随批次全过。

### P3-POST-01 工作区交付边界不清 — ⚠️ ANALYZED（未提交，唯一未闭环项）

- 实施方对未跟踪/未提交产物做了归属分析（见其 result 文档 §7），决策清晰（commit/gitignore/needs-decision），符合计划 §0 规则 3。
- **但工作区当前不干净**（本 agent `git status` 实测）：
  - `master` ahead origin/master **2 commits 未 push**（`60e65be`、`f35aeab`）。
  - 10 modified + 10+ untracked 文件**尚未提交**（含本次修复的核心代码 `api/path_safety.py`、`classification.py`、`metadata.py`、`works.py`、`healthcheck_library.py`、3 个新测试、`ClassificationReview.vue` 等）。
- 故"工作区干净/可解释"闸门**尚未达成**——需用户执行一次提交（含 push）。这是程序决策而非代码修复，故不阻塞 PASS，但属本复核明确指出的剩余动作。

## 3. 复核中发现的差异（诚实记录）

1. **healthcheck 计数文档误差（低）**：实施方 result 文档 §6 写 `status_inconsistencies=53`（细分为 16+16+21），本 agent 实时 `--json` 实测为 **56**（16+16+**24**），`quarantine_path_status_mismatch` 多 3 条。DB 只读未写，计数应稳定，故判定为**文档计数陈旧/不准**，非功能缺陷。建议实施方更新文档数字。
2. **计划中验收命令 `npm.cmd run build` 缺工作目录（低）**：须在 `web/` 下执行；根目录会 `ENOENT package.json`。实施方文档的"1.69s"系从 web/ 运行所得。建议计划补 `cd web`。
3. **`parser/docs/archive/latest_changes.diff`（~1.6MB）已 gitignore**：核实 `.gitignore` 含该条目，不会误入提交。✓

## 4. 真实库只读声明

本轮本 agent **未对真实 `literature.sqlite`、`works/`、`_archive/`、`_quarantine/` 执行任何写入**。证据：

- `healthcheck_library.py --json`：`applied_fixes=0`。
- `healthcheck_library.py --repair-quarantine-status`（无 --apply）：`applied_fixes=[]`，库指纹前后完全一致。
- 未运行任何带 `--apply` / `--repair ... --apply` 的命令。
- 所有反向验证走 pytest 临时库（`sample_db`/`tmp_path`）。

**真实库 repair 仍未执行**。如需修复 16 条不一致，由用户确认后运行：

```powershell
.\.venv\Scripts\python.exe scripts\healthcheck_library.py --repair-quarantine-status --apply
```

## 5. 工作区交付状态（本 agent 实测）

- 分支：`master`，**ahead origin/master 2**（未 push）。
- 未提交修改（10）：`.gitignore`、`api/routes/{classification,metadata,works}.py`、`scripts/healthcheck_library.py`、`scripts/run_api.py`、`tests/conftest.py`、`tests/test_batch_parse_cli.py`、`web/src/views/ClassificationReview.vue`、`web/vite.config.js`。
- 未跟踪新增：`api/path_safety.py`、3 个新测试、多个 docs 目录、本轮 4 份 review 文档。
- 建议提交策略见 §6。

## 6. 提交/Push 建议

**建议：提交本轮修复并 push（连同 ahead 2）。** 代码侧 1×P1 + 4×P2 已真实闭环，验证充分。

提交前建议：
1. 实施方修正 result 文档中 status_inconsistencies 计数（53→56）等小误差（§3）。
2. 决定 `parser/docs/archive/20260403文档服务在线部署_V1.1.docx`（needs-decision）的归属。
3. 提交 + push。

参考 commit message（实施方已拟，本 agent 认可）：

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

## 7. 逐项状态总表

| Finding | 级别 | 实施方声称 | 本复核独立结论 | 剩余动作 |
| --- | --- | --- | --- | --- |
| P1-POST-01 词表绕过 | P1 | fixed | **✅ FIXED**（代码+测试+前端均验证） | 无 |
| P2-POST-01 quarantine 安全名 | P2 | fixed | **✅ FIXED** | 无 |
| P2-POST-02 /tmp 硬编码 | P2 | fixed | **✅ FIXED** | 无 |
| P2-POST-03 真实库状态不一致 | P2 | fixed-with-dry-run | **✅ FIXED-WITH-DRY-RUN**（真实库零写入铁证） | 用户确认后 --apply |
| P2-POST-04 phantom 口径 | P2 | fixed | **✅ FIXED** | 无 |
| P3-POST-01 交付边界 | P3 | analyzed | **⚠️ ANALYZED（未提交）** | commit + push |

## 8. 与实施方 result 文档的关系

本 agent **未覆盖** 实施方已写的 `2026-06-29-post-remediation-followup-result.md`（遵循"不动他人产物"原则）。两者并存：实施方文档为整改自述，本文件为第三方独立复核。结论一致（均判修复成立），本文件额外提供独立命令证据、库指纹铁证、3 项差异记录，并明确指出 P3-POST-01 仍是"待用户提交"的未闭环点。
