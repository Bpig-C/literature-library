# 用户问题记录

> **用途**：记录日常使用中发现的不合理之处、体验问题、功能缺陷。
>
> **使用方式**：发现问题时直接在下方添加，定期整理后转移到 `FUTURE_WORK_PLAN.md` 作为开发规划。
>
> **更新时间**：2026-07-05

---

## 问题格式

```markdown
### UX-XXX: 简短标题
- **发现日期**：YYYY-MM-DD
- **页面/模块**：哪个页面或功能
- **问题描述**：具体是什么问题
- **期望行为**：应该是什么样的
- **优先级**：🔴 高 / 🟡 中 / 🟢 低
- **状态**：📋 待处理 / 🔧 已规划 / ✅ 已解决
```

---

## 待处理问题

### UX-002: PyMuPDF 解析后丢失 PDF 中的图片/图表
- **发现日期**：2026-07-02
- **页面/模块**：解析流程（parser/core/mineru/router.py 路由策略）
- **问题描述**：
  - 当前解析路由策略（D13 二元路由）：有文本层的 born-digital PDF 会优先走 PyMuPDF 本地抽取
  - PyMuPDF 只提取嵌入文字层，**完全丢弃图片、图表、架构图等视觉元素**
  - 实际案例：W-sha-05e46bff6988 (Claude Sonnet 5 System Card) 解析后 content.md 只有纯文字（234K），无任何图片引用
  - 系统卡片/技术文档类 PDF 通常包含大量架构图/流程图，丢失后严重影响阅读体验
- **期望行为**：
  - 方案A：允许用户在审核页面选择重新解析并指定后端（强制走 Cloud VLM）
  - 方案B：修改路由规则，对特定类型文献（系统卡片/技术报告）默认走 VLM
  - 方案C：PyMuPDF 抽取时同时提取图片（pymupdf 支持 `page.get_images()` 和 `pix.save()`）
- **优先级**：🟡 中
- **状态**：📋 待处理
- **技术备注**：
  - 路由代码：`parser/core/mineru/router.py` 的 `_route_by_d13()` 函数
  - PyMuPDF 后端代码：`parser/core/mineru/pymupdf_client.py`（注释已写明代价：丢版面结构）
  - VLM 后端保留图片：markdown 中 `![](images/xxx.png)` 引用 + 独立图片文件
  - 用户提到子项目（MinerU）是保留了图片的，问题出在走了 pymupdf 分支

### UX-001: 缺少批量触发流程的管理页面
- **发现日期**：2026-07-01
- **页面/模块**：全局（收件箱 → 解析 → 元数据抽取 → 分类抽取）
- **问题描述**：摄入收件箱后，只能一篇一篇地触发解析、元数据抽取、分类抽取。每个阶段都需要手动操作，效率极低。
- **期望行为**：
  1. 有一个总体管理页面，可以一键运行整个流程（解析 → 元数据 → 分类）
  2. 或者每个阶段支持批量触发，然后分别到各审核页面审核
  3. 显示各阶段的待处理数量和状态
- **优先级**：🔴 高
- **状态**：📋 待处理
- **技术备注**：后端 API 已支持批量（`work_ids` 数组或 `all_pending: true`），缺的是前端入口

### QA-004: 分类词汇模板仍是预留能力，尚未建立同步/发布流程
- **发现日期**：2026-07-04
- **页面/模块**：模板管理（`api/routes/templates.py`、`TemplateManage.vue`）+ `api/classification_vocab.py` + 前端 labels
- **问题描述**：元数据模板已经接入真实抽取链路；但分类词汇 Tab 仍为只读/预留，保存端点不会自动同步 `classification_vocab.py`、前端 labels 和测试 fixture。
- **期望行为**：分类模板变更应有明确的审核、同步、测试和发布流程；前端编辑入口开放前必须保证后端 vocab、前端 labels、分类抽取 prompt 和测试 fixture 一致。
- **优先级**：🟡 中
- **状态**：📋 待处理

### QA-002: 手动上传候选 PDF 缺少生命周期保护
- **发现日期**：2026-07-03
- **页面/模块**：`POST /api/intake/candidates/{id}/upload-pdf`
- **问题描述**：当前上传端点只校验候选存在，未拒绝已入库、已拒绝或已有 `local_pdf_path` 的候选；重复调用可能覆盖 `_collector_cache/{candidate_id}.pdf` 并改写 resolution。
- **期望行为**：只允许未入库且未拒绝候选上传；已有 PDF 时返回 409 或要求显式 force；上传采用临时文件 + 原子替换，并记录替换原因。
- **优先级**：🟡 中
- **状态**：📋 待处理

### QA-003: 收件箱上传声明大小限制但未执行，且同名文件会覆盖
- **发现日期**：2026-07-03
- **页面/模块**：`POST /api/ingest/upload`
- **问题描述**：`api/routes/ingest.py` 定义了 `MAX_FILE_SIZE = 200MB`，但上传流程未累计检查大小；写入 `_inbox` 时同名 PDF 会直接覆盖。
- **期望行为**：超过限制返回 413 并清理临时文件；同名冲突返回 409 或生成唯一文件名。
- **优先级**：🟢 低
- **状态**：📋 待处理

---

## 已规划问题

<!-- 从待处理转移到这里，标注对应的开发计划 -->

---

## 已解决问题

<!-- 解决后移到这里，保留记录供参考 -->

### UX-004: 字段级重抽前端入口（双模式） → ✅ 已完成
- **解决日期**：2026-07-04
- **解决方式**：新增后端 `rerun-preview` / `rerun-apply` / `rerun-prompt` 三个端点，复用 `scripts/literature_metadata_rerun.py` 的字段级重抽、field_focus prompt 和 supersede 链路。
- **前端入口**：`MetadataReview.vue` 每个可重抽字段旁新增「重抽」和「复制」按钮；重抽先预览 diff，确认后写入新 extraction 并 supersede 旧记录；复制 prompt 作为剪贴板/手动降级方案。
- **验证**：`tests/test_metadata_rerun_api.py` 15 passed；`web` 构建通过；健康检查通过。

### QA-001: 元数据模板接入真实抽取链路 → ✅ 已完成
- **解决日期**：2026-07-04
- **解决方式**：新增共享 loader `api/metadata_template.py`，把 `templates/templates.json`、内置字段、字段校验、prompt 生成、rerun 字段白名单统一为一个运行时事实源。
- **接入范围**：`scripts/literature_metadata_extract.py`、`POST /api/metadata/extract`、`scripts/literature_metadata_rerun.py`、`rerun-preview`、`rerun-prompt` 均读取当前元数据模板；`validate_extraction()` 的 missing 字段也按模板字段计算。
- **前端动态化**：`MetadataReview.vue` 已读取模板字段生成审核表；自定义字段可展示、编辑、复制 prompt、发起字段级重抽；人工编辑的模板字段会提升为 high confidence。
- **使用文档**：`README.md` §9 已说明前端 `/templates` + `/metadata` 使用方式、CLI/API/agent 批量处理方式；`scripts/README.md` 已说明 agent 批量重抽直接读模板并调用脚本，不需要从界面复制 prompt。
- **资产落地**：新增可审查的 `templates/templates.json` baseline（metadata v1.1）。
- **遗留拆分**：分类词汇模板同步/发布流程另记为 QA-004。

### UX-003: 元数据字段模板可视化展示 → ✅ 升级为独立模板管理页面
- **解决方式**：从 MetadataReview 详情弹窗（只读展示）升级为 `/templates` 独立页面（可编辑+三大Tab）
- **解决日期**：2026-07-03
- **详情**：见 `docs/PROJECT_HISTORY.md` §六「模板管理独立页面」
