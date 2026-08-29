PUBLIC HANDOFF READY

更新时间：2026-08-30

仓库：https://github.com/xiaochuqing-dev/AI-Agent-Desktop
Reference Baseline Tag：v0.1-reference-baseline
Baseline HEAD：cd3493b191fdc19114e0ae037746ab3d23a58a79
cc-connect 历史参考运行版本：v1.4.1-patchset0.1-fc315d2
cc-connect 当前产品受管版本：v1.5.0-patchset0.2-17c6106
PR #1 最终 Head：5b47f430cd7c003c00ab6c3a3ad006e8df336b46
PR #1 合并提交：0952c74e95fa8557b78352f8c30d19de0e021fb0
本轮 v1.5.0 功能提交：aca96a0a456fa60a0c00fce4452b771e4e6043f0
本轮 v1.5.0 功能闭环提交：725d371bf2f662fc456fdf4d5df80900f4821624

当前交付

Control Plane v1 契约与 ADR 已冻结。除只读发现、Readiness、Diagnostic、Dry-run、持久化 OperationExecutor/SSE 和脱敏外，Windows Credential Manager、三 Bot 身份/绑定、Update Lease、managed/native 配置分离、Claude/Codex 合法原生配置、revision/回滚、产品自有 cc-connect 生命周期、六链路可观测性、消息关联、Session 隔离探针、代理策略、合成 E2E、一次性计划和验收向导已实现。Fake 与 Windows 11 合成验收通过；2026-08-07 用户直接在 Telegram 验证六条链路并明确通过。Windows 10 和未经向导生成的结构化 live 证据仍未完成，整体为 PARTIAL。

当前 GUI 为 `0.4.1-prebeta`。产品受管 cc-connect 已从 v1.4.1 精确升级到 Stable v1.5.0 source `17c61062c2f9ce9bcdd45a2082e491f9743a2770`：Patch 001–004 重放并有语义变异门禁，Patch 005 退役；锁文件、Renderer、升级停止门禁、配置 revision、运行证据和回滚测试已同步。历史外部参考运行体不受该升级事务影响。

本地全量为 269 passed、2 skipped，Ruff、format、`mypy control_plane`、契约验证及 cc-connect Go/配置/Patch/制品门禁通过；这不是用户 live 证据。新 GUI Telegram 与 Hermes Native Telegram Setup：`PENDING USER LIVE VALIDATION`。Windows 10 x64：`PENDING WINDOWS 10 VALIDATION`。最终 Windows 11 candidate 为 `control-plane/dist/AI-Agent-Desktop-0.4.1-prebeta-windows-x64`，EXE SHA256 `dfe9ad2bfef7f9a7afe402753a2cc5c1eacaf7bb2b26c047067ae97b5630d99e`，validator 与 ordinary-user smoke 通过；MSI、正式安装器和代码签名：`DEFERRED`。

历史功能提交 `ee4343e7f2cd99b93e02fd5c6768f73d50c384b2` 的 GitHub Actions Run `31636567632` 已完成，四个 Job 全部 success。GUI Artifact ID 为 `9157449259`，digest 为 `sha256:c5ca4b0ed29bcce80d6ea1a4cfb8f918da60044c5d9d8fef19cdc88b0343a25d`；cc-connect Artifact ID 为 `9157450718`，digest 为 `sha256:5574b3594b7bdce06ad117ca11c3c1eaadb0139c49b8c0894ea67c66400e5b64`。

历史 GUI 收口提交 `582b12a95e69d2494a58856f62cdae886000d3d5` 已推送 `main`。GitHub Actions Run `31878741409` 四个 Job 全部 success；GUI Artifact ID 为 `9245537693`，digest 为 `sha256:14bd224f82eb8d0c2cb1c07f8be6095b21c021147447e182bcb32317284ebf1d`；cc-connect Artifact ID 为 `9245538197`，digest 为 `sha256:97d5ea9d4d438d8de5a75b2db7eb4d866f8fceb9de71dcb72c225b59b609ead3`。

本轮 v1.5.0 功能证据 GitHub Actions Run `33273341357` 四个 Job 全部 success。GUI Artifact ID 为 `9720889896`，digest 为 `sha256:99349df00159bbb26b0d1b013a0b8190b84d3bd8920f64cb802c927e11dc70f4`；cc-connect Artifact ID 为 `9720890261`，digest 为 `sha256:9368d97911e7f5b71e500da29007299081dcbc123f7df0b2f137e03b75e2470e`。完整证据见 `reports/CC_CONNECT_V1_5_0_STABLE_FUSION_UPGRADE_REPORT.md`。

产品范围

首发固定为 Windows 10/11 与 Telegram，Agent 为 Hermes、Claude Code、Codex。用户可见三个 Bot，目标为六条私聊/群聊链路。cc-connect 是 V1 核心桥梁，CC Switch 是推荐但非强制的配置入口。采用 Integration First 和唯一 ManagementOwner。

运行环境保护

本阶段未修改 src/、dual_agent、真实 Bot/Provider 配置、系统/用户 PATH、注册表、计划任务定义或 junction。仅产品集成层的 cc-connect Patch 001–004 按 v1.5.0 重放，Patch 005 退役。Windows Credential 验收只写入并删除随机 acceptance/ 引用；全部本轮验收均未发送真实 Telegram 消息。

下一阶段

下一阶段为用户用 `0.4.1-prebeta` candidate 做新 GUI Telegram 与 Hermes Native Telegram 真实验收，再做 Windows 10 x64 普通用户实机验证；通过后进入 Installer、卸载、快捷方式、Release Asset 与签名准备。历史 2026-08-07 六链路只保留为旧入口 `LIVE_VERIFIED`。

历史候选包、manifest、SHA256、锁定 venv、用户验证边界和旧 CI 结果见 reports/SIX_LINK_OBSERVABILITY_LIVE_E2E_AND_USER_VALIDATION_REPORT.md；本轮 GUI Pre-Beta 实施、功能 CI 和未完成门禁见 reports/GUI_PRE_BETA_AGENT_RUNTIME_AND_LIVE_CLOSURE_REPORT.md。

公开文件保护

本轮未触碰 `reference-baseline/`。Patch 与 347 个公开文件清单按最终 v1.5.0 融合升级提交重新计算，`SHA256SUMS.txt` 继续排除自身以避免自引用。

最终分支

远端和本地均只保留 main 作为开发主线。本轮功能 SHA、GitHub Actions Run 与 Artifact 已记录在最终融合升级报告中。
