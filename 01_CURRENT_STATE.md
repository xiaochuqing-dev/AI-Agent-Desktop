01 当前状态
============

更新时间：2026-08-05

一、Reference Baseline
----------------------

Git Tag 为 v0.1-reference-baseline，baseline HEAD 为 cd3493b191fdc19114e0ae037746ab3d23a58a79。公开仓库 src/ 与该 HEAD 对齐，当前运行 cc-connect 为 v1.4.1-patchset0.1-fc315d2，Patch-set 0.1 共 5 个 Patch。

本阶段未修改 src/、dual_agent、integrations/cc-connect/patches/、真实配置、计划任务、Watchdog、PATH、注册表或外部运行中服务。

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

当前不具备：其他组件安装或生命周期接管、自动更新、真实 Telegram live 绑定、六链路真实消息 E2E 和正式 GUI。合成验收已证明合法 Project 的 cc-connect 可持续运行，但整体仍为 PARTIAL：Telegram 为 PENDING USER LIVE VALIDATION，Windows 10 为 PENDING WINDOWS 10 VALIDATION，Hermes 为 pending_component_install，锁定上游原生 Group Chat 过滤和 deep health 为 unsupported，management API 监听范围受上游限制为所有网卡。

三、Telegram 运行证据
--------------------

2026-07-28 的 Reference Baseline 证据确认群聊主要链路和 Hermes 私聊通过。Claude Code 与 Codex 私聊已有基本可用或实际使用证据，但正式完整矩阵仍需补齐。

/start 等命令偶尔可能没有进入预期命令逻辑；普通消息仍可能正常。私聊、群聊、Reply、Mention、Topic 与 Session 之间仍有少量路由和隔离边界，当前未发现阻断性体验 Bug。本阶段没有使用真实 Token、没有执行真实 Telegram E2E，也没有发送消息。Fake Telegram 验收已完成三次 getMe、三个私聊绑定、三个同群绑定、同一 User/Group 和 3/3 completed；该结果不能替代真实 Telegram 验证。

四、产品范围
------------

产品已收窄为 Windows 10/11 + Telegram + Hermes/Claude Code/Codex + cc-connect。用户可见三个 Bot，目标验收六条私聊/群聊链路。cc-connect 是 V1 核心桥梁；CC Switch 是推荐但非强制的配置入口；PySide6 是未来 GUI 首选。

五、下一阶段
------------

下一阶段是“六链路可观测性、真实消息 E2E 与会话隔离修复切片”。进入前先完成用户显式 live 绑定与 Windows 10 实机门禁。详见 05_NEXT_PHASE.md。
