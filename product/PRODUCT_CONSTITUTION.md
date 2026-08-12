产品宪法 PRODUCT_CONSTITUTION
============================

本文档是本产品的最高约束。任何路线、设计或组件取舍与本宪法冲突时，以本宪法为准。

一、产品定位
------------

面向 Windows 开发者的 Telegram AI 编程团队安装、配置、管理、诊断与恢复中心。

产品价值在于把成熟上游装好、调好、管好：减少配置和首次使用摩擦，降低失败率，统一安装、状态、诊断、更新、回滚与恢复，让用户无需查找配置文件和日志。

二、固定首发范围
----------------

首发平台为 Windows 10/11，首发 Channel 为 Telegram。首发 Agent 为 Hermes、Claude Code、Codex；cc-connect 是 Claude Code/Codex 与 Telegram 的 V1 核心桥梁；CC Switch 是推荐但非强制的供应商配置入口；PySide6 + Qt Widgets + QSS 是当前最小 GUI 实现。

用户可见三个 Bot：Hermes Bot、Claude Code Bot、Codex Bot。产品目标固定为 Hermes、Claude Code、Codex 各自私聊与群聊共六条链路。

三、Integration First
---------------------

不重新开发 Hermes、Claude Code、Codex 或 cc-connect，不开发替代 cc-connect 的通用 Telegram Bridge，不重复开发完整 Provider 管理器。优先通过 Adapter、受控调用、只读发现、配置所有权、深链接和生命周期管理集成熟上游。

上游不具备的能力不得由 Adapter 虚报为 available。每个配置作用域同一时刻只能有一个 ManagementOwner，本产品与 CC Switch 不得同时写同一作用域。

四、组件职责
------------

- Hermes：编排中枢与 Hermes Bot 运行主体。
- Claude Code：独立编码 Agent。
- Codex：独立编码 Agent。
- cc-connect：Claude Code/Codex 与 Telegram 的核心桥接和 Project/Session 承载。
- CC Switch：推荐的供应商、模型和 API 配置入口，非新手强制依赖。
- Control Plane：安装、发现、配置权、状态、生命周期、诊断、更新、回滚与统一操作。
- GUI：当前最小实现只通过 Control Plane 契约工作，不直接写上游私有配置；关闭 GUI 不停止后台。

五、未来用户职责与自动化
----------------------

用户未来只需提供模型账号或 API 凭据，创建三个 Bot 并粘贴 Token，创建群聊并加入三个 Bot，完成 Telegram 官方必须由用户执行的少量操作，例如首次 /start 与权限设置，然后点击 GUI 的配置或验证按钮。

产品未来自动识别 Bot、验证 Token、获取 User ID 与 Group/Chat ID、建立绑定和白名单、生成 Hermes 与 cc-connect 配置、创建 cc-connect Project、处理端口/Hook/Session/后台启动、检测六条链路并提供修复。

六、当前实现边界
----------------

Control Plane 基础运行代码已存在，当前已实现只读发现、三个真实 Agent Detector、Readiness、Dry-run、持久化 OperationExecutor/SSE、脱敏诊断、Windows Credential Manager、三 Bot 身份与一次性绑定、Update Lease、Claude/Codex 原生配置生成与回滚，以及严格的 cc-connect 受管 Runtime Readiness。PySide6 `0.3.0-prebeta` 四步 GUI、Dashboard、Diagnostics、QR、Telegram 深链接和用户确认 Live E2E 也已实现；真实 Telegram 用户尚未复测新 GUI，状态为 `PENDING USER LIVE VALIDATION`，Windows 10 为 `PENDING WINDOWS 10 VALIDATION`，MSI/签名为 `DEFERRED`。第五节仍是完整产品目标，不得把合成证据写成真实 Telegram、认证状态或 Hermes 已受管验证。

七、不得走偏
------------

不重写上游，不新增其他 Channel 或 Agent Runtime，不开发通用 DAG、工作流市场、插件市场或第二套消息总线，不无限扩大 dual_agent 和 cc-connect Patch，不让 GUI 直接依赖上游内部目录。

范围细节见 TELEGRAM_AI_CODING_TEAM_SCOPE.md，集成规则见 INTEGRATION_FIRST_POLICY.md，运行边界见 TELEGRAM_KNOWN_LIMITATIONS.md。
