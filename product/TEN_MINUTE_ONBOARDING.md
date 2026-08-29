十分钟安装引导 TEN_MINUTE_ONBOARDING
====================================

本文档描述正式产品目标和 2026-08-13 的 Pre-Beta 实现。三 Bot 绑定、真实 Agent Detection、严格 Runtime Readiness 与 PySide6 GUI 已接线；新 GUI Telegram 和 Windows 10 仍待用户验证。

一、用户准备
------------

用户准备受支持的 Windows 10/11、模型账号或 API 凭据，创建 Hermes Bot、Claude Code Bot、Codex Bot 并粘贴三个 Token，创建群聊并加入三个 Bot，完成 Telegram 官方必须由用户执行的首次 /start 与必要权限设置。

用户不手工填写 User ID、Group/Chat ID，不编辑 Hermes 或 cc-connect 配置，不处理端口、Hook、Session、计划任务或 Secret 注入。

二、目标流程
------------

当前最小 GUI 使用一个欢迎页和固定四步 Shell：

1. 录入 Hermes、Claude Code、Codex 三个 Bot Token；真实模式写入 Windows Credential Manager，并复用 Control Plane getMe 验证 Bot 身份。
2. 为三个 Bot 生成短时私聊 deep link，用户通过桌面 Telegram 或手机 QR 打开私聊并点击 Start；GUI 轮询 Control Plane 绑定状态，不要求用户输入 User ID。
3. 用户创建或打开一个群并把三个 Bot 加入同一个群；GUI 使用 Telegram group deep link/startgroup 辅助打开，并通过 Binding API 检测三 Bot 是否进入同一群，不要求 Group ID，也不读取群列表。
4. GUI 检测三个 Agent、启动并严格核验 cc-connect、生成配置，再显示 Binding 与 Chat Health；真实六链路测试需要用户明确确认，每条最多一条且不自动重试，也可跳过。

完整产品目标仍包括组件安装、官方登录、配置所有权、Hermes/cc-connect 候选配置、运行环境准备和六链路证据展示；当前最小 GUI 尚未完成所有这些自动化。

三、六条目标链路
----------------

Hermes 私聊、Hermes 群聊、Claude Code 私聊、Claude Code 群聊、Codex 私聊、Codex 群聊必须独立验收。Bot 连接、普通消息、命令、Mention、Reply、Topic 和 Session 隔离也必须分开记录，不能相互推断。

四、Operation 与安全
--------------------

每个外部变更使用可审计 Operation、Idempotency-Key 和恢复点。Secret 不进入日志、URL、Diagnostic 或普通配置。任何真实消息测试必须由用户明确确认目标会话，超时不自动重复发送。

五、当前阶段
------------

当前已实现只读发现、Readiness、Dry-run、Operation/SSE、Windows Credential Manager、三 Bot 身份与绑定、三个真实 Agent Detector、Claude/Codex 原生配置、Hermes Telegram Native Configuration、严格 cc-connect Runtime Ready、Live E2E GUI、SVG IconRegistry、Design Tokens、统一对话框和 PySide6 GUI。当前工作区 pytest 为 269 passed、2 skipped；Ruff、format、`mypy control_plane` 112 files、契约、cc-connect v1.5.0 门禁和 `0.4.1-prebeta` candidate validator 通过。

这些自动化结果只证明代码与合成合同。新 GUI 私聊激活、群自动检测和 Hermes Native Telegram Setup 为 `PENDING USER LIVE VALIDATION`；Windows 10 为 `PENDING WINDOWS 10 VALIDATION`；MSI/正式安装器/代码签名为 `DEFERRED`。Hermes 已有配置保持 external-first；仅已安装且 Telegram 未配置或用户明确确认切换时，Adapter 才通过官方 `.env` 与 Gateway CLI 完成最小 Telegram 接入。Provider、Model、Tool 与其它 Hermes 配置仍由 Hermes/外部工具管理。历史 2026-08-07 六链路直接 Telegram 用户确认不覆盖新 GUI。

六、恢复与预览模式
------------------

GUI 启动后从 Control Plane 快照恢复步骤，不把纯 GUI 内存 bool 当作事实源。默认正式模式使用 Embedded Control Plane；已有 loopback API Token 与地址时使用 HTTP/Bearer 客户端。只有显式 `--demo` 才进入带明显“预览模式”标识的合成客户端；Demo 只用于截图和控件测试，不写入真实 Token，也不构成 live 验收。Control Plane 不可达时，正式连接模式返回用户可理解的错误和重试入口。
