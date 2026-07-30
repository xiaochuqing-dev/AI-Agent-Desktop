02 产品愿景
============

一、产品定位
------------
面向个人 AI 开发团队的桌面端安装、配置、管理与协作产品。
不重新开发 Hermes、Claude Code、Codex 或完整 Runtime，而是把成熟能力组合成普通用户十分钟可安装、配置、启动、诊断、升级、回滚和迁移的完整体验。

二、北极星目标
--------------
在基本干净的 Windows 电脑上，普通用户应能在十分钟左右完成:
- 环境检测
- 必要组件安装
- 模型或账号授权
- Telegram 配置
- 首次成功测试
不手工编辑配置文件，不需要理解 AppData、npm 全局目录、环境变量、端口和计划任务。

三、当前真实 Telegram 拓扑
---------------------------
Hermes Bot -> Hermes 自己直连 Telegram
Claude Code Bot -> cc-connect -> Telegram
Codex Bot -> cc-connect -> Telegram

四、产品架构方向
----------------
Desktop GUI -> Local Control Plane -> Provider/Adapter -> Hermes / cc-connect / Claude Code / Codex / Telegram

五、默认组件定位
----------------
- Hermes: 默认智能中枢和 Orchestration Provider
- cc-connect: 当前辅助 Runtime/Telegram 连接层，可被替换
- Claude Code: 一等代码 Agent
- Codex: 一等代码 Agent
- Telegram: 首发 Channel，不是唯一 Channel
- dual_agent: 当前 Fallback，不是永久核心
- cc-connect Patch: 当前兼容层，不得无限扩大

六、长期竞争力
--------------
十分钟安装、统一配置、Secret 安全管理、状态可见、错误可诊断、一键启停重启、更新备份回滚、新电脑迁移、多 Agent 多 Channel 组合体验、人类暂停取消介入改派、美观现代 GUI。

七、不得走偏
------------
不重写 Hermes/Claude Code/Codex、不开发第二套完整 Runtime、不开发第二套消息总线、不把 Control Plane 变通用 DAG、不无限扩大 dual_agent 和 Patch、不锁定 GUI 技术栈、不让 GUI 直接依赖上游内部目录。
