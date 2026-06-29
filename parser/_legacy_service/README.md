# `_legacy_service/` — 已休眠的独立解析微服务（归档）

**状态：DORMANT（休眠）。** 这里是从外部"远端部署文档解析服务"原样拷过来的
独立 FastAPI 微服务层，**当前不再接入文献库的主解析流程**。

## 为什么留着

历史保留 + 可选复活：若将来数据量增大、需要从 MinerU 官网 API 切回自部署
MinerU，可基于此目录重新起服务。

## 为什么归档

主流程已改用 **MinerU 官网 API**（数据量小，够用），解析入口是
`api/routes/parse.py`，它通过 `sys.path` 把 `parser/`（本目录的父目录）当作
库根，`from core.mineru.router import route_and_parse` 直接调用 `parser/core/`，
解析状态写入共享库 `literature.sqlite` 的 `literature_parse_runs` 表（唯一权威）。

本目录的微服务有**自己独立的内存任务追踪系统**（`api/task_manage.py` 的
`TaskManager` + `Datas/uploads/`），与 `literature_parse_runs` **完全不互通**。
继续把它放在 `parser/` 顶层会造成"两套解析追踪系统"的混淆，故下移到
`_legacy_service/` 明确边界。

## 边界声明（重要）

- **现行解析路径**：`api/routes/parse.py` → `parser/core/mineru/`（当库用）→
  MinerU 官网 API → `literature_parse_runs`（DB 唯一权威）。
- **本目录**：独立可选的 HTTP 微服务，`python _legacy_service/main.py` 可单独
  运行，但其任务状态**不进入** `literature_parse_runs`，与文献库主流程隔离。
- **不要**从这里触发文献库的解析；状态会丢失在内存里。

## 依赖

本目录内文件仍以 `parser/` 为 sys.path 根（`from core...`、`from config import config`、
`import api.task_manage`）。复活时需保证从 `parser/` 目录启动，或调整导入路径。
