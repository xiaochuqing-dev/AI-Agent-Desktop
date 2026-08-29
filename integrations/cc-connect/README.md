# cc-connect 产品受管集成

本目录只保存 AI-Agent-Desktop 对 cc-connect 的锁、四个产品 Patch、兼容性 Fixture 与构建/验证脚本，不复制完整上游源码，也不修改用户的全局 npm 安装或外部 Reference Baseline。

## 当前锁

- 上游仓库：https://github.com/chenhg5/cc-connect.git
- Stable Tag：v1.5.0
- 精确 Commit：17c61062c2f9ce9bcdd45a2082e491f9743a2770
- 产品版本：v1.5.0-patchset0.2-17c6106
- Artifact ID：cc-connect-v1.5.0-patchset0.2-17c6106-windows-amd64
- Artifact SHA256：67a127b6c59b942058ed2bd8c6237ff613e37eb3df64e7cd6ea0c18f3c418144
- Artifact 大小：54266368 字节
- 工具链：Go 1.26.5、windows/amd64、CGO_ENABLED=0
- Build Tags：no_web、goolm、no_pi
- 签名状态：unsigned

事实源是 manifests/artifact-lock.json。Control Plane 内置副本必须与它逐字节一致，生产安装器同时锁定 manifest 身份、产物大小和产物 SHA256。

## Active Patchset 0.2

001 保留：显式 @mention 优先于 Reply-to-self，避免群内双 Bot 同时响应。

002 保留：把 HookConfig Headers 从 TOML 贯通到 HTTP Hook，同时由协议最后覆盖 Content-Type、User-Agent 和 X-Hook-Event，防止配置伪造协议头。

003 保留：只移除 Relay response 的目标 Bot 前缀；request label 与 visibility 行为保持不变。

004 保留并重构：Telegram 在每次真实发送成功后上报精确 message/chat/thread/type/chunk 元数据；失败不报，HTML fallback 只报成功结果，Preview 只在最终更新成功后报，回调 panic 不影响已成功的发送。

005 已退休：v1.5.0 的 agent/pi/proc_windows.go 已不再导入未使用的 os，干净源码可直接完成 Windows 构建。旧 Patch 只保留在 Git 历史和阶段报告中，不再位于 active patches 目录。

## 可复现构建

1. 以 core.autocrlf=false 获取精确 Commit。
2. 运行 scripts/check-cc-connect-patches.ps1。
3. 运行 scripts/apply-cc-connect-patches.ps1。
4. 运行相关 Go 测试、Native Config 兼容测试和 Patch 负向有效性测试。
5. 运行 scripts/build-cc-connect.ps1。
6. 运行 scripts/verify-cc-connect-artifact.ps1。

Windows PowerShell 5.1 与 PowerShell 7.6.4 从相同锁定输入构建出的二进制 SHA256 完全一致。构建脚本和验证脚本都会拒绝与 artifact lock 大小或摘要不一致的产物。

## 配置、升级与回滚

Native Renderer 身份为 cc-connect-17c6106-native-v2，绑定同一精确上游 Commit。legacy v1 与 current v2 Fixture 字节一致，并由 v1.5.0 的真实 config.Load 同时解析，Claude Code、Codex、Telegram、Management 和环境变量占位符语义无变化。

已有产品受管进程必须先停止才允许切换 artifact。切换后必须通过现有 Native Configuration Plan 新建 revision，使 current pointer、ManagedCcConnectState、NativeConfigurationRevisionRecord、ComponentConfigRendererRecord 和 ManagedProcessRecord 一致指向新 artifact。旧 v1.4.1 immutable version directory 保留为回滚候选；回滚复用 RestoreRequest 和 Native Configuration rollback。

Management API 仍没有 bind_host/bind 配置，网络暴露限制继续标为 PARTIAL。真实 Telegram 和物理 Windows 10 验收不在本阶段自动执行，状态分别保持 PENDING USER LIVE VALIDATION 与 PENDING WINDOWS 10 VALIDATION。
