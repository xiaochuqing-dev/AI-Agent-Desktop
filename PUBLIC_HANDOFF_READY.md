PUBLIC HANDOFF READY

更新时间：2026-08-05

仓库：https://github.com/xiaochuqing-dev/AI-Agent-Desktop
Reference Baseline Tag：v0.1-reference-baseline
Baseline HEAD：cd3493b191fdc19114e0ae037746ab3d23a58a79
cc-connect 参考版本：v1.4.1-patchset0.1-fc315d2
PR #1 最终 Head：5b47f430cd7c003c00ab6c3a3ad006e8df336b46
PR #1 合并提交：0952c74e95fa8557b78352f8c30d19de0e021fb0

当前交付

Control Plane v1 契约与 ADR 已冻结。除只读发现、Readiness、Diagnostic、Dry-run、持久化 OperationExecutor/SSE 和脱敏外，Windows Credential Manager、三 Bot 身份/绑定、Update Lease、managed/native 配置分离、Claude/Codex 合法原生配置、revision/回滚和产品自有 cc-connect 生命周期已实现。Fake 与 Windows 11 合成验收通过；真实 Telegram、Windows 10、六链路消息 E2E 和 GUI 尚未完成，整体为 PARTIAL。

产品范围

首发固定为 Windows 10/11 与 Telegram，Agent 为 Hermes、Claude Code、Codex。用户可见三个 Bot，目标为六条私聊/群聊链路。cc-connect 是 V1 核心桥梁，CC Switch 是推荐但非强制的配置入口。采用 Integration First 和唯一 ManagementOwner。

运行环境保护

本阶段未修改 src/、dual_agent、5 个 cc-connect Patch、真实配置、系统/用户 PATH、注册表、计划任务、Watchdog、junction 或外部运行中服务。Windows Credential 验收只写入并删除随机 acceptance/ 引用；未使用真实 Telegram Token，未执行真实消息 E2E，未发送消息。

下一阶段

六链路可观测性、真实消息 E2E 与会话隔离修复切片。入口与门禁见 05_NEXT_PHASE.md 和 next-agent/NEXT_AGENT_PROMPT.txt。开始真实消息前必须完成用户显式 live 三 Bot 绑定；Windows 10 x64 仍待用户实机验证。

最终 Git、CI、分支清理、文件清单与 SHA256 结果见 reports/TELEGRAM_THREE_BOT_SECURE_BINDING_AND_NATIVE_CONFIG_GENERATION_REPORT.md。

最终分支

远端和本地均只保留 main 作为开发主线。当前阶段的精确 GitHub Actions Run 与 Artifact 记录在阶段报告中。
