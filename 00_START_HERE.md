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
8. control-plane/README.md

src/ 与 integrations/cc-connect/patches/ 是 Reference Baseline 的当前证据。control-plane/ 是已实现的独立基础运行代码区，不覆盖或接管 Reference Baseline 的现有服务。

三、当前实现边界
----------------

Control Plane 已提供只读发现、Readiness、Dry-run、持久化 Operation/SSE、脱敏诊断，以及 cc-connect 单组件的锁定产物计划、显式确认、隔离安装、回滚、卸载和恢复。其他组件安装、配置或凭据写入、生命周期接管、Telegram 自动绑定、六链路自动检测和 GUI 均未实现。

四、下一阶段
------------

下一阶段准确名称是“cc-connect 产品管理生命周期与最小配置写入切片”。前提是保持外部生命周期所有权不被静默接管，并通过 SecretRef、端口所有权和可回滚配置门禁。见 05_NEXT_PHASE.md 与 next-agent/NEXT_AGENT_PROMPT.txt。

五、遇到矛盾
------------

以实际文件、Git、GitHub Actions、Patch 和 SHA256 为准，记录冲突与证据，不覆盖更新事实，不虚报未知能力。
