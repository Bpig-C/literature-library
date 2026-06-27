# P3.5 文档解析子项目化 —— 执行审计日志

> 本文件记录 P3.5 全阶段执行过程中的**每一次决策**与**每一轮自审结果**，供事后逐项审查。
> 执行依据：`docs/superpowers/specs/2026-06-27-parser-subproject-design.md`
> 分支：`feat/p3.5-parser-subproject`（从 master 切出）
> 执行日期：2026-06-27 起

## 决策登记（按时间）

| # | 时间 | 决策 | 依据/原因 | 影响 |
|---|------|------|-----------|------|
| D1 | 启动前 | 子项目目录 `parser/` | 用户确认 | 复制目标位置 |
| D2 | 启动前 | `literature_batch_parse.py` 进程内直连 cloud client | 用户确认 | 衔接方式 |
| D3 | 启动前 | 默认 `pipeline` + 质检闸门决定是否升 vlm | 用户反问 → 两段闸门设计 | §5 模型路由 |
| D4 | 启动前 | 自部署 MinerU 保留作降级（`MINERU_BACKEND=selfdeploy`） | 用户确认 | §3/§6 |
| D5 | 启动前 | 质量裁判走 opencode→MiMo-v2.5-pro（弃 Ollama qwen3:4b） | 用户：旧模型不胜任通篇阅读 | §5b |
| D6 | 启动前 | 每篇新解析都跑质量裁判 | 用户确认 | §5b 覆盖范围 |
| D7 | 启动前 | 建 `scripts/llm_judge.py` 共享模块（非内联） | 用户确认 | §5b 范围 |
| D8 | 启动前 | 借鉴参考项目 `ei_corpus_loop_*` 的运行时原语，不搬 loop 框架 | 过度设计取舍 | §5b |
| D9 | 启动前 | token 放根目录 `.env` 的 `MinerU_API_KEY` | 用户放置 | 配置 |
| D10 | 启动前 | `.env` 加入 `.gitignore`（原本未忽略，密钥有泄露风险） | 安全护栏 | .gitignore |
| D11 | 启动前 | 在 `feat/p3.5-parser-subproject` 分支执行（非 master） | 隔离可回滚 | git |

## 自审记录（阶段间派发 code-reviewer subagent）

> 每阶段完成后在此追加一节：审核范围、发现、处置、是否放行进入下一阶段。

（执行中按阶段填充）
