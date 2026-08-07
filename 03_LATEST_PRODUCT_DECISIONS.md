03 最新产品决策
================

更新时间：2026-08-07

1. 产品正式定位为“面向 Windows 开发者的 Telegram AI 编程团队安装、配置、管理、诊断与恢复中心”。
2. 首发平台固定为 Windows 10/11，首发 Channel 固定为 Telegram，本阶段不扩展其他渠道。
3. 用户可见三个 Bot：Hermes Bot、Claude Code Bot、Codex Bot；产品目标固定为三者各自私聊和群聊共六条链路。
4. Hermes 是编排中枢与 Hermes Bot 运行主体；Claude Code 和 Codex 是独立编码 Agent。
5. cc-connect 是 V1 中 Claude Code/Codex 与 Telegram 的核心桥梁及 Project/Session 承载，不再标记为可随意替换的辅助层。
6. CC Switch 是推荐但非强制的供应商、模型和 API 配置入口，不进入新手必选条件。
7. 采用 Integration First：不重写 Hermes、Claude Code、Codex、cc-connect，不自研替代桥梁或完整 Provider 管理器。
8. 每个配置作用域同一时刻只能有一个 ManagementOwner；本产品与 CC Switch 不得同时写同一作用域。
9. GUI 与 Control Plane 独立；GUI 未来只调用稳定契约，不直接读写上游私有配置。
10. 正式 GUI 未来首选 PySide6 + Qt Widgets + QSS；当前 Tk 验收向导只是自包含验证入口，不等同于正式产品 GUI。
11. Control Plane v1 契约和四项 ADR 已冻结，基础运行代码已经存在。
12. 当前能力包含只读发现、Readiness、Dry-run、持久化 OperationExecutor/SSE、脱敏诊断，以及 cc-connect 锁定产物隔离安装、原生配置 revision/回滚、所有权交接和产品管理生命周期。
13. 找到可执行文件、配置文件或 Token 引用均不足以证明运行、配置有效、认证有效或健康；没有直接证据时返回 unknown。
14. CC Switch 只允许公开边界上的可执行文件检测和普通打开；安装、更新、配置和所有权交接无稳定证据时为 unknown，不读取其私有数据或 Secret。
15. 产品管理元数据与 cc-connect 原生运行配置必须永久分离；前者保存 Owner、revision、凭据引用和证据，后者只写锁定上游支持的 Project、Agent、Platform 与 Secret 占位符。
16. Telegram 命令与 Session 隔离问题登记为非阻断已知限制，后续依靠可观测性和测试矩阵修复，本阶段不重构现有路由。
17. Bot Token 固定保存在 Windows Credential Manager；API、Operation、SSE、日志、SQLite、命令行和原生配置不得保存或回显明文，Python 无法保证物理内存完全清零必须如实说明。
18. 同一个 Bot Token 同时只能有一个 Update Stream Owner；绑定前 runtime 必须停止，Control Plane 只在显式绑定 Operation 中临时 getUpdates，并在完成、取消、失败或超时后释放 Lease。
19. 三 Bot 身份、User ID、Group ID 和 3/3 一致性已通过 Fake Telegram 合成验收；2026-08-07 用户直接在 Telegram 验证六条私聊/群聊链路并明确通过。两类证据保持分开，用户体验通过不能反推不存在的向导 getMe、3/3 或 correlation 记录。
20. PATH 中仅安装外部 cc-connect 不阻塞产品实例；目标端口、相同配置作用域或外部 Supervisor 冲突才硬阻塞，证据不足返回 unknown。
21. 锁定上游原生配置不支持 Group Chat 白名单字段，management API 只能监听所有网卡，deep health 也无官方端点；这些能力保持 unsupported/partial，不增加 Patch。
22. Hermes 未安装时仍准确标记 pending_component_install；当前机器已观测到 Hermes external runtime，但 Control Plane 不接管其 Provider、配置或生命周期。
23. 六链路可观测性、一次性 E2E 计划和自包含验收向导已实现；六条真实用户体验链路已通过。正式 GUI 尚未实现，Windows 10 x64 为 PENDING WINDOWS 10 VALIDATION。
24. 下一阶段固定为“最小 GUI、十分钟 Onboarding 与 Windows 自包含分发切片”，继续保持 Integration First 和唯一 ManagementOwner。
25. 用户可直接在 Telegram 做最终体验验收；若未使用向导，报告只能记录用户确认与只读日志元数据，不能生成或补写 Control Plane 结构化 live 证据。
