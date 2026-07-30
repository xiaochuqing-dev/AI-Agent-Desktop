05 下一阶段
============

一、目标
--------
独立 Control Plane 与 Provider/Adapter 契约设计。
先形成正式产品级设计，不直接大规模编码。

二、第一轮产出
--------------
- 产品用户流程（十分钟安装全流程）
- Provider 能力边界（Orchestration/AgentRuntime/Channel/Lifecycle/CapabilityRegistry/HumanControl）
- 通用数据模型（Agent/Capability/Task/Conversation/Message/Channel）
- Control Plane API 契约
- ModelConfigurationProvider 与 CredentialProvider 边界
- GUI 状态模型和十分钟安装流程
- 当前参考实现向 Adapter 体系迁移的分阶段计划

三、第一轮禁止
--------------
- 直接开发完整 GUI
- 锁定 GUI 技术栈（PySide6/Tauri/Electron/Web）
- 重写 Hermes 或 cc-connect
- 开发第二套完整 Runtime 或消息总线
- 通用 DAG
- 继续扩大 dual_agent 和 cc-connect Patch
- 接入新渠道
- 升级上游组件
- 修改当前运行环境
- 重启服务

四、见 architecture/ 目录
-------------------------
Control Plane 与各 Provider 契约需求已写在 architecture/ 下 6 份文档。
先输出契约设计方案，等用户确认后再进入代码阶段。
