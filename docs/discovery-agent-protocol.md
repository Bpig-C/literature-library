# Discovery Agent Backfill Protocol

V1.1 受约束广泛发现与检索方案 — Agent 回填协议

## 概述

本文档定义了外部 agent 向 discovery run 回填命中结果的协议。agent 通过 HTTP API、Python core 或 CLI 将搜索结果写入 `discovery_hits` 表，然后由人工审核并接受为 intake candidate。

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
    "reason": "..."
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
)
```

### CLI 方式

```bash
# 创建 run
python scripts/literature_discovery.py run \
  --mode name \
  --input '{"name": "GPT-5.6 system card", "artifact_type_hint": "system_card"}'

# 查看 hits
python scripts/literature_discovery.py hits --run DR-xxxx

# 接受 hits
python scripts/literature_discovery.py accept --hits DH-1,DH-2

# 拒绝 hit
python scripts/literature_discovery.py reject --hit DH-1 --note "not relevant"
```

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
| `url` | string | url/title 至少一个 | 资源 URL |
| `title` | string | url/title 至少一个 | 资源标题 |
| `source_type` | string | 否 | 来源类型：`web`, `official_domain`, `manual_url`, `openalex`, `crossref`, `semantic_scholar` |
| `snippet` | string | 否 | 摘要或上下文片段 |
| `artifact_type_hint` | string | 否 | 产物类型提示：`system_card`, `model_card`, `technical_report`, `research_article`, `unknown` |
| `confidence` | string | 否 | 置信度：`high`, `medium`, `low`（默认 `medium`） |
| `reason` | string | 否 | 命中原因说明 |
| `query` | string | 否 | 触发此结果的搜索查询 |
| `primary_source` | string | 否 | 是否 primary source：`true`, `false`, `unknown` |
| `content_type` | string | 否 | 内容类型：`html`, `pdf`, `metadata`, `repo`, `model_card`, `unknown` |
| `verification_status` | string | 否 | 验证状态：`unverified`, `url_verified`, `content_checked`, `failed` |

## 必填验证

- `url` 或 `title` 至少提供一个
- 若两者都缺失，回填会失败，不创建 hit

## 去重规则

- 同一 `run_id` + `dedup_key` 不重复创建
- `dedup_key` 生成规则（优先级从高到低）：
  - `url:{canonical_url}` — 如果有 URL
  - `title:{lowercase_stripped_title}` — 如果只有 title
- 重复写入返回已存在的 hit 行（不报错）

## Agent 任务指令模板

```
请执行 discovery search run。

输入：
- mode: {mode}
- {mode_input_key}: {mode_input_value}
- artifact_type_hint: {artifact_type_hint}
- preferred_sources: {preferred_sources}
- max_results: {max_results}

要求：
1. 使用通用 Web 搜索和官方来源优先策略。
2. 不要登录，不要绕过访问控制。
3. 每个结果输出 title/url/source_type/snippet/reason/confidence。
4. 标出是否看起来是 primary source。
5. 不要编造 URL；无法确认则 confidence=low。
6. 返回 JSON 数组。

输出格式：
[
  {
    "title": "...",
    "url": "https://...",
    "source_type": "official_domain",
    "snippet": "...",
    "artifact_type_hint": "system_card",
    "confidence": "high",
    "reason": "Official model release page links to system card PDF",
    "query": "\"GPT-5.6\" \"system card\""
  }
]
```

## Agent 返回格式

```json
[
  {
    "title": "GPT-5.6 System Card",
    "url": "https://openai.com/gpt56-system-card.pdf",
    "source_type": "official_domain",
    "snippet": "This system card describes the safety evaluations...",
    "artifact_type_hint": "system_card",
    "confidence": "high",
    "reason": "Official model release page links to system card PDF",
    "query": "\"GPT-5.6\" \"system card\""
  }
]
```

## 回填后处理流程

1. Agent 返回结果 → 通过 `insert_discovery_hit()` 写入 `discovery_hits`
2. 人工审核 hits（`hits --run DR-xxxx`）
3. 接受有效命中（`accept --hits DH-1,DH-2`）
4. 被接受的命中自动创建为 `intake_candidates`
5. 后续走标准 intake 流程（resolve → ingest）

## batch_accept_hits 行为

- 没有 URL 的 title-only hit 不能批量接受，会进入 `failed`
- 不存在的 hit 会进入 `failed`
- 已接受且已有 `candidate_id` 的 hit 会以 `already_accepted` 返回
- 返回 `{"accepted": [...], "failed": [...]}`

## CLI 命令参考

| 命令 | 说明 | 示例 |
|------|------|------|
| `plan` | 生成搜索方案（不执行） | `plan --name "GPT-5.6 system card"` |
| `run` | 创建 discovery run | `run --mode name --input '{...}'` |
| `runs` | 列出 discovery runs | `runs --status planned` |
| `hits` | 列出 run 的命中 | `hits --run DR-xxxx` |
| `accept` | 接受命中到 intake | `accept --hits DH-1,DH-2` |
| `reject` | 拒绝单个命中 | `reject --hit DH-1 --note "not relevant"` |

## V1.1 不支持的模式

以下输入模式在 V1.1 不受支持，CLI 会给出明确错误提示：

| 输入 | 替代方案 |
|------|---------|
| `--doi` | V1.1 不支持 DOI discovery；可先按 title/name 检索，或等待 V1.2 DOI 反查 |
| `--arxiv` | `python scripts/literature_intake.py collect --ids <ID>` |
| `--github-url` | `python scripts/literature_intake.py collect --github <URL>` |
