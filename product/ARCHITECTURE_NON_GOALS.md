架构非目标 ARCHITECTURE_NON_GOALS
================================

一、硬约束
----------

1. 不重写 Hermes、Claude Code、Codex 或 cc-connect。
2. 不开发第二套 Agent Runtime、通用 Telegram Bridge 或消息总线。
3. 不重复开发完整 Provider 管理器；优先集成可选 CC Switch。
4. 不把 Control Plane 变成通用 DAG、工作流市场或插件市场。
5. 不让 GUI 直接依赖或写入上游内部目录。
6. 不新增 Telegram 之外的 Channel，也不新增其他 Agent Runtime。
7. 不扩大 dual_agent 或现有 5 个 cc-connect Patch。
8. 不把配置存在、Token 引用或普通消息证据虚报为健康、认证有效、命令可用或 Session 隔离已验证。
9. 不让两个 ManagementOwner 同时写同一配置作用域。
10. 不静默升级上游，不在没有快照和回滚点时接管生命周期。

二、Integration First
---------------------

Adapter 只声明上游真实具备且有证据的能力。上游不足时返回 unsupported、unavailable 或 unknown，不用本地兼容代码伪造完整能力。

三、当前非范围
--------------

完整正式发布 GUI、通用安装器、无人确认的真实 Telegram 操作、六链路自动验收、Provider 编辑页面、真实凭据迁移与多组件安装均不属于当前阶段。当前仅实现 PySide6 最小 GUI/四步 Onboarding 壳和 Control Plane 客户端；新 GUI 私聊/群自动检测仍待用户 live 验证，不能扩展为通用 Bot 平台或伪造 Hermes/消息证据。
