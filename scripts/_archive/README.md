# scripts/_archive

> 状态：已归档一次性脚本
> 更新时间：2026-06-29

本目录保存阶段性、一次性或已被替代的脚本。这里的脚本不应被当作当前操作入口。

已归档脚本：

- `_phase_b_trial.py`：Phase B parser 试验 helper。仅作历史记录，不属于当前 parser 链路。
- `_batch_classify.py`：早期分类批处理 helper。已被当前分类抽取/审核流程取代。
- `_batch_classify_all.py`：早期全库分类批处理 helper。已被当前分类抽取/审核流程取代。
- `_phase_c_validate.py`：Phase C 验证 helper；其报告保存在 `docs/superpowers/reviews/phase_c_validate_report.json`。
- `literature_healthcheck.py`：旧健康检查脚本。已被 `scripts/healthcheck_library.py` 取代。

当前有效的分类、验证和健康检查入口见 `scripts/README.md`。
