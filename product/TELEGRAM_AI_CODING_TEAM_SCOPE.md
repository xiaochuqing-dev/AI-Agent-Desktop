Telegram AI 编程团队范围
========================

一、定位
------

面向 Windows 开发者的 Telegram AI 编程团队安装、配置、管理、诊断与恢复中心。

二、固定首发范围
----------------

Windows 10/11、Telegram、Hermes、Claude Code、Codex、cc-connect，以及推荐但非强制的 CC Switch。当前最小 GUI 使用 PySide6 + Qt Widgets + QSS；完整发布和 Windows 10 验收仍未完成。

三、三个 Bot
------------

1. Hermes Bot
2. Claude Code Bot
3. Codex Bot

四、六条目标链路
----------------

1. Hermes 私聊
2. Hermes 群聊
3. Claude Code 私聊
4. Claude Code 群聊
5. Codex 私聊
6. Codex 群聊

五、当前与目标
--------------

当前 Reference Baseline 与 2026-08-07 旧入口用户确认保留历史 Telegram 证据。Control Plane 已实现三个固定 Bot 的安全凭据、getMe、一次性绑定、User ID/Group ID 自动发现和 3/3 同群一致性，但结构化真实向导证据仍未采集。最小 GUI 已提供四步私聊/群 Onboarding、QR、深链接、Dashboard 和 Diagnostics；新 GUI 私聊/群自动检测为 `PENDING USER LIVE VALIDATION`。

用户只需提供三个 Bot Token，并完成 Telegram 官方要求的首次 /start、建群/加 Bot 与权限设置；模型账号、Hermes 管理和六链路真实消息测试不由本轮 GUI 假装完成。Bot 识别、Token 验证、User ID、Group/Chat ID、Claude/Codex Project 和受管启动在 Control Plane 路径具备；Hermes 仍可能 pending_component_install。Windows 10 为 `PENDING WINDOWS 10 VALIDATION`，MSI/签名为 `DEFERRED`。

六、验收规则
------------

每条链路独立记录 Bot 连接、私聊、群聊、命令、Mention、Reply、Topic、Session 隔离、最近验证时间和证据等级。任一证据不得替代另一项，unknown 不视为 healthy。
