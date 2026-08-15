AI Agent Desktop
================

面向 Windows 开发者的 Telegram AI 编程团队安装、配置、管理、诊断与恢复中心。

本仓库是当前公开事实源。产品集成 Hermes、Claude Code、Codex、cc-connect、Telegram，并把 CC Switch 作为推荐但非强制的供应商配置入口。核心价值是减少配置和首次使用摩擦，降低失败率，并统一状态、诊断、更新、回滚与恢复；不重复开发成熟上游。

2026-08-15 实施更新
-------------------

本轮从 `1506f8d997b1339665462f87d76aa3476bb97acf` 开始，完成 `0.4.0-prebeta` GUI Product Polish 与 Hermes Telegram Native Onboarding 收口：正式 SVG 图标体系、统一标题栏/设计 Token/卡片对比度、统一对话框、Hermes 官方 `.env` 最小 Telegram 配置事务、Gateway 生命周期、Update Lease 交接、冲突确认与回滚。Agent 检测继续使用各自官方 `--version` 做有界无窗口探测；不读取账号、Provider、模型或私有配置。

本机真实检测为 Hermes 0.19.0、Claude Code 2.1.228、Codex 0.147.0，均为 `LOCAL_VERIFIED`。本地门禁为 264 passed、2 skipped，Ruff、format、CI 范围内 mypy 和全部契约验证通过。Windows 11 x64 candidate 位于 `control-plane/dist/AI-Agent-Desktop-0.4.0-prebeta-windows-x64`，EXE 66.09 MiB、SHA256 `dbebb193cd1ec3779f1dab796f3b075c061f906bfd4b8270e055bf790c7b8910`，manifest SHA256 `f85874a6f0308459660e1e13f688bf46a7455f56a93e840bd70936b2121714c1`，package SHA256 `72f93cdf3ad38db8b41f818dc717826d1939404260e65af9e5d2022c0e60e92f`，validator 与 ordinary-user version/headless smoke 通过。新 GUI Telegram 与 Hermes Native Telegram Setup 均为 `PENDING USER LIVE VALIDATION`，Windows 10 为 `PENDING WINDOWS 10 VALIDATION`；历史 2026-08-07 六链路仅代表旧入口 `LIVE_VERIFIED`。MSI、安装器和签名为 `DEFERRED`。

一、当前状态
------------

- reference baseline v0.1 已冻结，Tag 为 v0.1-reference-baseline。
- 参考实现的 Telegram 群聊主要链路与 Hermes 私聊已经真实验证。
- Control Plane v1 契约与四项 ADR 已冻结，基础运行代码已实现于 control-plane/。
- Control Plane 已实现只读发现、Readiness、Dry-run、持久化 Operation/SSE、脱敏诊断，以及 cc-connect 锁定产物的隔离安装、配置、所有权交接和产品管理生命周期。
- Windows CredentialBackend 已真实落到当前普通用户的 Windows Credential Manager；支持 put、replace、status、resolve_for_operation、delete、元数据列表与 revision，不允许退化到明文文件后端。
- 产品管理状态与锁定版 cc-connect 原生运行配置已分离为 state/managed/cc-connect-state.json 与 state/runtime-config/cc-connect.toml。Renderer 绑定 fc315d2，只输出锁定 Schema 支持的 Project、Agent、Telegram Platform、allow_from/admin_from 和 Secret 环境变量占位符。
- 三个固定 Bot slot、getMe 身份验证、Webhook 检查、Update Lease、一次性绑定码、防重放、User ID/Group ID 自动发现和三 Bot 3/3 一致性已实现并通过 Fake Telegram 合成验收。
- 合法 Claude/Codex Project 的真实 cc-connect 进程已在 Windows 11 普通用户、非系统盘、中文空格括号路径下通过持续运行、stop、restart、Control Plane 重启 reconcile、PID/exe SHA/config revision/端口所有权和 Bearer management API 验收。
- 六链路可观测性、消息关联、Session 隔离探针、显式一次性 E2E 计划、代理策略、脱敏用户验收向导和 Windows x64 候选包已实现。
- Agent Detection 已接入 Onboarding、Dashboard、Diagnostics 和全局刷新；Bot Identity 不再冒充 Agent installed/connected。Claude/Codex 只有 Agent acceptable 且严格 Runtime Ready 才显示 connected；Hermes Telegram readiness 单独显示，不把 Agent installed 误报为 Provider authenticated。
- Step 4 会真实启动/协调 cc-connect，并核验 PID、exe、配置 revision、端口所有权和启动稳定性；Binding 完成不再等同 Chat Live Health，真实 6 条消息必须由用户明确确认且不会自动重试。
- 2026-08-07，用户直接在 Telegram 完成 Hermes、Claude Code、Codex 的私聊与群聊六链路验收，并明确确认无问题、可以通过；六条用户体验链路均记为 LIVE_VERIFIED。
- 本轮真实验收绕过向导，未生成三次 getMe、3/3 绑定和六条 correlation 的 Control Plane 持久化证据，不能把用户确认改写为不存在的结构化记录。
- 整体仍为 PARTIAL：Windows 10 为 PENDING WINDOWS 10 VALIDATION；当前实机为 Windows 11；上游 management API 只能监听所有网卡、原生 Group Chat 过滤和 deep health 为 unsupported。
- Hermes 已安装但 Telegram 未配置时，Control Plane 仅通过 Hermes 官方公开 `.env` 和 Gateway CLI 完成最小 Telegram 接入；已有 Hermes 配置 external-first，必须显式确认冲突，Provider、Model、Tool 与其它 Hermes 配置仍由外部管理。
- 旧 stage-a 候选包仍是 Tk/Windows 验收向导；当前工作区的正式 GUI 最小切片已使用 PySide6 + Qt Widgets + QSS。新 GUI candidate 已完成 Windows 11 本地构建验证，但用户 live 与 Windows 10 尚未完成，不能标为发布完成。
- Step 4 与 Dashboard 已在原生 Windows Qt 1280×720 下复核，无文字重叠和关键按钮越界。

二、首发产品范围
----------------

首发平台为 Windows 10/11，首发渠道仅为 Telegram，用户可见三个 Bot：Hermes Bot、Claude Code Bot、Codex Bot。

目标验收六条链路：Hermes 私聊、Hermes 群聊、Claude Code 私聊、Claude Code 群聊、Codex 私聊、Codex 群聊。当前已交付安全凭据、身份发现、三 Bot 绑定、Claude/Codex 原生配置生成、六链路可观测性和候选包；六条真实用户体验链路已由用户逐条验证通过。产品内置 E2E 仍坚持逐条显式确认、每次最多一条且失败不自动重试。

三、集成优先
------------

本产品不重写 Hermes、Claude Code、Codex 或 cc-connect，不自研替代 cc-connect 的通用 Telegram Bridge，也不重复开发完整 Provider 管理器。GUI 未来只调用 Control Plane 契约；每个配置作用域同一时刻只有一个 ManagementOwner。

四、快速阅读
------------

1. 00_START_HERE.md
2. 01_CURRENT_STATE.md
3. 02_PRODUCT_VISION.md
4. 03_LATEST_PRODUCT_DECISIONS.md
5. product/TELEGRAM_AI_CODING_TEAM_SCOPE.md
6. product/INTEGRATION_FIRST_POLICY.md
7. product/TELEGRAM_KNOWN_LIMITATIONS.md
8. reference-baseline/SOURCE_OF_TRUTH.md
9. architecture/control-plane-v1/README.md
10. contracts/control-plane-v1/
11. reports/TELEGRAM_THREE_BOT_SECURE_BINDING_AND_NATIVE_CONFIG_GENERATION_REPORT.md
12. reports/SIX_LINK_OBSERVABILITY_LIVE_E2E_AND_USER_VALIDATION_REPORT.md
13. 05_NEXT_PHASE.md
14. next-agent/NEXT_AGENT_PROMPT.txt
15. reports/MINIMAL_GUI_ONBOARDING_AND_WINDOWS_DISTRIBUTION_REPORT.md
16. reports/GUI_PRE_BETA_AGENT_RUNTIME_AND_LIVE_CLOSURE_REPORT.md

五、目录结构
------------

src/ 保存当前参考实现源码；integrations/cc-connect/ 保存 cc-connect Patch 与构建证据；control-plane/ 保存 Local Control Plane；product/、architecture/、contracts/、reference-baseline/ 和 reports/ 分别保存产品、设计、机器契约、运行事实与阶段报告。

六、安全
--------

仓库不保存真实 Token、API Key、密码、Transcript、个人聊天内容或私有运行配置。Bot Token 仅由 Windows Credential Manager 保存，原生 TOML 只包含环境变量占位符；Control Plane API、Diagnostic、Operation、SSE、SQLite 和日志均不回显 Secret。详见 SECURITY_REVIEW.md。
