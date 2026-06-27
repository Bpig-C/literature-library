# 分类本体 v0.2 落地实施方案 v1

> 文档用途：供本地模型优化与审核，通过后作为正式实施依据
> 对应规范：../methodology/classification-methodology.md（文献库分类方法规范 v0.2）
> 当前代码基准：LiteratureLib_2026-06-07（FastAPI + SQLite + Vue 3）
> 撰写时间：2026-06-07

---

## 零、核心约束与设计原则

在所有方案细节之前，先列出不可违反的约束：

1. **旧字段保留，不改语义**：`doc_type`、`read_status`、`work_relations` 等现有字段在迁移完成前保持原样，新字段并存。
2. **向后兼容**：现有 API 请求参数、响应结构、前端筛选均不得因新增字段而 break，新字段对旧客户端是透明附加。
3. **分步可回滚**：每个 Phase 独立可回滚，不依赖后续 Phase 的完成。
4. **不强制立即填满**：新字段全部可为 NULL，允许逐步标注，不设批量强制填写截止。
5. **两套 `ingestion_state` 与 `read_status` 不合并**：`read_status` 管文件物理工作流（隔离/恢复），`ingestion_state` 管文献逻辑入库资格，语义正交，共存不替换。

---

## 一、数据库层

### 1.1 新增列（`works` 表）

以下列通过 `ALTER TABLE` 逐一追加，全部可为 NULL，无默认值约束（迁移脚本负责回填）：

```sql
ALTER TABLE works ADD COLUMN primary_doc_type    TEXT;
ALTER TABLE works ADD COLUMN publication_status  TEXT;
ALTER TABLE works ADD COLUMN ingestion_state     TEXT;
ALTER TABLE works ADD COLUMN priority            TEXT;
ALTER TABLE works ADD COLUMN is_core_literature  INTEGER;  -- 0/1/NULL
ALTER TABLE works ADD COLUMN primary_source_actor_type TEXT;
ALTER TABLE works ADD COLUMN region              TEXT;
ALTER TABLE works ADD COLUMN canonical_file_format TEXT;
```

**说明**：

- `primary_doc_type` 与现有 `doc_type` 并存。`doc_type` 在 Phase 3 完成迁移验证后再废弃，不提前删除。
- `is_core_literature` 用 INTEGER 存储（SQLite 无原生 BOOLEAN），0=false，1=true，NULL=未标注。
- `ingestion_state` 与 `read_status` 正交共存，不合并，详见第零节约束说明。

**新增索引**：

```sql
CREATE INDEX IF NOT EXISTS idx_works_primary_doc_type     ON works(primary_doc_type);
CREATE INDEX IF NOT EXISTS idx_works_publication_status   ON works(publication_status);
CREATE INDEX IF NOT EXISTS idx_works_ingestion_state      ON works(ingestion_state);
CREATE INDEX IF NOT EXISTS idx_works_priority             ON works(priority);
CREATE INDEX IF NOT EXISTS idx_works_primary_actor_type   ON works(primary_source_actor_type);
CREATE INDEX IF NOT EXISTS idx_works_region               ON works(region);
```

---

### 1.2 新建 `work_classification_tags` 表（多值标签）

以下字段天然多选，不适合单列存储，统一放入标签表：

```text
secondary_doc_type
additional_actor_types
reading_lane
artifact_focus
risk_domain
primary_method_type
method_tags
processing_flags
target_model_or_system
```

建表语句：

```sql
CREATE TABLE IF NOT EXISTS work_classification_tags (
    id               TEXT PRIMARY KEY,           -- CT-{uuid12}
    work_id          TEXT NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    tag_group        TEXT NOT NULL,              -- reading_lane / artifact_focus / risk_domain / method_tags / ...
    tag_value        TEXT NOT NULL,              -- 具体标签值，来自规范词汇表
    vocab_version    TEXT NOT NULL DEFAULT 'v1', -- 对应规范中的词汇版本号
    source           TEXT NOT NULL DEFAULT 'human',  -- human / model / rule / import
    confidence       TEXT,                       -- high / medium / low / NULL
    review_status    TEXT NOT NULL DEFAULT 'pending', -- pending / approved / rejected
    reviewed_at      TEXT,
    reviewed_by      TEXT,
    evidence         TEXT,                       -- 支持该标签的文本片段或推断依据
    notes            TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_wct_work_id     ON work_classification_tags(work_id);
CREATE INDEX IF NOT EXISTS idx_wct_work_group  ON work_classification_tags(work_id, tag_group);
CREATE INDEX IF NOT EXISTS idx_wct_group_value ON work_classification_tags(tag_group, tag_value);
CREATE INDEX IF NOT EXISTS idx_wct_review      ON work_classification_tags(review_status);
```

**说明**：

- `tag_group` 的合法值由应用层校验，不在 DB 层加 CHECK 约束（便于词汇扩充时不需要 migration）。
- `source` 区分人工、模型、规则（迁移脚本回填用 `import`）的来源，便于后续审核优先级区分。
- `vocab_version` 跟随规范文档中的 `risk_domain` 词汇版本 / `method_tags` 词汇版本，与规范保持一致。

---

### 1.3 新建 `classification_extractions` 表（模型分类候选）

模型生成的分类建议先进候选表，不直接写入 `works` 或 `work_classification_tags`，通过审核后才提升。

```sql
CREATE TABLE IF NOT EXISTS classification_extractions (
    id                  TEXT PRIMARY KEY,          -- CE-{uuid12}
    work_id             TEXT NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    model_name          TEXT,
    prompt_version      TEXT,
    extracted_json      TEXT,  -- 模型输出的完整分类 JSON
    confidence_json     TEXT,  -- 各字段置信度 JSON
    ambiguity_score     INTEGER DEFAULT 0,  -- 0-100，分类模糊程度（越高越需人工审核）
    ambiguity_reasons   TEXT,  -- JSON array，说明为何模糊
    review_status       TEXT NOT NULL DEFAULT 'pending',  -- pending / approved / needs_fix / rejected
    review_note         TEXT,
    reviewed_at         TEXT,
    fix_action          TEXT,  -- edited / superseded / quarantined / NULL
    applied             INTEGER NOT NULL DEFAULT 0,  -- 0/1
    applied_at          TEXT,
    raw_response        TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ce_work_id      ON classification_extractions(work_id);
CREATE INDEX IF NOT EXISTS idx_ce_review       ON classification_extractions(review_status);
CREATE INDEX IF NOT EXISTS idx_ce_applied      ON classification_extractions(applied);
CREATE INDEX IF NOT EXISTS idx_ce_ambiguity    ON classification_extractions(ambiguity_score);
```

**说明**：

- `ambiguity_score`（0-100）对应 `metadata_extractions` 里的 `risk_score`，但语义不同：分类的"高风险"是"这篇文献的归类高度模糊，多个 `primary_doc_type` 均可能适用"，而非数据质量问题。
- `ambiguity_reasons` 的典型触发条件（见 §4.1 详细说明）。
- `applied=1` 后，对应的 `primary_doc_type` / `publication_status` / `ingestion_state` / `priority` 写入 `works`，多值标签写入 `work_classification_tags`。

---

### 1.4 扩展 `work_relations` 表（不新建 `work_doc_relations`）

现有 `work_relations` 已经承担文献间关系，且包含 `version_of`、`supersedes`、`part_of` 等与规范中 `related_doc_id` / `relation_type` 高度重叠的关系。若再新建 `work_doc_relations`，后续查询、UI 展示、矩阵导出会出现"同一对文献关系应该查哪张表"的问题。

因此第一版不新建 `work_doc_relations`，而是在现有 `work_relations` 上增加关系类别和审计字段：

```sql
ALTER TABLE work_relations ADD COLUMN relation_category TEXT DEFAULT 'content';
ALTER TABLE work_relations ADD COLUMN source TEXT DEFAULT 'human';
ALTER TABLE work_relations ADD COLUMN created_at TEXT;

CREATE INDEX IF NOT EXISTS idx_wr_category ON work_relations(relation_category);
CREATE INDEX IF NOT EXISTS idx_wr_source   ON work_relations(source);
```

**说明**：

- `relation_category='content'`：内容层关系，例如 `same_work`、`not_duplicate`、`translation_of`。
- `relation_category='versioning'`：版本层关系，例如 `version_of`、`supersedes`。
- `relation_category='document_structure'`：文档结构关系，例如 `parent`、`child`、`companion`、`part_of`。
- 第一版保留现有主键 `(work_id_a, work_id_b, relation_type)`，避免大迁移。若未来同一对 work 需要在不同 category 下保留同名 `relation_type`，再升级主键或迁移到带 `id` 的关系表。
- 扩展 `api/routes/relations.py` 的合法类型集合，新增 `parent`、`child`、`companion`；旧 API 请求不传 `relation_category` 时默认 `content`，保持兼容。

---

## 二、迁移脚本

### 2.1 `migrate_add_classification_columns.py`

**职责**：执行所有 DDL 变更（`ALTER TABLE` + `CREATE TABLE`），幂等可重复运行。

```python
"""
scripts/migrate_add_classification_columns.py

执行分类本体 v0.2 的数据库结构变更。
幂等：已存在的列和表不会重复创建。

Usage:
    python scripts/migrate_add_classification_columns.py
    python scripts/migrate_add_classification_columns.py --dry-run
"""
```

逻辑要点：

- 用 `PRAGMA table_info(works)` 检查列是否存在，不存在才执行 `ALTER TABLE`
- 用 `sqlite_master` 检查表是否存在，不存在才 `CREATE TABLE`
- `--dry-run` 模式只打印将执行的 SQL，不实际运行
- 执行完成后打印当前 `works` 列列表和新建表列表作为确认

---

### 2.2 `migrate_backfill_doc_type.py`

**职责**：将现有 `doc_type` 和真实 `source_files.original_name` 中的文件名前缀/关键词映射为新分类候选。能高置信判断的可直接写入 `works`，其余写入候选/待审状态。

映射规则（硬编码）：

```python
DOC_TYPE_MAP = {
    "system_card": {
        "primary_doc_type": "system_model_card",
        "publication_status": "institutional_release",
        "ingestion_state": "verified",
        "confidence": "high",
    },
    "benchmark": {
        "primary_doc_type": "benchmark_dataset_paper",
        "ingestion_state": "needs_review",
        "confidence": "medium",
    },
    "preprint": {
        "primary_doc_type": None,
        "publication_status": "preprint",
        "ingestion_state": "needs_review",
        "confidence": "low",
    },
    "paper": {
        "primary_doc_type": None,           # 无法自动判断，打上 needs_review
        "ingestion_state": "needs_review",
    },
    "report": {
        "primary_doc_type": None,           # 可能是 technical_report / institutional_report / evaluation_report
        "ingestion_state": "needs_review",
    },
}
```

文件名启发式（在旧 `doc_type` 之前或之后作为修正信号）：

```python
FILENAME_HINTS = [
    (r"system[_ -]?card|model[_ -]?card|safety[_ -]?card|transparency[_ -]?report",
     {"primary_doc_type": "system_model_card", "publication_status": "institutional_release", "confidence": "high"}),
    (r"technical[_ -]?report",
     {"primary_doc_type": "technical_report", "confidence": "high"}),
    (r"benchmark|bench|dataset|eval[_ -]?suite|leaderboard paper",
     {"primary_doc_type": "benchmark_dataset_paper", "confidence": "medium"}),
    (r"leaderboard|dashboard|scorecard",
     {"primary_doc_type": "platform_snapshot", "publication_status": "webpage_release", "confidence": "medium"}),
    (r"guide|guideline|sp[_ -]?\d+|iso|code[_ -]?of[_ -]?practice|standard",
     {"primary_doc_type": "standard_guideline", "confidence": "medium"}),
    (r"framework|rmf|preparedness|responsible[_ -]?scaling|rsp|frontier[_ -]?safety",
     {"primary_doc_type": "governance_framework", "confidence": "medium"}),
    (r"year[_ -]?in[_ -]?review|trend|landscape|annual[_ -]?report",
     {"primary_doc_type": "institutional_report", "confidence": "medium"}),
]
```

编号前缀启发式（来自当前真实文件名，如 `[I6g]`、`E6_`、`G16_`、`C7_`、`【R】`）：

```text
E*       → evaluation_report 候选；若标题含 Benchmark/Dataset，则转为 benchmark_dataset_paper 候选。
G* / S*  → governance_framework / standard_guideline / institutional_report 候选，必须结合关键词。
I*       → frontier/company/system 相关候选；标题含 System Card/Model Card 时高置信 system_model_card，否则不直接判主类型。
C*       → company technical/system 相关候选；标题含 Technical Report 时 technical_report。
R / 【R】 → report-like 候选；只设置 needs_review，不直接判 institutional_report。
X* / M* / MS* → 暂不自动映射，只作为 evidence 写入 notes。
```

执行逻辑：

1. 对 `primary_doc_type IS NULL` 的所有 `works` 行执行映射
2. 读取 `source_files.original_name`、`works.title`、`works.doc_type`、`works.arxiv_id` 作为规则输入
3. 高置信规则（例如 system/model card、technical report）可直接写入 `works`，同时在脚本输出和 `notes`/报告中保留规则证据
4. 中低置信规则只写入 `ingestion_state='needs_review'`，并在 dry-run/JSON 报告中列为候选；Phase 3 建立 `classification_extractions` 后可再导入为正式候选
5. 不能自动映射的写入 `ingestion_state='needs_review'`，`primary_doc_type` 保持 NULL
6. 输出统计：自动映射 N 条、候选 N 条、需人工审核 N 条，并按旧 `doc_type`、文件名前缀和新候选类型分组列出
7. `--dry-run` 支持

---

### 2.3 `migrate_import_filename_metadata.py`（可选，优先级较低）

**职责**：从 `source_files.original_name`、已有 `metadata_extractions.extracted_json`、旧索引文件（如存在）中批量导入 `primary_source_actor_type`、`region`、`canonical_file_format`、`processing_flags` 等结构化候选。

当前 `README.md` 是项目说明，不是文献清单，因此不建议解析 README 作为数据源。导入结果默认作为候选（`source='rule'` / `source='import'`、`review_status='pending'`），不直接写 `verified`。

---

## 三、后端 API 层

### 3.1 `api/models.py` 变更

新增或扩展以下 Pydantic 模型：

```python
# 扩展 WorkUpdate，新增四个 Phase 1 字段
class WorkUpdate(BaseModel):
    # 现有字段保留不变 ...
    primary_doc_type:            str | None = None
    publication_status:          str | None = None
    ingestion_state:             str | None = None
    priority:                    str | None = None
    is_core_literature:          bool | None = None
    primary_source_actor_type:   str | None = None
    region:                      str | None = None
    canonical_file_format:       str | None = None

# 标签操作模型
class TagCreate(BaseModel):
    tag_group:    str
    tag_value:    str
    source:       str = "human"
    confidence:   str | None = None
    evidence:     str | None = None
    notes:        str | None = None

class TagBatchCreate(BaseModel):
    tags: list[TagCreate]

class TagReview(BaseModel):
    review_status: str   # approved / rejected
    review_note:   str = ""

# 分类抽取审核模型
class ClassificationReviewAction(BaseModel):
    review_status:  str             # approved / needs_fix / rejected
    review_note:    str = ""
    edited_fields:  dict | None = None

# 文档关联模型
class DocRelationCreate(BaseModel):
    work_id_a:      str
    work_id_b:      str
    relation_type:  str
    note:           str = ""
```

---

### 3.2 `api/routes/works.py` 变更

**新增筛选参数**（对现有逻辑无破坏，参数可选）：

```python
@router.get("/works")
def list_works(
    # 现有参数保留 ...
    primary_doc_type:          str | None = None,
    publication_status:        str | None = None,
    ingestion_state:           str | None = None,
    priority:                  str | None = None,
    primary_source_actor_type: str | None = None,
    region:                    str | None = None,
    # 多值标签筛选（AND 语义，所有指定标签均需存在）
    reading_lane:              str | None = None,
    artifact_focus:            str | None = None,
    risk_domain:               str | None = None,
):
```

多值标签筛选通过子查询实现：

```sql
-- 筛选 reading_lane=evaluation_method 的 work_id
SELECT DISTINCT work_id FROM work_classification_tags
WHERE tag_group='reading_lane' AND tag_value='evaluation_method'
  AND review_status='approved'
```

**`get_work` 响应扩展**（不修改现有字段，追加新字段）：

```python
# 在 get_work 的 dict 中追加
work["classification_tags"] = {
    tag_group: [tag_value, ...]   # 仅返回 approved 状态的标签
    for tag_group in ["reading_lane", "artifact_focus", "risk_domain", ...]
}
work["relations"] = [...]        # 继续复用 work_relations，附加 relation_category
```

**`update_work` 扩展**：在现有 UPDATE 逻辑中追加对新列的处理，与现有字段处理方式相同。

---

### 3.3 `api/routes/classification.py`（新建）

新建路由模块，注册到 `main.py`：

```python
# api/routes/classification.py

# 标签 CRUD
GET    /classification/tags/{work_id}               # 获取某 work 的所有标签
POST   /classification/tags/{work_id}               # 新增标签（单条）
POST   /classification/tags/{work_id}/batch         # 批量新增标签
DELETE /classification/tags/{tag_id}                # 删除标签
PATCH  /classification/tags/{tag_id}/review         # 审核标签

# 分类抽取候选
GET    /classification/extractions                  # 列表，支持 status/work_id/ambiguity 筛选
GET    /classification/extractions/{ce_id}          # 单条详情
PATCH  /classification/extractions/{ce_id}/review   # 审核（approved/needs_fix/rejected）
POST   /classification/extractions/batch-approve-low-ambiguity  # 批量批准低模糊度候选

# 文档关联
# 不在 classification 路由中新建 doc-relations；继续复用 /relations，
# 并在 relations API 中支持 relation_category。

# 词汇表（只读，供前端下拉渲染）
GET    /classification/vocab                        # 返回全部 tag_group 及其合法 tag_value 列表
```

---

### 3.4 `api/classification_ambiguity.py`（新建，对应 `risk.py` 的分类版）

**职责**：计算模型生成分类候选的模糊程度（`ambiguity_score` 0-100）和 `ambiguity_reasons`。

`ambiguity_score` 只表示"主文档类型是否模糊"，不要混入字段完整度。`reading_lane`、`risk_domain`、`method_tags` 缺失属于补标问题，可以进入 `classification_reasons` 或后续完整度评分，但不应直接把主类型判为高模糊。

评分触发条件（各条触发后加分，满分 100 上限）：

| 触发条件 | 加分 |
|---|---|
| `primary_doc_type` 为 NULL 或置信度 low | +35 |
| 模型显式给出多个候选主类型，或 `ambiguity_notes` 表示边界模糊 | +25 |
| `primary_doc_type` 与文件名强规则冲突（如 `System_Card` 却判为 `research_article`） | +25 |
| `primary_doc_type` 与旧 `doc_type` 强冲突（如 `system_card` 却非 `system_model_card`） | +20 |
| `primary_doc_type` 与 `publication_status` 明显冲突（如 `webpage_blog` + `preprint`） | +20 |
| `artifact_focus` 与 `primary_doc_type` 强不匹配（如 `system_model_card` 但 focus 只有 `benchmark`/`dataset`） | +15 |
| 支持 `primary_doc_type` 的 evidence 为空或无法在输入文本/文件名中定位 | +10 |

评分区间：

```text
0-20:  low_ambiguity    # 可批量批准
21-60: medium_ambiguity # 抽样审核
61-100: high_ambiguity  # 必须逐条审核
```

可选增加 `completeness_score`（0-100），用于衡量标签是否完整：

```text
reading_lane 为空
artifact_focus 为空
primary_source_actor_type=unknown
region=unknown
ingestion_state=needs_review 但 processing_flags 为空
risk_domain/method_tags 对当前阶段要求填写但为空
```

第一版可以只实现 `ambiguity_score`，但命名和 UI 文案必须避免把"信息不完整"误说成"类型模糊"。

---

### 3.5 `api/main.py` 变更

追加 router 注册：

```python
from api.routes import classification
app.include_router(classification.router, prefix="/api")
```

---

## 四、分类抽取脚本

### 4.1 `scripts/literature_classification_extract.py`（新建）

仿照 `literature_metadata_extract.py` 的整体结构，差异点如下：

**输入**：`content.md` 前 6000-8000 字符（与 metadata 相同），附加已有的 `title`、`doc_type`、`source_files.original_name`、`arxiv_id`、`doi`、`venue`、`url` 等上下文。

**提示策略**：

- 不把整篇《文献库分类方法规范 v0.2》原文塞进 system prompt。规范很长，小模型容易丢重点。
- 使用"短系统提示 + 规范摘录 + 固定词汇表 + 文献上下文"。
- 第一版只抽核心字段：`primary_doc_type`、`publication_status`、`primary_source_actor_type`、`region`、`reading_lane`、`artifact_focus`、`ingestion_state`、`priority`。
- `risk_domain`、`method_tags` 暂不作为第一版必填字段；只有文本明确出现时才返回，否则用 `[]`。这两个字段可以在阅读分析阶段或 Phase 3.5 再强化。

**系统提示（框架）**：

```
You classify literature records for a local AI safety literature library.
Use only the provided vocabulary and rules.
Do not invent tag values.
If evidence is insufficient, use null for scalar fields and [] for list fields.
Output only valid JSON. No markdown, no explanations, no thinking traces.

Core rule:
- primary_doc_type is the document identity, single-choice.
- publication_status is release status, not document type.
- reading_lane means why we read it.
- artifact_focus means what it contributes or discusses.
- risk_domain and method_tags are optional in phase 1; fill only when explicit.

对每个字段给出 confidence（high/medium/low）。
对 primary_doc_type、publication_status、reading_lane、artifact_focus 给出 evidence 短片段。
```

**用户提示结构**：

```text
Vocabulary:
<只列合法值，不贴完整长文档>

Primary doc type decision order:
1. system/model/safety card / transparency report -> system_model_card
2. standard/guideline/code of practice -> standard_guideline
3. safety/risk/governance/deployment framework -> governance_framework
4. reusable benchmark/dataset/eval suite as main contribution -> benchmark_dataset_paper
5. third-party structural evaluation of a model/system/framework -> evaluation_report
6. leaderboard/dashboard/platform snapshot -> platform_snapshot
7. thesis -> thesis
8. technical object centered report -> technical_report
9. institutional trend/landscape/annual/capacity report -> institutional_report
10. survey/review/position paper -> survey_review
11. ordinary research article -> research_article
12. webpage/blog -> webpage_blog
13. workflow artifact / not literature / other as needed

Ambiguity rules:
<粘贴易混规则摘要，不超过 1200-1800 字>

Existing local context:
id:
title:
old_doc_type:
source_file_names:
arxiv_id:
doi:
venue:
url:

Document excerpt:
<content.md first 6000-8000 chars>
```

**输出 JSON 结构**：

```json
{
  "primary_doc_type": "evaluation_report",
  "publication_status": "institutional_release",
  "primary_source_actor_type": "evaluation_lab",
  "region": "US",
  "reading_lane": ["evaluation_method", "safety_case_method"],
  "artifact_focus": ["audit_finding", "safety_report"],
  "risk_domain": ["scheming", "evaluation_awareness"],
  "method_tags": ["evaluation_execution", "evaluation_awareness_testing"],
  "ingestion_state": "verified",
  "priority": "P1",
  "alternative_primary_doc_types": ["technical_report"],
  "evidence": {
    "primary_doc_type": "third-party evaluation of ...",
    "publication_status": "published by METR ...",
    "reading_lane": "evaluation protocol ...",
    "artifact_focus": "alignment evaluation ..."
  },
  "confidence": {
    "primary_doc_type": "high",
    "publication_status": "medium",
    "primary_source_actor_type": "high",
    "reading_lane": "high",
    "artifact_focus": "medium",
    "risk_domain": "medium",
    "method_tags": "low",
    "ingestion_state": "high",
    "priority": "medium"
  },
  "ambiguity_notes": "technical_report is possible, but the evaluator is third-party and the object is another organization's model"
}
```

**执行流程**：

```text
1. 查找 primary_doc_type IS NULL 的 works（或 --work-id / --force 指定）
2. 读取 content.md 前 8000 字符
3. 附加已有 metadata 上下文（title, doc_type, authors, year 等）
4. 调用 Ollama（与 metadata 脚本使用同一接口）
5. 解析 JSON，执行词汇表合法性校验（非法值设 null + 警告）
6. 计算 ambiguity_score（api/classification_ambiguity.py）
7. 写入 classification_extractions（--no-write 时仅打印）
8. 可选 --apply：只允许 `ambiguity_score <= 20` 且 `primary_doc_type` evidence 非空的结果自动批准；否则保持 pending
```

**CLI 参数**（与 metadata 脚本保持一致风格）：

```text
--limit N
--work-id W-xxxx
--force                  # 重新抽取已有分类的 work
--no-write               # 只打印，不写库
--apply                  # 批准低模糊度结果并回填
--ambiguity-threshold N  # 自动批准的上限（默认 20）
--model MODEL
--url URL
```

---

### 4.2 词汇表校验模块 `api/classification_vocab.py`（新建）

**职责**：集中维护所有合法词汇值，供抽取脚本校验和前端下拉渲染使用。

结构：

```python
VOCAB = {
    "primary_doc_type": [
        "research_article", "survey_review", "technical_report",
        "system_model_card", "evaluation_report", "standard_guideline",
        "governance_framework", "benchmark_dataset_paper", "institutional_report",
        "webpage_blog", "platform_snapshot", "thesis", "book_chapter",
        "workflow_artifact", "other_literature", "not_literature",
    ],
    "publication_status": [
        "published", "preprint", "working_paper", "draft",
        "living_document", "institutional_release", "webpage_release", "unknown",
    ],
    "primary_source_actor_type": [
        "frontier_ai_company", "domestic_ai_company", "evaluation_lab",
        "government_agency", "standards_body", "international_network",
        "academic_group", "civil_society_org", "platform_dashboard", "unknown",
    ],
    "region": ["US", "UK", "EU", "CN", "JP", "KR", "SG", "international", "unknown"],
    "reading_lane": [...],     # 完整列表来自规范 §4.1
    "artifact_focus": [...],   # 完整列表来自规范 §4.2
    "risk_domain": [...],      # 完整列表来自规范 §4.3，含版本号
    "method_tags": [...],      # 完整列表来自规范 §4.4，含版本号
    "ingestion_state": ["verified", "needs_review", "provisional", "excluded", "deprecated"],
    "priority": ["P0", "P1", "P2", "P3", "archive"],
    "canonical_file_format": ["pdf_native", "pdf_printed", "html", "markdown", "png", "txt", "mixed", "unknown"],
    "processing_flags": [...],  # 完整列表来自规范 §4.8
}

VOCAB_VERSIONS = {
    "risk_domain": "v1",
    "method_tags": "v1",
}

def validate_tag_value(tag_group: str, tag_value: str) -> bool:
    return tag_value in VOCAB.get(tag_group, [])

def get_vocab() -> dict:
    return VOCAB
```

---

## 五、前端层

### 5.1 `web/src/labels.js` 扩展

在现有 `DOC_TYPE_LABELS` 等映射基础上追加：

```javascript
export const PRIMARY_DOC_TYPE_LABELS = {
  research_article:       '研究论文',
  survey_review:          '综述/评述',
  technical_report:       '技术报告',
  system_model_card:      '系统卡/模型卡',
  evaluation_report:      '第三方评估报告',
  standard_guideline:     '标准/指南',
  governance_framework:   '治理框架',
  benchmark_dataset_paper:'基准/数据集论文',
  institutional_report:   '机构报告',
  webpage_blog:           '网页/博客',
  platform_snapshot:      '平台快照',
  thesis:                 '学位论文',
  book_chapter:           '书章',
  workflow_artifact:      '工作流产物',
  other_literature:       '其他文献',
  not_literature:         '非文献',
}

export const PUBLICATION_STATUS_LABELS = {
  published:             '已发表',
  preprint:              '预印本',
  working_paper:         '工作论文',
  draft:                 '草案',
  living_document:       '持续更新文档',
  institutional_release: '机构正式发布',
  webpage_release:       '网页发布',
  unknown:               '未知',
}

export const INGESTION_STATE_LABELS = {
  verified:     '已核验',
  needs_review: '待核查',
  provisional:  '暂留',
  excluded:     '已排除',
  deprecated:   '已废弃',
}

export const PRIORITY_LABELS = {
  P0:      '核心必读',
  P1:      '重要',
  P2:      '参考',
  P3:      '边缘',
  archive: '归档',
}

export const SOURCE_ACTOR_TYPE_LABELS = {
  frontier_ai_company:  '前沿AI企业',
  domestic_ai_company:  '国内AI企业',
  evaluation_lab:       '评估实验室',
  government_agency:    '政府机构',
  standards_body:       '标准组织',
  international_network:'国际网络',
  academic_group:       '学术机构',
  civil_society_org:    '公益/NGO',
  platform_dashboard:   '平台/排行榜',
  unknown:              '未知',
}

export const REGION_LABELS = {
  US:            '美国',
  UK:            '英国',
  EU:            '欧盟',
  CN:            '中国大陆',
  JP:            '日本',
  KR:            '韩国',
  SG:            '新加坡',
  international: '国际/多国',
  unknown:       '未知',
}

export const READING_LANE_LABELS = {
  framework_taxonomy:     '框架与分类',
  evaluation_method:      '评测方法',
  governance_method:      '治理方法',
  system_transparency:    '系统透明度',
  model_technical_profile:'模型技术特征',
  institutional_landscape:'机构生态',
  safety_case_method:     '安全论证',
  interpretability_method:'可解释性',
  background_theory:      '理论背景',
  literature_mapping:     '文献综述',
  workflow_support:       '工作流支持',
}
```

---

### 5.2 `Works.vue` 筛选变更

**方案**：新增折叠式"高级筛选"区域，不影响现有筛选栏布局。

高级筛选区域包含：

```text
主文档类型（primary_doc_type）  - 分组下拉，见下方分组设计
发布状态（publication_status）  - 下拉，8 个选项
入库状态（ingestion_state）     - 下拉，5 个选项
优先级（priority）              - 下拉，5 个选项
来源机构类型（primary_source_actor_type） - 下拉，10 个选项
地区（region）                  - 下拉，9 个选项
阅读用途（reading_lane）        - 多选 chip 组（单击切换选中）
```

**`primary_doc_type` 分组下拉设计**（避免 16 个选项的扁平列表）：

```
── 机构自述类 ──
  system_model_card    / 系统卡/模型卡
  technical_report     / 技术报告
  governance_framework / 治理框架

── 评估类 ──
  evaluation_report         / 第三方评估报告
  benchmark_dataset_paper   / 基准/数据集论文

── 规范类 ──
  standard_guideline   / 标准/指南

── 报告类 ──
  institutional_report / 机构报告
  platform_snapshot    / 平台快照

── 学术类 ──
  research_article     / 研究论文
  survey_review        / 综述/评述
  thesis               / 学位论文

── 网页类 ──
  webpage_blog         / 网页/博客

── 管理类 ──
  workflow_artifact    / 工作流产物
  not_literature       / 非文献
  other_literature     / 其他
```

API 参数透传方式：高级筛选通过 `params.primary_doc_type` 等新参数追加到现有 `getWorks()` 调用，不改变调用结构。

---

### 5.3 `WorkDetail.vue` 变更

在元数据区域新增"分类信息"子区块，与现有"元数据"子区块平级：

```
── 分类信息 ──
  主文档类型：[evaluation_report] 第三方评估报告
  发布状态：  [institutional_release] 机构正式发布
  来源机构：  [evaluation_lab] 评估实验室
  地区：      [US] 美国
  优先级：    [P1] 重要
  入库状态：  [verified] 已核验

  阅读用途：  [evaluation_method] [safety_case_method]
  贡献对象：  [audit_finding] [safety_report]
  风险领域：  [scheming] [evaluation_awareness]
  方法标签：  [evaluation_execution] [evaluation_awareness_testing]
```

标签以 chip 形式展示，点击可跳转到该标签的筛选结果页。

编辑模式下：互斥字段用下拉，多值字段用多选 chip 组（可添加/删除）。

---

### 5.4 新页面：`ClassificationReview.vue`

参照 `MetadataReview.vue` 的三栏布局（列表 / 详情 / PDF 预览），差异点：

**列表栏**：按 `ambiguity_score` 降序排列，顶部显示：

```
[高模糊度 N] [中 N] [低 N] | [批量批准低模糊度]
```

**详情栏**：

```
── 分类候选字段 ──（来自 extracted_json）
  每行：字段名 | 候选值（可编辑）| 置信度 badge
  特别标注：与现有 doc_type / 现有已有标签不一致的字段（高亮显示冲突）

── 模糊原因 ──
  列出 ambiguity_reasons

── 操作栏 ──
  [批准] [需修正] [拒绝]
  审核备注输入框
```

路由注册：`/classification`，侧边栏新增导航项"分类审核"。

---

## 六、实施分阶段计划

### 6.0 多子 agent 与双轮审核放行机制

本计划允许本地模型开启多个子 agent，但由于模型能力有限，每个 Phase 必须配置至少一个审核子 agent，并完成两轮审核后才能放行到下一阶段。

建议角色：

```text
Implementation Agent
  负责执行当前 Phase 的代码/文档/脚本修改。

Schema/API Review Agent
  第一轮审核。重点检查 schema 兼容性、API 参数兼容性、迁移幂等性、测试是否覆盖破坏性风险。

Domain Classification Review Agent
  第二轮审核。重点检查分类规范语义是否被误用，尤其是 primary_doc_type / publication_status / reading_lane / artifact_focus 是否混淆。
```

放行规则：

```text
1. Implementation Agent 完成 Phase 任务并运行计划内测试。
2. Schema/API Review Agent 独立读取 diff 和测试结果，输出 pass / needs_fix。
3. Implementation Agent 修复第一轮问题并再次运行相关测试。
4. Domain Classification Review Agent 独立审核分类语义、词汇表、UI 文案和迁移规则，输出 pass / needs_fix。
5. Implementation Agent 修复第二轮问题并再次运行相关测试。
6. 两轮审核均 pass 后，才能进入下一 Phase。
```

任何一轮审核不得只写"看起来没问题"。必须至少覆盖：

```text
- 本阶段改了哪些文件
- 是否破坏旧 API / 旧字段 / 旧测试
- 是否有未迁移或未初始化的列/表
- 是否存在分类语义混用
- 是否有必须人工确认的数据被自动标记为 verified / approved
```

### Phase 1：数据库结构 + 基础 API + 旧字段迁移 ✅ PASS

**目标**：所有 `works` 都有明确的分类迁移状态；能高置信判断的写入 `primary_doc_type`，不能判断的保持 NULL 并标注 `ingestion_state='needs_review'`。筛选 API 支持新参数，前端显示新字段。

**任务清单**：

```text
DB-1   执行 migrate_add_classification_columns.py（DDL）
DB-2   执行 migrate_backfill_doc_type.py（旧字段 + 文件名启发式预填）
API-1  WorkUpdate 新增四字段（primary_doc_type / publication_status / ingestion_state / priority）
API-2  list_works 新增四个筛选参数
API-3  get_work 响应追加新字段
FE-1   labels.js 追加新映射
FE-2   Works.vue 新增高级筛选折叠区（primary_doc_type + publication_status + ingestion_state + priority）
FE-3   WorkDetail.vue 分类信息子区块（只读显示）
TEST-1 test_api.py 新增筛选参数测试
```

**验收标准**：

- `GET /api/works?primary_doc_type=system_model_card` 返回正确过滤结果
- `GET /api/works/{id}` 返回中包含 `primary_doc_type` 字段
- `migrate_backfill_doc_type.py --dry-run` 输出自动映射、候选和待审统计
- 旧 `doc_type` 字段、旧 `doc_type` 筛选和旧前端显示仍可用
- 现有所有测试仍然通过

---

### Phase 2：多值标签表 + 来源机构 + 地区 + 手动打标签 ✅ PASS

**目标**：支持通过 API 和前端对文献手动添加多值标签，标签可用于筛选。

**任务清单**：

```text
DB-3   建立 work_classification_tags 表（DDL）
DB-4   扩展 work_relations：relation_category / source / created_at，并增加 parent / child / companion 类型
API-4  新建 api/routes/classification.py（标签 CRUD + 词汇表接口）
API-5  classification_vocab.py（词汇表模块）
API-6  list_works 支持 reading_lane / artifact_focus / risk_domain 多值标签筛选
API-7  WorkUpdate 新增 primary_source_actor_type / region / canonical_file_format
API-8  relations API 支持 relation_category，旧请求不传时默认 content
FE-4   WorkDetail.vue 标签编辑功能（多选 chip 组）
FE-5   Works.vue 高级筛选新增来源机构 / 地区 / 阅读用途 chip 筛选
TEST-2 分类路由测试
```

**验收标准**：

- 可通过 API 为某 work 添加 `reading_lane=evaluation_method` 标签
- `GET /api/works?reading_lane=evaluation_method` 返回包含该标签的 works
- `GET /api/classification/vocab` 返回完整词汇表 JSON
- `POST /api/relations` 不传 `relation_category` 时保持旧行为
- 可创建 `relation_category=document_structure, relation_type=companion` 的关系

---

### Phase 3：模型分类抽取 + ClassificationReview 页面 ⚠️ 已实现+后端验证（未端到端验证）

**目标**：通过 Ollama 批量生成分类候选，在专用页面审核，approved 后自动回填到标签表。

**任务清单**：

```text
DB-5   建立 classification_extractions 表（DDL）
SCRIPT-1  literature_classification_extract.py
SCRIPT-2  classification_ambiguity.py（ambiguity 评分模块）
API-9  classification extractions 的 CRUD + 审核路由
FE-6   新建 ClassificationReview.vue 页面
FE-7   router.js 注册 /classification 路由
FE-8   AppLayout.vue 侧边栏新增"分类审核"导航项
TEST-3 分类抽取 + 审核流程测试
```

**验收标准**：

- 运行 `literature_classification_extract.py --limit 5 --no-write` 能输出有效分类 JSON
- `POST /api/classification/extractions/{ce_id}/review` 审核后能将标签写入 `work_classification_tags`
- ClassificationReview 页面能正确渲染候选列表和详情
- `ambiguity_score` 不因 `risk_domain` / `method_tags` 为空而直接升高
- 自动批准只作用于 `ambiguity_score <= 20` 且主类型 evidence 非空的候选

---

### Phase 4：废弃旧 `doc_type` + Dashboard 统计升级 🚫 未启动（blocked: coverage 48.6% < 95%）

**目标**：`primary_doc_type` 标注率 ≥ 95% 后，废弃旧 `doc_type` 列，升级 Dashboard 统计维度。

**任务清单**：

```text
DB-6   验证 primary_doc_type IS NOT NULL 覆盖率
DB-7   标记 doc_type 列为 deprecated（在 API 文档中），暂不物理删除
FE-9   Dashboard.vue 类型分布改为展示 primary_doc_type
FE-10  Works.vue 旧类型筛选下拉切换为新分组下拉
TEST-4 全量测试，确认无旧字段依赖残留
```

**验收标准**：

- Dashboard 类型分布基于 `primary_doc_type`
- `doc_type` 仍存在于 DB 但 API 响应中标注 deprecated
- 旧 `doc_type` 筛选参数仍可用（兼容旧客户端）

---

## 七、风险点与注意事项

### 7.1 `doc_type: preprint` 迁移的歧义性

当前库中 `doc_type=preprint` 的 works 只能稳定映射为 `publication_status=preprint`。`primary_doc_type` 不应自动设为 `research_article`，因为 arXiv 上可能是模型技术报告、框架论文、benchmark/dataset paper 或普通研究论文。迁移脚本应将这批设为 `ingestion_state=needs_review`，`primary_doc_type` 保持 NULL，除非文件名/标题有高置信规则。

### 7.2 `ingestion_state` 与 `read_status` 的联动边界

两个字段不合并，但需要在 UI 上明确展示语义差异：

```
read_status=quarantined     → 物理上被隔离，文件移入 _quarantine/
ingestion_state=excluded    → 逻辑上不作为正式文献，但文件不一定移动

两者可以同时为真，也可以独立为真。
```

代码层需要确保 `quarantine_work()` 不会自动修改 `ingestion_state`，反之亦然。

### 7.3 多值标签的"approved"门槛

`work_classification_tags` 中 `review_status=approved` 的标签才会参与筛选。模型生成的标签初始 `review_status=pending`，通过 ClassificationReview 审核后才变为 `approved`。手动添加的标签（通过 WorkDetail.vue）默认 `review_status=approved`，`source=human`。

### 7.4 词汇扩充的向后兼容

当 `risk_domain` 或 `method_tags` 词汇表新增值时：

- 旧版本词汇值的历史标签不受影响（`vocab_version` 字段记录标注时的版本）
- 筛选时默认包含所有版本的标签，除非前端显式按 `vocab_version` 过滤
- 不触发批量迁移，只在 `classification_vocab.py` 末尾追加值并升级 `VOCAB_VERSIONS`

### 7.5 Phase 1 的 `doc_type` 兼容性

Phase 1 完成后，`list_works` 中旧的 `doc_type` 筛选参数继续有效（用于兼容旧请求），但内部同时追加 `primary_doc_type` 筛选。前端在 Phase 4 之前应同时支持两套，以 `primary_doc_type` 为主显示，`doc_type` 作为回退。

### 7.6 文件名前缀启发式不能直接等于最终分类

当前真实 `source_files.original_name` 中存在 `[I6g]`、`E6_`、`G16_`、`C7_`、`【R】` 等旧整理前缀。它们对迁移非常有帮助，但不是规范本体的一部分，不能把 `E*`、`G*`、`I*` 简单等同于最终 `primary_doc_type`。

建议原则：

```text
文件名前缀 + 标题关键词 + 旧 doc_type 三者一致 → 可中高置信预填。
只有文件名前缀命中 → 只生成候选，不直接 verified。
旧 doc_type 与文件名强规则冲突 → 进入高优先级人工审核。
```

### 7.7 关系表扩展的兼容边界

`work_relations` 当前主键是 `(work_id_a, work_id_b, relation_type)`。本计划第一版只新增 `relation_category`，不改变主键。如果未来同一对 work 需要同时存在两个同名 `relation_type` 但不同 category 的关系，再做第二次迁移。当前不要为了理论完整性提前重建关系表，避免破坏去重闭环。

---

## 八、本地模型逐阶段执行提示词

以下提示词可直接交给本地模型。每个 Phase 建议开启 3 个子 agent：一个实现 agent、两个审核 agent。由于本地模型能力有限，每阶段必须完成两轮审核并修复后才能放行。

### 8.1 Phase 1 提示词：数据库字段、旧值迁移、基础筛选

```text
你是本地代码实施 agent。请在当前项目中完成 classification_integration_plan_v1.md 的 Phase 1。

范围：
1. 新增幂等 migration：scripts/migrate_add_classification_columns.py。
2. 新增幂等迁移/预填脚本：scripts/migrate_backfill_doc_type.py。
3. 扩展 works 表字段：
   primary_doc_type, publication_status, ingestion_state, priority,
   is_core_literature, primary_source_actor_type, region, canonical_file_format。
4. 保持旧 doc_type 字段和旧 API 行为完全兼容。
5. list_works 新增 primary_doc_type / publication_status / ingestion_state / priority 筛选。
6. get_work / update_work 支持新字段。
7. 前端 labels.js、Works.vue、WorkDetail.vue 增加第一批分类字段展示和筛选。
8. tests/test_api.py 增加基础筛选测试。

迁移规则：
- system_card -> system_model_card，可 high confidence。
- preprint 只自动写 publication_status=preprint，不自动写 primary_doc_type。
- benchmark 只作为 medium 候选，除非文件名/标题强命中 benchmark/dataset。
- paper/report 默认 needs_review，不直接判主类型。
- 使用 source_files.original_name 的关键词和前缀启发式，但中低置信不得标记 verified。

约束：
- 不删除 doc_type。
- 不破坏现有测试。
- migration 必须可重复运行。
- dry-run 必须输出计划执行的 DDL/DML 和统计。

完成后运行：
uv run python -m pytest tests/test_api.py
python scripts/migrate_add_classification_columns.py --dry-run
python scripts/migrate_backfill_doc_type.py --dry-run

输出：
- 修改文件列表
- dry-run 统计
- 测试结果
- 已知未解决问题
```

**Phase 1 第一轮审核提示词（Schema/API Review Agent）**

```text
你是第一轮审核 agent。请只审核 Phase 1 的实现 diff 和测试输出，不新增功能。

重点检查：
1. migration 是否幂等，重复运行是否安全。
2. 新字段是否均可 NULL，不会破坏旧数据。
3. 旧 doc_type 字段、旧 doc_type 筛选、旧 API 响应是否仍兼容。
4. list_works / get_work / update_work 是否处理新字段一致。
5. tests/test_api.py 是否覆盖新增筛选。
6. 是否有未经审核就把 paper/report/preprint 大批标为 verified 的风险。

输出格式：
- verdict: pass / needs_fix
- blocking issues
- non-blocking suggestions
- required test evidence
```

**Phase 1 第二轮审核提示词（Domain Classification Review Agent）**

```text
你是第二轮分类语义审核 agent。请审核 Phase 1 迁移规则是否符合《classification-methodology.md》。

重点检查：
1. primary_doc_type 是否被用于文献身份，而不是发布状态/主题/阅读用途。
2. preprint 是否只进入 publication_status。
3. benchmark 是否区分主贡献 benchmark_dataset_paper 与 artifact_focus benchmark。
4. paper/report 是否没有被粗暴自动映射。
5. 文件名前缀 [I*]/E*/G*/C*/【R】 是否只作为候选或辅助 evidence。
6. ingestion_state 是否没有与 read_status 混用。

输出格式：
- verdict: pass / needs_fix
- semantic issues
- suggested rule changes
- examples needing manual review
```

### 8.2 Phase 2 提示词：多值标签、词汇表、关系表扩展

```text
你是本地代码实施 agent。请完成 classification_integration_plan_v1.md 的 Phase 2。

范围：
1. 建立 work_classification_tags 表，支持多值标签。
2. 不新建 work_doc_relations；改为扩展 work_relations：
   relation_category, source, created_at。
3. 扩展 relation_type 合法值：parent, child, companion。
4. 新建 api/classification_vocab.py，集中维护合法词汇表。
5. 新建 api/routes/classification.py：
   - 标签 CRUD
   - 批量添加标签
   - 标签审核
   - vocab 只读接口
6. list_works 支持 reading_lane / artifact_focus / risk_domain 多值标签筛选。
7. WorkDetail 支持手动添加/删除标签，手动标签默认 source=human, review_status=approved。
8. 保持旧 Relations 页面和旧 relations API 行为兼容。
9. 增加测试。

约束：
- work_classification_tags 中只有 review_status=approved 的标签参与筛选。
- 不改变 work_relations 主键。
- 旧 POST /api/relations 请求不传 relation_category 时默认 content。

完成后运行：
uv run python -m pytest tests/test_api.py

输出：
- 修改文件列表
- 新增 API 示例
- 测试结果
- 已知未解决问题
```

**Phase 2 第一轮审核提示词（Schema/API Review Agent）**

```text
你是第一轮审核 agent。请审核 Phase 2 的 schema/API 兼容性。

重点检查：
1. work_classification_tags 表是否幂等创建。
2. tag_group/tag_value 是否由应用层校验，DB 不用硬 CHECK。
3. list_works 的多值标签筛选是否只使用 approved 标签。
4. work_relations 扩展是否不破坏旧去重、Relations 页面和 tests。
5. 旧关系 API 不传 relation_category 是否仍可用。
6. 新 classification 路由是否被 main.py 注册且测试覆盖。

输出格式：
- verdict: pass / needs_fix
- blocking issues
- compatibility risks
- required test evidence
```

**Phase 2 第二轮审核提示词（Domain Classification Review Agent）**

```text
你是第二轮分类语义审核 agent。请审核 Phase 2 的词汇表和 UI/API 语义。

重点检查：
1. reading_lane 是否表示阅读用途。
2. artifact_focus 是否表示贡献/讨论对象。
3. risk_domain 与 method_tags 是否没有混用。
4. processing_flags 是否没有与 ingestion_state 混用。
5. relation_category 的 content/versioning/document_structure 是否能解释 parent/child/companion/part_of/version_of/supersedes。
6. UI 文案是否避免把所有标签统称为“类型”。

输出格式：
- verdict: pass / needs_fix
- semantic issues
- vocabulary issues
- suggested UI wording changes
```

### 8.3 Phase 3 提示词：模型分类候选与 ClassificationReview

```text
你是本地代码实施 agent。请完成 classification_integration_plan_v1.md 的 Phase 3。

范围：
1. 建立 classification_extractions 表。
2. 新建 api/classification_ambiguity.py。
3. 新建 scripts/literature_classification_extract.py，仿照 literature_metadata_extract.py。
4. 提示策略使用短 system prompt + 规范摘录 + 固定词汇表 + 文献上下文，不把完整规范全文塞入 system prompt。
5. 第一版只重点抽：
   primary_doc_type, publication_status, primary_source_actor_type, region,
   reading_lane, artifact_focus, ingestion_state, priority。
   risk_domain 和 method_tags 只有明确证据时填写，否则 []。
6. 新增 classification extraction 审核 API。
7. 新建 ClassificationReview.vue 页面。
8. approved 后写入 works 和 work_classification_tags。
9. 自动批准只允许 ambiguity_score <= 20 且 primary_doc_type evidence 非空。
10. 增加测试。

模型：
qwen3:4b-instruct-2507-q4_K_M

完成后运行：
uv run python -m pytest tests/test_api.py
python scripts/literature_classification_extract.py --limit 5 --no-write

输出：
- 修改文件列表
- 5 条 no-write 输出摘要
- ambiguity_score 分布
- 测试结果
- 已知未解决问题
```

**Phase 3 第一轮审核提示词（Schema/API Review Agent）**

```text
你是第一轮审核 agent。请审核 Phase 3 的抽取、审核和回填链路。

重点检查：
1. classification_extractions 是否只保存候选，不自动污染 works。
2. approved/apply 是否精确作用于当前 CE id。
3. 自动批准阈值是否正确，且 evidence 为空不能自动批准。
4. ambiguity_score 是否不因 risk_domain/method_tags 为空而直接升高。
5. 脚本 --no-write 是否绝不写库。
6. API 测试是否覆盖 approve / needs_fix / rejected / apply。

输出格式：
- verdict: pass / needs_fix
- blocking issues
- data corruption risks
- required test evidence
```

**Phase 3 第二轮审核提示词（Domain Classification Review Agent）**

```text
你是第二轮分类语义审核 agent。请审核 Phase 3 的 prompt、输出 JSON 和样例结果。

重点检查：
1. prompt 是否明确 primary_doc_type 与 publication_status 分离。
2. prompt 是否没有要求小模型记住整篇规范。
3. primary_doc_type 判定优先级是否与规范一致。
4. evaluation_report / technical_report / institutional_report 是否能区分。
5. benchmark_dataset_paper 与 artifact_focus=benchmark 是否能区分。
6. system_model_card 与 technical_report 是否能区分。
7. 输出是否只使用合法词汇。
8. 5 条 no-write 样例中是否有明显误判。

输出格式：
- verdict: pass / needs_fix
- prompt issues
- semantic misclassification examples
- required prompt/rule edits
```

### 8.4 Phase 4 提示词：Dashboard 升级与旧字段降级

```text
你是本地代码实施 agent。请完成 classification_integration_plan_v1.md 的 Phase 4。

前置条件：
- primary_doc_type 覆盖率 >= 95%。
- Phase 1-3 均已通过两轮审核。

范围：
1. Dashboard 类型分布改用 primary_doc_type。
2. Works 默认显示 primary_doc_type，doc_type 只作为兼容回退。
3. 旧 doc_type 筛选参数继续保留。
4. API 文档或 README 标注 doc_type deprecated，但不物理删除。
5. 增加覆盖率检查脚本或 healthcheck 项。
6. 增加测试。

完成后运行：
uv run python -m pytest tests/test_api.py

输出：
- primary_doc_type 覆盖率
- 修改文件列表
- 测试结果
- 仍依赖 doc_type 的文件清单
```

**Phase 4 第一轮审核提示词（Schema/API Review Agent）**

```text
你是第一轮审核 agent。请审核 Phase 4 的兼容性。

重点检查：
1. doc_type 是否未被物理删除。
2. 旧 doc_type API 参数是否仍可用。
3. Dashboard 和 Works 是否有 primary_doc_type 回退逻辑。
4. 覆盖率不足 95% 时是否阻止废弃展示。
5. 测试是否覆盖新旧筛选共存。

输出格式：
- verdict: pass / needs_fix
- compatibility issues
- required test evidence
```

**Phase 4 第二轮审核提示词（Domain Classification Review Agent）**

```text
你是第二轮分类语义审核 agent。请审核 Phase 4 的展示和统计口径。

重点检查：
1. Dashboard 的“类型分布”是否明确指 primary_doc_type。
2. publication_status 是否没有混入类型统计。
3. benchmark / preprint / report 的旧口径是否不会继续误导用户。
4. UI 是否能让用户看出字段来源和待审状态。

输出格式：
- verdict: pass / needs_fix
- semantic/statistical issues
- suggested wording changes
```

---

## 九、关键文件变更汇总

| 文件 | 变更类型 | Phase |
|---|---|---|
| `scripts/migrate_add_classification_columns.py` | 新建 | 1 |
| `scripts/migrate_backfill_doc_type.py` | 新建 | 1 |
| `scripts/migrate_import_filename_metadata.py` | 新建（可选） | 1/2 |
| `scripts/literature_classification_extract.py` | 新建 | 3 |
| `api/models.py` | 扩展 | 1/2 |
| `api/routes/works.py` | 扩展 | 1/2 |
| `api/routes/classification.py` | 新建 | 2 |
| `api/classification_ambiguity.py` | 新建 | 3 |
| `api/classification_vocab.py` | 新建 | 2 |
| `api/main.py` | 扩展（注册新路由） | 2 |
| `api/db.py` | 扩展（新表的 ensure 函数） | 1/2 |
| `api/routes/relations.py` | 扩展（relation_category 与结构关系） | 2 |
| `web/src/labels.js` | 扩展 | 1 |
| `web/src/api.js` | 扩展（新 API 调用函数） | 2 |
| `web/src/router.js` | 扩展（新路由） | 3 |
| `web/src/components/AppLayout.vue` | 扩展（新导航项） | 3 |
| `web/src/views/Works.vue` | 扩展（高级筛选） | 1/2 |
| `web/src/views/WorkDetail.vue` | 扩展（分类信息区块） | 1/2 |
| `web/src/views/ClassificationReview.vue` | 新建 | 3 |
| `tests/test_api.py` | 扩展 | 1/2/3 |
| `pyproject.toml` | 无需改动 | — |

---

## 十、实施进度跟踪（截至 2026-06-08）

### Phase 1：数据库结构 + 基础 API + 旧字段迁移 — ✅ PASS

**状态**：已完成，双轮审核均通过。

| 任务 | 状态 | 说明 |
|---|---|---|
| DB-1 DDL 迁移 | ✅ | 29 条 SQL 幂等执行，works 表新增 8 列 + 2 张新表 |
| DB-2 旧字段回填 | ✅ | 31 条高置信自动映射（19 system_model_card + 12 technical_report），107 条 needs_review |
| API-1~3 works API 扩展 | ✅ | WorkUpdate 新增字段、list_works 筛选、get_work 返回分类字段 |
| FE-1~3 前端基础 | ✅ | labels.js 映射、Works.vue 高级筛选、WorkDetail.vue 分类信息区块 |
| TEST-1 测试 | ✅ | 11 个新测试，全量 62 passed |

**审核结论**：
- Schema/API Review：PASS
- Domain Classification Review：PASS（修复 1 轮：benchmark 映射降级、arXiv 预印本规则移除）

**已知遗留**：`migrate_add_classification_columns.py --dry-run` 已修复表存在性判断逻辑。

---

### Phase 2：多值标签表 + 来源机构 + 地区 + 手动打标签 — ✅ PASS

**状态**：已完成，双轮审核均通过。

| 任务 | 状态 | 说明 |
|---|---|---|
| DB-3~4 标签表 + 关系扩展 | ✅ | work_classification_tags 表、work_relations 新增 relation_category/source/created_at |
| API-4~8 分类路由 | ✅ | classification.py 标签 CRUD + 词汇表、list_works 多值标签筛选 |
| FE-4~5 前端标签编辑 | ✅ | WorkDetail.vue 标签增删、Works.vue 阅读用途筛选 |
| TEST-2 测试 | ✅ | 11 个新测试 |

**审核结论**：
- Schema/API Review：PASS
- Domain Classification Review：PASS（修复 1 轮：alignment_tax 命名、TAG_GROUP_LABELS、质量标记标题、关系类型标签）

---

### Phase 3：模型分类抽取 + ClassificationReview 页面 — ✅ completed

**状态**：代码实现完成，真实库已写入 extraction 数据（373 条，119 approved / 0 pending / 254 rejected），分类积压已清空，词汇表已同步（1842 条 approved tags）。

| 任务 | 状态 | 说明 |
|---|---|---|
| DB-5 classification_extractions 表 | ✅ | 已在 Phase 1 DDL 中创建 |
| SCRIPT-1 classification_extract.py | ✅ | Ollama 抽取脚本，5/5 works 成功产出有效 JSON（需绕过代理） |
| SCRIPT-2 classification_ambiguity.py | ✅ | 0-100 模糊度评分，risk_domain/method_tags 为空不计入 |
| API-9 抽取 CRUD + 审核路由 | ✅ | list/get/review/batch-approve，含幂等保护和 evidence 门控 |
| FE-6~8 ClassificationReview.vue | ✅ | 模糊度筛选、中文标签、审核操作栏 |
| TEST-3 测试 | ✅ | 12 个测试（含合成数据 fixture），74 passed / 1 skipped |

**审核结论**：
- Schema/API Review：PASS（2 轮）
- Domain Classification Review：PASS（2 轮，修复 batch approve evidence 门控、ambiguity 边界重叠、select 中文标签）

**已修复问题**：
1. Ollama 代理绕过：`_get_opener()` 对 localhost URL 绕过 `http_proxy`
2. batch_approve 只标记实际 applied 的行（approved_ids 追踪）
3. 幂等保护：已 applied 的 extraction 重新 approve 直接返回
4. migration dry-run 正确显示表存在状态
5. 测试断言增强：`test_review_extraction_approved_writes_tags` 明确验证 tag 写入

**遗留 caveat**：
- 真实库 `classification_extractions = 0`，`work_classification_tags = 0`
- 合成 fixtures 验证 API 行为，非真实数据审核/apply
- 首次全量抽取（`--limit 200`）因 Ollama 冷启动超时中断，需增加超时或分批执行

---

### Phase 4：废弃旧 `doc_type` + Dashboard 统计升级 — 🚫 blocked

**状态**：未开始，被 `primary_doc_type` 覆盖率阻塞。

| 条件 | 当前值 | 目标 | 状态 |
|---|---|---|---|
| `primary_doc_type` 覆盖率 | 67/138 = 48.6% | ≥ 95% | ❌ 未达标 |

**解锁路径**：Phase 3 真实抽取 + 审核完成后自动解锁。

---

## 十一、审核人配合指南

### 当前需要审核人做什么

Phase 3 代码已完成，但**真实数据尚未入库**。下一步需要审核人配合完成以下工作：

#### 步骤 1：运行小批量抽取（建议 5-10 篇）

```bash
# 先确认 Ollama 可用
curl http://localhost:11435/api/tags

# 小批量测试（不写库）
python scripts/literature_classification_extract.py --limit 5 --no-write

# 确认输出合理后，写入库
python scripts/literature_classification_extract.py --limit 5 --apply
```

**预期**：每篇产出 `primary_doc_type`、`publication_status`、`reading_lane`、`artifact_focus` 等字段，低模糊度（<20）的自动写入 works 表和 tags 表。

**注意**：首次调用 Ollama 有模型加载冷启动（30-60 秒），脚本默认超时 300 秒。如遇超时，可增加 `--timeout 600`。

#### 步骤 2：在 ClassificationReview 页面人工审核

访问 `http://localhost:5173/classification`（需先启动前端 `npm run dev`）：

1. **查看待审核列表**：按模糊度降序排列，高模糊度优先处理
2. **逐条审核**：
   - 检查 `primary_doc_type` 是否正确（与文献实际类型一致）
   - 检查 `reading_lane` 和 `artifact_focus` 是否合理
   - 如有错误，直接在编辑区修改候选值
   - 点击"批准"（正确）或"拒绝"（明显错误）
3. **批量处理**：低模糊度（<20）可点击"批量批准低模糊度"

#### 步骤 3：逐步扩大抽取规模

审核通过 5-10 篇后，可逐步扩大：

```bash
# 50 篇
python scripts/literature_classification_extract.py --limit 50 --apply

# 全量（跳过已有 extraction 的）
python scripts/literature_classification_extract.py --limit 200 --apply
```

每批完成后在 `/classification` 页面审核，逐步将 `primary_doc_type` 覆盖率推至 95%。

#### 步骤 4：确认进入 Phase 4

当 `primary_doc_type` 覆盖率 ≥ 95% 后，通知我执行 Phase 4：
- Dashboard 统计切换为 `primary_doc_type` 维度
- `doc_type` 标记为 deprecated（不物理删除）
- Works.vue 旧类型筛选切换为新分组

---

### 审核重点（给审核人的检查清单）

审核 ClassificationReview 页面时，重点关注：

1. **primary_doc_type 准确性**：
   - 系统卡/模型卡 vs 第三方评估报告的区分
   - 技术报告 vs 研究论文的区分
   - 基准/数据集论文 vs 评测执行的区分

2. **publication_status 准确性**：
   - 已发表 vs 预印本 vs 机构正式发布

3. **reading_lane 合理性**：
   - 是否反映了"为什么读这篇文献"
   - 是否与文献实际内容匹配

4. **artifact_focus 合理性**：
   - 是否反映了"这篇文献贡献了什么"

5. **ambiguity_score 参考**：
   - 高模糊度（≥50）：必须人工逐条审核
   - 中模糊度（20-49）：建议人工审核
   - 低模糊度（<20）：可批量批准，但仍需抽查

---

## 十二、后续工作清单

### 我（Implementation Agent）需要做的

| 优先级 | 任务 | 说明 |
|---|---|---|
| P0 | 增加抽取脚本超时 + 冷启动处理 | 首次调用 Ollama 模型加载慢，需增加默认超时或添加 warm-up ping |
| P0 | 分批执行全量抽取 | `--limit 200` 需分批执行（每批 20-30 篇），避免单次超时 |
| P1 | 抽取脚本错误重试 | 单篇失败不应中断整个批次，需添加 try/except + 重试逻辑 |
| P1 | 前端 mojibake 确认 | ClassificationReview.vue 中文在 Read 工具中正常（UTF-8），需确认 `npm run dev` 在浏览器中显示正常 |
| P2 | 抽取结果质量统计脚本 | 统计各 `primary_doc_type` 分布、平均模糊度、置信度分布，辅助判断抽取质量 |
| P2 | Phase 4 前置检查脚本 | 自动检测覆盖率是否达到 95%，列出未标注文献清单 |

### 审核人需要做的

| 优先级 | 任务 | 说明 |
|---|---|---|
| P0 | 运行小批量抽取并审核 | 5-10 篇，验证抽取质量，确认流程可用 |
| P0 | 审核 ClassificationReview 页面 | 逐条检查候选分类，批准/拒绝/修正 |
| P1 | 逐步扩大抽取规模 | 每批 20-50 篇，审核后继续 |
| P1 | 确认词汇表完整性 | 检查 `classification_vocab.py` 中的词汇是否覆盖所有文献类型 |
| P2 | 确认进入 Phase 4 | 覆盖率达标后通知执行 Phase 4 |
