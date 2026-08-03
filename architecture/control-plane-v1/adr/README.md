ADR 索引
========

本目录记录 Control Plane v1 实现阶段需要正式冻结的实现决策。每份 ADR 必须包含:状态、日期、上下文、决策、替代方案、后果、回退条件、未来重审触发器。

状态取值:Proposed(提案)、Accepted(已接受)、Frozen(已冻结)、Superseded(被取代)、Deprecated(已弃用)。

已冻结决策
----------

ADR-001 Control Plane 实现语言与 Web/API 框架
  状态: Accepted / Frozen
  日期: 2026-07-31
  文件: ADR-001-implementation-language-and-api-framework.md

ADR-002 Operation、事件与事务型状态的持久化方案
  状态: Accepted / Frozen
  日期: 2026-07-31
  文件: ADR-002-operation-state-and-event-persistence.md

ADR-003 Windows 后台宿主与生命周期所有权
  状态: Accepted / Frozen
  日期: 2026-07-31
  文件: ADR-003-windows-background-host-and-lifecycle-ownership.md

ADR-004 CredentialBackend 组合与 Secret 边界
  状态: Accepted / Frozen
  日期: 2026-07-31
  文件: ADR-004-credential-backend-and-secret-boundary.md

与契约的关系
------------

本目录的 ADR 只冻结实现技术决策,不改写 architecture/control-plane-v1/ 下已冻结的设计事实源,也不改写 contracts/control-plane-v1/ 下的机器契约。若实现需要契约向后兼容增量(新增端点、事件类型、模型字段),按 05_LOCAL_API_AND_EVENT_CONTRACT.md 的版本策略与 ADR 程序单独记录,不在 ADR 中混入契约变更。

冻结边界
--------

四项 ADR 在首片编码前必须完成,是 09_MIGRATION_AND_FIRST_VERTICAL_SLICE.md 阶段 1 进入条件“实现技术决策记录完成”的满足依据。Frozen 状态表示本轮不再讨论方向,只允许按“未来重审触发器”重新打开。
