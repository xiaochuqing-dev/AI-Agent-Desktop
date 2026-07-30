# cc-connect Patch 集

本目录包含 cc-connect 自定义 Patch，从 %TEMP%\cc-connect-src (HEAD fc315d2) 的 dirty working tree 拆分而来。
拆分依据是真实 git diff（patches/raw/git-diff.patch，38 个 hunk），不以旧文档"6 个 Patch"为准。

## 上游基准

- 仓库: https://github.com/chenhg5/cc-connect.git
- 分支: main
- 基准 Commit: fc315d213b49d62e9d90ea4a510189d4115e636f
- npm package version: 1.4.1 (框架；bin 已被自编译版覆盖)
- 所有 Patch 均基于此 Commit，按编号顺序应用。

## 应用前提（重要：行尾）

cc-connect 上游 Go 文件以 LF 存储于 blob，但 Windows 默认 core.autocrlf=true 会在 checkout 时转成 CRLF，导致 LF-context 的 patch 用普通 `git apply` 不匹配。
应用前必须确保源码工作树为 LF：
  git config core.autocrlf false
  git checkout HEAD -- .     # 重新 checkout 为 LF
或 clone 时用 `git clone -c core.autocrlf=false`。
脚本 apply-cc-connect-patches.ps1 已内置此步骤。

## Patch 清单

| 编号 | 文件 | 分类 | 修改目的 |
|---|---|---|---|
| 001 | 001-telegram-directed-routing.patch | A 运行行为 | Telegram 显式 @ 与 Reply 路由优先级 |
| 002 | 002-hook-config-headers.patch | A 运行行为 | HookConfig Headers 透传 |
| 003 | 003-relay-response-prefix.patch | A 运行行为 | Relay response 去 [toName] 前缀 |
| 004 | 004-message-delivery-hooks.patch | A 运行行为 | message.sent_delivered 链路 + 2 新测试文件 |
| 005 | 005-windows-build-compat.patch | B 构建兼容 | proc_windows.go 删 unused import |

未纳入 patch 的 untracked 文件:
- core/test_ws_*.json (2 个，内容相同的空 session store) - 是测试运行产物，非源码。测试时会自动生成。建议上游加入 .gitignore。
- 已确认: 旧文档 test_ws_151634a8/71fdff4d.json 同类，均为测试产物。

---

## Patch 001: telegram-directed-routing

修改目的:
  群消息显式 @ 优先于 Reply。消息含任何不指向本 bot 的 @mention 时，抑制 Reply-to-self 激活；
  仅完全无 @ 时 Reply 才激活本 bot。解决"Reply A + @B 导致双 Bot 回复"。
上游基准 Commit: fc315d2
修改文件:
  platform/telegram/telegram.go (4 hunk: isDirectedAtBot 注释 + hasMentionToOther 文本/caption + reply-to-self 抑制)
  platform/telegram/telegram_test.go (1 hunk: TestIsDirectedAtBot +4 P0 用例)
依赖前置 Patch: 无
真实解决场景:
  群里 Reply Claude 的消息并 @Codex，旧逻辑 Claude(被Reply) 和 Codex(被@) 都回复 -> 双回复。
  修复后仅 Codex 回复，Reply 只提供引用上下文。
单元测试:
  TestIsDirectedAtBot (10 子测试，含 4 个 P0 新用例: reply+@other/not, reply+@self/yes, caption 同理) - 通过
上游升级冲突风险:
  中。telegram.go 上游改动频繁；isDirectedAtBot 函数可能被重构。冲突时需手工重打。
回滚方式:
  git checkout HEAD -- platform/telegram/telegram.go platform/telegram/telegram_test.go
是否适合提上游:
  是。通用路由修复，不依赖本项目业务。建议提 PR。

## Patch 002: hook-config-headers

修改目的:
  config 的 HookConfig 新增 Headers 字段；main 构造 core.HookConfig 时透传 h.Headers；
  executeHTTP 把 h.Headers 加到 POST 请求。解决 [hooks.headers] 被丢弃 -> Hook 无 Authorization -> receiver 401 -> msgid_agent_map 恒空。
上游基准 Commit: fc315d2
修改文件:
  config/config.go (HookConfig struct +Headers 字段)
  cmd/cc-connect/main.go (构造 coreHooks 时透传 h.Headers)
  core/hooks.go (HookConfig.Headers 字段 + executeHTTP 遍历 h.Headers 设置请求头)
依赖前置 Patch: 无
真实解决场景:
  cc-connect Hook POST 到 Hermes receiver(8423) 时缺 Authorization，被 401 拒绝，出站消息无 message_id 记录。
  修复后 Bearer 鉴权通过，Transcript 完整。
单元测试:
  无独立单测（E2E 验证: msgid_agent_map 持续写入）。
  注意: 本 patch 与 Patch 004 共享 core/hooks.go，但改的是不同 hunk（002 改 HookConfig+executeHTTP，004 改 HookEvent 常量）。
上游升级冲突风险:
  低。config struct 新增字段；main.go/hooks.go 局部新增。
回滚方式:
  git checkout HEAD -- config/config.go cmd/cc-connect/main.go core/hooks.go
  (注意: core/hooks.go 同时含 Patch 004 的常量，回滚会连带 004)
是否适合提上游:
  是。通用 bug 修复（Hook headers 应被透传）。

## Patch 003: relay-response-prefix

修改目的:
  relayVisibilityResponseLabel 由 "[toName] <response>" 改为 "<response>"（Full 模式），
  Summary 模式去 [toName]。Worker Bot 已以自己身份发言，不需要 cc-connect 再加 [Claude]/[Codex] 前缀。
  Step 1.5: 同步更新 core/relay_test.go 的 Full 与 Summary 两个断言，使新行为有明确测试。
上游基准 Commit: fc315d2
修改文件:
  core/relay.go (relayVisibilityResponseLabel: Full 去 [toName]，Summary 去 [toName])
  core/relay_test.go (Step 1.5 新增: TestRelayManager_DefaultVisibilityEchoesFullMessages 与
    TestRelayManager_VisibilitySummarySuppressesBodies 两处断言去 [target-bot] 前缀)
依赖前置 Patch: 无
真实解决场景:
  修复前群里 Worker 发言带 [Claude]/[Codex] 冗余前缀，像机器人自报身份。修复后前缀消失。
单元测试:
  TestRelayManager_DefaultVisibilityEchoesFullMessages - 通过 (Step 1.5 修正断言后)
  TestRelayManager_VisibilitySummarySuppressesBodies - 通过 (Step 1.5 修正断言后)
  TestRelayManager_VisibilityNoneSuppressesGroupEcho - 通过 (不受影响)
  注: request label ([source-bot -> target-bot]) 未改，符合 patch 003 只改 response label 的语义边界。
上游升级冲突风险:
  低。单函数单处修改 + 测试断言同步。
回滚方式:
  git checkout HEAD -- core/relay.go core/relay_test.go
是否适合提上游:
  可争议。前缀是 visibility 设计，上游可能认为有用。体验改进，非 bug。
  若提上游，relay_test.go 断言更新必须同 PR。

## Patch 004: message-delivery-hooks

修改目的:
  平台发送成功后取回真实 message_id，触发 message.sent_delivered hook，
  让外部治理层(Hermes receiver)记录出站消息 -> Transcript 完整 + msgid_agent_map。
  新增 SentMessageRecorder 接口、Message +4 字段(ChatID/ThreadID/ReplyToMessageID/SenderIsBot)、
  engine 的 emitSentDelivered、telegram 的 recordSent/LastSentMessageID/ClearLastSent + 各 Send 路径补 recordSent。
上游基准 Commit: fc315d2
修改文件:
  core/engine.go (5 hunk: messageReceivedExtra/messageSentDeliveredExtra + handleMessage Extra + 2 处 stream-preview 补 emitSentDelivered + sendAlreadyRenderedWithError 补 + emitSentDelivered 函数)
  core/hooks.go (1 hunk: HookEventMessageSentDelivered 常量)
  core/interfaces.go (SentMessageRecorder 接口)
  core/message.go (Message struct +4 字段)
  platform/telegram/telegram.go (13 hunk: lastSent 字段 + dispatchMessage 填充 metadata + recordSent/LastSent/Clear + Reply/Send/SendImage/SendFile/sendVoice/sendAudio/SendWithButtons/SendPreviewStart/sendChunked/sendChunkedWithButtons 各路径补 recordSent)
  新增: core/multiagent_hook_test.go, platform/telegram/multiagent_metadata_test.go
依赖前置 Patch: 无（与 001/002/003 互不依赖，但同文件 telegram.go 与 001 共享，应用顺序 001 先 004 后）
真实解决场景:
  修复前出站消息无 message_id 回传 -> Transcript 不完整 -> msgid_agent_map 缺失。
  修复后 Hermes 能记录每条出站消息的真实 message_id 与归属 agent。
单元测试:
  TestMessageReceivedExtra (3 子测试) - 通过
  TestMessageSentDeliveredExtra - 通过
  TestSendRecordsMessageID / TestSendImageRecordsMessageID / TestSendFileRecordsMessageID
  TestDispatchMessagePopulatesMetadata / TestDispatchMessageBotSender (platform/telegram) - 通过
PII 提示:
  Step 1.5 已 sanitize: 新文件 multiagent_metadata_test.go 的测试 fixture User ID
  与 username 已替换为虚构值（1000000001 / test_human_user），测试仍全部通过。
  原始 dirty 源中的真实 ID 未进入 Patch。
上游升级冲突风险:
  高。跨 5 文件 + 2 新文件；telegram.go 上游改动频繁。冲突时需逐文件手工重打。
回滚方式:
  git checkout HEAD -- core/engine.go core/hooks.go core/interfaces.go core/message.go platform/telegram/telegram.go
  rm core/multiagent_hook_test.go platform/telegram/multiagent_metadata_test.go
  (注意: telegram.go 同时含 Patch 001，hooks.go 同时含 Patch 002)
是否适合提上游:
  部分。接口设计(SentMessageRecorder)通用，但改动面大。可拆分提 PR。

## Patch 005: windows-build-compat

修改目的:
  删除 agent/pi/proc_windows.go 未使用的 "os" import。修复 fc315d2 (tuitui commit) 遗留的编译错误。
上游基准 Commit: fc315d2
修改文件:
  agent/pi/proc_windows.go (删 "os" import)
依赖前置 Patch: 无
真实解决场景:
  fc315d2 的 proc_windows.go 含未使用 import，去掉 no_pi tag 编译时阻塞。
  当前 no_pi build 不受影响(间接必需)；去 no_pi 时必需。
单元测试:
  无（编译修复）。
上游升级冲突风险:
  低。若上游已修则本 patch 多余但无害。
回滚方式:
  git checkout HEAD -- agent/pi/proc_windows.go
是否适合提上游:
  是。上游 bug（unused import）。

---

## 验证结果（Step 1.5，2026-07-27）

- 5 个 Patch 普通 git apply --check 全部通过（源码工作树为 LF 时）。
- 按顺序 git apply 全部成功：modified=11（含 Step 1.5 新增 relay_test.go）+ 2 untracked 新文件。
- go build -tags "no_web goolm no_pi" ./... 编译通过。
- patch 001: TestIsDirectedAtBot (10 子测试含 4 P0) 通过。
- patch 003: TestRelayManager_DefaultVisibilityEchoesFullMessages / VisibilitySummary / VisibilityNone 全通过（Step 1.5 修正断言后）。
- patch 004: TestMessageReceivedExtra / TestMessageSentDeliveredExtra / 6 个 multiagent_metadata 测试全通过。
- platform/telegram 包测试全部通过。
- 预存失败（与 Patch 无关，pristine fc315d2 同样失败）:
  TestAppendFileRefs_AbsolutizesRelativePaths / TestAppendFileRefs_AbsoluteInputsPassthrough
  原因: 上游测试用 Unix 绝对路径（/tmp/...），Windows 下被改写为 C:\... 路径。非本 Patch 集引入。
- PII: Step 1.5 已清除测试 fixture 中的真实 User ID 与 username，全部替换为虚构值。
- 可重复: reset 到 pristine 后重新 apply --check + apply 全部成功。
- 候选二进制已构建（见 build/output/），未覆盖 npm 全局运行二进制。
