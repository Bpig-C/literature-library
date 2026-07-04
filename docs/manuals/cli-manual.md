# CLI 与自动化手册

> 状态：当前权威
> 更新时间：2026-07-05
> 面向对象：本地命令操作者、批处理脚本、CI/自动化检查、需要调用命令的 agent

本手册讲命令行和自动化入口。浏览器页面使用看 [用户手册](user-manual.md)；agent 协作边界看 [Agent 协作手册](agent-manual.md)。

## 环境与端口

常用端口：

- FastAPI 后端：`19527`
- Vue 前端：`19528`

启动后端：

```powershell
uvicorn api.main:app --port 19527 --reload
```

启动前端：

```powershell
cd web
npm run dev
```

构建前端：

```powershell
cd web
npm run build
```

## 验证命令

常规后端测试：

```powershell
python -m pytest tests -q -p no:cacheprovider --basetemp .codex_tmp\pytest-all
```

健康检查：

```powershell
python scripts\healthcheck_library.py --json
```

文档/提交前检查：

```powershell
git diff --check
```

前端构建：

```powershell
cd web
npm run build
```

## 新文献摄入与解析

查看收件箱摄入计划：

```powershell
python scripts\literature_ingest.py
```

执行摄入：

```powershell
python scripts\literature_ingest.py --execute
```

解析 pending 文献：

```powershell
python scripts\literature_batch_parse.py --execute
```

解析状态以 SQLite 的 `literature_parse_runs` 为准，不再使用历史 `parse_ledger.json`。

## 元数据抽取与重抽

元数据模板事实源：

- 模板资产：`templates/templates.json`
- runtime loader：`api/metadata_template.py`
- 脚本说明：`scripts/README.md`

抽取待处理文献：

```powershell
python scripts\literature_metadata_extract.py --limit 10
```

对指定 work 强制抽取：

```powershell
python scripts\literature_metadata_extract.py --work-id W-arxiv-xxxx --force
```

查看待修复队列：

```powershell
python scripts\literature_metadata_rerun.py --status needs_fix --limit 20
```

字段级重抽：

```powershell
python scripts\literature_metadata_rerun.py --ext-id ME-xxxx --fields title,url,journal --rerun
```

预览字段级重抽，不写库：

```powershell
python scripts\literature_metadata_rerun.py --ext-id ME-xxxx --fields journal --rerun --no-write --json
```

约束：

- `--fields` 必须是当前模板字段 key；脚本会校验白名单。
- 重抽写入新的 `metadata_extractions`，并 supersede 旧记录。
- 不要让批处理绕过审核直接写 `works`。

## API 自动化入口

常用元数据 API：

| 方法 | 路径 | 用途 |
|------|------|------|
| `POST` | `/api/metadata/extract` | 触发元数据抽取 |
| `GET` | `/api/metadata/agent/queue` | 获取 agent 修复队列 |
| `GET` | `/api/metadata/{ext_id}/rerun-prompt` | 生成字段级 prompt |
| `POST` | `/api/metadata/{ext_id}/rerun-preview` | 字段级重抽预览 |
| `POST` | `/api/metadata/{ext_id}/rerun-apply` | 确认预览并写入 superseding extraction |
| `POST` | `/api/metadata/{ext_id}/supersede` | 用外部结果创建替换抽取 |
| `POST` | `/api/templates/metadata` | 保存元数据字段模板 |

批量 agent 不需要从前端复制 prompt；直接读模板并调用 CLI/API。

## 安全边界

- 不要打印 `.env` 中的密钥值。
- 不要手动移动 `works`、`_quarantine`、`_archive` 中的文件后忘记同步数据库。
- 不要恢复旧的自部署 MinerU / document-parser 默认路径。
- 不要把一次性脚本长期留在 `scripts/` 根目录；需要归档到 `scripts/_archive/`。

