# 文档解析 + MinerU 联调部署指南

本文用于从零安装 MinerU 服务，并与本项目 `document-parser` 本地服务联调。

当前推荐拓扑：

```text
本机 document-parser:18201
  └── 调用 MINERU_SERVER_URL=http://127.0.0.1:18200/file_parse
          └── SSH 隧道转发到远端 GPU 机器 MinerU:18200
```

> 说明：当前仓库只包含文档解析服务，不包含 MinerU。真实端到端解析需要先启动 MinerU 的 `mineru-api` 服务。

---

## 1. 远端 GPU 机器安装 MinerU

以下以 Ubuntu / Autodl GPU 机器为例。

### 1.1 安装系统依赖

```bash
sudo apt update
sudo apt install -y git curl net-tools libgl1 libglib2.0-0
python3 -m pip install --upgrade pip
python3 -m pip install uv
```

### 1.2 创建 MinerU 环境

```bash
mkdir -p ~/doc-services/mineru ~/modelscope_cache ~/logs
cd ~/doc-services/mineru

uv venv --python 3.11
source .venv/bin/activate

# 国内网络推荐加 PyPI 镜像源
uv pip install -U "mineru[all]" -i https://mirrors.aliyun.com/pypi/simple
```

如果环境只需要轻量核心能力，可把 `mineru[all]` 换成 `mineru[core]`；但为了减少后续后端能力缺失，GPU 机器建议先用 `mineru[all]`。

### 1.3 配置模型源

```bash
export MINERU_MODEL_SOURCE=modelscope
export MODELSCOPE_CACHE=~/modelscope_cache

# 持久化，避免重启后丢失
cat >> ~/.bashrc <<'EOF'
export MINERU_MODEL_SOURCE=modelscope
export MODELSCOPE_CACHE=~/modelscope_cache
EOF
```

### 1.4 启动 MinerU API

```bash
cd ~/doc-services/mineru
source .venv/bin/activate
export MINERU_MODEL_SOURCE=modelscope
export MODELSCOPE_CACHE=~/modelscope_cache

nohup mineru-api --host 0.0.0.0 --port 18200 > ~/logs/mineru-api.log 2>&1 &
```

### 1.5 验证 MinerU

```bash
curl http://127.0.0.1:18200/health
# 或在浏览器打开 http://<远端机器IP>:18200/docs
```

如果看不到健康检查响应，先检查日志：

```bash
tail -f ~/logs/mineru-api.log
netstat -tulnp | grep 18200
```

---

## 2. 本机打通 SSH 隧道

如果远端 MinerU 端口没有直接公网暴露，推荐在本机开 SSH 隧道。

### 2.1 本地原生运行 document-parser

本地服务直接运行在 Windows / macOS / Linux 上时，隧道绑定 `127.0.0.1` 即可：

```powershell
ssh -p <SSH端口> -L 127.0.0.1:18200:127.0.0.1:18200 root@<远端SSH地址> -N
```

示例：

```powershell
ssh -p 54360 -L 127.0.0.1:18200:127.0.0.1:18200 root@connect.example.com -N
```

验证：

```powershell
curl http://127.0.0.1:18200/health
```

### 2.2 本地 Docker 运行 document-parser

如果 document-parser 也跑在 Docker 容器里，容器访问宿主机要用 `host.docker.internal`，隧道建议绑定 `0.0.0.0`：

```powershell
ssh -p <SSH端口> -L 0.0.0.0:18200:127.0.0.1:18200 root@<远端SSH地址> -N
```

验证监听地址：

```powershell
netstat -ano | findstr :18200
```

---

## 3. 本机启动 document-parser

### 3.1 使用 uv 安装依赖

```powershell
cd D:\06_tools\document-parser
uv sync --dev
```

### 3.2 配置环境变量

#### PowerShell 临时配置

```powershell
$env:DOC_PARSER_HOST = "127.0.0.1"
$env:DOC_PARSER_PORT = "18201"
$env:DOC_PARSER_SHARE_DIR = "D:\06_tools\document-parser\Datas"
$env:DOC_PARSER_API_KEYS = "test_client=test_key"
$env:DOC_PARSER_CORS_ORIGINS = "http://localhost,http://localhost:3000,http://127.0.0.1,http://127.0.0.1:3000"
$env:MINERU_SERVER_URL = "http://127.0.0.1:18200/file_parse"
$env:MINERU_PARSE_BACKEND = "pipeline"
```

> 如果本服务跑在 Docker 中，`MINERU_SERVER_URL` 改为 `http://host.docker.internal:18200/file_parse`。

### 3.3 启动本地服务

```powershell
uv run python main.py
```

验证：

```powershell
curl http://127.0.0.1:18201/health
```

---

## 4. Docker 运行 document-parser（可选）

```powershell
cd D:\06_tools\document-parser

docker build -t document-parser:latest .

docker run --rm `
  -p 18201:18201 `
  -v D:\06_tools\document-parser\Datas:/app/Datas `
  -e DOC_PARSER_API_KEYS="test_client=test_key" `
  -e MINERU_SERVER_URL="http://host.docker.internal:18200/file_parse" `
  document-parser:latest
```

---

## 5. 端到端验证

准备一个 PDF 文件，例如 `D:\test\sample.pdf`。

### 5.1 提交解析任务

```powershell
curl.exe -X POST "http://127.0.0.1:18201/tools/api/v1/doc-content-extraction/submit" `
  -H "Client-ID: test_client" `
  -H "X-API-Key: test_key" `
  -F "files=@D:\test\sample.pdf"
```

返回中会包含 `task_id`。

### 5.2 查询任务状态

```powershell
$taskId = "替换为上一步返回的task_id"

curl.exe "http://127.0.0.1:18201/tools/api/v1/doc-content-extraction/status/$taskId" `
  -H "Client-ID: test_client" `
  -H "X-API-Key: test_key"
```

状态为 `succeeded` 后再取结果。

### 5.3 获取解析结果

```powershell
curl.exe "http://127.0.0.1:18201/tools/api/v1/doc-content-extraction/result/$taskId" `
  -H "Client-ID: test_client" `
  -H "X-API-Key: test_key"
```

常用 `tool_id`：

- `doc-content-extraction`：内容抽取 JSON
- `doc-layout-recognition`：版面识别 JSON
- `doc-annotated-pdf`：标注 PDF
- `doc-detail-pdf`：详情结果

---

## 6. 常见问题

### 6.1 本机访问不到 MinerU

先确认 SSH 隧道窗口仍在运行：

```powershell
curl http://127.0.0.1:18200/health
```

如果失败，检查远端 MinerU：

```bash
netstat -tulnp | grep 18200
tail -f ~/logs/mineru-api.log
```

### 6.2 Docker 容器访问不到 MinerU

容器内不要写 `127.0.0.1:18200`，应写：

```text
http://host.docker.internal:18200/file_parse
```

同时 SSH 隧道建议用：

```powershell
ssh -p <SSH端口> -L 0.0.0.0:18200:127.0.0.1:18200 root@<远端SSH地址> -N
```

### 6.3 MinerU 首次请求很慢

首次启动或首次解析会下载/加载模型，耗时较长。观察：

```bash
tail -f ~/logs/mineru-api.log
```

### 6.4 libGL 报错

Ubuntu 上如果出现 `ImportError: libGL.so.1`，安装：

```bash
sudo apt install -y libgl1 libglib2.0-0
```

---

## 7. 当前代码库验证命令

本项目自身单元测试不依赖真实 MinerU：

```powershell
cd D:\06_tools\document-parser
uv run python -m pytest -q
```

端到端解析必须在 `MINERU_SERVER_URL` 可访问后再验证。


