01 当前状态
============

更新时间：2026-08-13

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
- PySide6 GUI 已实现于 `control-plane/control_plane/gui/`：统一标题栏和 StepRail、Welcome、四步 Onboarding、二维码弹窗、Dashboard、Diagnostics、Demo 合成客户端以及 HTTP/Embedded Control Plane 客户端。
- GUI 当前版本为 `0.3.0-prebeta`。Agent Detection 由 `control_plane/agent_detection/` 实现，Hermes、Claude Code、Codex 使用独立规则、共享安全 Windows discovery/version probe，并接入 Onboarding、Dashboard、Diagnostics 和全局刷新。
- 本机真实检测为 Hermes 0.19.0、Claude Code 2.1.228、Codex 0.147.0，状态均 healthy；这是 `LOCAL_VERIFIED`，不等于认证或聊天 live。
- Step 4 会确保 cc-connect 安装、Owner、原生配置、start/reconcile，并严格核验 PID、exe、configuration revision、port ownership、startup stability 和 fatal log；未 ready 不得完成 Onboarding。
- Telegram Binding、Chat Live Health 与历史 evidence revision 已分离。GUI Live E2E 需要用户确认六条消息，每条最多一次、失败不自动重试；可跳过并从 Dashboard 后续执行。
- GUI 只调用 onboarding/dashboard snapshot、Telegram credential/verify/binding/poll 等本地 API；Token 不由 GUI 状态快照保存，二维码只承载短时 deep-link binding payload。
- 新 GUI 私聊激活与群自动检测的真实用户复测为 `PENDING USER LIVE VALIDATION`；GUI 单元/合成测试通过不等于 Telegram live 通过。

当前不具备：其他组件安装或生命周期接管、自动更新、正式 Installer、代码签名。最终 candidate 位于 `control-plane/dist/AI-Agent-Desktop-0.3.0-prebeta-windows-x64-final3-20260813`，Windows 11 x64 validator 与 ordinary-user version/headless smoke 通过；EXE 66.05 MiB，SHA256 `7b2a2370f17eb0d1ff181d8fbf6fa36a221672a3bc9525f4c3fca74aa2186223`。本地质量门禁为 240 passed、1 skipped，Ruff、format、mypy 104 files 和契约验证通过。Windows 10 仍为 `PENDING WINDOWS 10 VALIDATION`。

三、Telegram 运行证据
--------------------

2026-08-07 的用户现场验收确认 Hermes、Claude Code、Codex 的私聊与群聊六条链路均正常，无串线或阻断问题，用户明确表示可以通过。Hermes gateway 日志仅作为辅助元数据证据，记录到 Claude/Codex 的私聊或群聊收发事件以及 Hermes 私聊/群聊活动；报告不复制 Token 或消息正文。

该轮验证由用户直接在 Telegram 操作，未通过候选向导，所以六链路用户体验可记为 LIVE_VERIFIED，但不能虚构向导 getMe、3/3 bound、plan/run、correlation_id 或完整 response message_id。Fake Telegram 验收仍独立证明三次 getMe、三个私聊绑定、三个同群绑定、同一 User/Group 和 3/3 completed；合成证据与用户现场证据保持分开。

四、产品范围
------------

产品已收窄为 Windows 10/11 + Telegram + Hermes/Claude Code/Codex + cc-connect。用户可见三个 Bot，目标验收六条私聊/群聊链路。cc-connect 是 V1 核心桥梁；CC Switch 是推荐但非强制的配置入口；PySide6 是当前 GUI 实现技术。新 GUI 的真实私聊/群自动检测仍为 `PENDING USER LIVE VALIDATION`。

五、下一阶段
------------

下一阶段收口门禁为：用最终 `0.3.0-prebeta` candidate 完成新 GUI 三 Bot私聊/同群/可选六链路用户现场验证，再在 Windows 10 x64 普通用户实机重复；之后才进入 Installer、卸载、快捷方式、Release Asset 与签名准备。详见 `reports/GUI_PRE_BETA_AGENT_RUNTIME_AND_LIVE_CLOSURE_REPORT.md`。
