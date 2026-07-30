AI Agent Desktop
================

面向个人 AI 开发团队的桌面端安装、配置、管理与协作产品。

本仓库是当前公开事实源。它把多个成熟 AI 工具（Hermes、Claude Code、Codex）和消息渠道（Telegram）组合成普通用户十分钟可安装、配置、启动、诊断、升级、回滚和迁移的完整体验，并提供以人类调控为主的多 Agent 协作。

一、当前状态
------------
reference baseline v0.1 已冻结（Tag v0.1-reference-baseline）。
当前参考实现通过真实 Telegram 群聊与 Hermes 私聊 E2E。
当前运行 cc-connect v1.4.1-patchset0.1-fc315d2。
源码与当前运行体一致（见 CURRENT_RUNTIME_SOURCE_MAP.md）。
当前未进入 Control Plane 编码或 GUI 开发。

二、这不是什么
--------------
- 不是把 Hermes、cc-connect、Claude Code、Codex、Telegram 永久焊死的脚本集合
- 不是最终产品 v0.1.0
- 不是最终产品架构
- 不重写 Hermes、Claude Code、Codex 或完整 Runtime
- 不锁定 GUI 技术栈

三、快速阅读
------------
1. 00_START_HERE.md（开始）
2. 01_CURRENT_STATE.md（当前状态）
3. 02_PRODUCT_VISION.md（产品愿景）
4. 03_LATEST_PRODUCT_DECISIONS.md（最新产品决策）
5. 04_REFERENCE_BASELINE.md（参考基线）
6. 05_NEXT_PHASE.md（下一阶段）
7. CURRENT_RUNTIME_SOURCE_MAP.md（运行源码映射）
8. src/（与当前运行体对齐的源码）
9. next-agent/NEXT_AGENT_PROMPT.txt（下一 Agent 提示词）

四、目录结构
------------
src/                  当前有效源码（hermes-adapter / dual-agent-fallback / lifecycle）
integrations/cc-connect/  cc-connect Patch、构建脚本、manifest
config-examples/      脱敏配置模板
product/              产品宪法、十分钟安装、组件定位、模型配置权、GUI 状态、非目标
architecture/         Control Plane 契约需求
reference-baseline/   版本矩阵、E2E 验证、已知问题、上游版本、事实源
tests/                单元测试与 E2E 摘要
history-minimal/      历史摘要
next-agent/           下一 Agent 提示词

五、第三方组件
--------------
Hermes、Claude Code、Codex、cc-connect 都是独立上游项目，各自有许可证。
本仓库只保存我们自己的适配代码、Patch、配置模板和构建脚本，不复制完整上游项目。
上游获取方式见 reference-baseline/UPSTREAM_REVISIONS.md 和 integrations/cc-connect/README.md。

六、安全
--------
本仓库不含 Token、API Key、密码、数据库、Transcript、日志、PID、个人聊天内容。
所有配置模板使用占位符。详见 SECURITY_REVIEW.md。
