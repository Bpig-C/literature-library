# 文献库数据存档·更新·迁移 方案规划书

> 版本：v0.2（**已冻结**，未进入实现）
> 冻结说明：2026-07-17 用户决策——§六 D1-D5 决策保留有效，近期以 git + 网盘手动备份兜底，实现待排期；重启时从本文件继续。
> 基于：`docs/architecture/migration-and-data-management-analysis.md` 诊断结论
> 范围：存档（备份/归档）+ 更新（增量同步）+ 迁移（换机/恢复）
> 编制时间：2026-07-08

---

## 一、现状速写（数据层面）

### 1.1 数据资产清单

| 资产 | 大小 | 说明 |
|------|------|------|
| `literature.sqlite` | 4.4 MB | 19 张表，约 3900 行数据 |
| `works/`（含 PDF 源文件） | ~950 MB | 150 个 work 目录 |
| `works/*/parsed/mineru/`（解析产物） | **~19 GB** | MinerU 输出的 content.json / content.md |
| `_collector_cache/` | 17 MB | 采集候选暂存 PDF |
| `_quarantine/` | 78 MB | 隔离区文件 |
| `_archive/` | 169 MB | 归档区文件 |
| `_duplicates/` | 70 MB | 精确重复文件 |
| `_inbox/` | 3.4 MB | 手动投放区 |
| `templates/templates.json` | <1 MB | 模板配置 |
| **合计** | **~20.7 GB** | 解析产物占 92% |

> ⚠️ 关键发现：**解析产物（parsed/mineru/）占总体积的 92%**。这是所有备份/迁移策略必须面对的核心约束。

### 1.2 数据库路径现状（影响迁移的核心变量）

| 表.列 | 存储方式 | 示例（截断） | 迁移时需重写？ |
|--------|---------|-------------|---------------|
| `source_files.source_path` | **绝对路径** | `D:\02_academic\...\works\W-xxx\source\paper.pdf` | ✅ 必须 |
| `source_files.relative_source_path` | **相对路径** | `works\W-xxx\source\paper.pdf` | ❌ 无需 |
| `literature_parse_runs.content_md_path` | 绝对路径 | `D:\02_academic\...\works\W-xxx\parsed\...` | ✅ 必须 |
| `literature_parse_runs.content_json_path` | 绝对路径 | 同上 | ✅ 必须 |
| `metadata_extractions.content_md_path` | 绝对路径 | 同上 | ✅ 必须 |
| `parse_artifacts.file_path` | 相对/混合 | 视具体值而定 | 需检查 |
| `library_migration_files.library_path` | 绝对路径 | `D:\02_academic\...\works\W-xxx\...` | ✅ 必须 |
| `library_migration_files.original_source_path` | 绝对路径 | 原始位置 | 可选保留历史 |
| `intake_candidates.local_pdf_path` | **相对路径** | `_collector_cache\IC-xxx.pdf` | ❌ 无需 |

**需重写的绝对路径涉及 6 张表、8 个列**。

### 1.3 时间戳覆盖情况（影响增量同步的基础设施）

| 时间戳状态 | 表 | 影响 |
|------------|-----|------|
| ✅ 有 `updated_at` + `created_at` | works, analysis_runs, classification_extractions, collection_topics, discovery_runs, work_classification_tags | 可精确追踪变更 |
| ⚠️ 仅 `created_at`（无 updated_at） | work_codes, work_relations | 能追踪新增，无法追踪修改 |
| ❌ 无通用时间戳 | source_files, literature_parse_runs, intake_candidates, duplicate_*, parse_artifacts, metadata_extractions, discovery_hits | **增量同步需要补充机制或全量扫描** |

---

## 二、需求定义（用户关注的三件事）

### 2.1 存档（Archiving）

**目标**：在任何时刻，能生成一份「完整的、可验证的、可恢复的数据快照」。

用户场景：
- 定期自动备份（如每周一次）
- 重大操作前手动打快照（如批量入库前）
- 数据出问题时能回退到某个已知良好状态

**关键决策点**：
- 解析产物（19 GB，占 92%）是否每次都纳入完整备份？
  - 选项 A：全部打包 → 备份包 ~21 GB，恢复零成本
  - 选项 B：仅备 DB + PDF 源文件 → 备份包 ~1.2 GB，解析产物按需重跑
  - **建议**：默认选项 B，提供选项 A 的 `--full` 开关

### 2.2 更新（Updating / Incremental Sync）

**目标**：两台设备间能高效传递「自上次以来的变化」，而非每次全量复制。

用户场景：
- 在实验室电脑和家用电脑之间同步最新进展
- 手机/平板查看时只拉取元数据（不拉 19 GB 解析产物）

**关键约束**：
- 当前约一半的表缺少 `updated_at` 列，无法纯靠时间戳做增量
- 解析产物体积大，增量传输时需要智能 diff 或直接跳过

### 2.3 迁移（Migration）

**目标**：将整个文献库从一台机器搬到另一台机器（或从 SSD 迁到移动硬盘），搬完后一切正常可用。

用户场景：
- 换电脑
- 数据盘空间不足，迁移到更大的存储
- 在另一台离线机器上复用已有数据

**核心难点**：绝对路径重写 + schema 一致性保证

---

## 三、方案设计（三阶段递进）

### 阶段一：基础存档能力（P0 — 先解决"别丢数据"问题）

#### 交付物

| # | 名称 | 类型 | 用途 |
|---|------|------|------|
| D1.1 | `scripts/backup_export.py` | Python 脚本 | 生成完整备份包 |
| D1.2 | `scripts/backup_import.py` | Python 脚本 | 从备份包恢复 |
| D1.3 | `scripts/schema_version.py` | 迁移脚本 | 新增 `schema_version` 表 |
| D1.4 | `scripts/migrate.py` | Python 脚本 | 统一迁移 CLI 入口 |
| D1.5 | 备份包格式规范 | 设计文档 | 定义 .zip 包内部结构 |

#### D1.5：备份包格式

```
library_backup_YYYYMMDD_HHmmss.zip
├── manifest.json              # 元数据 + 完整性校验
├── data/
│   ├── literature.sqlite      # 完整数据库（WAL 已 checkpoint 合入）
│   └── files/
│       ├── works/            # 所有 works 目录
│       ├── _collector_cache/
│       ├── _quarantine/
│       ├── _archive/
│       ├── _duplicates/
│       ├── _inbox/
│       └── templates.json    # 模板配置
└── OPTIONAL_parsed/          # 仅 --full 时包含
    └── works/*/parsed/       # 解析产物（可单独跳过）
```

**manifest.json 结构**：

```json
{
  "version": "1",
  "created_at": "2026-07-08T23:30:00+08:00",
  "source_root": "D:\\02_academic\\doctoral\\literature_library",
  "schema_version": 6,
  "db_checksum_sha256": "abc123...",
  "file_counts": {
    "works": 150,
    "source_files": 163,
    "total_files": 320
  },
  "size_breakdown": {
    "db_mb": 4.4,
    "works_mb": 950,
    "parsed_gb": 19.0,
    "auxiliary_mb": 337,
    "total_gb": 20.7
  },
  "includes_parsed": true,
  "tables": ["works", "source_files", "..."]
}
```

#### backup_export.py 核心逻辑

```
输入: --output PATH [--full] [--exclude-patterns GLOB]
输出: .zip 备份包

步骤:
1. DB WAL checkpoint → 确保一致性快照
2. 计算 literature.sqlite SHA256
3. 收集文件清单 + 每个 SHA256
4. 写 manifest.json
5. 打包: DB → data/literature.sqlite, 文件 → data/files/
6. 如果 --full: 额外打包 parsed/ 到 OPTIONAL_parsed/
7. 最终 zip + 输出摘要
```

#### backup_import.py 核心逻辑

```
输入: BACKUP.ZIP --target DIR [--merge] [--dry-run]
输出: 目标目录下完整恢复的文献库

步骤:
1. 校验 zip 完整性（manifest 中记录的 checksum vs 实际文件）
2. 解压到 --target
3. 【关键】路径重写:
   扫描 manifest.source_root → 替换为 --target 的绝对路径
   涉及 8 列 × 6 张表的 SQL REPLACE 操作
4. 运行 migrate.py upgrade（确保目标环境 schema 一致）
5. 运行 healthcheck_library.py 验证一致性
6. 输出报告
```

#### 路径重写的精确范围（基于源码核查结果）

```python
# 必须重写的 8 个绝对路径列:
PATH_COLUMNS = [
    ("source_files", "source_path"),
    ("literature_parse_runs", "source_path"),
    ("literature_parse_runs", "content_md_path"),
    ("literature_parse_runs", "content_json_path"),
    ("literature_parse_runs", "package_path"),
    ("literature_parse_runs", "output_dir"),
    ("metadata_extractions", "content_md_path"),
    ("library_migration_files", "library_path"),
]
# library_migration_files.original_source_path: 选择性保留原始值作为历史记录
```

> 注意：`relative_source_path` 和 `local_pdf_path` 经确认是相对路径，**不需要重写**。

#### schema_version 表 + migrate.py 入口

```sql
-- 初始版本号分配（对应当前已执行的迁移）
INSERT INTO schema_version (version, name, applied_at) VALUES
  (1, 'ensure_core_schema',        '2026-06-01'),
  (2, 'migrate_add_intake_candidates', '2026-06-15'),
  (3, 'migrate_add_collection_topics','2026-06-20'),
  (4, 'migrate_add_discovery',     '2026-06-22'),
  (5, 'migrate_add_classification_columns', '2026-06-25'),
  (6, 'migrate_add_analysis_runs','2026-06-28');
```

`migrate.py` 子命令：
```bash
python scripts/migrate.py status     # 显示当前版本和待执行迁移
python scripts/migrate.py upgrade    # 按序执行所有 pending 迁移
python scripts/migrate.py verify     # 校验 checksum（如果启用）
```

#### 阶段一工作量估计

| 任务 | 复杂度 | 预计工时 |
|------|--------|---------|
| backup_export.py | 中 | 主要工作是文件遍历 + zip 打包 + manifest 生成 |
| backup_import.py | 中高 | 路径重写是核心难点；需处理 merge 冲突场景 |
| schema_version 表 | 低 | 一个简单迁移脚本 |
| migrate.py 统一入口 | 低中 | 包装现有脚本，增加序号管理 |
| 测试 + 文档 | 中 | 验证备份→恢复→healthcheck 全流程 |

---

### 阶段二：增量更新能力（P1 — 解决"两台设备间同步"问题）

#### 前置依赖：补充缺失的时间戳

当前有 7 张表缺乏 `updated_at`，增量同步前需要补齐：

```sql
-- 对以下表添加 updated_at 列（幂等 ALTER）
ALTER TABLE source_files           ADD COLUMN updated_at TEXT;
ALTER TABLE literature_parse_runs  ADD COLUMN updated_at TEXT;
ALTER TABLE intake_candidates      ADD COLUMN updated_at TEXT;
ALTER TABLE duplicate_candidates   ADD COLUMN updated_at TEXT;
ALTER TABLE parse_artifacts        ADD COLUMN updated_at TEXT;
ALTER TABLE metadata_extractions   ADD COLUMN updated_at TEXT;  -- 仅有 created_at
ALTER TABLE discovery_hits         ADD COLUMN updated_at TEXT;

-- 同时在 API 层面的写入路径中自动维护这些字段
```

> 这一步可以和现有迁移脚本统一走 `migrate.py upgrade` 管理。

#### 交付物

| # | 名称 | 用途 |
|---|------|------|
| D2.1 | `scripts/sync_export.py` | 生成增量变更包 |
| D2.2 | `scripts/sync_import.py` | 应用增量变更到目标库 |
| D2.3 | `scripts/migrate_add_updated_at.py` | 补充时间戳列 |

#### sync_export.py 核心逻辑

```bash
python scripts/sync_export.py \
    --since 2026-07-01T00:00:00 \   # 起始时间戳
    --output increment.zip \          # 输出增量包
    --include-files                  # 是否包含变更的物理文件
```

```
步骤:
1. 查询所有表中 updated_at >= --since 的行（或 created_at >= --since）
2. 按 table 分组导出为 JSON
3. 收集关联的新增/修改物理文件（works/*/source/* 等）
4. 生成 sync_manifest.json（含变更统计、源端 version）
5. 打包
```

增量包结构：
```
increment_YYYYMMDD.zip
├── sync_manifest.json
├── changes/
│   ├── works.json          # 变更行列表
│   ├── source_files.json
│   ├── metadata_extractions.json
│   └── ...
└── files/                   # 关联的物理文件（如有）
    └── works/W-xxx/source/paper.pdf
```

#### sync_import.py 核心逻辑

```bash
python scripts/sync_import.py \
    increment.zip \
    --target /path/to/target/library \  # 目标库路径
    --strategy lww                       # last-write-wins
```

```
冲突解决策略（三层优先级）:
1. ID 不存在 → 直接 INSERT
2. ID 存在且目标端 updated_at 较旧 → UPDATE（LWW）
3. ID 存在且两端都有更新（updated_at 都 > 上次同步）→ 记录冲突日志，人工裁决
```

#### 阶段二工作量估计

| 任务 | 复杂度 | 说明 |
|------|--------|------|
| 补充 updated_at 列 | 低 | 幂等 ALTER，但需同时改写入代码以维护该字段 |
| sync_export.py | 中高 | 需处理跨表关联、文件跟随逻辑 |
| sync_import.py | 高 | LWW 策略实现 + 冲突检测 + 回滚能力 |
| 写入路径改造 | 中 | 所有 INSERT/UPDATE 点需加 updated_at 自动维护 |

---

### 阶段三：高级能力（P2 — 按需启动，非必须）

| 能力 | 描述 | 适用场景 |
|------|------|---------|
| JSON 导出格式 | 将整个 DB 导出为人类可读的嵌套 JSON | Git 版本控制 / 代码审查 |
| 双向同步（CRDT） | 两台设备各自编辑后自动合并 | 多人协作 / 多设备高频使用 |
| 定期 SHA256 校验 | 周期性扫描检测文件损坏/篡改 | 长期存储完整性保障 |
| 部分导出 | 按主题/标签/时间导出子集 | 与导师/同行分享特定方向的文献 |
| 定时自动备份 | cron / scheduler 集成 | 无人值守定期存档 |

---

## 四、实施路线图

```
                    现在                        3个月后
  阶段一 ◄──────────── P0 基础存档 ────────────► 完成
  │  ├─ schema_version 表 (~0.5d)
  │  ├─ migrate.py 统一入口 (~1d)
  │  ├─ backup_export.py (~2d)
  │  ├─ backup_import.py (~3d)        ← 最复杂：路径重写
  │  └─ 端到端测试 (~1d)
  │
  ▼
  阶段二 ◄──────────── P1 增量同步 ────────────► 6个月后
       ├─ 补充 updated_at 列 (~1d + 写入路径改造 ~2d)
       ├─ sync_export.py (~2d)
       ├─ sync_import.py (~3d)         ← 最复杂：冲突处理
       └─ 端到端测试 (~2d)

  阶段三 ◄──────────── P2 按需 ─────────────────► 随时
       (各能力独立，按实际需求逐个启动)
```

---

## 五、风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| 路径重写遗漏某列 | 导入后部分路径断裂，对应功能异常 | 中 | 维护 `PATH_COLUMNS` 清单作为单一事实来源；import 后强制跑 healthcheck |
| 解析产物过大导致备份慢 | full 备份可能耗时 30min+，占用 20 GB | 高 | 默认排除 parsed/，提供 `--full` 开关；解析产物可按需重跑 |
| updated_at 未被所有写入路径维护 | 增量同步漏掉某些变更 | 中 | 在 DB 层面用 trigger 自动维护（SQLite 支持 AFTER UPDATE trigger） |
| 合并模式下 ID 冲突 | 两台机器独立采集了同一篇论文但用了不同的 source_file_id | 低 | works.id 是确定性的（基于 arxiv/doi/sha），不会冲突；source_file_id 基于 sha+seq，同一文件 seq 可能不同 |
| 备份包本身损坏 | 无法恢复 | 极低 | manifest 含 SHA256 校验；建议重要备份双份存储（本地+云盘） |

---

## 六、决策记录

| # | 决策点 | 结论 | 说明 |
|---|--------|------|------|
| D1 | **默认备份是否包含解析产物？** | ✅ **不含**，保留 `--full` 开关 | 默认包 ~1.2 GB；`--full` 时 ~20.7 GB。解析产物可从 PDF 重跑 |
| D2 | **备份格式选择？** | ✅ **.zip** | Windows 兼容性最好 |
| D3 | **增量同步方向？** | ✅ **单向（可逆）**，当前机器=辅机，另一台=主机 | 数据流：主机变更 → 导出增量包 → 辅机导入。反向亦可，只是每次单方向推 |
| D4 | **何时补 updated_at？** | ✅ **阶段二再做** | 不影响阶段一的备份/恢复功能。影响范围：source_files / parse_runs / intake_candidates / metadata_extractions / parse_artifacts / discovery_hits / duplicate_candidates 共 7 张表 |
| D5 | **是否需要定时自动备份？** | ✅ **暂不需要**，手动即可 | 列入 P3 未来规划（实现成本很低，只需在 backup_export 外层加 scheduler wrapper） |

### D3 补充说明：用户部署模型

```
  ┌─────────── 主机（日常操作主力机）────────────┐
  │  入库 / 标注 / 分析 / 审核都在这台做         │
  │                                             │
  │  sync_export.py → 增量包.zip                │
  │        （通过 U盘/网盘/局域网传输）           │
  │                                             │
  │                                     ┌──────▼────────┐
  │                                     │   辅机（本机）  │
  │                                     │ sync_import.py │
  │                                     │  只读/查看/容灾 │
  │                                     └───────────────┘

  反向场景（偶尔需要）：辅机上做了修改 → 从辅机 export → 主机 import
  单向 = 每次推送只有一个数据流向，避免双向合并冲突
```

---

## 七、P3 未来规划（已识别但暂不实施）

| # | 能力 | 触发条件 | 预估复杂度 |
|---|------|---------|-----------|
| F1 | 定时自动备份（scheduler 集成） | 用户有无人值守存档需求时启动 | 低（backup_export.py 的 cron/任务计划程序 wrapper） |
| F2 | JSON 导出格式（人类可读嵌套 JSON） | 需要 Git 版本控制或跨 DB 引擎迁移时 | 中 |
| F3 | 双向同步（CRDT 操作日志） | 多设备高频同时编辑同一库 | 极高 |
| F4 | SHA256 周期校验（文件完整性扫描） | 长期存储防篡改需求 | 低中 |
| F5 | 按主题/标签/时间范围部分导出 | 与同行分享特定子集文献 | 中 |

> F1 实现成本最低（~0.5d），随时可以加。

---

*本文档是规划书 v0.3，决策项已全部确认。下一步：拆解为阶段一的具体实现任务清单。*
