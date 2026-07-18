# 阶段一出口侧：两轮模型独立审核记录

> 状态：当前有效
> 审核日期：2026-07-18
> 审核对象：`api/export_format.py`、`api/routes/export.py`、`tests/test_export_format.py`、`tests/test_export_api.py`、`web/src/api.js`（buildExportUrl）、`web/src/views/Works.vue`（导出弹窗）
> 方法：两个互相独立的子 agent（无实现上下文），第一轮代码质量审核 + 第二轮事实与产出核对

## 第一轮 · 代码质量与边界审核（8 条 finding）

| # | 严重度 | finding | 处理 |
|---|--------|---------|------|
| 1 | 中 | `_load_digests` 未排除 superseded approved digest，陈旧定位句可导出 | ✅ 已修：`AND (superseded_by IS NULL OR superseded_by = '')`，补 `test_superseded_digest_not_exported` |
| 2 | 中 | BibTeX 转义不全（缺 `$ ^ ~ \`），`{}` 不处理会破坏条目配平 | ✅ 已修：转义表扩至 `\ $ % & # _ ^ ~ { }`（反斜杠优先），补 `test_bibtex_escapes_structure_and_math_chars` |
| 3 | 中 | 前端弹窗不透传工具栏 typeFilter（旧 doc_type），"当前筛选"静默偏差 | ✅ 已修：`primaryDocTypeFilter || (typeFilter !== 'all' && typeFilter)` |
| 4 | 低 | search 的 LIKE 通配符 `% _` 未转义 | ✅ 已修：匹配前剔除通配符，按字面匹配 |
| 5 | 低 | work_ids 与其他筛选互斥语义未声明 | ✅ 已修：`_select_works` docstring 写明优先级与门禁不可突破 |
| 6 | 低 | `work_to_bibtex` 的 tags 死参数 | ✅ 已修：签名移除 tags 参数，调用点同步 |
| 7 | 低 | CSV 无公式注入防护 | ✅ 已修：`= + - @` 开头单元格前置 `'`，补 `test_matrix_csv_formula_injection_guard` |
| 8 | 低 | 测试弱断言与覆盖缺口 | ✅ 已修：字段缺失断言改行级（`"doi = {" not in out`）；补 CSV quoting、RIS 缺字段、RIS EP、digest superseded 测试 |

第一轮验证无问题要点：过滤门禁不可绕过（含 work_ids 显式指定）、SQL 全参数化、无 N+1、CSV 走 csv 模块、BOM 双向验证、fixture 不污染共享 sample_db。

## 第二轮 · 事实与产出核对（6 口径）

| # | 结论 | 摘要 |
|---|------|------|
| 1 | 成立 | 独立 SQL 计数 111 = 导出条目 111；隔离/无 approved 指定 ID 导出为 0 |
| 2 | 成立 | 三端点 200 + attachment；CSV 前三字节 ef bb bf |
| 3 | 成立（受限） | 抽查 3 篇 BibTeX/CSV 与库一致；导出集 venue/doi 全空，非空渲染路径无真实数据可验（数据质量问题，非导出问题） |
| 4 | 成立 | digest 全 pending → 一句话定位列全空；代码审阅 approved 后填值路径正确 |
| 5 | 成立 | doc_type/tag/work_ids/search 实跑与独立 SQL 逐项一致（30/29/1/7） |
| 6 | 部分成立 | 类型映射缺 thesis/book_chapter（落 @misc 不合理）；RIS 丢 arxiv_id |

第二轮 finding 处理：
- ✅ 类型映射补 `thesis→@phdthesis`、`book_chapter→@incollection`（RIS 对应 THES/CHAP；venue 字段对应 school/booktitle），补测试
- ✅ RIS 增加 `EP  - <arxiv_id>` 行，补测试
- 观察项（venue/doi 全空、旧 doc_type 回退路径不触发、not_literature 映射策略）：记录为已知限制，不属本次修复范围

## 修复后回归

- `pytest tests -q`：562 passed, 5 skipped（导出相关 29 个测试全过）
- `healthcheck_library.py --json`：五类问题全空
- `check_docs.py`：PASS
- `npm run build`：通过
- 真实库 smoke（重启加载新代码后）：bibtex 111 条、RIS `EP  - 2501.17805` 正确输出

## 环境说明

- 核对过程中 19527 服务曾因主 agent 的 smoke 进程超时退出（非缺陷），第二轮审核员重启后继续；修复验证前已重启加载新代码。
- matrix.csv 未实际用 Excel/WPS 打开验证显示效果（仅字节级 BOM 验证），建议用户首次使用时确认。
