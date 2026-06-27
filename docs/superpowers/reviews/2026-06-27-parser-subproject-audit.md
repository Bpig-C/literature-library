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

### Phase A 自审（code-reviewer，针对 commit 568b76e）

- **范围**：cloud_client / config+conf.json+mineru_op / literature_batch_parse / llm_judge / test_cloud_client / .gitignore+.env.example。
- **CRITICAL**：无。四条硬契约全部成立（输出路径契约、不删文件/串行、token 仅环境变量、下游链路未污染）。密钥安全：.env 已 ignore、.env.example 仅空值、staged diff 无 token。
- **裁定**：PASS-WITH-FINDINGS，可进入 Phase B。

**MAJOR 发现与处置**：
- M1（-60018 不重试仅靠"无分支"实现，意图不显式）→ **已修**：`_request_with_retry` 增加 `elif code==-60018` 显式分支 + 注释。
- M2（成功时 task_id 未记 batch_id，丢失唯一回溯句柄）→ **已修**：CloudClient 暴露 `self.last_batch_id`；batch 脚本成功/失败均写 `task_id=batch_id`。
- M3（ledger 仅循环末尾落盘，中途崩溃丢进度+重复烧配额）→ **已修**：每条处理后立即 `save_ledger(ledger)`。

**MINOR 处置**：
- m6（临时 prompt 文件名同秒碰撞）→ **已修**：改用进程内计数器 + `time.time_ns()`。
- m7（测试覆盖薄）→ **已修**：新增 `test_safe_extract_zip_blocks_traversal`（ZIP Slip）、`test_missing_full_md_fails_with_zip_retained`（缺 full.md 失败且保留 zip）。共 6 测全过。
- m1/m2/m3/m5：低风险，记存，不在 Phase A 处理（images 覆盖、is_parsed rglob、language 默认、reader 异常静默）。

**需登记的决策**：
- D12（m4）：`quality_verdict` 默认 `full=True`（通篇阅读），偏离 spec §5b"只送摘要省成本"的初衷。**原因**：冒烟实测发现 head+tail 摘要里的"[省略中段]"标记会被模型误判为解析截断，导致每篇误报 poor；MiMo 1M context 可承载全文，且用户已确认"每篇都判、成本可接受"。权衡后选全文以保证裁判准确性。成本：~15k 脚手架 + 正文 tokens/篇。**若后续批量成本过高，可改回 `full=False` 粗筛**。

