# cc-connect Active Patchset 0.2

所有 Patch 均基于 cc-connect v1.5.0 Stable 的精确 Commit 17c61062c2f9ce9bcdd45a2082e491f9743a2770，按编号顺序应用。上游 Go blob 使用 LF；Windows checkout 必须设置 core.autocrlf=false。check/apply 脚本已校验精确 Commit、顺序、LF 规范化摘要和最终 patched file 摘要。

## Patch 清单

| 编号 | 文件 | 决策 | SHA256 |
|---|---|---|---|
| 001 | 001-telegram-directed-routing.patch | 保留并语义重基 | 675437ee433a1f9cca6e43b8e3f7b77e012098cbff0bbfdf65a19d12bed89b37 |
| 002 | 002-hook-config-headers.patch | 保留并语义重基 | 136edd956a33bca4225841a6473b512e05e109edcf09d350e8c54d9c6c3be246 |
| 003 | 003-relay-response-prefix.patch | 保留并语义重基 | f1d1e6dc7a553b889e9a6d04c4215bc1de5a920310f1c3602c18d0a56e5ed2b8 |
| 004 | 004-message-delivery-hooks.patch | 保留、重构并语义重基 | 5302466a7d65c09cc61aa8686d113ff5e9a6b6bb98040ba49d553924cf72b101 |

## 001 Telegram directed routing

上游仍会让 Reply-to-self 先激活 Bot，无法表达“Reply A 但显式 @B 时只激活 B”。Patch 同时检查 text 与 caption entities：存在任意显式 mention 时，只由是否 mention self 决定；完全没有显式 mention 时才回退到 Reply-to-self。命令及命令 @suffix 语义不变。

TestIsDirectedAtBot 覆盖 text/caption @self、@other、纯 Reply、普通群消息和命令矩阵。负向门禁把优先级退回旧语义后，该测试必然失败。

## 002 Hook headers

上游 config.HookConfig、core.HookConfig、main 投影和 executeHTTP 仍没有完整自定义 Header 链路。Patch 增加 TOML decode、config-to-core 投影和 HTTP 发送，并深拷贝 Header map。协议拥有的 Content-Type、User-Agent、X-Hook-Event 最后写入；Headers 不进入 HookEvent JSON，也不记录值。

TestHookConfigHeadersDecode、TestProjectHookConfigPreservesHeaders、TestEmit_HTTPHookCustomHeadersPreserveProtocolHeaders 与 TestHookConfigJSONOmitsHeaders 覆盖该链路。负向门禁禁用 Header 写入后，传播测试必然失败。

## 003 Relay response prefix

上游 Full 和 Summary response 仍带 [toName]。Patch 只移除 response 前缀；request label、None 模式和正文截断不变。

三个 Relay visibility 测试覆盖 Full、Summary 和 None。负向门禁恢复 response 前缀后，Full 测试必然失败。

## 004 Delivery evidence

上游没有等价的 message.sent_delivered 或入站治理元数据。旧 patchset0.1 的共享 lastSent 槽存在并发覆盖、陈旧消费和分片丢失风险，因此没有机械移植。

新设计由 Engine 给可选 DeliveryReporter 注册回调。Telegram 对 Reply、Send、Image、File、Voice、Audio、Buttons、HTML fallback 和每个成功 chunk 使用 Bot API 返回的真实 ID 即时报告；发送失败不报告，部分 chunk 只报告已成功部分。Preview start 不是最终交付，只有最终 Update 成功才报告一次。回调在锁外执行并隔离 panic。

测试覆盖治理 metadata、Hook JSON、成功/失败/fallback、附件、按钮、Preview、部分 chunk、并发唯一 ID 和 panic 隔离。负向门禁切断 Engine delivery callback 后，精确 Hook 测试必然失败。

## 005 退休证据

v1.5.0 原生 agent/pi/proc_windows.go 已没有未使用的 os import。Patch 005 已从 active 目录删除，不生成空 Patch，不改变编号历史。干净 v1.5.0 加四个 Active Patch 可在 Windows 使用锁定 Tags 构建成功。

## 验证入口

- check-cc-connect-patches.ps1：精确基准、Patch digest、顺序 apply check、最终文件 digest。
- apply-cc-connect-patches.ps1：Windows PowerShell 5.1/PowerShell 7 的正式应用路径。
- verify-cc-connect-patch-effectiveness.ps1：四个行为的负向突变测试。
- verify-cc-connect-native-config.ps1：legacy/current TOML 的真实 v1.5.0 config.Load 测试。

core/test_ws_*.json 仍属于上游测试运行产物，不进入 Patch、lock 或 Artifact。
