# 文献库前端

> 状态：当前权威文档
> 更新时间：2026-06-29

这是本地文献治理系统的 Vue 3 前端，不是通用 Vite 模板。

## 产品形态

V1 前端遵循的治理原则是：

```text
队列优先 -> 证据辅助 -> 人工决策 -> 状态留痕
```

主要界面包括：

- Dashboard：入口和快速导航。
- Works / WorkDetail：文献浏览、源文件/PDF 检查、元数据与分类编辑。
- Duplicates：重复组审核、关系决策、隔离/合并操作。
- MetadataReview：带证据的模型元数据抽取审核，以及低风险批量批准。
- ClassificationReview：分类体系审核、模糊度筛选、草稿/审核流程。
- IntakeReview / InboxReview / TopicsReview：采集审核、手动 inbox 摄入和主题闸门。

## 开发命令

首次安装依赖：

```powershell
npm install
```

启动开发服务：

```powershell
npm.cmd run dev
```

构建生产产物：

```powershell
npm.cmd run build
```

部分 Windows PowerShell 环境会拦截 `npm.ps1`，本项目验证命令优先使用 `npm.cmd`。

## 后端耦合

前端通过 `/api` 调用 FastAPI，开发代理配置在 `vite.config.js` 中。

默认端口：

- 后端：`19527`
- 前端：`19528`

生产模式下，后端可以托管 `dist/` 构建产物。

## 体验不变量

- 隔离、合并等高影响操作必须在执行前说明影响范围。
- 审核页面应让证据靠近决策。
- 页面统一使用 `App.vue` 中的全局 `AppLayout`；route view 不应再包一层 `AppLayout`。
- 可能发生部分写入的保存流程，不应误报成功。
- 界面标签应使用研究者能理解的业务语言，而不是纯实现名。
