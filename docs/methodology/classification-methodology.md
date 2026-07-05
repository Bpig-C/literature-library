# 文献库分类方法规范 v0.2.2

> 版本说明：v0.2.2 在 v0.2.1 基础上补齐词汇表与后端 VOCAB 的缺失项，新增变更流程和审核语义说明。
>
> v0.2.2 变更：
> - `artifact_focus` 新增 7 个值：`empirical_finding`、`capability_profile`、`policy_analysis`、`framework_proposal`、`eval_suite`、`theoretical_contribution`、`tool_release`
> - `risk_domain` 新增 9 个值：`jailbreak_resistance`、`self_preservation`、`cyber_offense`、`power_seeking`、`autonomous_replication`、`systemic_risk`、`distributional_risk`、`bio_risk`、`alignment_tax`
> - `method_tags` 新增 7 个值：`empirical_measurement`、`interpretability_analysis`、`framework_design`、`policy_review`、`theoretical_analysis`、`survey_synthesis`、`formal_verification`
> - 新增 §12 分类规范变更流程
> - 新增 §13 审核操作语义
> - 新增 §14 字段实现状态说明（`primary_method_type`、`secondary_doc_type`）
>
> v0.2.1 变更：针对 `primary_doc_type` 互斥性问题进行结构性补丁：新增类型层级与优先级规则，明确功能定位类型优先于文档形态类型；补充 8.16–8.17 两条辨析规则；更新 §9 第二步标注流程。不改动词汇表。
>
> `risk_domain` 词汇版本：v1（随现象本体变化更新，预期低频）
> `method_tags` 词汇版本：v1（随评估实践演进更新，预期高频）
>
> **词汇更新原则**：新增词汇只需在词汇表末尾追加，已有条目的历史标注无需迁移（向后兼容）。只有在已有词汇的**定义需要修改**时，才触发批量迁移并升级对应词汇版本号。

---

## 1. 目的

本分类方法用于统一整理前沿 AI 安全、评估、治理、系统透明度与相关技术文献。它的目标不是简单判断一份材料是不是"论文"或"报告"，而是同时回答以下几个问题：

1. 这份材料作为文献本身是什么形态？
2. 它当前处于什么发布状态？
3. 它由什么类型的机构主导发布？
4. 我们阅读它主要是为了什么？
5. 它主要贡献或讨论了什么对象？
6. 它涉及哪些风险领域、方法类型或治理主题？
7. 它在本地文献库中的处理状态是否可靠？

因此，本分类体系采用：

```text
互斥主字段 + 可重叠标签字段 + 辅助边界字段
```

核心原则是：

```text
身份型字段必须互斥；
用途、主题、贡献、风险和处理问题字段允许重叠。
```

---

## 2. 字段总览

### 2.1 最小推荐字段

```yaml
id:
title:
year:
authors_or_org:
source_actor:
primary_source_actor_type:
primary_doc_type:
publication_status:
reading_lane:
artifact_focus:
ingestion_state:
processing_flags:
priority:
notes:
```

### 2.2 完整推荐字段

```yaml
id:
title:
year:
authors_or_org:
source_actor:
primary_source_actor_type:
additional_actor_types:
region:
primary_doc_type:
secondary_doc_type:
publication_status:
reading_lane:
artifact_focus:
risk_domain:
primary_method_type:
method_tags:
target_model_or_system:
canonical_file_format:
ingestion_state:
processing_flags:
related_doc_id:
relation_type:
is_core_literature:
priority:
local_path:
source_url:
notes:
```

---

# 3. 互斥字段

互斥字段用于建立稳定统计口径。每份文献在这些字段中原则上只能选择一个值。

---

## 3.1 `primary_doc_type`

### 定义

`primary_doc_type` 表示一份材料的主要文献形态或文档身份。

它回答的问题是：

```text
这份材料作为"文献"主要是什么？
```

### 填写规则

* 必填。
* 单选。
* 不用于表示发表状态。
* 不用于表示主题。
* 不用于表示阅读用途。
* 不用于表示发布机构类型。

### 类型层级与优先级

`primary_doc_type` 的选项在语义上分为三层，标注时按层级依次判断：

**第一层：功能定位类型**（优先选用）

```text
system_model_card
governance_framework
standard_guideline
benchmark_dataset_paper
evaluation_report
```

这五种类型有明确的领域功能标识——透明度披露、风险框架、合规规范、工具贡献、第三方评估。只要文档符合其判定准则，优先选用，不再与第二层类型竞争。如果文档同时具备形态层属性（如 evaluation_report 在形态上也是 technical_report），用 `secondary_doc_type` 记录次要属性。

**第二层：文档形态类型**（兜底选用）

```text
technical_report
institutional_report
research_article
survey_review
webpage_blog
thesis
book_chapter
platform_snapshot
other_literature
```

当文档不符合任何第一层类型的判定准则时，从这一层中选择最匹配的形态。

**第三层：存在性标记**（不表示文档形态，不与其他类型竞争）

```text
not_literature
workflow_artifact
```

这两个值表示的是入库资格判断，而非文档形态本身。标注这两种情况时，应以 `ingestion_state: excluded` 为主要信号，`primary_doc_type` 填写对应值作为补充说明，不需要与第一、二层类型比较。

### 可选值

```yaml
primary_doc_type:
  - research_article
  - survey_review
  - technical_report
  - system_model_card
  - evaluation_report
  - standard_guideline
  - governance_framework
  - benchmark_dataset_paper
  - institutional_report
  - webpage_blog
  - platform_snapshot
  - thesis
  - book_chapter
  - workflow_artifact
  - other_literature
  - not_literature
```

### 字段值说明

#### `research_article`

常规研究论文，包括会议论文、期刊论文、工作坊论文、arXiv 预印本论文等。

适用于：

```text
以提出研究问题、方法、实验、论证或实证发现为主的独立研究论文。
```

注意：

```text
arXiv 上的论文不自动等于 preprint 类型；
preprint 应放入 publication_status。
```

示例：

```yaml
primary_doc_type: research_article
publication_status: preprint
```

---

#### `survey_review`

综述、survey、review、position paper、概念性综述或领域评述。

适用于：

```text
主要目的是整理已有研究、提出概念框架、比较观点、总结领域趋势的研究性文章。
```

如果一份文档是机构年度趋势报告，而不是学术综述，应优先考虑 `institutional_report`。

---

#### `technical_report`

技术报告。

适用于：

```text
围绕模型、系统、方法、评测、实验设计、技术实现或性能结果展开的技术性说明文档。
```

常见内容包括：

```yaml
- 模型架构
- 训练数据
- 后训练方法
- benchmark 结果
- safety evaluation
- model capability profile
- 实验设计
- 技术路线
- 误差分析
```

判断口诀：

```text
如果中心问题是"这个模型、方法、系统怎么做，表现如何，安全评测如何"，
优先标为 technical_report。
```

---

#### `system_model_card`

系统卡、模型卡、安全卡、透明度报告等。

适用于：

```text
由模型或系统提供方发布，用于说明模型能力、限制、安全评估、风险缓解、部署边界、透明度信息的文档。
```

包括：

```yaml
- system card
- model card
- safety card
- transparency report
- responsible AI transparency report
```

判断口诀：

```text
如果文档的核心功能是披露一个模型或系统的能力、安全测试、限制和部署信息，
优先标为 system_model_card。
```

---

#### `evaluation_report`

第三方评估报告。

适用于：

```text
由第三方机构（评估实验室、政府机构或研究团队）对特定模型、系统或治理框架实施评估、出具的结构性评估文档。
评估对象是另一机构的系统，结论直接指向被评估对象的风险状态或能力判断。
```

包括：

```yaml
- 评估实验室对特定模型的能力/风险评估报告
- 预部署评估报告
- 方法设计清晰但可复用工具并非主贡献的多模型比较报告
- 政府机构委托或存档的第三方模型评估
- 对安全框架或治理框架的独立外部评估
```

区别于：

```text
technical_report：模型提供方自述，不是第三方评估。
institutional_report：趋势/态势/能力建设类概述，评估对象不是特定模型或系统。
benchmark_dataset_paper：可独立复用的评测工具本身为主贡献。
```

与 `benchmark_dataset_paper` 的判定准则：

```text
将本文档移除后，其描述的评测工具/基准是否作为独立可复用资源继续存在？
若否，则为 evaluation_report；若是，则为 benchmark_dataset_paper。
```

注意：该类型涵盖"针对单一模型的结构性评估"和"方法设计清晰但工具非主贡献的多模型比较报告"。是否覆盖单一或多个模型，不作为判断依据——核心判断标准始终是主要贡献物是什么。

---

#### `standard_guideline`

标准、指南、规范、code of practice、合规指南。

适用于：

```text
由政府、标准机构、行业组织或国际机构发布，目标是提供规范性要求、合规路径、流程指南或标准化要求的文档。
```

包括：

```yaml
- 国家标准
- 国际标准
- NIST 指南
- ISO 相关指南
- EU Code of Practice
- AI assurance guide
- 安全评估指南
```

判断口诀：

```text
如果文档主要告诉别人"应该如何遵守、实施、评估或对齐某套规范"，
优先标为 standard_guideline。
```

---

#### `governance_framework`

治理框架、风险管理框架、安全框架、前沿模型部署框架。

适用于：

```text
企业、研究机构、评估机构或政策机构提出的，用于组织风险识别、能力分级、安全阈值、治理流程或部署决策的框架性文档。
```

包括：

```yaml
- Frontier Safety Framework
- Preparedness Framework
- Responsible Scaling Policy
- Risk Management Framework
- Advanced AI Scaling Framework
- Safety and Security Framework
```

判断口诀：

```text
如果文档主要是在提出一套风险分类、能力层级、部署阈值、治理流程或安全决策框架，
优先标为 governance_framework。
```

---

#### `benchmark_dataset_paper`

主贡献是 benchmark、dataset、evaluation suite 或测试集的论文或报告。

适用于：

```text
文档的主要贡献是构建、发布或验证一个评测基准、数据集、评估套件或排行榜，
且该工具可作为独立可复用资源独立于本文档继续存在。
```

包括：

```yaml
- benchmark paper
- dataset paper
- evaluation suite paper
- leaderboard paper
```

判断口诀：

```text
如果没有这个 benchmark/dataset/eval suite，这篇文献的主要贡献就不存在，
优先标为 benchmark_dataset_paper。
```

注意：

```text
benchmark 也可以作为 artifact_focus；
但如果 benchmark 是主贡献，primary_doc_type 应标为 benchmark_dataset_paper。
```

---

#### `institutional_report`

机构报告、趋势报告、年度报告、生态报告、能力建设报告、综合态势报告。

适用于：

```text
由机构代表自身立场或职能，对领域趋势、政策进展、机构能力、行业状态、年度工作或生态格局进行总结和判断的文档。
```

包括：

```yaml
- annual report
- year in review
- trend report
- landscape report
- capacity report
- institutional update
- external review report
```

判断口诀：

```text
如果中心问题是"这个机构如何判断领域、趋势、治理状态、年度进展或生态格局"，
优先标为 institutional_report。
```

---

#### `webpage_blog`

网页、博客、在线文章、机构新闻稿、HTML 保留件。

适用于：

```text
原始形态是网页或博客文章，且没有明显转化为正式 PDF 报告、论文、标准或系统卡的材料。
```

包括：

```yaml
- 官方博客
- 新闻页
- 在线说明页
- HTML 保留页
- LessWrong / AlignmentForum / Substack 等网页文章
```

注意：

```text
如果网页内容本质上是一篇研究论文或正式报告，且已有正式 PDF，则不标为 webpage_blog。
```

---

#### `platform_snapshot`

排行榜、仪表盘或在线评测平台的快照性文档。

适用于：

```text
某个持续更新的在线平台（排行榜、评分仪表盘、在线评测平台）在某时刻的状态记录。
内容是平台数据或界面的快照，而非报告叙述或研究论文。
```

包括：

```yaml
- leaderboard 打印件或截图
- 安全评分仪表盘 PDF
- 平台能力排行榜保存件
- JS 渲染型平台的截全页图
```

判断口诀：

```text
如果文档的主要内容是"某个平台此刻显示的状态"而非"围绕某个研究问题展开的叙述"，
优先标为 platform_snapshot。
```

---

#### `thesis`

学位论文。

适用于：

```text
博士论文、硕士论文或其他以取得学位为目的提交的完整论文。
```

注意：

```text
即使 thesis 内部包含 article-like chapters，主类型仍然是 thesis。
```

---

#### `book_chapter`

书章、手册章节、编辑书中的章节。

适用于：

```text
文档是某本书、手册、论文集或 edited volume 中的独立章节。
```

---

#### `workflow_artifact`

工作过程材料，不作为正式文献。

适用于：

```text
本地整理、修复、拼接、抽取、缓存、核验、脚本、摘要合并等工作流产物。
```

包括：

```yaml
- 摘要拼接版
- 索引文件
- deepread 缓存
- PDF 修复记录
- 正文抽取记录
- 自动化脚本
- 临时 TXT
- 方法向摘要缓存
```

判断口诀：

```text
如果它服务于文献库维护，而不是作为外部正式文献被引用，
标为 workflow_artifact。
```

---

#### `other_literature`

相关但不适合以上类型的文献。

适用于：

```text
确实与研究相关，但暂时无法纳入已有类型的材料。
```

使用要求：

```text
尽量少用；
使用时必须在 notes 中说明原因。
```

---

#### `not_literature`

误收材料、无关材料、错误下载、首页快照、空白文件、无效文件。

适用于：

```text
不应进入正式文献库的材料。
```

包括：

```yaml
- 下载错误
- 首页快照
- 空白 PDF
- 无关网页
- 重复无效文件
- 截图但无法确认原文
```

---

## 3.2 `publication_status`

### 定义

`publication_status` 表示文档当前的发布状态。

它回答的问题是：

```text
这份材料目前处于什么发布或发表状态？
```

### 填写规则

* 建议必填。
* 单选。
* 不与 `primary_doc_type` 混用。
* `preprint` 不应作为文献类型。

### 可选值

```yaml
publication_status:
  - published
  - preprint
  - working_paper
  - draft
  - living_document
  - institutional_release
  - webpage_release
  - unknown
```

### 字段值说明

#### `published`

已正式发表的论文、正式出版物或正式版本。

适用于：

```yaml
- journal article
- conference paper
- officially published report
- formally released standard
```

---

#### `preprint`

预印本，通常包括 arXiv、SSRN、bioRxiv 等平台发布但未正式发表的文章。

示例：

```yaml
primary_doc_type: research_article
publication_status: preprint
```

或：

```yaml
primary_doc_type: benchmark_dataset_paper
publication_status: preprint
```

---

#### `working_paper`

工作论文、讨论稿、研究草案。

适用于：

```text
作者或机构明确标注为 working paper、discussion paper、preliminary paper 的材料。
```

---

#### `draft`

草案版本。

适用于：

```text
标准草案、指南草案、征求意见稿、初版公开草案。
```

---

#### `living_document`

持续更新文档。

适用于：

```text
版本持续更新、官网持续维护、内容会随政策或模型发布变化的文档。
```

---

#### `institutional_release`

机构正式发布，但不属于传统学术发表的文件。

适用于：

```yaml
- 企业系统卡
- 政府报告
- 标准组织指南
- 安全框架
- 模型卡
- 年度报告
- 第三方评估报告
```

---

#### `webpage_release`

以网页形式发布，且没有清晰正式 PDF 版本的材料。

适用于：

```yaml
- 官方博客
- 在线说明页
- 新闻稿
- HTML 保留件
```

---

#### `unknown`

发布状态不明。

使用要求：

```text
只在无法判断时使用；
后续应优先补全。
```

---

## 3.3 `primary_source_actor_type`

### 定义

`primary_source_actor_type` 表示文档主导发布者的机构类型。

它回答的问题是：

```text
这份文档主要由哪一类主体发布或主导？
```

### 填写规则

* 建议必填。
* 单选。
* 联合发布时，选择主导方（通常为文档归属机构，即发布渠道所属机构）。
* 其他参与方放入 `additional_actor_types`。

### 可选值

```yaml
primary_source_actor_type:
  - frontier_ai_company
  - domestic_ai_company
  - evaluation_lab
  - government_agency
  - standards_body
  - international_network
  - academic_group
  - civil_society_org
  - platform_dashboard
  - unknown
```

### 字段值说明

#### `frontier_ai_company`

前沿 AI 企业。

示例：

```yaml
OpenAI
Anthropic
Google DeepMind
Meta
xAI
Microsoft
```

---

#### `domestic_ai_company`

国内模型厂商或国内 AI 企业。

示例：

```yaml
DeepSeek
Qwen（阿里）
智谱
百度
月之暗面
MiniMax
腾讯
华为
```

---

#### `evaluation_lab`

第三方评估实验室或评估机构。

示例：

```yaml
METR
Apollo Research
Scale AI SEAL
FAR AI
SaferAI
Concordia AI
上海AI-Lab
```

---

#### `government_agency`

国家机构、政府部门、官方研究所。

示例：

```yaml
UK AISI
US NIST
EU AI Office
中国标准相关机构
日本 AISI（IPA）
```

---

#### `standards_body`

标准组织、认证组织、行业标准制定机构。

示例：

```yaml
ISO
NIST 标准项目
MLCommons
CSA
AI Verify Foundation
```

---

#### `international_network`

国际网络、跨国合作组织、国际安全研究网络。

适用于：

```text
多国 AISI 网络、国际联合使命、跨国安全治理网络等。
```

---

#### `academic_group`

大学、研究团队、学术机构。

---

#### `civil_society_org`

非营利组织、倡议组织、政策倡导组织、公益研究机构。

---

#### `platform_dashboard`

平台、排行榜、仪表盘或在线评测平台。

适用于：

```yaml
- leaderboard
- benchmark dashboard
- online risk platform
- evaluation platform
```

---

#### `unknown`

来源主体不明。

---

## 3.4 `canonical_file_format`

### 定义

`canonical_file_format` 表示本地保留文件的主要格式。

### 填写规则

* 单选。
* 只描述本地文件格式。
* 不描述文件质量问题。

### 可选值

```yaml
canonical_file_format:
  - pdf_native
  - pdf_printed
  - html
  - markdown
  - png
  - txt
  - mixed
  - unknown
```

### 字段值说明

#### `pdf_native`

原生 PDF，例如 arXiv、官方 CDN、机构官网直接提供的 PDF。

#### `pdf_printed`

由网页打印或浏览器渲染生成的 PDF。

#### `html`

保留的 HTML 原文。

#### `markdown`

Markdown 原文。

#### `png`

截图或图片保留件。

#### `txt`

纯文本抽取、缓存或核验文本。

#### `mixed`

同一条记录对应多个混合格式文件。

#### `unknown`

格式不明。

---

## 3.5 `ingestion_state`

### 定义

`ingestion_state` 表示该条目是否可以作为正式文献进入库中。

### 填写规则

* 必填。
* 单选。
* 只表示入库状态。
* 具体问题放入 `processing_flags`。

### 可选值

```yaml
ingestion_state:
  - verified
  - needs_review
  - provisional
  - excluded
  - deprecated
```

### 字段值说明

#### `verified`

已核验，可以作为正式文献使用。

#### `needs_review`

需要人工复核。

适用于：

```yaml
- 来源不确定
- 标题不确定
- 是否原文不确定
- 下载质量可疑
- 正文无法抽取
```

#### `provisional`

暂时保留，尚未完全确认。

适用于：

```text
可能有用，但目前没有足够信息确认其正式文献身份。
```

#### `excluded`

排除出正式文献库。

适用于：

```yaml
- 无关材料
- 首页快照
- 错误下载
- 空白文件
- 明显重复且无保留价值
```

#### `deprecated`

旧版本或已被新版本替代。

适用于：

```text
保留用于版本追踪，但不作为当前主版本。
```

---

## 3.6 `priority`

### 定义

`priority` 表示当前阅读、整理或处理优先级。

### 填写规则

* 单选。
* 可随项目进展更新。

### 可选值

```yaml
priority:
  - P0
  - P1
  - P2
  - P3
  - archive
```

### 字段值说明

#### `P0`

核心必读，当前研究直接依赖。

#### `P1`

重要文献，建议系统阅读。

#### `P2`

有参考价值，按主题需要阅读。

#### `P3`

边缘材料，低优先级。

#### `archive`

归档保留，不进入当前阅读计划。

---

## 3.7 `is_core_literature`

### 定义

`is_core_literature` 表示该条目是否属于核心文献。

### 填写规则

* 布尔值。
* 与 `priority` 配合使用。
* 不替代 `primary_doc_type`。

### 可选值

```yaml
is_core_literature: true
is_core_literature: false
```

---

# 4. 可重叠字段

可重叠字段用于表达复杂用途、主题、对象和方法。每份文献可以选择多个值。

---

## 4.1 `reading_lane`

### 定义

`reading_lane` 表示我们阅读这份文献的主要用途。

它回答的问题是：

```text
我们为什么要读这份文献？
```

### 填写规则

* 多选。
* 是最重要的研究用途字段。
* 不等同于文献形态。
* 不等同于贡献对象。

### 可选值

```yaml
reading_lane:
  - framework_taxonomy
  - evaluation_method
  - governance_method
  - system_transparency
  - model_technical_profile
  - institutional_landscape
  - safety_case_method
  - interpretability_method
  - background_theory
  - literature_mapping
  - workflow_support
```

### 字段值说明

#### `framework_taxonomy`

用于研究框架、分类法、风险分类、能力层级、概念结构。

适用于：

```yaml
- 风险分类体系
- 能力分级
- 危险能力 taxonomy
- 治理框架结构
- AI safety framework comparison
```

---

#### `evaluation_method`

用于研究评测方法、实验设计、benchmark、eval suite、red teaming、auditing，以及阅读具体评估结论。

适用于：

```yaml
- benchmark construction
- safety evaluation
- pre-deployment evaluation
- model behavior evaluation
- red teaming
- capability evaluation
- 第三方评估报告的发现与结论
```

注意：`evaluation_method` 同时覆盖"构建评测工具"和"实施评测并出具结论"两类用途。若需区分，通过 `method_tags` 中的 `benchmark_construction` 与 `evaluation_execution` 进一步标注。

---

#### `governance_method`

用于研究治理机制、监管方法、风险管理流程、合规路径、责任分配。

适用于：

```yaml
- risk management
- deployment decision process
- governance mechanism
- policy compliance
- institutional responsibility
```

---

#### `system_transparency`

用于研究系统卡、模型卡、安全卡、透明度披露方式。

适用于：

```yaml
- system card analysis
- model card comparison
- safety disclosure
- transparency report
```

---

#### `model_technical_profile`

用于了解模型能力、训练、架构、数据、部署和技术特征。

适用于：

```yaml
- model technical report
- capability profile
- training method
- post-training method
```

---

#### `institutional_landscape`

用于了解机构生态、年度趋势、政策格局、国际网络、评估组织分布。

适用于：

```yaml
- trend report
- year in review
- landscape report
- institutional capacity report
```

---

#### `safety_case_method`

用于研究 safety case、安全论证、证据链、部署前证明结构，以及无法执行某类行为的论证（inability safety case）。

适用于：

```yaml
- safety case
- assurance case
- pre-deployment evidence
- structured safety argument
- inability safety case
```

---

#### `interpretability_method`

用于研究可解释性、机制可解释、monitorability、内部表征分析。

适用于：

```yaml
- mechanistic interpretability
- monitorability
- chain-of-thought monitoring
- activation analysis
- SAE（稀疏自编码器）
```

---

#### `background_theory`

用于概念背景、理论基础、问题定义、position paper。

---

#### `literature_mapping`

用于综述、索引、文献地图、研究路线规划。

---

#### `workflow_support`

用于支持本地整理、摘要、抽取、修复或工作流程。

通常与：

```yaml
primary_doc_type: workflow_artifact
```

搭配使用。

---

## 4.2 `artifact_focus`

### 定义

`artifact_focus` 表示文献主要贡献或讨论的对象。

它回答的问题是：

```text
这份材料主要讨论、提出、评估或发布了什么？
```

### 填写规则

* 多选。
* 可与 `primary_doc_type` 重叠，但功能不同。
* 用于表达主题和贡献对象。

### 可选值

```yaml
artifact_focus:
  - framework
  - taxonomy
  - evaluation_framework
  - benchmark
  - dataset
  - evaluation_suite
  - metric
  - model
  - system_card
  - model_card
  - safety_report
  - transparency_report
  - safety_case_argument
  - risk_update
  - interpretability_finding
  - audit_finding
  - standard
  - guideline
  - governance
  - policy
  - risk_management
  - audit
  - red_teaming
  - safety_case
  - transparency
  - monitorability
  - interpretability
  - leaderboard
  - platform
  - trend
  - literature_index
  - workflow_cache
  # ── 实证与分析类（v0.2.2 新增）──
  - empirical_finding          # 实证发现（量化/实验结果）
  - risk_assessment            # 风险评估（对特定对象的风险分析结论）
  - capability_profile         # 能力画像（模型能力特征描述）
  - policy_analysis            # 政策分析（对政策文本的结构化分析）
  - framework_proposal         # 框架提案（提出新框架但未完整实现）
  - eval_suite                 # 评测套件（evaluation_suite 的别名，用于 LLM 输出兼容）
  - theoretical_contribution   # 理论贡献（形式化/数学/概念性贡献）
  - tool_release               # 工具发布（开源工具、库、平台）
```

### 说明

`evaluation_framework`：评估框架，区别于治理框架（`framework`）。指专门用于组织评估流程、评估标准或评估体系结构的框架。

`safety_case_argument`：安全论证文档，特指以结构化方式论证模型不具备某类危险能力或倾向的文档（如 inability safety case）。

`risk_update`：系统卡或框架发布后出具的专项风险再评估报告。

`interpretability_finding`：可解释性研究的具体发现，包括白盒探针、SAE 分析、因果特征等研究结果。

`audit_finding`：外部审计结论，特指对另一机构安全论证或评估结果的独立外部审查发现。

示例一：

```yaml
primary_doc_type: benchmark_dataset_paper
artifact_focus:
  - benchmark
  - dataset
  - evaluation_suite
```

示例二：

```yaml
primary_doc_type: system_model_card
artifact_focus:
  - model
  - system_card
  - safety_report
  - transparency
  - evaluation_suite
```

示例三：

```yaml
primary_doc_type: governance_framework
artifact_focus:
  - framework
  - risk_management
  - governance
  - evaluation_framework
```

示例四：

```yaml
primary_doc_type: evaluation_report
artifact_focus:
  - safety_case_argument
  - audit_finding
```

---

## 4.3 `risk_domain`

### 定义

`risk_domain` 表示文献涉及的风险领域或现象类别。

它回答的问题是：

```text
这份材料研究的是哪类风险或失控现象？
```

### 填写规则

* 多选。
* 本体论标签，关心"研究对象是什么现象"，而非"用了什么方法"（方法放 `method_tags`）。
* 不要求每篇都填；只在风险领域明确时填写。
* 词汇更新原则：随现象本体演进而扩充，预期低频；新增词汇追加到末尾，向后兼容，已有标注无需迁移。

### 可选值

```yaml
risk_domain:
  # ── 信息操控与欺骗类 ──
  - deception               # 广义欺骗（不限于输出层）
  - scheming                # 谋算（工具性顺从 + 延迟行动）
  - sandbagging             # 能力隐藏 / 沙袋
  - evaluation_awareness    # 评估意识与行为切换
  - information_concealment # 信息遮蔽（CoT 不忠实、未言明评估意识等）
  - persuasion              # 影响操纵与说服
  - misinformation          # 错误信息生成与传播

  # ── 自主失控类 ──
  - autonomy                # 自主性（宽泛兜底，优先使用以下子类）
  - self_replication        # 自复制与持久化
  - resource_acquisition    # 超授权资源获取
  - goal_preservation       # 目标守护与自我保存
  - covert_action           # 隐蔽行动（含 covert/deferred subversion）
  - oversight_subversion    # 监控机制规避与破坏
  - autonomous_ai_rnd       # 自主 AI 研发与自我改进
  - multi_agent_collusion   # 多智能体串谋
  - sabotage                # 破坏性行为

  # ── 危害能力类 ──
  - cybersecurity           # 网络安全
  - biosecurity             # 生物安全
  - chemical_security       # 化学安全
  - dual_use                # 双重用途
  - catastrophic_risk       # 灾难性风险（跨领域）
  - misuse                  # 滥用（用户驱动的危害）

  # ── 治理与合规类 ──
  - governance_risk         # 治理失效风险
  - model_behavior          # 模型行为（广泛的行为偏差）

  # ── 伦理与社会类 ──
  - privacy                 # 隐私
  - fairness                # 公平性
  - robustness              # 鲁棒性
  - safety_case_validity    # 安全论证有效性

  # ── 对齐与安全验证类（v0.2.2 新增）──
  - jailbreak_resistance    # 越狱抵抗（对抗性攻击防御能力）
  - alignment_tax           # 对齐税（对齐导致的能力/效率损失）

  # ── 失控现象扩展类（v0.2.2 新增）──
  - self_preservation        # 自我保护（goal_preservation 的行为层表现）
  - cyber_offense            # 网络攻击（cybersecurity 的进攻面向）
  - power_seeking            # 权力寻求（获取更多资源/权限的倾向）
  - autonomous_replication   # 自主复制（self_replication 的强化版，含环境适应）

  # ── 系统性风险类（v0.2.2 新增）──
  - systemic_risk            # 系统性风险（跨领域、跨模型的全局风险）
  - distributional_risk      # 分布性风险（训练数据/部署分布导致的风险）
  - bio_risk                 # 生物风险（biosecurity 的量化/具体化场景）

  - unknown
```

### 关于 `autonomy` 的兜底用法

当可以精确归入 `self_replication`、`resource_acquisition`、`goal_preservation`、`covert_action`、`oversight_subversion`、`autonomous_ai_rnd`、`multi_agent_collusion` 等子类时，优先使用子类标签。`autonomy` 仅用于涉及自主性问题但无法精确归类的宽泛情形，或用于跨多个子类的综合性文献。

---

## 4.4 `primary_method_type` 与 `method_tags`

### 定义

`risk_domain` 是本体论标签，回答"研究对象是哪类风险/现象"；`method_tags` 是程序论标签，回答"用哪些研究手段"。两者语义轴根本不同，独立使用，可以自由组合：同一文献可以研究沙袋风险（`risk_domain: sandbagging`），同时使用白盒探针和 benchmark 构建两种方法（`method_tags: [white_box_probing, benchmark_construction]`）。

方法类型拆为：

```yaml
primary_method_type:   # 主要方法，单选
method_tags:           # 其他方法标签，多选
```

词汇更新原则：随评估实践演进而扩充，预期高频；新增词汇追加到末尾，向后兼容，已有标注无需迁移。

### `primary_method_type` 可选值

```yaml
primary_method_type:
  - benchmark_construction
  - capability_evaluation
  - risk_assessment
  - red_teaming
  - auditing
  - safety_case
  - model_card_analysis
  - policy_mapping
  - taxonomy_building
  - standard_comparison
  - empirical_experiment
  - case_study
  - literature_review
  - conceptual_analysis
  - workflow_processing
  - unknown
```

### `method_tags` 可选值

```yaml
method_tags:
  # ── 评测工具构建类 ──
  - benchmark_construction       # 构建可复用评测基准
  - dataset_curation             # 数据集整理与构建
  - evaluation_protocol          # 描述了可重复的评估流程设计，但工具非主贡献

  # ── 评估实施类 ──
  - evaluation_execution         # 对特定对象实施评估（区别于构建工具）
  - pre_deployment_evaluation    # 专指部署前的能力/风险评估
  - multi_model_comparison       # 以多模型横向对比为核心分析结构
  - capability_evaluation        # 能力评估
  - risk_assessment              # 风险评估
  - red_teaming                  # 红队测试
  - auditing                     # 审计
  - external_audit               # 对另一机构的安全论证实施独立外部审查

  # ── 失控现象专项检测类 ──
  - sandbagging_detection        # 能力隐藏 / 沙袋检测
  - elicitation                  # 能力引出（与 sandbagging_detection 配合，目标不同）
  - evaluation_awareness_testing # 评估意识测量
  - reward_hacking_detection     # 奖励黑客 / 指标操纵检测
  - cross_modality_consistency   # 跨场景（如文本 vs 工具调用）行为一致性测试
  - agentic_behavior_audit       # Agent 行动序列审计
  - multi_agent_sandbox          # 多智能体沙箱实验

  # ── 机制与可解释性类 ──
  - white_box_probing            # 激活探针 / SAE 等白盒分析手段
  - safety_case_construction     # 安全论证构建（inability safety case 等）

  # ── 分析综合类 ──
  - safety_case                  # 安全论证（广义）
  - model_card_analysis          # 模型卡 / 系统卡分析
  - policy_mapping               # 政策映射
  - taxonomy_building            # 分类法构建
  - standard_comparison          # 标准比较
  - empirical_experiment         # 实证实验
  - case_study                   # 案例研究
  - expert_elicitation           # 专家访谈 / 征询
  - leaderboard_comparison       # 排行榜横向比较

  # ── 文献库工作类 ──
  - text_extraction              # 正文抽取
  - document_repair              # 文档修复
  - summary_synthesis            # 摘要综合

  # ── 测量与验证类（v0.2.2 新增）──
  - empirical_measurement        # 实证测量（侧重量化指标采集，区别于 empirical_experiment）
  - formal_verification          # 形式化验证（数学证明、模型检查等）

  # ── 分析与设计类（v0.2.2 新增）──
  - interpretability_analysis    # 可解释性分析（广义，含 mechanistic/behavioral）
  - framework_design             # 框架设计（提出新框架，区别于 framework_analysis）
  - policy_review                # 政策评述（对政策文本的分析评价）
  - theoretical_analysis         # 理论分析（形式化/数学/逻辑论证）
  - survey_synthesis             # 综述综合（系统性文献综述方法）
```

### 示例

```yaml
primary_method_type: capability_evaluation
method_tags:
  - benchmark_construction
  - risk_assessment
  - red_teaming
  - multi_model_comparison
```

```yaml
primary_method_type: empirical_experiment
method_tags:
  - evaluation_awareness_testing
  - white_box_probing
  - sandbagging_detection
```

```yaml
primary_method_type: auditing
method_tags:
  - external_audit
  - safety_case_construction
```

---

## 4.5 `additional_actor_types`

### 定义

`additional_actor_types` 表示除主导发布者之外，参与文档生产、评估、合作或引用较重的其他主体类型。

### 填写规则

* 多选。
* 与 `primary_source_actor_type` 配合使用。
* 联合评估或合作报告中尤其有用。

### 可选值

与 `primary_source_actor_type` 相同：

```yaml
additional_actor_types:
  - frontier_ai_company
  - domestic_ai_company
  - evaluation_lab
  - government_agency
  - standards_body
  - international_network
  - academic_group
  - civil_society_org
  - platform_dashboard
```

### 联合评估场景填写指引

涉及多机构的常见场景，按以下约定处理：

**场景一：A 机构评估 B 机构的模型**（例如评估实验室评估前沿企业模型）

```yaml
primary_source_actor_type: evaluation_lab    # 发布方（A）
# 被评估方（B）不计入 actor_type
# 被评估模型通过 target_model_or_system 字段记录
```

**场景二：政府机构委托或存档第三方评估**（例如 NIST 存档的预部署评估，实际执行方为另一机构）

```yaml
primary_source_actor_type: government_agency
additional_actor_types:
  - evaluation_lab        # 实际评估执行机构
```

**场景三：主导机构明确的多机构合作研究**（例如 UK AISI 主导、FAR.AI 与前沿企业参与的合作研究）

```yaml
primary_source_actor_type: government_agency  # 主导发布机构
additional_actor_types:
  - evaluation_lab        # FAR.AI 等参与机构
  - frontier_ai_company   # 前沿企业参与方
```

**场景四：两家前沿企业的联合评估**（例如 Anthropic 发布对 OpenAI 模型的对齐评估）

```yaml
primary_source_actor_type: frontier_ai_company  # 发布文档的机构（Anthropic）
# 被评估方（OpenAI）不计入 actor_type，通过 target_model_or_system 记录
```

---

## 4.6 `target_model_or_system`

### 定义

文献涉及的具体模型、系统、平台或评估对象。

### 填写规则

* 多选。
* 可自由文本。
* 用于后续按模型或系统检索。

### 示例

```yaml
target_model_or_system:
  - GPT-5
  - Claude 4
  - Gemini 2.5
  - DeepSeek-R1
  - Qwen3
  - Grok 4
```

---

## 4.7 `region`

### 定义

`region` 表示主导发布机构所属的地区或国家。

### 填写规则

* 单选或多选（多国联合时可多选）。
* 填写**主导发布机构**所属地区，而非研究对象的地区。
* 国际网络或多国联合发布时填 `international`；`additional_actor_types` 中可额外通过 `notes` 注明具体国家机构。

### 可选值

```yaml
region:
  - US            # 美国
  - UK            # 英国
  - EU            # 欧盟
  - CN            # 中国大陆
  - JP            # 日本
  - KR            # 韩国
  - SG            # 新加坡
  - international # 多国联合 / 国际网络
  - unknown
```

---

## 4.8 `processing_flags`

### 定义

`processing_flags` 表示文件处理、下载、抽取、格式转换、重复性或原文可靠性方面的问题。

### 填写规则

* 多选。
* 不表示是否入库。
* 与 `ingestion_state` 配合使用。

### 可选值

```yaml
processing_flags:
  - needs_pdf_conversion
  - html_retained
  - screenshot_only
  - homepage_snapshot_problem
  - not_original_document
  - text_extraction_failed
  - text_extraction_fixed
  - duplicate_candidate
  - duplicate_confirmed
  - cache_only
  - repair_workspace
  - source_url_uncertain
  - source_url_dead
  - manually_verified
  - needs_relocation
  - deprecated_version
```

### 字段值说明

#### `needs_pdf_conversion`

HTML 或网页材料需要后续转为 PDF。

#### `html_retained`

保留 HTML 原文。

#### `screenshot_only`

仅有截图或 PNG，缺少可抽取文本。

#### `homepage_snapshot_problem`

下载到的是机构首页或页面快照，而不是目标文档原文。

#### `not_original_document`

不是正式原文。

#### `text_extraction_failed`

正文无法抽取或抽取失败。

#### `text_extraction_fixed`

正文抽取问题已修复。

#### `duplicate_candidate`

疑似重复文件。

#### `duplicate_confirmed`

确认重复。

#### `cache_only`

仅为缓存材料，不作为正式文献。

#### `repair_workspace`

属于修复工作区材料。

#### `source_url_uncertain`

来源 URL 不确定。

#### `source_url_dead`

来源 URL 已失效。

#### `manually_verified`

已经人工核验。

#### `needs_relocation`

需要移动至正式目录或隔离目录。

#### `deprecated_version`

旧版本，被新版本替代。

---

# 5. 关联字段

关联字段用于记录文档之间的结构性关系，属于可选字段。

---

## 5.1 `related_doc_id`

### 定义

记录与本条目在内容上具有结构性关联的其他文献的 ID。

### 填写规则

* 可选，多值。
* 须配合 `relation_type` 说明关联性质。
* 凡 `secondary_doc_type` 标注 `addendum`、`risk_update`、`appendix` 者，必须填写本字段。

### 示例

```yaml
related_doc_id:
  - I4g
relation_type: parent    # 本文档是 I4g 的子件（风险更新）
```

---

## 5.2 `relation_type`

### 定义

描述本条目与 `related_doc_id` 所指文档之间的关系类型。

### 可选值

```yaml
relation_type:
  - parent      # 本文档是子件（附件、增补件、风险更新），关联文档是主体
  - child       # 本文档是主体，关联文档是子件
  - supersedes  # 本文档替代关联文档（新版本替代旧版本）
  - version_of  # 本文档是关联文档的某一版本
  - companion   # 并列伴随关系（联合评估报告的两个独立文件等）
```

---

# 6. 字段组合规则

## 6.1 主字段与标签字段的关系

推荐理解为：

```text
primary_doc_type           → 它是什么
publication_status         → 它发布到什么状态
primary_source_actor_type  → 谁主导发布
region                     → 主导发布机构所属地区
reading_lane               → 我们为什么读它
artifact_focus             → 它贡献或讨论什么
risk_domain                → 它涉及什么风险现象（本体论）
primary_method_type        → 它主要用了什么方法（程序论）
method_tags                → 它还涉及哪些方法（程序论）
ingestion_state            → 它能否进入正式库
processing_flags           → 它有哪些处理问题
related_doc_id             → 它与哪些文献有结构性关联
relation_type              → 关联关系的性质
```

---

## 6.2 最小标注示例

### 示例 1：benchmark 论文

```yaml
id: E11
title: WMDP Benchmark
primary_doc_type: benchmark_dataset_paper
publication_status: preprint
primary_source_actor_type: evaluation_lab
region: US
reading_lane:
  - evaluation_method
artifact_focus:
  - benchmark
  - dataset
  - evaluation_suite
risk_domain:
  - biosecurity
  - cybersecurity
  - chemical_security
primary_method_type: benchmark_construction
method_tags:
  - benchmark_construction
  - multi_model_comparison
ingestion_state: verified
processing_flags:
  - manually_verified
priority: P1
```

---

### 示例 2：前沿安全框架

```yaml
id: I6b
title: Frontier Safety Framework v3.1
primary_doc_type: governance_framework
publication_status: institutional_release
primary_source_actor_type: frontier_ai_company
region: UK
reading_lane:
  - framework_taxonomy
  - governance_method
  - safety_case_method
artifact_focus:
  - framework
  - risk_management
  - governance
  - evaluation_framework
ingestion_state: verified
priority: P0
```

---

### 示例 3：NIST 指南

```yaml
id: G6
title: NIST AI 600-1
primary_doc_type: standard_guideline
publication_status: institutional_release
primary_source_actor_type: government_agency
region: US
reading_lane:
  - governance_method
  - framework_taxonomy
artifact_focus:
  - standard
  - guideline
  - risk_management
ingestion_state: verified
priority: P1
```

---

### 示例 4：系统卡

```yaml
id: I4g
title: Claude Mythos Preview System Card
primary_doc_type: system_model_card
publication_status: institutional_release
primary_source_actor_type: frontier_ai_company
region: US
reading_lane:
  - system_transparency
  - evaluation_method
  - governance_method
artifact_focus:
  - system_card
  - model
  - safety_report
  - transparency
  - evaluation_suite
ingestion_state: verified
priority: P0
```

---

### 示例 5：国内模型技术报告

```yaml
id: C1
title: DeepSeek-R1 Technical Report
primary_doc_type: technical_report
publication_status: preprint
primary_source_actor_type: domestic_ai_company
region: CN
reading_lane:
  - model_technical_profile
  - evaluation_method
artifact_focus:
  - model
  - evaluation_suite
  - safety_report
ingestion_state: verified
priority: P1
```

---

### 示例 6：机构趋势报告

```yaml
id: G2
title: Frontier AI Trends 2025
primary_doc_type: institutional_report
publication_status: institutional_release
primary_source_actor_type: government_agency
region: UK
reading_lane:
  - institutional_landscape
  - framework_taxonomy
  - governance_method
artifact_focus:
  - trend
  - governance
  - risk_management
ingestion_state: verified
priority: P1
```

---

### 示例 7：第三方评估报告（单一模型）

```yaml
id: E6
title: Opus 4.6 Alignment Evaluation
primary_doc_type: evaluation_report
publication_status: institutional_release
primary_source_actor_type: evaluation_lab
region: US
reading_lane:
  - evaluation_method
  - safety_case_method
artifact_focus:
  - audit_finding
  - safety_report
risk_domain:
  - scheming
  - evaluation_awareness
  - information_concealment
primary_method_type: capability_evaluation
method_tags:
  - evaluation_execution
  - evaluation_awareness_testing
target_model_or_system:
  - Claude Opus 4.6
ingestion_state: verified
priority: P1
```

---

### 示例 8：多模型比较评估报告（方法清晰但工具非主贡献）

```yaml
id: E9
title: Science of Scheming
primary_doc_type: evaluation_report
publication_status: institutional_release
primary_source_actor_type: evaluation_lab
region: US
reading_lane:
  - evaluation_method
  - framework_taxonomy
artifact_focus:
  - audit_finding
  - evaluation_framework
risk_domain:
  - scheming
  - covert_action
  - evaluation_awareness
primary_method_type: empirical_experiment
method_tags:
  - evaluation_execution
  - evaluation_protocol
  - multi_model_comparison
ingestion_state: verified
priority: P1
```

---

### 示例 9：安全论证论文（inability safety case）

```yaml
id: I6g
title: Scheming Inability Safety Case
primary_doc_type: research_article
publication_status: preprint
primary_source_actor_type: frontier_ai_company
region: UK
reading_lane:
  - safety_case_method
  - evaluation_method
artifact_focus:
  - safety_case_argument
  - evaluation_framework
risk_domain:
  - scheming
  - oversight_subversion
  - evaluation_awareness
primary_method_type: safety_case
method_tags:
  - safety_case_construction
  - evaluation_awareness_testing
ingestion_state: verified
priority: P0
```

---

### 示例 10：系统卡的风险更新伴随文档

```yaml
id: I4g-R
title: Mythos Alignment Risk Update
primary_doc_type: institutional_report
secondary_doc_type:
  - risk_update
publication_status: institutional_release
primary_source_actor_type: frontier_ai_company
region: US
reading_lane:
  - system_transparency
  - safety_case_method
artifact_focus:
  - risk_update
  - safety_report
related_doc_id:
  - I4g
relation_type: parent
ingestion_state: verified
priority: P1
```

---

### 示例 11：排行榜快照

```yaml
id: E19
title: F5 CASI Leaderboard
primary_doc_type: platform_snapshot
publication_status: webpage_release
primary_source_actor_type: platform_dashboard
region: US
reading_lane:
  - institutional_landscape
artifact_focus:
  - leaderboard
  - platform
canonical_file_format: pdf_printed
ingestion_state: needs_review
processing_flags:
  - screenshot_only
priority: P3
```

---

### 示例 12：工作缓存

```yaml
id: history_deepread_precise
title: deepread_precise.txt
primary_doc_type: workflow_artifact
publication_status: unknown
primary_source_actor_type: unknown
reading_lane:
  - workflow_support
artifact_focus:
  - workflow_cache
canonical_file_format: txt
ingestion_state: excluded
processing_flags:
  - cache_only
priority: archive
is_core_literature: false
```

---

# 7. 辅助字段使用规则

## 7.1 `secondary_doc_type`

### 定义

`secondary_doc_type` 用于记录边界案例中的次要文档形态，或标注伴随关系。

### 填写规则

* 可选。
* 多选。
* 不应常态化填写。
* 只在主类型无法完整表达边界特征时使用。
* 凡标注 `addendum`、`risk_update`、`appendix` 者，须在 `notes` 中写明所关联主文档 ID，并填写 `related_doc_id` 和 `relation_type` 字段。

### 可选值

```yaml
secondary_doc_type:
  # ── 文献形态类 ──
  - research_article
  - technical_report
  - system_model_card
  - evaluation_report
  - research_article_collection
  - webpage_blog

  # ── 伴随文档类 ──
  - addendum      # 增补件：对主文档的更新或补充说明，无独立完整论证结构
  - risk_update   # 风险更新件：系统卡/框架发布后出具的专项风险再评估
  - appendix      # 附件：附属于主文档的技术性补充材料
```

### 使用原则

```text
能用 reading_lane 和 artifact_focus 表达的，不用 secondary_doc_type；
只有文献形态本身确实跨界时，才使用文献形态类值；
只有文档确实是另一文档的伴随件时，才使用伴随文档类值。
```

### 示例

#### arXiv 技术报告很像研究论文

```yaml
primary_doc_type: technical_report
secondary_doc_type:
  - research_article
publication_status: preprint
```

#### 机构报告中包含大量评测结果

```yaml
primary_doc_type: institutional_report
secondary_doc_type:
  - evaluation_report
reading_lane:
  - institutional_landscape
  - evaluation_method
```

#### 系统卡的增补件

```yaml
primary_doc_type: system_model_card
secondary_doc_type:
  - addendum
related_doc_id:
  - I1b
relation_type: parent
```

---

# 8. 易混概念辨析与判定规则

## 8.1 `technical_report` vs `institutional_report`

### 核心区别

```text
technical_report 以技术对象为中心；
institutional_report 以机构判断、趋势总结或态势评估为中心。
```

### 判定规则

如果文档主要回答：

```text
这个模型、系统、方法怎么做？
它的能力如何？
实验结果如何？
安全评测结果如何？
```

标为：

```yaml
primary_doc_type: technical_report
```

如果文档主要回答：

```text
这个机构如何判断领域趋势？
年度进展是什么？
生态格局如何变化？
政策或能力建设状态如何？
```

标为：

```yaml
primary_doc_type: institutional_report
```

### 注意

```text
不是机构发布的文档就一定是 institutional_report。
```

企业发布的模型技术报告仍然可以是：

```yaml
primary_doc_type: technical_report
primary_source_actor_type: frontier_ai_company
```

政府机构发布的评估趋势报告则可能是：

```yaml
primary_doc_type: institutional_report
primary_source_actor_type: government_agency
```

---

## 8.2 `evaluation_report` vs `technical_report` vs `institutional_report`

### 核心三角区别

```text
technical_report：     模型提供方自述——我们的模型怎么做、效果如何
evaluation_report：    第三方结构性评估——外部机构评估某个目标系统的风险/能力
institutional_report： 趋势/态势综述——机构对领域格局、年度进展的判断
```

### 判定规则

如果评估主体（actor）是另一机构的系统，且结论直接指向该系统的风险状态：

```yaml
primary_doc_type: evaluation_report
```

如果文档既有方法设计又有多模型横向比较，但可复用工具本身不是主贡献：

```yaml
primary_doc_type: evaluation_report
method_tags:
  - evaluation_protocol
  - multi_model_comparison
```

---

## 8.3 `evaluation_report` vs `benchmark_dataset_paper`

### 判定准则

将本文档移除后，其描述的评测工具 / 基准是否作为独立可复用资源继续存在？

```text
若否 → evaluation_report
若是 → benchmark_dataset_paper
```

覆盖单一模型还是多个模型，不作为判断依据。

---

## 8.4 `thesis` vs `research_article`

### 核心区别

```text
thesis 是学位身份；
research_article 是独立研究论文身份。
```

如果文档是为了取得学位提交的完整论文，即使内含多个 article-style chapter：

```yaml
primary_doc_type: thesis
secondary_doc_type:
  - research_article_collection
```

---

## 8.5 `system_model_card` vs `technical_report`

### 核心区别

```text
system_model_card 以透明度披露和安全说明为中心；
technical_report 以技术实现、模型能力和实验细节为中心。
```

如果标题或功能明显是 system card / model card / safety card / transparency report：

```yaml
primary_doc_type: system_model_card
```

如果文档主要展开训练、架构、数据、实验、benchmark 结果：

```yaml
primary_doc_type: technical_report
```

一份模型卡中可能包含技术评测，不需要改成 `technical_report`，用 `reading_lane` 和 `artifact_focus` 表达：

```yaml
primary_doc_type: system_model_card
reading_lane:
  - system_transparency
  - evaluation_method
artifact_focus:
  - model_card
  - evaluation_suite
```

---

## 8.6 `standard_guideline` vs `governance_framework`

### 核心区别

```text
standard_guideline 更偏规范、标准、合规和操作指南；
governance_framework 更偏风险结构、治理逻辑、部署阈值和决策框架。
```

典型区别：

```text
NIST AI 600-1              → standard_guideline
EU GPAI Code of Practice   → standard_guideline
Frontier Safety Framework  → governance_framework
Preparedness Framework     → governance_framework
Responsible Scaling Policy → governance_framework
```

---

## 8.7 `benchmark_dataset_paper` vs `research_article`

如果文档最核心贡献是发布或验证一个 benchmark/dataset/eval suite：

```yaml
primary_doc_type: benchmark_dataset_paper
```

如果 benchmark 只是实验工具，而不是主贡献：

```yaml
primary_doc_type: research_article
artifact_focus:
  - benchmark
```

---

## 8.8 `platform_snapshot` 的边界

排行榜发布机构的分析报告（叙述性文字为主）：

```yaml
primary_doc_type: institutional_report
artifact_focus:
  - leaderboard
```

排行榜平台本身在某时刻的数据快照（打印件或截图）：

```yaml
primary_doc_type: platform_snapshot
artifact_focus:
  - leaderboard
  - platform
```

---

## 8.9 `preprint` 不能作为 `primary_doc_type`

```text
preprint 是发布状态，不是文献形态。
```

错误写法：

```yaml
primary_doc_type: preprint
```

正确写法：

```yaml
primary_doc_type: research_article
publication_status: preprint
```

---

## 8.10 `reading_lane` vs `artifact_focus`

```text
reading_lane 表示我们为什么读；
artifact_focus 表示它讨论或贡献了什么。
```

示例：

```yaml
reading_lane:
  - framework_taxonomy
  - governance_method
artifact_focus:
  - framework
  - risk_management
  - governance
```

---

## 8.11 `risk_domain` vs `method_tags`

```text
risk_domain 是本体论标签：研究对象是哪类风险现象？
method_tags 是程序论标签：用了哪些研究手段？
```

两者独立，不互斥，可以自由组合。示例：

```yaml
risk_domain:
  - sandbagging           # 研究的是能力隐藏现象
  - evaluation_awareness
method_tags:
  - sandbagging_detection  # 用了沙袋检测方法
  - white_box_probing      # 用了白盒探针方法
  - multi_model_comparison # 进行了多模型横向对比
```

---

## 8.12 `source_actor_type` 不能替代 `primary_doc_type`

```text
谁发布，不决定它是什么文献类型。
```

示例：

```yaml
primary_doc_type: technical_report
primary_source_actor_type: domestic_ai_company
```

```yaml
primary_doc_type: evaluation_report
primary_source_actor_type: evaluation_lab
```

```yaml
primary_doc_type: research_article
primary_source_actor_type: academic_group
```

---

## 8.13 `ingestion_state` vs `processing_flags`

```text
ingestion_state 表示能不能入库；
processing_flags 表示有什么处理问题。
```

HTML 保留但内容可靠：

```yaml
ingestion_state: needs_review
processing_flags:
  - html_retained
  - needs_pdf_conversion
```

首页快照，不是目标文档：

```yaml
ingestion_state: excluded
processing_flags:
  - homepage_snapshot_problem
  - not_original_document
```

正文抽取失败但原始 PDF 可靠：

```yaml
ingestion_state: needs_review
processing_flags:
  - text_extraction_failed
```

正文抽取已修复：

```yaml
ingestion_state: verified
processing_flags:
  - text_extraction_fixed
  - manually_verified
```

---

## 8.14 `webpage_blog` vs `workflow_artifact`

```text
webpage_blog 是外部发布材料；
workflow_artifact 是本地工作过程材料。
```

---

## 8.15 `not_literature` vs `workflow_artifact`

```text
workflow_artifact 对本地工作有用；
not_literature 是误收、无效或不应保留为文献的材料。
```

---

## 8.16 功能定位类型与文档形态类型的竞争

`primary_doc_type` 的第一层（功能定位类型）和第二层（文档形态类型）在边界案例中会同时成立，这不是标注错误，而是文档本身的双重属性。

**处理原则**：功能定位类型优先，次要属性用 `secondary_doc_type` 补充。

**典型案例：政府机构发布的模型能力评估报告**

```text
从形态看：technical_report（技术内容为主）
从形态看：institutional_report（政府机构发布）
从功能看：evaluation_report（第三方对特定模型的结构性评估）
```

正确标注：

```yaml
primary_doc_type: evaluation_report        # 功能定位优先
secondary_doc_type:
  - technical_report                       # 次要形态属性
primary_source_actor_type: government_agency
```

**典型案例：企业发布的包含大量技术细节的系统卡**

```text
从功能看：system_model_card（核心功能是透明度披露）
从形态看：technical_report（包含训练方法、评测结果等技术内容）
```

正确标注：

```yaml
primary_doc_type: system_model_card        # 功能定位优先
secondary_doc_type:
  - technical_report                       # 仅在技术细节比重极大时填写，否则省略
```

**注意**：`secondary_doc_type` 的形态类值（如 `technical_report`、`research_article`）只在文档确实横跨两层时才填写，不需要为每篇 system_model_card 都追加 `technical_report`。判断标准是：如果把 `secondary_doc_type` 去掉，是否会在检索或统计时丢失有价值的分类信息。

---

## 8.17 `not_literature` 与 `ingestion_state: excluded` 的主从关系

`not_literature` 和 `workflow_artifact` 的核心语义是"不应进入正式文献库"，这一判断由 `ingestion_state: excluded` 承载。`primary_doc_type` 填写这两个值只是补充说明具体原因，不是必须项。

如果已经确定 `ingestion_state: excluded`，且原因已经通过 `processing_flags` 说明清楚（如 `homepage_snapshot_problem`、`cache_only`），`primary_doc_type` 可以省略或填 `other_literature`，不必强制填 `not_literature`。

---

# 9. 推荐标注流程

## 第一步：先判断是否为正式文献

如果是工作缓存、脚本、抽取记录、修复记录：

```yaml
primary_doc_type: workflow_artifact
ingestion_state: excluded
```

如果是误下载、首页快照、无效文件：

```yaml
primary_doc_type: not_literature
ingestion_state: excluded
```

如果是正式外部材料，进入第二步。

---

## 第二步：判断主文档类型

`primary_doc_type` 按以下优先级判断。**功能定位类型（1–5）优先于文档形态类型（5.5–12）**；如果文档同时符合两层类型，以功能定位类型为 `primary_doc_type`，形态类型记入 `secondary_doc_type`。

**功能定位类型（优先判断）：**

```text
1.  system/model/safety card / transparency report  → system_model_card
2.  标准、指南、code of practice、合规规范            → standard_guideline
3.  安全框架、风险框架、部署框架、治理框架              → governance_framework
4.  benchmark/dataset/eval suite 为主贡献，工具可独立复用 → benchmark_dataset_paper
5.  第三方对特定模型/系统/框架的结构性评估              → evaluation_report
```

**文档形态类型（功能定位类型均不适用时选用）：**

```text
5.5 排行榜、仪表盘、在线平台的快照性文档               → platform_snapshot
6.  学位论文                                         → thesis
7.  模型、方法、实验、技术细节为中心                    → technical_report
8.  机构趋势、年度、生态、能力建设总结                   → institutional_report
9.  综述、survey、review、position paper              → survey_review
10. 普通独立研究论文                                   → research_article
11. 网页、博客、在线文章                               → webpage_blog
12. 其他相关文献                                      → other_literature
```

> 如果文档在功能定位类型中找到了匹配，但在形态上也明显属于第二层的某个类型（如一份 `evaluation_report` 在形态上是 `technical_report`），可选填 `secondary_doc_type`。判断原则见 §8.16。

---

## 第三步：填写发布状态

```yaml
publication_status:
  - published
  - preprint
  - working_paper
  - draft
  - living_document
  - institutional_release
  - webpage_release
  - unknown
```

---

## 第四步：填写来源主体与地区

```yaml
primary_source_actor_type:
  - frontier_ai_company / domestic_ai_company / evaluation_lab
  - government_agency / standards_body / international_network
  - academic_group / civil_society_org / platform_dashboard / unknown

region:
  - US / UK / EU / CN / JP / KR / SG / international / unknown
```

联合发布时，参照 §4.5 联合评估场景填写指引处理。

---

## 第五步：填写阅读用途

至少从以下三条主线中判断：

```yaml
reading_lane:
  - framework_taxonomy
  - evaluation_method
  - governance_method
```

可再补充：

```yaml
  - system_transparency / model_technical_profile
  - institutional_landscape / safety_case_method
  - interpretability_method / background_theory
```

---

## 第六步：填写贡献对象与风险领域

```yaml
artifact_focus:
  # 选取最能描述文献主要贡献或讨论对象的标签

risk_domain:
  # 选取文献明确研究的风险/失控现象类别
  # 优先使用精确子类，autonomy 仅作宽泛兜底
```

---

## 第七步：填写方法标签

```yaml
primary_method_type:  # 主要方法，单选

method_tags:
  # 所有适用的方法，多选
  # 注意区分：
  # - benchmark_construction（构建工具）vs evaluation_execution（实施评估）
  # - sandbagging_detection（检测沙袋）vs elicitation（引出能力）
  # - white_box_probing（白盒方法）vs evaluation_awareness_testing（行为层测量）
```

---

## 第八步：填写处理状态与关联关系

判断是否可正式入库：

```yaml
ingestion_state:
  - verified / needs_review / provisional / excluded / deprecated
```

记录具体处理问题：

```yaml
processing_flags:
  # 适用的处理问题标签
```

如有关联文档，填写：

```yaml
related_doc_id:   # 关联文档 ID
relation_type:    # parent / child / supersedes / version_of / companion
```

---

# 10. 推荐最终字段模板

```yaml
id:
title:
year:
authors_or_org:
source_actor:
primary_source_actor_type:
additional_actor_types:
region:

primary_doc_type:
secondary_doc_type:
publication_status:

reading_lane:
artifact_focus:
risk_domain:
primary_method_type:
method_tags:
target_model_or_system:

canonical_file_format:
ingestion_state:
processing_flags:

related_doc_id:
relation_type:

is_core_literature:
priority:
local_path:
source_url:
notes:
```

---

# 11. 核心结论

本分类体系的核心不是把所有信息压进一个 `doc_type`，而是拆成多个维度：

```text
primary_doc_type      → 文献主身份，单选
publication_status    → 发布状态，单选
source_actor_type     → 主导来源，单选
region                → 地区，单选或多选
reading_lane          → 研究用途，多选
artifact_focus        → 贡献对象，多选
risk_domain           → 风险领域（本体论），多选
method_tags           → 方法标签（程序论），多选
ingestion_state       → 入库状态，单选
processing_flags      → 处理问题，多选
related_doc_id        → 关联文档，可选
relation_type         → 关联性质，可选
```

其中最关键的是：

```text
primary_doc_type 不承担 preprint、benchmark、governance、evaluation 等所有含义；
preprint 放 publication_status；
benchmark/dataset 既可以是 primary_doc_type，也可以是 artifact_focus；
治理、评测、框架分类等真正阅读目的放 reading_lane；
风险现象类别（本体论）放 risk_domain；
研究手段（程序论）放 method_tags；两者语义独立，可自由组合；
evaluation_report 专用于第三方结构性评估，区别于模型自述（technical_report）和趋势概述（institutional_report）；
platform_snapshot 专用于排行榜和仪表盘的快照性文档；
primary_doc_type 的三层结构：功能定位类型 > 文档形态类型 > 存在性标记，标注时按层级优先判断；
not_literature 和 workflow_artifact 是存在性标记，不与功能定位类型或形态类型竞争；
伴随文档关系通过 secondary_doc_type + related_doc_id + relation_type 三字段联合表达；
本地文件质量和处理问题放 ingestion_state + processing_flags。
```

这样可以同时满足：

```text
1. 后续统计稳定（互斥字段保证统计口径一致）；
2. 边界案例可解释（判定流程与辨析规则覆盖主要模糊地带）；
3. 阅读用途不丢失（reading_lane 独立于文献类型）；
4. 本地文献库维护状态清楚（ingestion_state + processing_flags）；
5. 关联文献结构可追踪（related_doc_id + relation_type）；
6. 词汇表可独立演进（risk_domain 与 method_tags 各自版本化，向后兼容）；
7. 前沿 AI 安全、评估、治理、系统卡、标准框架等复杂材料可以统一归档；
8. 功能定位类型优先于形态类型，消除 evaluation_report / technical_report 等边界案例的竞争（三层结构 + secondary_doc_type 补充）。
```

---

# 12. 分类规范变更流程

分类词汇变更必须遵循以下流程，确保文档、代码和前端一致。

## 变更流程

```
规范文档 (本文档)
    ↓
后端词表 (api/classification_vocab.py)
    ↓
前端标签 (web/src/labels.js)
    ↓
抽取提示 (scripts/literature_classification_extract.py)
    ↓
测试 fixture (tests/)
    ↓
审核页面 (web/src/views/ClassificationReview.vue)
```

## 各环节职责

| 环节 | 文件 | 职责 |
|------|------|------|
| 规范文档 | `docs/methodology/classification-methodology.md` | 定义字段语义、填写规则、辨析规则、可选值列表 |
| 后端词表 | `api/classification_vocab.py` | 运行时验证、API 端点 `/classification/vocab`、抽取 prompt 生成 |
| 前端标签 | `web/src/labels.js` | UI 显示中文标签、审核页面字段选项 |
| 抽取提示 | `scripts/literature_classification_extract.py` | LLM 抽取指令中的词汇列表（通过 `vocab_strs` 动态生成） |
| 测试 fixture | `tests/` | 覆盖新值的测试用例 |
| 审核页面 | `web/src/views/ClassificationReview.vue` | 审核 UI 的字段选项（通过 `labels.js` 读取） |

## 变更检查清单

新增词汇时：
- [ ] 更新本文档对应字段的可选值列表
- [ ] 更新 `api/classification_vocab.py` 的 `VOCAB`
- [ ] 更新 `web/src/labels.js` 的对应 `*_LABELS`
- [ ] 运行 `python scripts\check_docs.py` 确认文档一致性
- [ ] 运行 `pytest tests/ -q` 确认测试通过
- [ ] 运行 `cd web && npm run build` 确认前端构建通过
- [ ] 在审核页面确认新值可选

修改词汇定义时：
- [ ] 更新本文档对应字段的说明和辨析规则
- [ ] 确认无需迁移已有标注（向后兼容原则）
- [ ] 如需迁移，编写迁移脚本并更新测试

## 版本号规则

- `risk_domain` 词汇版本：`VOCAB_VERSIONS["risk_domain"]`（当前 v1）
- `method_tags` 词汇版本：`VOCAB_VERSIONS["method_tags"]`（当前 v1）
- 规范文档版本：文档头部 `版本说明`（当前 v0.2.2）

版本升级时机：
- 新增词汇：通常不升级 `VOCAB_VERSIONS`，追加到末尾即可（向后兼容）；规范文档版本可按文档发布批次升级
- 修改词汇定义：升级对应词汇版本号
- 删除词汇：升级版本号，需编写迁移脚本

---

# 13. 审核操作语义

分类审核页面（`/classification`）提供以下操作，每个操作有明确语义。

## 操作说明

| 操作 | 按钮 | 语义 | 对 extraction 的影响 | 对 works 的影响 |
|------|------|------|---------------------|----------------|
| 保存草稿 | `save-draft` | 保存人工编辑，不改变审核状态 | 更新 `extracted_json`、`confidence_json`、`ambiguity_score` | 无 |
| 批准 | `approved` | 确认分类结果正确，写入稳定层 | 设置 `review_status='approved'`、`applied=1` | 写入标量字段和多值标签 |
| 需修正 | `needs_fix` | 分类结果有误，需人工修正后重新提交 | 设置 `review_status='needs_fix'` | 无 |
| 拒绝 | `rejected` | 分类结果无效，丢弃 | 设置 `review_status='rejected'` | 无 |
| 隔离 | `quarantine` | 文献本身有问题，移出审核队列 | 设置 `review_status='rejected'`、`fix_action='quarantined'` | 设置 `read_status='quarantined'`，移动源文件 |

## 批准的详细语义

当审核员点击"批准"时：

1. **标量字段写入**（fill-empty 语义）：
   - `primary_doc_type`、`secondary_doc_type`、`publication_status`、`ingestion_state`、`priority`、`primary_source_actor_type`、`region`
   - 只在 `works` 表对应字段为空时写入，不覆盖已有值

2. **多值标签写入**（skip-if-exists 语义）：
   - `reading_lane`、`artifact_focus`、`risk_domain`、`method_tags`
   - 写入 `work_classification_tags` 表，已存在的标签不重复写入
   - 所有标签 `review_status='approved'`

3. **Supersede 其他 extraction**：
   - 同一 work 的其他 `pending` 或 `needs_fix` extraction 被标记为 `rejected`、`fix_action='superseded'`

## 隔离的详细语义

当审核员点击"隔离"时：

1. **选择隔离原因**：
   - `bad_source`：坏源（PDF 内容为空、反爬页、扫描损坏等）
   - `out_of_scope`：不在范围（不属于当前研究主题或综述范围）
   - `not_literature`：非文献（不是论文、报告、标准等目标文献）
   - `duplicate_residual`：重复残留（已由其他 work 覆盖）
   - `needs_rerun`：待重跑（主题对，但上传文档本身有问题，需替换后重新抽取）
   - `user_removed`：用户移除（明确不想保留）

2. **影响范围**：
   - 当前 extraction 和同一 work 的所有 pending extraction 被标记为 `rejected`
   - 同一 work 中 `review_status='approved'` 且 `applied=0` 的 extraction 也会被标记为 `rejected`、`fix_action='quarantined'`
   - `works.read_status` 设置为 `'quarantined'`
   - 源文件移动到 `_quarantine/` 目录
   - 隔离状态在所有审核页面（元数据、分类、文献管理）同步可见

## 保存草稿的详细语义

当审核员点击"保存草稿"时：

1. **合并人工编辑**：
   - 将 `editForm` 中的值合并到 `extracted_json`
   - 人工编辑的字段 `confidence` 提升为 `'high'`

2. **重新计算模糊度**：
   - 使用合并后的 `confidence` 重新计算 `ambiguity_score`

3. **不改变审核状态**：
   - `review_status` 保持 `'pending'`
   - 不写入 `works` 表
   - 不 supersede 其他 extraction

---

# 14. 字段实现状态说明

## primary_method_type

`primary_method_type` 当前只是方法论推荐字段，**暂不进入后端落库和审核页面**。

**当前状态**：
- 后端 `classification_vocab.py` 的 `VOCAB` 和 `SCALAR_VOCAB_FIELDS` 均未包含此字段
- 前端 `ClassificationReview.vue` 的 `CLASS_FIELDS` 未展示此字段
- 抽取 prompt 中未要求 LLM 输出此字段

**后续如需落库，需**：
1. 在 `VOCAB` 中新增 `primary_method_type` 键和对应值列表
2. 在 `SCALAR_VOCAB_FIELDS` 中追加
3. 在前端 `labels.js` 新增 `PRIMARY_METHOD_TYPE_LABELS`
4. 在审核页面 `CLASS_FIELDS` 中追加
5. 更新抽取 prompt

## secondary_doc_type

`secondary_doc_type` 当前实现说明：

**抽取脚本和前端审核页**：
- 按 `primary_doc_type` 词表处理（复用同一值列表）
- 抽取 prompt 中要求 LLM 输出 `secondary_doc_type`，值域与 `primary_doc_type` 相同

**API 校验**：
- `api/classification_vocab.py` 的 `SCALAR_VOCAB_FIELDS` 未包含 `secondary_doc_type`
- 这是有意设计：`secondary_doc_type` 允许自由文本输入（如 `addendum`、`risk_update`、`appendix` 等伴随文档类值）
- 通用 scalar 校验不校验此字段

**伴随文档类值**：
- `addendum`（增补件）、`risk_update`（风险更新件）、`appendix`（附件）等伴随文档类值属于方法论扩展
- 这些值尚未完整接入 UI/抽取链路
- 本轮只记录为边界，不做实现

**边界说明**：
- `secondary_doc_type` 的形态类值（如 `technical_report`、`research_article`）可正常使用
- 伴随文档类值（如 `addendum`、`risk_update`）需要配合 `related_doc_id` 和 `relation_type` 使用
- 完整的伴随文档支持需后续实现
