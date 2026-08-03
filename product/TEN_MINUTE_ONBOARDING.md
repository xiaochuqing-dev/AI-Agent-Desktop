十分钟安装引导 TEN_MINUTE_ONBOARDING
====================================

本文档描述正式产品目标，不表示安装器、Telegram 自动绑定或 GUI 已实现。

一、用户准备
------------

用户准备受支持的 Windows 10/11、模型账号或 API 凭据，创建 Hermes Bot、Claude Code Bot、Codex Bot 并粘贴三个 Token，创建群聊并加入三个 Bot，完成 Telegram 官方必须由用户执行的首次 /start 与必要权限设置。

用户不手工填写 User ID、Group/Chat ID，不编辑 Hermes 或 cc-connect 配置，不处理端口、Hook、Session、计划任务或 Secret 注入。

二、目标流程
------------

1. Control Plane 只读检测系统、组件、版本、配置所有权和现有生命周期所有者。
2. 用户选择官方登录、本产品管理的 API 凭据或可选 CC Switch 路线。
3. 产品安全保存 Secret 引用并生成 Hermes 与 cc-connect 候选配置。
4. 产品识别三个 Bot，获取 User ID 与 Group/Chat ID，建立绑定与白名单，创建 cc-connect Project。
5. 产品处理端口、Hook、Session 与后台启动，并逐项检测六条目标链路。
6. GUI 显示每条链路的证据、最近验证时间、失败位置与恢复动作。

三、六条目标链路
----------------

Hermes 私聊、Hermes 群聊、Claude Code 私聊、Claude Code 群聊、Codex 私聊、Codex 群聊必须独立验收。Bot 连接、普通消息、命令、Mention、Reply、Topic 和 Session 隔离也必须分开记录，不能相互推断。

四、Operation 与安全
--------------------

每个外部变更使用可审计 Operation、Idempotency-Key 和恢复点。Secret 不进入日志、URL、Diagnostic 或普通配置。任何真实消息测试必须由用户明确确认目标会话，超时不自动重复发送。

五、当前阶段
------------

当前只实现只读发现、Readiness、Dry-run、Operation/SSE 和无副作用诊断。上述自动配置、真实安装、真实链路检测和 GUI 均为后续目标。
