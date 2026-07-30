03 最新产品决策
================

生成时间: 2026-07-30

1. 产品是桌面端应用，但内部不是单体 GUI。GUI 和本地 Control Plane 分离。

2. GUI 未来只依赖我们的稳定 API，不直接依赖 Hermes 或 cc-connect 内部目录和对象。

3. Hermes 是默认主体系统（Orchestration Provider）。

4. cc-connect 当前非常重要，但长期可由 Hermes 原生能力替代。

5. Hermes 自己直连 Telegram（不经 cc-connect）。

6. Claude Code 和 Codex 当前通过 cc-connect 连 Telegram。

7. Hermes 的基础模型配置必须由本应用原生支持。

8. Claude Code / Codex 必须支持官方登录引导、状态检测和基础 API 配置。

9. CC Switch 只作为可选的高级模型供应商管理入口。

10. CC Switch 不能成为新手首次安装的强制依赖。

11. 每个工具只能有一个配置管理权: 本应用 / 官方登录 / CC Switch / 外部管理。

12. 本应用与 CC Switch 不得同时写同一份配置。

13. GUI 状态不只在线/离线，至少包括:
    未安装、已安装未配置、需要登录、配置无效、正在启动、运行正常、部分能力异常、更新可用、启动失败、已停止。

14. Control Plane v1 设计包和机器可读契约已经形成；下一阶段先正式审阅并冻结，再实现第一个最小纵向切片，不直接大规模写 GUI。

15. 正式 GUI 当前首选 PySide6 + Qt Widgets + QSS，可使用受控视觉资源、主题和克制动画，但本轮没有实现 GUI。

16. GUI 与 Control Plane 必须是独立进程。关闭 GUI 只断开客户端，不能停止 Control Plane 或后台 Agent/Channel 服务。

17. 选择 PySide6 不代表 Control Plane 必须使用 Python。领域模型、Provider 契约和本地 API 不依赖 QWidget 或任何 GUI 框架。

18. Control Plane v1 默认本地协议为 127.0.0.1 HTTP/JSON，事件使用 SSE；WebSocket 不进入 v1，IPC 仅保留未来等价传输边界。

19. 变更操作采用 Operation、Idempotency-Key 和 revision；取消必须区分请求已接受与外部工作已确认终止。

20. 第一个最小纵向切片只包装当前体系，不实现新 Runtime、新 Channel、通用 DAG、复杂讨论或正式 GUI。
