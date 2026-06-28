# _archive

已弃用、确认无 active 引用的脚本。保留备查，不在任何运行路径上。

- `parser_scripts_literature_batch_parse.py`：旧自部署 MinerU Agent API（:18200 /api/v1/tasks）版批量解析 CLI。Phase D 状态源统一时归档——新 CLI `scripts/literature_batch_parse.py`（官网 cloud API + core.mineru.router 单核）已取代。
- `parser_scripts_literature_cleanup_bad_sources.py`：依赖已废弃的 parse_ledger.json，随旧 CLI 归档。
- `parse_ledger.json.bak`：Phase D 状态源统一前 DB 的冗余文件镜像，移入归档；DB（`literature_parse_runs`）为唯一权威。
