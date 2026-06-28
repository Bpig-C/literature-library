# 三链路完整性总体规划（CLI / API / UI）

> 日期：2026-06-28
> 状态：总体规划（落地依据），任务计划与实施由后续 agent 负责
> 关联：`FUTURE_WORK_PLAN.md`（P3.5 parser、P6 collector）、`docs/superpowers/specs/2026-06-27-collector-integration-design.md`、`docs/superpowers/specs/2026-06-27-collector-retrieval-design.md`、`docs/superpowers/specs/2026-06-27-parser-subproject-design.md`
> 上位：`D:\02_academic\doctoral\LITERATURE_SYSTEM_PLAN.md`

## 1. 目标

让文献库的每个能力在 **CLI、后端 API、前端 UI** 三条链路上都完整可用。当前既有系统（works/metadata/classification/dedup/relations/files）三链路已齐全，作为模板；本规划聚焦把 **parser（P3.5）** 与 **collector（P6）** 两个已合并但仅 CLI 可用的子系统补齐 API + UI 两条链，并端到端打通全流程。

## 2. 架构原则（硬约束，所有 agent 必须遵守）

**单核三适配器**：业务逻辑只在 core 包里写一次；CLI 脚本、API 路由、Vue 页面都是薄适配器，绝不重复实现。

```text
┌──────────────────────────────────────────────────────┐
│ Core（单一真相源，已存在）                               │
│  collector/  gate · candidate_store · ingest_bridge · │
│              topics · adapters · discovery_*          │
│  parser/core mineru cloud_client(vlm) · pymupdf ·     │
│              selfdeploy · artifact_generator          │
│  existing    ingest · dedup · metadata · classify     │
└──────────────────────────────────────────────────────┘
        ▲                 ▲                  ▲
        │                 │                  │
   CLI scripts       API routers         Vue SPA
  (operator/agent)  (程序化 + 喂 UI)       (人)
```

- API 是 UI 与 core 之间的契约；CLI 和 API 都只包装 core。
- 禁止在 API 路由或 CLI 里复制业务逻辑（避免"两个真相源"）。
- UI 优先服务"人必须决策"的环节（A2 审核、主题提案拍板）；重批量（全库采集、批量回填）留 CLI/loop。
- 向后兼容：既有 6 个路由 + 7 个页面不动语义，只新增。

## 3. 能力 × 链路矩阵（现状 → 目标）

| 能力 | CLI | API | UI | 说明 |
|---|---|---|---|---|
| collector-A 主题生命周期 | ✅ `literature_intake topic` | ❌ | ❌ | `collection_topics` 表未迁移到 live DB |
| collector-B 发现(collect) | ✅ `literature_intake collect` | ❌ | ❌ | 重批量，主战场 CLI/loop |
| collector-C 闸门(resolve) | ✅ `literature_intake resolve` | ❌ | ❌ | 可被 promote 链式触发 |
| collector-D **A2 审核+晋升** | ✅ `literature_intake list/promote` | ❌ | ❌ | 人必须介入，UI 优先级最高 |
| parser-E 解析 pending | ✅ `parser/main.py` | ❌ | ❌ | backend 路由 D13（vlm/pymupdf/selfdeploy） |
| parser-F 解析状态/产物 | (parse_ledger) | ❌ | ❌ | |
| (既有) works/meta/分类/去重/关系/文件 | ✅ | ✅ | ✅ | 三链齐全，作模板 |

**差距**：parser 与 collector 各缺 API + UI；collector 另有部署缺口（collection_topics 迁移）。

## 4. 分阶段规划

### Phase A — collector 审核闭环（API + UI）〔最高价值〕

把 collector 唯一必须人介入的环节（A2 审核 + 晋升）搬进 UI。

- **部署前置**：把 retrieval 层的 `collection_topics`（及相关）迁移跑到真实库（代码已就绪、仅在测试夹具中）。
- **后端**：新增 `api/routes/intake.py`，挂进 `api/main.py`。端点全部委托 `collector/` core：
  - `GET  /api/intake/candidates`（按 resolution / review_status / topic 过滤、分页）
  - `POST /api/intake/resolve`（触发闸门，可批量）
  - `POST /api/intake/promote`（A2 批量晋升 → 复用 `ingest_bridge`）
  - `GET  /api/intake/stats`（new/exact_hit/title_candidate/needs_better_copy/sha256_duplicate 计数）
  - `GET/POST /api/intake/topics`（主题列表 / 成熟度流转）
- **前端**：新增 `IntakeReview.vue`（仿 `MetadataReview.vue`）——候选列表 + 四态判别展示 + 逐条 approve/reject + 批量 promote + needs_better_copy 高亮。侧边栏加入口。
- **验收**：人能在浏览器走完「候选 → 审核 → 晋升为 work」，晋升后 work 进入既有 metadata/分类审核流。

### Phase B — 解析触发与状态（API + UI）〔打通晋升→全文〕

- **后端**：新增 `api/routes/parse.py`，委托 `parser/core`：
  - `POST /api/parse/trigger`（解析指定/全部 pending，尊重 D13 backend 路由，保守并发）
  - `GET  /api/parse/status`（pending/succeeded/failed 计数 + 个别 work 状态）
  - 从 `.env` 读 `MinerU_API_KEY`；不可用时按 selfdeploy 降级策略。
- **前端**：WorkDetail 加解析状态徽标 + 触发按钮；可选轻量 Parse 页看全库 pending。
- **验收**：promote 后能在 UI 触发解析并看到 `content.md` 落地，`literature_parse_runs.content_md_path` 更新。

### Phase C — collector 主题与发现进 UI〔补齐 A/B/C 的 UI 链〕

- Topics 页：主题成熟度（seedling/proposed/mapped）管理 + 提案闸门 4 判据展示。
- 在 UI 触发 collect/resolve（或明确"按主题发起一次采集"为 UI 入口，持续订阅/loop 留 CLI）。
- **验收**：collector 四子能力 A/B/C/D 三链路齐全。

### Phase D — 端到端打通与三链验收

- 全流程 smoke：`collect → resolve → [IntakeReview 审核] → promote → [parse 触发] → content.md → metadata/分类/去重(既有 UI) → 分析`。
- **硬指标**：每个能力从 CLI、API、UI 三入口都能触发并观察到结果。
- 新增端点全部配测试；`parser/tests` 的 `fitz`(PyMuPDF) 收集错误在根 pytest 配置中隔离（ignore 或 testpaths 限定 `tests/`），不污染根测试。

## 5. 跨切关注点（贯穿所有 phase）

1. **单核三适配器**——API/CLI 不写业务逻辑。
2. **每端点配测试**（参照 `tests/test_api.py`：temp DB 副本 + patch 各路由 `get_conn`；不污染真实库）。
3. **配置/部署**：`.env` MinerU_API_KEY（已就位）、parser backend 选择、`collection_topics` 迁移、API 进程能 import `parser`/`collector` 子包。
4. **测试隔离**：根 pytest 不要收集 `parser/tests`（PyMuPDF 未必在根 venv）；用 `pyproject.toml` 的 `[tool.pytest.ini_options]` 限定 `testpaths = ["tests"]` 或 ignore parser。
5. **边界守恒**：collector 绝不直接写 `works`（经 `ingest_bridge`）；解析输出契约（`works/{id}/parsed/mineru/{sfid}/content.md` + `content_md_path`）不变。

## 6. 端态验收（Definition of Done）

- 能力矩阵中 ✅/❌ 全部转为 ✅（每能力三链路可达）。
- `uv run python -m pytest tests/` 全绿（含新增 intake/parse 端点测试）。
- 三链路 smoke 脚本/用例：同一动作从 CLI、`curl /api`、UI 各走一遍，结果一致。
- 既有功能无回归（既有 153 passed 基线不退化）。

## 7. 分工

- **总体规划（本文档）**：架构、矩阵、分阶段、验收标准。
- **后续 agent**：按 Phase 拆任务计划（`writing-plans` 技能 → `docs/superpowers/plans/`）→ 实施 → 自审 → 提 PR/合并。每个 Phase 独立可交付。
