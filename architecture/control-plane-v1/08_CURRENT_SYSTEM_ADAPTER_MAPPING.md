# 08 当前系统 Adapter 映射

实施状态更新（2026-08-05）：除本文件原有只读 Adapter 映射外，当前已有仅限产品自有 cc-connect 的隔离安装、managed/native 配置分离、Windows Credential Manager、Telegram 三 Bot 身份与绑定、Native Config Renderer、运行时 Secret 注入和受管生命周期 Adapter。它不接管下述 Reference Baseline、计划任务、Watchdog、junction 或外部运行服务；`src/` 与既有 5 个 Patch 内容保持冻结。

## 映射原则

本文件是具体实现名可以出现的唯一正式映射层之一。通用模型和稳定 API 不继承这些内部名称。映射基于公开仓库事实源和已冻结 E2E，不重新运行真实消息测试。

能力标记：

- `verified`：有当前源码与冻结 E2E/版本证据
- `partial`：存在入口，但不满足完整 v1 语义
- `read_only_candidate`：可先只读包装
- `missing`：当前没有可靠实现
- `temporary`：由兼容层提供，具备明确退场条件

## 当前拓扑

- Hermes Bot 由 Hermes 自身 Telegram platform 直连，不经过 cc-connect。
- Claude Code Bot 和 Codex Bot 由 cc-connect 连接 Telegram。
- Hermes multiagent 是默认治理与编排主体。
- dual_agent 提供当前并行/顺序纯逻辑回退。
- cc-connect 5 个 Patch 补齐显式路由、Hook header、展示和 delivered message 映射。
- 当前运行关键源码与 `src/` 对齐；本设计不修改运行环境。

## Provider 映射总表

| v1 契约 | 当前 Adapter 候选 | 已有能力 | 主要缺口 | 第一阶段策略 |
|---|---|---|---|---|
| OrchestrationProvider | Hermes multiagent Adapter | 单 Agent、并行、顺序、结果汇总 verified | 讨论未 E2E；控制 ack、改派缺失 | 先只读声明能力与 Task 查询，不改编排路径 |
| AgentRuntimeProvider | cc-connect relay Adapter | Claude Code/Codex 调用与 Session 连续 partial/verified | 统一 Agent 状态、强取消、稳定 Session API 缺失 | 包装版本/进程/可用性；调用路径保持现状 |
| ChannelProvider | Hermes Telegram Adapter + cc-connect Telegram Adapter | 提及、Reply、群/私聊隔离、三 Bot 路由 verified | Hook best-effort；通用连接管理缺失 | 从现有事件只读映射通用状态 |
| LifecycleProvider | Reference Baseline 只读 Adapter + 产品自有 cc-connect Adapter | 隔离安装、start/stop/restart/status/reconcile、进程身份与回滚 verified | 自动更新、跨机迁移、外部生命周期接管缺失 | 继续限制在产品自有实例 |
| ModelConfigurationProvider | Reference Baseline 只读 Adapter + cc-connect Native Config Renderer | managed/native 分离、schema、Owner、revision、备份、漂移检测与回滚 verified | Hermes 未安装时仅能生成 pending 计划；通用组件写入缺失 | Claude/Codex 走受管原生配置；外部配置只读 |
| CredentialProvider | Windows Credential Manager + 显式 Fake 后端 | Telegram 固定引用的 put/replace/status/resolve/delete/metadata/revision verified | 加密导入导出、跨机迁移、通用 Provider Secret 缺失 | Secret 仅在受限 Operation 内解析并注入目标子进程 |
| CapabilityRegistry | multiagent.yaml、relay bindings、版本事实 Adapter | 三个 Agent 与静态角色已知 | 动态注册、版本协商、心跳缺失 | 从配置与进程探测建立只读快照 |
| HumanControlPolicy | Hermes routing/intervention Adapter | 显式 @、Reply、部分 pause/cancel入口 | 插话、持久化 ack、强控制、改派缺失 | 只声明 verified 能力；完整控制后续实现 |

表中 Reference Baseline 项仍为只读映射。新的产品自有路径独立于该基线：LifecycleProvider 已实现真实 cc-connect start/stop/restart/status/reconcile，ModelConfigurationProvider 已实现锁定版本的原生配置、revision、备份和回滚，CredentialProvider 已通过 Windows Credential Manager 安全写入与按 Operation 解析 Telegram Token；任何 API、SQLite、配置、日志或命令行都不保存或回显 Token。

## Hermes Orchestration Adapter

### 当前来源

- `src/hermes-adapter/__init__.py`：pre-dispatch、计划入口、活跃 Orchestrator 与部分干预
- `src/hermes-adapter/_planner.py`：语义计划
- `src/hermes-adapter/orchestrator.py`：委派、并行/顺序、讨论/执行路径和内存控制
- `src/hermes-adapter/store.py`：当前 multiagent SQLite 状态与审计
- `src/dual-agent-fallback/`：并行、线性顺序、部分失败与跳数保险丝

### 可映射能力

- `orchestration.single.v1`：verified
- `orchestration.parallel.v1`：verified，temporary dual_agent
- `orchestration.sequential.v1`：verified，temporary dual_agent
- `orchestration.discussion.v1`：experimental，未真实 E2E
- Task 基础查询：partial；当前表结构和状态值不是 v1 领域 schema
- pause/cancel：partial；只在内存 Orchestrator 的轮次检查点生效

### 不能声称的能力

当前 cancel 不终止已经发出的 relay 外部调用；reply-to-task 只标记干预，不保证真正注入下一轮；没有可靠 reassign；进程重启后内存 Orchestrator 与控制状态不能恢复。因此 Adapter 必须声明 `checkpoint` 或 `best_effort`，不能声明 strong。

`multiagent.db` 是当前实现私有存储，不直接升级为 Control Plane 数据库。首阶段只读映射，避免 GUI 绑定现有表结构。

## cc-connect Agent Runtime Adapter

### 当前来源

- `src/hermes-adapter/relay_client.py` 调用 `cc-connect relay send`
- `src/lifecycle/cc-connect/cc_connect_autostart.py` 启动当前 daemon
- `integrations/cc-connect/` 保存上游版本、5 Patch、构建与校验证据

### 可映射能力

- Claude Code 与 Codex 作为两个独立 Agent：verified
- relay 调用与完整回复：verified
- 按 chat/agent/epoch 的 Session 连续：当前代码存在，长期稳定性仅 partial
- 调用 timeout：partial；超时不杀死 Agent 进程
- Agent 状态：read_only_candidate，可通过进程、版本、配置存在和受限 CLI 检查组合

### 缺口

没有冻结的 Agent 管理 API、统一强取消、可靠调用 receipt、统一 Session 枚举与跨进程 Operation。首片不能把 CLI 文本输出直接暴露给 GUI。

## Channel Adapter

### Hermes 侧

Hermes 自身 platform 接收和发送其 Bot 消息。`policy.py` 当前直接处理 Telegram 字段，这是 Reference Baseline 内部事实；未来 Hermes Channel Adapter 必须在边界处转换为 Channel/Conversation/Message/Mention/Reply，通用核心不复用 `RouteInput` 的专属字段。

### cc-connect 侧

两个 Worker Bot 由 cc-connect Telegram platform 承载。Patch 映射：

| Patch | 当前作用 | v1 契约位置 | 退场条件 |
|---|---|---|---|
| 001 directed routing | Reply + 显式 @ 时显式目标优先 | ChannelAdapter normalize/routing evidence | 上游原生等价规则并回归通过 |
| 002 hook headers | Authorization header 透传 | Adapter 内部安全传输 | 上游正式支持 headers |
| 003 response prefix | Worker 以自身身份展示 | Channel delivery presentation | 上游提供可配置展示策略 |
| 004 delivery hooks | 真实出站 message ref 与 metadata | DeliveryReceipt/私有 ref 映射 | 上游提供正式 delivered event |
| 005 Windows build | 修复当前构建 | 非运行契约 | 上游修复或升级后不再需要 |

Hook receiver 绑定 localhost 且使用 Bearer header，但 delivery 事件管道是 fire-and-forget/best-effort。它可以提供 Diagnostic 和最近观测，不能作为强一致事件总线或完整 Transcript 承诺。

### 通用字段映射

Adapter 私有保存平台 chat/message/entity 值，并仅输出：

- 平台会话 -> `channel_id` + `conversation_id`
- 平台消息 -> `message_ref`
- 平台提及 -> `Mention.target_agent_id`
- 平台回复 -> `Reply.replied_to_ref`
- 平台发送结果 -> `DeliveryReceipt`

私有原值不进入 OpenAPI、JSON Schema、普通日志或 GUI 状态。

## Lifecycle Adapter

### 当前来源与可读能力

- Hermes Gateway VBS/CMD 与 Watchdog：启动来源和配置可发现
- cc-connect autostart VBS/Python：进程路径与启动来源可发现
- `health-check.ps1`：junction 与 dual_agent 文件存在性检查
- 构建/应用 Patch 脚本：仅作为恢复证据，不由首片执行

read_only_candidate：文件存在、版本、哈希、进程身份、监听可达性、计划启动来源和依赖状态。读取时必须使用占位/脱敏路径输出。

### 安全接管门禁与现状

产品自有 cc-connect 路径已经按以下门禁实现并通过合成 Windows 验收；Reference Baseline 与外部实例仍只读：

1. 用可验证进程身份而非进程名定位目标。
2. 明确谁拥有启动权，避免旧计划任务与 Control Plane 双重拉起。
3. 保存当前启动链配置和回滚入口。
4. start/stop 具备目标状态幂等与 timeout 后重新探测。
5. 不调用 `--force` 作为普通重启默认路径。
6. 在隔离环境通过回归后才影响 Reference Baseline。

产品自有 cc-connect 的锁定产物隔离安装与回滚已实现；自动 update、跨机 migrate 和外部实例 takeover 仍为 missing，不能通过组合现有脚本假装已产品化。

## Model Configuration 与 Credential 映射

### Reference Baseline 与外部配置的只读包装

- 判断配置文件是否存在、是否可解析、必需字段是否缺失
- 判断 credential reference 或环境注入是否“存在”，不读取/回显真实值
- 调用官方 CLI 的脱敏登录状态检查
- 把当前文件 mtime/hash 映射为初始 revision，用于漂移检测

### 产品自有受管路径与不可接管边界

- Reference Baseline、外部 cc-connect、官方登录配置和 CC Switch 私有数据不写入
- 不读取 Token/API Key/OAuth/Bearer/Session
- 不自动把当前环境文件迁移进新 vault
- 不推断 CC Switch 是否为 Owner；需要专用检测和用户确认

产品自有路径已经实现正式 Owner marker、managed/native 配置分离、原子备份/回滚、Windows CredentialBackend、Telegram Update Lease 与 cc-connect 子进程 Secret 注入。该能力不授权读取旧环境文件中的 Token，也不扩大到 Hermes 模型 Provider、官方登录凭据或 CC Switch。

## Capability Registry 映射

初始 Registry 可从以下只读证据组合：

- multiagent 配置中的 Agent 声明
- relay binding 的 Agent 连接关系
- 当前进程、版本和能力探测
- Reference Baseline 版本矩阵与 Adapter 固定声明

静态配置只说明“预期存在”，进程/健康说明“当前观测”。两者必须分开；配置中出现 Agent 不等于在线。Registry 不把当前固定数量或名称写进通用契约。

## HumanControlPolicy 映射

当前 verified：群聊普通消息静默、直接 @ 指定、Reply + @ 显式目标优先、普通 Reply 指向原 Agent、Bot 来源防环基础规则。

当前 partial：Orchestrator.pause/resume/cancel 在同进程内存对象上改变状态，并在轮次边界检查；多个任务时能要求澄清。

当前 missing：跨进程持久化 receipt、control_sequence、对已发外部调用的强取消、可靠插话应用、ChildTask 改派、Agent 治理隔离与 GUI/Channel 完全统一。

## 第一批只读 Adapter

首个实现阶段可以安全建立：

1. ComponentDiscoveryAdapter：读取公开/已安装版本和存在性，不写系统。
2. RuntimeObservationAdapter：只读进程、端口和健康探针。
3. ConfigurationValidationAdapter：解析脱敏结构并报告缺失/冲突，不保存 Secret。
4. StaticCapabilityAdapter：把冻结能力证据映射到 Registry，并把未验证能力标 experimental/unavailable。
5. SanitizedLogAdapter：读取明确允许的日志源并在边界脱敏；默认不读取聊天正文。

## 后续安全接管顺序

1. 只读发现与状态对照。
2. 在不禁用旧启动链时模拟 lifecycle plan，不执行。
3. 建立回滚点后，以单组件、显式用户操作接管 start/stop/restart。
4. 验证稳定后再迁移启动所有权，防止双重 supervisor。
5. 配置与凭据在独立阶段接管，不能与生命周期首片同时扩大范围。
6. 人类控制只有 Provider 能力和 ack 完整后才从“状态展示”升级为可操作按钮。

## 本轮保护结论

本轮没有修改 `src/`、`integrations/cc-connect/patches/`、Reference Baseline 真实配置、PATH、注册表、计划任务、Watchdog、junction 或外部服务。新增能力只作用于产品自有隔离目录；已执行 Fake Telegram 与合成 Token 验收，没有发送真实消息，真实 Telegram 仍为 `PENDING USER LIVE VALIDATION`。
