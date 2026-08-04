Telegram 已知限制
=================

更新时间：2026-08-05

一、已知事实
------------

- 2026-07-28，群聊主要链路已通过 Reference Baseline 真实 E2E。
- 2026-07-28，Hermes 私聊已通过真实 E2E。
- Claude Code 与 Codex 私聊基本可工作或已有实际使用，但正式完整证据矩阵仍需补齐。
- /start 等命令偶尔可能未进入预期命令逻辑；命令异常时普通消息仍可能正常。
- 私聊、群聊、Reply、Mention、Topic 与 Session 之间仍可能存在少量隔离和路由边界。
- 当前未发现阻断性体验 Bug，本阶段不重构现有路由。
- Control Plane 已通过 Fake Telegram 完成三 Bot getMe、三私聊、三同群绑定与 3/3 一致性；未使用真实 Token，结论是 PENDING USER LIVE VALIDATION。
- 锁定版 cc-connect 原生 Telegram Schema 只有 allow_from，缺少 Group Chat ID 白名单字段；当前可限制 operator user，不能限制唯一群，状态为 unsupported。
- 锁定版 management API 没有 bind host 字段，实测监听所有网卡；虽然 Bearer 验证通过，健康仍只能记为 partial。

二、能力证据登记
----------------

| 能力 | 当前结论 | 最近验证 | 证据等级 |
|---|---|---|---|
| 三 Bot 连接 | 主要链路可用，逐 Bot 持续状态尚未统一采集 | 2026-07-28 | 中 |
| Hermes 私聊 | 已验证 | 2026-07-28 | 高 |
| Hermes 群聊 | 已验证 | 2026-07-28 | 高 |
| Claude Code 私聊 | 基本可用，正式矩阵待补 | 未单独记录 | 中 |
| Claude Code 群聊 | 已纳入群聊主要链路验证 | 2026-07-28 | 高 |
| Codex 私聊 | 基本可用，正式矩阵待补 | 未单独记录 | 中 |
| Codex 群聊 | 已纳入群聊主要链路验证 | 2026-07-28 | 高 |
| /start 等命令 | 存在偶发识别边界 | 未形成独立矩阵 | 低 |
| Mention 路由 | 主要群聊场景已验证 | 2026-07-28 | 高 |
| Reply 路由 | Reply + Mention 场景已验证，其他组合待补 | 2026-07-28 | 中 |
| Topic | 尚无完整证据 | 未验证 | 低 |
| Session 隔离 | 群聊与 Hermes 私聊不串线已验证，跨三 Agent 完整矩阵待补 | 2026-07-28 | 中 |

三、后续处理
------------

通过脱敏可观测性和逐项测试矩阵修复，不用普通消息成功推断命令、Topic 或 Session 隔离已通过。真实 E2E 必须由用户明确确认且不得自动重复发送。

四、本阶段边界
--------------

本阶段只用 Fake Telegram 和合成 Token 验证身份、绑定与受管运行，不执行真实 Telegram E2E，不发送任何消息，不停止或重启 Reference Baseline 或外部服务。
