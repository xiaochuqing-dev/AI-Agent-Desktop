Telegram AI 编程团队范围
========================

一、定位
------

面向 Windows 开发者的 Telegram AI 编程团队安装、配置、管理、诊断与恢复中心。

二、固定首发范围
----------------

Windows 10/11、Telegram、Hermes、Claude Code、Codex、cc-connect，以及推荐但非强制的 CC Switch。PySide6 是未来 GUI 首选，本阶段不实现 GUI。

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

当前 Reference Baseline 已有群聊主要链路和 Hermes 私聊证据，Claude Code/Codex 私聊仍需补齐正式矩阵。Control Plane 当前只读，不会自动绑定 Bot 或检测六条真实链路。

未来用户只提供模型账号或 API 凭据、三个 Bot Token，并完成 Telegram 官方要求的首次 /start 与权限设置。产品未来自动处理 Bot 识别、Token 验证、User ID、Group/Chat ID、白名单、Hermes/cc-connect 配置、Project、端口、Hook、Session、后台启动、六链路检测和修复。

六、验收规则
------------

每条链路独立记录 Bot 连接、私聊、群聊、命令、Mention、Reply、Topic、Session 隔离、最近验证时间和证据等级。任一证据不得替代另一项，unknown 不视为 healthy。
