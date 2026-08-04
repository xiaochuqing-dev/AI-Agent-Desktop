01 当前状态
============

更新时间：2026-08-04

一、Reference Baseline
----------------------

Git Tag 为 v0.1-reference-baseline，baseline HEAD 为 cd3493b191fdc19114e0ae037746ab3d23a58a79。公开仓库 src/ 与该 HEAD 对齐，当前运行 cc-connect 为 v1.4.1-patchset0.1-fc315d2，Patch-set 0.1 共 5 个 Patch。

本阶段未修改 src/、dual_agent、integrations/cc-connect/patches/、真实配置、计划任务、Watchdog 或运行中服务。

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
- SecretRef/CredentialBackend 边界；InMemory 仅用于测试，Windows Credential Manager 只有不读写 Secret 的骨架
- 显式 ManagementOwner/LifecycleOwner 交接与 cc-connect start/stop/restart/status/reconcile
- 进程身份、PID 复用、exe SHA256、命令摘要、配置 revision、端口到 PID 所有权和崩溃恢复检查
- cc-connect/Hermes 更新边界与 CC Switch ExternalToolProvider 边界；CC Switch 仅支持可执行文件检测和普通打开

当前不具备：真实凭据写入、其他组件安装或生命周期接管、自动更新、Telegram 自动绑定、六链路自动验收和正式 GUI。锁定版 cc-connect 要求至少一个 Project 和 Platform；Telegram-disabled、无 Secret 最小配置无法满足该运行前提，真实持续运行验收为 PARTIAL，local endpoint 与 deep health 为 unsupported。Windows 10 x64 仍为 pending user real-machine validation。

三、Telegram 运行证据
--------------------

2026-07-28 的 Reference Baseline 证据确认群聊主要链路和 Hermes 私聊通过。Claude Code 与 Codex 私聊已有基本可用或实际使用证据，但正式完整矩阵仍需补齐。

/start 等命令偶尔可能没有进入预期命令逻辑；普通消息仍可能正常。私聊、群聊、Reply、Mention、Topic 与 Session 之间仍有少量路由和隔离边界，当前未发现阻断性体验 Bug。本阶段没有执行真实 Telegram E2E，也没有发送消息。

四、产品范围
------------

产品已收窄为 Windows 10/11 + Telegram + Hermes/Claude Code/Codex + cc-connect。用户可见三个 Bot，目标验收六条私聊/群聊链路。cc-connect 是 V1 核心桥梁；CC Switch 是推荐但非强制的配置入口；PySide6 是未来 GUI 首选。

五、下一阶段
------------

下一阶段是“Telegram 三 Bot 安全绑定、自动身份发现与配置生成切片”。详见 05_NEXT_PHASE.md。
