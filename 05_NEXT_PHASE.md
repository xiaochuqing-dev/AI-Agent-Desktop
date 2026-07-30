05 下一阶段
============

一、准确名称
------------
审阅并冻结 Control Plane v1 契约，然后实现第一个最小纵向切片。

二、先完成正式评审
------------------
以 architecture/control-plane-v1/README.md 为阅读入口，以 contracts/control-plane-v1/ 下的 OpenAPI 和 JSON Schema 为机器契约。
评审必须解决文档与机器契约的不一致，并为以下四项形成 ADR：
- Control Plane 实现语言与框架
- 事务型元数据与 Operation 存储
- Windows 后台宿主与生命周期所有权
- CredentialBackend 组合

稳定字段正式冻结后，只允许向后兼容地增加可选字段。破坏性变化进入新的 API 或 Provider 合约主版本。

三、第一个最小纵向切片
----------------------
按 architecture/control-plane-v1/09_MIGRATION_AND_FIRST_VERTICAL_SLICE.md 实施：
- 发现本机组件和依赖
- 显示安装、配置、授权、运行、健康和更新状态
- 显示版本、Agent 和 Capability
- 脱敏读取并只读校验配置
- 通过门禁后逐组件接管启动、停止、重启
- 执行无副作用健康检查
- 提供统一脱敏日志、Operation 和用户可理解错误

先完成只读观测，再进行受控 lifecycle 接管。旧启动所有权与 Control Plane 不得形成双 supervisor。

四、完成门禁
------------
- GUI 或验收客户端关闭后后台继续运行
- 相同幂等请求不重复产生副作用
- 状态未知时如实返回 unknown，不伪造正常
- 配置只读校验前后文件哈希不变
- 一个 Adapter 失败不拖垮其他 Provider
- 生命周期接管可恢复旧启动所有权
- src/、5 个 Patch 和 Reference Baseline 回归证据不变
- 不产生真实 Telegram 消息，不读取或输出真实凭据

五、仍然禁止
------------
- 直接开发正式 GUI 或大规模 PySide6 工程
- 新 Channel、新 Runtime、通用 DAG 或第二套消息总线
- 重写 Hermes 或 cc-connect
- 扩大 dual_agent 或 5 个 cc-connect Patch
- 未经门禁接管当前真实生命周期、配置或凭据
- 重启当前服务或重新执行真实 Telegram E2E
- 把未验证的人类控制、讨论或迁移能力标成已实现

PySide6 + Qt Widgets + QSS 是正式 GUI 当前首选方向，但不改变上述实施顺序，也不绑定 Control Plane 的实现语言。
