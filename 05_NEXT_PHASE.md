05 下一阶段
============

一、准确名称
------------

Telegram 三 Bot 安全绑定、自动身份发现与配置生成切片。

二、目标
------

在已实现的 cc-connect 配置、SecretRef、所有权、进程身份和端口门禁上，安全录入三个 Bot Token，通过 Telegram getMe 验证身份，使用一次性绑定码发现 User ID 与 Group ID，并生成 Hermes 与 cc-connect 的可回滚配置。

三、进入门禁
------------

- 先确认锁定版 cc-connect 在合法 SecretRef 可用后能持续运行；当前无 Secret 验收只是 PARTIAL。
- 实现可用且不回显明文的 Windows CredentialBackend，并先通过 Fake 和合成凭据测试。
- 保持配置计划、revision、备份、回滚、LifecycleOwner 和 ManagementOwner 门禁。
- 真实 Telegram 操作必须由用户显式启动，记录脱敏证据，不在默认 health 中发消息。
- Windows 10 x64 用户实机验证仍是交付门禁。

四、仍然禁止
------------

- 六链路完整 E2E、正式 GUI、Provider 编辑器或通用生命周期平台
- 其他组件安装、Hermes 自动更新或通用更新器
- 扩大 dual_agent、增加 Patch 或升级 cc-connect 上游
- 静默接管外部进程、修改系统 PATH、计划任务、Watchdog 或真实运行配置
- 读取、输出或提交真实 Secret

五、验收重点
------------

三 Bot 身份唯一，一次性绑定防重放，User/Group ID 自动发现可审计，Secret 不落明文且不回显，生成配置可回滚，三 Bot 同群一致性可验证，Reference Baseline 无回归。
