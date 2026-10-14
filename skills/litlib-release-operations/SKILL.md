---
name: litlib-release-operations
description: 核实并发布 literature-library 修复，完成 Git 推送、不可变快照、服务槽恢复、写者 epoch 交接及客户端验证。用于该项目服务器迭代和重新部署。
---

# LitLib 发布操作

目标是让经验证的提交实际在线服务，并保留数据、认证配置和恢复证据。

## 授权与版本

- 用户需授权 Git 推送和生产部署。先完成可审查的修复、测试和具体部署计划；无授权时在生产变更前请求一次授权。已有本次发布授权则继续，无需重复询问。
- 小 bug 保持产品版本、API/客户端协议、contract/schema 版本不变，除非修改确实改变兼容契约。每次实际部署必须产生独立 commit、release、manifest；写者切换按权威守卫交接到 N+1。这些身份不等于产品版本升级，不能省略 epoch 规避守卫。
- 尽量在一次授权、一个维护窗口中合并相关补丁。推送成功、快照可发现、代码修复、线上修复是不同阶段，分别报告证据。

## 执行

执行发布前阅读 [发布流程与恢复边界](references/procedure.md)。流程依赖仓库现有 `storage_release.py`、`storage_authority.py`、`restored_runtime.py` 和主机 `litlib/control` 下的维护适配器及持久启动脚本。发现当前服务、epoch、待续跑作业和主机路径，不能把历史示例当成当前配置。

保持客户端服务器 URL、CA 和 bearer token；无需因兼容补丁重新配置客户端。若客户端使用 expected-commit 固定校验，告知新的提交。能力或协议改变才更新客户端工具。

验收后提供实际线上 commit/release/manifest/epoch、回执位置、测试范围和客户端影响。获授权时回复对应 issue，说明修复已部署；保留尚未解决的关联问题。
