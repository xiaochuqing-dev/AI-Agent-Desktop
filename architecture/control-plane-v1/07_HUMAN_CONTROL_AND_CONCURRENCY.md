# 07 人类控制与并发

## 原则

1. 已鉴权人类指令优先于任何自动编排、Agent 建议和 Provider 默认行为。
2. “已接受控制请求”与“外部工作已停止/暂停”是两件事，必须分别确认。
3. Channel 指令与 GUI 本地 API 最终都变成同一 HumanIntervention。
4. Bot、Agent 和系统消息不能获得人类控制权限。
5. 每个目标的控制指令按单调 `control_sequence` 串行化，并用 task revision 防止基于旧状态误操作。
6. 上游不支持的控制能力必须返回 unsupported，不允许用静默丢弃模拟成功。

## HumanIntervention

必需字段：

- intervention_id
- actor_ref 与 actor_kind=human
- source=local_api/channel
- action=pause/resume/cancel/intervene/reassign
- target_type=task/child_task/agent
- target_id
- idempotency_key
- expected_revision
- issued_at
- payload：插话文本引用或目标 agent，可选
- causation_id：来源消息或 GUI command 的通用引用

服务端返回 ControlReceipt：`accepted/applied/rejected/superseded/accepted_not_confirmed`、control_sequence、operation_id、provider_ack、effective_state、reason 和 observed_at。

## 五类控制

### 插话 intervene

把人类新增约束写入目标的控制流。默认不强行终止正在进行的外部调用；在下一个安全检查点注入后续步骤。若 Provider 声明支持当前调用动态输入，可更早应用，但 receipt 必须说明实际应用点。

已完成任务不能插话；用户可以基于原任务创建新任务，二者保持关联。

### 暂停 pause

阻止目标开始新的工作，并请求正在进行的工作在安全点暂停。状态经过 `running -> pausing -> paused`。Provider 仅支持 checkpoint 时，当前调用可能先完成；GUI 显示“正在暂停”，不能提前显示“已暂停”。

### 恢复 resume

只对 paused/pausing 合法。恢复前重新验证 Agent、授权、配置与 deadline；条件不满足则 rejected。对 running 重复恢复是 no-op，对终态恢复是冲突。

### 取消 cancel

状态经过 `running/paused/queued -> cancel_requested -> canceled|succeeded|failed`。取消优先级最高，但仍是尽力而为：外部工作可能在请求生效前成功。取消后不调度新的 ChildTask；已产生输出标记为 `completed_before_cancel` 或 `partial_after_cancel`，默认不进入后续自动编排。

### 改派 reassign

不修改旧 ChildTask 的 agent_id。系统请求旧 ChildTask 取消或停止接续，创建带 `replaces_child_task_id` 的新 ChildTask，并传递经用户确认的必要上下文。旧任务与替代任务均可审计。

## Task、ChildTask 与 Agent 目标差异

| 操作 | Task | ChildTask | Agent |
|---|---|---|---|
| pause | 停止新建/调度所有子任务，并按能力请求活跃子任务暂停 | 只暂停该子任务；父任务进入等待或降级 | 将 Agent 置调度隔离；默认不影响已运行任务 |
| resume | 恢复父任务并重新评估可运行子任务 | 只恢复该子任务 | 解除未来调度隔离，不自动重启失败任务 |
| cancel | 取消父任务并请求所有非终态子任务取消 | 只取消该子任务；父任务按依赖决定部分失败 | 不作为“杀死 Agent”快捷方式；需指定 Task/ChildTask |
| intervene | 更新父任务后续约束 | 注入该子任务的下个安全点 | 只更新该 Agent 的未来路由约束 |
| reassign | 对未完成执行计划创建替代子任务 | 创建一个替代 ChildTask | 更改未来选择，不改写历史任务归属 |

Agent 级 pause 是治理隔离，不等于 LifecycleProvider 停止 Runtime。停止进程是独立、显式的生命周期操作。

## 优先级与线性化

所有人类控制都高于自动动作。对同一目标并发到达时：

1. 服务端在目标锁内检查 expected revision。
2. 分配 control_sequence 并持久化 receipt。
3. cancel 使尚未应用的 pause/resume/intervene/reassign 变为 superseded。
4. 除 cancel 外，按 control_sequence 顺序应用；后到指令基于最新 revision 重新判定，不是无条件覆盖。
5. 每次状态变化增加 revision；Provider ack 与资源状态在事件中发布。

不同目标可并行，但父 Task 的 cancel 会建立 cancellation fence：该 fence 之后不得开始新的 ChildTask，即使某个子任务的 start 已排队。

## 冲突矩阵

| 当前状态 | pause | resume | cancel | intervene | reassign |
|---|---|---|---|---|---|
| queued | applied -> paused | no-op/rejected | applied -> canceled | accepted，首步前应用 | applied，替换目标 |
| running | accepted -> pausing | no-op | accepted -> cancel_requested | accepted，安全点应用 | accepted，先处理旧 ChildTask |
| pausing | no-op | accepted，可撤销未生效 pause | cancel 优先 | 排队在 pause 后 | 排队或由 cancel 策略处理 |
| paused | no-op | applied -> running | accepted -> cancel_requested | applied 到恢复上下文 | applied，保持父任务暂停 |
| cancel_requested | superseded | superseded | 返回原 receipt | rejected | rejected |
| succeeded | conflict | conflict | no-op，说明已完成 | rejected，可创建新任务 | rejected，可创建新任务 |
| failed | conflict | conflict | no-op | rejected，可创建重试任务 | rejected，可创建替代任务 |
| canceled | conflict | conflict | no-op | rejected，可创建新任务 | rejected，可创建新任务 |

“no-op”仍返回当前状态和原始/新 receipt，不伪造一次新的 Provider 调用。

## 幂等与重复命令

- 同一 idempotency key 与相同 intervention 返回同一 ControlReceipt。
- 同一 key 指向不同 action/target 返回 409。
- 不同 key 的语义重复命令按状态矩阵处理，例如 paused 上再次 pause 为 no-op。
- Channel 重投、SSE 重连和 GUI 双击不能产生重复控制副作用。
- receipt 与 Operation 至少跨 Control Plane 重启保留；重启后先查询 Provider 实际状态。

## 超时与未确认

本地 API 接受控制请求应快速返回 202。Provider 在 deadline 内没有确认时，receipt 为 `accepted_not_confirmed`，任务状态保持 pausing/cancel_requested 或 unknown，并产生 Diagnostic。系统可以继续探测，但不能自动发送第二个不同 idempotency key。

强取消只有 Provider 明确声明并证明目标已终止时才为 applied。终止本地等待线程不等于强取消外部工作。

## Channel 与 GUI 的统一语义

### GUI

GUI 直接提交结构化 HumanIntervention，actor 来自本地鉴权 principal。按钮在 Capability 不支持时禁用，并展示原因。

### Channel

1. Channel Adapter 验证消息发送者是获授权人类。
2. Adapter 把平台语法解析为通用 action、target 与 causation_id。
3. 无法唯一确定目标时只返回澄清，不猜测最近任务。
4. Control Plane 使用与 GUI 相同的 authorize/apply 路径。
5. 结果由通用 ControlReceipt 生成用户消息，再由 Channel Adapter 发送。

Channel 专属 Mention、Reply 和用户标识不进入 HumanControlPolicy；归一化之后只使用通用引用。

## Bot 消息防环

每条归一化 Message 必须标记 sender_kind、delivery_id、causation_id、origin_event_id 和 hop_count。

防环规则：

- sender_kind=agent/system 的消息永不转为 HumanIntervention。
- Control Plane 产生的状态通知标记 system，Channel Adapter 不再回送为新命令。
- 相同 channel_id + delivery_id 只处理一次。
- Reply 或 Mention 只改变路由上下文，不覆盖 sender_kind。
- causation 链出现重复 event id 或超过 Adapter 声明 hop 上限时停止并生成 Diagnostic。
- 一个 Bot 的正式输出不会因包含控制词、另一个 Agent 名称或命令样式而触发控制。

## 授权

- 默认只有当前本地用户及明确配置的 Channel 管理员可以控制 Task。
- reassign、Agent 级隔离和强制停止可以要求更高角色。
- 授权失败只记录 actor ref 的不可识别内部 ID，不在普通日志暴露平台身份。
- 多人同时控制时仍遵循 revision 和 control_sequence，不以客户端时间排序。

## 当前能力边界

Reference Baseline 已有显式人类指定和回复路由，并存在部分内存级暂停/取消入口，但没有上述跨进程可靠 ack、持久化 control_sequence、完整插话或改派。Adapter 必须按真实能力声明，第一纵向切片只展示状态，不把这些设计能力提前标为已实现。
