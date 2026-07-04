# 项目交接指南

> **用途**：帮助新接手者快速了解项目全貌，以便和用户一起决定下一步做什么。
> **不指定具体任务**——本文档只负责"让你看得懂"，决策权在用户。
> **更新时间**：2026-07-05

---

## 一、30 秒速览：这是什么项目

一个**本地文献管理系统**，给博士研究用的。核心功能：

1. **把 PDF 收进来**（手动上传 或 从网上搜索发现）
2. **自动解析**（提取文本、结构）
3. **AI 辅助抽取**（元数据、分类标签）
4. **人工审核把关**（每一步都有审核闸门，不能跳过）
5. **去重 / 隔离 / 关系管理**

技术栈：**Python FastAPI 后端 + Vue 3 Naive UI 前端 + SQLite 数据库**

---

## 二、先看这些文档（按顺序）

### 第一步：了解项目骨架

| 文档 | 看什么 |
|------|--------|
| `README.md` | 项目首页、目录结构、核心概念和文档导航 |
| `docs/README.md` | 文档总目录：按角色、职责和写入位置分流 |
| `docs/manuals/user-manual.md` | 浏览器用户怎么操作页面和审核流程 |
| `docs/manuals/cli-manual.md` | CLI/自动化命令、测试、健康检查和批处理入口 |
| `docs/manuals/agent-manual.md` | agent 协作边界、任务派发、两轮审核和交接格式 |
| `FUTURE_WORK_PLAN.md` | 当前路线图 + 维护原则 + 所有未完成任务列表 |
| `docs/PROJECT_HISTORY.md` | 已完成工作的完整归档（V1 → V1.3 → Pipeline → IngestHub） |

### 第二步：了解技术架构

| 文档/目录 | 内容 |
|-----------|------|
| `api/routes/*.py` | 后端 API 全部路由（约 10 个文件） |
| `web/src/router.js` | 前端全部页面路由与导航结构 |
| `web/src/api.js` | 前端所有后端调用封装 |
| `web/src/views/*.vue` | 全部 18 个页面组件（含新增 TemplateManage.vue，见下方清单） |
| `web/src/components/*.vue` | 通用 UI 组件（9 个） |
| `web/src/composables/use*.js` | 可复用逻辑封装（7 个） |

### 第三步：了解关键设计决策

| 决策点 | 结论 | 在哪看的 |
|--------|------|----------|
| 为什么用 SQLite 不用 PostgreSQL | 本地单用户工具，零运维 | `README.md` 核心概念 |
| 解析状态以什么为准 | `literature_parse_runs` 表（不是文件系统） | `README.md` 核心概念 |
| AI 抽取结果必须人工审核吗 | 是的，双闸门设计（发现→intake→ingest） | `docs/discovery-agent-protocol.md` |
| 前端为什么不引 TypeScript/Pinia/Tailwind | 用户明确要求的红线 | `.workbuddy/memory/MEMORY.md` |
| 后端 per_page 上限 | 最大 100 | 实际踩坑记录 |

---

## 三、前端页面全景

```
侧边栏分组：

📊 总览
├── Dashboard.vue          → 导航首页（待办概览）

📚 文献库
├── Works.vue              → 文献列表
├── WorkDetail.vue         → 单篇文献详情（工作台）

── 流程 ──
├── PipelineView.vue       → ⭐ 4阶段流水线（收件箱→解析→元数据→分类）
│                          │   + 发现检索审核 + 采集审核 审计节点
├── TopicsReview.vue       → 主题闸门（管理研究主题，含悬浮提示）
├── IngestHub.vue          → 文献入库（发现检索 + 收件箱 Tab 合并）
├── IntakeReview.vue       → 采集审核（discovery hit → intake candidate）
│                          │   含来源追溯卡片 + PDF 操作栏
├── ClassificationReview.vue → 分类审核
└── MetadataReview.vue     → 元数据审核

── 库内 ──
├── Duplicates.vue          → 去重管理
└── Relations.vue           → 关系图

── 系统 ──
└── TemplateManage.vue      → 🆕 模板管理（元数据/分类/Discovery 三大模板资产）
```

---

## 四、数据流主线（两条入口，汇合后走同一流水线）

```
入口 A: 发现检索              入口 B: 本地上传
(DiscoveryReview)             (IngestHub → InboxReview)
    │                              │
    ▼                              ▼
 discovery_hits              _inbox/ PDF 文件
    │                              │
    ▼ (人工接受)                   ▼ (确认摄入)
 intake_candidates          execute_plan()
    │                              │
    └──────────┬───────────────────┘
               ▼
         ingest_bridge.promote()
               │
        ┌──────▼──────┐
        │   works 表   │ ← 新文献入库
        └──────┬──────┘
               │
        parse_run(pending)
               │
     ┌─────▼─────┐
     │  MinerU    │ ← 自动解析 PDF
     │  解析器     │
     └─────┬─────┘
           │
     ┌─────▼─────────────┐
     │  元数据抽取(LLM)    │ ← 人工审核后才能用
     │  分类抽取(LLM)      │
     └────────────────────┘
```

**关键理解**：两条入口在 `ingest_bridge.promote()` 处汇合，之后走的流水线完全一样。

---

## 五、项目约定（必须遵守的红线）

从 `.workbuddy/memory/MEMORY.md` 提炼：

| 约束 | 说明 |
|------|------|
| 不引入新依赖 | npm/pip 都不算，除非用户明确要求 |
|不改后端数据结构 | 数据库 schema 不能动 |
| 不改数据库 schema | 同上 |
| 纯 JS | 不引入 TypeScript |
| 不引入 Pinia | 用 Composable 替代状态管理 |
| 不引入 Tailwind | 用 CSS 变量体系 |
| 端口 | 前端 localhost:19528 / 后端 localhost:19527 |
| 沟通语言 | 中文优先，避免堆砌英文术语 |
| 解释方式 | 用大白话类比，不要抽象架构描述 |

---

## 六、当前状态总结

### 已完成 ✅

| 大阶段 | 内容 | 详情位置 |
|--------|------|----------|
| V1 | 基础设施（摄入/解析/去重/元数据/分类/审核链路） | `PROJECT_HISTORY.md` §V1 |
| V1.1 | 前端端到端主流程 + 受约束发现检索 | `PROJECT_HISTORY.md` §V1.1 |
| V1.2 | Composite 多信号组合输入（discovery 增强） | `PROJECT_HISTORY.md` |
| V1.3 P0-P2 | 知识闭环（状态机修复/主题关联/侧边栏重排） | `PROJECT_HISTORY.md` §V1.3 |
| 前端重构 Phase 0-5 | CSS 变量体系/组件提取/布局统一/a11y | `PROJECT_HISTORY.md` §前端重构 |
| Pipeline 页面 | 4阶段流水线/双模式/预览隔离/上传 + 发现检索&采集审核节点 | `PROJECT_HISTORY.md` §Pipeline |
| IngestHub | 发现检索+收件箱合并为统一入库页 | `PROJECT_HISTORY.md` §IngestHub |
| **前端体验大优化** (2026-07-02) | 导航栏调整/发现检索Tab改造/采集审核深度改造/PDF链路修复/来源追溯/模板管理页 | `PROJECT_HISTORY.md` §2026-07-02 |
| **模板管理页面** (2026-07-02) | 独立 `/templates` 页面，三大模板资产（元数据可编辑/分类预留/Discovery预留） | `PROJECT_HISTORY.md` §六 |
| **字段级重抽前端化** (2026-07-04) | MetadataReview 字段行双模式入口：重抽预览写入 + 复制 prompt 降级 | `PROJECT_HISTORY.md` §2026-07-04 |
| **元数据模板 runtime 接入** (2026-07-04/05) | `templates/templates.json` + `api/metadata_template.py` 接入抽取 CLI/API/rerun，MetadataReview 动态字段审核 | `PROJECT_HISTORY.md` §2026-07-04 |
| **元数据模板使用文档同步** (2026-07-05) | README 和 scripts README 明确 UI、CLI/API、agent 批量处理边界 | `README.md` §9、`scripts/README.md` |
| **使用手册角色拆分** (2026-07-05) | 新增用户手册、CLI/自动化手册、Agent 协作手册，README 改为总入口 | `docs/README.md` |

### 待做项（详见 `FUTURE_WORK_PLAN.md`）

**三大方向**：
- A. 元数据抽取模板固化
  - **✅ 已完成**：独立模板管理页面（`/templates`），元数据字段可在线编辑，保存到 `templates/templates.json`
  - **✅ 已完成**：UX-004 字段级重抽前端化（智能预览写入 + 复制 prompt 降级）
  - **✅ 已完成**：QA-001 元数据模板接入真实抽取/rerun 链路，审核页可动态展示/编辑/重抽自定义字段
  - **✅ 已完成**：使用文档已明确 `/templates`、`/metadata`、CLI/API 和 agent 批量处理方式；批量 agent 不需要从界面复制 prompt，应直接读模板并调用命令
  - **当前下一步建议**：继续元数据模板资产治理，把 `needs_fix` / `rejected` / supersede 案例沉淀为模板改进建议；QA-004 分类词汇模板同步/发布流程暂缓
  - 详见 `USER_ISSUES.md` 已解决 UX-004/QA-001、待处理 QA-004 和 `FUTURE_WORK_PLAN.md` §A
- B. 分类规范与审核模板
  - 模板管理页面 Tab2 已有只读展示，后端编辑 API 已预留（🔒 前端未开放按钮）
- C. 采集与检索模板沉淀

**高优先级任务队列**（#1 ~ #11 + UX）：

| 编号 | 任务 | 优先级 | 状态 |
|------|------|--------|------|
| UX-001 | 批量触发流程的管理页面（Dashboard 增强） | 🔴 高 | 📋 待处理 |
| UX-002 | PyMuPDF 解析丢失图片/图表 | 🟡 中 | 📋 待处理 |
| UX-004 | 字段级重抽前端入口（双模式） | 🟡 中 | ✅ 已完成 |
| QA-001 | 元数据模板接入真实抽取链路 | 🟡 中 | ✅ 已完成 |
| QA-004 | 分类词汇模板同步/发布流程 | 🟡 中 | 📋 待处理 |
| #1 | Discovery 本地模型自动执行器 | 中高 | 📋 待处理 |
| #2 | ~~元数据模板 V1.1~~ | — | ✅ 已完成 |
| #3 | 分类规范与审核模板 V1.1 | 高 | 📋 待处理 |
| #4 | 分类标签事务式保存 | 中 | 📋 待处理 |
| #5 | Parse status 多源语义 | 低 | 📋 待处理 |
| #6 | Dashboard 队列压力面板 | 中 | 📋 待处理 |
| #7 | 审核日志语义统一 | 低 | 📋 待处理 |
| #8 | needs_better_copy 替换源文件链路 | 低 | 📋 待处理 |
| #9 | 文档治理自动化 | 低 | 📋 待处理 |
| #10 | 引用导出与综述矩阵 | 中 | 📋 待处理 |
| #11 | proposed_new 标签转正路径 | 中 | 📋 待处理 |

**暂不做**：移动端适配、大规模自动采集、无约束自动入库。

---

## 七、接手后的建议步骤

1. **跑一遍健康检查**：`python scripts/healthcheck_library.py --json` — 确认环境正常
2. **启动前后端**：后端 `uvicorn api.main:app --port 19527`，前端 `npm run dev`（端口 19528）
3. **浏览各页面**：按第四节的页面清单逐个打开，了解每个页面干什么
4. **读 FUTURE_WORK_PLAN.md 全文**：了解有哪些方向可以选择
5. **和用户讨论**：基于了解到的信息，一起决定下一步优先做哪个方向

如果下一步继续做元数据模板资产治理，先读 `README.md` §9 和 `scripts/README.md` 的“元数据模板与批量重抽”。前端单条处理走 `/templates` + `/metadata`；agent 批量处理直接读 `templates/templates.json` 并调用 `scripts\literature_metadata_extract.py` / `scripts\literature_metadata_rerun.py` 或对应 HTTP API。界面的“复制 prompt”只作为单条降级方案，不是批量 agent 的主入口。

---

## 八、常用命令速查

```bash
# 后端启动
uvicorn api.main:app --port 19527 --reload

# 前端启动
cd web && npm run dev        # 开发模式 :19528
cd web && npm run build      # 构建检查

# 测试
pytest tests/ -q             # 后端测试
python scripts/healthcheck_library.py --json  # 健康检查

# 数据库直查（调试用）
sqlite3 literature.sqlite "SELECT COUNT(*) FROM works;"
sqlite3 literature.sqlite ".tables"
```

---

## 九、关键联系人/上下文

- **用户身份**：博士研究生，研究方向涉及目标错误泛化、大语言模型安全性评估
- **沟通偏好**：中文大白话，要类比不要抽象术语
- **工作方式**：用户作为中间人，本地模型实施 → 审核
- **项目路径**：`D:\02_academic\doctoral\literature_library`

---

## 十、2026-07-02 工作交接详情

### 本次新增/修改的关键文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `api/routes/templates.py` | **新建** | 模板管理后端 API（6 端点 + 备份机制） |
| `web/src/api_templates.js` | **新建** | 前端模板 API 封装（7 函数） |
| `web/src/views/TemplateManage.vue` | **新建** | 模板管理主页面（~560 行，三大 Tab） |
| `web/src/views/IntakeReview.vue` | 大改 | 来源追溯卡片 + PDF 操作栏 + 布局滚动修复 + 根因修复 |
| `web/src/views/DiscoveryReview.vue` | 中改 | Tab 切换改造 + 主题名称显示 |
| `web/src/views/PipelineView.vue` | 小改 | 新增发现检索审核 + 采集审核两个节点卡片 |
| `web/src/views/TopicsReview.vue` | 小改 | 全字段 title 悬浮提示 |
| `web/src/views/MetadataReview.vue` | 小改 | 移除旧弹窗代码（~170 行清理） |
| `web/src/components/AppLayout.vue` | 小改 | 导航栏调序 + 新增「系统」分组 |
| `web/src/router.js` | 小改 | 新增 /templates 路由 |
| `web/src/api.js` | 微改 | export request 函数 |
| `collector/discovery.py` | 微改 | accept 时提取 arxiv_id + 推断 source_type |
| `collector/gate.py` | 微改 | _pdf_url_for() 扩展反向提取 |
| `collector/ingest_bridge.py` | 微改 | promote() 回填 ingested_work_id；2026-07-03 复核后保留 review_status=approved，不再混用生命周期 |
| `api/routes/intake.py` | 小改 | 新增 upload-pdf 端点 |
| `api/main.py` | 微改 | 注册 templates router |

### 数据库变更（无 schema 变更）

| 操作 | 表 | 说明 |
|------|-----|------|
| UPDATE | intake_candidates | IC-8663473e: approved → pending（误批准回退） |
| UPDATE | intake_candidates | IC-1f9eed3c: status → ingested + ingested_work_id 回填；review_status 语义保留为人工审核结论 |

### 已知遗留问题（未解决）

1. **UX-002**：PyMuPDF 解析丢失图片 —— 需要修改路由策略或增加 VLM 回退
2. **UX-001**：批量触发流程管理页面 —— Dashboard 增强
3. **#11**：proposed_new 标签转正路径清晰化
4. **QA-004**：分类词汇模板同步/发布流程 —— 当前 Tab2 只读/预留
5. **QA-002**：候选 PDF 手动上传缺少生命周期保护
6. **QA-003**：收件箱上传缺少大小限制和同名保护
