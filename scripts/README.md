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
- 在 `parse_ledger.json` 中新增 `pending` 解析任务
- 刷新 `index.json`

该脚本不提交 MinerU 解析。新增条目会先标记为 `pending`；等 MinerU 和 document-parser 可用时，再用 document-parser 工程中的 `literature_batch_parse.py` 解析。

## Phase 3：只读文献台账

生成本地 HTML 台账：

```powershell
python scripts\literature_dashboard.py
```

输出文件：

```text
views\library_dashboard.html
```

这个页面不需要后端服务，直接用浏览器打开即可。它读取 `literature.sqlite`、`index.json` 和 `parse_ledger.json`，展示当前活跃文献、PDF 位置、解析状态、`content.md` 路径、重复候选和文献关系。
