# 源码部署补充说明

主流程请优先阅读 `deploy.md`。本文覆盖两种源码部署场景：

- **场景 A**：远端运行 MinerU，本地 document-parser 联调（主要场景）
- **场景 B**：同一台远端机器同时运行 MinerU 与 document-parser

## 1. 目录规划

```bash
mkdir -p ~/doc-services/mineru ~/logs /opt/mineru /opt/modelscope_cache
```

## 2. MinerU 服务

国内网络环境下，Python 包使用阿里云 PyPI 镜像，模型统一使用 ModelScope。模型缓存和 MinerU 配置都放到系统盘 `/opt`，避免迁移时丢失模型路径配置。

```bash
cd ~/doc-services/mineru
python3 -m pip install -U pip uv -i https://mirrors.aliyun.com/pypi/simple
uv venv --python 3.11
uv pip install -U "mineru[all]" -i https://mirrors.aliyun.com/pypi/simple

cat >/opt/mineru/mineru.env <<'EOF'
MINERU_HOME=/opt/mineru
MINERU_MODEL_SOURCE=modelscope
MODELSCOPE_CACHE=/opt/modelscope_cache
MINERU_TOOLS_CONFIG_JSON=/opt/mineru/mineru.json
MINERU_HOST=0.0.0.0
MINERU_PORT=18200
EOF

export HOME=/opt/mineru
export MINERU_MODEL_SOURCE=modelscope
export MODELSCOPE_CACHE=/opt/modelscope_cache
export MINERU_TOOLS_CONFIG_JSON=/opt/mineru/mineru.json

# API 默认使用 pipeline 能力；如无明确 VLM 需求，先不要下载 all，避免系统盘占用过大。
.venv/bin/mineru-models-download -s modelscope -m pipeline

# 可选：安装完成后清理 uv 下载缓存，释放系统盘。
python3 -m uv cache clean

env \
HOME=/opt/mineru \
VIRTUAL_ENV=/root/doc-services/mineru/.venv \
PATH=/root/doc-services/mineru/.venv/bin:$PATH \
MINERU_MODEL_SOURCE=modelscope \
MODELSCOPE_CACHE=/opt/modelscope_cache \
MINERU_TOOLS_CONFIG_JSON=/opt/mineru/mineru.json \
  setsid -f .venv/bin/mineru-api --host 0.0.0.0 --port 18200 > ~/logs/mineru-api.log 2>&1 < /dev/null
```

验证：

```bash
curl http://127.0.0.1:18200/health
```

## 3. 本地 document-parser 联调

document-parser 在本地机器运行时，将 MinerU 地址指向远端服务器：

```bash
export MINERU_SERVER_URL="http://<远端服务器IP>:18200/file_parse"
```

如果本地 document-parser 运行在 Docker 容器中，仍然使用远端服务器 IP，不要使用 `127.0.0.1`：

```bash
export MINERU_SERVER_URL="http://<远端服务器IP>:18200/file_parse"
```

## 4. MinerU 启动脚本

保存为 `~/doc-services/start_services.sh`：

```bash
#!/usr/bin/env bash
set -euo pipefail

SERVICES_DIR="${SERVICES_DIR:-/root/doc-services}"
MINERU_DIR="${MINERU_DIR:-$SERVICES_DIR/mineru}"
LOGS_DIR="${LOGS_DIR:-/root/logs}"
MINERU_ENV="${MINERU_ENV:-/opt/mineru/mineru.env}"
mkdir -p "$LOGS_DIR"

if [[ -f "$MINERU_ENV" ]]; then
  set -a
  source "$MINERU_ENV"
  set +a
fi

MINERU_HOME="${MINERU_HOME:-/opt/mineru}"
MINERU_MODEL_SOURCE="${MINERU_MODEL_SOURCE:-modelscope}"
MODELSCOPE_CACHE="${MODELSCOPE_CACHE:-/opt/modelscope_cache}"
MINERU_TOOLS_CONFIG_JSON="${MINERU_TOOLS_CONFIG_JSON:-/opt/mineru/mineru.json}"
MINERU_HOST="${MINERU_HOST:-0.0.0.0}"
MINERU_PORT="${MINERU_PORT:-18200}"

health_ok() {
  curl -fsS -m 5 "$1" >/dev/null 2>&1
}

start_mineru() {
  if health_ok "http://127.0.0.1:${MINERU_PORT}/health"; then
    echo "MinerU already healthy on ${MINERU_PORT}"
    return
  fi
  cd "$MINERU_DIR"
  env \
  HOME="$MINERU_HOME" \
  VIRTUAL_ENV="$MINERU_DIR/.venv" \
  PATH="$MINERU_DIR/.venv/bin:$PATH" \
  MINERU_MODEL_SOURCE="$MINERU_MODEL_SOURCE" \
  MODELSCOPE_CACHE="$MODELSCOPE_CACHE" \
  MINERU_TOOLS_CONFIG_JSON="$MINERU_TOOLS_CONFIG_JSON" \
    setsid -f "$MINERU_DIR/.venv/bin/mineru-api" \
      --host "$MINERU_HOST" \
      --port "$MINERU_PORT" \
      > "$LOGS_DIR/mineru-api.log" 2>&1 < /dev/null
  echo "MinerU start requested"
}

stop_all() {
  pkill -f 'mineru-api' || true
}

case "${1:-start}" in
  start)
    start_mineru
    ;;
  stop)
    stop_all
    ;;
  restart)
    stop_all
    sleep 2
    start_mineru
    ;;
  status)
    curl -fsS -m 5 "http://127.0.0.1:${MINERU_PORT}/health" || true
    echo
    pgrep -af 'mineru-api' || true
    ;;
  logs)
    tail -n 100 "$LOGS_DIR/mineru-api.log"
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|logs}"
    exit 1
    ;;
esac
```

```bash
chmod +x ~/doc-services/start_services.sh
~/doc-services/start_services.sh start
```

## 5. 说明

- MinerU 使用 `18200`。
- MinerU 模型源固定为 `modelscope`。
- MinerU 配置文件固定为 `/opt/mineru/mineru.json`。
- ModelScope 模型缓存固定为 `/opt/modelscope_cache`。
- 本地 document-parser 联调时使用 `MINERU_SERVER_URL=http://<远端服务器IP>:18200/file_parse`。

## 6. 两种 MinerU 后端验证

准备一个测试 PDF 后，可直接验证 MinerU `/file_parse`。

### 6.1 验证 pipeline 后端

`pipeline` 更通用，适合作为 document-parser 默认后端。

```bash
curl -sS -w "\nHTTP_STATUS=%{http_code}\n" \
  -X POST "http://127.0.0.1:18200/file_parse" \
  -F "files=@/path/to/sample.pdf" \
  -F "backend=pipeline" \
  -F "parse_method=auto" \
  -F "formula_enable=true" \
  -F "table_enable=true" \
  -F "return_md=true" \
  -F "return_middle_json=false" \
  -F "return_model_output=false" \
  -F "return_content_list=true" \
  -F "return_images=false" \
  -F "response_format_zip=false" \
  -F "start_page_id=0" \
  -F "end_page_id=99999" \
  -F "lang_list=ch" \
  --max-time 240
```

成功时应看到：

```text
"status":"completed"
HTTP_STATUS=200
```

### 6.2 验证 hybrid-auto-engine 后端

`hybrid-auto-engine` 会使用 VLM/vLLM 能力，要求远端 GPU、显存、模型缓存和 vLLM 初始化均正常。

```bash
curl -sS -w "\nHTTP_STATUS=%{http_code}\n" \
  -X POST "http://127.0.0.1:18200/file_parse" \
  -F "files=@/path/to/sample.pdf" \
  -F "backend=hybrid-auto-engine" \
  -F "parse_method=auto" \
  -F "formula_enable=true" \
  -F "table_enable=true" \
  -F "return_md=true" \
  -F "return_middle_json=false" \
  -F "return_model_output=false" \
  -F "return_content_list=true" \
  -F "return_images=false" \
  -F "response_format_zip=false" \
  -F "start_page_id=0" \
  -F "end_page_id=99999" \
  -F "lang_list=ch" \
  --max-time 300
```

成功时应看到：

```text
"status":"completed"
"backend":"hybrid-auto-engine"
HTTP_STATUS=200
```

如果返回 `HTTP_STATUS=409`，查看日志：

```bash
tail -n 200 ~/logs/mineru-api.log
```

常见原因是 vLLM 初始化失败、显存不足、模型未完整下载或模型缓存路径不一致。

### 6.3 document-parser 后端切换

本地 document-parser 默认使用 `pipeline`。如需使用 GPU/VLM 后端，启动本地服务前设置：

```powershell
$env:MINERU_PARSE_BACKEND = "hybrid-auto-engine"
```

如需恢复通用后端：

```powershell
$env:MINERU_PARSE_BACKEND = "pipeline"
```

今日验证记录：

- MinerU `pipeline` 后端已验证成功。
- MinerU `hybrid-auto-engine` 后端已在 GPU 可用后验证成功。

## 7. 已有远端服务切换端口

如果远端 MinerU 已经在 `8000` 运行，切到 `18200` 时可以按下面执行：

```bash
sed -i 's/^MINERU_PORT=.*/MINERU_PORT=18200/' /opt/mineru/mineru.env
pkill -f 'mineru-api' || true
~/doc-services/start_services.sh start
curl -fsS http://127.0.0.1:18200/health
```

本地 document-parser 同步改为：

```powershell
$env:MINERU_SERVER_URL = "http://<远端服务器IP>:18200/file_parse"
```

---

## 场景 B：同一台远端机器同时运行 MinerU 与 document-parser

### B.1 document-parser 服务

```bash
cd ~/doc-services
# git clone git@github.com:your-org/document-parser.git
cd document-parser
uv sync

export DOC_PARSER_HOST=0.0.0.0
export DOC_PARSER_PORT=18201
export DOC_PARSER_SHARE_DIR="$PWD/Datas"
export DOC_PARSER_API_KEYS="test_client=test_key"
export MINERU_SERVER_URL="http://127.0.0.1:18200/file_parse"

nohup uv run python main.py > ~/logs/document-parser.log 2>&1 &
```

验证：

```bash
curl http://127.0.0.1:18201/health
```

### B.2 双服务合管启动脚本

将下面的脚本追加到 `~/doc-services/start_services.sh` 的 `stop_all` 和 `case` 块中，或单独保存为新脚本：

```bash
#!/usr/bin/env bash
set -euo pipefail

SERVICES_DIR="${SERVICES_DIR:-/root/doc-services}"
MINERU_DIR="${MINERU_DIR:-$SERVICES_DIR/mineru}"
DOC_DIR="${DOC_DIR:-$SERVICES_DIR/document-parser}"
LOGS_DIR="${LOGS_DIR:-/root/logs}"
MINERU_ENV="${MINERU_ENV:-/opt/mineru/mineru.env}"
mkdir -p "$LOGS_DIR"

if [[ -f "$MINERU_ENV" ]]; then
  set -a; source "$MINERU_ENV"; set +a
fi

MINERU_PORT="${MINERU_PORT:-18200}"

health_ok() {
  curl -fsS -m 5 "$1" >/dev/null 2>&1
}

start_mineru() {
  if health_ok "http://127.0.0.1:${MINERU_PORT}/health"; then
    echo "MinerU already healthy on ${MINERU_PORT}"; return
  fi
  cd "$MINERU_DIR"
  env HOME="${MINERU_HOME:-/opt/mineru}" \
      VIRTUAL_ENV="$MINERU_DIR/.venv" \
      PATH="$MINERU_DIR/.venv/bin:$PATH" \
      MINERU_MODEL_SOURCE="${MINERU_MODEL_SOURCE:-modelscope}" \
      MODELSCOPE_CACHE="${MODELSCOPE_CACHE:-/opt/modelscope_cache}" \
      MINERU_TOOLS_CONFIG_JSON="${MINERU_TOOLS_CONFIG_JSON:-/opt/mineru/mineru.json}" \
    setsid -f "$MINERU_DIR/.venv/bin/mineru-api" \
      --host 0.0.0.0 --port "$MINERU_PORT" \
      > "$LOGS_DIR/mineru-api.log" 2>&1 < /dev/null
  echo "MinerU start requested"
}

start_doc_parser() {
  if health_ok "http://127.0.0.1:18201/health"; then
    echo "document-parser already healthy on 18201"; return
  fi
  cd "$DOC_DIR"
  export DOC_PARSER_HOST=0.0.0.0
  export DOC_PARSER_PORT=18201
  export DOC_PARSER_SHARE_DIR="$DOC_DIR/Datas"
  export DOC_PARSER_API_KEYS="test_client=test_key"
  export MINERU_SERVER_URL="http://127.0.0.1:${MINERU_PORT}/file_parse"
  nohup uv run python main.py > "$LOGS_DIR/document-parser.log" 2>&1 &
  echo "document-parser started: $!"
}

stop_all() {
  pkill -f 'mineru-api' || true
  pkill -f 'python main.py' || true
}

case "${1:-start}" in
  start)   start_mineru; start_doc_parser ;;
  stop)    stop_all ;;
  restart) stop_all; sleep 2; start_mineru; start_doc_parser ;;
  status)
    curl -fsS -m 5 "http://127.0.0.1:${MINERU_PORT}/health" || true; echo
    curl -fsS -m 5 "http://127.0.0.1:18201/health" || true; echo
    pgrep -af 'mineru-api\|python main.py' || true
    ;;
  logs)
    tail -n 100 "$LOGS_DIR/mineru-api.log" "$LOGS_DIR/document-parser.log"
    ;;
  *) echo "Usage: $0 {start|stop|restart|status|logs}"; exit 1 ;;
esac
```

```bash
chmod +x ~/doc-services/start_services.sh
~/doc-services/start_services.sh start
```

### B.3 说明

- 两服务同机时 `MINERU_SERVER_URL` 使用 `127.0.0.1`。
- 若 document-parser 跑在 Docker 容器中而 MinerU 在宿主机，改用 `host.docker.internal`：
  ```bash
  export MINERU_SERVER_URL="http://host.docker.internal:18200/file_parse"
  ```
