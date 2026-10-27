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

## 8. 异步解析与原生多文件批次（Issue #7/#14）

2026-10-23 候选新增 async_parse_v1。部署方开启 LITLIB_ASYNC_PARSE_ENABLED=1 并启动独立 parse_worker 后，更新版 CLI 的 run/continue 快速入队。HTTP 202/退出 0 表示已接收，随后 status 查询；Parse/version 在 worker prepare 短事务中分配。旧同步写入口在开启时返回 async_required，客户端按 version 的固定地址/SHA 更新；未开启的服务保留原同步协议及其长锁限制。

```powershell
python scripts/litlib_remote.py --server $server parse run --plan deception-plan.json --request-id vlm-async-001 --max-items 10 --max-submissions 12 --max-pages 300 --execute
python scripts/litlib_remote.py --server $server parse status --plan-id PP-实际ID
python scripts/litlib_remote.py --server $server parse status --task-id PQ-实际ID
python scripts/litlib_remote.py --server $server parse scheduler
python scripts/litlib_remote.py --server $server parse pause --task-id PQ-实际ID --reason "暂停本地处理" --execute
python scripts/litlib_remote.py --server $server parse retry --task-id PQ-实际ID --reason "核对后继续原任务或单项重试" --execute
python scripts/litlib_remote.py --server $server parse cancel --task-id PQ-实际ID --reason "停止后续处理，保留预算与上游跟踪" --execute
```

同批 batch ID 可相同，data_id、Source、Parse/version、PDF 身份各自独立。cloud_history 回看各次映射，不返回签名链接；GET /api/async/parse/batches/{CB-ID} 查看逐文件状态。单份成功先登记，其余继续；failed 项有剩余预算才可明确 retry，已成功项不重提。文件尝试预算保守预留，批次 POST 意图另列，不代表账户余额或实际计费。等待上传、云排队、云 done、目录 registered 与固定资产可读分开表达。

依据[官方精准 API](https://mineru.net/apiManage/docs)于 2026-10-23 的详细说明，本地批次上限按 50 份约束；余项可立即小批，不凑满。原生 batch 不保证全部文件同时执行。PUT 中断先查原批次，已确认上传但暂报 waiting-file 的文件继续等待，不重复上传；链接缺失/过期、密钥不符进入检查，不自动新建 batch。

暂停/取消的已知任务仍仅查询到终态，tracking_upstream=true 表示尚在跟踪；不保证取消云端任务或退款。正常 pending/running 不计失败；查询错误有持久连续计数和有界退避。未知提交需实际核对 provider 后记录结论：

```powershell
python scripts/litlib_remote.py --server $server parse resolve --task-id PQ-实际ID --outcome task_found --provider-task-id 原上游ID --reason "已核对账户回执及文件身份" --execute
python scripts/litlib_remote.py --server $server parse resolve --task-id PQ-实际ID --outcome not_submitted --reason "已核实该提交未创建任务" --execute
```

not_submitted 不退还原尝试预算，后续仍需剩余预算或新计划。响应丢失且上传链接未保存时保留映射待核，取得 batch ID 不等于已上传。-60009/429、-60018、认证错误和本地 busy 分列。账号额度恢复后，维护身份可执行 parse scheduler --resume-submissions --reason "核对依据" --execute 解除提交暂停；需要 LITLIB_BACKUP_ADMIN_TOKEN，不自动重试未知/已完成任务。

部署准备（本轮不执行）：

1. 保全数据、盘点并协调旧作业；从与运行 manifest 相同提交的干净代码目录安装 uv sync --locked --extra storage --extra parsing。
2. API/worker 配相同根、authority 及 LITLIB_ASYNC_PARSE_ENABLED=1。另行保全 worker 的 32 字节 base64 密钥 LITLIB_PARSE_UPLOAD_KEY，不交普通客户端、不入 Git/快照。上传及结果链接用 AES-GCM 加密，AAD 绑定 namespace/batch/PQ/用途；恢复未上传文件需原密钥。
3. 可信 limits JSON 可设 prepare/submit/upload/poll/download/publish/local 槽位、upstream 在途文件数、batch_size（1–50）、batch_input_bytes、提交/查询 RPM、页数/字节/磁盘和 lease。默认本地阶段/worker 为 1，批大小/在途文件数为 10；它们是排队边界，不承诺 10 个云端同时执行或账号配额，上线值按账号及有限样本调整。
4. python scripts/parse_worker.py --configure C:/受控目录/parse-limits.json 提交共享配置，之后独立运行 python scripts/parse_worker.py --workers 1。多进程共享领取限制；--once 仅推进一个阶段。启动检查代码干净且与运行 manifest 提交一致。
5. 维护用 --maintenance drain --owner 工单ID 阻止新接收/prepare，排空后才进入 snapshot；备份执行器已协调屏障。冷恢复通过 scheduler 读取 maintenance_owner，核对实际写者后，以 --maintenance resume --owner 原工单ID 显式解除保留的屏障。未登记资产/部分不可变包仍需先协调。

parse_queue_control/jobs/events、parse_cloud_batches/members 为增量控制表，研究 schema/contract 不变。密文随数据库恢复，密钥独立配置；所有目录写入经短 epoch/租约事务。Source/最新版本在 resume/resolve/claim/发布检查，历史任务不能绕过新版本恢复。代码交付不安装 worker/定时任务、不自动迁移旧执行作业，不代表生产验收。

### 网页后台解析

Work 详情的解析/重解析按钮及流水线批量解析进入同一预览面板。先明确 VLM 或 PyMuPDF；同 Work 多原件时在详情选择具体 Source，批量入口不会猜选最新文件。预览展示可处理原件与排除原因，再确认文件数、云端文件尝试数和累计页数上限。默认只处理一份、最多一次云端尝试、最多 100 页；这些是本地预算，不是账户余额。VLM 不自动降级。

确认前先在当前浏览器保存冻结计划、预算和 request_id，再接收计划和持久入队。响应丢失时以“使用原请求继续入队”恢复同一请求，不重建新计划；本地保存失败则不提交。关闭面板或网页不会取消已接收任务。再次打开相同 Work 集合可以读回计划，使用“查询任务状态”查看后台阶段；只在已登记成功后提示完成。剩余项、预算耗尽、失败、待检查、取消不等于全部完成。

保留请求/计划/任务 ID，可通过上述 CLI 查询和受控恢复。浏览器记录仅是恢复入口，不是服务器任务账本；切换浏览器或清除站点数据前应保存这些 ID。状态查询不重复提交云任务，预算不会自动扩充。需要暂停、取消或核对未知上游任务时，沿用已有 CLI 的显式控制流程。

MinerU 结果包的 `content_list.json` 和单个 `*_content_list.json` 均映射到正式 `content.json`；多个候选结构化清单返回 `ambiguous_content_list`，不按文件顺序猜选。无清单时占位说明显式标注 `content_list_available=false`。该兼容修复不会改写旧 Parse 的不可变资产；旧占位 JSON 的修复需从保留的原包生成新的、可追溯的登记版本，不需要重新向 MinerU 提交原文。
