# 05 本地 API 与事件契约

实施状态更新（2026-08-05）：产品自有 `cc-connect` 已实现 install-plan、install、uninstall、restore、managed-versions、Native Config plan/apply/state/rollback、Telegram Credential/Bot/Binding/Lease，以及 start/stop/restart/status/reconcile。确认仍绑定 plan_id、plan_digest、confirmation=true 与 Idempotency-Key；Secret 写入不持久化原始请求体。其他组件安装和生命周期写操作仍返回 CAPABILITY_UNSUPPORTED。

## 传输取舍

v1 默认且唯一必需传输是 loopback HTTP/1.1 + JSON；事件使用同一服务上的 Server-Sent Events。选择原因：PySide6 与其他未来 GUI 都能稳定调用；查询、命令和单向状态流足够；SSE 自带重连游标语义；不需要维护第二套 IPC API 或 WebSocket 双向状态机。

| 方案 | v1 决策 | 原因 |
|---|---|---|
| HTTP/JSON | 默认 | 工具成熟、语言无关、易生成客户端、适合资源与 Operation |
| SSE | 默认事件层 | 服务器到 GUI 单向状态/进度/脱敏日志，支持 `Last-Event-ID` |
| WebSocket | 不采用 | v1 无持续双向 RPC 需求；命令仍应通过可审计 HTTP |
| Windows IPC/named pipe | 未来兼容 | 可作为同一 HTTP/事件语义的传输绑定，不定义第二套模型 |

## 端点与本地鉴权

- 基础路径为 `/api/v1`，仅绑定 `127.0.0.1`。`::1` 是否同时启用是实现期安全决策。
- 安装时生成至少 256 bit 随机 API token，存入仅当前用户可读的 CredentialBackend。
- GUI 通过受 ACL 保护的服务发现记录取得 endpoint 与 token reference，再由安全 broker 获取短期连接凭据。
- 请求使用 `Authorization: Bearer <LOCAL_API_TOKEN>`；禁止 query token、URL 中的 Secret 和持久化明文 token。
- 服务端拒绝非 loopback remote address、非 loopback Host 和未允许的 Origin。没有 Origin 的原生客户端仍需 Bearer。
- token 轮换产生新服务 instance epoch；旧 token 有短暂排空窗口后失效。
- 日志不记录 Authorization、完整请求体中的敏感字段或服务发现文件内容。

## API 版本策略

1. URI 主版本冻结为 `/api/v1`；响应同时包含 `api_version` 和 `contract_version`。
2. v1 内可新增可选字段、端点、事件类型与 Capability；客户端必须忽略未知字段。
3. 不得改变既有字段含义、幂等语义、枚举含义或默认安全行为。
4. 破坏性变化进入 `/api/v2`，并提供明确并行支持窗口与迁移说明。
5. `experimental` 端点或字段带 `x-stability: experimental`，不得成为 GUI 启动必需项。
6. GUI 启动先读取 `/system/capabilities`；不支持的按钮隐藏或禁用，不通过试错探测。

## 查询与变更

- GET 是只读、可重试、不会启动健康测试或刷新外部状态。响应包含观测时间和 revision。
- 明确以 `:run`、`:check`、`:validate`、`:start` 等结尾的 POST 可以触发操作。
- 变更类请求必须携带 `Idempotency-Key`；配置与状态资源同时使用 `If-Match` 或 body 中的 `expected_revision`。
- 快速、纯本地且可原子完成的创建可返回 201；涉及外部组件或超过短请求预算的操作返回 202 与 Operation。
- 202 响应包含 `Location: /api/v1/operations/{operationId}`，断开连接不取消 Operation。

## 稳定端点清单

### 系统、发现与状态

| 方法与路径 | 语义 | 结果 |
|---|---|---|
| GET `/system` | Control Plane 实例、版本、启动时间 | SystemInfo |
| GET `/system/capabilities` | API 与 Provider 能力协商 | Capability[] |
| POST `/discovery:run` | 只读发现本机组件与依赖 | 202 Operation |
| GET `/readiness` | 最近一次扫描的就绪报告与 dry-run 计划 | ReadinessReport |
| GET `/components` | 组件快照与聚合状态 | Component[] |
| GET `/components/{componentId}` | 单组件详情、版本、Condition | Component |

### 安装、配置、Owner 与凭据

| 方法与路径 | 语义 | 结果 |
|---|---|---|
| POST `/components/{componentId}:install` | 安装或修复安装 | 202 Operation |
| GET `/components/{componentId}/configuration` | 读取脱敏配置、schema 与 revision | RedactedConfig |
| POST `/components/{componentId}/configuration:validate` | 校验候选或当前配置 | 202 Operation |
| PUT `/components/{componentId}/configuration` | Owner 校验后原子写入 | 202 Operation |
| GET `/components/{componentId}/management-owner` | 查询唯一写入方 | ManagementOwner |
| POST `/components/{componentId}/management-owner:transfer` | 备份并切换 Owner | 202 Operation |
| GET `/credentials` | 只列脱敏凭据元数据 | CredentialMetadata[] |
| POST `/credentials` | 保存 Secret；响应不回显值 | 201 CredentialMetadata |
| POST `/credentials/{credentialId}:validate` | 受限连通验证 | 202 Operation |
| DELETE `/credentials/{credentialId}` | 显式确认后删除 | 202 Operation |
| GET `/components/{componentId}/authentication` | 官方登录或 API 授权状态 | AuthenticationStatus |
| POST `/components/{componentId}/authentication:begin` | 发起官方登录引导 | 202 Operation |

### Agent、Capability 与 Channel

| 方法与路径 | 语义 | 结果 |
|---|---|---|
| GET `/agents` | 一等 Agent 清单 | Agent[] |
| GET `/agents/{agentId}` | Agent 状态、Runtime 与能力 | Agent |
| GET `/capabilities` | Registry 一致快照 | Capability[] |
| GET `/channels` | Channel 实例与连接状态 | Channel[] |
| GET `/channels/{channelId}` | 单 Channel 通用详情 | Channel |
| POST `/channels/{channelId}:validate` | 只读校验；不发送消息 | 202 Operation |
| POST `/channels/{channelId}:connect` | 连接目标状态 | 202 Operation |
| POST `/channels/{channelId}:disconnect` | 断开目标状态 | 202 Operation |

### 生命周期、健康、诊断与日志

| 方法与路径 | 语义 | 结果 |
|---|---|---|
| POST `/components/{componentId}:start` | 幂等启动 | 202 Operation |
| POST `/components/{componentId}:stop` | 幂等停止 | 202 Operation |
| POST `/components/{componentId}:restart` | 串行重启 | 202 Operation |
| POST `/components/{componentId}/health:check` | 只读健康检查；深度测试另需确认 | 202 Operation |
| GET `/diagnostics` | 脱敏诊断索引 | Diagnostic[] |
| GET `/diagnostics/{diagnosticId}` | 用户说明与已脱敏技术详情 | Diagnostic |
| GET `/logs` | 分页读取脱敏统一日志 | LogEntry[] |

### 更新、备份、回滚与迁移

| 方法与路径 | 语义 | 结果 |
|---|---|---|
| POST `/updates:check` | 检查兼容版本，不安装 | 202 Operation |
| POST `/components/{componentId}:update` | 备份后更新 | 202 Operation |
| POST `/components/{componentId}:rollback` | 回到已验证版本/配置 | 202 Operation |
| GET `/backups` | 备份与回滚点清单 | Backup[] |
| POST `/backups` | 创建配置/程序/凭据分层备份 | 202 Operation |
| POST `/backups/{backupId}:restore` | 恢复指定范围 | 202 Operation |
| POST `/migrations` | 导出或导入加密迁移包 | 202 Operation |

### Task 与人类控制

| 方法与路径 | 语义 | 结果 |
|---|---|---|
| GET `/tasks` | 分页查询 Task | Task[] |
| GET `/tasks/{taskId}` | Task、ChildTask、控制 revision | Task |
| POST `/tasks/{taskId}/interventions` | 暂停、恢复、取消、插话或改派 | 202 Operation + ControlReceipt 引用 |

### Operation 与事件

| 方法与路径 | 语义 | 结果 |
|---|---|---|
| GET `/operations` | 按状态、类型、目标查询 | Operation[] |
| GET `/operations/{operationId}` | 当前阶段与结果 | Operation |
| POST `/operations/{operationId}:cancel` | 请求取消；不承诺已终止 | 202 Operation |
| GET `/events` | 已鉴权 SSE；支持 topic 与游标 | CloudEvents 信封流 |

机器可读细节以 [OpenAPI](../../contracts/control-plane-v1/control-plane.openapi.yaml) 为准；若本文与规范冲突，评审必须同时修正两者，不能静默选择一方。

## Operation 契约

Operation 状态为 `queued/running/cancel_requested/succeeded/failed/canceled`。规则：

1. queued/running/cancel_requested 时 `result` 与 `error` 为空。
2. succeeded 时可以有 result，不得有 error。
3. failed/canceled 时有 UserFacingError；canceled 说明已完成与未执行阶段。
4. 取消返回新的“取消请求已接受”响应，但查询原 Operation 才能确认终态。
5. `progress.phase` 是稳定阶段码；message 是本地化用户文案，逻辑不能依赖文案。
6. `point_of_no_return=true` 后，取消只阻止安全的后续阶段。
7. Operation 至少保留到 GUI 完成重连和用户查看；具体保留期是开放实现参数。

## 幂等与并发

- Server 保存 `Idempotency-Key`、请求方法、资源、规范化 body 摘要和 Operation ID。
- 相同 key 与相同摘要返回原响应；相同 key 与不同摘要返回 409 `IDEMPOTENCY_KEY_REUSE`。
- 所有资源返回 ETag/revision。陈旧 `If-Match` 返回 412 `REVISION_CONFLICT`，响应给出当前 revision，不自动合并。
- Owner 切换、配置写入、更新和人类控制按目标资源串行；不同无依赖组件可以并行。
- Server 重启后保留幂等记录；无法确认外部副作用时 Operation 转 failed/unknown diagnostic，先探测再允许人工重试。

## 事件信封与 SSE

事件采用 CloudEvents 1.0 JSON 格式，必需字段为 `specversion`、`id`、`source`、`type`、`time`、`subject`、`datacontenttype`、`data`，本产品扩展为：

- `sequence`：同一 epoch 内严格递增整数
- `epoch`：Control Plane 事件纪元
- `resourceversion`：事件提交后的资源 revision
- `correlationid`：跨调用关联
- `operationid`：关联长操作，可选
- `severity`：debug/info/warning/error，可选

SSE 记录：

```text
id: <epoch>:<sequence>
event: com.aiagentdesktop.operation.progress.v1
data: {CloudEvents JSON object}
```

稳定事件类型至少包括：

- `com.aiagentdesktop.component.state.changed.v1`
- `com.aiagentdesktop.component.discovered.v1`
- `com.aiagentdesktop.provider.state.changed.v1`
- `com.aiagentdesktop.registry.changed.v1`
- `com.aiagentdesktop.operation.started.v1`
- `com.aiagentdesktop.operation.progress.v1`
- `com.aiagentdesktop.operation.completed.v1`
- `com.aiagentdesktop.operation.failed.v1`
- `com.aiagentdesktop.scan.progress.v1`
- `com.aiagentdesktop.plan.generated.v1`
- `com.aiagentdesktop.diagnostic.created.v1`
- `com.aiagentdesktop.task.state.changed.v1`
- `com.aiagentdesktop.log.appended.v1`

新增事件类型属 v1 向后兼容增量（见“API 版本策略”第 2 条），客户端必须忽略未知事件。`diagnostic.recorded` 语义由既有的 `diagnostic.created.v1` 承载，不另立类型。机器可读清单见 OpenAPI 顶层 `x-event-types`。

日志事件只携带脱敏摘要和 log entry ref，不嵌入无限长度原始日志。

## 重连、去重与顺序

1. 交付语义为 at-least-once；客户端用 `source + id` 去重。
2. 顺序只保证同一 epoch 的 sequence；不承诺不同 Provider 原始事件的全局发生顺序。
3. 状态写入与对应事件在同一产品事务中分配 resourceversion，GUI 可检测旧事件。
4. GUI 重连发送 `Last-Event-ID`。游标仍在保留窗口时从下一条重放。
5. 游标过期或 epoch 不可恢复时返回 410 `EVENT_CURSOR_EXPIRED`；GUI 重新 GET 状态快照，再无游标订阅。
6. SSE 断开不取消 Operation。客户端退避重连并加入抖动，不能高频轮询替代。
7. Provider 重复事件先由 Adapter 去重；无法去重时仍可由信封 id 和资源 revision 抑制重复 UI 更新。

## 超时

- HTTP 请求的短同步预算建议 5 秒；超出改为 202 Operation。
- 客户端超时只表示未收到响应，可用同一 idempotency key查询/重试。
- 每个 Operation 有 `deadline_at` 和 Provider 能力上限；达到 deadline 后进入取消请求或 failed，具体取决于安全阶段。
- 健康、登录和外部调用的 timeout 分开配置，不能用一个全局数字掩盖不同恢复策略。

## 用户错误与原始诊断双层表达

错误响应使用 `application/problem+json` 的基本语义，并增加稳定字段：

```json
{
  "type": "urn:ai-agent-desktop:error:management-owner-conflict",
  "title": "Configuration owner conflict",
  "status": 409,
  "code": "MANAGEMENT_OWNER_CONFLICT",
  "detail": "The requested configuration scope is read-only.",
  "user_message": "这项配置当前由其他工具管理，请先切换管理方。",
  "retryable": false,
  "recovery_actions": ["open_management_owner"],
  "diagnostic_id": "diag_example",
  "correlation_id": "corr_example"
}
```

默认层只展示 user_message 和 recovery_actions。Diagnostic 详情必须显式展开、已脱敏并受访问控制；Secret、个人消息正文、Authorization、私有路径和未清理堆栈在两层都禁止出现。

## 2026-08-05 向后兼容增量

OpenAPI v1 已新增固定 Telegram 凭据 put/replace/status/delete/capability、Bot getMe 身份与 webhook、Update Lease、Binding create/get/cancel/poll、cc-connect Native Renderer/plan/apply/state、external cc-connect 状态以及 Hermes Telegram plan/state。Secret 输入字段标记 writeOnly，响应模型没有 Secret 字段；Secret 写入 Operation 只持久化幂等摘要，不保存原始 body。

绑定轮询与 Bot 验证使用 202 Operation 和既有 Operation/SSE 语义；创建/读取绑定会话与配置计划使用同步资源。Webhook 删除必须提交 explicit_confirmation，Control Plane 不静默删除。机器可读路径与 Schema 以 control-plane.openapi.yaml 和 managed-runtime.schema.json 为准。
