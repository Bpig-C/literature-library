# 文档解析（Document Parser）

基于 FastAPI 的文档解析服务，支持上传 PDF、Office、HTML/XML 等文件，调用 MinerU 或本地转换流程生成版面识别、内容抽取、标注 PDF、详情结果等解析产物。

## 功能概览

- 文件上传与任务化处理
- PDF、Office 文档转 PDF
- HTML/XML 内容解析
- MinerU 远端或本地命令解析
- 解析结果查询接口
- Docker 部署支持

## 快速开始

推荐使用 `uv` 管理开发环境：

```bash
uv sync --dev
uv run python main.py
```

也可以使用传统 pip：

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.minimal.txt
python main.py
```

默认配置位于 `conf.json`。服务启动后可访问：

- 健康检查：`GET /health`
- Agent 提交解析：`POST /api/v1/parse`
- Agent 查询任务：`GET /api/v1/tasks/{task_id}`
- Agent 获取结果：`GET /api/v1/tasks/{task_id}/result?type=content`
- Agent 列出产物：`GET /api/v1/tasks/{task_id}/artifacts`
- Agent 下载产物包：`GET /api/v1/tasks/{task_id}/artifacts/package`
- 提交任务：`POST /tools/api/v1/{tool_id}/submit`
- 查询状态：`GET /tools/api/v1/{tool_id}/status/{task_id}`
- 获取结果：`GET /tools/api/v1/{tool_id}/result/{task_id}`

## Agent API 示例

所有解析接口默认需要认证 Header：

```text
Client-ID: test_client
X-API-Key: test_key
```

上传并提交解析：

```powershell
curl.exe -X POST "http://127.0.0.1:18201/api/v1/parse" `
  -H "Client-ID: test_client" `
  -H "X-API-Key: test_key" `
  -F "file=@D:\test\sample.pdf" `
  -F "backend=pipeline" `
  -F "parse_method=auto"
```

查询状态：

```powershell
curl.exe "http://127.0.0.1:18201/api/v1/tasks/<task_id>" `
  -H "Client-ID: test_client" `
  -H "X-API-Key: test_key"
```

获取结构化内容：

```powershell
curl.exe "http://127.0.0.1:18201/api/v1/tasks/<task_id>/result?type=content" `
  -H "Client-ID: test_client" `
  -H "X-API-Key: test_key"
```

下载完整产物包：

```powershell
curl.exe -L "http://127.0.0.1:18201/api/v1/tasks/<task_id>/artifacts/package" `
  -H "Client-ID: test_client" `
  -H "X-API-Key: test_key" `
  -o "document-parser-<task_id>.zip"
```

## 配置说明

- `server`：服务监听地址、端口、共享目录、CORS 白名单、开发测试 API key
- `mineru`：MinerU 服务地址、超时、并发 worker 数
- `parse_request`：解析请求默认参数
- `libreoffice`：Office 转 PDF 的 LibreOffice 配置

常用环境变量：

- `DOC_PARSER_HOST`：服务监听地址
- `DOC_PARSER_PORT`：服务监听端口
- `DOC_PARSER_SHARE_DIR`：上传与结果共享目录
- `DOC_PARSER_API_KEYS`：API 客户端，格式 `client_id=api_key`，多组用逗号分隔
- `DOC_PARSER_CORS_ORIGINS`：跨域白名单，多组用逗号分隔
- `MINERU_SERVER_URL`：远端 MinerU 解析接口，例如 `http://host.docker.internal:18200/file_parse`
- `MINERU_PARSE_BACKEND`：MinerU 后端，默认 `pipeline`；`hybrid-auto-engine` 需要远端 vLLM/VLM 正常初始化

当前仓库不包含远端 MinerU 服务，端到端解析需要部署 MinerU 后配置 `MINERU_SERVER_URL` 再验证。

## Docker

```bash
docker build -t document-parser:latest .
docker run --rm -p 18201:18201 -v /data/document-parser/Datas:/app/Datas \
  -e MINERU_SERVER_URL=http://host.docker.internal:18200/file_parse \
  document-parser:latest
```

## 开发与测试

```bash
uv run python -m pytest -q
```

如果测试环境提示缺少 `fitz`，请确认已安装 `PyMuPDF`。


