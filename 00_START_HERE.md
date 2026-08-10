00 开始阅读
============

本仓库是当前公开事实源。请按以下顺序阅读。

2026-08-11 状态提示
-------------------

当前 `main` 起点为 `33652568727b6bb4b41ae84b99a1e2332eea6bce`。最小 PySide6 GUI 与四步 Onboarding 已落到 `control-plane/control_plane/gui/`，入口版本为 `0.2.0-gui`；它通过本地 Control Plane API 工作，并带有 Demo/合成模式用于离线截图和自动化测试。新 GUI 私聊与群自动检测尚未经过用户真实 Telegram 复测，统一记为 `PENDING USER LIVE VALIDATION`。

Windows 10 x64 仍为 `PENDING WINDOWS 10 VALIDATION`。新的 GUI Windows candidate 已在 Windows 11 x64 构建并通过 manifest、SHA256、PE GUI subsystem、离线 smoke、Qt/内嵌模块和敏感信息验证；旧 stage-a 验收包仍不能冒充新包。MSI、正式安装器和代码签名均为 `DEFERRED`。2026-08-07 直接 Telegram 六链路确认是历史入口证据，与新 GUI 证据分开记录。

一、产品与当前状态
------------------

1. README.md
2. 01_CURRENT_STATE.md
3. 02_PRODUCT_VISION.md
4. 03_LATEST_PRODUCT_DECISIONS.md
5. product/PRODUCT_CONSTITUTION.md
6. product/TELEGRAM_AI_CODING_TEAM_SCOPE.md
7. product/INTEGRATION_FIRST_POLICY.md
8. product/TELEGRAM_KNOWN_LIMITATIONS.md

二、运行事实与 Control Plane
----------------------------

1. CURRENT_RUNTIME_SOURCE_MAP.md
2. reference-baseline/SOURCE_OF_TRUTH.md
3. 04_REFERENCE_BASELINE.md
4. architecture/control-plane-v1/README.md
5. contracts/control-plane-v1/control-plane.openapi.yaml
6. contracts/control-plane-v1/core-models.schema.json
7. contracts/control-plane-v1/event-envelope.schema.json
8. contracts/control-plane-v1/managed-runtime.schema.json
9. control-plane/README.md
10. reports/TELEGRAM_THREE_BOT_SECURE_BINDING_AND_NATIVE_CONFIG_GENERATION_REPORT.md
11. reports/MINIMAL_GUI_ONBOARDING_AND_WINDOWS_DISTRIBUTION_REPORT.md

src/ 与 integrations/cc-connect/patches/ 是 Reference Baseline 的当前证据。control-plane/ 是已实现的独立基础运行代码区，不覆盖或接管 Reference Baseline 的现有服务。

三、当前实现边界
----------------

Control Plane 已提供只读发现、Readiness、Dry-run、持久化 OperationExecutor/SSE、脱敏诊断、Windows Credential Manager 凭据、三 Bot getMe 与绑定、Update Lease、managed/native 配置分离、锁定 Renderer、Claude/Codex 原生配置计划/备份/回滚、六链路可观测性、一次性 E2E 计划、Session 隔离探针、代理策略和自包含验收向导。当前工作区另有最小 PySide6 GUI、四步 Onboarding、Dashboard、Diagnostics、二维码与 Telegram 深链接实现。GUI 自动化/合成门禁已通过，但新 GUI 私聊和群自动检测仍为 `PENDING USER LIVE VALIDATION`；旧的 2026-08-07 直接 Telegram 用户确认不生成新 GUI 的结构化 live 记录。Windows 10 仍未实机验证，整体状态为 PARTIAL。

四、下一阶段
------------

当前切片的下一步是用户真实 GUI Telegram 验收和 Windows 10 x64 实机验证；MSI、正式安装器、签名和公开分发仍为 `DEFERRED`。如需把 Telegram 证据升级为 Control Plane 可审计记录，应单独执行真实 getMe、3/3 绑定和 correlation 流程，不得由旧用户确认反推。见 05_NEXT_PHASE.md、next-agent/NEXT_AGENT_PROMPT.txt 与新阶段报告。

五、遇到矛盾
------------

以实际文件、Git、GitHub Actions、Patch 和 SHA256 为准，记录冲突与证据，不覆盖更新事实，不虚报未知能力。
