---
angle: digest
version: 1
kind: digest
input: head:12000
language: zh
---

## 目的

本模板用于生成文献速览卡片（digest），作为三层阅读体系的第一层。digest 回答"这篇文献在讲什么"的核心问题，为分类审核提供快速上下文，为后续定向阅读提供子集筛选依据。每篇文献只跑一次 digest，除非 content.md 本身被替换。

## 问题清单

1. **一句话定位**：这是一篇什么文献、解决什么问题？（中文，≤50字）
2. **TL;DR**：3-5 条要点，概括文献核心内容（中文）。
3. **文献角色**：该文献在学术对话中扮演什么角色？从以下选项中选择一个：
   - 提出框架：提出新的概念框架、分类体系或理论模型
   - 报告评测结果：报告实验、评测或基准测试的结果
   - 披露系统信息：披露模型/系统的技术细节、能力边界或安全措施
   - 综述：系统性回顾和总结某一领域的现有工作
   - 立场论证：就某一议题提出明确立场并进行论证
   - 其他：不属于以上任何一类
4. **核心产出物**：文献中提出或使用的核心产出物名称（框架名/benchmark名/模型名/标准名等具体指称）。
5. **与自主性安全的相关度**：评估该文献与 AI 自主性安全（autonomy safety）研究方向的相关程度。
   - 相关度：high / medium / low
   - 理由：一句话说明判断依据
6. **建议阅读优先级**：基于与自主性安全的相关度和文献质量，建议的阅读优先级与理由（供人参考，不自动写入 works.priority）。

## 输出要求

- 只输出一个 JSON 对象，符合下方 Schema，不输出解释性正文。
- 每个实质性回答必须附 evidence：原文片段（≤300字）+ 大致位置（章节名或前/中/后部）。
- 文中未涉及的问题，对应字段置 null 并在 not_addressed_fields 中列出；禁止臆测。
- 整体置信度 confidence: high/medium/low；low 时在 confidence_note 说明原因。
- 禁止猜测 content.md 中未出现的信息。

## 幻觉防护规则

1. **evidence 必填**：每个实质判断（非 null 字段）必须有 evidence 支撑，包含 quote（原文引用）和 location（位置描述）。
2. **未涉及即 null**：文中未涉及的内容必须写 null，并在 not_addressed_fields 数组中列出字段名。
3. **禁止臆测**：不得基于外部知识或推测填充字段；只能使用 content.md 中明确出现的信息。
4. **confidence 解释**：当 confidence 为 low 时，必须在 confidence_note 中说明原因（如：内容截断、关键信息缺失、表述模糊等）。
5. **quote 校验**：evidence.quote 必须是 content.md 中实际存在的文本片段，不得编造或改写。

## 输出 Schema

```json
{
  "angle": "digest",
  "template_version": 1,
  "work_id": "",
  "not_addressed": false,
  "not_addressed_fields": [],
  "confidence": "high",
  "confidence_note": "",
  "fields": {
    "one_sentence_positioning": {
      "value": "",
      "evidence": {
        "quote": "",
        "location": ""
      }
    },
    "tldr": {
      "value": [],
      "evidence": {
        "quote": "",
        "location": ""
      }
    },
    "literature_role": {
      "value": "",
      "evidence": {
        "quote": "",
        "location": ""
      }
    },
    "core_artifacts": {
      "value": [],
      "evidence": {
        "quote": "",
        "location": ""
      }
    },
    "relevance_to_autonomy_safety": {
      "value": {
        "level": "",
        "reason": ""
      },
      "evidence": {
        "quote": "",
        "location": ""
      }
    },
    "suggested_reading_priority": {
      "value": {
        "priority": "",
        "reason": ""
      },
      "evidence": {
        "quote": "",
        "location": ""
      }
    }
  },
  "open_questions": []
}
```

### 字段说明

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `one_sentence_positioning.value` | string | ≤50字中文 | 一句话定位文献的核心内容和贡献 |
| `tldr.value` | string[] | 3-5条 | 文献要点概括 |
| `literature_role.value` | enum | 6选1 | 文献在学术对话中的角色 |
| `core_artifacts.value` | string[] | 可为空数组 | 文献中提出或使用的核心产出物名称 |
| `relevance_to_autonomy_safety.value.level` | enum | high/medium/low | 与自主性安全的相关度 |
| `relevance_to_autonomy_safety.value.reason` | string | 非空 | 相关度判断理由 |
| `suggested_reading_priority.value.priority` | string | 如 high/medium/low | 建议的阅读优先级 |
| `suggested_reading_priority.value.reason` | string | 非空 | 优先级判断理由 |
| `open_questions` | string[] | 可为空数组 | 执行中发现的、模板未覆盖但值得问的问题 |

### 公共信封字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `angle` | string | 固定为 "digest" |
| `template_version` | integer | 固定为 1 |
| `work_id` | string | 文献 ID，格式如 W-arxiv-xxxx |
| `not_addressed` | boolean | 该文献对 digest 角度整体是否无话可说 |
| `not_addressed_fields` | string[] | 文中未涉及的字段名列表 |
| `confidence` | enum | 整体置信度：high/medium/low |
| `confidence_note` | string | 置信度说明，low 时必填 |
| `fields` | object | 包含上述 6 个字段的结构化数据 |
| `open_questions` | string[] | 模板生长机制的输入 |

### Evidence 结构

每个字段的 evidence 包含：

```json
{
  "quote": "原文引用片段，≤300字",
  "location": "位置描述，如：摘要、第3节、结论、前部"
}
```

## 使用说明

1. **输入**：work 的 content.md 前 12000 字符（head:12000）
2. **输出**：符合上述 Schema 的 JSON 对象
3. **落点**：`_analysis_outbox/digest/{work_id}.json`
4. **审核**：digest 层不设审核流程，错误在使用时发现后标 needs_fix 触发重跑
5. **原则**：每篇文献只跑一次，除非 content.md 被替换（重新解析）
