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

五、产品管理运行边界
--------------------------

Control Plane 仅为自有安装版本生成 state/config/cc-connect.managed.toml。配置限定 127.0.0.1 与受控端口段，仅保存 SecretRef，不包含 Token、API Key、User ID 或 Group ID。写入使用显式确认、revision、备份、原子替换、重解析和回滚。

启停只操作经产品所有权交接且身份可证明的进程。身份绑定 artifact、exe 规范路径/SHA256、PID/创建时间、命令摘要、configuration revision 和 loopback 端口。不匹配或端口被外部 PID 占用时拒绝操作，不终止外部进程。

锁定上游版本要求至少一个 Project 和 Platform；本阶段的 Telegram-disabled、无 Secret 合成配置无法满足受支持运行前提，并且上游没有稳定的本地 health endpoint。因此真实持续运行与 deep health 不得标为 COMPLETE：前者为 PARTIAL，后者为 unsupported。本阶段没有升级上游或增加 Patch。

六、可升级边界
--------------------

当前版本仅来自 artifact lock、manifest、current 指针和持久化记录。ArtifactProvider 和 UpdateSource 边界支持未来精确版本评估、兼容性检查、迁移计划和回滚，当前不使用 latest，不自动下载或升级。

七、许可证
------------

cc-connect 上游许可证见上游仓库。本目录只保存我们的 Patch 和脚本，保留 Attribution。
