# Control Plane v1 验收清单

实施状态更新（2026-08-15）：当前已实现 Windows Credential Manager、三 Bot 绑定、真实 Agent Detection、managed/native 分离、合法 Claude/Codex 原生配置、Hermes Telegram Native Configuration、严格 Runtime Readiness 和 `0.4.0-prebeta` PySide6 GUI/Live E2E；新 GUI Telegram 与 Hermes Native Telegram 仍为 `PENDING USER LIVE VALIDATION`，Windows 10 为 `PENDING WINDOWS 10 VALIDATION`，MSI/签名为 `DEFERRED`，整体为 PARTIAL。

状态定义：`PASS` 已通过并有证据；`N/A` 按本轮范围不适用且有原因；`PENDING` 尚待本轮后续验证；`FAIL` 未满足。

## A 事实与范围

| 状态 | 验收项 | 证据 |
|---|---|---|
| PASS | 按正式提示词顺序完整阅读事实源、关键 `src/` 与 5 个 Patch/构建说明 | [设计包关系说明](README.md)、[当前系统映射](08_CURRENT_SYSTEM_ADAPTER_MAPPING.md) |
| PASS | 旧报告和 `history-minimal/` 未作为当前事实覆盖当前文件/Git/SHA | [设计包关系说明](README.md) |
| PASS | 公开仓库独立脱敏历史与私有 Reference Baseline 来源 SHA 的关系未被误判为源码冲突 | [风险说明](10_RISKS_OPEN_DECISIONS_AND_NON_GOALS.md) |
| PASS | `src/` 相对起始 BASE_SHA 零差异 | Git 路径差异验证；[完成报告](../../reports/CONTROL_PLANE_CONTRACT_V1_COMPLETION_REPORT.md) |
| PASS | `integrations/cc-connect/patches/` 相对起始 BASE_SHA 零差异 | Git 路径差异验证；[完成报告](../../reports/CONTROL_PLANE_CONTRACT_V1_COMPLETION_REPORT.md) |
| PASS | 未修改真实配置、计划任务、junction、服务或凭据，未执行真实 Telegram E2E | [映射保护结论](08_CURRENT_SYSTEM_ADAPTER_MAPPING.md) |

## B 设计完整性

| 状态 | 验收项 | 证据 |
|---|---|---|
| PASS | 十分钟首次可用、失败恢复、断点续装与三条配置路线完整 | [用户旅程](01_USER_JOURNEY_AND_ONBOARDING.md) |
| PASS | 日常启动、诊断、更新、回滚和迁移流程完整 | [用户旅程](01_USER_JOURNEY_AND_ONBOARDING.md) |
| PASS | Control Plane 职责、非职责、进程、存储、权限和网络边界完整 | [边界设计](02_CONTROL_PLANE_BOUNDARIES.md) |
| PASS | GUI 与 Control Plane 独立，GUI 关闭后台继续 | [边界设计](02_CONTROL_PLANE_BOUNDARIES.md) |
| PASS | OrchestrationProvider 契约完整 | [Provider 契约](03_PROVIDER_ADAPTER_CONTRACTS.md) |
| PASS | AgentRuntimeProvider 契约完整 | [Provider 契约](03_PROVIDER_ADAPTER_CONTRACTS.md) |
| PASS | ChannelProvider 契约完整 | [Provider 契约](03_PROVIDER_ADAPTER_CONTRACTS.md) |
| PASS | LifecycleProvider 契约完整 | [Provider 契约](03_PROVIDER_ADAPTER_CONTRACTS.md) |
| PASS | ModelConfigurationProvider 契约完整 | [Provider 契约](03_PROVIDER_ADAPTER_CONTRACTS.md) |
| PASS | CredentialProvider 契约完整 | [Provider 契约](03_PROVIDER_ADAPTER_CONTRACTS.md) |
| PASS | CapabilityRegistry 契约完整 | [Provider 契约](03_PROVIDER_ADAPTER_CONTRACTS.md) |
| PASS | HumanControlPolicy 契约完整 | [Provider 契约](03_PROVIDER_ADAPTER_CONTRACTS.md) |
| PASS | 每类契约含职责、能力、操作、状态/错误、幂等、超时/取消、版本与替换映射 | [Provider 契约](03_PROVIDER_ADAPTER_CONTRACTS.md) |
| PASS | 指定核心实体、正交状态、允许转换、聚合和不可逆操作完整 | [领域与状态](04_DOMAIN_AND_STATE_MODELS.md) |
| PASS | 通用模型没有平台专属 Channel 字段或原始消息对象 | [Channel 模型约束](04_DOMAIN_AND_STATE_MODELS.md) |
| PASS | 本地 API 覆盖系统、安装、配置、凭据、Agent、Channel、生命周期、诊断、更新、Task、人类控制和事件 | [API 契约](05_LOCAL_API_AND_EVENT_CONTRACT.md) |
| PASS | HTTP/JSON + SSE 为 v1 默认；WebSocket 排除；IPC 只作未来等价传输 | [API 传输取舍](05_LOCAL_API_AND_EVENT_CONTRACT.md) |
| PASS | Operation、SSE 重连/去重/顺序、幂等、并发、取消和双层错误语义完整 | [API 契约](05_LOCAL_API_AND_EVENT_CONTRACT.md) |
| PASS | 模型配置三条路线、唯一 Owner、交接、备份、回滚和冲突防护完整 | [配置与凭据](06_MODEL_CONFIGURATION_AND_CREDENTIALS.md) |
| PASS | CredentialProvider 保存、受限使用、脱敏、Windows 安全存储和跨机迁移完整 | [配置与凭据](06_MODEL_CONFIGURATION_AND_CREDENTIALS.md) |
| PASS | 插话、暂停、恢复、取消、改派及 Task/ChildTask/Agent 差异完整 | [人类控制](07_HUMAN_CONTROL_AND_CONCURRENCY.md) |
| PASS | 控制竞态、幂等、状态冲突、Channel/API 统一和 Bot 防环完整 | [人类控制](07_HUMAN_CONTROL_AND_CONCURRENCY.md) |
| PASS | 当前 Hermes、cc-connect、Telegram、生命周期与 5 个 Patch 均有真实能力/缺口映射 | [当前系统映射](08_CURRENT_SYSTEM_ADAPTER_MAPPING.md) |
| PASS | 分阶段迁移、回归门禁、回滚点和第一个最小纵向切片完整 | [迁移与首片](09_MIGRATION_AND_FIRST_VERTICAL_SLICE.md) |
| PASS | 风险有触发信号、缓解、决策门禁；开放项有选项与建议 | [风险与开放决策](10_RISKS_OPEN_DECISIONS_AND_NON_GOALS.md) |
| PASS | 开源成熟方案调研有固定快照与取舍，未复制完整平台 | [开源参考](11_OPEN_SOURCE_DESIGN_REFERENCES.md) |

## C 产品原则

| 状态 | 验收项 | 证据 |
|---|---|---|
| PASS | Hermes 默认但通用核心不绑定其内部实现 | [边界设计](02_CONTROL_PLANE_BOUNDARIES.md)、[映射](08_CURRENT_SYSTEM_ADAPTER_MAPPING.md) |
| PASS | cc-connect 是 V1 固定核心桥梁，Patch 有独立锁定与升级门禁 | [当前系统映射](08_CURRENT_SYSTEM_ADAPTER_MAPPING.md) |
| PASS | Claude Code 与 Codex 保持一等 Agent | [Provider 契约](03_PROVIDER_ADAPTER_CONTRACTS.md) |
| PASS | 不重写上游，不做第二套 Runtime、总线或 DAG | [设计包非目标](README.md) |
| PASS | 人类控制最高优先级且不伪造强取消 | [人类控制](07_HUMAN_CONTROL_AND_CONCURRENCY.md) |
| PASS | 每个配置 scope 唯一写入权 | [配置与凭据](06_MODEL_CONFIGURATION_AND_CREDENTIALS.md) |
| PASS | CC Switch 是可选高级入口，不阻塞新手首用 | [配置与凭据](06_MODEL_CONFIGURATION_AND_CREDENTIALS.md) |
| PASS | PySide6 首选已同步到产品决策和宪法，且未污染核心契约 | [最新决策](../../03_LATEST_PRODUCT_DECISIONS.md)、[产品宪法](../../product/PRODUCT_CONSTITUTION.md) |
| PARTIAL | 已实现 Control Plane、cc-connect 隔离安装、最小配置、产品自有生命周期和最小 PySide6 GUI；未实现完整十分钟发布体验、MSI/签名或外部接管 | Git 变更范围与阶段报告 |

## D 安全与公开仓库边界

| 状态 | 验收项 | 证据 |
|---|---|---|
| PASS | Local API 只绑定 loopback，使用高熵 Bearer、Host/Origin 校验，禁止 query token | [API 鉴权](05_LOCAL_API_AND_EVENT_CONTRACT.md) |
| PASS | Secret 与业务配置分离，GUI 和普通日志不取得明文 | [配置与凭据](06_MODEL_CONFIGURATION_AND_CREDENTIALS.md) |
| PASS | 新增/修改文件 Secret、PII、私有路径扫描无真实值命中 | [完成报告](../../reports/CONTROL_PLANE_CONTRACT_V1_COMPLETION_REPORT.md) |
| PASS | 禁入扩展、日志、数据库、Transcript、构建产物未进入 Git | Git 扩展扫描；[完成报告](../../reports/CONTROL_PLANE_CONTRACT_V1_COMPLETION_REPORT.md) |
| PASS | `.gitignore` 与公开文件清单一致 | [公开清单](../../PUBLIC_FILE_MANIFEST.txt)；禁入扩展检查 |

## E 文档与机器契约

| 状态 | 验收项 | 证据 |
|---|---|---|
| PASS | 正式设计目录包含 README、01 至 13 和本清单 | [设计包入口](README.md) |
| PASS | OpenAPI 3.1 可由标准解析器读取并覆盖首片/核心端点 | [OpenAPI](../../contracts/control-plane-v1/control-plane.openapi.yaml)；Redocly 验证 |
| PASS | 事件信封 JSON Schema 可解析并通过正反样例验证 | [事件 schema](../../contracts/control-plane-v1/event-envelope.schema.json)；Draft 2020-12 验证 |
| PASS | 核心模型 JSON Schema 可解析并覆盖 Operation、Component、Agent、状态、Diagnostic | [核心 schema](../../contracts/control-plane-v1/core-models.schema.json)；Draft 2020-12 验证 |
| PASS | 根 README、START_HERE、产品决策、宪法、NEXT_PHASE、下一 Agent 提示词均同步 | 对应仓库文件；阶段旧表述扫描 |
| PASS | GUI 状态与十分钟引导和冻结状态/API 一致，未把设计写成已实现 | [GUI 状态](../../product/GUI_STATUS_EXPERIENCE.md)、[十分钟引导](../../product/TEN_MINUTE_ONBOARDING.md) |
| PASS | Reference Baseline 事实优先级未改变，仅增加架构事实源位置 | [Reference 事实源](../../reference-baseline/SOURCE_OF_TRUTH.md) |
| PASS | 所有仓库内 Markdown 相对链接有效 | 递归相对链接检查 |
| PASS | `PUBLIC_FILE_MANIFEST.txt` 与实际公开文件一致 | [公开清单](../../PUBLIC_FILE_MANIFEST.txt)；以最终主线集合比对为准 |
| PASS | `SHA256SUMS.txt` 覆盖全部公开文件且排除自身 | [SHA256 清单](../../SHA256SUMS.txt)；以最终主线逐文件复算为准 |
| PASS | 16 项完成报告已进入仓库且不含敏感信息 | [完成报告](../../reports/CONTROL_PLANE_CONTRACT_V1_COMPLETION_REPORT.md)；安全扫描 |

## F Git 安全与远端验证

| 状态 | 验收项 | 证据 |
|---|---|---|
| PASS | 起始 `origin/main` BASE_SHA 为 `8a6ba2a130195a82a07fa2bb9c8a54e6f50b8835` | [设计包入口](README.md)；完成报告 |
| PASS | 从最新 `origin/main` 创建 `phase/control-plane-contract-v1` | Git 分支记录 |
| PASS | 提交前 fetch 后 `origin/main` 仍等于 BASE_SHA | Git 安全闸门；[完成报告](../../reports/CONTROL_PLANE_CONTRACT_V1_COMPLETION_REPORT.md) |
| PASS | 阶段提交完成且本地 main 仅用 `--ff-only` 合并 | Git 提交与 first-parent 记录 |
| PASS | 未 force push，正常推送远端 main | 远端 push 与 fetch 记录 |
| PASS | 推送后重新 fetch 并在全新浅克隆验证文件、链接、规范与报告 | 全新 `core.autocrlf=false` 浅克隆验证 |
| PASS | 最终工作区干净 | 最终 `git status` |

## G Telegram 三 Bot 与原生配置切片

| 状态 | 验收项 | 证据 |
|---|---|---|
| PASS | Windows Credential Manager 普通用户 put/replace/status/resolve/delete/metadata/revision，且无明文文件回退 | Windows credential acceptance；[架构切片](13_TELEGRAM_THREE_BOT_AND_NATIVE_CONFIGURATION.md) |
| PASS | managed state 与 fc315d2 原生 TOML 分离，Renderer 不泄漏产品元数据或 Secret | Renderer 测试；[受管边界](12_CC_CONNECT_MANAGED_RUNTIME_BOUNDARIES.md) |
| PASS | 三 Fake getMe 身份唯一、一次性绑定防重放、同一 User/Group 3/3 completed | windows_native_runtime_acceptance.py |
| PASS | 合法 cc-connect 真实进程 start/stop/restart/reconcile、PID/SHA/config/port 和 management Bearer 通过 | windows_native_runtime_acceptance.py |
| PASS | PATH 仅安装不阻塞，目标端口/配置/Supervisor 冲突阻塞，外部状态未修改 | external detector 测试与 Windows 验收 |
| PASS | Hermes 缺失准确 pending_component_install，不阻塞 Claude/Codex；已安装但 Telegram 未配置时仅通过官方公开 `.env`/Gateway 完成 allowlisted 最小配置，并保留 existing/external-first 边界 | Hermes Telegram Adapter 测试与 Windows 合成验收 |
| PENDING | 三个真实 Token 的 getMe、三私聊/三同群 live 绑定 | PENDING USER LIVE VALIDATION |
| PENDING | Windows 10 x64 普通用户打包实机验证 | PENDING WINDOWS 10 VALIDATION |
| PENDING | 新 GUI 私聊/群自动检测真实用户验收 | `PENDING USER LIVE VALIDATION` |
| PENDING | 六链路真实消息 E2E（新 GUI 入口） | 用户显式确认后另行执行；每条最多一条且无自动重试 |
| N/A | 原生 Group Chat 过滤与 deep health | 锁定上游 unsupported；未增加 Patch |

## 当前结论

设计、机器契约、代码、Fake 与 Windows 11 合成安全验证通过；本地 GUI/onboarding/Hermes pytest 通过。新 GUI Telegram live、Hermes Native Telegram live、Windows 10 candidate 验证、MSI/签名仍未完成，阶段整体为 PARTIAL，不得标为 COMPLETE。
