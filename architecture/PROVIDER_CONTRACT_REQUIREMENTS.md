Provider 契约需求文档

文档定位: 定义五类 Provider 的职责、能力边界、不绑定什么、未来如何被替代，
以及通用本地 API 要求。本文档是需求契约，不含实现代码。
真实凭据与本机路径一律使用占位符，如 <TELEGRAM_BOT_TOKEN>、<PROJECT_ROOT>。

一、通用要求

1. 每个 Provider 只定义能力边界与调用约定，不绑定具体组件名或私有数据结构。
2. 通过 Control Plane 本地 API（HTTP/IPC，仅绑定 localhost）对外暴露。
3. 能力版本化，新增能力走版本协商，不破坏旧调用方。
4. 调用应可幂等查询、可失败回退、可被人类控制指令中断。
5. 实现可被等价组件替换，替换时契约不变则上层无感。

二、OrchestrationProvider（当前映射 Hermes）

职责: 接收编排请求并决定由哪些 Agent 处理、串行还是并行；执行单 Agent 委派、
并行与顺序编排；管理内部 handoff 与上下文传递（handoff 不对外公开）；
维护编排共享内存写入策略。
能力边界: 只负责编排决策与流程，不负责 Agent 内部模型调用与通道收发底层细节；
并行 Worker 不获得全局主持职责，防止措辞越权。
不绑定: Hermes 插件加载机制、webhook receiver 端口、内部 store 结构、
dual_agent 路径解析（环境变量 > 配置 > junction > fail-fast）。契约不出现
hermes_cli、multiagent、dual_agent_root 等实现名字。
未来替代: 任何能完成编排决策、单 Agent 委派、并行与顺序编排的组件，
实现本契约即可替代当前 Hermes，Control Plane 与 GUI 无需改动。

三、AgentRuntimeProvider（当前映射 cc-connect）

职责: 承载 Agent 运行时，把通道消息接入具体 Agent（当前为 Claude Code 与 Codex CLI）；
管理 Agent Session 连续性与空闲超时；通过 relay 同步调用目标 Agent 并取回完整回复；
把消息事件通过 hook 上报给编排层。
能力边界: 只负责运行时与 Session 管理，不负责路由裁决（由编排层决定）；
群聊普通消息不触发 Agent，由静态配置与编排层路由共同保证。
不绑定: cc-connect 的 config.toml 结构、projects 数组、patch-set 版本、
具体连接的 Agent 类型（claudecode、codex 可扩展为其他）。契约不出现
cc-connect、relay_bindings.json 等实现名字。
未来替代: 任何能把通道消息接入运行时、管理 Session、上报事件并取回回复的组件，
实现本契约即可替代当前 cc-connect。

四、ChannelProvider（当前映射 Telegram 与 Hermes Telegram Platform）

职责: 提供通道收发能力；暴露会话、消息、提及、回复等通用模型
（详见 CHANNEL_MODEL_REQUIREMENTS.md）；支持多 Bot 共存与治理；区分群聊与私聊
的路由和会话隔离。
能力边界: 只负责通道收发与通用模型映射，不负责编排决策与 Agent 内部模型调用；
通用核心不使用 chat_id、message_id 等通道专属字段。
不绑定: Telegram Bot API、MessageEntity、getUpdates 长轮询机制、
具体 Bot 用户名或群标识（用占位符如 <TELEGRAM_GROUP_CHAT_ID>）。契约不出现
telegram、ptb、bot_token 等实现名字。
未来替代: 实现 ChannelAdapter 即可接入飞书、Discord、Slack、Web 等新通道，
无需改动通用核心与编排层。

五、LifecycleProvider

职责: 安装（拉起组件、写配置、建 junction）、启动与停止（VBS 或计划任务拉起终止）、
重启（停止后再启动，保证幂等）、健康（进程存活、端口监听、hook 回调）、
更新（替换版本，保留配置与数据）、回滚（更新失败回到上一可用版本）、
迁移（本机或跨机转移配置、凭据、Session 数据）。
能力边界: 只负责组件进程与配置生命周期，不负责编排逻辑；迁移只转移授权范围内
配置与凭据，不越权读取；健康检查只读不写，不改变组件运行状态。
不绑定: VBS 脚本、计划任务名、Windows 注册表具体实现、本机绝对路径
（用 <PROJECT_ROOT>、<HERMES_HOME> 占位）。契约不出现 Hermes_Gateway.vbs、
CcConnect_Autostart.vbs 等脚本名。
未来替代: 任何能完成安装、启停、健康、更新、回滚、迁移的宿主机制，
实现本契约即可替代当前 VBS 与计划任务方案。

六、CapabilityRegistry

职责: Agent 注册（记录标识、角色、所属通道、能力声明）、能力检测（查询 Agent
是否在线、是否支持某能力）、能力变更通知（上线、下线、能力变化时通知订阅方）。
能力边界: 只负责能力注册与查询，不负责编排决策与 Agent 具体模型配置；
注册信息不含真实凭据，只存能力描述与状态。
不绑定: 具体 Agent 数量与命名（当前三个 Bot 不写死）、Telegram 角色枚举
（orchestrator、coder 可扩展）。
未来替代: 任何能完成注册、能力检测、变更通知的机制，
实现本契约即可替代当前配置文件式的静态注册。
