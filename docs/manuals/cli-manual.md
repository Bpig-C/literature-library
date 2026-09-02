# CLI 与自动化手册

> 状态：当前权威
> 更新时间：2026-07-05
> 面向对象：本地命令操作者、批处理脚本、CI/自动化检查、需要调用命令的 agent

本手册讲命令行和自动化入口。浏览器页面使用看 [用户手册](user-manual.md)；agent 协作边界看 [Agent 协作手册](agent-manual.md)。

## 环境与端口

常用端口：

- FastAPI 后端：`19527`
- Vue 前端：`19528`

启动后端（日常推荐）：

```powershell
uv run python scripts\run_api.py
```

启动后端（开发热重载）：

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
python scripts\check_docs.py
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

强制重解析指定文献（不限 pending 状态），并可指定后端：

```powershell
# 强制云 VLM（保留版面图表，耗时分钟级、耗官网额度）
python scripts\literature_batch_parse.py --execute --work-ids W-sha-xxxx --force --backend vlm
# 强制 PyMuPDF 本地直抽（秒级，提取文本层栅格图）
python scripts\literature_batch_parse.py --execute --work-ids W-sha-xxxx --force --backend pymupdf
```

`--backend` 取值：`auto`（默认，双路合并：云 VLM 优先+生成合并视图，失败回退
PyMuPDF 本地）/ `pymupdf` / `vlm`（强制后端，显式指定不回退）。`--force` 必须配合
`--work-ids`；多源 work（同一文献多个 PDF 副本）可用 `--source-file-ids` 精准指定
某一副本。重解析前会自动清理该文献解析输出目录中的已知产物。

解析状态以 SQLite 的 `literature_parse_runs` 为准，不再使用历史 `parse_ledger.json`。

查看当前库状态：

```powershell
python scripts\healthcheck_library.py --json
```

查看 `_inbox` 中待摄入 PDF：

```powershell
Get-ChildItem _inbox -Recurse -Filter *.pdf
```

历史只读台账仍可生成，但日常推荐使用 Vue SPA：

```powershell
python scripts\literature_dashboard.py
```

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

完整交互式 API 文档在 `http://127.0.0.1:19527/docs`。下面只列自动化和 agent 最常用入口。

文献、文件和关系：

| 方法 | 路径 | 用途 |
|------|------|------|
| `GET` | `/api/works` | 文献列表，支持搜索、筛选、分页 |
| `GET` | `/api/works/{id}` | 文献详情 |
| `PATCH` | `/api/works/{id}` | 更新文献元数据 |
| `POST` | `/api/works/{id}/quarantine` | 隔离文献 |
| `POST` | `/api/works/{id}/restore` | 恢复隔离文献 |
| `GET` | `/api/files/{work_id}/content` | 获取解析后的 `content.md` |
| `GET` | `/api/files/{work_id}/images/{name}` | 获取解析产物图片（content.md 中 `images/` 引用） |
| `GET` | `/api/files/{work_id}/pdf` | 获取 PDF 文件 |
| `GET` | `/api/relations` | 文献关系列表 |
| `POST` | `/api/relations` | 新增关系 |
| `DELETE` | `/api/relations` | 删除关系 |

摄入、解析和流水线：

| 方法 | 路径 | 用途 |
|------|------|------|
| `GET` | `/api/ingest/plan` | 摄入 dry-run 预览 |
| `POST` | `/api/ingest/execute` | 执行摄入 |
| `GET` | `/api/parse/status` | 查询解析状态 |
| `POST` | `/api/parse/trigger` | 触发解析；可选 `backend`（auto/pymupdf/vlm）与 `force: true`（配合 `work_ids` 强制重解析） |

发现检索和采集候选：

| 方法 | 路径 | 用途 |
|------|------|------|
| `POST` | `/api/discovery/plan` | 生成 discovery search plan |
| `POST` | `/api/discovery/run` | 创建 discovery run |
| `GET` | `/api/discovery/runs` | run 列表 |
| `GET` | `/api/discovery/runs/{run_id}` | 单个 run 和 search plan |
| `POST` | `/api/discovery/runs/{run_id}/hits` | agent 回填 hits |
| `GET` | `/api/discovery/hits` | 命中列表 |
| `POST` | `/api/discovery/hits/{hit_id}/accept` | 接受 hit 并创建 intake candidate |
| `POST` | `/api/discovery/hits/batch-accept` | 批量接受 hits |
| `POST` | `/api/discovery/hits/{hit_id}/reject` | 拒绝 hit |
| `GET` | `/api/intake/candidates` | 采集候选列表 |
| `PATCH` | `/api/intake/candidates/{candidate_id}/review` | 审核候选 |
| `POST` | `/api/intake/promote` | 批量提升已批准候选 |

元数据和模板：

| 方法 | 路径 | 用途 |
|------|------|------|
| `GET` | `/api/metadata` | 元数据抽取审核队列 |
| `POST` | `/api/metadata/extract` | 触发元数据抽取 |
| `GET` | `/api/metadata/{ext_id}` | 元数据抽取详情 |
| `PATCH` | `/api/metadata/{ext_id}/review` | 审核抽取结果 |
| `POST` | `/api/metadata/apply-approved` | 回填已批准且未应用的抽取结果 |
| `POST` | `/api/metadata/batch-approve-low-risk` | 批量批准低风险 pending 记录 |
| `GET` | `/api/metadata/agent/queue` | 获取 agent 修复队列 |
| `GET` | `/api/metadata/{ext_id}/rerun-prompt` | 生成字段级 prompt |
| `POST` | `/api/metadata/{ext_id}/rerun-preview` | 字段级重抽预览 |
| `POST` | `/api/metadata/{ext_id}/rerun-apply` | 确认预览并写入 superseding extraction |
| `POST` | `/api/metadata/{ext_id}/supersede` | 用外部结果创建替换抽取 |
| `GET` | `/api/templates` | 模板概览 |
| `GET` | `/api/templates/metadata/schema` | 元数据模板字段 schema |
| `POST` | `/api/templates/metadata` | 保存元数据字段模板 |
| `POST` | `/api/templates/metadata/reset` | 恢复元数据默认模板 |

分类：

| 方法 | 路径 | 用途 |
|------|------|------|
| `GET` | `/api/classification/tags/{work_id}` | 获取文献分类标签 |
| `POST` | `/api/classification/tags/{work_id}` | 创建分类标签 |
| `POST` | `/api/classification/tags/{work_id}/batch` | 批量创建分类标签 |
| `DELETE` | `/api/classification/tags/{tag_id}` | 删除分类标签 |
| `PATCH` | `/api/classification/tags/{tag_id}/review` | 审核分类标签 |
| `GET` | `/api/classification/vocab` | 分类词汇表 |
| `GET` | `/api/classification/extractions` | 分类抽取列表 |
| `POST` | `/api/classification/extract` | 触发分类抽取 |
| `GET` | `/api/classification/extractions/{ext_id}` | 分类抽取详情 |
| `PATCH` | `/api/classification/extractions/{ext_id}/review` | 审核分类抽取结果 |

引用导出与综述矩阵（门禁：仅含元数据已批准且未隔离的文献）：

| 方法 | 路径 | 用途 |
|------|------|------|
| `GET` | `/api/export/bibtex` | BibTeX 引用导出 |
| `GET` | `/api/export/ris` | RIS 引用导出 |
| `GET` | `/api/export/matrix.csv` | 综述矩阵 CSV 导出 |

```powershell
curl "http://localhost:19527/api/export/bibtex"
```

（ris、matrix.csv 同理替换路径。）

批量 agent 不需要从前端复制 prompt；直接读模板并调用 CLI/API。

## 本地脚本速查

脚本细节见 `scripts/README.md`。常用入口：

| 脚本 | 用途 |
|------|------|
| `scripts\literature_ingest.py` | `_inbox` 摄入 |
| `scripts\literature_batch_parse.py` | 批量解析 pending 文献 |
| `scripts\literature_dashboard.py` | 生成历史只读 HTML 台账 |
| `scripts\literature_dedup.py` | 去重候选分析 |
| `scripts\dedup_apply.py` | 应用去重决策 |
| `scripts\literature_metadata_extract.py` | 元数据抽取 |
| `scripts\literature_metadata_rerun.py` | 修复队列、字段级重抽、supersede |
| `scripts\literature_classification_extract.py` | 分类候选抽取 |
| `scripts\literature_discovery.py` | 发现检索 CLI |
| `scripts\check_docs.py` | 文档治理轻量门禁 |

## 安全边界

- 不要打印 `.env` 中的密钥值。
- 不要手动移动 `works`、`_quarantine`、`_archive` 中的文件后忘记同步数据库。
- 不要恢复旧的自部署 MinerU / document-parser 默认路径。
- 不要把一次性脚本长期留在 `scripts/` 根目录；需要归档到 `scripts/_archive/`。
