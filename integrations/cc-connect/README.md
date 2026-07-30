cc-connect 集成
================

本目录保存我们对 cc-connect 的 5 个正式 Patch、构建脚本和 manifest。
不复制完整 cc-connect 上游源码。

一、上游
--------
仓库 https://github.com/chenhg5/cc-connect.git
分支 main
HEAD fc315d213b49d62e9d90ea4a510189d4115e636f

二、Patch 集（patchset 0.1，5 个）
-----------------------------------
patches/001-telegram-directed-routing.patch   群消息显式 @ 优先于 Reply
patches/002-hook-config-headers.patch          HookConfig Headers 透传
patches/003-relay-response-prefix.patch         Relay response 去 [toName] 前缀
patches/004-message-delivery-hooks.patch       message.sent_delivered 链路
patches/005-windows-build-compat.patch         proc_windows.go 删 unused import

三、构建
--------
1. git clone cc-connect 上游，checkout fc315d2
2. 运行 scripts/apply-cc-connect-patches.ps1 应用 5 个 Patch
3. 运行 scripts/check-cc-connect-patches.ps1 校验
4. 运行 scripts/build-cc-connect.ps1 构建
5. 产物版本 v1.4.1-patchset0.1-fc315d2，SHA256 f7a577bb...

四、当前运行
------------
当前运行二进制即该构建产物，已通过真实 Telegram 群聊与 Hermes 私聊 E2E。

五、许可证
----------
cc-connect 上游许可证见上游仓库。本目录只保存我们的 Patch 和脚本，保留 Attribution。
