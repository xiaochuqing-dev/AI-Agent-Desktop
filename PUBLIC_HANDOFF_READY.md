PUBLIC HANDOFF READY

更新时间：2026-08-04

仓库：https://github.com/xiaochuqing-dev/AI-Agent-Desktop
Reference Baseline Tag：v0.1-reference-baseline
Baseline HEAD：cd3493b191fdc19114e0ae037746ab3d23a58a79
cc-connect 参考版本：v1.4.1-patchset0.1-fc315d2
PR #1 最终 Head：5b47f430cd7c003c00ab6c3a3ad006e8df336b46
PR #1 合并提交：0952c74e95fa8557b78352f8c30d19de0e021fb0

当前交付

Control Plane v1 契约与 ADR 已冻结。除只读发现、Readiness、Diagnostic、Dry-run、持久化 OperationExecutor/SSE 和脱敏外，cc-connect 锁定 Windows 产物的隔离安装、原子最小配置、revision/回滚、所有权交接与产品自有生命周期已实现。真实凭据、其他组件生命周期、Telegram 自动绑定、六链路自动验收和 GUI 尚未实现；无 Secret 持续运行为 PARTIAL。

产品范围

首发固定为 Windows 10/11 与 Telegram，Agent 为 Hermes、Claude Code、Codex。用户可见三个 Bot，目标为六条私聊/群聊链路。cc-connect 是 V1 核心桥梁，CC Switch 是推荐但非强制的配置入口。采用 Integration First 和唯一 ManagementOwner。

运行环境保护

本阶段未修改 src/、dual_agent、5 个 cc-connect Patch、真实配置、凭据、计划任务、Watchdog、junction 或运行中服务，未执行真实 Telegram E2E，未发送消息。

下一阶段

Telegram 三 Bot 安全绑定、自动身份发现与配置生成切片。入口与门禁见 05_NEXT_PHASE.md 和 next-agent/NEXT_AGENT_PROMPT.txt。Windows 10 x64 仍待用户实机验证。

最终 Git、CI、分支清理、文件清单与 SHA256 结果见 reports/CC_CONNECT_WINDOWS_ARTIFACT_AND_INSTALLATION_SLICE_REPORT.md。

最终分支

远端和本地均只保留 main 作为开发主线。当前阶段的精确 GitHub Actions Run 与 Artifact 记录在阶段报告中。
