PUBLIC HANDOFF READY

更新时间：2026-08-07

仓库：https://github.com/xiaochuqing-dev/AI-Agent-Desktop
Reference Baseline Tag：v0.1-reference-baseline
Baseline HEAD：cd3493b191fdc19114e0ae037746ab3d23a58a79
cc-connect 参考版本：v1.4.1-patchset0.1-fc315d2
PR #1 最终 Head：5b47f430cd7c003c00ab6c3a3ad006e8df336b46
PR #1 合并提交：0952c74e95fa8557b78352f8c30d19de0e021fb0

当前交付

Control Plane v1 契约与 ADR 已冻结。除只读发现、Readiness、Diagnostic、Dry-run、持久化 OperationExecutor/SSE 和脱敏外，Windows Credential Manager、三 Bot 身份/绑定、Update Lease、managed/native 配置分离、Claude/Codex 合法原生配置、revision/回滚、产品自有 cc-connect 生命周期、六链路可观测性、消息关联、Session 隔离探针、代理策略、合成 E2E、一次性计划和验收向导已实现。Fake 与 Windows 11 合成验收通过；2026-08-07 用户直接在 Telegram 验证六条链路并明确通过。Windows 10 和未经向导生成的结构化 live 证据仍未完成，整体为 PARTIAL。

产品范围

首发固定为 Windows 10/11 与 Telegram，Agent 为 Hermes、Claude Code、Codex。用户可见三个 Bot，目标为六条私聊/群聊链路。cc-connect 是 V1 核心桥梁，CC Switch 是推荐但非强制的配置入口。采用 Integration First 和唯一 ManagementOwner。

运行环境保护

本阶段未修改 src/、dual_agent、5 个 cc-connect Patch、真实 Bot/Provider 配置、系统/用户 PATH、注册表、计划任务定义或 junction。Windows Credential 验收只写入并删除随机 acceptance/ 引用。用户直接在 Telegram 发送真实验收消息，仓库与报告没有接收 Token 或保存消息正文。Hermes 黑窗口反馈只在本机外部运行层做了带备份的启动脚本和子进程无窗口修复，不属于仓库源码。

下一阶段

下一阶段为最小 GUI、十分钟 Onboarding 与 Windows 自包含分发。Windows 10 x64 仍待用户实机验证；若要形成机器可审计的 live 证据，应通过向导补做三次 getMe、3/3 绑定和六条 correlation，不得由用户体验结论反推。

最终候选包、manifest、SHA256、锁定 venv、用户验证边界和 CI 结果见 reports/SIX_LINK_OBSERVABILITY_LIVE_E2E_AND_USER_VALIDATION_REPORT.md。

最终分支

远端和本地均只保留 main 作为开发主线。当前阶段的精确 GitHub Actions Run 与 Artifact 记录在阶段报告中。
