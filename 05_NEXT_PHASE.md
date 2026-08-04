05 下一阶段
============

一、准确名称
------------

六链路可观测性、真实消息 E2E 与会话隔离修复切片。

二、目标
------

在安全凭据、三 Bot 绑定、Update Lease 和 Claude/Codex 原生配置已经完成的基础上，为三个私聊与三个群聊建立脱敏可观测性，并由用户显式启动真实消息 E2E，定位和修复命令、Mention、Reply、Topic 与 Session 隔离问题。

三、进入门禁
------------

- 用户显式提供三个真实测试 Bot Token，并分别完成 getMe；真实 Token 不进入仓库、日志、报告或命令行。
- 三个 Bot 由同一用户完成私聊与同一群绑定，真实状态达到 3/3 bound；Fake 合成结果不能代替。
- Claude/Codex 产品受管进程在真实 Token 下稳定运行，Update Lease 所有权无冲突，原生配置仍可回滚。
- Hermes 必须有明确状态：已安装且 Schema 可验证，或继续准确 pending_component_install。
- Windows 10 x64 用户实机验证单独完成；Windows 11 证据不能替代。

四、仍然禁止
------------

- 默认或无人确认的六链路 E2E、正式 GUI、Provider 编辑器或通用生命周期平台
- 其他组件安装、Hermes 自动更新或通用更新器
- 扩大 dual_agent、增加 Patch 或升级 cc-connect 上游
- 静默接管外部进程、修改系统 PATH、计划任务、Watchdog 或真实运行配置
- 读取、输出或提交真实 Secret

五、验收重点
------------

六条链路逐条记录连接、发送、接收、命令、Mention、Reply、Topic、Session 隔离、最近验证时间和脱敏证据；不得用一条链路推断另一条。真实消息只在用户确认的会话中发送一次，失败不自动重复。修复仍需保持 Reference Baseline、凭据、Update Lease、原生配置和外部环境边界。
