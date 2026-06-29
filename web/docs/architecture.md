# Web 子项目架构

`web/` 是 Vue 3 + Vite 单页应用，负责人工浏览、审核、编辑和触发部分后端动作。

## 页面结构

![Web 子项目架构](../../docs/architecture/diagrams/web-architecture.svg)

## 职责边界

- 负责人工可视化审核和交互，不直接读写 SQLite。
- 所有业务数据通过 `/api` 访问。
- PDF 预览、列表筛选、审核按钮、批量批准等交互必须与后端状态语义一致。
