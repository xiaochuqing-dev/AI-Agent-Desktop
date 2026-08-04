AI Agent Desktop
================

面向 Windows 开发者的 Telegram AI 编程团队安装、配置、管理、诊断与恢复中心。

本仓库是当前公开事实源。产品集成 Hermes、Claude Code、Codex、cc-connect、Telegram，并把 CC Switch 作为推荐但非强制的供应商配置入口。核心价值是减少配置和首次使用摩擦，降低失败率，并统一状态、诊断、更新、回滚与恢复；不重复开发成熟上游。

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
- 整体状态仍为 PARTIAL：未使用真实 Telegram Token，live 身份与绑定为 PENDING USER LIVE VALIDATION；Windows 10 为 PENDING WINDOWS 10 VALIDATION；Hermes 为 pending_component_install；上游 management API 只能监听所有网卡、原生 Group Chat 过滤和 deep health 为 unsupported。
- 六链路真实消息 E2E 与正式 GUI 尚未实现。
- 正式 GUI 未来首选 PySide6 + Qt Widgets + QSS，本阶段没有实现 GUI。

二、首发产品范围
----------------

首发平台为 Windows 10/11，首发渠道仅为 Telegram，用户可见三个 Bot：Hermes Bot、Claude Code Bot、Codex Bot。

目标验收六条链路：Hermes 私聊、Hermes 群聊、Claude Code 私聊、Claude Code 群聊、Codex 私聊、Codex 群聊。当前已交付安全凭据、身份发现、三 Bot 绑定和 Claude/Codex 原生配置生成，但尚未执行六链路真实消息 E2E。

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
12. 05_NEXT_PHASE.md
13. next-agent/NEXT_AGENT_PROMPT.txt

五、目录结构
------------

src/ 保存当前参考实现源码；integrations/cc-connect/ 保存 cc-connect Patch 与构建证据；control-plane/ 保存 Local Control Plane；product/、architecture/、contracts/、reference-baseline/ 和 reports/ 分别保存产品、设计、机器契约、运行事实与阶段报告。

六、安全
--------

仓库不保存真实 Token、API Key、密码、Transcript、个人聊天内容或私有运行配置。Bot Token 仅由 Windows Credential Manager 保存，原生 TOML 只包含环境变量占位符；Control Plane API、Diagnostic、Operation、SSE、SQLite 和日志均不回显 Secret。详见 SECURITY_REVIEW.md。
