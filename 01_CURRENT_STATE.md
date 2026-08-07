01 当前状态
============

更新时间：2026-08-07

一、Reference Baseline
----------------------

Git Tag 为 v0.1-reference-baseline，baseline HEAD 为 cd3493b191fdc19114e0ae037746ab3d23a58a79。公开仓库 src/ 与该 HEAD 对齐，当前运行 cc-connect 为 v1.4.1-patchset0.1-fc315d2，Patch-set 0.1 共 5 个 Patch。

本阶段未修改 src/、dual_agent、integrations/cc-connect/patches/、真实 Bot/Provider 配置、计划任务定义、PATH、注册表或 Reference Baseline。针对用户反馈的 Hermes 黑窗口，仅在本机外部运行层调整了启动 VBS、Watchdog VBS、Python startup hook 和 env_probe 子进程无窗口标志，并保留独立备份；该修复不属于本仓库源码，也未改变产品方向。

二、Control Plane
----------------

Control Plane v1 机器契约和 ADR-001..004 已冻结。基础运行代码已经实现于 control-plane/，包括 domain、application、api、persistence、security 和 adapters。

当前实现能力：

- loopback + Bearer 本地服务
- 只读组件发现与正交状态
- ReadinessReport 与结构化 Diagnostic
- DryRunPlan，不执行任何写入
- Operation、幂等、基础重启恢复和 SSE 事件
- Windows System、Hermes、cc-connect、Claude Code、Codex、CC Switch、Telegram Config 共 7 个只读 Adapter
- 全链路脱敏与源码 Secret 扫描
- cc-connect Windows amd64 锁定、可重复构建产物与机器可读 Manifest
- 绑定计划摘要的显式确认、隔离安装、原子 current.json、自动回滚、卸载、恢复和 pending_cleanup
- Alembic 基线与安装状态迁移、持久化安装审计事件和跨重启恢复
- 有界持久化 OperationExecutor，含组件互斥、幂等、取消、关机等待和现场探测恢复
- 不可变配置计划、显式确认、产品自有最小配置、revision、备份、原子替换、手工漂移检测和回滚
- Windows Credential Manager 真实 CredentialBackend；InMemory 仅用于测试，原生后端不允许明文文件回退
- 显式 ManagementOwner/LifecycleOwner 交接与 cc-connect start/stop/restart/status/reconcile
- 进程身份、PID 复用、exe SHA256、命令摘要、配置 revision、端口到 PID 所有权和崩溃恢复检查
- cc-connect/Hermes 更新边界与 CC Switch ExternalToolProvider 边界；CC Switch 仅支持可执行文件检测和普通打开
- managed state 与 cc-connect 原生配置分离；Renderer 固定绑定 fc315d2，并验证环境变量占位符、Project/Agent/Platform Schema
- Hermes、Claude、Codex 三个固定 Bot 凭据引用，getMe 唯一身份、Webhook 显式处理和脱敏 Telegram Client
- Telegram Update Lease、一次性 HMAC 绑定码、offset 单调前进、防旧 Update/重放/抢绑定/跨群冲突，以及同一 User/Group 的 3/3 绑定状态
- Claude Code/Codex 两个原生 Project 的计划、revision、备份、原子写入、漂移检测、回滚和 Agent 可执行入口预检
- external cc-connect 状态拆分；PATH 仅安装不阻塞，目标端口、相同配置作用域或 Supervisor 冲突才硬阻塞
- Hermes 未安装时准确返回 pending_component_install，不阻塞 Claude/Codex

当前不具备：其他组件安装或生命周期接管、自动更新和正式产品 GUI。六链路可观测性、合成 E2E、显式一次性计划、消息关联、Session 隔离探针、代理策略、脱敏验收向导和 Windows x64 候选包已实现。2026-08-07 用户直接在 Telegram 完成六条真实消息链路并明确通过；本轮没有经过向导，因此 Control Plane 的三次 getMe、3/3 绑定和 correlation live 记录仍未补齐。Windows 10 为 PENDING WINDOWS 10 VALIDATION；当前机器上的 Hermes 作为 observed external runtime，锁定上游原生 Group Chat 过滤和 deep health 为 unsupported，management API 监听范围受上游限制为所有网卡。

三、Telegram 运行证据
--------------------

2026-08-07 的用户现场验收确认 Hermes、Claude Code、Codex 的私聊与群聊六条链路均正常，无串线或阻断问题，用户明确表示可以通过。Hermes gateway 日志仅作为辅助元数据证据，记录到 Claude/Codex 的私聊或群聊收发事件以及 Hermes 私聊/群聊活动；报告不复制 Token 或消息正文。

该轮验证由用户直接在 Telegram 操作，未通过候选向导，所以六链路用户体验可记为 LIVE_VERIFIED，但不能虚构向导 getMe、3/3 bound、plan/run、correlation_id 或完整 response message_id。Fake Telegram 验收仍独立证明三次 getMe、三个私聊绑定、三个同群绑定、同一 User/Group 和 3/3 completed；合成证据与用户现场证据保持分开。

四、产品范围
------------

产品已收窄为 Windows 10/11 + Telegram + Hermes/Claude Code/Codex + cc-connect。用户可见三个 Bot，目标验收六条私聊/群聊链路。cc-connect 是 V1 核心桥梁；CC Switch 是推荐但非强制的配置入口；PySide6 是未来 GUI 首选。

五、下一阶段
------------

下一阶段是“最小 GUI、十分钟 Onboarding 与 Windows 自包含分发切片”。发布门禁仍需 Windows 10 x64 普通用户实机；如要补齐机器可审计的 live 证据，需另行通过向导完成真实 getMe、3/3 绑定和 correlation 流程。详见 reports/SIX_LINK_OBSERVABILITY_LIVE_E2E_AND_USER_VALIDATION_REPORT.md。
