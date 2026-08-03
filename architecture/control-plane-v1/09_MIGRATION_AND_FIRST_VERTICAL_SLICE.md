# 09 迁移与第一个最小纵向切片

实施状态更新（2026-08-04）：本文件定义的只读 Readiness 子集已经由 `control-plane/` 基础运行代码实现；真实生命周期接管、安装、配置写入和凭据写入仍未实现。下一阶段仅进入 cc-connect 单组件真实安装纵向切片。

## 迁移目标

迁移采用“先观测、后接管、逐项替换”的路线。Reference Baseline 始终是第一个 Adapter 对象和回归基准，不把现有脚本、数据库或 Patch 直接改造成 Control Plane 核心，也不要求一次切换全部组件。

每一阶段必须同时满足：可独立验收、默认不影响未接管链路、有明确回滚点、能力声明不超过真实证据。阶段失败只回滚本阶段，不用旧快照覆盖 `src/` 或当前配置。

## 阶段门禁

| 阶段 | 交付 | 进入条件 | 回归基准 | 回滚点 |
|---|---|---|---|---|
| 0 契约评审 | 本设计包、OpenAPI、JSON Schema、契约测试计划 | 本设计包解析和一致性检查通过 | 文档事实与冻结基线一致 | 保留本轮前公开仓库 Commit |
| 1 最小纵向切片 | 独立 Control Plane 骨架、只读 Adapter、受控 lifecycle、统一诊断 | v1 契约正式冻结；实现技术决策记录完成 | 现有单元测试；不产生真实消息的发现与健康测试 | Control Plane 可完全退出；旧启动所有权与配置不变 |
| 2 配置与凭据 | ManagementOwner、原子配置、CredentialBackend | Secret 安全评审、备份和冲突演练通过 | 配置读回、Owner 冲突、凭据不泄露测试 | 恢复旧配置；凭据引用回切；不删旧有效凭据 |
| 3 安装与更新 | 断点安装、更新、备份、回滚、迁移 | 包来源、签名、提权边界和磁盘恢复已评审 | 干净 Windows 沙箱首次安装与失败恢复 | 版本级回滚点和安装 journal |
| 4 人类控制 | 持久化 receipt、暂停、恢复、取消、插话、改派 | Provider 对每项能力给出可靠 ack 与取消等级 | 冻结 E2E 仍通过；新增竞态与幂等测试 | 按 capability 关闭控制入口，保留当前路由 |
| 5 正式 GUI 与扩展 | PySide6 GUI、完整十分钟体验；之后才评估新 Channel | API 客户端兼容和无头运行已验证 | GUI 关闭后台继续；所有状态和恢复动作可见 | GUI 可独立回退，不降级 Control Plane API |

阶段编号表达依赖，不要求一次发布包含整个阶段。每次增量都必须有 feature flag 或可撤销的所有权切换。

## 第一个最小纵向切片

### 明确范围

第一个切片形成一条真实但克制的管理链：

本机组件发现 -> 安装、配置、授权、运行与健康状态 -> 版本和能力 -> 配置只读校验 -> 启动、停止、重启 -> 健康检查 -> 脱敏日志与用户可理解错误。

该切片实现 Control Plane 服务和 Adapter 契约的最小代码，不实现正式 GUI。验收客户端可以是契约测试工具或最小开发壳，但不能绕过 API 直接读写上游。

### 1. 发现本机组件

- 入口：`POST /api/v1/discovery:run`，返回 Operation；结果通过 `GET /components` 查询。
- Provider：LifecycleProvider 的 `discover` 和 CapabilityRegistry 的只读快照。
- 输入：允许探测的组件种类与范围；默认只读，不扫描用户无关目录。
- 输出：Component、Provider、Agent、版本、观测时间、证据等级和 Condition。
- 失败：单个探针失败产生 Diagnostic，并把对应状态设为 unknown；其他组件继续返回。
- 验收：重复发现不产生系统修改；未知组件不被猜成未安装。

### 2. 展示正交状态

- 每个 Component 分别返回 InstallationState、ConfigurationState、AuthenticationState、RuntimeState、HealthState 和 UpdateState。
- Control Plane 按冻结优先级生成 `user_status`，同时保留底层状态和 `status_overlays`。
- 发现结果与期望不一致时输出 `Drift=True`，不自动修复。
- 首片只读取授权是否存在或是否有效，不读取真实 Secret，也不代替官方登录。

### 3. 展示版本和能力

- `GET /system/capabilities`、`GET /capabilities`、`GET /agents` 提供一致快照。
- Capability 必须包含版本、成熟度、availability 与限制；当前未验证的人类控制和讨论能力标为 experimental、unavailable 或 unsupported。
- Claude Code 与 Codex 始终是独立 Agent；Runtime 状态不能替代 Agent 状态。
- 静态配置是期望证据，进程和健康探针是观测证据，两者不能合并成虚假 ready。

### 4. 配置只读校验

- `GET /components/{componentId}/configuration` 只返回脱敏结构、schema、Owner 候选和 revision。
- `POST .../configuration:validate` 默认执行结构与引用完整性检查，不写文件、不轮换凭据、不访问真实消息 Channel。
- 首片不提供配置写入和 Owner 交接的可用实现；对应 Capability 标 unavailable，即使 OpenAPI 已冻结未来端点。
- 解析失败返回字段级安全摘要和恢复建议，不返回配置正文、私有路径或 Secret 片段。

### 5. 启动、停止和重启

生命周期接管分两个小门禁实施：

1. shadow plan：识别现有启动所有者、目标进程、依赖、命令与预期结果，只生成计划，不执行。
2. controlled takeover：仅在隔离环境回归、备份旧启动定义并由用户显式确认后，对一个组件启用 start/stop/restart。

每个动作返回 Operation，使用 Idempotency-Key 和目标状态幂等。restart 是单个串行操作；超时后先重新探测，不把“命令已发出”当成“组件已停止或运行”。旧计划任务、Watchdog 与 Control Plane 不能同时拥有启动权。首片若尚未通过接管门禁，API 返回 `CAPABILITY_UNSUPPORTED`，不得调用现有脚本冒充实现完成。

### 6. 健康检查

- 默认健康检查只做进程身份、受限端点、依赖和版本等无副作用探测。
- 会产生外部消息、模型调用或登录刷新的深度测试不属于默认 health check，首片不执行真实 Telegram E2E。
- 每个探针有独立 timeout；部分探针失败聚合为 degraded，不抹去成功结果。
- 结果含稳定 reason、用户说明、建议动作和可展开 Diagnostic 引用。

### 7. 统一日志与错误

- SanitizedLogAdapter 只读取明确允许的日志源，先结构化允许字段再脱敏。
- 默认不采集聊天正文、Authorization、配置正文、登录回调、命令行 Secret 或私有绝对路径。
- `GET /logs` 使用分页与时间游标；事件只携带 log entry ref 和短摘要。
- 所有失败同时给出稳定错误码、用户可理解说明、可执行恢复动作和脱敏 Diagnostic。

## 首片内部模块边界

首片最少需要以下可替换模块，但不建立通用插件平台：

- API Host：HTTP/JSON、SSE、本地鉴权、Host/Origin 校验和版本协商。
- Operation Store：幂等记录、阶段进度、取消请求、恢复 journal。
- State Store：Component 快照、revision、Condition 与聚合状态。
- Adapter Host：只装载内置 Adapter，做超时、取消和故障隔离。
- Discovery/Observation Adapters：发现组件、进程、版本与只读健康。
- Configuration Validation Adapter：脱敏读取与无副作用校验。
- Lifecycle Takeover Adapter：只有通过门禁的组件才暴露写能力。
- Diagnostic Pipeline：结构化分类、脱敏、用户错误与审计。

这些模块可以同属 Control Plane 进程；进程外 Provider 插件不是 v1 要求。

## 首片验收场景

1. GUI 或契约客户端关闭后，Control Plane 和已运行组件继续工作。
2. Control Plane 停止后，未接管的 Reference Baseline 链路继续按原所有权运行。
3. 对同一发现、启动、停止请求重放相同 idempotency key，不产生第二次副作用。
4. 组件状态无法确认时显示 unknown 和恢复建议，不显示虚假绿色。
5. 一个 Adapter 超时或崩溃不拖垮 API 和其他组件观测。
6. SSE 断开重连后可去重；游标过期时先取快照再订阅。
7. 配置校验前后文件哈希不变，Secret 扫描和请求日志检查无泄露。
8. lifecycle 接管失败可以恢复旧启动所有权，不出现双 supervisor。
9. `src/` 与 5 个 Patch 的哈希和冻结基线一致。
10. 不发送真实 Telegram 消息、不升级上游、不接入新 Channel。

## 后续迁移规则

- 配置写入与凭据迁移不得和首次 lifecycle 接管放在同一风险变更中。
- 每替换一个 Adapter，都要通过共同契约测试、状态映射测试、基线回归和回滚演练。
- 临时 Patch 只有在上游等价能力已验证后删除；不能为了架构整洁提前移除。
- 新 Channel 复用 Channel/Conversation/Message/Mention/Reply，不给核心 schema 增加平台字段。
- 正式 GUI 只使用 OpenAPI 和事件契约；禁止把 Adapter 私有路径作为“临时接口”。

## 首片非目标

- 正式 PySide6 GUI 大开发
- 新 Channel、新 Agent Runtime 或新编排器
- 完整安装器、自动更新和跨机迁移实现
- 配置写入、Owner 自动切换和真实凭据迁移
- 完整讨论模式或人类控制执行能力
- 扩大 dual_agent、cc-connect Patch 或真实 Telegram E2E
- 通用 DAG、消息总线、插件市场或分布式 Control Plane
