05 下一阶段
============

一、准确名称
------------

cc-connect 产品管理生命周期与最小配置写入切片。

二、目标
------

在已完成的隔离安装闭环之上，只为产品管理的 cc-connect 实例增加启动、停止、重启、端口所有权和最小配置模板。配置必须使用 SecretRef，不写入真实 Token 或 API Key，并继续保持可审计、可取消和可回滚。

三、进入门禁
------------

- 明确区分 external 与 product 生命周期所有权，禁止双 supervisor。
- 只操作产品自有版本目录，不修改 Reference Baseline、计划任务或 Watchdog。
- 配置写入前完成 revision、备份、原子替换和回滚测试。
- 端口冲突可诊断，健康探针不连接真实 Telegram。
- CredentialBackend 未完成前只允许 SecretRef，不落明文。

四、仍然禁止
------------

- Telegram 三 Bot 自动绑定、真实 User ID/Group ID 获取或六链路真实 E2E
- 其他组件安装、正式 GUI、Provider 编辑器或通用生命周期平台
- 扩大 dual_agent、增加 Patch 或升级 cc-connect 上游
- 静默接管外部进程、修改系统 PATH、计划任务、Watchdog 或真实运行配置
- 读取、输出或提交真实 Secret

五、验收重点
------------

单一生命周期所有者、最小权限、端口与进程身份可证明、配置可回滚、Operation 重启可恢复、Reference Baseline 无回归。
