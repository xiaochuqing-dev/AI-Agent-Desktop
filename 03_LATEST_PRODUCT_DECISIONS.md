03 最新产品决策
================

更新时间：2026-08-04

1. 产品正式定位为“面向 Windows 开发者的 Telegram AI 编程团队安装、配置、管理、诊断与恢复中心”。
2. 首发平台固定为 Windows 10/11，首发 Channel 固定为 Telegram，本阶段不扩展其他渠道。
3. 用户可见三个 Bot：Hermes Bot、Claude Code Bot、Codex Bot；产品目标固定为三者各自私聊和群聊共六条链路。
4. Hermes 是编排中枢与 Hermes Bot 运行主体；Claude Code 和 Codex 是独立编码 Agent。
5. cc-connect 是 V1 中 Claude Code/Codex 与 Telegram 的核心桥梁及 Project/Session 承载，不再标记为可随意替换的辅助层。
6. CC Switch 是推荐但非强制的供应商、模型和 API 配置入口，不进入新手必选条件。
7. 采用 Integration First：不重写 Hermes、Claude Code、Codex、cc-connect，不自研替代桥梁或完整 Provider 管理器。
8. 每个配置作用域同一时刻只能有一个 ManagementOwner；本产品与 CC Switch 不得同时写同一作用域。
9. GUI 与 Control Plane 独立；GUI 未来只调用稳定契约，不直接读写上游私有配置。
10. 正式 GUI 未来首选 PySide6 + Qt Widgets + QSS，本阶段不实现 GUI。
11. Control Plane v1 契约和四项 ADR 已冻结，基础运行代码已经存在。
12. 当前能力包含只读发现、Readiness、Dry-run、持久化 OperationExecutor/SSE、脱敏诊断，以及 cc-connect 锁定产物隔离安装、原子配置 revision/回滚、所有权交接和产品管理生命周期。
13. 找到可执行文件、配置文件或 Token 引用均不足以证明运行、配置有效、认证有效或健康；没有直接证据时返回 unknown。
14. CC Switch 只允许公开边界上的可执行文件检测和普通打开；安装、更新、配置和所有权交接无稳定证据时为 unknown，不读取其私有数据或 Secret。
15. cc-connect 最小非敏感配置和生命周期机制已实现；上游要求至少一个 Project 和 Platform，Telegram-disabled、无 Secret 配置无法满足前提，故真实持续运行验收为 PARTIAL，不等同于完整健康。
16. Telegram 命令与 Session 隔离问题登记为非阻断已知限制，后续依靠可观测性和测试矩阵修复，本阶段不重构现有路由。
17. 真实凭据写入、Telegram 自动绑定、六链路自动验收和 GUI 尚未实现；Windows 10 x64 待用户实机验证。
18. 下一阶段固定为“Telegram 三 Bot 安全绑定、自动身份发现与配置生成切片”，不直接跳到 GUI。
