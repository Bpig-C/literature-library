# Document Parser Agent Notes

This repository is a FastAPI-based document parsing service. It accepts PDF, Office, HTML/XML files, converts or routes them as needed, calls MinerU for PDF parsing, and returns structured JSON plus downloadable parsing artifacts.

## Current Shape

- Main entry: `main.py`
- App assembly, CORS, auth, OpenAPI: `server/app.py`
- Legacy tool API routes: `api/routes_submit.py`, `api/routes_status.py`, `api/routes_result.py`, `api/routes_run.py`
- Agent API routes: `api/routes_agent.py`
- Shared parse service: `api/services/parse_service.py`
- Artifact listing/download service: `api/services/artifact_service.py`
- Task model and in-memory task manager: `api/task_manage.py`
- MinerU queue/client integration: `core/mineru/`
- Result builders: `core/document/artifact_generator.py`
- HTML/XML conversion: `core/xml/`
- Tests: `tests/`

Project index files:

- Manual architecture doc: `PROJECT_INDEX/architecture.md`
- Generated code signature indexes: `PROJECT_INDEX/history/`
- Project index usage notes: `PROJECT_INDEX/README.md`

## Run

Recommended local run:

```bash
uv run python main.py
```

Traditional run:

```bash
python main.py
```

Default host and port come from `conf.json`: `127.0.0.1:18201`.

## Test

Use the project test command:

```bash
uv run python -m pytest -q
```

Current expected baseline after the Agent API work:

```text
46 passed, 1 warning
```

The warning is a FastAPI/Starlette TestClient dependency warning and is not a business failure.

## MinerU Setup

The service can call remote MinerU when `conf.json` has `mineru.localcommand_mineru=false` and `MINERU_SERVER_URL` is set.

Typical local tunnel / local MinerU setting:

```powershell
$env:MINERU_SERVER_URL = "http://127.0.0.1:18200/file_parse"
$env:MINERU_PARSE_BACKEND = "pipeline"
uv run python main.py
```

Remote MinerU via SSH tunnel:

```powershell
# 假设远程MinerU运行在remote-host的8000端口，SSH端口为45488
ssh -L 18200:localhost:8000 -p 45488 user@remote-host
# 后台运行
ssh -f -N -L 18200:localhost:8000 -p 45488 user@remote-host
```

然后设置环境变量：

```powershell
$env:MINERU_SERVER_URL = "http://127.0.0.1:18200/file_parse"
$env:MINERU_PARSE_BACKEND = "pipeline"
```

Useful MinerU health check:

```powershell
curl.exe "http://127.0.0.1:18200/health"
```

Known working MinerU version during recent validation: `3.2.1`.

## Auth

Most API routes require:

```text
Client-ID: test_client
X-API-Key: test_key
```

`/health`, `/docs`, `/openapi.json`, `/redoc`, and `/html/*` are intentionally unauthenticated for local development and debugging.

Production API keys should be provided through:

```text
DOC_PARSER_API_KEYS=client_id=api_key,another_client=another_key
```

## Agent API

Preferred new API for agents:

```text
POST /api/v1/parse
GET  /api/v1/tasks/{task_id}
GET  /api/v1/tasks/{task_id}/result?type=content
GET  /api/v1/tasks/{task_id}/artifacts
GET  /api/v1/tasks/{task_id}/artifacts/file?path={relative_path}
GET  /api/v1/tasks/{task_id}/artifacts/package
```

`POST /api/v1/parse` accepts multipart form fields:

- `file`: required upload file
- `backend`: optional MinerU backend, for example `pipeline` or `hybrid-auto-engine`
- `parse_method`: optional, default `auto`
- `return_package`: optional bool, default true
- `metadata`: optional JSON/string metadata stored on the task

Result types:

```text
content
layout
detail
annotated
```

## Legacy API

Keep these compatible unless explicitly asked to break them:

```text
POST /tools/api/v1/{tool_id}/submit
GET  /tools/api/v1/{tool_id}/status/{task_id}
GET  /tools/api/v1/{tool_id}/result/{task_id}
POST /tools/api/v1/{tool_id}/run
```

Common `tool_id` values:

```text
doc-content-extraction
doc-layout-recognition
doc-annotated-pdf
doc-detail-pdf
```

## Artifact Rules

- Runtime uploads and outputs live under `Datas/uploads/{task_id}` by default.
- `/Datas` static serving is disabled by default; artifact access should go through authenticated API routes.
- Single artifact downloads must stay inside the task directory. `api/services/artifact_service.py` resolves paths and blocks `../` traversal.
- If MinerU returns an original `*_result.zip`, package download returns that zip first.
- If no original zip exists, a dynamic zip is generated under `Datas/uploads/_packages`.

## Implementation Notes

- `api/services/parse_service.py` is the shared submit path for both legacy and Agent APIs.
- `Task` includes `error_message`, `backend`, `parse_method`, `artifact_dir`, `result_zip_path`, and `metadata`.
- `MinerU_OP.push_task` supports per-task `backend` and `parse_method`; do not assume only global config is used.
- MinerU non-200 responses are normalized in `core/mineru/web_client.py` and surfaced through task status `error`.
- Keep new tests focused in `tests/test_api.py` unless adding lower-level unit coverage.
- Avoid editing generated runtime files under `Datas/`, `logs/`, `.pytest_cache/`, `.venv/`, and `.codex_tmp/`.
