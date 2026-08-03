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

当前不具备：真实安装、配置写入、凭据写入、登录、启动或停止接管、更新或回滚执行、Telegram 自动绑定、真实网络健康探测、六链路自动验收、正式 GUI。

三、Telegram 运行证据
--------------------

2026-07-28 的 Reference Baseline 证据确认群聊主要链路和 Hermes 私聊通过。Claude Code 与 Codex 私聊已有基本可用或实际使用证据，但正式完整矩阵仍需补齐。

/start 等命令偶尔可能没有进入预期命令逻辑；普通消息仍可能正常。私聊、群聊、Reply、Mention、Topic 与 Session 之间仍有少量路由和隔离边界，当前未发现阻断性体验 Bug。本阶段没有执行真实 Telegram E2E，也没有发送消息。

四、产品范围
------------

产品已收窄为 Windows 10/11 + Telegram + Hermes/Claude Code/Codex + cc-connect。用户可见三个 Bot，目标验收六条私聊/群聊链路。cc-connect 是 V1 核心桥梁；CC Switch 是推荐但非强制的配置入口；PySide6 是未来 GUI 首选。

五、下一阶段
------------

下一阶段是 cc-connect 单组件真实安装纵向切片，尚未开始实现。详见 05_NEXT_PHASE.md。
