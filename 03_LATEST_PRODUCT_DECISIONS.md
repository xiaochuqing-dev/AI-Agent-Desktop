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

14. 下一阶段先冻结产品架构和 Control Plane 契约，不直接大规模写 GUI。
