# Issue：模糊分数（ambiguity_score）重算不一致 —— 人工补充字段后分数从 5 跳到 20

> 日期：2026-06-12
> 状态：✅ 已修复（2026-06-13）
> 严重性：中（影响审核排序与批量通过的语义，不破坏数据）

## 现象

ClassificationReview 中某条抽取记录显示 ambiguity_score=5；人工补充编辑若干字段并保存草稿后，分数反而升到 20。直觉上人工补充信息应降低模糊度。

## 根因（已核验，三个叠加缺陷）

### D1（直接触发）：Mimo 批次入库数据与评分函数不一致

`scripts/_batch_classify_batch1-6.py` 等批次脚本入库时：

- `ambiguity_score` 是 agent **手工填写**的（5/8/10），不是 `api/classification_ambiguity.py::compute_ambiguity` 算出的。证据：batch1 的 `ambiguity_reasons` 含 `"secondary_doc_type=research_article"`，而 `compute_ambiguity` 根本没有 secondary_doc_type 规则。
- `confidence_json` 列只存了 `{"primary_doc_type": "high"}`，而完整置信度在 `extracted_json` 内嵌的 `confidence` 键里（两处不一致，见 `_batch_classify_batch2.py:20-22`）。
- `evidence` 多数只有 `risk_domain` 一个键，没有 `primary_doc_type` 的证据。

当用户在 UI 保存草稿时，`api/routes/classification.py::save_extraction_draft`（L441）用**列里的稀疏 confidence** 首次真正调用 `compute_ambiguity` 重算：

| 规则 | 该类记录的命中情况 | 加分 |
|---|---|---|
| publication_status 置信度缺失 → 默认 low | 命中 | +5 |
| reading_lane 非空但置信度缺失 → low | 命中 | +3 |
| artifact_focus 非空但置信度缺失 → low | 命中 | +3 |
| evidence 无 primary_doc_type 键 | 命中 | +10 |

合计 ≈ 20-21 分。**与用户编辑了什么无关**——首次重算暴露了入库数据不一致，编辑只是触发器。

### D2（设计缺陷）：人工编辑不提升 confidence

`save_extraction_draft`（L431-441）与 `review_extraction`（L487-492）把 `edited_fields` 合并进 `extracted` 后，`confidence` 原样不动就重算。这与 P1.0f 已确立的 metadata 审核语义不一致：MetadataReview 中人工编辑过的字段视为 `human-confirmed`，`confidence_json[field]` 提升为 `high`。结果是：人工补全一个模型没填的字段后，该字段仍按"低置信"计罚，模糊分降不下来。

### D3（语义缺陷）：评分函数无视人工来源

`compute_ambiguity` 的语义是"需要人工关注的程度"，但它无法区分模型原始输出和人工确认值。D2 修复后此问题自然消解（人工字段 confidence=high 即不计罚），无需改评分函数本身。

## 修复设计

1. **编辑即确认（修 D2/D3）**：`save_extraction_draft` 和 `review_extraction` 在合并 `edited_fields` 时，对**值发生实际变化**的字段把 `confidence[field]` 置为 `high`，并同步写回 `confidence_json`。与 metadata 闭环的 human-confirmed 语义对齐。注意：值未变化的字段不要提升（前端发送的是整个 editForm，不能把"原样提交"当成"人工确认"——需 diff 旧值）。
2. **重算时合并双源 confidence（修 D1 的读取面）**：重算前 `confidence = {**extracted.get("confidence", {}), **confidence_json}`，让批次记录内嵌的完整置信度参与计算。
3. **存量数据一次性重算（修 D1 的存量面）**：新增维护脚本 `scripts/recompute_classification_ambiguity.py`，对全部 `review_status='pending'` 记录按修复后逻辑重算 score/reasons 并更新；输出修正前后分布对比（重点观察 Mimo 批次从 5-10 跳到 15-25 的数量）。已审核记录不重算（保留历史快照语义，与 P1.0d"风险快照"原则一致）。
4. **堵住源头**：批次类脚本今后必须调用 `compute_ambiguity` 而不是手填分数；`confidence_json` 列与 `extracted_json.confidence` 必须同源写入。`_batch_classify_*.py` 是一次性脚本，不改历史文件，但在 README 或脚本头注释标注此约定。

## 对批量审核通过的影响（重要时序约束）

批量通过端点 `batch-approve-low-risk` 的条件是**存量** `ambiguity_score < 20`。Mimo 批次手填的 5-10 分会被当作低模糊度通过，而其真实重算分约 20+。如果计划"批量通过全部 pending 后按需精读"，建议顺序：

**先执行第 3 步全量重算 → 再批量通过**。这样 `review_note` 留痕（batch 通过 vs 人工核实）和模糊度分层的历史语义才是真实的，后续精读时按模糊度筛选才有意义。

## 验收标准

- 人工补充一个模型未填字段并保存草稿后，该记录模糊分**不升**（且该字段 confidence 显示 high）。
- 仅打开记录并原样保存草稿，分数不变（diff 保护生效）。
- 重算脚本运行后，所有 pending 记录的 score 与 `compute_ambiguity(merged_confidence)` 一致，输出变化清单。
- 对 Mimo 批次任一记录（如 `W-sha-fb8cb57faf5f`）：重算后 reasons 不再包含 evidence/低置信罚分与内嵌 confidence 矛盾的条目。
- 新增/更新 `tests/test_api.py` 用例：编辑提升 confidence、原样保存不变分、双源 confidence 合并。
