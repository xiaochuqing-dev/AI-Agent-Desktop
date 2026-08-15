Telegram 已知限制
=================

更新时间：2026-08-15

2026-08-15 GUI/Hermes 状态更新
-----------------------

`0.4.0-prebeta` GUI 已接入正式 SVG 图标、私聊 deep link/QR、群 startgroup、Binding API、独立 Chat Health、Hermes readiness/conflict 与用户确认 Live E2E，但尚未由用户真实复测。Binding、ready_for_test、LIVE_VERIFIED、failed 和 stale 分开显示；Demo/合成测试不能替代。Windows 10 x64 为 `PENDING WINDOWS 10 VALIDATION`。Hermes Native Telegram Setup 同样等待用户现场确认。

一、已知事实
------------

- 2026-07-28，群聊主要链路已通过 Reference Baseline 真实 E2E。
- 2026-07-28，Hermes 私聊已通过真实 E2E。
- 2026-08-07，用户直接在 Telegram 完成 Hermes、Claude Code、Codex 的私聊与群聊六链路验证，并明确确认无问题、可以通过。
- /start 等命令偶尔可能未进入预期命令逻辑；命令异常时普通消息仍可能正常。
- 私聊、群聊、Reply、Mention、Topic 与 Session 之间仍可能存在少量隔离和路由边界。
- 当前未发现阻断性体验 Bug，本阶段不重构现有路由。
- Control Plane 已通过 Fake Telegram 完成三 Bot getMe、三私聊、三同群绑定与 3/3 一致性。用户真实验收绕过向导，因此六链路用户体验为 LIVE_VERIFIED，但真实 getMe、3/3 和 correlation 结构化证据未采集。
- 锁定版 cc-connect 原生 Telegram Schema 只有 allow_from，缺少 Group Chat ID 白名单字段；当前可限制 operator user，不能限制唯一群，状态为 unsupported。
- 锁定版 management API 没有 bind host 字段，实测监听所有网卡；虽然 Bearer 验证通过，健康仍只能记为 partial。
- GUI 只能通过 Control Plane 快照和 Telegram Binding API 判断私聊/群进度，不读取 Telegram Desktop 登录状态、tdata、群列表或聊天历史；客户端不可达时显示 unknown/需要刷新。
- Telegram Desktop 深链接优先走 `tg://`，不可用时打开官方 HTTPS 下载页；这只证明打开入口，不证明用户已登录或点击 Start。
- QR 只编码短时 binding deep link；QR 显示成功不证明 Bot 激活，绑定状态仍需 Control Plane poll 和用户现场操作。
- Hermes Native Adapter 使用官方 `hermes config env-path` 定位公开 `.env`，只修改 `TELEGRAM_BOT_TOKEN` 与 `TELEGRAM_ALLOWED_USERS`；不默认写入 `TELEGRAM_GROUP_ALLOWED_CHATS`，不设置 Allow-All，不修改 `TELEGRAM_HOME_CHANNEL`。
- 已有 Hermes Bot 配置会先形成 readiness/冲突计划；复用现有 Bot 或切换当前 Bot 都需要显式选择，`.env` 写入可原子回滚，Gateway 原状态会在失败时恢复。

二、能力证据登记
----------------

| 能力 | 当前结论 | 最近验证 | 证据等级 |
|---|---|---|---|
| 三 Bot 连接 | 用户现场均可用；结构化持续状态未由向导采集 | 2026-08-07 | 用户确认 |
| Hermes 私聊 | LIVE_VERIFIED | 2026-08-07 | 用户确认 + 只读日志元数据 |
| Hermes 群聊 | LIVE_VERIFIED | 2026-08-07 | 用户确认 + 只读日志元数据 |
| Claude Code 私聊 | LIVE_VERIFIED | 2026-08-07 | 用户确认 + 只读日志元数据 |
| Claude Code 群聊 | LIVE_VERIFIED | 2026-08-07 | 用户确认 + 只读日志元数据 |
| Codex 私聊 | LIVE_VERIFIED | 2026-08-07 | 用户确认 + 部分只读日志元数据 |
| Codex 群聊 | LIVE_VERIFIED | 2026-08-07 | 用户确认 + 只读日志元数据 |
| /start 等命令 | 存在偶发识别边界 | 未形成独立矩阵 | 低 |
| Mention 路由 | 主要群聊场景已验证 | 2026-07-28 | 高 |
| Reply 路由 | Reply + Mention 场景已验证，其他组合待补 | 2026-07-28 | 中 |
| Topic | 尚无完整证据 | 未验证 | 低 |
| Session 隔离 | 群聊与 Hermes 私聊不串线已验证，跨三 Agent 完整矩阵待补 | 2026-07-28 | 中 |
| 新 GUI 私聊自动检测 | 尚未用户现场复测 | 2026-08-13 | PENDING USER LIVE VALIDATION |
| 新 GUI 群自动检测 | 尚未用户现场复测 | 2026-08-13 | PENDING USER LIVE VALIDATION |
| 新 GUI 六链路 Live E2E | 已接线，尚未用户确认执行 | 2026-08-13 | PENDING USER LIVE VALIDATION |

三、后续处理
------------

继续通过脱敏可观测性和逐项测试矩阵定位问题，不用普通消息成功推断未单独测试的命令或 Topic 已通过。真实 E2E 必须由用户明确确认且不得自动重复发送。

四、本阶段边界
--------------

自动化只用 Fake Telegram 和合成 Token 验证身份、绑定与受管运行。真实消息由用户直接在 Telegram 发送，未向本任务提供 Token，仓库不保存消息正文；因未使用向导，本轮不具备结构化 getMe、3/3 或 correlation 证据。Windows 10 仍为 PENDING WINDOWS 10 VALIDATION。
