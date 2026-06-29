# 第三方双轴独立评审 + 设计闭环收尾

> 日期：2026-06-29
> 评审者：独立第三方（不信任任何 `docs/`，只读代码 + 可复现运行结果）
> 评审对象：POST 整改后的整体质量
> 上游：`2026-06-29-third-party-audit-handoff-to-next-planner.md`、`2026-06-29-post-remediation-followup-result.md`

## 1. 评审方法

两轴：
- **功能质量**（往下钻）：声称复现 + 钻进代码找残留缺陷。
- **设计质量**（往上抽象）：数据流是否闭环、状态机是否自洽、子系统边界是否清晰。

## 2. 复现事实（声称全部属实）

| 声称 | 复现命令 | 结果 |
| --- | --- | --- |
| 全量测试绿 | `python -m pytest -q` | ✅（评审起点 316 passed / 7 skipped） |
| healthcheck 干净 | `python scripts/healthcheck_library.py` | ✅ orphan/phantom/inconsistency 全 0 |
| 工作树状态 | `git status` | ✅ |

## 3. 功能轴：两个"部分修复"新发现（上一轮 POST 报告漏掉的面）

### F1（P2）：分类标量字段词表绕过——POST-01 只堵了多值 tag
`classification.py` 的 `_validate_and_write_tags` 对 `reading_lane/method_tags/...` 多值 tag 做了词表校验，但 review / batch-approve-low-risk / batch-approve-with-tag 三条 fast-path 里的 `CLASSIFICATION_FIELDS`（`primary_doc_type`/`publication_status`/`ingestion_state`/`priority`/`primary_source_actor_type`/`region`）直写 `works` 表，**零词表校验**。
- **修复**：`classification_vocab.py` 新增 `validate_scalar_fields()`；三处 approved-path 写入前先校验（`secondary_doc_type` 为合法自由文本，不校验）。
- **测试**：`tests/test_classification_scalar_vocab.py`（3 例，含正/负向）。

### F2（P2）：duplicates.py 路径穿越——POST-01 没覆盖 dedup 移动路径
`api/path_safety.py` 实现正确，works/metadata/classification quarantine 都接了，但 `duplicates.py` 三处 `shutil.move` 用 `source_files.original_name` 裸拼目标路径，未 sanitize。
- **修复**：`duplicates.py` 接入 `_safe_dest_name` + `_unique_dest`，覆盖 merge-archive 与 `_move_to_quarantine`。
- **测试**：`tests/test_duplicates_path_safety.py`（4 例）。

## 4. 设计轴：三个结构张力点

### D1（结构性）：`works.parse_status` 三个写入源定义打架
- `literature_ingest.py:742`：加新源→`partial`（"所有源都解析过"=succeeded）。
- `sync_work_parse_status`（粘性 succeeded："任一 run 成功过"=succeeded，永不回退）。
- 多源 work 时 ingest 写的正确 `partial` 被 sync 改回 `succeeded`，误报完整解析。
- **修复（方案1）**：重写 `sync_work_parse_status` 为**按 active 源覆盖**计算——每源取最好成绩再聚合（全 succeeded=succeeded / 全 failed=failed / 全 pending=pending / 混合=partial），只数 `status='active'` 的源。让 ingest 与 sync 定义对齐。signature 不变。
- **配套**：新增单子文件归档/恢复端点 `POST /works/{id}/sources/{sfid}/archive|restore`，使"归档死附录→正文 work 回 succeeded"可从 API 触发（不动 `works.read_status`，走 `path_safety`）。
- **phantom 回归（评审中抓出并补修）**：初版 archive 端点没同步 `source_path`，归档后制造 healthcheck phantom。修正为 `source_path = archive_path = dest`（house convention），并补 healthcheck 零 phantom 断言。
- **测试**：`test_sync_parse_status_coverage.py`（8 例）+ `test_source_file_archive.py`（5 例 + phantom 断言）。

### D2：两个互不打通的 parser 追踪系统——实为休眠代码
`parser/` 是从外部"远端部署解析服务"拷来的独立微服务（内存 `task_manage` + `Datas/uploads/`），与现行 `literature_parse_runs`（DB 唯一权威）不互通。现行流程是 `api/routes/parse.py` 把 `parser/core` 当库用、直连 MinerU 官网 API。微服务层（`parser/api`、`parser/server`、`main.py`、`Dockerfile`、deploy 文档）无人引用。
- **修复（归档）**：上述休眠层 `git mv` 到 `parser/_legacy_service/`，附 README 声明边界与休眠状态。`parser/core/`、`parser/config.py` 留在原位（core 仍 `from config import config`）。

### D3：无 DB 外键的检测盲区
17 张表里 15 张无 FK 约束，healthcheck 原先只查"文件↔DB"，不查"DB 内部引用一致性"——删一个 work 可能留下悬挂的 `source_files`/`intake_candidates`/`parse_runs` 而无人知晓。
- **修复**：`healthcheck_library.py` 新增 `_check_dangling_references()`，只读扫描 10 条逻辑外键引用，守卫表/列存在性。新增 `dangling_references` 字段，进入 `has_issues()`/`summary()`/输出。真实库当前 0 悬挂。
- **测试**：`test_healthcheck_dangling_refs.py`（6 例）。
- **FK 约束**：确认为长期正解，但现网 SQLite 加 FK 需重建表 + 预清洗，风险/收益不划算，**留作下次大 schema 迁移时补**。

## 5. 修复提交清单（均 TDD、已 push）

| commit | 内容 | 类别 |
| --- | --- | --- |
| `a50f9a5` | F1 标量词表校验 + F2 dedup 路径穿越 | 安全修复 |
| `19e1449` | D2 归档休眠 parser 微服务 | 设计治理 |
| `aa93722` | D3 悬挂引用 healthcheck 检测 | 闭环加固 |
| `fc3ad2c` | D1 覆盖感知 sync + 单子文件归档端点（本地模型实现，经评审） | 结构性修复 |
| `a130fa6` | D1 archive phantom 回归修复（评审抓出） | 闭环加固 |

## 6. 最终裁定

| 维度 | 裁定 |
| --- | --- |
| 功能正确性 | **PASS**（342 passed / 7 skipped；healthcheck 五项全零） |
| 安全修复完整度 | **PASS**（F1/F2 两处残留面已闭合） |
| 设计闭环 | **PASS**（D1/D2/D3 三个结构张力点全部闭合；F2/D3/D1 互为护栏） |

### 残留（已确认延后，非缺陷）
- DB 外键约束：下次大 schema 迁移时补（D3 检测已覆盖盲区）。
- `status='superseded_quarantine'` 死枚举、quarantine `work_codes.code` 取值不统一：P3 卫生项，不影响闭环。

## 7. 可复现命令
```
python -m pytest -q                   # 342 passed, 7 skipped
python scripts/healthcheck_library.py # No issues detected（含 Dangling references: 0）
```
