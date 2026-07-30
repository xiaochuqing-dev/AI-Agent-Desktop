cc-connect Patch 集测试结果摘要 (TEST_RESULTS_SUMMARY)

生成时间: 2026-07-28
说明: 本文件记录 cc-connect Patch 集相关测试的命令与结果摘要。测试在 Step 1.5（2026-07-27）执行，基于 fc315d2 上游源码加 5 个 Patch 的干净应用副本。不含用户隐私，不含完整环境变量。

一、测试环境

操作系统: Windows 11 Home China 10.0.26200
Go 版本: go1.26.5 windows/amd64
cc-connect 上游 Commit: fc315d213b49d62e9d90ea4a510189d4115e636f
Patch 状态: 5 个 Patch 全部应用（modified=10，untracked=2）
行尾: LF（autocrlf=false 已归一化）
测试执行位置: cc-connect 源码工作树根目录（%TEMP%\cc-connect-src 或其干净 clone）

二、测试命令

主命令（覆盖 patch 相关包）:
  go test -tags "no_web goolm no_pi" ./core/ ./platform/telegram/

限定到 patch 相关子测试:
  go test -tags "no_web goolm no_pi" -run "TestIsDirectedAtBot|TestRelayManager|TestMessageReceivedExtra|TestMessageSentDeliveredExtra" ./core/ ./platform/telegram/

build tags 说明:
  no_web  跳过 web admin 前端 embed
  goolm   使用 goolm olm 库（默认）
  no_pi   排除 pi agent（cmd/cc-connect/plugin_agent_pi.go）

三、patch 相关测试全绿清单

下列测试在 Step 1.5 全部通过。

Patch 001 相关（platform/telegram/telegram_test.go）:
  TestIsDirectedAtBot
    共 10 个子测试，含 4 个 P0 新用例:
      reply 加 @other 不响应（防双回复）
      reply 加 @self 仍响应
      caption reply 加 @other 不响应（对称用例）
      caption reply 加 @self 仍响应（对称用例）
    状态: 通过

Patch 003 相关（core/relay_test.go，Step 1.5 新增/修正断言）:
  TestRelayManager_DefaultVisibilityEchoesFullMessages
    断言: Full 模式 response label 去 [toName] 前缀
    状态: 通过（Step 1.5 修正断言后）
  TestRelayManager_VisibilitySummarySuppressesBodies
    断言: Summary 模式 response label 去 [toName] 前缀
    状态: 通过（Step 1.5 修正断言后）
  TestRelayManager_VisibilityNoneSuppressesGroupEcho
    不受 Patch 003 影响
    状态: 通过

Patch 004 相关（core/multiagent_hook_test.go 与 platform/telegram/multiagent_metadata_test.go）:
  TestMessageReceivedExtra
    共 3 个子测试，验证 message.received hook 填充 Extra 字段（message_id/chat_id/thread_id/reply_to/sender_type/附件）
    状态: 通过
  TestMessageSentDeliveredExtra
    验证 message.sent_delivered hook 触发与 Extra 字段
    状态: 通过
  6 个 multiagent_metadata 测试（platform/telegram 包）:
    包含但不限于以下子测试（具体子测试名见测试源文件）:
      TestDispatchMessagePopulatesMetadata
      TestDispatchMessageBotSender
      TestSendRecordsMessageID
      TestSendImageRecordsMessageID
      TestSendFileRecordsMessageID
      等
    验证: platform 发送成功后取回真实 message_id 并 recordSent
    状态: 通过
  PII 提示: Step 1.5 已 sanitize 测试 fixture，真实 User ID 83...273(已掩码) 替换为虚构值 1000000001，username <已掩码测试用户名> 替换为 test_human_user。测试全部通过。

四、预存失败说明（与 Patch 无关）

下列测试在 pristine fc315d2（未应用任何 Patch）同样失败，非本 Patch 集引入。

  TestAppendFileRefs_AbsolutizesRelativePaths
    位置: core 包（cc-connect 上游测试）
    失败原因: 上游测试用 Unix 绝对路径（/tmp/...），Windows 下被改写为 C:\... 路径，断言不匹配
    状态: 预存失败，不作为 Patch 失败依据
  TestAppendFileRefs_AbsoluteInputsPassthrough
    位置: 同上
    失败原因: 同上
    状态: 预存失败，不作为 Patch 失败依据

处理建议: 这两个测试应在 cc-connect 上游修复（让测试跨平台），不在本 Patch 集范围内。本 Patch 集不修改这两个测试或其依赖代码。

五、构建验证（非单元测试）

go build -tags "no_web goolm no_pi" ./...
  状态: 编译通过
  说明: 5 个 Patch 应用后，全项目（含 cmd/cc-connect）可正常编译。Patch 005 的删 unused import 是编译兼容修复，去掉 no_pi tag 时必需；当前 no_pi build 不直接受影响，但 Patch 005 仍保留作通用编译兼容。

候选二进制 --version 输出:
  v1.4.1-patchset0.1-fc315d2
  说明: 与 VERSIONS.lock [cc-connect-build].version_format 一致

六、可重复性验证

Step 1.5 已执行可重复性验证:
  1. reset 到 pristine fc315d2
  2. 重新 apply --check 5 个 Patch: 全部通过
  3. apply 5 个 Patch: 全部成功
  4. go build: 通过
  5. patch 相关测试: 全绿（与首次应用结果一致）
  6. 预存失败项: 与首次应用结果一致

结论: 从 pristine fc315d2 出发，按 001 -> 002 -> 003 -> 004 -> 005 顺序应用 5 个 Patch 后，可重复构建出功能等价的候选二进制，patch 相关测试稳定全绿。每次构建因 buildTime 嵌入 ldflags，SHA256 会变（非位级可复现），但功能代码同源。

七、隐私与脱敏说明

本文件不含:
  - Telegram Bot Token 或 Hook Bearer Token
  - 真实 Telegram User ID 或群 Chat ID
  - 真实用户名或邮箱
  - 完整环境变量集
  - 真实路径中的用户名（仅在测试 fixture 中出现已 sanitize 的虚构值 1000000001 与 test_human_user）

本文件含:
  - 测试命令（含 build tags）
  - 测试名清单
  - 通过/失败状态
  - 上游 Commit hash（fc315d2...）
  - 版本字符串（v1.4.1-patchset0.1-fc315d2）

八、参考文件

  engineering/PATCHSET_INDEX.md（每个 Patch 的测试明细）
  engineering/BUILD_AND_REPRODUCTION.md（测试命令与构建流程）
  artifacts/patches/README.md（Patch 集验证结果汇总）
  artifacts/manifests/VERSIONS.lock（Go 版本与 build tags）
