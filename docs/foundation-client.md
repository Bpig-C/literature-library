# 基础功能客户端操作手册

本手册对应 `parse_plans_v1`、`intake_reconcile_v1`、`backup_jobs_v1` 能力。代码推送不代表线上已部署；先运行 `check-version`，旧服务会明确报告缺少能力。保持原服务器 URL、CA、认证配置。以下 `$server` 是已配置的服务器地址，凭证放在进程环境中。

## 1. 能力与说明入口

```powershell
python scripts/litlib_remote.py --server $server check-version --require-capability parse_plans_v1
python scripts/litlib_remote.py --server $server guide
```

`guide` 从认证服务读取本版本手册并检查摘要。首次升级 CLI 按服务 `/api/remote/version` 给出的固定下载 URL 和 SHA256 下载核对，不自动执行下载内容。

## 2. 补录清单核对

本地 Agent 根据实际文件计算 SHA256，生成 JSON；不要只用文件名或口头数量。`client_id` 是本清单唯一标识，`work_id/request_id/purpose` 可选，用于核对预期身份及用途回执。

```json
{"items":[{"client_id":"paper-001","sha256":"填写实际64位SHA256","work_id":"实际WorkID","request_id":"原摄入请求ID","purpose":"欺骗相关研究"}]}
```

```powershell
python scripts/litlib_remote.py --server $server intake reconcile --manifest intake.json
```

返回精确文件命中、Work 存在但文件缺失、身份冲突、停用文件命中、文件缺失，以及用途回执 confirmed/missing/conflict/history_unavailable。HTTP/数据库失败是错误，不会伪装“未入库”。此入口只核对提交的清单，不宣称知道客户端全部文献或完整服务端差集。

实际上传继续用现有入库 API，保留 purpose 和原 request_id；确认是新文件才补录，标题候选或身份冲突需先核实。已有同 Work 的其他 PDF 不等于这份文件存在。

## 3. 按用途、时间或摄入请求批次生成解析计划

```powershell
python scripts/litlib_remote.py --server $server parse plan --backend vlm --purpose "欺骗" --time-field purpose_created --from-time "2026-10-01T00:00:00+08:00" --to-time "2026-11-01T00:00:00+08:00" --output deception-plan.json
python scripts/litlib_remote.py --server $server parse plan --backend vlm --request-id intake-001 --request-id intake-002 --output batch-plan.json
```

也可重复指定 `--source-file-id` 或 `--work-id`。不同维度 AND；同维度多个 ID 为任一。用途是大小写敏感的字面子串，不假装已有标签分类；用途文本和用途时间在同一条记录匹配。带 Source 的用途记录只作用于该 Source，无 Source 的 Work 级用途可匹配该 Work。

时间字段：`work_created` 为目录首次创建时间，`source_imported` 为 Source 导入时间，`purpose_created` 为用途登记时间；区间 `[from,to)`。输入必须包含时区；历史无时区/无效时间在时间筛选时排除并说明。不能用 updated_at 推断某次摄入，也不能把“最近 N 篇”当成批次。

现阶段“摄入批次”采用明确的 request_id 集合冻结在清单中，不自动按时间聚类，也不复用科研 batch_id。尚未引入命名摄入批次管理界面。

默认多 Source 的 Work 要明确选 Source；确实需要全部时使用 `--source-policy all`。已有目标后端且有已登记文本、隔离/归档、活动任务等分别列出排除原因。`--reparse-completed` 明确允许新的解析意图，不用于失败恢复。

plan 只查询数据库，不下载 PDF、不调用 MinerU、不登记任务。返回清单摘要、Source SHA/bytes、基线 producer 身份、Work/Source 计数和排除项。匹配超过 5000 Source 时要求缩小范围；执行计划最多 1000 Source，不静默截断。

## 4. 限额执行、暂停与续接

```powershell
python scripts/litlib_remote.py --server $server --timeout 2100 parse run --plan deception-plan.json --request-id vlm-run-001 --max-items 10 --max-submissions 10 --max-pages 300 --execute
python scripts/litlib_remote.py --server $server parse status --plan-id PP-实际ID
python scripts/litlib_remote.py --server $server --timeout 2100 parse continue --plan-id PP-实际ID --steps 2 --execute
```

CLI 先打印已持久登记的 plan_id，再逐项执行。一次 step 最多启动一篇，服务端保留原整请求 authority 守卫及全局 producer 串行锁；这一版不提高解析吞吐。无需改 MinerU 并发设置。

`max_items` 限制本计划启动篇数，`max_submissions` 限制本计划 VLM 提交尝试，`max_pages` 可选，执行前从固定 PDF 实际计页；读取失败或超预算不提交。对 PyMuPDF 可设 `max_submissions=0`。这些是本地计划上限，不是 MinerU 账户余额；旧 trigger 或其他客户端的调用不计入本计划，限额批处理应统一用本入口。

预算在调用解析器前持久预留。失败或不确定消耗保留预留，不推断退款；不会因单次请求内部 POST 重试突破提交上限。额度用完返回 `budget_exhausted` 和剩余 Source 清单。暂停后再次 continue 不改变预算；下一额度周期对剩余精确 Source 重新 plan，使用新 request_id 和新预算。

同 request_id、同计划与预算重放返回原 plan；改参数会冲突。新增补录不会自动加入已冻结计划；Source 或基线变化会拒绝，要求重新预览。一个失败/不确定项会阻止自动继续，此时先查精确 job，不重复 force。

CLI 正常完成返回 0；能力不兼容返回 2；暂停/待检查返回 3；传输/其他错误为非零。传输超时只说明客户端没拿到结果，先 status。step 仍可能在服务器完成；重复 step 查询/协调已有状态，不重跑已启动项。

## 5. 失败诊断与恢复

```powershell
python scripts/litlib_remote.py --server $server parse status --job-id parse-实际ID
python scripts/litlib_remote.py --server $server parse resume --job-id parse-实际ID --execute
python scripts/litlib_remote.py --server $server --timeout 2100 parse recover --job-id parse-实际ID --execute
```

诊断保留 configuration/submitting/upstream_submitted/upload/poll/download 等阶段、已知 task_id、有限上游代码和关联 job。没有配置、上游拒绝、提交响应丢失和已有产物登记失败可区分；不返回 token、签名 URL、完整 stderr 或私有路径。

MinerU POST 创建任务不自动重试；响应丢失或格式不明标为 `submission_unknown`。上游 ID 一获得即落库。`resume` 仅处理已有完整产物的 `artifacts_ready`，复用原 job/operation/版本。`recover` 对已知 VLM task_id 只轮询/下载原任务，保留原 job/Parse/版本，不创建或上传新云任务；产物完成后登记。已出现后续版本、归属不明或部分不可变包时拒绝覆盖，要求人工核对。上游任务无结果/已过期时会明确失败，不转成新提交。完成后 continue 会协调计划状态。

进程崩溃后如果 plan 显示 running，但 producer 未登记完成，会阻止自动重跑并要求检查。无需为恢复创建新 Work/Source；未获确认的结果保留原记录。新的解析意图和科研审核/采纳彼此独立。

2026-10-23 起，producer 创建、可迁移恢复凭据和计划 job 关联在同一事务内提交。凭据 `producer_recovery` 保存 Source/Parse/版本、固定 PDF SHA/大小及提交阶段，随目录数据库快照保留，不含私有路径或凭证。已知云任务冷恢复后可在核对固定身份后重建空输出目录，继续读取同一 task；不接管有不明文件的目录，不覆盖部分不可变包。旧任务若没有该凭据，须在原 slot 恢复完成后再备份，备份预检会明确拒绝这类已知云任务。

确认中断项无法按 resume/recover 完成、决定停止该项时，可使用以下入口（要求 `parse_resolution_v1` 能力和原有写权限）：

```powershell
python scripts/litlib_remote.py --server $server parse abandon --plan-id PP-实际ID --position 0 --reason "已核对中断阶段，停止本项并保留额度预留" --execute
```

`position` 是 status 返回的零起始编号。旧版本遗留的无关联 producer 必须核对 source/baseline 后额外提供 `--job-id`，服务拒绝猜测或关联别的计划。操作留存原因、时间、job 和结果，**不取消上游任务、不退还预留额度、不提交新任务**。已有完整产物必须 resume；已注册成功的项只协调成 succeeded。未知提交/已知未完成 task 的 Source 仍被新计划排除，不因 abandon 放行重复消费。之后可 continue 处理其余项目；含终止项的计划返回 `complete_with_abandoned`，CLI 退出码 3，不能当成全部解析成功。

## 6. 备份查询和请求

```powershell
python scripts/litlib_remote.py --server $server backup status
python scripts/litlib_remote.py --server $server backup request --request-id after-intake-001 --execute
python scripts/litlib_remote.py --server $server backup job --job-id BK-实际ID
```

查询使用普通远程身份。请求还需部署方授予的 `LITLIB_BACKUP_ADMIN_TOKEN`，作为独立请求头传递；不把所有入库身份自动升级为维护管理员。HTTP 202/queued 仅表示已登记。只有 job 为 succeeded 且有 verified manifest 回执才表示发布成功；冷恢复演练状态另行报告，不由上传成功推断。

独立主机 worker 执行备份，业务服务短暂停止期间客户端可能遇到连接失败；恢复后查询同一 job。相同 request_id 不重复备份。客户端可读取回执/索引；完整两库下载、恢复、自动 slot 删除不在此权限中。

status 分列 configured、worker_last_seen、worker_state、latest_verified、last_attempt；scheduler_state=`not_managed` 表示未由此功能注册定时任务，不能把配置七天策略写成“自动备份已启用”。worker 未启动时请求保持 queued，须在部署阶段配置执行器，无需每次人工转交文件。

## 7. 部署方配置（本次只准备，不执行部署）

业务 API 与独立 worker 共用槽外绝对目录 `LITLIB_BACKUP_CONTROL`，建议单独的主机控制目录；使用主机 ACL 限制写入。API 配普通远程 token 和专用 backup admin token。worker 通过进程环境获得远程 token、OSS 配置、authority token；配置文件不含凭证，不允许客户端指定执行 argv。

可信主机配置 JSON 字段：`server`、可选 `ca_file`、`releases_root`、当前 `epoch`、`max_snapshot_bytes`、`frontend_zip`、`maintenance_enter`、`maintenance_verify_stopped`、`maintenance_exit`。最后三个是固定 argv 数组：进入停写、验证所有写进程已停止、恢复同一写者。必须沿用当前主机适配器并实机验收，不用空命令或仅设置布尔值代替停写证明。

```powershell
python scripts/backup_worker.py --config C:/受控目录/backup-worker.json --preview
python scripts/backup_worker.py --config C:/受控目录/backup-worker.json --loop
```

worker 运行于与线上同提交的、干净且有完整 Git 历史的受管代码目录。维护与发布输入由认证运行身份重新发现；两库和工作材料来自同一 slot。普通备份不交接 epoch，使用 SQLite 一致快照流程，不裸拷贝 DB。已有 producer/未完成 operation 或中断 plan 须先协调。

worker 异常或断电遗留 running 时标为 needs_attention 并停止后续任务；不自动重跑维护。主机操作者核对维护 lease、实际写者和回执、恢复服务后，可用 `--resolve-job BK-... --service-verified` 确认该次失败已处理；该命令不把失败伪装成备份成功。后续另用新 request_id。

未开始的 `pending` 解析可以随快照备份，因此可以先补录、备份，再按额度解析。真正 running 的解析/计划以及未登记完成的资产仍须协调。执行器明确证明尚未进入维护的预检失败记为 `failed`，后续请求可继续；修正原因后使用新 request_id。已调用维护入口（即使入口随后报错）或断电导致阶段不明的任务仍为 `needs_attention`，不能按普通预检失败处理。

新表 `parse_plans`、`parse_plan_items`、`producer_diagnostics`、`producer_recovery`、`parse_plan_resolutions` 在首次授权写入时增量创建，只读入口不迁移；既有研究 schema/contract 不变。切换前在恢复副本验证新表进入两库快照；代码回退不删除这些记录，也不重放未知解析。线上发布和真实 MinerU/维护窗口验证另行执行。
