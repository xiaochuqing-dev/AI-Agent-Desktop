# Control Plane v1 正式设计包

## 文档状态

- 设计版本：`1.0.0`
- 契约状态：已正式冻结；标记为 `experimental` 或 `draft` 的条目除外
- 适配基准：`v0.1-reference-baseline`，基线来源 HEAD 为 `cd3493b191fdc19114e0ae037746ab3d23a58a79`
- 公开仓库起始基线：`8a6ba2a130195a82a07fa2bb9c8a54e6f50b8835`
- 实现决策：ADR-001..004 已冻结（见 `adr/`）
- 实现状态：Control Plane 已完成 cc-connect 隔离安装、Windows Credential Manager、三 Bot 身份/绑定、三个真实 Agent Detector、Update Lease、managed/native 分离、Claude/Codex 原生配置、Hermes Telegram Native Configuration、严格 Runtime Readiness 和受管生命周期；`0.4.1-prebeta` GUI 已实现。产品受管 cc-connect 已精确升级到 Stable v1.5.0 source `17c61062c2f9ce9bcdd45a2082e491f9743a2770`；新 GUI Telegram 与 Hermes Native Telegram 为 `PENDING USER LIVE VALIDATION`，Windows 10 为 `PENDING WINDOWS 10 VALIDATION`，MSI/签名为 `DEFERRED`，整体为 PARTIAL

本设计包把 Local Control Plane 定义为安装、配置、状态、生命周期、能力与人类控制的统一管理层。它不是新的 Agent Runtime、消息总线、通用 DAG 或智能编排大脑。

## 阅读顺序

1. [01 用户旅程与十分钟引导](01_USER_JOURNEY_AND_ONBOARDING.md)
2. [02 Control Plane 边界](02_CONTROL_PLANE_BOUNDARIES.md)
3. [03 Provider 与 Adapter 契约](03_PROVIDER_ADAPTER_CONTRACTS.md)
4. [04 领域与状态模型](04_DOMAIN_AND_STATE_MODELS.md)
5. [05 本地 API 与事件契约](05_LOCAL_API_AND_EVENT_CONTRACT.md)
6. [06 模型配置与凭据](06_MODEL_CONFIGURATION_AND_CREDENTIALS.md)
7. [07 人类控制与并发](07_HUMAN_CONTROL_AND_CONCURRENCY.md)
8. [08 当前系统 Adapter 映射](08_CURRENT_SYSTEM_ADAPTER_MAPPING.md)
9. [09 迁移与第一个最小纵向切片](09_MIGRATION_AND_FIRST_VERTICAL_SLICE.md)
10. [10 风险、开放决策与非目标](10_RISKS_OPEN_DECISIONS_AND_NON_GOALS.md)
11. [11 开源成熟方案取舍](11_OPEN_SOURCE_DESIGN_REFERENCES.md)
12. [cc-connect 受管运行与可升级边界](12_CC_CONNECT_MANAGED_RUNTIME_BOUNDARIES.md)
13. [Telegram 三 Bot 与原生配置切片](13_TELEGRAM_THREE_BOT_AND_NATIVE_CONFIGURATION.md)
14. [验收清单](ACCEPTANCE_CHECKLIST.md)

机器可读入口：

- [OpenAPI 3.1 契约](../../contracts/control-plane-v1/control-plane.openapi.yaml)
- [统一事件信封 JSON Schema](../../contracts/control-plane-v1/event-envelope.schema.json)
- [核心模型 JSON Schema](../../contracts/control-plane-v1/core-models.schema.json)
- [受管运行 JSON Schema](../../contracts/control-plane-v1/managed-runtime.schema.json)

## 与现有事实源的关系

本设计包细化现有需求，不覆盖运行事实。事实冲突时优先级仍为：实际文件、Git、Patch 与 SHA256；当前运行配置和真实 E2E；根目录与 `reference-baseline/` 文档；历史摘要。

需求输入：

- [Control Plane 需求](../CONTROL_PLANE_REQUIREMENTS.md)
- [Provider 契约需求](../PROVIDER_CONTRACT_REQUIREMENTS.md)
- [Channel 模型需求](../CHANNEL_MODEL_REQUIREMENTS.md)
- [人类控制需求](../HUMAN_CONTROL_REQUIREMENTS.md)
- [模型配置需求](../MODEL_CONFIGURATION_PROVIDER_REQUIREMENTS.md)
- [凭据需求](../CREDENTIAL_PROVIDER_REQUIREMENTS.md)

运行事实输入：

- [当前运行源码映射](../../CURRENT_RUNTIME_SOURCE_MAP.md)
- [Reference Baseline 事实源](../../reference-baseline/SOURCE_OF_TRUTH.md)
- [Reference Baseline E2E](../../reference-baseline/E2E_VALIDATION.md)

`src/` 与 `integrations/cc-connect/patches/` 是当前参考实现证据。本设计只从外部定义 Adapter，不修改或重新解释它们。

## 已冻结项

1. GUI、Control Plane、Adapter 与外部组件采用单向依赖；GUI 只能调用稳定本地 API。
2. GUI 与 Control Plane 是独立进程；GUI 退出只断开客户端连接，后台不随之停止。
3. 默认传输为 loopback HTTP/JSON；实时事件使用同一服务上的 SSE。WebSocket 不作为 v1 默认，IPC 仅保留等价传输映射。
4. 变更类请求使用异步 `Operation`、`Idempotency-Key` 与明确取消语义。
5. 事件信封采用 CloudEvents 1.0 核心属性，并增加本地顺序、纪元与资源版本扩展。
6. 八类正式契约为 OrchestrationProvider、AgentRuntimeProvider、ChannelProvider、LifecycleProvider、ModelConfigurationProvider、CredentialProvider、CapabilityRegistry、HumanControlPolicy。
7. Provider 能力显式声明并协商版本；未知或不支持能力必须返回 `unsupported`，不得静默降级。
8. 安装、配置、授权、运行、健康与更新状态正交保存，再聚合成用户状态。
9. 每个配置作用域同一时刻仅有一个 `ManagementOwner`；切换使用备份、版本比较和两阶段交接，禁止双写窗口。
10. 凭据与业务配置分离；GUI 不读取明文 Secret，Secret 不出现在 URL、普通日志、事件或错误详情中。
11. 人类指令优先级最高；取消是可确认的异步请求，不虚假承诺瞬时终止外部进程。
12. Readiness、Agent Detection、cc-connect 隔离安装、合法原生配置与产品自有生命周期已实现；Telegram 只限三个固定 Bot slot、显式绑定和用户确认六链路 E2E，GUI 只消费本地契约，其他组件安装与外部生命周期仍不在当前范围。

## 未冻结项

以下条目不阻塞契约评审。前四项已由 ADR-001..004 冻结（见 `adr/`），其余为开放实现参数，须在首片原型中测量并记录：

- Control Plane 实现语言与框架 — 已由 ADR-001 冻结
- 元数据存储引擎的最终选择 — 已由 ADR-002 冻结（SQLite WAL + SQLAlchemy 2 + Alembic）
- Windows 后台宿主采用登录启动项、计划任务还是用户服务 — 已由 ADR-003 冻结（本阶段前台进程，不接管生命周期）
- Windows Credential Manager 与 DPAPI 封装的最终实现组合 — 小型 Bot/内部 Token 已实测采用 keyring 的 Windows WinVault 后端；结构化大凭据是否需要 DPAPI vault 仍开放
- loopback 端口分配与事件保留窗口的具体默认值
- Provider 是否在后续版本支持进程外插件；v1 不实现通用插件装载器
- 讨论模式与外部 Runtime 能否提供强暂停、强取消的能力等级

## 当前实现的明确非目标

- 不在当前切片实现其他组件安装、外部生命周期接管、六链路真实消息 E2E、MSI/正式安装器或代码签名；PySide6 最小 GUI 已实现但仍处于候选和用户验证阶段
- 不新增 Channel 或 Runtime
- 不重写 Hermes、Claude Code、Codex 或 cc-connect
- 不扩大 dual_agent，也不在 v1.5.0 已收敛的 Patch 001–004 之外增加 Patch
- 不定义通用 DAG、低代码工作流、插件市场或分布式控制平面
- 不把当前 Adapter 私有字段写入通用模型
- 不修改、重启、停止或测试当前在线系统

## 契约变更规则

`v1` 稳定字段只允许向后兼容地新增可选字段或新能力。删除字段、改变既有语义、收紧已发布枚举或改变幂等行为属于破坏性变更，必须进入 `/api/v2` 或新的 Provider 合约主版本。实验字段必须带 `x-stability: experimental`、`maturity: experimental` 或文档中的同等标记，不能被 GUI 当成必需能力。
