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

src/ 与 integrations/cc-connect/patches/ 是 Reference Baseline 的当前证据。control-plane/ 是已实现的独立基础运行代码区，不覆盖或接管 Reference Baseline 的现有服务。

三、当前实现边界
----------------

Control Plane 已提供只读发现、Readiness、Dry-run、持久化 OperationExecutor/SSE、脱敏诊断，以及 cc-connect 锁定产物的隔离安装、原子最小配置、revision/备份/回滚、所有权交接、启停重启、进程身份、端口所有权与重启恢复。真实凭据、Telegram 自动绑定、六链路自动检测和 GUI 均未实现。因上游无可用的无 Secret 持续运行模式，真实管理运行验收为 PARTIAL。

四、下一阶段
------------

下一阶段准确名称是“Telegram 三 Bot 安全绑定、自动身份发现与配置生成切片”。进入前需先解决锁定版 cc-connect 无 Secret 持续运行限制，并保持本阶段的 SecretRef、所有权、进程身份与回滚门禁。见 05_NEXT_PHASE.md 与 next-agent/NEXT_AGENT_PROMPT.txt。

五、遇到矛盾
------------

以实际文件、Git、GitHub Actions、Patch 和 SHA256 为准，记录冲突与证据，不覆盖更新事实，不虚报未知能力。
