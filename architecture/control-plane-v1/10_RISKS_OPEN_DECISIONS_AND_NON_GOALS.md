# 10 风险、开放决策与非目标

## 使用规则

“已冻结”表示下一阶段可以直接依赖其语义；“开放”表示实现方式仍需 Architecture Decision Record，但不得改变已冻结 API、状态、安全和替换边界。ADR-001..004 已解决语言框架、事务存储、当前后台宿主和凭据边界。cc-connect 隔离安装、原生配置、产品自有生命周期、固定 Telegram Credential 与最小 PySide6 GUI 客户端已落地；新 GUI live、外部接管和 Windows 10 仍受后续门禁约束。

## 已冻结、不再重复讨论

- GUI 与 Control Plane 独立进程，GUI 只依赖稳定本地 API，退出 GUI 不停止后台。
- v1 默认是 `127.0.0.1` HTTP/JSON + SSE；WebSocket 不进入 v1，IPC 只能做等价传输。
- Provider 使用显式能力和版本协商；未知能力不能静默降级。
- 长操作使用 Operation；幂等 key、revision 和取消确认语义是强制约束。
- 通用 Channel 模型不包含平台专属字段；具体映射只在 Adapter。
- 一个配置 scope 只有一个 ManagementOwner；Secret 与业务配置分离。
- 人类控制优先，但上游不支持的强暂停或强取消不能伪造。
- Hermes 是编排中枢，cc-connect 是 V1 固定核心桥梁，Claude Code/Codex 为一等 Agent。
- v1 不创建新 Runtime、消息总线、DAG 或第三方插件市场。

## 风险登记表

| 风险 | 可能性/影响 | 早期信号 | 缓解与失败策略 | 决策门禁 |
|---|---|---|---|---|
| 双重生命周期所有权导致重复进程或互相拉起 | 中/高 | 同一组件出现多个 supervisor、PID 快速变化 | shadow plan；识别启动所有者；逐组件交接；保留旧定义但禁用其写权 | 首次 controlled takeover 前 |
| 非结构化 CLI/脚本输出变化造成错误状态 | 高/中 | 新版本解析失败、状态频繁 unknown | 版本锁、结构化探针优先、解析器契约测试；失败转 unknown 而非猜测 | 每个 Adapter 合入前 |
| Control Plane 崩溃时外部副作用状态不明 | 中/高 | Operation 长期 running、重启后无 ack | 持久化阶段 journal；重启后探测；禁止自动重放未知副作用 | 首片 Operation Store 评审 |
| 本地 API 被浏览器或同机恶意进程滥用 | 中/高 | 异常 Origin、Host 或 token 使用 | loopback、Bearer、ACL 服务发现、Host/Origin 校验、轮换、限流；危险操作再次确认 | API Host 安全测试前 |
| Secret 通过日志、异常或 Adapter 子进程泄露 | 中/高 | 扫描命中敏感字段、命令行出现值 | allowlist 结构化日志、禁止 query/argv Secret、受限 lease、自动扫描；后端失败不退化明文 | CredentialProvider 上线前 |
| 配置 Owner 漂移或双写破坏有效配置 | 中/高 | hash/revision 无授权变化、多个 Owner 标记 | 两阶段交接、原子替换、备份、漂移 Condition；冲突时停止写入 | 首次配置写入前 |
| Adapter 能力过度声明导致 GUI 给出无效按钮 | 中/中 | 请求持续返回 unsupported、取消无法确认 | capability 逐项声明、证据等级、契约测试；实验能力不进入必需路径 | 每次 Registry 快照评审 |
| 状态聚合隐藏部分故障或旧观测 | 中/中 | GUI 绿色但 Condition 过期/异常 | 正交状态、observed_generation、资源版本与 overlay；unknown 不视为正常 | GUI 状态验收前 |
| SSE 丢游标或重复事件导致界面倒退 | 中/中 | sequence 缺口、重复通知、旧状态覆盖新状态 | at-least-once 去重、epoch/sequence/resourceversion、410 后重取快照 | 事件契约测试前 |
| 日志统一采集无意收集聊天正文或 PII | 中/高 | Diagnostic 出现内容片段或私有路径 | 日志源 allowlist、正文默认禁采、字段级脱敏、导出前二次扫描 | SanitizedLogAdapter 合入前 |
| 上游升级使 Patch 或 Adapter 映射失效 | 高/中 | Patch 校验失败、能力探针变化 | 继续锁定已知版本；升级单独评审；保留回滚点和冻结回归 | 每次上游升级前 |
| 强取消在外部 Runtime 中不可实现 | 高/中 | cancel_requested 后仍收到正式输出 | 声明 none/checkpoint/best_effort；区分接受与确认；保留部分结果 | 人类控制实现前 |
| Windows 提权 helper 扩大攻击面 | 中/高 | helper 接收任意路径/命令或继承 Secret | 固定动作 allowlist、短生命期、签名请求、最小权限；与主进程分离 | 安装器/系统写入前 |
| 新手十分钟路径受网络和官方登录波动影响 | 高/中 | 步骤超时、重复输入、丢失进度 | 断点 journal、独立 timeout、可跳过非核心项、明确恢复动作 | 安装引导验收前 |
| 私有 Reference Baseline SHA 与公开仓库历史被误当冲突 | 中/中 | Agent 试图从公开远端找私有 tag/object | 明确两套历史关系；公开仓库以当前 Git 和文档为事实源，不覆盖 `src/` | 每次交接阅读时 |
| 锁定版 cc-connect management API 暴露到所有网卡 | 中/高 | 端口在非 loopback 地址监听 | 随机高熵 Bearer、受控端口、本机防火墙、健康标 partial；升级前不伪报 loopback-only | 上游 Renderer 升级评审 |
| 原生 Telegram Schema 无 Group Chat 白名单 | 中/中 | operator 可在其他群触发 Bot | 只允许绑定 operator、公开 unsupported、六链路验收限定目标群；不增加私有 Patch | 真实消息 E2E 前 |
| 合成 3/3 被误当真实 Telegram 已通过 | 中/高 | 报告缺少真实 getMe/Update 时间与证据 | 强制 PENDING USER LIVE VALIDATION，真实操作只能用户显式启动 | 下一阶段进入门禁 |
| Demo GUI 自动进度被误当真实 Onboarding 完成 | 中/高 | 预览模式显示 bound/ready 但没有用户操作 | 标题栏显示预览模式；报告区分 Demo、Fake 与用户 live；新 GUI 固定 PENDING USER LIVE VALIDATION | 新 GUI 用户验收前 |

## 实现前开放决策

### Control Plane 实现语言与框架

选项：Python 异步 Web 框架、.NET、Rust 或其他成熟本地服务栈。推荐按“Windows 后台可靠性、OpenAPI/SSE 支持、进程管理、安全存储集成、打包体积、团队维护能力”做一个限时原型比较，不因 GUI 使用 PySide6 就默认绑定 Python。

必须在首片编码前形成 ADR。无论选择什么，GUI API、Provider 契约和 JSON Schema 不变。

### 元数据与 Operation 存储

选项：SQLite 事务存储或同等单用户嵌入式数据库。推荐 SQLite WAL + 明确 migration，因为需要 revision、幂等记录、Operation journal 和原子事件 outbox；不引入外部数据库或分布式一致性。

需要验证进程崩溃恢复、备份一致性、文件 ACL 与迁移。不把当前 `multiagent.db` 直接复用为 Control Plane 数据库。

### Windows 后台宿主与启动所有权

选项：登录启动项、计划任务、用户级服务宿主。推荐先以最小权限、当前用户可观察和可回滚为评价标准做隔离测试；没有完成进程身份和所有权协议前，不接管现有 Watchdog/计划任务。

选择必须保证 GUI 退出不停止后台，并定义升级时的进程排空和恢复。

### CredentialBackend 组合

小型固定 Bot/内部 Token 已选用 Windows Credential Manager，并在普通用户下实测 keyring WinVault 后端。DPAPI 当前用户范围 vault 只保留给未来结构化大凭据；没有需求和迁移设计前不引入。

后端不可用时必须报错，不允许回退明文。此决策不改变 `credential_ref` 或 CredentialProvider 操作。

### 端口与服务发现

端口可使用安装时随机高位端口或保留端口；推荐由受 ACL 保护的服务发现记录公布实际 endpoint 和 instance epoch，并在冲突时安全换端口。具体默认值未冻结，不能硬编码进 GUI。

需验证端口抢占、Host header、IPv4/IPv6、token 轮换和多实例冲突。v1 冻结只绑定 loopback，不开放局域网远程管理。

### 事件与幂等记录保留期

具体窗口未冻结。推荐以“GUI 常见离线时长、磁盘上限、诊断需要”为输入，分别给事件、Operation、幂等 key 和 tombstone 设置上限；过期行为已经冻结为快照恢复或明确冲突，不能静默丢失。

### Adapter 隔离级别

首片可先使用同进程内置 Adapter，但每个调用必须有 timeout、取消边界和故障捕获。只有出现不可接受的崩溃、依赖冲突或权限隔离需求，才评估进程外 Adapter；不提前设计通用插件协议。

### 脱敏日志字段与诊断包格式

冻结原则是 allowlist、默认不采聊天正文、Secret 永不出现。具体允许字段、保留周期、最大尺寸和诊断包格式必须在实现时接受安全测试；原始日志不可因“高级模式”绕过脱敏。

## 可以延后但必须保留兼容边界

- named pipe 等等价本地传输
- 其他组件安装、自动更新、签名分发与跨机迁移
- 其他组件的 ManagementOwner 写入接管和凭据迁移
- 完整人类插话、暂停、取消、改派与 Agent 隔离
- 讨论模式产品化
- 新 Channel 与附件能力
- Provider 进程外隔离或第三方扩展
- 完整 PySide6 GUI 的视觉收口、Windows candidate、MSI 和签名体验

延后表示当前 Capability 为 unavailable/experimental，不表示删除 API 资源或改用私有临时接口。

## 明确非目标

- 不把 Control Plane 变成推理 Agent、编排大脑、工作流语言或通用 DAG。
- 不重写 Hermes、Claude Code、Codex、cc-connect 或它们的官方登录系统。
- 不建立第二套消息总线、Transcript 数据库或跨机器控制服务。
- 不把 cc-connect、dual_agent 或当前五个 Patch 变成永久核心依赖。
- 不让 GUI、测试客户端或未来 Channel 绕过 Control Plane 读写上游私有文件。
- 不为通用模型增加 Telegram 或其他平台专属“可选扩展字段”。
- 不承诺瞬时强取消、零停机升级、跨平台首发或无人确认的高风险自动修复。
- 不在当前阶段实现完整发布级 GUI、MSI/签名、新 Channel、新 Runtime、复杂讨论、通用配置平台或通用凭据平台；最小 PySide6 GUI 壳已实现但仍待真实验收。

## 需要正式评审确认的优先事项

下一阶段优先完成用户显式真实三 Bot 绑定、Windows 10 实机门禁和六链路脱敏可观测性；随后才执行真实消息 E2E 与 Session 隔离修复。其余开放参数必须通过 ADR 或实现证据记录，并保持冻结契约兼容。
