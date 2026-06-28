# 三链路完整性 — 审核 & 测试操作手册

> 配套总规划：`docs/superpowers/specs/2026-06-28-three-chain-completeness-plan.md`（架构/矩阵/DoD）。
> 本手册面向**审核 + 手工测试**：怎么起服务、每条链路怎么从 CLI/API/UI 各走一遍、预期是什么、怎么核验不变量。

## 0. 本次交付总览（A→B→B'→C→D 全完成）

| 能力 | CLI | API | UI |
|---|---|---|---|
| collector-A 主题生命周期 | `literature_intake topic` | `GET/POST /api/intake/topics` | `/topics` TopicsReview |
| collector-B 发现(collect) | `literature_intake collect` | `POST /api/intake/collect` | `/topics` 发起采集按钮 |
| collector-C 闸门(resolve) | `literature_intake resolve` | `POST /api/intake/resolve` | `/topics` 触发 resolve 按钮 |
| collector-D A2 审核+晋升 | `literature_intake list/promote` | `/api/intake/candidates·/stats·/review·/promote` | `/intake` IntakeReview |
| ingest-G inbox 手动摄入 | `literature_ingest.py` | `GET /api/ingest/plan`、`POST /api/ingest/execute` | `/inbox` InboxReview |
| parser-E 解析 pending | `literature_batch_parse.py` | `POST /api/parse/trigger` | WorkDetail 触发按钮 |
| parser-F 解析状态/产物 | DB-only | `GET /api/parse/status` | WorkDetail 徽标 |

**不变量**：解析单核 `parser/core/mineru/router.py::route_and_parse`；采集单核 `collector/collect.py::collect_once`；collector 写 works 必经 `ingest_bridge`；解析输出契约 `works/{id}/parsed/mineru/{sfid}/content.md` + `literature_parse_runs.content_md_path`；状态源唯一 `literature_parse_runs`（`parse_ledger.json` 已废弃归档）。

---

## 1. 起服务

```bash
# 后端（默认 8000；vite 代理期望 19527，二选一对齐）
uv run uvicorn api.main:app --host 127.0.0.1 --port 19527   # 或 8000
# 前端
cd web && npm run dev      # vite，默认 5173；web/vite.config.js 把 /api 代理到 127.0.0.1:19527
```
> 端口要对齐：vite 代理目标写死 `19527`。若后端起在别的端口，改 `web/vite.config.js` 的 `proxy./api.target`。

## 2. 测试（自动化基线）

```bash
uv run python -m pytest tests/                 # 213 passed / 6 skipped / 0 failed
uv run python -m pytest --collect-only -q      # 干净收集（testpaths=tests，不收 parser/tests）
```
- **hermetic 核验**：`MinerU_API_KEY= uv run python -m pytest tests/` 也应全绿（不依赖真实 .env）。
- §2 核验：
  ```bash
  grep -rn "def route_and_parse" --include=*.py . | grep -v "_archive\|/docs/"   # 仅 parser/core/mineru/router.py
  grep -rn "def collect_once"   --include=*.py . | grep -v "_archive\|/docs/"   # 仅 collector/collect.py
  grep -rn "INSERT INTO works" collector/                                       # 空（boundary 测试守卫）
  grep -rn "parse_ledger" --include=*.py api/ scripts/ collector/ parser/core/  # 空（已废弃）
  ```

---

## 3. 链路一：采集路径（collector，经候选闸门）

`collect → resolve → IntakeReview 审核 → promote → parse → content.md`

### 3.1 CLI 走法
```bash
# 采集（fetch arxiv 元数据 + 轻量闸门，不下载）
uv run python scripts/literature_intake.py collect --ids 1706.03762
# 闸门（下载 PDF + SHA256；heavy_gate 自管连接）
uv run python scripts/literature_intake.py resolve
# 列待晋升候选
uv run python scripts/literature_intake.py list
# （审核 + 晋升见 API/UI，或 CLI promote 子命令）
```

### 3.2 API 走法（curl，端口按你对齐的来）
```bash
B=http://127.0.0.1:19527
# collect（薄适配器 → collect_once；触达 arxiv 网络）
curl -sS -X POST $B/api/intake/collect -H "Content-Type: application/json" \
  -d '{"explicit_ids":["1706.03762"]}'
# resolve（heavy_gate 下载+SHA256）
curl -sS -X POST $B/api/intake/resolve -H "Content-Type: application/json" -d '{}'
# 审核批准某候选（替换 <cid>）
curl -sS -X PATCH $B/api/intake/candidates/<cid>/review -H "Content-Type: application/json" -d '{"review_status":"approved"}'
# 晋升（经 ingest_bridge 写 works + 建 parse_runs pending）
curl -sS -X POST $B/api/intake/promote -H "Content-Type: application/json" -d '{"ids":["<cid>"]}'
# 解析（→ content.md）
curl -sS -X POST $B/api/parse/trigger -H "Content-Type: application/json" -d '{"work_ids":["W-arxiv-1706.03762"]}'
```

### 3.3 UI 走法
- `/intake`（采集审核）：候选列表 → 详情 → approve → promote。
- `/topics`（主题闸门）：选中主题 → 「按主题发起采集」→ 「触发 resolve」（若建了主题）。
- WorkDetail（`/works/{id}`）：解析触发按钮 + parse 徽标。

### 3.4 预期 / 核验
```bash
uv run python -c "
import sqlite3; c=sqlite3.connect('literature.sqlite'); c.row_factory=sqlite3.Row
pr=c.execute(\"SELECT status,backend FROM literature_parse_runs WHERE work_id='W-arxiv-1706.03762'\").fetchone()
w =c.execute(\"SELECT parse_status FROM works WHERE id='W-arxiv-1706.03762'\").fetchone()
print('parse_run:', dict(pr) if pr else None, '| work.parse_status:', w[0] if w else None)"
ls works/W-arxiv-1706.03762/parsed/mineru/*/content.md   # 应存在
```
**smoke 实测**：succeeded, backend=vlm(cloud), 43.5KB content.md。

---

## 4. 链路二：inbox 旁路（手动摄入，无候选闸门）

`丢 PDF → InboxReview dry-run → ingest → parse → content.md`

### 4.1 准备
把 PDF 丢进 `_inbox/`（支持子目录递归，仅收 `*.pdf`）：
```bash
cp some-paper.pdf _inbox/
```

### 4.2 API 走法
```bash
curl -sS $B/api/ingest/plan                    # dry-run 预览（不写盘）：summary.ingests 应 ≥1
curl -sS -X POST $B/api/ingest/execute -H "Content-Type: application/json" -d '{}'   # 执行摄入
curl -sS -X POST $B/api/parse/trigger -H "Content-Type: application/json" -d '{"work_ids":["<new-work-id>"]}'
```

### 4.3 UI 走法
- `/inbox`（收件箱摄入）：自动读 plan → 列出待摄入 → 「确认摄入」→（再到 WorkDetail 触发解析，或 API trigger）。

### 4.4 CLI 走法（等价）
```bash
uv run python scripts/literature_ingest.py           # dry-run 预览
uv run python scripts/literature_ingest.py --execute # 执行
uv run python scripts/literature_batch_parse.py --execute   # 解析 pending（DB-only）
```

### 4.5 边界（与采集路径互不混）
- ingest **直写 works**（源可信，不经 `intake_candidates`/`ingest_bridge`）。
- collector 摄入**必经 `ingest_bridge`**（临时 inbox 子目录 + 读完即删），不碰用户 `_inbox/` 顶层。
- 精确 SHA256 重复 → 自动归档到 `_duplicates/exact_sha256/`，不建新 work。

**smoke 实测**：BERT 1810.04805 → W-arxiv-1810.04805 → succeeded, backend=pymupdf(本地), 66.8KB content.md。

---

## 5. 主题闸门（topics 成熟度，collector-A 真价值）

> live DB 的 `collection_topics` 表当前**为空**——需先建主题才能跑闸门。建主题后即可在 `/topics` 走 seedling→proposed→mapped。

### 5.1 建主题（CLI；UI 暂只做成熟度流转 + 采集，创建留 CLI）
```bash
uv run python scripts/literature_intake.py topic add \
  --name "目标错误泛化" --description "..." \
  --explicit-ids 2506.19248 --axis-hint risk_domain
```

### 5.2 成熟度闸门（4 判据 = 复现性 / 不可折叠性 / 轴归属 / 边界可述）
- core 只强制：`proposed` 必须带非空 `proposed_note`；`mapped` 必须带 `mapped_tags`；状态只能 `seedling→proposed→mapped` 单调前进。
- UI `/topics`：点 `seedling→proposed` 弹框填 proposed_note（提示 4 判据）；`proposed→mapped` 填 mapped_tags（`group=value`，如 `risk_domain=alignment_fail`）。
- API：`POST /api/intake/topics` body `{id, to_map_status, proposed_note/mapped_tags, ...}`。
- **不碰本体词表**：`mapped_tags` 只记 JSON blob，不写 vocab（有 `test_collection_topics` 守卫）。

### 5.3 按主题发起采集
`/topics` 选中主题 → 「按主题发起采集」（调 `collect_once(topic_id=...)`，读该主题 `query_def` 的 explicit_ids/seed_paper_ids 分发）。也支持 topic + 临时 explicit_ids 组合（均归属该主题）。

---

## 6. 已知边界 / follow-up（非阻塞，供审核参考）

1. **topics 表为空**：链路已通，缺的是数据——需你在 UI/CLI 建主题后才能真正跑成熟度闸门。
2. **smoke 新增 2 个真实 work**：`W-arxiv-1810.04805`(BERT)、`W-arxiv-1706.03762`(Attention)，均解析成功、title 为占位（元数据抽取未跑，留给 metadata review）。不需要可在 Works 页隔离删除。
3. **parser/tests 不被根 pytest 收集**（`testpaths=["tests"]`，因依赖 fitz；hygiene 设计）。
4. **真实 smoke 须在带 `.env`(MinerU_API_KEY) + 网络的环境跑**；自动化测试全 hermetic（不依赖真网络/真 fitz/真 .env）。
5. `ingest_bridge.promote` 的 `library_root` 隐式依赖 `api.db.LIBRARY_ROOT`（生产 OK）。
6. born-digital PDF 走 PyMuPDF 本地（免费）；扫描型/质检不过 → 回退 cloud vlm（耗 API 配额）。

## 7. 合并轨迹（master）

`048a93e`(Phase A) → `d42455a`(Phase B) → `49579d6`(D-hygiene) → `0a9d508`(D 状态源统一) → `bd02763`(Phase B') → `cf26db8`(Phase C) → `c93a8e5`(D-acceptance)。各 phase 均为 `--no-ff` 合并，保留 phase 点。实施计划见 `docs/superpowers/plans/2026-06-2*-*.md`。
