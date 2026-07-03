# Project Memory — literature_library

## 项目约定
- **技术栈**: Vue 3 + Naive UI + Vite（纯 JS，不引 TS/Pinia/axios/Tailwind）
- **端口**: 前端 localhost:19528 / 后端 localhost:19527
- **红线**: 不引入新依赖 / 不改后端数据结构 / 不改数据库 schema
- **审核模式**: 用户作为中间人，本地模型实施 → 我(WorkBuddy)审核
- **语言**: 纯中文沟通，大白话类比，避免堆砌英文术语

## 关键架构决策
- CSS 变量全量替换策略（用户明确否决增量方案）
- purple 色系废弃，统一 accent 蓝
- Composable 为主的状态管理策略（暂不引入 Pinia）
- Pipeline 页面双模式设计：待抽取(extract) vs 待审核(review)，通过 selectable prop 控制 UX

## 文件结构速查
- API 路由: `api/routes/*.py`（含新增 `templates.py`）
- 前端视图: `web/src/views/*.vue`（含新增 `TemplateManage.vue`）
- 组件: `web/src/components/*.vue`
- Composable: `web/src/composables/use*.js`
- 前端 API: `web/src/api.js`（+ 新增 `api_templates.js`）
- 脚本: `scripts/*.py`
- 数据库: `literature.sqlite`（SQLite）
- 模板数据: `templates/templates.json`（运行时生成，元数据字段自定义存储）
- 计划文档: `docs/superpowers/plans/`
- 审核报告: `docs/superpowers/reviews/`

## 2026-07-02 新增架构决策
- **模板资产管理**：独立 `/templates` 页面统一管理三大模板（元数据/分类/Discovery），后端 API 预留编辑能力
- **采集审核来源追溯**：从 raw_meta JSON 自动解析发现检索/直接采集渠道，展示可跳转的溯源信息
- **PDF 操作拦截**：无 PDF 时不允许直接批准，强制引导先下载
- **api.js 的 request 函数已 export**：供 api_templates.js 复用

## 已知限制
- 后端 per_page 最大 100
- python-multipart 已安装（上传功能需要）
- Pipeline 的"选择性执行"后端已支持 work_ids 参数
