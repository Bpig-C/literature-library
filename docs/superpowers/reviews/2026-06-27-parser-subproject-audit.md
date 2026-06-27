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

### Phase B 试跑（真实官网 API，隔离输出）

**执行**：3 篇 reward-hacking 样本经官网 cloud API（pipeline/en）重解析到隔离目录 `_cloud_trial/`，未触碰真实契约路径（实测真实 content.md mtime 仍为 2026-06-17，未被改动）。报告：`docs/superpowers/reviews/phase_b_trial_report.json`。

**结果**（全部 ok=True）：
| 文献 | 耗时 | 新旧字符差 | 章节数(新/旧) | abstract/refs | 裁判 old→new |
|------|------|-----------|--------------|--------------|-------------|
| 2406.10162 | 32s | +147 (91368/91221) | 48/48 | 有/有 | good(0.98)→good(0.98) |
| 2511.18397 | 42s | +2021 (212197/210176) | 136/136 | 有/有 | good(0.95)→acceptable(0.92) |
| 2105.14111 | 24s | +254 (63006/62752) | 24/24 | 有/有 | acceptable(0.9)→acceptable(0.88) |

**结论**：官网 API 与原自部署 MinerU 产出**结构高度一致**（字符差 ~1% 内、章节数相同、abstract/refs 均在）。但 Phase B 自审（见下节）发现一个**可复现的已知差异**：cloud 的 pipeline 后端对数学公式渲染存在**公式间距伪影**（如 `$3 3 . 7$` 数字间多空格），2/3 样本裁判因此出现 formula_spacing/garbled_formulas issue、completeness 略降。这不是随机噪声，而是 cloud-pipeline 渲染器特性。

**对路由的影响（落实 D3 两段闸门）**：数学密集型文献走 pipeline 会有公式间距伪影 → 这类 work 应走 `vlm` 后端，或经质检闸门（裁判 needs_reparse）自动升级。已解析的 145 篇不必批量回填（自部署产出本身良好）；cloud 主要面向**新入库 PDF**。

**契约路径、隔离、token 仅环境读取均成立**。可进入 Phase C（写真实契约路径）。

### Phase B 自审（code-reviewer）

- **CRITICAL**：无。隔离（仅写 `_cloud_trial/`，真实 content.md mtime 仍 06-17 未动）、token 安全（仅环境读取，报告无 `eyJ` 泄露）、无 DB 写（仅 SELECT）、`_cloud_trial/` 已 gitignore 且未入库——四项全过。
- **裁定**：PASS-WITH-FINDINGS，可进入 Phase C。
- **M1（重要）**：上述公式间距伪影——审计原"高度一致"措辞高估，已据实修正为"结构一致 + 已知公式渲染差异"。
- **m1**：`md_stats.has_references` 启发式过松（`[1]` 命中任何引用标记，refs 章节被丢也判 true）→ Phase C 跑批脚本不复用此启发式；如需 gates 改用标题正则。
- **m2**：试跑报告未记 `model_version` → Phase C 报告补记 model_version/language 以便复现。

### Phase C 真实契约路径验证（backup/restore，不污染既有数据）

**执行**：样本 `W-arxiv-2406.10162` / `SF-13d4293ad314-00158`。因 Phase B 发现 cloud-pipeline 公式间距伪影（M1），且该篇已由自部署良好解析，故采用**保守 backup/restore**：把 Phase B 的 cloud 试跑产物临时放到真实路径，校验全链路后**按 hash 还原原始文件**，不永久改写既有良好数据。报告：`docs/superpowers/reviews/phase_c_validate_report.json`。

**结果**（全链路成立）：
- `db_path_resolves=True`：DB `content_md_path` 指向真实文件。
- `is_cloud_version=True`：放置 cloud 产物后，DB 路径所指即为 cloud 版本。
- `downstream_read`：复刻 metadata_extract 读前 8000 字成功（has_abstract=True）。
- `metadata_extract --no-write` 真实运行：成功读取 `content.md`（"输入：8000 字符 → 2967 tokens"），仅在 Ollama 连接处失败（`localhost:11435` 离线，`WinError 10061`）——属模型服务基础设施问题，**非 P3.5 契约问题**；证明下游正确以 `content_md_path` 为唯一文本入口消费 cloud 产出。
- `restored_matches_before=True`：真实目录按 hash 完全还原（real content.md hash `e51bdcda587f3371` ≠ cloud `c5538cff69ba7a6d`，确认已还原为原始自部署产出）。

**结论**：cloud→真实路径→DB→下游读取 全链路验证通过，契约不破坏、可回滚。**既有 145 篇不批量回填**（自部署产出良好 + cloud-pipeline 对数学公式有间距伪影）；cloud 面向新入库 PDF，数学密集型走 `vlm`（D3 闸门）。

**遗留**（非 P3.5 范畴）：`works.parse_status` 与 `literature_parse_runs.status` 不同步（3 篇 parse_runs=succeeded 但 works.parse_status=pending），Phase D 登记。

### Phase C 自审（code-reviewer）

- **CRITICAL**：无。四项安全属性独立复核全过——无永久数据改写（real content.md hash 还原为原始自部署版）、无 DB/ledger 写（仅 SELECT）、无 cloud 产物残留、报告无密钥泄露。
- **裁定**：PASS-WITH-FINDINGS，可进入 Phase D。
- **M1/M2**：针对"批量回填工具"的健壮性（restore 需 try/finally、images/ 子树需字节备份）。**不适用于本 P3.5**：已决策不批量回填 145 篇（cloud 面向新 PDF），故无需构建批量回填工具；若未来另立批量任务再硬化。
- **m3**：parse_status 滞留需独立子任务 → Phase D 处理。

### Phase D 文档与收尾

- **文档**：
  - `TECHNICAL_OVERVIEW.md` §2 解析链路重写（cloud 默认 / selfdeploy 降级 + 质量裁判）、技术栈表、当前限制更新。
  - `FUTURE_WORK_PLAN.md` P3.5 状态 TODO → **已完成**；路线图第 15 项标记 ✅。
  - `parser/README.md` 标注子项目身份 + cloud/selfdeploy 后端说明 + token 来源。
- **parse_status 滞留修复**：新增 `scripts/migrate_sync_parse_status.py`（dry-run 默认 + `--apply`，幂等、单向 pending→succeeded）。
  dry-run 定位 5 篇（parse_runs=succeeded 但 works.parse_status=pending），apply 后复核剩余 0。
- **未做（明确出范围）**：不批量回填既有 145 篇（自部署产出良好 + cloud-pipeline 公式伪影）；批量回填若需要，另立任务并按 Phase C 自审 M1/M2 硬化（restore try/finally + 子树字节备份）。

## P3.5 整体裁定

四阶段全部完成，三道自审（A/B/C）均为 PASS-WITH-FINDINGS，无 CRITICAL。契约（content_md_path 唯一文本入口、输出路径、不删文件、串行、token 仅环境变量）全程未破坏，全程可回滚（feature 分支、隔离试跑、backup/restore）。解析能力已进版本控制；新 PDF 走官网 cloud API；自部署保留降级；质量裁判 + 共享 LLM 基础设施就位。



