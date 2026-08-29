03 最新产品决策
================

更新时间：2026-08-30

1. 产品正式定位为“面向 Windows 开发者的 Telegram AI 编程团队安装、配置、管理、诊断与恢复中心”。
2. 首发平台固定为 Windows 10/11，首发 Channel 固定为 Telegram，本阶段不扩展其他渠道。
3. 用户可见三个 Bot：Hermes Bot、Claude Code Bot、Codex Bot；产品目标固定为三者各自私聊和群聊共六条链路。
4. Hermes 是编排中枢与 Hermes Bot 运行主体；Claude Code 和 Codex 是独立编码 Agent。
5. cc-connect 是 V1 中 Claude Code/Codex 与 Telegram 的核心桥梁及 Project/Session 承载，不再标记为可随意替换的辅助层。
6. CC Switch 是推荐但非强制的供应商、模型和 API 配置入口，不进入新手必选条件。
7. 采用 Integration First：不重写 Hermes、Claude Code、Codex、cc-connect，不自研替代桥梁或完整 Provider 管理器。
8. 每个配置作用域同一时刻只能有一个 ManagementOwner；本产品与 CC Switch 不得同时写同一作用域。
9. GUI 与 Control Plane 独立；当前 PySide6 GUI 只调用稳定契约，不直接读写上游私有配置。
10. 最小正式 GUI 已采用 PySide6 + Qt Widgets + QSS；旧 Tk 验收向导仍只作为历史自包含验证入口，不等同于新 GUI 的 live 验收。
11. Control Plane v1 契约和四项 ADR 已冻结，基础运行代码已经存在。
12. 当前能力包含只读发现、Readiness、Dry-run、持久化 OperationExecutor/SSE、脱敏诊断，以及 cc-connect 锁定产物隔离安装、原生配置 revision/回滚、所有权交接和产品管理生命周期。
13. 找到可执行文件、配置文件或 Token 引用均不足以证明运行、配置有效、认证有效或健康；没有直接证据时返回 unknown。
14. CC Switch 只允许公开边界上的可执行文件检测和普通打开；安装、更新、配置和所有权交接无稳定证据时为 unknown，不读取其私有数据或 Secret。
15. 产品管理元数据与 cc-connect 原生运行配置必须永久分离；前者保存 Owner、revision、凭据引用和证据，后者只写锁定上游支持的 Project、Agent、Platform 与 Secret 占位符。Renderer 身份必须绑定精确 artifact 与 source SHA。
16. Telegram 命令与 Session 隔离问题登记为非阻断已知限制，后续依靠可观测性和测试矩阵修复，本阶段不重构现有路由。
17. Bot Token 固定保存在 Windows Credential Manager；API、Operation、SSE、日志、SQLite、命令行和原生配置不得保存或回显明文，Python 无法保证物理内存完全清零必须如实说明。
18. 同一个 Bot Token 同时只能有一个 Update Stream Owner；绑定前 runtime 必须停止，Control Plane 只在显式绑定 Operation 中临时 getUpdates，并在完成、取消、失败或超时后释放 Lease。
19. 三 Bot 身份、User ID、Group ID 和 3/3 一致性已通过 Fake Telegram 合成验收；2026-08-07 用户直接在 Telegram 验证六条私聊/群聊链路并明确通过。两类证据保持分开，用户体验通过不能反推不存在的向导 getMe、3/3 或 correlation 记录。
20. PATH 中仅安装外部 cc-connect 不阻塞产品实例；目标端口、相同配置作用域或外部 Supervisor 冲突才硬阻塞，证据不足返回 unknown。
21. 锁定上游原生配置不支持 Group Chat 白名单字段，management API 只能监听所有网卡，deep health 也无官方端点；这些能力保持 unsupported/partial，不增加 Patch。
22. Hermes 未安装时仍准确标记 pending_component_install；Hermes 已安装但 Telegram 未配置时，Control Plane 可通过 Hermes 官方公开配置面完成最小 Telegram 配置和 Gateway 生命周期；Provider、Model、Tool 和其它配置仍由 Hermes/外部工具管理。
23. 六链路可观测性、一次性 E2E 计划、自包含验收向导和最小 PySide6 GUI 已实现。旧入口六条真实用户体验链路仍记为历史 `LIVE_VERIFIED`；新 GUI 私聊激活与群自动检测必须单独由用户复测，状态为 `PENDING USER LIVE VALIDATION`。
24. `0.4.1-prebeta` Windows candidate 已在 Windows 11 x64 构建并通过本地候选验证器与普通用户 smoke；Windows 10 为 `PENDING WINDOWS 10 VALIDATION`，MSI/正式安装器/签名为 `DEFERRED`。
25. Hermes 采用 external-first 配置边界：已有配置绝不静默覆盖；仅对已安装且 Telegram 未配置或用户明确确认切换的场景写入官方 `.env`，并使用官方 Gateway 生命周期。新 Hermes Telegram live 仍为 `PENDING USER LIVE VALIDATION`。
26. 当前收口工作继续保持 Integration First 和唯一 ManagementOwner，下一步只做用户验证、候选包验证和文档证据，不扩展 Agent、Channel，也不继续升级或增加上游 Patch。
27. 用户可直接在 Telegram 做最终体验验收；若未使用向导，报告只能记录用户确认与只读日志元数据，不能生成或补写 Control Plane 结构化 live 证据。
28. Agent installed/healthy 必须来自产品自己的 detector，不再由 Telegram Bot Identity 推断；Agent installed 不等于 authenticated。Claude/Codex connected 仅在 detector acceptable 且严格 Runtime Ready 时为 true；Hermes Telegram readiness 与 Agent Provider 状态分开显示。
29. Agent discovery 必须按 PATH 目录顺序和安全 known locations 解析 Windows wrapper/executable；版本探测使用官方 `--version`、shell=False、短 timeout、无 stdin、无控制台、受限输出和敏感环境清理，不写死版本。
30. Step 4 只有在 cc-connect PID、exe、configuration revision、port owner、startup stability 等证据同时满足时才完成；Binding、ready_for_test、LIVE_VERIFIED 和 stale 必须分开显示。
31. GUI 真实 Live E2E 必须弹出用户确认，六条链路每条最多发送一次且不自动重试；用户可跳过，自动化和 Demo 不能升级为 LIVE_VERIFIED。
32. CC Switch 继续可选。Agent Detection 仅参考其公开成熟策略重新实现，参考 upstream `1f38c83826a8bca3c1a7a18d9629f05a914718fd`、MIT；未复制第三方代码，不新增第三方 License 文件。
33. 产品受管 cc-connect 固定升级到 Stable `v1.5.0`、source `17c61062c2f9ce9bcdd45a2082e491f9743a2770`、patchset `0.2`。Patch 001–004 保留并重放，Patch 005 因上游已吸收而退役；制品锁同时固定 ID、版本、SHA256、字节数、Manifest 与 Renderer 证据。
34. 升级切换必须先停止产品受管进程，安装新旧版本并存，生成绑定新 artifact 的原生配置 revision，再启动并核验严格证据；失败时恢复旧 current 指针、旧配置 revision 与旧进程。外部 cc-connect 不在该事务范围内。
