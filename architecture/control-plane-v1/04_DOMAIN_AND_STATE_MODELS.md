# 04 领域与状态模型

## 通用规则

- 所有 ID 是 Control Plane 生成或规范化的不透明字符串，不编码文件路径、平台类型或 Secret。
- 所有可变资源包含 `revision`、`observed_at` 和 `conditions`；修改必须携带预期 revision。
- `desired` 表示产品期望，`observed` 表示 Adapter 最近可靠观测。两者不一致产生 `Drift=True` Condition，不自动覆盖。
- 时间使用 UTC RFC 3339；持续时间使用毫秒整数。
- 通用 Channel 模型严禁出现平台专属 ID、实体类型或原始消息对象。Adapter 维护私有映射。
- `unknown` 表示证据不足，不等同于失败、停止或未安装。

## 核心实体

| 模型 | 关键字段 | 语义与边界 |
|---|---|---|
| Component | component_id、kind、display_name、version、state、provider_refs | 可安装、配置或运行的产品组件；不等于进程 |
| Provider | provider_id、kind、adapter_id、contract_versions、capabilities、state | 某类能力端口的一个实现实例 |
| Adapter | adapter_id、implementation_version、component_refs、provider_kinds、state | 防腐与翻译实现；不向 GUI 暴露私有结构 |
| Agent | agent_id、display_name、runtime_ref、roles、capability_refs、state | 用户可直接选择或由编排调用的一等 Agent |
| Capability | capability_id、version、maturity、availability、constraints | 可协商的最小能力单元，不表示实现类名 |
| Runtime | runtime_id、component_id、process_refs、state、session_capabilities | 承载 Agent 调用的外部执行环境；process_refs 只对受信诊断可见 |
| Channel | channel_id、provider_id、display_name、connection_state、capabilities | 一个已配置消息通道实例 |
| Conversation | conversation_id、channel_id、scope、participant_refs、isolation_key | 通用会话与隔离边界；scope 为 direct/group/thread/project |
| Message | message_ref、conversation_id、sender_ref、sender_kind、content、mentions、reply、causation_id | 归一化消息；sender_kind 为 human/agent/system |
| Mention | target_agent_id、source、span 可选 | 对 Agent 的显式指向；source 为 native/parsed/command |
| Reply | replied_to_ref、replied_to_sender_ref、excerpt 可选 | 回复关系；原始平台引用只留 Adapter |
| Task | task_id、pattern、status、target_refs、child_task_refs、result_ref、revision | 一次用户可见的编排任务；不是通用 DAG |
| ChildTask | child_task_id、parent_task_id、agent_id、sequence、depends_on_previous、status、result_ref | 单 Agent 子任务；v1 只支持单步、并行或线性顺序 |
| TaskResult | result_id、task_id、status、outputs、failures、completed_at | 保留所有成功与失败，不因部分失败丢结果 |
| HumanIntervention | intervention_id、actor、source、action、target_type、target_id、payload、idempotency_key、expected_revision | 已归一化的人类控制指令 |
| ManagementOwner | scope_id、owner_type、state、revision、since、transfer_id | 一个配置作用域的唯一写入管理方 |
| Operation | operation_id、kind、target_ref、status、progress、result/error、idempotency_key、timestamps | 安装、启停、配置等控制操作；不承载 Agent 推理 |
| OperationProgress | phase、percent 可选、message、completed_units、total_units、point_of_no_return | 可恢复的阶段进度；percent 未知时省略 |
| Diagnostic | diagnostic_id、severity、code、summary、user_message、suggested_actions、technical_details、redaction_applied | 技术诊断；technical_details 已脱敏且默认折叠 |
| UserFacingError | code、message、retryable、recovery_actions、diagnostic_id、operation_id | 面向用户的错误层，不含堆栈与 Secret |

## 状态对象

Component 的状态由六个正交对象组成，不能压缩成单一 online/offline。

| 状态对象 | 枚举 |
|---|---|
| InstallationState | unknown、not_installed、installing、installed、uninstalling、failed |
| ConfigurationState | unknown、missing、validating、valid、invalid、conflict |
| AuthenticationState | unknown、not_required、required、authenticating、authenticated、expired、invalid |
| RuntimeState | unknown、stopped、starting、running、stopping、restarting、failed |
| HealthState | unknown、checking、healthy、degraded、unhealthy |
| UpdateState | unknown、checking、up_to_date、update_available、updating、rollback_available、rolling_back、failed |

StateSnapshot 包含上述状态、`user_status`、`status_overlays`、`conditions`、`revision`、`observed_generation` 和 `observed_at`。

## Condition

Condition 用于表达不适合塞入状态枚举的正交事实：

| 字段 | 说明 |
|---|---|
| type | 稳定条件名，如 Ready、DependenciesReady、Authenticated、Drift、CapabilityDegraded |
| status | true、false、unknown |
| reason | 稳定机器码，不使用自由文本做逻辑判断 |
| message | 已脱敏的人类说明 |
| observed_generation | 该观测对应的期望状态 generation |
| last_transition_time | 条件真假最后变化时间 |

当 `observed_generation < generation` 时，GUI 标记“状态正在刷新”，不能把旧 Condition 当成当前结论。

## 状态机

### InstallationState

允许转换：

- unknown -> not_installed、installed、failed
- not_installed -> installing
- installing -> installed、not_installed、failed
- installed -> uninstalling
- uninstalling -> not_installed、installed、failed
- failed -> unknown、installing、uninstalling

`installed -> not_installed` 必须经过 uninstalling；只删状态记录不算卸载。探测丢失时转 unknown，不直接判定卸载。

### ConfigurationState

允许转换：

- unknown -> missing、validating、valid、invalid、conflict
- missing -> validating
- validating -> valid、invalid、conflict、missing
- valid -> validating、conflict
- invalid -> validating、conflict、missing
- conflict -> validating；只有 Owner 冲突解决或用户选择来源后才能继续

候选配置校验不改变当前 `valid` 配置；只有原子提交成功才发布新 revision。

### AuthenticationState

允许转换：

- unknown -> not_required、required、authenticated、expired、invalid
- required -> authenticating、not_required
- authenticating -> authenticated、required、invalid
- authenticated -> expired、invalid、required
- expired -> authenticating、required
- invalid -> authenticating、required

超时从 authenticating 回到 required 或 invalid，并保留原因。检测不到登录态转 unknown，不自动注销。

### RuntimeState

允许转换：

- unknown -> stopped、running、failed
- stopped -> starting
- starting -> running、stopping、failed
- running -> stopping、restarting、failed
- restarting -> running、stopping、failed
- stopping -> stopped、running、failed
- failed -> starting、stopping、unknown

重复 start/stop 是 no-op。restart 是一个串行 Operation；不得并发创建独立 stop 与 start。超时后若实际状态不明则转 unknown 并探测。

### HealthState

允许转换：

- unknown、healthy、degraded、unhealthy -> checking
- checking -> healthy、degraded、unhealthy、unknown
- Provider 主动可靠事件可在 healthy、degraded、unhealthy 间转换

健康状态不直接启动、停止或修复组件。深度健康测试若会发外部消息，必须是单独、经用户确认的操作。

### UpdateState

允许转换：

- unknown、up_to_date、update_available、failed -> checking
- checking -> up_to_date、update_available、failed
- update_available -> updating
- updating -> up_to_date、rollback_available、failed
- rollback_available -> rolling_back、checking
- rolling_back -> up_to_date、rollback_available、failed
- failed -> checking、rolling_back

检测到版本变化不自动进入 updating。更新前必须创建或确认回滚点。

## Provider、Task 与 Operation 状态机

### Provider

`unavailable -> discovered -> initializing -> ready`；ready 可进入 degraded 或 error；degraded 可恢复 ready 或进入 error；任何实现变化后重新进入 initializing；无兼容版本进入 incompatible。incompatible 只能在 Adapter/契约变化后重新协商。

### Task 与 ChildTask

允许转换：

- queued -> running、cancel_requested、canceled、failed
- running -> pausing、cancel_requested、succeeded、failed
- pausing -> paused、cancel_requested、running、failed
- paused -> running、cancel_requested、failed
- cancel_requested -> canceled、succeeded、failed
- succeeded、failed、canceled 为终态

`cancel_requested -> succeeded` 合法：外部工作可能在取消生效前完成，UI 必须如实说明。终态不能恢复；改派通过新建替代 ChildTask 完成，不复活旧任务。

### Operation

允许转换：

- queued -> running、cancel_requested、canceled、failed
- running -> cancel_requested、succeeded、failed
- cancel_requested -> canceled、succeeded、failed
- succeeded、failed、canceled 为终态

Operation 的 `result` 与 `error` 在终态互斥；非终态两者均为空。删除 Operation 记录不等于取消实际操作。

## ManagementOwner 状态机

owner_type 为 `application`、`official_login`、`cc_switch` 或 `external`；state 为 `unassigned`、`owned`、`transfer_preparing`、`transfer_committing`、`conflict`。

允许转换：

1. unassigned -> owned：首次确认 Owner。
2. owned -> transfer_preparing：锁定 expected revision、读取双方能力、创建备份。
3. transfer_preparing -> transfer_committing：旧 Owner 已只读，目标配置验证通过。
4. transfer_committing -> owned：原子写入新 Owner 与 revision，再启用新写方。
5. transfer_preparing/transfer_committing -> owned：失败时恢复原 Owner 和备份。
6. 任意可写状态 -> conflict：检测到未知外部写入或多个 Owner 标记。
7. conflict -> transfer_preparing：用户明确选择来源后重新交接。

任何时刻只有 state=owned 的 owner_type 可以写。切换期间所有普通写入返回冲突，不存在双写过渡。

## 用户状态聚合

`user_status` 只用于默认展示，底层正交状态始终保留。按以下优先级选择第一个命中项：

1. installation=not_installed -> `not_installed`
2. configuration=conflict/invalid -> `configuration_invalid`
3. configuration=missing -> `installed_unconfigured`
4. authentication=required/expired/invalid -> `login_required`
5. runtime=starting/restarting -> `starting`
6. runtime=failed -> `start_failed`
7. runtime=running 且 health=degraded/unhealthy，或关键 Capability 不可用 -> `partially_degraded`
8. update=update_available -> `update_available`
9. runtime=running 且 health=healthy -> `running_healthy`
10. runtime=stopped -> `stopped`
11. 其他 -> `unknown`

`status_overlays` 可同时包含 `update_available`、`operation_in_progress`、`drift_detected`、`restart_required`。例如运行正常且有更新时，主状态可以是 update_available，同时底层 runtime 仍明确为 running。

多组件系统聚合规则：

- 任一必需组件处于阻断状态，系统采用最高优先级阻断状态。
- 可选组件异常只产生 partially_degraded，不把整个系统标为启动失败。
- 所有必需组件 runtime=running 且 health=healthy 才是 running_healthy。
- 未观测组件产生 unknown Condition；不能用其他组件状态代填。

## 不可逆与高风险操作

以下动作至少要求预检、影响清单、显式确认、审计记录和幂等 key：

- 卸载并清理用户数据
- 删除最后一份配置备份或迁移源
- 删除 Credential 或撤销不可恢复的外部授权
- 在无可用回滚点时更新
- 迁移完成后清理源机材料

不可逆操作不能由“重试上一个按钮”隐式触发。Operation 进入 `point_of_no_return=true` 后，取消只能停止后续阶段并报告已完成影响。

## Channel 通用模型约束

Conversation 使用 `conversation_id` 与 `scope`；Message 使用 `message_ref`；Reply 使用 `replied_to_ref`；Mention 使用 `target_agent_id`。平台专属字段只存在 Adapter 内部映射表，不能放进 `extensions`、`metadata` 或“可选回退字段”绕过本约束。

Message 的 `sender_kind` 决定控制权限。只有 sender_kind=human 且通过 Channel Adapter 身份验证，或本地 API 的已鉴权 principal，才可生成 HumanIntervention。agent/system 消息即使包含控制词或 Mention 也不能获得人类优先级。
