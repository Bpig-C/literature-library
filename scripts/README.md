# 文献库维护脚本

本目录存放 `D:\02_academic\doctoral\literature_library` 的本地维护脚本。

## Phase 1：Inbox 摄入

先查看摄入计划：

```powershell
python scripts\literature_ingest.py
```

确认后执行：

```powershell
python scripts\literature_ingest.py --execute
```

脚本会：

- 扫描 `_inbox` 中的 PDF
- 计算 sha256
- 将精确重复文件归档到 `_duplicates\exact_sha256`
- 将新 PDF 复制到 `works\{work_id}\source`
- 将 `_inbox` 原始投递文件归档到 `_archive\ingested_inbox`
- 写入 SQLite 的 `works`、`source_files`、`literature_parse_runs`
- 刷新 `index.json`

该脚本不自动提交 MinerU 解析。新增条目会先在 `literature_parse_runs` 中标记为 `pending`；需要解析时运行本仓库内的 `scripts/literature_batch_parse.py --execute`，或通过 API/UI 触发。

## Phase 3：只读文献台账

生成本地 HTML 台账：

```powershell
python scripts\literature_dashboard.py
```

输出文件：

```text
views\library_dashboard.html
```

这个页面不需要后端服务，直接用浏览器打开即可。它是历史只读台账，当前日常工作优先使用 Vue SPA；新功能应直接查询 SQLite/API，不应恢复 `parse_ledger.json` 依赖。

## Active Scripts

| Script | Status | Purpose |
|---|---|---|
| `literature_ingest.py` | active | `_inbox` dry-run / execute 摄入，写 `works`、`source_files`、`literature_parse_runs`。 |
| `literature_batch_parse.py` | active | DB-only pending 解析，调用 `parser/core/mineru/router.py::route_and_parse`。 |
| `healthcheck_library.py` | active | 当前只读健康检查和可选修复入口。 |
| `check_docs.py` | active | 轻量文档治理检查：入口互链、三类手册、废弃目录和旧路径误用。 |
| `run_api.py` | active | 启动 FastAPI 后端。 |
| `literature_intake.py` | active | collector/intake CLI。 |
| `dedup_cleanup.py` / `dedup_apply.py` / `scan_title_duplicates.py` | active | 去重维护与候选生成。 |
| `literature_metadata_extract.py` / `literature_metadata_rerun.py` / `backfill_risk.py` | active | 元数据抽取、重抽和风险回填。 |
| `literature_classification_extract.py` / `recompute_classification_ambiguity.py` | active | 分类抽取和模糊度重算。 |
| `literature_dashboard.py` | legacy | 历史 HTML 台账生成器；SPA 已替代日常入口。 |

## 元数据模板与批量重抽

元数据字段模板的事实源是 `templates/templates.json`，运行时由 `api/metadata_template.py` 合并默认字段和用户字段。Agent 批量处理时不要从前端复制 prompt；应直接读取模板定义并调用脚本。

常用命令：

```powershell
# 抽取待处理文献，使用当前模板
python scripts\literature_metadata_extract.py --limit 10

# 对指定 work 强制重抽
python scripts\literature_metadata_extract.py --work-id W-arxiv-xxxx --force

# 查看待修复队列
python scripts\literature_metadata_rerun.py --status needs_fix --limit 20

# 字段级重抽，字段 key 来自 templates\templates.json
python scripts\literature_metadata_rerun.py --ext-id ME-xxxx --fields title,url,journal --rerun

# 预览字段级重抽结果，不写库，适合 agent 批量审核前抽样
python scripts\literature_metadata_rerun.py --ext-id ME-xxxx --fields journal --rerun --no-write --json
```

约束：

- `--fields` 会校验当前模板字段白名单，旧别名会归一到 canonical key。
- 重抽会创建新的 `metadata_extractions` 并让旧记录进入 superseded 链路，不直接改 `works`。
- 真正回填仍需审核批准后执行 apply；不要让批量脚本绕过人工审核门禁。
- 修改模板后至少运行相关后端测试、`python scripts\healthcheck_library.py --json` 和 `cd web && npm run build`。

## Archived One-Off Scripts

下划线前缀的一次性脚本不应留在 `scripts/` 根目录。已归档到 `scripts/_archive/`：

- `_phase_b_trial.py`
- `_batch_classify.py`
- `_batch_classify_all.py`
- `_phase_c_validate.py`
- `literature_healthcheck.py`：旧健康检查脚本；V1 维护入口已替换为 `healthcheck_library.py`。
