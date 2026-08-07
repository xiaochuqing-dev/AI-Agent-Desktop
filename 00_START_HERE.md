00 开始阅读
============

本仓库是当前公开事实源。请按以下顺序阅读。

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

src/ 与 integrations/cc-connect/patches/ 是 Reference Baseline 的当前证据。control-plane/ 是已实现的独立基础运行代码区，不覆盖或接管 Reference Baseline 的现有服务。

三、当前实现边界
----------------

Control Plane 已提供只读发现、Readiness、Dry-run、持久化 OperationExecutor/SSE、脱敏诊断、Windows Credential Manager 凭据、三 Bot getMe 与绑定、Update Lease、managed/native 配置分离、锁定 Renderer、Claude/Codex 原生配置计划/备份/回滚、六链路可观测性、一次性 E2E 计划、Session 隔离探针、代理策略和自包含验收向导。Fake/合成门禁已通过；2026-08-07 用户直接在 Telegram 验证六条私聊/群聊链路并明确通过。由于没有经向导执行，本轮没有三次 getMe、3/3 绑定和 correlation 的结构化 live 记录；Windows 10 也未实机验证，因此整体状态仍为 PARTIAL。

四、下一阶段
------------

下一阶段准确名称是“最小 GUI、十分钟 Onboarding 与 Windows 自包含分发切片”。进入正式发布前仍需补齐 Windows 10 x64 实机验证；如需把直接 Telegram 的用户证据升级为 Control Plane 可审计证据，应单独执行向导 getMe、3/3 绑定和六链路 correlation 流程，不得由现有用户确认反推。见 05_NEXT_PHASE.md 与 next-agent/NEXT_AGENT_PROMPT.txt。

五、遇到矛盾
------------

以实际文件、Git、GitHub Actions、Patch 和 SHA256 为准，记录冲突与证据，不覆盖更新事实，不虚报未知能力。
