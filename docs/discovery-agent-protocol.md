# Discovery Search Agent Protocol

V1.2 受约束广泛发现与检索方案的本地模型/agent 执行规范（支持 composite 多信号组合输入）。

本文档既是外部 agent 的回填协议，也是可以直接交给本地模型读取的"skill/runbook"。它的目标是让 agent 按已有 discovery run 的检索方案执行真实检索，把结构化命中写回 `discovery_hits`，再由人工在前端审核；agent 不自行探索系统边界，也不直接写 `works`。

V1.2 新增 `composite` 模式：允许用户/系统同时提供 names、titles、authors、institutions、keywords、known_urls 等多种信号，agent 综合生成更优的搜索策略和去重指导，解决单一模式输入对 agent 过于弱的问题。

## 使用场景

当用户在 `/discovery` 或 `/topics` 中创建 discovery run 后，如果 run 的 `executor` 是 `agent:web-access` 且状态为 `planned`，本地模型/agent 应读取本文档，并只负责执行检索和回填 hits。

当前 V1.1 不会自动拉起 opencode/Codex 子进程。实际流程是用户从前端复制 run 指令，再交给本地模型执行；“生成方案后一键调用 opencode 执行检索”已记录为后续 `Discovery 本地模型自动执行器` 工作项。

V1.2 支持的输入模式：

- `topic`：根据已有采集主题生成检索方案。
- `name`：根据模型、系统、机构项目或材料名称检索。
- `title`：根据已知标题检索。
- `url`：用户显式给定 URL，系统创建 manual run/hit。
- `composite`：多信号组合输入，允许同时提供 names、titles、authors、institutions、keywords、known_urls、preferred_domains、exclude_terms、artifact_type_hint、max_results、freeform_note 等多种线索。agent 根据多种信号综合生成更优的搜索策略和去重指导。

V1.2 不支持 DOI、arXiv、GitHub URL 作为 discovery mode。arXiv/GitHub 仍走现有 intake collect 链路，DOI 可先按 title/name 检索，或等待后续 DOI 反查能力。

## 人机分工

用户负责：

1. 在 `/topics` 新建或选择主题，或在 `/discovery` 填写 name/title/url/topic。
2. 检查系统生成的 search plan，确认它不是无约束全网抓取。
3. 把 run id 和本文档交给本地模型/agent 执行。
4. 在 `/discovery` 审核 hits，接受有效命中或拒绝噪声。
5. 在 `/intake` 继续 resolve、review、promote，最后再进入解析/抽取/分类流程。

agent 负责：

1. 读取本文档和 run 的 `search_plan_json`。
2. 按 plan 中的 queries、source/domain hints、exclude terms、max_results 执行检索。
3. 优先找 primary source、官方域名、机构页面、项目页、PDF/HTML 报告页。
4. 只把可信或可审核的命中回填到 `discovery_hits`。
5. 对不确定结果降低 `confidence`，并在 `reason` 里说明不确定点。

agent 禁止：

- 不登录，不绕过访问控制，不抓取需要授权的内容。
- 不编造 URL、标题、摘要或来源。
- 不直接写 `works`、`intake_candidates`、ontology vocab 或分类标签。
- 不自动 accept、promote、ingest、download PDF。
- 不把 title-only hit 批量接受；没有 URL 的命中必须由人工进一步判断。

## Web-Access Skill 约束（强制）

所有 discovery agent **必须**加载并遵循 `web-access` skill 的指引。该 skill 定义了网络访问的安全边界和质量约束：

### 核心约束

| 约束类别 | 规则 | 违规后果 |
|----------|------|----------|
| 认证与授权 | 不登录、不使用 cookie/session、不绕过任何访问控制 | confidence 降为 low + reason 标注 |
| 内容类型 | 只抓取公开可访问的 HTML/PDF/metadata；不下载二进制/视频/音频 | 忽略该资源 |
| 域名白名单 | 优先访问官方域名、学术机构域名、知名平台（arXiv/GitHub/HuggingFace） | 非白名单域名需降低置信度 |
| 请求频率 | 遵守 robots.txt；同一域名请求间隔 ≥ 2 秒；单次 run 总请求数 ≤ 50 | 超限后停止检索 |
| 内容验证 | 每个返回 URL 必须验证可达性（HTTP status check） | 无法验证时 verification_status=unverified |

### 处理受限资源的正确行为

当遇到以下情况时，agent 应按指引处理：

1. **403 Forbidden / 登录墙**
   - 不尝试绕过
   - 在 hit reason 中注明："页面需登录，未获取全文"
   - confidence 设为 `medium` 或 `low`
   - 可提供元数据级信息（标题、作者、摘要）作为参考

2. **404 Not Found / 页面已下线**
   - 该 URL 不创建 hit
   - 在 reasoning 中记录失败原因
   - 尝试搜索缓存版本或其他镜像源（如 Internet Archive）

3. **Rate Limited (429)**
   - 暂停对该域名的请求
   - 降低 max_results 或提前结束
   - 在 run 日志中记录限流情况

4. **内容不匹配**
   - 如果页面内容与查询意图明显不符
   - 不编造匹配内容
   - 标记 confidence=`low` 并在 reason 中说明差异

### Composite 模式的 Web-Access 特别要求

当 mode 为 `composite` 且包含多个信号时：

1. **优先级排序**：根据信号强度（known_urls > preferred_domains > names/titles > keywords）决定搜索顺序
2. **来源交叉验证**：如果同一个实体出现在多个信号中（如 name 出现在 known_urls 的域名），应优先验证该 URL
3. **去重预检**：在回填前检查 URL 是否已在其他 run 中出现，避免重复网络请求
4. **排除词优先应用**：exclude_terms 应在生成 query 时就加入，而非事后过滤，以减少无效网络请求

## 推荐使用流程

1. 启动后端和前端：

```powershell
uv run python scripts\run_api.py
cd web
npm run dev
```

2. 在前端创建 run：

- `/topics`：新建或选择主题后生成 discovery plan/run。
- `/discovery`：按 name/title/url/topic 创建 run；URL 模式会直接创建 manual hit。

3. 交给本地模型执行。推荐给模型的固定指令如下：

```text
你是 literature_library 的 discovery-search agent。

工作目录：D:\02_academic\doctoral\literature_library
必须先读取：docs/discovery-agent-protocol.md

任务：
1. 获取并阅读 discovery run：run_id={DR-xxxx}。
2. 读取 run 的 search_plan_json，理解输入信号和搜索策略：
   - 如果 mode 是 composite：plan 包含多种线索（names/titles/authors/keywords/institutions 等），agent 应综合这些信号设计检索查询，而非只用单一字段。
   - 如果 mode 是 name/title/topic/url：按对应单模式检索。
3. 严格按照 search_plan_json 执行检索，不自行扩展成无限制抓取。
4. 每条命中必须包含 url 或 title；优先提供 url。
5. 每条命中输出 title、url、source_type、snippet、reason、confidence、query、primary_source、content_type、verification_status。

【强制】Web-access 约束：
- 必须加载 web-access skill 并严格遵循其指引执行所有网络访问。
- web-access skill 定义了允许的域名白名单、请求频率、内容类型约束等规则。
- 不登录、不绕过访问控制、不抓取需要授权的内容。
- 遇到访问受限页面时，应降低 confidence 并在 reason 中说明限制，而非尝试绕过。

6. 通过 POST /api/discovery/runs/{DR-xxxx}/hits 回填 JSON 数组。
7. 回填后停止。不要 accept、promote、写 works、改 ontology vocab、下载 PDF 或摄入文件。

质量约束：
- 优先官方域名、机构发布页、项目主页、PDF/HTML 原文页。
- 不编造 URL、标题或摘要。
- 无法确认的结果 confidence=low，并说明原因。
- 发现噪声过高或没有结果时，回填空数组或少量 low confidence 候选，并解释检索失败原因。

Composite 模式特殊要求：
- 当 plan 中包含多个信号时（如 names + authors + keywords），应生成组合查询而非单一查询。
- 利用 preferred_domains 和 exclude_terms 缩小搜索范围并提高结果相关性。
- 在 reasoning 字段中记录如何综合各信号制定策略。
- 对于 known_urls，将其作为 source hint 辅助验证，但不自动创建 hit。
```

4. 回到 `/discovery` 审核 hits。

5. 接受后的 hit 只会创建 `intake_candidates(resolution='pending')`，仍需到 `/intake` 走现有 resolve/review/promote 闸门。

## 回填入口

### HTTP API（推荐用于外部 agent）

```http
POST /api/discovery/runs/{run_id}/hits
Content-Type: application/json

[
  {
    "url": "https://...",
    "title": "...",
    "source_type": "web",
    "confidence": "high",
    "snippet": "...",
    "reason": "...",
    "query": "...",
    "primary_source": "true",
    "content_type": "html",
    "verification_status": "url_verified"
  }
]
```

### Python core

```python
from collector.discovery import insert_discovery_hit

hit = insert_discovery_hit(
    run_id="DR-xxxx",
    url="https://...",
    title="...",
    source_type="web",
    confidence="high",
    snippet="...",
    reason="...",
    query='"model name" "system card"',
)
```

### CLI 方式

```bash
# 生成 plan，不创建 run
python scripts/literature_discovery.py plan --name "GPT-5.6 system card"

# 创建 run
python scripts/literature_discovery.py run \
  --mode name \
  --input '{"name": "GPT-5.6 system card", "artifact_type_hint": "system_card"}'

# 查看 planned runs
python scripts/literature_discovery.py runs --status planned

# 查看 hits
python scripts/literature_discovery.py hits --run DR-xxxx

# 接受 hits 到 intake
python scripts/literature_discovery.py accept --hits DH-1,DH-2

# 拒绝 hit
python scripts/literature_discovery.py reject --hit DH-1 --note "not relevant"
```

## Composite Input Schema

V1.2 新增的 `composite` 模式允许 agent 接收多种线索信号，综合生成更优的搜索策略。适用于用户同时掌握多种碎片信息但不确定如何组合检索的场景。

### 输入字段

| 字段 | 类型 | 必填 | 说明 | 使用场景 |
|------|------|------|------|----------|
| `topic_id` | string | 否 | 关联的主题 ID | 将 discovery run 绑定到已有主题 |
| `names` | string[] | 否 | 已知名称列表（模型名、系统名、材料名） | 已知模型/系统名称，想找相关资料 |
| `titles` | string[] | 否 | 已知标题关键词或片段标题 | 记得标题的部分关键词 |
| `authors` | string[] | 否 | 作者列表 | 知道作者姓名 |
| `institutions` | string[] | 否 | 机构列表 | 知道发布机构 |
| `keywords` | string[] | 否 | 关键词列表 | 有领域关键词但不构成完整名称 |
| `known_urls` | string[] | 否 | 已知 URL（作为 source hint，不自动创建 hit） | 已有参考链接但需找更多来源 |
| `preferred_domains` | string[] | 否 | 偏好搜索的域名 | 希望结果来自特定机构/平台 |
| `exclude_terms` | string[] | 否 | 排除词 | 需要过滤掉不相关的噪声词 |
| `artifact_type_hint` | string | 否 | 产物类型提示：`system_card` / `model_card` / `technical_report` / `research_article` / `unknown` | 明确要找的文献类型 |
| `max_results` | int | 否 | 最大结果数，默认 20 | 控制返回数量 |
| `freeform_note` | string | 否 | 自由形式研究上下文 | 补充说明检索背景和目标 |

### search_plan_json 输出结构（composite 模式）

当 mode 为 `composite` 时，search_plan_json 应包含以下结构：

```json
{
  "mode": "composite",
  "queries": [
    "\"model name\" \"author name\" keyword",
    "\"institution\" \"technical report\" topic"
  ],
  "source_hints": ["official_domain", "academic", "project_page"],
  "preferred_domains": ["openai.com", "arxiv.org"],
  "exclude_terms": ["tutorial", "blog post"],
  "max_results": 20,
  "reasoning": "综合 names + authors + institutions 信号，设计组合查询以覆盖官方页面和学术来源",
  "search_strategy": "hybrid",
  "dedup_guidance": {
    "rules": ["按 URL 规范化去重", "按标题相似度去重"],
    "threshold": 0.85
  },
  "input_signals": {
    "names": ["GPT-5.6"],
    "authors": ["Alice Smith"],
    "institutions": ["OpenAI"],
    "keywords": ["large language model", "safety evaluation"]
  }
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `mode` | string | 固定为 `"composite"` |
| `queries` | string[] | 组合后的搜索查询列表，应综合利用多种输入信号 |
| `source_hints` | string[] | 建议来源类型：`official_domain`, `academic`, `project_page`, `repository` 等 |
| `preferred_domains` | string[] | 从输入直接传递或推断出的偏好域名 |
| `exclude_terms` | string[] | 从输入直接传递的排除词列表 |
| `max_results` | int | 最大返回结果数 |
| `reasoning` | string | **必填**。策略推理说明：agent 如何综合各输入信号制定查询策略 |
| `search_strategy` | string | 搜索策略：`broad`（广泛）、`focused`（聚焦）、`hybrid`（混合） |
| `dedup_guidance` | object | 去重指导：包含 rules 和 threshold |
| `input_signals` | object | **必填**。原始输入信号的完整记录，用于审计和复盘 |

### 使用示例

#### CLI 创建 composite plan

```bash
# 使用 composite 模式生成 plan
python scripts/literature_discovery.py plan --composite \
  --names '["GPT-5.6"]' \
  --authors '["Alice Smith", "Bob Jones"]' \
  --institutions '["OpenAI"]' \
  --keywords '["safety evaluation", "system card"]' \
  --artifact_type_hint system_card \
  --max-results 15
```

#### HTTP API 创建 composite run

```http
POST /api/discovery/run
Content-Type: application/json

{
  "mode": "composite",
  "input": {
    "names": ["GPT-5.6"],
    "authors": ["Alice Smith"],
    "institutions": ["OpenAI"],
    "keywords": ["safety evaluation", "system card"],
    "artifact_type_hint": "system_card",
    "max_results": 15,
    "freeform_note": "寻找该模型的正式安全评估报告"
  }
}
```

### 向后兼容性

- 旧的单模式 API（`topic` / `name` / `title` / `url`）完全保留且不受影响。
- 已有的数据库记录（runs 和 hits）无需迁移。
- `composite` 是增量功能，不影响现有 discovery 流程。
- Agent 在处理 composite run 时，仍遵循相同的边界约束：
  - 只能回填 `discovery_hits`
  - 不自动 accept/promote/写 works
  - title-only hit 不能批量接受
  - DOI/arXiv/GitHub 不作为自动 discovery mode

## Hit 数据 Schema

```json
{
  "url": "https://...",
  "title": "...",
  "source_type": "web",
  "snippet": "...",
  "artifact_type_hint": "system_card",
  "confidence": "high",
  "reason": "Official model release page links to system card PDF",
  "query": "\"GPT-5.6\" \"system card\"",
  "primary_source": "true",
  "content_type": "pdf",
  "verification_status": "url_verified"
}
```

## 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `url` | string | url/title 至少一个 | 资源 URL；agent 回填时强烈建议提供 |
| `title` | string | url/title 至少一个 | 资源标题 |
| `doi` | string | 否 | DOI 标识符（如 `10.1234/example`）；强烈建议在已知时填写，可提升去重准确率 |
| `arxiv_id` | string | 否 | arXiv ID（如 `2501.12345`）；强烈建议在已知时填写，可提升去重准确率 |
| `source_type` | string | 否 | 来源类型：`web`, `official_domain`, `manual_url`, `openalex`, `crossref`, `semantic_scholar` |
| `snippet` | string | 否 | 摘要或上下文片段 |
| `artifact_type_hint` | string | 否 | 产物类型提示：`system_card`, `model_card`, `technical_report`, `research_article`, `unknown` |
| `confidence` | string | 否 | 置信度：`high`, `medium`, `low`（默认 `medium`） |
| `reason` | string | 否 | 命中原因说明，必须能解释为什么值得人工审核 |
| `query` | string | 否 | 触发此结果的搜索查询 |
| `primary_source` | string | 否 | 是否 primary source：`true`, `false`, `unknown` |
| `content_type` | string | 否 | 内容类型：`html`, `pdf`, `metadata`, `repo`, `model_card`, `unknown` |
| `verification_status` | string | 否 | 验证状态：`unverified`, `url_verified`, `content_checked`, `failed`, `dup_of_works` |

## 必填验证

- `url` 或 `title` 至少提供一个。
- 两者都缺失时回填失败，不创建 hit。
- title-only hit 可以进入 `discovery_hits`，但不能批量 accept；人工应补 URL 或拒绝。

## 去重规则

- 同一 `run_id` + `dedup_key` 不重复创建。
- `dedup_key` 生成规则（优先级从高到低）：
  - `arxiv:{arxiv_id}`，如果提供了 arxiv_id。
  - `doi:{doi}`，如果提供了 doi。
  - `url:{canonical_url}`，如果有 URL。
  - `title:{lowercase_stripped_title}`，如果只有 title。
- 重复写入返回已存在的 hit 行，不报错。

### Works 表去重（dup_of_works）

回填命中时，后端会自动通过 `light_gate` 元数据查重检查该 hit 是否已在 `works` 表中存在（通过 arxiv_id / doi 强键匹配，或 title 高度相似 Jaccard>=0.9）。若匹配，`verification_status` 会自动设为 `dup_of_works`，并把 `dup_of_work_id` 写入 `raw_json`。

**这不会阻止 hit 插入**——hit 仍然会成功创建（status=created），agent 需要知道这个事实。用户在前端审核时应跳过或降级标记为 `dup_of_works` 的 hit，不再重点推荐。

建议 agent 在回填时尽量提供 `doi` 和 `arxiv_id`（即使标题已知），以提升去重准确率。任何查重异常都会静默降级为 `unverified`（不抛异常）。

## Agent 返回格式

```json
[
  {
    "title": "GPT-5.6 System Card",
    "url": "https://example.org/gpt56-system-card.pdf",
    "source_type": "official_domain",
    "snippet": "This system card describes the safety evaluations...",
    "artifact_type_hint": "system_card",
    "confidence": "high",
    "reason": "Official release page links to the system card PDF.",
    "query": "\"GPT-5.6\" \"system card\"",
    "primary_source": "true",
    "content_type": "pdf",
    "verification_status": "url_verified"
  }
]
```

## 回填后处理流程

1. Agent 返回结果，通过 HTTP API 或 `insert_discovery_hit()` 写入 `discovery_hits`。
2. 用户在 `/discovery` 或 CLI `hits --run DR-xxxx` 查看 hits。
3. 用户接受有效命中，或拒绝噪声并写 review note。
4. 被接受的命中自动创建为 `intake_candidates`，状态保持 `resolution='pending'`。
5. 后续走标准 intake 流程：resolve -> review -> promote -> ingest/parse/extract。
6. Agent 完成回填后若**零命中**或**主动放弃**，应调用 `POST /api/discovery/runs/{run_id}/complete`（`{"status":"failed","error":"..."}`）；正常回填有命中时后端自动置 `succeeded`，无需再调。

## batch_accept_hits 行为

- 没有 URL 的 title-only hit 不能批量接受，会进入 `failed`。
- 不存在的 hit 会进入 `failed`。
- 已接受且已有 `candidate_id` 的 hit 会以 `already_accepted` 返回。
- 返回 `{"accepted": [...], "failed": [...]}`。

## CLI 命令参考

| 命令 | 说明 | 示例 |
|------|------|------|
| `plan` | 生成搜索方案（单模式），不执行 | `plan --name "GPT-5.6 system card"` |
| `composite-plan` | **[V1.2]** 生成 composite 多信号组合搜索方案 | 见下方 Composite 使用示例 |
| `run` | 创建 discovery run | `run --mode name --input '{...}'` |
| `runs` | 列出 discovery runs | `runs --status planned` |
| `hits` | 列出 run 的命中 | `hits --run DR-xxxx` |
| `accept` | 接受命中到 intake | `accept --hits DH-1,DH-2` |
| `reject` | 拒绝单个命中 | `reject --hit DH-1 --note "not relevant"` |

### composite-plan 完整示例

```bash
# 综合多种线索生成检索方案
python scripts/literature_discovery.py plan --composite \
  --names '["Claude 4", "Anthropic"]' \
  --titles '["model card", "safety report"]' \
  --authors '["Dario Amodei"]' \
  --institutions '["Anthropic"]' \
  --keywords '["AI safety", "evaluation", "benchmark"]' \
  --preferred-domains '["anthropic.com", "arxiv.org"]' \
  --exclude-terms '["blog", "press release"]' \
  --artifact-type-hint system_card \
  --max-results 20 \
  --freeform-note "寻找 Claude 4 的正式系统卡和安全评估报告"
```

## V1.2 不支持的模式

以下输入模式在 V1.2 不受支持，API/CLI 会给出明确错误提示：

| 输入 | 替代方案 |
|------|---------|
| `doi` | V1.1 不支持 DOI discovery；可先按 title/name 检索，或等待 V1.2 DOI 反查 |
| `arxiv` | `python scripts/literature_intake.py collect --ids <ID>` |
| `github_url` | `python scripts/literature_intake.py collect --github <URL>` |
