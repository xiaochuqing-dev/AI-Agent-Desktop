00 开始阅读
============

本仓库是当前公开事实源。请按以下顺序阅读。

2026-08-15 状态提示
-------------------

本轮起点为 `74c81d077d4f4e7dc72937af5bd9253eb261d670`。PySide6 四步 GUI 已推进为 `0.4.1-prebeta`，产品受管 cc-connect 已精确锁定到 Stable v1.5.0 source `17c61062c2f9ce9bcdd45a2082e491f9743a2770`；Patch 001–004 重放并增加语义有效性门禁，Patch 005 因上游吸收而退役。新 GUI Telegram 与 Hermes Native Telegram Setup 仍统一记为 `PENDING USER LIVE VALIDATION`。

`0.4.1-prebeta` candidate 在 Windows 11 x64 完成 validator 与 ordinary-user smoke，EXE SHA256 为 `dfe9ad2bfef7f9a7afe402753a2cc5c1eacaf7bb2b26c047067ae97b5630d99e`，全程未访问真实 Telegram。Windows 10 x64 仍为 `PENDING WINDOWS 10 VALIDATION`；MSI、正式安装器和代码签名为 `DEFERRED`。2026-08-07 直接 Telegram 六链路是旧入口历史证据。

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
12. reports/GUI_PRE_BETA_AGENT_RUNTIME_AND_LIVE_CLOSURE_REPORT.md

src/ 与 integrations/cc-connect/patches/ 是 Reference Baseline 的当前证据。control-plane/ 是已实现的独立基础运行代码区，不覆盖或接管 Reference Baseline 的现有服务。

三、当前实现边界
----------------

Control Plane 已提供上述能力，并新增三个独立 Agent Detector、TTL/显式刷新缓存、Onboarding/Dashboard Agent 读模型、严格 Runtime Ready 聚合、GUI Live E2E 接线和 Hermes Telegram Native Configuration Adapter。Bot getMe 只证明 Telegram Identity，不再决定 Agent installed/connected；cc-connect 配置存在也不再等同运行完成。264 passed、2 skipped 及静态/契约门禁是本地自动化证据，不替代真实 Telegram 或 Windows 10 实机证据，整体仍为 PARTIAL。

四、下一阶段
------------

当前切片的下一步是用户真实 GUI Telegram 验收和 Windows 10 x64 实机验证；MSI、正式安装器、签名和公开分发仍为 `DEFERRED`。如需把 Telegram 证据升级为 Control Plane 可审计记录，应单独执行真实 getMe、3/3 绑定和 correlation 流程，不得由旧用户确认反推。见 05_NEXT_PHASE.md、next-agent/NEXT_AGENT_PROMPT.txt 与新阶段报告。

五、遇到矛盾
------------

以实际文件、Git、GitHub Actions、Patch 和 SHA256 为准，记录冲突与证据，不覆盖更新事实，不虚报未知能力。
