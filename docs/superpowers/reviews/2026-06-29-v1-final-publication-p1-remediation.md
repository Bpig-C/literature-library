# V1 发布审查 — P1 阻断项整改结果

> 日期：2026-06-29
> 上游评审：`docs/superpowers/reviews/2026-06-29-v1-final-publication-review.md`（CONDITIONAL PASS）
> 整改范围：P1-01 ~ P1-04 四个发布阻断项（P2 与文档治理按约定留作后续）

## 裁定升级

上游给出 **CONDITIONAL PASS**，建议修完 P1-01~04 再盖 V1 发布章。本轮四个 P1 全部修复并通过验证，**V1 发布阻断项清零**，项目可作为初始 V1 发布。

## P1 整改清单

### P1-01 / P1-02 quarantine 状态漂移 + 语义不一致 → fixed
新建共享 nucleus `api/quarantine.py`（`quarantine_work_sources` / `restore_work_sources`）：
- 移动文件**同时同步** `source_files.status='quarantined'`（restore 回 `'active'`）、`works.read_status`、`work_codes`。
- **统一 strict 策略**：缺源文件 → 409（移动前预检，caller 未 commit，无半隔离、无部分移动）。
- works/metadata/classification 三处 quarantine 全部改调 nucleus（metadata/classification 保留各自的 extraction 级联拒绝）；duplicates `_move_to_quarantine` 加 `status='quarantined'` 同步（保留批量 best-effort 语义）。
- **新增不变式测试** `tests/test_quarantine_healthcheck_invariant.py`：works/metadata/classification quarantine + works restore 每条路径跑完 `run_healthcheck` 必须零 inconsistency；strict 409 不改 DB。

### P1-03 needs_better_copy 未接通 → 安全拦截（标 V1 后续）
`/api/intake/promote` 检测 `resolution='needs_better_copy'` 时**拒绝并返回明确提示**（含 `matched_work_id`），不再走 `ingest_bridge.promote` 创建重复 work。replace-source 链路文档化为 V1 后续能力。
- 测试：`test_promote_rejects_needs_better_copy`（approved 的 nbc 候选 → failed，ingest_bridge 绝不被调用）。

### P1-04 前端 V1 UX → fixed
- IntakeReview / InboxReview / TopicsReview：移除顶层多余 `<AppLayout>`（App.vue 已统一包裹），消除双重 chrome。
- WorkDetail：标题 contenteditable blur 改写 `editForm.title`（saveEdit 的提交源），修复"编辑标题保存后丢失"。
- Duplicates：quarantine 加 `useDialog.warning` 二次确认，显示受影响候选 work 数。
- `npm run build` 通过。

## 验证（全部通过）
```
python -m pytest tests/ -q            # 348 passed, 7 skipped
python scripts/healthcheck_library.py # No issues detected（五项全零）
npm.cmd run build                     # built OK
```

## 相关提交
| commit | 内容 |
| --- | --- |
| `13bd0d9` | P1-01/02 quarantine nucleus + 状态同步 |
| `5c4aef5` | P1-03 promote 拒绝 needs_better_copy |
| `32af45c` | P1-04 前端三处 UX 修复 |

## 残留（非阻断，已确认延后）
- P2 项：分类标签事务批端点、`GET /parse/status` 多源聚合策略、dashboard 队列压力、审计日志语义统一。
- 文档治理：`docs/DOCUMENT_GOVERNANCE.md`、`web/README.md` 替换、stale `parse_ledger.json`/`scripts/literature_healthcheck.py` 引用清理、`FUTURE_WORK_PLAN.md` 刷新。
- needs_better_copy 完整 replace-source promote 链路（含 parse_run 创建）。

这些不阻断初始 V1 发布，建议作为 V1.1 收口项。
