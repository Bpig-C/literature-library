# MinerU 运维手册

## 1. 服务信息

| 项目 | 值 |
|------|-----|
| 服务地址 | `http://<服务器IP>:8000` |
| 健康检查 | `http://127.0.0.1:8000/health` |
| 解析接口 | `http://127.0.0.1:8000/file_parse` |
| 启动脚本 | `/root/doc-services/start_services.sh` |
| 日志文件 | `/root/logs/mineru-api.log` |
| 配置文件 | `/opt/mineru/mineru.env` + `/opt/mineru/mineru.json` |

## 2. 常用命令

```bash
# 启动服务
bash /root/doc-services/start_services.sh start

# 停止服务
bash /root/doc-services/start_services.sh stop

# 重启服务
bash /root/doc-services/start_services.sh restart

# 查看状态（健康检查 + 进程信息）
bash /root/doc-services/start_services.sh status

# 查看最近日志
bash /root/doc-services/start_services.sh logs
```

## 3. 手动健康检查

```bash
curl -s http://127.0.0.1:8000/health | jq .
```

正常返回示例：

```json
{
  "status": "healthy",
  "version": "3.2.1",
  "queued_tasks": 0,
  "processing_tasks": 0,
  "completed_tasks": 0,
  "failed_tasks": 0
}
```

## 4. 进程检查

```bash
# 检查进程是否存在
ps aux | grep mineru-api | grep -v grep

# 检查端口监听
lsof -i :8000
```

## 5. 日志排查

```bash
# 实时跟踪日志
tail -f /root/logs/mineru-api.log

# 查看最近错误
grep -i "error\|exception\|traceback" /root/logs/mineru-api.log | tail -20
```
