# 03 Provider 与 Adapter 契约

## 共同约定

### Provider 与 Adapter

Provider 是能力端口；Adapter 是把一个具体外部组件翻译成该端口的实现。一个 Adapter 可以实现多个 Provider，但注册、状态、能力和错误必须分别报告，不能用“组件在线”代替所有能力健康。

所有 Provider 请求都携带：

| 字段 | 语义 |
|---|---|
| `operation_id` | 变更操作的稳定标识；只读请求可为空 |
| `correlation_id` | 跨 API、Provider 与事件的关联标识 |
| `idempotency_key` | 变更请求必需；相同 key 和规范化请求只执行一次 |
| `deadline_at` | 调用方最后等待时间；过期后不得开始新副作用阶段 |
| `expected_revision` | 修改状态或配置时的乐观并发版本 |
| `principal` | 已鉴权本地用户或受信系统主体，不含 Channel 私有身份字段 |
| `cancellation` | 可查询的取消信号；支持等级由能力声明决定 |

共同 Provider 描述符包含 `provider_id`、`provider_kind`、`adapter_id`、`implementation_version`、`supported_contract_versions`、`negotiated_contract_version`、`capabilities`、`state`、`conditions` 与 `observed_at`。

### Provider 状态

`unavailable -> discovered -> initializing -> ready` 是正常就绪路径；`ready -> degraded -> ready` 表示部分能力异常；不可恢复初始化错误进入 `error`；无共同主版本进入 `incompatible`。`unknown` 只表示无法可靠观测，不得当作 `ready`。

### 错误

稳定错误码至少包括：`PROVIDER_UNAVAILABLE`、`CAPABILITY_UNSUPPORTED`、`CONTRACT_INCOMPATIBLE`、`DEADLINE_EXCEEDED`、`CANCEL_NOT_SUPPORTED`、`REVISION_CONFLICT`、`AUTHENTICATION_REQUIRED`、`CONFIGURATION_INVALID`、`MANAGEMENT_OWNER_CONFLICT`、`DEPENDENCY_FAILED`、`PARTIAL_FAILURE` 和 `EXTERNAL_STATE_UNKNOWN`。

Provider 返回结构化错误给 Control Plane；Control Plane 再生成用户说明、恢复动作与脱敏 Diagnostic。Adapter 原始 stdout、堆栈和配置正文不能直接进入稳定 API。

### 幂等、超时与取消

- 只读操作天然幂等，不得改变外部状态。
- `start`、`stop`、`connect`、`disconnect`、`pause`、`resume` 和 `cancel` 是目标状态幂等；目标已满足时返回成功 no-op。
- install、update、rollback、迁移、配置写入和凭据删除使用 `idempotency_key` 与阶段日志；重放返回原 Operation。
- deadline 是“停止等待或禁止进入下一副作用阶段”，不是外部进程必然已终止。
- 取消等级为 `none`、`checkpoint`、`best_effort`、`strong`。未声明 `strong` 时不得向用户显示“已立即终止”。
- 超时或 Control Plane 崩溃后，Adapter 必须先探测实际状态再决定恢复，不自动重放未知副作用。

### 能力与版本协商

Provider 和 Control Plane 分别列出支持的合约 SemVer，选择最高共同主版本中的最高版本。主版本无交集时状态为 `incompatible`；次版本能力通过 capability ID 与版本协商，不能靠方法不存在来猜测。

Capability 由 `capability_id`、`version`、`maturity`、`availability`、`constraints` 构成。`maturity` 为 `stable`、`experimental` 或 `deprecated`；实验能力不能成为十分钟首用的必需路径。

替换一个 Adapter 的完成标准是：同一契约测试通过、状态映射无语义倒退、Reference Baseline 回归通过、回滚点可用。内部文件布局相同不构成兼容性。

## OrchestrationProvider

### 职责与非职责

负责接收受限的编排请求、建立 Task/ChildTask、选择单 Agent、并行或顺序执行模式、传递必要上下文并返回 TaskResult。它不负责 Channel 收发、Agent 模型调用细节、安装生命周期或通用 DAG。

### 能力声明

`orchestration.submit.v1`、`orchestration.single.v1`、`orchestration.parallel.v1`、`orchestration.sequential.v1` 为稳定候选；`orchestration.discussion.v1` 为 experimental；暂停、取消、插话、改派分别独立声明，不因存在 Task 查询就视为支持。

### 核心操作与模型

| 操作 | 输入 | 输出 | 语义 |
|---|---|---|---|
| `submit` | OrchestrationRequest：目标、约束、允许模式、deadline | Task | 只提交一次，不在 Control Plane 中自行规划 |
| `get_task` | task_id | Task | 返回 Provider 的最新观测与 revision |
| `list_children` | task_id | ChildTask[] | 保留执行顺序、依赖来源与 Agent 归属 |
| `get_result` | task_id | TaskResult | 终态才有完整结果；部分失败不得丢成功结果 |
| `apply_intervention` | HumanIntervention | ControlReceipt | 交给 HumanControlPolicy 后执行支持的控制 |

状态为 `queued/running/pausing/paused/cancel_requested/canceled/succeeded/failed`。提交以 idempotency key 去重；Task 执行超时由请求 deadline 和 Provider 上限共同决定。取消遵循能力等级，终态任务的重复取消为 no-op 或状态冲突，不创建新 Task。

### 可替换性与映射

当前 Adapter 映射：Hermes multiagent 负责默认编排，dual_agent 提供临时并行/顺序回退；单 Agent、并行与顺序已有基线证据，讨论与完整人类控制不得标为稳定。

未来替代：当默认编排组件原生覆盖同等能力时，Adapter 保持 Task/ChildTask/TaskResult 契约并移除临时回退；替换不得改变 GUI API 或把内部计划格式暴露给 Control Plane。

## AgentRuntimeProvider

### 职责与非职责

负责发现一等 Agent、提交一次受控调用、跟踪调用与 Session 能力、取得正式输出并在可用时取消。它不做编排决策、不决定人类路由、不负责 Channel UI，也不实现新的模型 Runtime。

### 能力声明

`agent.list.v1`、`agent.inspect.v1`、`agent.invoke.v1`、`agent.result.v1`、`agent.session.continuity.v1`、`agent.session.reset.v1`、`agent.cancel.best_effort.v1`。每个 Agent 可以有不同 availability 与限制。

### 核心操作与模型

| 操作 | 输入 | 输出 | 语义 |
|---|---|---|---|
| `list_agents` | filter | Agent[] | 只读发现，不启动 Agent |
| `inspect_agent` | agent_id | Agent、Capability[] | 返回版本、授权、运行与能力状态 |
| `invoke` | InvocationRequest：agent_id、task_id、输入、deadline | ChildTask | 由现有 Runtime 执行，Control Plane 不解释模型内容 |
| `get_invocation` | child_task_id | ChildTask/TaskResult | 可重复查询 |
| `cancel_invocation` | intervention context | ControlReceipt | 仅按声明能力执行 |
| `reset_session` | agent_id、scope、确认 | Operation | 新建后续 Session，不删除审计记录 |

invoke 以调用 key 去重；相同 key 不得触发第二次外部模型调用。默认 API 接受时间不超过 5 秒，实际调用异步完成。Session 标识是通用 opaque ref，不能暴露上游数据库 key。

### 可替换性与映射

当前 Adapter 映射：cc-connect relay 与其 Session 机制承载 Claude Code、Codex；直接查询、统一取消和强 Session 管理能力不完整。

未来替代：可改为编排组件的原生 Agent 接口或其他成熟 Runtime Adapter。Claude Code 与 Codex 仍是独立 Agent，不因 Runtime 替换而降级为隐藏工具。

## ChannelProvider

### 职责与非职责

负责 Channel 实例发现、连接校验、通用 Message 收发、Mention/Reply 映射、会话隔离和来源标注。它不做编排决策、不读写模型配置、不把 Bot 消息解释成人类控制。

### 能力声明

`channel.list.v1`、`channel.validate.v1`、`channel.connect.v1`、`channel.disconnect.v1`、`channel.send.text.v1`、附件能力独立声明、`channel.mention.v1`、`channel.reply.v1`、`channel.multibot.antiloop.v1`、`channel.delivery_receipt.v1`。

### 核心操作与模型

| 操作 | 输入 | 输出 | 语义 |
|---|---|---|---|
| `list_channels` | filter | Channel[] | 返回通用实例与健康状态 |
| `validate` | channel_id、只读检查范围 | Diagnostic[] | 不发送消息、不修改配置 |
| `connect` / `disconnect` | channel_id | Operation | 目标状态幂等 |
| `send` | Message、delivery id | DeliveryReceipt | 同一 delivery id 最多产生一次平台发送 |
| `normalize_inbound` | Adapter 私有事件 | Message | 专属字段只在 Adapter 内映射 |

连接状态为 `disconnected/connecting/connected/disconnecting/degraded/error/unknown`。发送超时不等于未送达；状态未知时返回 `EXTERNAL_STATE_UNKNOWN`，由 delivery receipt 探测，不自动重发。

### 可替换性与映射

当前 Adapter 映射：Hermes 的 Telegram platform 处理其 Bot；cc-connect Telegram 处理两个 Worker Bot；Patch 001 提供显式提及优先，Patch 004 提供送达消息映射。Hook 数据链是 best-effort。

未来替代：新增同级 Channel Adapter 或由上游原生通道接管。通用模型和 API 不出现 `chat_id`、平台 `message_id` 或平台实体类型。

## LifecycleProvider

### 职责与非职责

负责组件发现、预检、安装、启停、重启、健康、更新、备份、回滚与迁移。它不做 Agent 推理、消息路由或业务配置决策；健康检查默认只读。

### 能力声明

`lifecycle.discover.v1`、`lifecycle.preflight.v1`、`lifecycle.install.v1`、`lifecycle.start.v1`、`lifecycle.stop.v1`、`lifecycle.restart.v1`、`lifecycle.health.v1`、`lifecycle.update.v1`、`lifecycle.backup.v1`、`lifecycle.rollback.v1`、`lifecycle.migrate.v1`。每项声明支持的取消等级、是否需提权和是否可回滚。

### 核心操作与模型

| 操作 | 输入 | 输出 | 语义 |
|---|---|---|---|
| `discover` / `preflight` | component selector | Component[] / Diagnostic[] | 只读、可重复 |
| `install` | 版本、来源、校验信息 | Operation | 分阶段提交，失败保留诊断 |
| `start` / `stop` / `restart` | component_id、deadline | Operation | 目标状态幂等；restart 不是并发 stop+start |
| `health_check` | component_id、深度 | HealthState、Condition[] | 默认不写；深度测试需显式同意 |
| `check_update` / `update` | 版本策略 | UpdateState / Operation | 不静默更新，先建回滚点 |
| `backup` / `rollback` / `migrate` | 范围、目的、确认 | Operation | 清单化、可校验、Secret 单独处理 |

install/update/rollback/migrate 的不可逆阶段必须在 Operation 中标记 `point_of_no_return`；取消只能在安全检查点生效。发现和健康建议 10 秒内返回或转 Operation。

### 可替换性与映射

当前 Adapter 映射：VBS/CMD/Python 启动链、计划任务、junction 工具和只读健康脚本仍只读。另有仅限 cc-connect 的产品自有隔离安装、回滚、卸载与恢复实现；停止、重启、自动更新、配置迁移和外部生命周期接管尚不存在。

未来替代：由用户级后台宿主和受限提权 helper 接管；旧脚本在回归通过和回滚点建立后逐项退场，不要求外部组件改变内部实现。

## ModelConfigurationProvider

### 职责与非职责

负责描述可配置 schema、读取脱敏配置、校验候选配置、按 ManagementOwner 写入、管理 revision 与配置回滚。它不保存 Secret 明文、不覆盖官方登录态、不替用户选择模型策略。

### 能力声明

`modelconfig.schema.v1`、`modelconfig.read.v1`、`modelconfig.validate.v1`、`modelconfig.write.v1`、`modelconfig.owner.transfer.v1`、`modelconfig.rollback.v1`。只读外部配置可只声明 read/validate。

### 核心操作与模型

| 操作 | 输入 | 输出 | 语义 |
|---|---|---|---|
| `describe_schema` | component_id、scope | ConfigSchema | 标出敏感字段引用、默认值与稳定性 |
| `read` | scope | RedactedConfig、revision、owner | 永不返回 Secret 明文 |
| `validate` | candidate、revision | ValidationResult | 默认无写入；连通验证需显式标记 |
| `write` | candidate、expected_revision、owner | Operation | 原子替换，先备份再提交 |
| `prepare_owner_transfer` | from/to、revision | TransferPlan | 检测冲突、生成备份与影响说明 |
| `commit_owner_transfer` | plan_id、确认 | Operation | 旧写方先只读，成功后启用新写方 |
| `rollback_config` | backup_id、revision | Operation | 不触碰不在范围内的凭据 |

非 Owner 写入返回 `MANAGEMENT_OWNER_CONFLICT`。写入 key 重放返回同一结果；revision 不匹配不自动合并。验证调用有独立 timeout，不得因超时自动激活配置。

### 可替换性与映射

当前 Adapter 映射：Hermes 与 cc-connect 的配置文件、官方 CLI 登录状态以及可选 CC Switch 的只读检测；正式 Owner 标记与事务切换未实现。

未来替代：上游若提供稳定配置 API，Adapter 从文件写入切换到 API，schema、Owner 和 revision 语义保持不变。

## CredentialProvider

### 职责与非职责

负责 Secret 保存、元数据查询、使用授权、校验、移除、加密备份、迁移和恢复。它不管理普通配置，不把明文返回 GUI，不把 Secret 写入事件、URL 或普通诊断。

### 能力声明

`credential.store.v1`、`credential.metadata.v1`、`credential.validate.v1`、`credential.use.v1`、`credential.remove.v1`、`credential.export.encrypted.v1`、`credential.import.encrypted.v1`。明文导出能力不存在。

### 核心操作与模型

| 操作 | 输入 | 输出 | 语义 |
|---|---|---|---|
| `put` | purpose、secret value、owner | credential_ref、元数据 | value 只在调用边界短暂存在 |
| `get_metadata` / `list_metadata` | ref/filter | 脱敏元数据 | 不含可推断 Secret 的片段 |
| `validate` | ref、目标 Provider | ValidationResult | 受限使用，不写普通日志 |
| `lease_for_adapter` | ref、adapter_id、purpose、TTL | 一次性 lease | 仅受信 Adapter，可撤销，不经 GUI API 暴露 |
| `remove` | ref、expected_revision、确认 | Operation | 不可逆，重复删除为 no-op |
| `export_encrypted` / `import_encrypted` | 范围、口令/设备绑定策略 | Operation | 中间材料加密，导入后重新封装 |

所有操作限流并写不含值的审计记录。删除、导出和迁移要求更高权限与明确确认。deadline 到期后 lease 失效；Adapter 不应缓存明文。

### 可替换性与映射

当前 Adapter 映射：本地环境文件、上游官方登录存储和 HTTP Bearer 注入分散存在；没有统一 CredentialProvider，不能宣称满足完整契约。

未来替代：Windows 首版可用系统原生安全存储或 DPAPI 封装，未来映射 macOS Keychain、Secret Service 等；`credential_ref` 与 GUI API 不变。

## CapabilityRegistry

### 职责与非职责

负责注册 Provider/Agent/Capability 描述符、维护观测版本、解析满足约束的 Provider，并发布能力变化。它不执行调用、不安装组件、不根据自然语言选 Agent，也不是插件市场。

### 能力声明

Registry 自身提供 `registry.snapshot.v1`、`registry.resolve.v1`、`registry.watch.v1`、`registry.condition.v1`。被注册能力必须有版本、成熟度、availability 与约束。

### 核心操作与模型

| 操作 | 输入 | 输出 | 语义 |
|---|---|---|---|
| `register` | ProviderDescriptor、lease | resource_version | 同一 provider/instance 更新而非重复注册 |
| `heartbeat` | provider_id、observations | resource_version | 只更新观测与 Condition |
| `snapshot` | filter | Provider/Agent/Capability[] | 一致快照，带 resource_version |
| `resolve` | capability、版本与约束 | Resolution | 只做确定性匹配，不作智能规划 |
| `unregister` | provider_id、revision | receipt | Provider 消失后保留短期 tombstone |

注册和 heartbeat 幂等；lease 过期转 `unavailable`，不立即删除历史。查询快速返回，耗时探测由 discovery Operation 完成。

### 可替换性与映射

当前 Adapter 映射：静态多 Agent 配置、relay binding 和源码约定可形成只读 Registry Adapter；没有动态心跳与统一能力版本。

未来替代：逐步改为 Adapter 主动注册或 Control Plane 探测。无论来源如何，稳定快照结构保持不变。

## HumanControlPolicy

### 职责与非职责

负责验证“这是人类指令”、归一化来源、授权、确定优先级、按目标 revision 串行应用并产生 ControlReceipt。它不理解普通任务内容、不替 OrchestrationProvider 规划，也不把 Bot 消息升级成人类权限。

### 能力声明

`humancontrol.pause.v1`、`humancontrol.resume.v1`、`humancontrol.cancel.v1`、`humancontrol.intervene.v1`、`humancontrol.reassign.v1`、`humancontrol.agent.quarantine.v1`。能力分别标注 Task、ChildTask、Agent 目标和取消等级。

### 核心操作与模型

| 操作 | 输入 | 输出 | 语义 |
|---|---|---|---|
| `normalize` | 已鉴权 API 命令或 Channel Adapter 控制候选 | HumanIntervention | 统一目标、actor、causation 与 idempotency key |
| `authorize` | intervention、当前状态 | PolicyDecision | 本地用户优先；Bot/System 不获得 human 权限 |
| `apply` | intervention、expected_task_revision | ControlReceipt | 为目标分配单调 control_sequence |
| `get_receipt` | intervention_id | ControlReceipt | 状态为 accepted/applied/rejected/superseded |

重复 key 返回原 receipt。取消优先于暂停、恢复、插话和改派；终态之后的指令按冲突矩阵处理。控制 API 快速确认“已接受”，实际生效由 Provider 事件确认；超时显示 `accepted_not_confirmed`。

### 可替换性与映射

当前 Adapter 映射：显式提及、回复路由和部分内存级 pause/cancel 入口；跨 Agent 的完整暂停、取消、插话、改派及可靠确认尚未实现。

未来替代：Channel 语法或 GUI 可以改变，但都生成同一 HumanIntervention；上游支持更强控制时只提升 capability 等级，不改变控制优先级与 receipt 语义。
