# 迁移与数据管理全景分析

> 生成时间：2026-07-08
> 范围：数据库 schema、文件存储、迁移机制、一致性校验、备份/导出/导入/同步

---

## 1. 系统资产全景

### 1.1 数据库：19 张表

数据库文件：`literature.sqlite`（SQLite，WAL 模式），路径由 `api/db.py` 硬编码为 `<repo_root>/literature.sqlite`。

| # | 表名 | 行数级别 | 核心职责 | 创建来源 |
|---|------|---------|---------|---------|
| 1 | `works` | ~150 | 文献主实体 | `ensure_core_schema()` |
| 2 | `source_files` | ~160 | 物理 PDF 文件索引 | `ensure_core_schema()` |
| 3 | `literature_parse_runs` | ~150 | MinerU 解析任务 | `ensure_core_schema()` |
| 4 | `metadata_extractions` | ~100 | LLM 元数据提取 | 无 CREATE 脚本（手动建表 + runtime ALTER） |
| 5 | `classification_extractions` | ~50 | 分类提取结果 | `migrate_add_classification_columns.py` |
| 6 | `work_classification_tags` | ~200 | 分类标签 | `migrate_add_classification_columns.py` |
| 7 | `work_relations` | ~20 | 文献间关系 | `parser/scripts/literature_migrate.py` |
| 8 | `work_codes` | ~30 | 操作性标记 | `parser/scripts/literature_migrate.py` |
| 9 | `duplicate_groups` | ~20 | 重复组 | `ensure_core_schema()` |
| 10 | `duplicate_candidates` | ~40 | 重复候选 | `ensure_core_schema()` |
| 11 | `intake_candidates` | ~100 | 采集候选队列 | `migrate_add_intake_candidates.py` |
| 12 | `collection_topics` | ~10 | 检索主题 | `migrate_add_collection_topics.py` |
| 13 | `discovery_runs` | ~10 | 检索执行记录 | `migrate_add_discovery.py` |
| 14 | `discovery_hits` | ~50 | 检索命中结果 | `migrate_add_discovery.py` |
| 15 | `analysis_runs` | ~5 | 方法论分析 | `migrate_add_analysis_runs.py` |
| 16 | `parse_artifacts` | ~100 | 解析产物索引 | `parser/scripts/literature_inventory.py` |
| 17 | `migration_meta` | ~5 | parser 迁移元数据 | `parser/scripts/literature_migrate.py` |
| 18 | `inventory_meta` | ~5 | 库清单元数据 | `parser/scripts/literature_inventory.py` |
| 19 | `library_migration_files` | ~150 | 旧库迁移记录 | `ensure_core_schema()` + `literature_migrate.py` |

### 1.2 文件存储结构

```
works/{work_id}/
├── source/                     # 活跃 PDF（source_files.status='active'）
├── parsed/mineru/{sfid}/       # MinerU 解析输出
│   ├── content.json
│   ├── content.md
│   └── package.zip
├── metadata.json
├── analyses/
└── notes/

_collector_cache/               # 采集候选暂存 PDF
_inbox/                         # 手动投放区
_archive/                       # 归档（已入库/已去重/坏源）
_duplicates/                    # SHA256 精确重复
_quarantine/                    # 隔离区（坏源/孤儿/重复合并后）
```

### 1.3 数据库 ↔ 文件映射关系

| DB 表 | 文件路径来源 | 说明 |
|-------|-------------|------|
| `works.id` | `works/{id}/` 目录名 | 一一对应 |
| `source_files.source_path` | `works/{work_id}/source/{filename}` | 绝对路径 |
| `source_files.relative_source_path` | 同上（相对路径） | 两列冗余 |
| `source_files.content_sha256` | PDF 文件 SHA256 | 入库时计算，后续不再校验 |
| `literature_parse_runs.content_md_path` | `works/{wid}/parsed/mineru/{sfid}/content.md` | |
| `literature_parse_runs.content_json_path` | `works/{wid}/parsed/mineru/{sfid}/content.json` | |
| `intake_candidates.local_pdf_path` | `_collector_cache/IC-{hex}.pdf` | 相对路径 |

---

## 2. 现有迁移机制分析

### 2.1 迁移脚本清单

| 脚本 | 类型 | 幂等 | --dry-run | 测试覆盖 |
|------|------|------|----------|---------|
| `scripts/migrate_add_classification_columns.py` | 建表+加列+索引 | ✅ | ✅ | ❌ |
| `scripts/migrate_add_analysis_runs.py` | 建表+索引 | ✅ | ✅ | ❌ |
| `scripts/migrate_add_intake_candidates.py` | 建表+索引 | ✅ | ✅ | ✅ `test_intake_migration.py` |
| `scripts/migrate_add_collection_topics.py` | 建表+补列+索引 | ✅ | ✅ | ✅（plan 内嵌测试） |
| `scripts/migrate_add_discovery.py` | 建表+索引 | ✅ | ✅ | ❌ |
| `scripts/migrate_sync_parse_status.py` | 数据同步 | ✅ | ✅（默认） | 间接 |
| `scripts/migrate_backfill_doc_type.py` | 数据回填 | ✅ | ✅ | ❌ |
| `api/db.py::ensure_metadata_review_columns()` | runtime ALTER | ✅ | ❌ | ❌ |
| `scripts/literature_ingest.py::ensure_core_schema()` | 建表 | ✅ | ❌ | 间接 |
| `scripts/literature_ingest.py::_migrate_source_files_columns()` | runtime ALTER | ✅ | ❌ | ❌ |
| `scripts/dedup_apply.py`（内部 ALTER） | runtime ALTER | ✅ | ✅ | ❌ |

### 2.2 统一范式

所有脚本遵循：
1. `CREATE TABLE IF NOT EXISTS`
2. `PRAGMA table_info()` 检查列存在后才 `ALTER TABLE ADD COLUMN`
3. `_index_exists()` 检查后才 `CREATE INDEX`
4. `argparse` + `--dry-run`
5. `from api.db import table_exists` 复用

### 2.3 关键缺失

| 缺失项 | 影响 |
|--------|------|
| **无 schema_version 表** | 无法回答"当前 DB 跑过哪些迁移" |
| **无迁移序号** | 新环境部署需人工判断执行顺序 |
| **无回滚机制** | SQLite ALTER 本身有限制，且无 down 脚本 |
| **runtime ALTER 与脚本 ALTER 并行** | 职责分散，`ensure_metadata_review_columns` 在每次 API 启动时执行 |
| **`metadata_extractions` 无 CREATE 脚本** | 该表只在测试 conftest 中有完整定义，生产靠手动建表 |
| **部分表无迁移覆盖** | `work_codes`、`work_relations`、`parse_artifacts`、`library_migration_files` 仅在 parser 迁移中创建，主库无独立迁移脚本 |

---

## 3. 一致性校验现状

### 3.1 活跃工具：`scripts/healthcheck_library.py`

| 检查类别 | 检测内容 | 修复能力 |
|---------|---------|---------|
| 孤儿文件 | `works/*/source/*` 中无 `source_files` 记录的文件 | `--apply` 移至 `_quarantine/_healthcheck_orphans/` |
| 幽灵记录 | `source_files.source_path` 指向不存在的文件 | 仅报告 |
| 无主目录 | `works/` 下有目录但无 `works` 行 | 仅报告 |
| 隔离状态不一致 | 隔离区文件 status 不匹配 | `--repair-quarantine-status` |
| 悬空引用 | 10 组逻辑外键检查（子表→父表） | 仅报告 |
| intake_candidates 状态异常 | `status='ingested'` 但无 `ingested_work_id` | 仅报告 |

### 3.2 SHA256 校验

**现状：入库时计算一次，后续不再校验。**
- 入库时：`scripts/literature_ingest.py` 计算 SHA256 存入 `source_files.content_sha256`
- 去重时：`collector/gate.py::heavy_gate()` 下载后检查是否已存在
- **无周期性重校验**：文件被篡改/损坏不会被发现

### 3.3 不一致方向

| 方向 | 检测 | 修复 |
|------|------|------|
| 磁盘有、DB 不知（孤儿文件） | ✅ healthcheck | ✅ `--apply` |
| DB 有、磁盘没有（幽灵记录） | ✅ healthcheck | ❌ 无自动修复 |
| DB 有、父记录没有（悬空引用） | ✅ healthcheck | ❌ 无自动修复 |
| 文件内容被篡改（SHA256 不匹配） | ❌ 无检测 | ❌ 无修复 |

---

## 4. 核心问题：备份/导出/导入/同步

### 4.1 当前状态：完全空白

- **无自动备份**：仅有一次手动 `literature.sqlite.backup_20260608_235724`
- **无导出功能**：无 JSON/SQL dump
- **无导入功能**：无 restore from backup
- **无同步机制**：无跨实例数据同步

### 4.2 需要支持的场景

| 场景 | 描述 | 复杂度 |
|------|------|--------|
| **S1: 完整备份** | 将整个库（DB + 文件）打包为可恢复的备份 | 低 |
| **S2: 完整恢复** | 从备份包恢复到新位置 | 低 |
| **S3: 导出到另一台机器** | 打包备份 → 另一台机器导入 | 中 |
| **S4: 增量同步（A→B）** | A 做了更新，同步到 B | 高 |
| **S5: 双向同步** | A 和 B 各自更新，需要合并 | 极高 |
| **S6: 部分导出** | 按主题/标签/时间范围导出子集 | 中 |

### 4.3 难点分析

#### 难点 1：文件与数据库的耦合

数据库中的路径（`source_files.source_path`、`literature_parse_runs.content_md_path` 等）是**绝对路径**。迁移后路径失效，需要重写。

```
source_files.source_path = "D:\\02_academic\\doctoral\\literature_library\\works\\W-arxiv-2501.17805\\source\\paper.pdf"
                                                          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                                          这部分在另一台机器上不同
```

#### 难点 2：ID 生成策略

- `works.id`：基于 arxiv_id/doi/SHA 生成（`W-arxiv-{id}`、`W-doi-{slug}`、`W-sha-{prefix}`）
- `source_files.id`：`SF-{sha12}-{seq}` 基于 SHA256 前 12 位 + 序列号
- `intake_candidates.id`：`IC-{hex8}` 随机
- `discovery_runs.id`：`DR-{hex}` 随机

**ID 在不同实例间可能冲突**（同一论文在两台机器上会生成相同的 `works.id`，但不同实例的 `source_files.id` 可能因序列号不同而不同）。

#### 难点 3：状态一致性

同步时需要处理的状态冲突：
- A 机器上 `works.read_status='read'`，B 机器上同一 work 是 `'unread'`
- A 机器上 `intake_candidates.review_status='approved'`，B 上是 `'rejected'`
- A 机器上 `metadata_extractions` 有新版本，B 上有不同版本

#### 难点 4：解析产物

`works/{wid}/parsed/mineru/{sfid}/` 下的解析产物（content.json、content.md）是 MinerU 生成的，体积大（单个 content.json 可达数 MB）。完整同步这些产物成本高。

#### 难点 5：无全局版本号

没有 `schema_version` 表意味着：
- 无法判断两台机器的 schema 是否兼容
- 无法自动判断需要执行哪些迁移
- 无法保证迁移执行顺序

---

## 5. 解决方案方向

### 5.1 方案 A：轻量级（面向当前需求）

**目标**：支持 S1（备份）+ S3（导出到另一台机器）+ 基础 S4（单向增量）

#### A1: 引入 schema_version 表

```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    applied_at  TEXT NOT NULL,
    checksum    TEXT    -- 迁移脚本内容的 SHA256，防篡改
);

-- 初始化：将当前所有已应用的迁移插入
INSERT OR IGNORE INTO schema_version VALUES
    (1, 'ensure_core_schema', '2026-06-01T00:00:00', ''),
    (2, 'migrate_add_intake_candidates', '2026-06-15T00:00:00', ''),
    (3, 'migrate_add_collection_topics', '2026-06-20T00:00:00', ''),
    (4, 'migrate_add_discovery', '2026-06-22T00:00:00', ''),
    (5, 'migrate_add_classification_columns', '2026-06-25T00:00:00', ''),
    (6, 'migrate_add_analysis_runs', '2026-06-28T00:00:00', '');
```

每个新迁移脚本在执行成功后写入 `schema_version`。`migrate --status` 命令可查询当前版本。

#### A2: 引入 migrate CLI 入口

```bash
python scripts/migrate.py status          # 查看当前 schema 版本
python scripts/migrate.py upgrade         # 执行所有待执行的迁移
python scripts/migrate.py upgrade --to 5  # 升级到指定版本
python scripts/migrate.py verify          # 校验已应用迁移的 checksum
```

统一管理所有迁移脚本，替代手动逐个执行。

#### A3: 备份导出（`scripts/backup_export.py`）

```bash
python scripts/backup_export.py --output backup_20260708.zip
python scripts/backup_export.py --output backup_20260708.zip --exclude-parsed
```

导出内容：
1. `literature.sqlite`（完整数据库）
2. `works/`（所有 PDF + 解析产物，可选 `--exclude-parsed` 跳过解析产物）
3. `_collector_cache/`（暂存 PDF）
4. `templates/templates.json`
5. `backup_manifest.json`（包含 schema_version、导出时间、文件清单 + SHA256）

#### A4: 备份导入（`scripts/backup_import.py`）

```bash
python scripts/backup_import.py backup_20260708.zip --target /path/to/new/library
python scripts/backup_import.py backup_20260708.zip --merge  # 合并模式（不覆盖已有）
```

导入流程：
1. 解压到目标目录
2. 读取 `backup_manifest.json`，校验文件完整性
3. **路径重写**：将所有绝对路径中的源库路径替换为目标库路径
4. 运行 `migrate.py upgrade` 确保 schema 版本一致
5. 运行 `healthcheck_library.py` 验证一致性

路径重写 SQL：
```sql
UPDATE source_files SET
    source_path = REPLACE(source_path, '{old_root}', '{new_root}'),
    relative_source_path = REPLACE(relative_source_path, '{old_root}', '{new_root}')
WHERE source_path LIKE '%{old_root}%';

-- 类似地更新 literature_parse_runs, library_migration_files 等所有含路径的列
```

#### A5: 单向增量同步

```bash
python scripts/sync_export.py --since 2026-07-01 --output incremental_20260708.zip
python scripts/sync_import.py incremental_20260708.zip --target /path/to/other/library
```

增量包内容：
1. 自 `--since` 以来变更的 DB 行（基于 `updated_at`/`created_at` 时间戳）
2. 对应的新增/修改文件
3. `sync_manifest.json`（包含同步时间戳、变更摘要）

导入逻辑：
- **新增记录**：直接插入（ID 相同 = 同一论文，跳过或合并）
- **更新记录**：按 `updated_at` 取较新者（last-write-wins）
- **冲突检测**：两台机器都修改了同一记录且 `updated_at` 都比上次同步新 → 标记为冲突，人工裁决

### 5.2 方案 B：完整级（面向长期维护）

在方案 A 基础上增加：

#### B1: JSON 导出格式

将数据库完整导出为 JSON（类似 `migration_plan.json` 的格式），便于：
- 版本控制（git diff 可见变更）
- 跨 DB 引擎迁移（不限于 SQLite）
- 选择性导入

```json
{
  "schema_version": 6,
  "exported_at": "2026-07-08T10:00:00+08:00",
  "works": [
    {
      "id": "W-arxiv-2501.17805",
      "title": "...",
      "source_files": [
        {
          "id": "SF-a1b2c3-00001",
          "relative_source_path": "works/W-arxiv-2501.17805/source/paper.pdf",
          "content_sha256": "abc123..."
        }
      ],
      "metadata_extractions": [...],
      "classification_tags": [...]
    }
  ],
  "collection_topics": [...],
  "intake_candidates": [...]
}
```

#### B2: 双向同步（CRDT 思路）

对于 S5（双向同步），采用操作日志（operation log）而非状态快照：

```sql
CREATE TABLE IF NOT EXISTS sync_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name  TEXT NOT NULL,
    row_id      TEXT NOT NULL,
    operation   TEXT NOT NULL,  -- INSERT / UPDATE / DELETE
    column_name TEXT,           -- 仅 UPDATE
    old_value   TEXT,           -- 仅 UPDATE
    new_value   TEXT,
    timestamp   TEXT NOT NULL,
    instance_id TEXT NOT NULL   -- 机器标识
);
```

同步时：
1. 交换双方的 `sync_log`（自上次同步点之后）
2. 按时间戳排序应用
3. 冲突规则：同列不同值 → 取较新者；同列同时间 → 取 instance_id 较大者（打破平局）

**注意**：此方案复杂度极高，对于当前单用户场景可能过度设计。

#### B3: 周期性 SHA256 重校验

```bash
python scripts/verify_integrity.py [--fix] [--since 2026-01-01]
```

遍历所有 `source_files`，重算 SHA256 与 `content_sha256` 比对：
- 不匹配 → 标记 `integrity_status='corrupted'`
- 文件不存在 → 标记 `integrity_status='missing'`
- `--fix` → 尝试从备份/归档区恢复

新增列：
```sql
ALTER TABLE source_files ADD COLUMN integrity_status TEXT DEFAULT 'unchecked';
ALTER TABLE source_files ADD COLUMN integrity_checked_at TEXT;
```

---

## 6. 需要新增的数据库对象

| 对象 | 用途 | 优先级 |
|------|------|--------|
| `schema_version` 表 | 迁移版本追踪 | P0 |
| `sync_log` 表 | 操作日志（双向同步用） | P2 |
| `source_files.integrity_status` 列 | 文件完整性状态 | P1 |
| `source_files.integrity_checked_at` 列 | 最后校验时间 | P1 |
| `backup_manifest.json` 结构 | 备份元数据 | P0 |
| `sync_manifest.json` 结构 | 同步元数据 | P1 |

---

## 7. 需要新增的脚本

| 脚本 | 用途 | 优先级 |
|------|------|--------|
| `scripts/migrate.py` | 统一迁移 CLI（status/upgrade/verify） | P0 |
| `scripts/backup_export.py` | 完整备份导出 | P0 |
| `scripts/backup_import.py` | 备份导入（含路径重写） | P0 |
| `scripts/verify_integrity.py` | SHA256 周期校验 | P1 |
| `scripts/sync_export.py` | 增量导出 | P1 |
| `scripts/sync_import.py` | 增量导入（含冲突检测） | P1 |
| `scripts/schema_snapshot.py` | 导出当前 schema 为 JSON（用于 diff） | P2 |

---

## 8. 迁移执行顺序（新环境部署）

当前（无版本管理）：
```
1. python scripts/literature_ingest.py              # ensure_core_schema
2. python scripts/migrate_add_intake_candidates.py
3. python scripts/migrate_add_collection_topics.py
4. python scripts/migrate_add_discovery.py
5. python scripts/migrate_add_classification_columns.py
6. python scripts/migrate_add_analysis_runs.py
7. # 启动 API 时自动执行 ensure_metadata_review_columns()
```

目标（有版本管理）：
```
python scripts/migrate.py upgrade    # 自动按序执行所有待执行迁移
```

---

## 9. 与 Git 的关系

- **代码**（schema 定义、迁移脚本）：Git 管理
- **数据**（literature.sqlite、works/）：.gitignore 排除
- **备份包**（.zip）：建议单独存储（外部硬盘/网盘），不入 Git
- **JSON 导出**（如采用方案 B1）：可选入 Git（作为"数据快照"），但体积大时不推荐

---

## 10. 风险与权衡

| 决策点 | 选项 A | 选项 B | 建议 |
|--------|--------|--------|------|
| 路径存储方式 | 绝对路径（现状） | 全部改为相对路径 | **相对路径**：迁移时无需重写 |
| 冲突解决策略 | last-write-wins | 人工裁决队列 | **先 LWW，冲突日志留痕** |
| 解析产物同步 | 全量同步 | 仅同步 DB 记录，解析产物按需重跑 | **按需重跑**：节省空间和带宽 |
| schema 管理 | 继续幂等脚本 | 引入 Alembic | **保持幂等脚本**：SQLite 场景足够，Alembic 增加依赖 |
| ID 冲突处理 | 相同 ID = 跳过 | 相同 ID = 合并 | **跳过**：同一论文 ID 相同是预期行为 |
