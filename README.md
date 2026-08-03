AI Agent Desktop
================

面向 Windows 开发者的 Telegram AI 编程团队安装、配置、管理、诊断与恢复中心。

本仓库是当前公开事实源。产品集成 Hermes、Claude Code、Codex、cc-connect、Telegram，并把 CC Switch 作为推荐但非强制的供应商配置入口。核心价值是减少配置和首次使用摩擦，降低失败率，并统一状态、诊断、更新、回滚与恢复；不重复开发成熟上游。

一、当前状态
------------

- reference baseline v0.1 已冻结，Tag 为 v0.1-reference-baseline。
- 参考实现的 Telegram 群聊主要链路与 Hermes 私聊已经真实验证。
- Control Plane v1 契约与四项 ADR 已冻结，基础运行代码已实现于 control-plane/。
- 当前 Control Plane 能力仅包括只读发现、Readiness、Dry-run、Operation/SSE 和无副作用脱敏诊断。
- 真实安装、配置写入、凭据写入、启停接管、Telegram 自动绑定、六链路自动验收和正式 GUI 尚未实现。
- 正式 GUI 未来首选 PySide6 + Qt Widgets + QSS，本阶段没有实现 GUI。

二、首发产品范围
----------------

首发平台为 Windows 10/11，首发渠道仅为 Telegram，用户可见三个 Bot：Hermes Bot、Claude Code Bot、Codex Bot。

目标验收六条链路：Hermes 私聊、Hermes 群聊、Claude Code 私聊、Claude Code 群聊、Codex 私聊、Codex 群聊。上述自动配置与六链路自动检测是产品目标，不是当前已交付能力。

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
11. 05_NEXT_PHASE.md
12. next-agent/NEXT_AGENT_PROMPT.txt

五、目录结构
------------

src/ 保存当前参考实现源码；integrations/cc-connect/ 保存 cc-connect Patch 与构建证据；control-plane/ 保存 Local Control Plane；product/、architecture/、contracts/、reference-baseline/ 和 reports/ 分别保存产品、设计、机器契约、运行事实与阶段报告。

六、安全
--------

仓库不保存真实 Token、API Key、密码、Transcript、个人聊天内容或私有运行配置。Control Plane 默认 loopback + Bearer，并在 API、Diagnostic 和 ReadinessReport 输出前脱敏。详见 SECURITY_REVIEW.md。
