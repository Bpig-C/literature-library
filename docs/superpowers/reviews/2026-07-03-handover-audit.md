# 2026-07-03 交接报告全面审查

## 审查范围

本轮审查覆盖交接报告提到的文档、后端采集链路、模板管理、采集审核前端、测试与健康检查。

已读取/抽查的核心文件包括：

- `FUTURE_WORK_PLAN.md`
- `docs/HANDOVER_GUIDE.md`
- `docs/PROJECT_HISTORY.md`
- `USER_ISSUES.md`
- `.workbuddy/memory/MEMORY.md`
- `api/main.py`
- `api/routes/templates.py`
- `api/routes/intake.py`
- `collector/discovery.py`
- `collector/gate.py`
- `collector/ingest_bridge.py`
- `web/src/api.js`
- `web/src/views/TemplateManage.vue`
- `web/src/views/IntakeReview.vue`

## 审查结论

交接报告的大方向基本可信：`/templates` 页面、采集审核来源追溯、PDF 操作入口、Discovery accept 反向提取 arXiv ID 等确实已经落地。

但原交接报告存在过度乐观：审查开始时当前工作树的后端无法导入，`pytest tests -q` 不可能在该状态下完整通过；“模板管理后端就绪”也只代表 CRUD 就绪，不代表抽取链路已经真正模板化。

## 已当场修复的问题

| 严重性 | 问题 | 修复 |
|---|---|---|
| P0 | `api/routes/templates.py` 使用 `BaseModel` 但未导入，导致 `import api.main` 失败 | 增加 `from pydantic import BaseModel` |
| P1 | `collector/gate.py` 在 `sqlite3.Row` 上调用 `.get()`，无 arXiv 候选下载路径会崩溃 | 改为按 `row.keys()` 安全读取 `url_canonical` |
| P1 | `web/src/api.js` 对 `FormData` 请求仍强塞 `Content-Type: application/json`，手动上传 PDF 会破坏 multipart boundary | `request()` 遇到 `FormData` 时不设置默认 JSON 头 |
| P2 | `collector/ingest_bridge.py` 晋升后写入 `review_status='ingested'`，混用审核状态和生命周期状态 | 晋升只写 `status='ingested'` 与 `ingested_work_id`，保留 `review_status` 的人工审核语义 |
| P1 | `web/src/api_templates.js` 请求路径重复 `/api`，保存请求未 JSON 序列化 | 模板 API 前端封装改为 `/templates`，保存 body 使用 `JSON.stringify` |
| P1 | `api/routes/intake.py` 将字符串路径传给 `sha256_file(Path)` | 保存目标改为 `Path` 对象后再计算 SHA256 |

## 保留的待整改问题

1. 模板管理仍是维护界面和存储层，尚未接入 `literature_metadata_extract.py` / rerun / 分类抽取的真实 prompt 与字段选择链路。
2. `/api/intake/candidates/{id}/upload-pdf` 缺少生命周期保护：已入库、已拒绝、已有 PDF 的候选仍可能被覆盖。
3. `/api/ingest/upload` 声明了 200MB 限制但未执行，且同名文件会覆盖 `_inbox` 既有文件。
4. `USER_ISSUES.md` 原先把 UX-003 同时放在“待处理”和“已解决”，已在本轮修正文档。

## 验证结果

- `python -c "import api.main; print('import ok')"`：通过
- `pytest tests -q -p no:cacheprovider --basetemp .codex_tmp\pytest-all-audit`：511 passed, 5 skipped
- `python scripts\healthcheck_library.py --json`：五类问题全空
- `npm.cmd run build`：通过

## 给下个 agent 的要求

后续实现任务必须派发至少两类子审查：

1. 实施子 agent：负责具体代码改动，输出文件列表和验证命令。
2. 审核子 agent：只读复核，检查文档状态、测试覆盖、接口契约和未声明副作用。

每个任务至少两轮复核：第一轮查功能是否成立，第二轮查是否与文档、测试、数据库状态和用户红线冲突。
