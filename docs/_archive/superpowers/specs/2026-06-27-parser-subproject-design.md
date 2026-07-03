# P3.5 文档解析子项目化 —— 实施设计

> 状态：**待确认**（确认后再动手）
> 日期：2026-06-27
> 关联：`FUTURE_WORK_PLAN.md` P3.5；记忆 `document-parser-subproject-todo`

## 0. 背景与现状核实

- 文档解析依赖仓库外 `D:\06_tools\document-parser`（FastAPI 封装 18201 + 自部署 MinerU 18200）。
- **关键发现**：`scripts/literature_batch_parse.py` 并不经过 document-parser 的 HTTP 服务，而是**直连自部署 MinerU 的异步 `/tasks` API（18200）**。所以真正的衔接面是 `literature_batch_parse.py`，不是 document-parser 服务。
- **契约（不可破坏）**：解析产物落 `works/{work_id}/parsed/mineru/{source_file_id}/content.md` + `content.json`，路径写 `literature_parse_runs.content_md_path`（绝对路径）。下游元数据抽取/分类/分析**只读 `content_md_path`**，不重新解析 PDF。
- `literature_parse_runs` 字段：`id, work_id, source_file_id, source_path, task_id, status, backend, parse_method, file_size, started_at, finished_at, output_dir, error, content_json_path, content_md_path, package_path`。已含 `backend`/`parse_method`/`task_id`/`package_path` 列，天然容纳官网 API 的 batch_id/zip。
- **样本核实**：所谓"5 篇 pending"（`W-arxiv-2406.10162` 等 reward hacking / goal misgeneralization）在 `literature_parse_runs` 里**已经是 `succeeded`**，只是 `works.parse_status` 滞留在 `pending`（状态不同步）。→ 它们适合做**一致性重解析**，不是全新 pending。
- 仓库 `doc_type` 分布：paper(86) / report(24) / system_card(13) / benchmark(12) / preprint(8)，可作为路由启发式输入。

## 1. MinerU 官网精准解析 API 关键事实（已读官方文档 + 限流页）

- 鉴权：`Authorization: Bearer <token>`，token 在「API 管理」页自建。**token 由用户提供，不编造。**
- 本地文件流程（我们走这条，因为 PDF 在本地）：
  1. `POST /api/v4/file-urls/batch`，body `{"files":[{"name":"x.pdf","is_ocr":F,"data_id":...}], "model_version":"pipeline|vlm", "language":"en", "enable_formula":T, "enable_table":T}` → 返回 `batch_id` + `file_urls[]`（预签名 PUT，有效期 24h）。
  2. `PUT <file_urls[i]>`（**不要设 Content-Type**）上传文件 → 系统自动提交解析。
  3. 轮询 `GET /api/v4/extract-results/batch/{batch_id}` → 每个 `extract_result[].state`：`waiting-file/pending/running/converting/done/failed`。`done` 时给 `full_zip_url`。
  4. 下载 zip → 解压。产物：`full.md`（=我们的 content.md）、`content_list.json`、`layout.json`(=middle.json)、`*_model.json`、`images/`。
- 限制：单文件 ≤200MB / ≤200 页；批量单次 ≤50 个文件。
- **限流**：提交类接口共用 **50 文件/分钟**；单用户 **5000 文件/天**（html 100/天）；结果查询 **1000 次/分钟**；每日 **1000 页享最高优先级**，超出降级（仍可解析）。
- **计费**：官方限流页明确「**目前暂无商业化收费计划**」→ 当前免费。
- 错误码要点：`A0202` token 错、`A0211` token 过期、`-60018` 每日任务数达上限、`-60009` 队列已满（稍后重试）。

## 2. 待决问题结论

| 待决 | 结论 |
|---|---|
| 计费/配额是否够批量回填 | **够。** 当前免费；5000 文件/天、50 文件/分钟、1000 页/日高优先级，远超个人博士文献库回填量。 |
| 自部署 MinerU 处置 | **保留作降级**（用户已选）。代码留在 `parser/`，默认关闭，`MINERU_BACKEND=cloud\|selfdeploy` 可切回。 |

## 3. 子项目目录结构

复制 `D:\06_tools\document-parser` → `parser/`，**剔除**运行时/大文件/无关产物：

```
parser/
├── README.md                  # 改写：说明它现在是本仓库子项目 + 两种后端
├── pyproject.toml             # 独立依赖（fastapi/httpx/pymupdf/requests...），自带 pythonpath
├── uv.lock                    # 保留，锁版本
├── conf.json                  # 复制后改造（见 §5）
├── .gitignore                 # 新增：Datas/ logs/ .venv/ output/ *.zip
├── main.py                    # FastAPI 服务入口（保留，供交互/其他消费者）
├── config.py                  # 扩展 cloud 相关字段
├── api/  core/  server/  tests/   # 原样保留（FastAPI 服务 + LocalClient/WebClient 降级）
└── core/mineru/
    ├── base_client.py         # PdfParseClient 抽象 + ParseRequest（不动）
    ├── local_client.py        # 自部署命令行（降级用，保留）
    ├── web_client.py          # 自部署 HTTP /file_parse（降级用，保留）
    ├── cloud_client.py        # 【新增】官网精准解析 API 客户端（主路径）
    └── mineru_op.py           # 按 config 选 client（扩展 cloud 分支）
```

复制时**剔除**：`.git/ .venv/ .pytest_cache/ Datas/ logs/ PROJECT_INDEX/history/ html/`（运行时/生成物）。`Datas/` 里大量 MinerU 历史 jpg 不进 VCS。

## 4. API 适配层设计（cloud_client.py）

实现与 `LocalClient/WebClient` 同一个 `PdfParseClient.parse_pdf(req)->(bool,msg)` 接口，使其无缝接入 `mineru_op` 调度，也供 `literature_batch_parse.py` 进程内直连调用。

```python
class CloudClient(PdfParseClient):
    def parse_pdf(self, req: ParseRequest) -> tuple[bool, str]:
        # 1. POST /api/v4/file-urls/batch  → batch_id + upload_url
        # 2. PUT upload_url (无 Content-Type) 上传 PDF
        # 3. 轮询 GET /api/v4/extract-results/batch/{batch_id} 直到 done/failed（受 config.timeout）
        # 4. 下载 full_zip_url → 安全解压到 req.output_dir/<stem>/
        # 5. full.md → 产出 content.md；content_list.json → content.json
        #    images/ → 拷贝到输出目录，保证 md 内图片引用可解析
        # 6. 返回 (True, msg)；失败/超时返回 (False, err)
```

要点：
- **上传不设 Content-Type**（官方要求）；用 `requests.put(url, data=f)`。
- **限流/重试**：提交遇 `-60009`(队列满) / 429 / 网络错 → 指数退避重试（≤3 次）；`-60018`(日上限) → 不重试，标记 failed 并提示明日再试。
- **解压安全**：复用 `web_client._safe_extract_zip` 的逐文件防穿越逻辑。
- **输出映射**（契约不变）：
  - `content.md` ← `full.md`
  - `content.json` ← `content_list.json`（比现行 `{"raw_result":...}` 更有用；下游只读 `content_md_path`，格式变更不影响）
  - `package.zip`（原 zip）→ 记 `package_path`；`layout.json`/`*_model.json` 一并保留供排查
- **并发**：保持 `max_workers=1`；官网 50 文件/分钟限流在客户端用令牌桶软限速（默认远低于 50）。

## 5. 模型路由策略（回答"哪些文献走复杂流程"）

默认 **pipeline**，用"先廉价、失败再升级"的两段闸门，而不是预先分类：

1. **入口默认**：`model_version=pipeline`，`language` 按文献语言（`works.language`，英文论文 `en`）。
2. **OCR 自动探测**：上传前用 PyMuPDF 探测 PDF 是否有文本层；若平均每页文本字符过低（疑似扫描件）→ 该任务 `is_ocr=true`（pipeline 即可，无需 vlm）。
3. **显式覆盖**：`literature_parse_runs.backend` 已有列。允许对单个 work 标 `backend=vlm` 强制走高质量路径（如复杂表格的标准/报告：`doc_type ∈ {system_card, report, benchmark}` 且页数大）。
4. **质量回退闸门**（**本地强模型裁判 → 自动升级**，见 §5b）：
   - pipeline 解析后，由 §5b 的共享 LLM 裁判（**opencode → MiMo-v2.5-pro**，能通篇阅读）对 `content.md` 出一份类型化质量裁决。
   - 裁决 `quality=poor` 或 `needs_reparse=true` → 自动以 `model_version=vlm` 重解析一次，取较好结果。
   - **可选轻量预筛**（默认关）：先用启发式（提取率/字符数/乱码比）跳过明显良好的文档，省 opencode 调用；开启时只把"存疑"的送裁判。默认仍是**每篇都判**（用户已选）。

→ 这样"需要复杂流程的文献"由 **(a) 显式 per-work 标记** 或 **(b) 模型裁判失败自动升级** 决定，不依赖人工预判，也省 vlm 额度。

## 5b. 共享「本地强模型裁判」模块（opencode → MiMo-v2.5-pro）

> 用户决策：旧 Ollama qwen3:4b 不胜任通篇阅读；改用 **MiMo-v2.5-pro**，且该模型只能经 **opencode CLI** 调用（配置在 `~/.config/opencode/opencode.json`，provider `mimo`，云端 API `token-plan-cn.xiaomimimo.com`）。本模块是**解析质量门 + 后续元数据/主题/分类**共用的基础设施，现在就建。

**调用契约**（已冒烟验证）：
```
opencode run --pure -m mimo/mimo-v2.5-pro --format json "<prompt>"
```
- `--pure`：禁用外部插件，避免工具调用，保证确定性的纯文本 JSON 输出。
- `--format json`：流式 NDJSON。assistant 文本在各 `{"type":"text","part":{"text":"..."}}` 事件中，**拼接所有 `text` 事件的 `part.text`** 得完整回复；末尾 `step_finish` 带 token 计数。
- 退出码 0 = 成功；超时/非 0 = 失败，按重试策略处理。

**成本现实**（实测）：单次调用固定注入 **~15k input tokens** agent 脚手架（与 prompt 无关）。→ 质量门建议：裁判只送 content.md 的**结构化摘要**（首尾 N 字 + 章节标题 + 字符/页数统计）而非全文，把单次成本压到可控；**全文通篇阅读留给后续真正需要正文的抽取/主题/分类任务**。

**模块设计**（`scripts/llm_judge.py`，被 parser 质量门与下游共用）。**两种输出模式**：
- `judge(prompt, model="mimo/mimo-v2.5-pro", ...) -> dict`：**内联 JSON 模式**——解析 NDJSON 抽 assistant 文本，强制提取 JSON（容许 ```json fence），返回类型化 dict。质量门用这个。
- `run_executor(task_prompt, expected_outputs, ...) -> dict`：**执行器/写文件模式**——让 agent 按提示写结构化产物文件后校验。下游元数据/主题/分类用这个。**本期只建 `judge`，`run_executor` 留接口、实现待下游启动时补**（复用同一批运行时原语）。
- `quality_verdict(content_md_path) -> dict`：基于 `judge`，构造质量裁判 prompt（喂结构化摘要），返回固定 schema：
  ```json
  {"quality":"good|acceptable|poor","needs_reparse":bool,
   "issues":["missing_abstract","missing_refs","garbled","low_extraction",...],
   "completeness":0.0-1.0,"reason":"<短句>"}
  ```

**运行时硬化原语**（从参考项目 `ei_corpus_loop_serial_qbatch_001a` 的 `run_loop.py` 借鉴——那是成熟的 opencode-as-executor 运行时）：
- `find_opencode()`：Windows 下依次找 `opencode.cmd/.exe/opencode`，避免 shim 路径问题（参考 `run_loop.py:162-176`）。
- **flags 在前、message 在后**的命令拼装顺序（`run_loop.py:486-497`），规避 Windows shim 截断多行 message。冒烟测试已符合。
- **流式读取 + 双超时 + 进程树清理**：总超时 + **无输出超时(idle timeout)**，超时用 `taskkill /T /F`(Win) 杀整棵进程树（`run_loop.py` `run_streaming_process`/`kill_process_tree`）。比 `subprocess.run(timeout=)` 强：能识别"活着但不输出"的挂起，且不残留子进程。opencode 偶发挂起，这是关键稳健性。
- **noop/拒答检测**：模型返回散文/拒答而非 JSON 时识别并重试（参考 `looks_like_noop_response`）。
- **调用日志(JSONL + fsync)**：每条记 `run_id/model/tokens/cost/returncode/verdict`，便于核算 ~15k 脚手架成本与审计。
- **输出纪律写进 prompt**（参考 `RESEARCH_EXECUTOR.md`）：不编造、不向用户提问/不等待、只输出规定 JSON、完成即止。

**明确不搬**（过度设计/你已说可忽略）：编排+看门狗多 agent loop、`next_action.json`/`action_space.yaml` 机制、串行约束强制、`human_questions.md` 升级流、session export 诊断。（裁判失败只记日志 + 返回降级裁决，不升级人工。）

- **不在本仓库硬编码 MiMo apiKey**（它在用户 opencode 全局配置里，CLI 自带鉴权）；模块只认 `model` 参数。

## 6. 配置项（conf.json + 环境变量）

`parser/conf.json` 新增 `mineru` 段：

```jsonc
"mineru": {
  "localcommand_mineru": false,     // 自部署命令行降级（默认关）
  "backend": "cloud",               // cloud | selfdeploy  （selfdeploy=走原 WebClient/LocalClient）
  "cloud": {
    "api_base": "https://mineru.net",
    "token_env": "MINERU_API_TOKEN",// token 只从环境变量读，不入 conf.json
    "model_version": "pipeline",    // pipeline | vlm | MinerU-HTML
    "language": "en",               // 默认英文论文
    "is_ocr_auto": true,            // 自动探测扫描件
    "poll_interval": 10,
    "timeout": 1800,
    "submit_rate_per_min": 30,      // 软限速，低于 50
    "quality_gate": false           // 质检自动升级 vlm，默认关
  },
  "mineru_server_url": "...",       // selfdeploy 降级时用
  "timeout": 1800
}
```

`config.py` 扩展读取（token 强制 `os.getenv`，禁止落盘）。`.env`/`.env.example` 在 `parser/` 内加 `MINERU_API_TOKEN=`（空值占位）。

## 7. 与 `scripts/literature_batch_parse.py` 的衔接（进程内直连）

改造该脚本：去掉对 `:18200/tasks` 的直连，改为 `from parser.core.mineru import CloudClient`（或经 `mineru_op`），单进程调用：

```python
# 伪代码
client = CloudClient()
ok, msg = client.parse_pdf(ParseRequest(pdf_path=..., output_dir=run["output_dir"],
                                        backend=run.get("backend","pipeline"), ...))
# ok 后定位 content.md/content.json，按现行逻辑写 literature_parse_runs + parse_ledger.json
```

保留：dry-run、`--execute`、`--limit`、ledger 原子写、`max_workers=1` 串行、状态机（pending→succeeded/failed）。`MINERU_URL` 常量删除。

`parser/` 加进 `sys.path`（脚本头 `sys.path.insert` 或 `parser/pyproject.toml` 的 pythonpath + 以 `python -m` 运行）。

## 8. 迁移与验证步骤（可回滚）

**阶段 A — 落地子项目，不碰 DB（纯代码）**
1. 复制 document-parser → `parser/`，剔除运行时目录，加 `parser/.gitignore`。
2. 新增 `cloud_client.py` + 扩展 `config.py`/`conf.json`。
3. 改造 `literature_batch_parse.py` 衔接新 client（保留旧逻辑作函数备查，不删）。
4. 单测：mock 官网 API（batch→upload→poll→zip）跑通 `cloud_client.parse_pdf`，**不真实联网**。提交 `parser/`。
5. 建 `scripts/llm_judge.py`（§5b）：opencode→MiMo 调用 + NDJSON 解析 + 类型化 JSON 提取 + 重试/超时。用 1 篇真实 content.md 做端到端冒烟（真实 opencode 调用，验证 schema 落地）。**不写 DB**。

**阶段 B — 真实试跑（隔离输出，不动契约路径）**
5. 用户提供 `MINERU_API_TOKEN`。
6. 对 3 篇 reward-hacking 样本（已 succeeded）用官网 API 重解析，输出到**临时目录**（如 `parsed/mineru_cloud_trial/`），**绝不覆盖**现有 `content.md`。
7. 一致性比对：新旧 `content.md` 的字符数、章节数、是否含核心段落（abstract/refs）、首尾完整性；并对新旧各跑一次 §5b 裁判，比对 `quality`/`completeness` 裁决。记录到报告。

**阶段 C — 正式写契约（经确认后）**
8. 选 1–2 篇做 `--execute`，按真实路径写 `content.md`/`content.json`，更新 `literature_parse_runs`（`backend=cloud`, `task_id=batch_id`, `package_path`）+ ledger。
9. 抽样 5 篇已解析文献重解析比对，确认下游元数据抽取链路（读 `content_md_path`）不受影响。

**阶段 D — 收尾**
10. 文档：更新 `TECHNICAL_OVERVIEW.md` §2 解析链路、`FUTURE_WORK_PLAN.md` P3.5 状态、`parser/README.md`。
11. 处理 `works.parse_status` 滞留不同步问题（独立小修，或登记为后续任务）。

**回滚**：阶段 B 始终隔离输出；阶段 C 前 `content.md` 原样保留；配置 `MINERU_BACKEND=selfdeploy` 可整体切回旧行为；旧 `literature_batch_parse.py` 逻辑不删除，保留作回退参考。

## 9. 验收标准

- `parser/` 进 VCS，解析能力不再依赖 `D:\06_tools\document-parser`。
- 新 PDF 走官网精准 API 成功产出 `content.md`+`content.json`，路径契约与现有一致。
- 限流/失败（含日上限、队列满、token 过期）有明确处理，不污染 `pending`/`succeeded` 状态。
- token 仅从环境变量读，不落盘、不入 VCS。
- 自部署降级路径保留且可配置切换。

## 10. 风险与注意

- token 过期（`A0211`）→ 失败明确提示，不静默重试。
- 官网 zip 结构若与文档不符（字段名漂移）→ 解析时按 `full.md` 存在性断言，缺失即判失败并保留原始 zip 供排查。
- 文献含国外 URL 不影响（我们是上传本地文件，不走 URL 提交）。
- 不直接删任何文件；并发保守（`max_workers=1`）。
