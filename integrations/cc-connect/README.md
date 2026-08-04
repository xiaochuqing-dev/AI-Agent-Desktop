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

Control Plane 保留 state/config/cc-connect.managed.toml 作为旧兼容状态，并为合法运行分离生成 state/managed/cc-connect-state.json 与 state/runtime-config/cc-connect.toml。managed state 保存 Owner、revision、CredentialRef、Bot/binding 与证据引用；原生 TOML 只包含锁定 Schema 支持的 Project、Agent、Telegram Platform、allow_from/admin_from 和 Secret 环境变量占位符。写入使用显式确认、revision、备份、原子替换、重解析和回滚。

启停只操作经产品所有权交接且身份可证明的进程。身份绑定 artifact、exe 规范路径/SHA256、PID/创建时间、命令摘要、configuration revision 和 loopback 端口。不匹配或端口被外部 PID 占用时拒绝操作，不终止外部进程。

锁定源码的 Config.Load 已由源码与 Go 探针证明支持 `${NAME}` 展开；合法 Claude/Codex Project 的真实进程已通过持续运行、stop、restart、reconcile、PID/SHA/config/port 和 management Bearer 验收。整体仍不得标 COMPLETE：真实 Telegram 与 Windows 10 待验证，deep health 和原生 Group Chat 过滤为 unsupported，management API 因上游无 bind host 只能监听所有网卡。本阶段没有升级上游或增加 Patch。

六、可升级边界
--------------------

当前版本仅来自 artifact lock、manifest、current 指针和持久化记录。ArtifactProvider 和 UpdateSource 边界支持未来精确版本评估、兼容性检查、迁移计划和回滚，当前不使用 latest，不自动下载或升级。

七、许可证
------------

cc-connect 上游许可证见上游仓库。本目录只保存我们的 Patch 和脚本，保留 Attribution。
