# 系统定位与使用闭环校准

> 状态：已归档（2026-07-17）：Day 2-3 PipelineView 修复、Day 5 版本标注、Day 10 HANDOVER 修正均已执行；2 周路线图窗口已结束
> 审计日期：2026-07-05
> 方法：4 个独立子 agent（文档审计、流程审计、数据模型、代码/风险）+ 交叉复核
> 说明：本文件是关键节点审查，不是长期维护文档。内容基于 2026-07-05 的代码和文档快照，后续会过期。

---

## 产物一：系统定位一页纸

### 一句话定位

博士研究本地文献管理系统，服务于目标错误泛化、LLM 安全性评估等研究方向。核心价值是"把 PDF 收进来、自动解析、AI 辅助抽取、人工审核把关、结构化管理"。

### 核心约束（不可违反）

| 约束 | 含义 | 代码位置 |
|------|------|----------|
| 人工审核门禁 | AI 抽取结果不能自动写入 `works` 稳定层，必须经过 approve | `api/routes/metadata.py:559-610` |
| 物理+逻辑分离 | 文件系统存 PDF，SQLite 管关系，不靠文件夹表达分类 | `literature.sqlite` 全局 |
| 不直接删除 | 所有删除操作归档或隔离，不删源文件 | `api/quarantine.py:33-101` |
| 本地优先 | 不依赖外部服务（Ollama 可选，MinerU cloud 可选） | `pyproject.toml` |
| Discovery 只读 | 发现检索 agent 只能回填 hits，不能写 works/intake/vocab | `collector/discovery.py:1-9` |

### 技术边界

| 层 | 技术 | 端口 | 状态 |
|---|---|---|---|
| 数据库 | SQLite (WAL) | — | 稳定 |
| 后端 | FastAPI | 19527 | 11 路由组 |
| 前端 | Vue 3 + Naive UI | 19528 | 14 页面 |
| 解析 | PyMuPDF 本地 / MinerU cloud VLM | — | 二元路由 |
| 抽取 | opencode→MiMo-v2.5-pro | — | 质量裁判 |

### 版本状态

- V1：基础设施 ✅
- V1.1：前端端到端主流程 + 受约束发现检索 ✅
- V1.2：Composite 多信号发现检索 ✅
- V1.3：知识闭环 P0-P2 ✅
- 当前：V1.3 完成，进入体验优化和模板治理阶段

### 项目不是什么

- 不是通用文献管理工具（服务特定博士研究领域）
- 不是自动化采集系统（人工闸门优先）
- 不是云端服务（本地桌面工具）
- 不是无审核的 AI 自动化（每一步都有人工门禁）

### 最大文档风险

**TECHNICAL_OVERVIEW.md 严重过期**（标注 V1.1，实际 V1.3）。缺少 3 个页面（Pipeline / IngestHub / TemplateManage）、1 个路由组（templates）、10+ API 端点。任何基于该文档的架构判断都需要交叉验证代码。

---

## 产物二：日常使用流程图

### 路径 A：本地 PDF → 入库（最常用）

```text
_inbox/ 放入 PDF
  → /ingest 或 /inbox 确认摄入
  → 摄入完成：works + source_files + parse_runs(pending)
  ⚠️ 不自动触发解析
  → /pipeline 或 /works/:id 或 CLI 触发解析
  → parse_runs: pending → succeeded
  → /pipeline 或 /works/:id 触发元数据抽取
  → 创建 metadata_extractions(pending)
  → /metadata 人工审核 (approve/needs_fix/rejected)
  → approve → 自动回填 works + supersede 兄弟
  ⚠️ 隐式前置条件：元数据必须 approved
  → /pipeline 触发分类抽取
  → 创建 classification_extractions(pending)
  → /classification 人工审核 → 回填 works + 写标签
```

**关键断点**：
- 摄入后不自动解析（需手动触发）
- 元数据抽取后无"下一步"引导
- 分类抽取的前置条件（元数据 approved）未在 UI 告知

**每步入口数**：摄入(3) → 解析(3) → 元数据抽取(4) → 元数据审核(1) → 分类抽取(3) → 分类审核(1)

### 路径 B：发现检索 → 入库

```text
/topics 创建主题
  → /discovery 创建 run + 生成 plan
  → 外部 agent 执行检索 + 回填 hits
  → /discovery 审核 hits (accept/reject)
  → accept → 创建 intake_candidates(pending)
  ⚠️ 无自动跳转到 /intake
  → /intake 审核候选 (approve → promote)
  ⚠️ 硬约束：必须先下载 PDF 才能晋升
  ⚠️ 重复候选（resolution≠new）不可晋升
  → promote → 创建 works + source_files + parse_runs(pending)
  → 路径 A 的解析步骤
```

### 路径 C：元数据字段级重抽

```text
/metadata 选择记录
  → 字段行"重抽"按钮
  → 预览 diff → 确认写入
  → 创建新 extraction(pending) + 旧记录 superseded
  ⚠️ 新记录仍需审核批准
```

### 路径 D：分类审核（同路径 A 末段）

### 路径 E：去重与关系管理

```text
/duplicates 审核重复组 (same_work/not_duplicate/quarantine)
/works/:id 添加关联
```

### 入口重复地图

| 操作 | 入口 1 | 入口 2 | 入口 3 | 一致性 |
|------|--------|--------|--------|--------|
| 收件箱摄入 | `/ingest` (IngestHub) | `/inbox` (InboxReview) | `/pipeline` | IngestHub 嵌入 InboxReview |
| 发现检索 | `/discovery` | `/ingest` (Tab) | `/topics` (快捷) | 同一组件 |
| 触发解析 | `/pipeline` | `/works/:id` | CLI | API 一致 |
| 触发元数据抽取 | `/pipeline` | `/works/:id` | CLI + API | Pipeline limit=5 |
| 隔离 | `/pipeline` `/metadata` `/classification` `/works/:id` | — | — | QUARANTINE_REASONS 3 处硬编码+1 composable |

### PipelineView ambLevel 阈值 bug（交叉复核确认）

`PipelineView.vue:614-618` 的 `ambLevel` 使用 0.7/0.4 阈值，而后端返回 0-100 分制。结果：所有非零分数都 >= 0.7，模糊度 badge **全部显示为"高"**。`ClassificationReview.vue:517-521` 使用正确的 50/20 阈值。

---

## 产物三：关键字段/状态字典

### 核心表总览（16 张表）

| 表名 | 职责 | 主键 | 主要写入者 |
|------|------|------|-----------|
| `works` | 文献主表 | `id` TEXT | ingest, metadata, classification |
| `source_files` | 源文件追踪 | `id` TEXT | ingest, quarantine |
| `literature_parse_runs` | 解析任务 | `id` TEXT | ingest(创建), batch_parse(更新) |
| `parse_artifacts` | 解析产物 | `id` TEXT | batch_parse |
| `metadata_extractions` | 元数据抽取结果 | `id` ME-{hex} | metadata_extract, metadata API |
| `classification_extractions` | 分类抽取结果 | `id` CE-{hex} | classification_extract, classification API |
| `work_classification_tags` | 多值分类标签 | `id` CT-{hex} | classification review |
| `duplicate_groups` | 重复组 | `id` TEXT | dedup script |
| `duplicate_candidates` | 重复候选 | `id` TEXT | dedup script |
| `work_relations` | 文献关系 | (a,b,type) 复合 | dedup, relations API |
| `work_codes` | 标记代码 | (work_id,code) 复合 | quarantine |
| `intake_candidates` | 采集候选 | `id` IC-{hex} | collector, discovery |
| `analysis_runs` | 分析运行 | `id` AR-{hex} | literature_analyze |
| `collection_topics` | 采集主题 | `id` CT-{hex} | collector/topics |
| `discovery_runs` | 发现检索 run | `id` DR-{hex} | collector/discovery |
| `discovery_hits` | 发现检索命中 | `id` DH-{hex} | collector/discovery |

### 关键状态流转

#### works.parse_status（派生字段，不可直接写入）

```text
pending → succeeded (所有 active source 都 succeeded)
pending → failed    (所有 active source 都 failed)
pending → partial   (混合状态；succeeded→partial 是合法回退)
```

约束：必须由 `sync_work_parse_status()` 从 `literature_parse_runs` + `source_files` 计算。4 个调用点：works.py archive/restore, parse.py trigger, batch_parse.py。**风险：healthcheck 不验证此一致性。**

#### metadata_extractions.review_status

```text
pending → approved  → 自动 _apply_single() 回填 works + supersede 兄弟
pending → needs_fix → 再次审核 → approved/rejected
pending → rejected  → 不回填
```

约束：approve 一条自动 supersede 同 work 的其他 pending/needs_fix/approved-not-applied 记录。

#### metadata_extractions.applied

```text
0 → 1 (仅当 review_status='approved' 且 work 未隔离 且 applied=0)
```

语义：fill-empty，不覆盖 works 中已有值。

#### classification_extractions.review_status

```text
pending → approved  → 回填 works 标量字段 + 写 work_classification_tags
pending → needs_fix → 再次审核
pending → rejected
```

约束：标量字段 fill-empty；多值标签需通过 vocab 校验。

#### intake_candidates.resolution

```text
pending → light_gate() → new              (无匹配)
                        → exact_hit        (arxiv_id/doi 强匹配)
                        → title_candidate  (title Jaccard >= 0.9)
                        → needs_better_copy(匹配到隔离 work)
                        → fetch_failed     (下载失败)

new → heavy_gate(SHA256) → new (无 SHA256 匹配)
                          → sha256_duplicate
```

约束：只有 `resolution='new'` + `review_status='approved'` 的候选才能 promote。

#### intake_candidates.status

```text
pending → resolved → ingested (promote 成功)
                   → skipped  (重复候选)
```

#### discovery_runs.status

```text
planned → running (首个 hit 插入时自动翻转) → succeeded / failed
```

#### collection_topics.map_status

```text
seedling → proposed (需 proposed_note)
seedling → mapped   (需 mapped_tags，vocab 校验)
proposed → mapped
```

禁止：mapped → seedling/proposed 不可回退。

### 不可破坏约束

| # | 约束 | 涉及表 | 代码位置 |
|---|------|--------|----------|
| C1 | `works.parse_status` 是派生值，不可直接写入 | works, parse_runs, source_files | `migrate_sync_parse_status.py:49-95` |
| C2 | 隔离需原子三更新：works.read_status + source_files.status + 文件移动 | works, source_files, work_codes | `quarantine.py:33-101` |
| C3 | `status=ingested` 必须有 `ingested_work_id` | intake_candidates | `healthcheck_library.py:289-312` |
| C4 | 只有 approved 候选才能 promote | intake_candidates | `intake.py:189-194` |
| C5 | 只有 `resolution='new'` 才能 promote | intake_candidates | `intake.py:209-228` |
| C6 | Discovery agent 只能写 discovery_hits | discovery_hits | `discovery.py:1-9` |
| C7 | 元数据回填是 fill-empty，不覆盖已有值 | metadata_extractions → works | `metadata.py:580-582` |
| C8 | 分类回填标量字段也是 fill-empty | classification_extractions → works | `classification.py:592-618` |
| C9 | Approve 自动 supersede 兄弟记录 | metadata/classification extractions | `metadata.py:279-287` |
| C10 | Healthcheck 验证孤儿引用（10 对父子关系） | 多表 | `healthcheck_library.py:74-108` |
| C11 | 不手动移动 works 下的文件 | source_files | TECHNICAL_OVERVIEW:284 |
| C12 | 主题 map_status 只能前进 | collection_topics | `topics.py:71-72` |

### Schema 与文档差异

| 差异 | 严重程度 |
|------|----------|
| conftest.py 缺少 `intake_candidates.UNIQUE(source_type, url_canonical)` | 高 |
| conftest.py 缺少 `discovery_runs` 和 `discovery_hits` 表 | 中 |
| `works.metadata_status` 摄入脚本仍在写入但文档未说明 | 低 |
| `works.secondary_doc_type` 存在但 TECHNICAL_OVERVIEW 未记录 | 低 |

---

## 产物四：未来 2 周最小可执行路线图

### Week 1（7/7 - 7/11）

#### Day 1-2：提交 promote 去重改动 + 补充测试

- 文件：`api/routes/intake.py` + `tests/test_intake_api.py` + `web/src/views/IntakeReview.vue` + `templates/templates.json`
- 补充 3 个测试：`test_promote_rejects_title_candidate`、`test_promote_rejects_exact_hit`、`test_promote_allows_new_after_heavy_gate_clear`
- 验收：`pytest tests -q -p no:cacheprovider --basetemp .codex_tmp\pytest-all` 通过
- 复杂度：简单（代码已写好，只补测试）

#### Day 2-3：修复 PipelineView ambLevel 阈值 bug

- 文件：`web/src/views/PipelineView.vue:614-618`
- 改动：`0.7→50`、`0.4→20`
- 同时检查 `ambiguityLevels` 筛选器（第 468-473 行）是否也需要同步
- 验收：`npm run build` 通过；手动验证 `/pipeline` 分类阶段模糊度 badge 正确显示
- 复杂度：简单（2 行改动）

#### Day 3-4：QA-002 上传 PDF 生命周期保护

- 文件：`api/routes/ingest.py`（或 `api/routes/intake.py` 中的 upload-pdf 端点）
- 改动：拒绝已入库/已拒绝/已有 PDF 的候选上传；采用临时文件+原子替换
- 验收：新增测试覆盖 4 个边界场景；pytest 通过
- 复杂度：简单（< 1 天）

#### Day 5：提交 templates.json + 更新 TECHNICAL_OVERVIEW 版本标注

- 单独提交 `templates/templates.json`（新增 open_source_status/open_source_components 字段）
- 更新 `TECHNICAL_OVERVIEW.md` 第 4 行版本标注从 V1.1 改为 V1.3
- 验收：`git diff --check` 通过
- 复杂度：简单

### Week 2（7/14 - 7/18）

#### Day 6-7：UX-002 方案评估 + 最小原型

- 文件：`parser/core/mineru/router.py`、`parser/core/mineru/pymupdf_client.py`
- 推荐方案 C：PyMuPDF 抽取时同时提取图片（`page.get_images()` + `pix.save()`）
- 产出：方案评估文档 + 1 个 work 的原型验证
- 验收：解析一篇含图片的 PDF，content.md 中出现图片引用
- 复杂度：中等（2-3 天）

#### Day 8-9：QUARANTINE_REASONS 统一 + WorkDetail label 修正

- `web/src/views/WorkDetail.vue:418-425`：`needs_rerun` label 补齐"需替换后重新抽取"
- 评估是否将 3 处硬编码统一迁移到 `useQuarantine.js` composable
- 验收：4 处 label 完全一致；`npm run build` 通过
- 复杂度：简单

#### Day 10：HANDOVER_GUIDE 状态一致性修正

- `docs/HANDOVER_GUIDE.md` 第 286 行：将 UX-001 从"已知遗留问题"中移除
- `docs/HANDOVER_GUIDE.md` 第 175 行：明确 QA-004 是"暂缓"而非"第一优先候选"
- 验收：`python scripts\check_docs.py` 通过
- 复杂度：简单（文档修改）

### 明确推迟的任务

| 任务 | 推迟理由 |
|------|----------|
| Discovery 本地执行器 | 中高优先但依赖 discovery run 稳定性验证 |
| 分类标签事务式保存 | 中优先，当前 delete-then-add 有风险但不阻断使用 |
| UX-005 模板新增字段体验 | 中优先，当前可用但粗糙 |
| QA-004 分类词汇同步/发布 | 有意暂缓，避免与元数据模板治理混在一起 |
| Dashboard 队列压力面板 | 低优先，锦上添花 |
| 引用导出与综述矩阵 | 研究工作流需求，不阻断 |

### 验收命令清单

```powershell
# 后端测试
python -m pytest tests -q -p no:cacheprovider --basetemp .codex_tmp\pytest-all

# 健康检查
python scripts\healthcheck_library.py --json

# 文档检查
python scripts\check_docs.py

# 前端构建
cd web; npm run build

# Git 检查
git diff --check
```

---

## 交叉复核修正记录

以下为第二轮复核中发现并修正的错误：

| # | 原始报告错误 | 修正 |
|---|-------------|------|
| 1 | 文档审计声称 `.workbuddy/memory/MEMORY.md` 不存在 | **实际存在**且已被 git 跟踪，HANDOVER_GUIDE 引用有效 |
| 2 | 流程/风险报告声称 PipelineView ambLevel bug 导致"全部显示为低" | 实际应为**全部显示为高**（0-100 分制分数都 >= 0.7 阈值） |
| 3 | 流程审计声称"5 个页面各自硬编码 QUARANTINE_REASONS" | 实际是 3 个 Vue 文件硬编码 + 1 个 composable 共享定义（PipelineView 从 composable 导入） |
| 4 | 文档审计声称 Ollama 端口 11435"可能是笔误" | 11435 是项目历史中实际配置的端口，当前已弃用，不是笔误 |
| 5 | 数据模型报告称 `works.metadata_status` 是"遗留字段" | 摄入脚本 `literature_ingest.py` 仍在写入（值为 `'auto'`），Dashboard 仍在显示，不完全"死" |
