cc-connect 集成
================

本目录保存我们对 cc-connect 的 5 个正式 Patch、构建脚本和 manifest。
不复制完整 cc-connect 上游源码。

一、上游
--------
仓库 https://github.com/chenhg5/cc-connect.git
构建不跟随分支；精确 Commit 为 fc315d213b49d62e9d90ea4a510189d4115e636f。

二、Patch 集（patchset 0.1，5 个）
-----------------------------------
patches/001-telegram-directed-routing.patch   群消息显式 @ 优先于 Reply
patches/002-hook-config-headers.patch          HookConfig Headers 透传
patches/003-relay-response-prefix.patch         Relay response 去 [toName] 前缀
patches/004-message-delivery-hooks.patch       message.sent_delivered 链路
patches/005-windows-build-compat.patch         proc_windows.go 删 unused import

三、构建
--------
1. 获取上游精确 Commit，并设置 core.autocrlf=false。
2. 在未修改源码上运行 scripts/check-cc-connect-patches.ps1，验证 5 个 Patch 的 LF 规范化摘要和顺序可应用性。
3. 运行 scripts/apply-cc-connect-patches.ps1。
4. 使用锁定 Go 1.26.5 运行相关测试，再运行 scripts/build-cc-connect.ps1。
5. 运行 scripts/verify-cc-connect-artifact.ps1，验证 Manifest、SHA256、PE amd64 和隔离 --version 探针。

锁文件为 manifests/artifact-lock.json。产物版本为 v1.4.1-patchset0.1-fc315d2，大小 26928640 字节，SHA256 为 cd1b0787709c0401a42f7c3ce5321184889adbfbf3b080190fee180afc977eec。Windows PowerShell 5.1 与 PowerShell 7.6.4 共四次本地构建得到相同摘要，签名状态为 unsigned。

四、当前运行
------------
当前 Reference Baseline 运行二进制未被替换。新产物只上传为 GitHub Actions Artifact，并由 Control Plane 安装到当前用户 LocalAppData 下的产品自有隔离目录；安装侧不需要 Go、Node 或全局 npm。

五、许可证
----------
cc-connect 上游许可证见上游仓库。本目录只保存我们的 Patch 和脚本，保留 Attribution。
