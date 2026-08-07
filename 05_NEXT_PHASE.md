05 下一阶段
============

一、准确名称
------------

最小 GUI、十分钟 Onboarding 与 Windows 自包含分发切片。

二、目标
------

在六链路可观测性、一次性 E2E 计划、自包含验收向导和用户 Telegram 真实体验验收已经完成的基础上，提供最小正式 GUI、十分钟首次可用流程、状态面板、一键诊断、有限修复以及可回滚的 Windows 分发入口。

三、进入门禁
------------

- 六条 Telegram 用户体验链路维持 LIVE_VERIFIED；行为变化后必须重新请用户验收。
- Windows 10 x64 用户实机验证单独完成；Windows 11 证据不能替代。
- 如要把直接 Telegram 验收升级为机器可审计证据，必须另行完成真实 getMe、3/3 绑定和 correlation 流程，Token 不进入仓库、日志、报告或命令行。
- Claude/Codex 产品受管进程、Update Lease 和配置回滚保持稳定；Hermes 继续作为 external runtime，不静默接管。

四、仍然禁止
------------

- 默认或无人确认的六链路 E2E、Provider 编辑器或通用生命周期平台
- 其他组件安装、Hermes 自动更新或通用更新器
- 扩大 dual_agent、增加 Patch 或升级 cc-connect 上游
- 静默接管外部进程、修改系统 PATH、计划任务、Watchdog 或真实运行配置
- 读取、输出或提交真实 Secret

五、验收重点
------------

GUI 必须直接调用稳定 Control Plane 契约，不读取上游私有数据库或 Secret；状态、失败恢复和回滚需可解释。真实消息仍只在用户确认的会话中发送一次，失败不自动重复。正式分发需保持 Reference Baseline、凭据、Update Lease、原生配置和外部环境边界，并补齐 Windows 10 实机证据。
