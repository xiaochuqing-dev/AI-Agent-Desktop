产品宪法 PRODUCT_CONSTITUTION

本文档是本产品的最高约束。任何路线、设计、组件取舍与本宪法冲突时，以本宪法为准。
所有占位符为示意，真实值放受控的本地 Secret 存储，不入仓库。

————————————————————————————————

一、产品定位

面向个人 AI 开发团队的桌面端安装、配置、管理与协作产品。
本产品不重新开发 Hermes、Claude Code、Codex，也不开发完整 Runtime；
而是把上述成熟能力组合成一套普通用户十分钟内可完成的完整体验：
安装、配置、启动、诊断、升级、回滚和迁移。
本产品的价值不在"再造轮子"，而在"把轮子装好、调好、管好"。

————————————————————————————————

二、十分钟目标

在基本干净的 Windows 电脑上，普通用户应能在十分钟左右完成：
环境检测、必要组件安装、模型或账号授权、Telegram 配置、首次成功测试。
全程不手工编辑任何配置文件。
用户不需要理解 AppData 目录、npm 全局目录、环境变量、监听端口、计划任务这些底层概念。
所有底层细节由本应用封装和代管，用户只面对 GUI 表单与状态。

————————————————————————————————

三、默认组件定位

Hermes：默认智能中枢和 Orchestration Provider，群聊治理与委派的核心。
cc-connect：当前辅助 Runtime 和 Telegram 连接层，可被替换，不是永久核心。
Claude Code：一等代码 Agent，由 cc-connect 接入 Telegram。
Codex：一等代码 Agent，由 cc-connect 接入 Telegram。
Telegram：首发 Channel，不是唯一 Channel，渠道层必须可扩展。
dual_agent：当前 Fallback 编排层，不是永久核心，Hermes 原生支持后可退场。
cc-connect Patch：当前兼容层，用于补齐上游缺失能力，不得无限扩大。

————————————————————————————————

四、当前真实 Telegram 拓扑

本产品当前实际运行的消息拓扑如下，文档与代码以此为准：
Hermes Bot 自己直连 Telegram（gateway 与 telegram_platform adapter）。
Claude Code Bot 通过 cc-connect 连接 Telegram（cc-connect 的 claude-expert project）。
Codex Bot 通过 cc-connect 连接 Telegram（cc-connect 的 codex-expert project）。
治理规则在 Hermes 的 multiagent.yaml 中定义，cc-connect 通过本地 Hook 把消息事件回传给 Hermes。
任何新设计不得破坏这三条链路的现有职责边界。

————————————————————————————————

五、产品架构方向

Desktop GUI -> Local Control Plane -> Provider/Adapter -> Hermes/cc-connect/Claude Code/Codex/Telegram。
GUI 不直接调用上游组件，只与 Local Control Plane 的 API 交互。
Control Plane 之下是 Provider/Adapter 层，负责对接具体组件。
Hermes、cc-connect、Claude Code、Codex、Telegram 均作为可替换的 Provider 或 Channel 存在。
这一分层是本产品所有后续设计的前提。

————————————————————————————————

六、长期竞争力

十分钟安装、统一配置、Secret 安全管理、状态可见、错误可诊断、
一键启停重启、更新备份回滚、新电脑迁移、多 Agent 多 Channel 组合体验、
人类暂停取消介入改派、美观现代 GUI。
上述能力是本产品区别于"裸用上游组件"的核心护城河，优先级高于任何单一新功能。

————————————————————————————————

七、不得走偏

不重写 Hermes、Claude Code、Codex。
不开发第二套完整 Runtime。
不开发第二套消息总线。
不把 Control Plane 变成通用 DAG 编排引擎。
不继续无限扩大 dual_agent 和 cc-connect Patch。
不锁定 GUI 技术栈。
不让 GUI 直接依赖上游组件的内部目录结构。
任何提案若落入上述任一条，视为偏离产品方向，需退回重新设计。
