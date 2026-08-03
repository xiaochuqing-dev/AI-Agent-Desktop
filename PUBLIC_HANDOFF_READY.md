PUBLIC HANDOFF READY

更新时间：2026-08-04

仓库：https://github.com/xiaochuqing-dev/AI-Agent-Desktop
Reference Baseline Tag：v0.1-reference-baseline
Baseline HEAD：cd3493b191fdc19114e0ae037746ab3d23a58a79
cc-connect 参考版本：v1.4.1-patchset0.1-fc315d2

当前交付

Control Plane v1 契约与 ADR 已冻结，control-plane/ 基础运行代码已实现。当前能力是只读发现、Readiness、结构化 Diagnostic、Dry-run、Operation/SSE 和脱敏。真实安装、配置或凭据写入、生命周期接管、Telegram 自动绑定、六链路自动验收和 GUI 尚未实现。

产品范围

首发固定为 Windows 10/11 与 Telegram，Agent 为 Hermes、Claude Code、Codex。用户可见三个 Bot，目标为六条私聊/群聊链路。cc-connect 是 V1 核心桥梁，CC Switch 是推荐但非强制的配置入口。采用 Integration First 和唯一 ManagementOwner。

运行环境保护

本阶段未修改 src/、dual_agent、5 个 cc-connect Patch、真实配置、凭据、计划任务、Watchdog、junction 或运行中服务，未执行真实 Telegram E2E，未发送消息。

下一阶段

cc-connect 单组件真实安装纵向切片。入口与门禁见 05_NEXT_PHASE.md 和 next-agent/NEXT_AGENT_PROMPT.txt。

最终 Git、CI、合并、分支清理、文件清单与 SHA256 结果见 reports/PR1_READINESS_SCOPE_ALIGNMENT_AND_MAINLINE_MERGE_REPORT.md。
