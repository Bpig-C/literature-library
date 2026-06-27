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

## Phase E：路由重构 + 本地模型统一（用户追加需求，2026-06-28）

### 决策登记（追加）
- D13：解析路由改为二元——**文本层(born-digital) PDF → PyMuPDF 本地直抽**（精准公式/免费/快），**扫描型 → cloud vlm**；**pipeline 弃用**（其公式间距伪影见 Phase B M1）。PyMuPDF 抽取后做轻量质检，不合格回退 cloud vlm。
- D14：**所有本地模型调用弃用 ollama:11435(qwen3:4b)，统一走 opencode→MiMo-v2.5-pro**（经 `scripts/llm_judge.py`）。迁移范围：metadata_extract / classification_extract / metadata_rerun。

### Phase E1：PyMuPDF 文本层路径 + 二元路由
- 新增 `parser/core/mineru/pymupdf_client.py`：`PyMuPDFClient.parse_pdf`（文本层→content.md/content.json）+ `has_text_layer()` 文本层判定 + `quality_ok()` 质检（garble_ratio≤0.15 且 avg≥200 字符/页）。
- `scripts/literature_batch_parse.py`：`parse_one` → `route_and_parse`（文本层→PyMuPDF→质检→不合格回退 vlm；扫描型→vlm）；`update_db` 增写 `backend`（pymupdf/vlm）；DB backend 列落库。
- cloud 默认 `model_version` 由 pipeline 改 **vlm**（config.py + conf.json）。
- 实测：文本层 PDF（2406.10162）→ backend=pymupdf，93207 字符 / garble=0.0 / quality_ok=True，**cloud 未被调用**（DummyCloud 断言）。

### Phase E2：三脚本迁移到 opencode→MiMo
- `llm_judge.py` 新增 `chat(messages)->{"message":{"content":<json文本>}}` drop-in（拼 system+user → judge → 序列化回 JSON，兼容原 `parse_llm_json` 流程；失败抛 RuntimeError）。
- metadata_extract / classification_extract：`DEFAULT_MODEL=llm_judge.DEFAULT_MODEL`、调用点 `ollama_chat(...)`→`llm_judge.chat(messages, model=, timeout=)`。
- metadata_rerun：`import llm_judge` + 调用点替换（DEFAULT_MODEL 经 metadata_extract 继承已为 mimo）。
- 实测：`metadata_extract --work-id W-arxiv-2406.10162 --no-write` 经 MiMo 成功抽取标题/5 作者/contributors(Anthropic/Redwood/Oxford)/置信度，1 成功 0 失败。无活跃 ollama_chat 调用残留。

### Phase E 自审（code-reviewer）

- **CRITICAL**：无。四项核验全过——契约（PyMuPDF/cloud 都写 contract output_dir，content_md_path 唯一入口）、无双重 cloud 调用（route_and_parse fallback 仅调一次）、无密钥泄露、三脚本无活跃 ollama:11435 调用（DEFAULT_MODEL=mimo）。
- **裁定**：PASS-WITH-FINDINGS。
- **M1**（cloud_client 残留 `"pipeline"` 默认）→ **已修**：改 `"vlm"`。
- **M2**（metadata_rerun 死 import `ollama_chat`）→ **已修**：移除。
- **m6**（路由层无测试）→ **已修**：新增 `parser/tests/test_routing.py`，锁定三条不变量（文本层合格→pymupdf 且 cloud 不调；质检不合格→cloud 恰好一次且覆盖 content.md；扫描型→cloud）。共 9 测全过。
- 其余 MINOR（options 丢弃/--url 占位/短文档质检阈值/失败 backend 归属）记存，低风险不阻塞。

### Phase E 扩展：双栏阅读顺序检测（方案 B，2026-06-28）

**背景**：用户抽检双栏论文（Goal Misgeneralization 2105.14111）确认 PyMuPDF 阅读顺序正确（列顺序读取、无左右交错），但质检门原本只查 garble/字符率，**检测不到阅读顺序错乱**（列交错不产生乱码字符）。用户选方案 B：加一层列交错检测。

**实现**（`parser/core/mineru/pymupdf_client.py`）：
- 纯函数 `column_switch_count(blocks, width)`：按 PyMuPDF 给出的阅读顺序统计文本块的列切换次数（L/R，跨中线 M 忽略）。正常双栏≈1 次；列交错(L,R,L,R…)很多次。
- `reading_order_ok(pages_blocks)`：对双栏页（同时有≥2 左栏块和≥2 右栏块）判别，单页切换 > 6 视为乱序；双栏页中乱序占比 ≥ 50% → 整篇不可接受。
- 接入 `parse_pdf`（与文本抽取同遍历收集 blocks）+ `quality_ok`（`reading_order_ok=False` → 回退 cloud vlm）。
- 指标落 `last_metrics`：`reading_order_ok / two_col_pages / two_col_bad_pages / max_column_switches`。

**验证**：
- 实测 Goal Misgeneralization：11 个双栏页 / 0 乱序 / max_switches=3 / `quality_ok=True`（正确放行干净双栏论文）。
- 单测 `test_reading_order.py`（6 项）：顺序 1 切换、交错 15 切换、单栏不判、多数乱序判整篇不过——全过。
- 全 parser 相关测试 15 项（cloud_client+routing+reading_order）全过。`test_api.py` 26 项 ERROR 系 `./html` 静态目录缺失（复制时剔除；文献库不跑该 FastAPI 服务，无关）。

**残留**（轻度，不阻塞）：PyMuPDF 的逐行断行/去连字符(`outof-distribution`)/脚注插队——影响精读美观，不影响下游文本可用性。




