# 阶段一实施方案：出口侧最小闭环（引用导出 + 综述矩阵）

> 状态：当前有效（2026-07-18 经用户批准启动）
> 所属主线：`FUTURE_WORK_PLAN.md`「当前主线」阶段一（#10 提前）
> 两轮独立审核记录：完成后写入 `docs/superpowers/reviews/`，本文件随之归档

## 目标与非目标

**目标**
1. 已批准文献可一键导出 BibTeX 与 RIS（写论文直接可用）。
2. 已批准文献可导出综述矩阵 CSV（Excel 可直接打开，含分类标签列）。
3. 导出数据源严格限定为"已批准"：只导出有 approved 元数据且未隔离的 work。

**非目标**
- 不做 digest 批量化（"一句话定位"列只取已有 approved digest，无则留空）。
- 不做导出模板自定义、不做 Word/LaTeX 集成、不做批量勾选导出。
- 不改数据库 schema，不引入新依赖。

## 代码事实（已核实 2026-07-17）

- `works` 表直接持有引用字段：`title, title_zh, authors, contributors, year, doi, arxiv_id, venue, url, abstract, publication_date_json, doc_type/primary_doc_type, language, priority, is_core_literature, region`（approve 时 fill-empty 回填，即"已批准视图"）。
- 分类：`work_classification_tags(tag_group, tag_value)` 三组（artifact_focus / risk_domain / method_tags）+ works 标量。
- digest：`analysis_runs` 中 `kind='digest'` 且 `review_status='approved'` 的 `extracted_json.fields.one_sentence_positioning.value`（当前仅个位数，列允许为空）。
- 路由注册：`api/main.py:23-33`（11 组，新模块追加一行）；路由风格见 `api/routes/duplicates.py`（`APIRouter()` + `get_conn()`）。
- 测试基建：`tests/conftest.py` 的 `sample_db` fixture（session 级临时库），新增导出测试沿用。
- 前端：`web/src/views/Works.vue` 工具栏加导出入口；naive-ui 组件现成，无新依赖。

## 设计

### 后端

**`api/export_format.py`（纯函数，可单测）**
- `work_to_bibtex(work, tags) -> str`：entry key = work id；类型映射 journal/article→@article、conference/paper→@inproceedings、report/system_card/tech_report→@techreport、preprint→@misc(note={Preprint})、其余→@misc；author 支持 JSON 数组与逗号/分号字符串两种形态解析为 `A and B`；特殊字符 `% & # _` 转义；title 用 `{{...}}` 保护大小写；缺字段不产出空字段。
- `work_to_ris(work, tags) -> str`：TY(JOUR/CONF/RPRT/GEN)、TI、AU（每作者一行）、PY、JO、DO、UR、AB、KW（method_tags 每标签一行）、ID、ER。
- `works_to_matrix_csv(rows) -> str`：列 = work_id, 标题, 中文标题, 作者, 年份, venue, DOI, arXiv, URL, 类型, 语言, 方法标签, 风险域, artifact_focus, 优先级, 核心文献, 一句话定位；编码 utf-8-sig；多值分号连接。

**`api/routes/export.py`**
- `GET /api/export/bibtex` / `GET /api/export/ris` / `GET /api/export/matrix.csv`
- 查询参数：`search`、`doc_type`、`tag`、`work_ids`（显式指定优先于筛选）。
- 过滤规则：`read_status != 'quarantined'` 且存在 approved metadata_extractions。
- 响应带 `Content-Disposition: attachment`；tags 按 work_id 分组一次查询，避免 N+1。

`api/main.py` 注册 `export.router`。

### 前端

- `Works.vue` 工具栏加「导出」按钮 → NModal：格式三选一（BibTeX/RIS/综述矩阵 CSV）+ 范围二选一（当前筛选结果 / 全部已批准）+ 说明行。
- 确认后 `window.open(buildExportUrl(...))` 下载；`web/src/api.js` 加 `buildExportUrl(format, params)`。

### 测试（`tests/test_export_api.py`）

- BibTeX：类型映射、key=work id、多作者 `and`、缺 DOI 不产空字段、特殊字符转义。
- RIS：AU/KW 多行、TY 映射、ER 结尾。
- CSV：列齐全、utf-8-sig BOM、多值分号、digest 缺失留空。
- 过滤：pending/quarantined 不出现；tag/doc_type/work_ids 筛选生效。
- TestClient HTTP smoke。

## 执行顺序与分工

1. 主 agent：export_format + 单测先行 → routes/export + API 测试 → 前端 → 构建，跑通全部验收命令。
2. **两轮模型独立审核（硬性验收）**：第一轮代码质量与边界审核（独立子 agent，只读审查 diff，输出含行号证据的 finding）；第二轮事实与产出核对（另一个独立子 agent，逐项复查代码事实 + 实跑导出抽查 3 篇）。两轮均不带实现上下文，记录写入 `docs/superpowers/reviews/`。
3. finding 全部处理 → 全量回归 → 迁移收尾（FUTURE_WORK_PLAN 标记、PROJECT_HISTORY 补录、memory 更新）。

## 验收命令

```powershell
.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --basetemp .codex_tmp\pytest-phase1
.venv/Scripts/python.exe scripts/healthcheck_library.py --json
.venv/Scripts/python.exe scripts/check_docs.py
cd web; npm.cmd run build
```

## 回滚

纯新增文件 + 两行既有文件改动（main.py 注册、Works.vue 按钮），revert 单个 commit 即可，无数据迁移。
