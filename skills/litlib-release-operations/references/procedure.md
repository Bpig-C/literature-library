# 发布流程与恢复边界

## 1. 查明状态并准备候选

- 对照 authenticated `/api/research/schema`、`/api/remote/version`、权威对象、当前 slot/environment、两个持久启动脚本；记录源 manifest、当前 epoch N、远端 HEAD 和候选 HEAD。旧报告可能把已切换的 epoch 写成待授权。
- 从可编辑的候选 checkout 工作；封存 slot 内不 pull、不修改 tracked code、不安装测试依赖。检测其他模型改动，保留其修改。Git dubious ownership 使用进程级 safe.directory；不关闭 TLS 验证。
- 对 issue 做静态核实及有意义的隔离回归。续跑应覆盖真实 HTTP→producer wrapper→已有操作恢复、同 job/operation/version 幂等、锁及错误门禁，不触发真实用户任务。
- 使用锁定依赖和批准的 Python；运行所需测试、`scripts/check_release.py`，审查 diff、clean tree 和代码历史。提交后 fast-forward 推送并 ls-remote 读回，禁止 force。网络及凭据故障定向处理；持久故障停止该阶段并报告，不改变安全策略绕过。
- 前端未变可复用已核实 SHA/bytes 的 artifact。小修复无需改 pyproject version 或客户端能力标记。需要协议/schema 变化时另做兼容计划。

## 2. 发布前检查

- 一次授权覆盖已说明的本次推送、快照、服务切换及验证；无授权时先提供候选提交、测试结果、目标分支、源/目标槽、N→N+1 和中断影响供审查。
- 从当前 source slot 构造 snapshot inputs，刷新 named files 的 SHA/bytes，使用当前 catalog/research 库，不能借用旧 reception 数据。查询正在运行的解析、未完成 producer、pending storage operations；已有用户任务需等待或按其实际状态制定恢复方案，不能清空 journal 或强停正在执行的工作。
- prepare 确认 code_commit、namespace、预算、frontend 和源身份；保存 ticket、manifest digest、schema 和各表数量。生产回执仅放公开身份，token/OSS 凭据仅通过进程环境读取。
- 新 slot/staging 必须未占用，重试则严格匹配相同发布身份；准备 launchers 的备份和修改稿。

## 3. 唯一写者停止、最终快照与恢复

1. 主机 `maintenance-adapter.ps1 enter` 产生 durable lease。核实其 slot 和全部 serve PID、18765 端口已停止，TLS gateway 保持运行。
2. 冻结当前 epoch N，保留 freeze marker。最终 prepare/stage 在停写及冻结之后执行；按同 ticket/manifest 重试，不能重新生成随机发布覆盖中途结果。
3. publish 所有对象并逐个冷读核验，manifest 最后发布；成功后 `record_verified`，verified_at 必须晚于 frozen_at。
4. restore 到全新 slot，确认 git URL、commit、manifest、quota。`uv sync --frozen --extra storage --no-dev` 指定批准的 Python。主机 parser/conf 为非敏感配置时从现有槽复制，敏感配置另按主机规则处理，不能放 Git/artifact。
5. `restored_runtime.py check` 必须 ok、parser_config_present、parser_constructors_ok，并核实前端、tracked code、依赖和数据环境。
6. 以只读方式逐表比较 catalog 和 research；允许已定义的恢复路径重定位与等价 JSON 序列化，不能仅凭总数量相同判断。保存 quick_check、各表 normalized hash 及数量。禁止插入生产测试文献或解析任务。

## 4. 交接及在线验收

1. 严格检查成功、源冻结、lease 存在且全部写者仍停后，使用现有 authority CLI 和最终 verified version 交接 N→N+1；指定原 owner SHA，禁止手工改权威对象。
2. 同时更新 `restart-service-only.ps1` 和 `start-readonly-service.ps1` 的目标 slot/epoch，保留既有 remote/write/research-editing 配置。历史 readonly 文件名不代表运行只读。
3. 以 `--allow-writes` 启动新服务。后台 Start-Process 使用 Hidden；gateway、会话及 TLS 配置保留。核实 shim/child 属于同一 slot，不能误认成两个写者。
4. authenticated schema/version 必须报告精确 commit/release/manifest、clean code、write flags；新 write_guard 可用、旧 epoch 被 fencing、未认证请求401、前端完整、discover-remote 最新身份正确。
5. 针对修复做无业务副作用验收。例如 resume 使用随机不存在 job 和 force=true，应返回422 not_found，不能再出现 TypeError；续跑成功路径在隔离测试验证。薄 CLI check-version 必须兼容；检查 required capability/expected commit。
6. 成功后归档并关闭 maintenance lease，记录实际新写者。**跨 epoch 交接成功后不能调用适配器普通 exit**：它会恢复旧 slot。应在新身份核验后按主机已验证流程关闭 lease，并保留回执。

## 故障恢复

- 每阶段独立保存回执；错误后停止依赖阶段，先检查远端/本地持久状态，再重试相同身份。
- 冻结前可通过普通 adapter exit 恢复未冻结源。冻结后必须使用现有 authority 控制明确恢复，不能删除 freeze marker 绕过。authority 交接后旧 epoch 已失效，即使启动旧进程也不应成为写者。
- 交接后新服务失败：保留停止状态、修复目标槽的主机配置，或通过新一次权威交接恢复选定版本；不能把 launcher 改回旧 epoch 假装回滚。
- 发布成功但在线验证失败不能宣称上线成功，也不能关闭维护证据后遗忘未完成工作。

## 证据与客户端

工作区 acceptance 目录保存 preflight、freeze、stage、publish、verified version、restore、strict check、全表保全、authority、online、client compatibility 和 lease closure 回执。不要提交数据库、凭据、runtime receipts 到 code-only 仓库。

客户端沿用 URL、CA、token。固定 commit 的检查需换成新 SHA；客户端工具只有接口或能力发生变化才更新。项目 operations 文档链接到本技能；历史状态报告保留原日期，当前事实以实际在线身份及本次回执为准。
