PUBLIC HANDOFF READY

更新时间：2026-08-13

仓库：https://github.com/xiaochuqing-dev/AI-Agent-Desktop
Reference Baseline Tag：v0.1-reference-baseline
Baseline HEAD：cd3493b191fdc19114e0ae037746ab3d23a58a79
cc-connect 参考版本：v1.4.1-patchset0.1-fc315d2
PR #1 最终 Head：5b47f430cd7c003c00ab6c3a3ad006e8df336b46
PR #1 合并提交：0952c74e95fa8557b78352f8c30d19de0e021fb0

当前交付

Control Plane v1 契约与 ADR 已冻结。除只读发现、Readiness、Diagnostic、Dry-run、持久化 OperationExecutor/SSE 和脱敏外，Windows Credential Manager、三 Bot 身份/绑定、Update Lease、managed/native 配置分离、Claude/Codex 合法原生配置、revision/回滚、产品自有 cc-connect 生命周期、六链路可观测性、消息关联、Session 隔离探针、代理策略、合成 E2E、一次性计划和验收向导已实现。Fake 与 Windows 11 合成验收通过；2026-08-07 用户直接在 Telegram 验证六条链路并明确通过。Windows 10 和未经向导生成的结构化 live 证据仍未完成，整体为 PARTIAL。

本轮将 GUI 收口到 `0.3.0-prebeta`：真实 Hermes/Claude Code/Codex Detection、严格 cc-connect Runtime Readiness、Binding 与 Chat Live Health 分离、六链路 Live E2E 用户确认、Dashboard/Diagnostics/全局刷新和 1280×720 原生布局回归已完成。本地全量为 240 passed、1 skipped，Ruff、format、mypy 104 files 与契约验证通过；这不是用户 live 证据。

本机 Agent Detection：Hermes 0.19.0、Claude Code 2.1.228、Codex 0.147.0，`LOCAL_VERIFIED`。新 GUI Telegram：`PENDING USER LIVE VALIDATION`。Windows 10 x64：`PENDING WINDOWS 10 VALIDATION`。最终 Windows 11 candidate 为 `control-plane/dist/AI-Agent-Desktop-0.3.0-prebeta-windows-x64-final3-20260813`，EXE 66.05 MiB，SHA256 `7b2a2370f17eb0d1ff181d8fbf6fa36a221672a3bc9525f4c3fca74aa2186223`，validator 与 ordinary-user smoke 通过；MSI、正式安装器和代码签名：`DEFERRED`。

功能提交 `ee4343e7f2cd99b93e02fd5c6768f73d50c384b2` 的 GitHub Actions Run `31636567632` 已完成，四个 Job 全部 success。GUI Artifact ID 为 `9157449259`，digest 为 `sha256:c5ca4b0ed29bcce80d6ea1a4cfb8f918da60044c5d9d8fef19cdc88b0343a25d`；cc-connect Artifact ID 为 `9157450718`，digest 为 `sha256:5574b3594b7bdce06ad117ca11c3c1eaadb0139c49b8c0894ea67c66400e5b64`。

产品范围

首发固定为 Windows 10/11 与 Telegram，Agent 为 Hermes、Claude Code、Codex。用户可见三个 Bot，目标为六条私聊/群聊链路。cc-connect 是 V1 核心桥梁，CC Switch 是推荐但非强制的配置入口。采用 Integration First 和唯一 ManagementOwner。

运行环境保护

本阶段未修改 src/、dual_agent、5 个 cc-connect Patch、真实 Bot/Provider 配置、系统/用户 PATH、注册表、计划任务定义或 junction。Windows Credential 验收只写入并删除随机 acceptance/ 引用。用户直接在 Telegram 发送真实验收消息，仓库与报告没有接收 Token 或保存消息正文。Hermes 黑窗口反馈只在本机外部运行层做了带备份的启动脚本和子进程无窗口修复，不属于仓库源码。

下一阶段

下一阶段为用户用 final3 candidate 做真实 GUI Telegram 验收，再做 Windows 10 x64 普通用户实机验证；通过后进入 Installer、卸载、快捷方式、Release Asset 与签名准备。历史 2026-08-07 六链路只保留为旧入口 `LIVE_VERIFIED`。

历史候选包、manifest、SHA256、锁定 venv、用户验证边界和旧 CI 结果见 reports/SIX_LINK_OBSERVABILITY_LIVE_E2E_AND_USER_VALIDATION_REPORT.md；本轮 GUI Pre-Beta 实施、功能 CI 和未完成门禁见 reports/GUI_PRE_BETA_AGENT_RUNTIME_AND_LIVE_CLOSURE_REPORT.md。

公开文件保护

本轮未触碰 `reference-baseline/` 或 5 个 cc-connect Patch。`PUBLIC_FILE_MANIFEST.txt` 保持 310 项，`SHA256SUMS.txt` 已按最终文档重新计算。

最终分支

远端和本地均只保留 main 作为开发主线。当前阶段的精确 GitHub Actions Run 与 Artifact 记录在阶段报告中。
