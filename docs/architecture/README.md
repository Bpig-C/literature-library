# 架构文档维护入口

本目录维护项目级架构真相，只描述跨子项目边界、关键运行时依赖和数据/控制流。子项目内部实现细节放在各自目录的 `docs/architecture.md`。

## 文档分层

| 层级 | 文件 | 维护范围 |
| --- | --- | --- |
| 系统级 | [system-architecture.md](system-architecture.md) | 用户、智能体、前端、API、采集、解析、脚本、SQLite、文件区之间的关系 |
| 子项目级 | `api/docs/architecture.md` | FastAPI 路由、数据访问、对外 API 契约 |
| 子项目级 | `collector/docs/architecture.md` | 采集候选、来源适配、门控、提升入库 |
| 子项目级 | `parser/docs/architecture.md` | PDF/文档解析路由、MinerU/PyMuPDF 后端、解析产物 |
| 子项目级 | `web/docs/architecture.md` | Vue SPA 页面、API 客户端、用户交互入口 |
| 子项目级 | `scripts/docs/architecture.md` | CLI 维护脚本、批处理、迁移、健康检查 |

## 维护约定

- 图文件使用 `docs/architecture/diagrams/*.svg`，正文用普通 Markdown 图片引用，以兼容 VS Code 自带 Markdown Preview；不要改回 Mermaid 代码块，除非项目统一要求安装 Mermaid 扩展。
- 根目录图只画跨边界关系，不展开每个路由函数或 Vue 组件。
- 子项目图只展开本子项目内部结构，不复制整张系统图。
- 当 API、CLI、数据库表、文件目录契约变化时，同步更新系统级图和相关子项目图。
- 长任务更新时，主 agent 应派发子 agent 分块审查：至少覆盖文档一致性、代码事实核对、第二轮汇总复核。
- 审核结论必须基于仓库文件、README、测试、路由、脚本入口；不能凭记忆补系统能力。
