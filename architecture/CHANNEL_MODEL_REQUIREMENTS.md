通道模型需求文档

文档定位: 把 Telegram 群聊与私聊能力抽象为通用 Channel 模型，
使通用核心不依赖任何单一通道的专属字段。本文档是需求契约，不含实现代码。
真实群标识与 Bot 用户名一律使用占位符，如 <TELEGRAM_GROUP_CHAT_ID>、<BOT_USERNAME>。

一、设计目标

当前通道能力都建在 Telegram 之上，路由判定直接读取 chat_id、message_id、
MessageEntity 等专属字段。若直接接入飞书、Discord、Slack、Web，通用核心会
被迫处处适配各通道字段。

本模型把通道能力抽象为通用概念，通用核心只认通用字段，通道专属字段由
ChannelAdapter 负责映射。新增通道只需实现 ChannelAdapter。

二、通用模型定义

1. Channel
   表示一个消息通道实例。属性含通道类型、通道标识、通道形态（群聊或私聊）、
   所属 Bot 标识。通用标识不使用 chat_id，用抽象的 channel_id。

2. Conversation
   表示一个会话。属性含会话标识、所属 Channel、会话形态（群聊或私聊）、
   会话隔离边界。群聊与私聊的路由和 Session 隔离在此体现，不用 chat_type 区分，
   用通用的 conversation_scope 表示。

3. Message
   表示一条消息。属性含消息标识、所属 Conversation、发送者、发送者类型
   （人类或 Bot）、文本、附件（图片、文件、音频）、是否命令。
   通用标识不使用 message_id，用抽象的 message_ref。

4. Mention
   表示对某 Agent 的显式提及。属性含被提及的 Agent 标识、提及来源
   （服务端解析或文本正则）。通用模型不依赖 Telegram username，用 agent_handle。
   支持多提及（一条消息 @ 多个 Agent）。

5. Reply
   表示对某条消息的回复关系。属性含被回复消息的引用、被回复消息的文本。
   通用模型不依赖 reply_to_message_id，用抽象的 replied_to_ref。

6. MultiBot
   表示一个通道内多个 Bot 共存的治理关系。属性含该通道内的 Bot 列表、
   每个 Bot 的角色、互触发抑制规则。Bot 发起的消息不自动触发其他 Bot（防环）。

三、当前 Telegram 已实现的能力映射

1. 普通静默: 群聊普通消息（无 @、无回复、非命令）所有 Bot 静默，
   仅记录到 Transcript。映射为通用 Message 无 Mention 无 Reply 时默认不触发。
2. 直接 @: 显式 @某 Agent，仅该 Agent 响应。映射为 Message 含单一 Mention。
3. 多 @: 一条消息 @ 多个 Agent，仅被 @ 的 Agent 响应。映射为 Message 含多 Mention。
4. Reply 加 @: 回复某 Agent 同时 @ 另一 Agent，仅 @ 的 Agent 响应，
   被回复消息文本作为参考上下文。映射为 Message 同时含 Reply 与 Mention。
5. 普通回复: 回复某 Agent 但不 @，仅被回复的 Agent 响应。
   映射为 Message 含 Reply 无 Mention。
6. 多 Bot 治理: 三个 Bot 共存，Bot 互不触发。映射为 MultiBot 防环规则。
7. 私聊: 私聊默认响应当前 Bot，不需 @。映射为私聊 Conversation 默认触发所属 Bot。

四、通用核心的隔离要求

1. 通用核心不使用 chat_id、message_id、reply_to_message_id、MessageEntity、
   chat_type、thread_id 等 Telegram 专属字段。
2. 通用核心只认抽象字段: channel_id、message_ref、replied_to_ref、
   conversation_scope、agent_handle。
3. 通道专属字段由 ChannelAdapter 在适配层映射为通用字段，不进入通用核心。
4. 路由判定、人类控制、能力查询均基于通用模型，不基于通道专属字段。

五、未来接入新通道

1. 接入飞书、Discord、Slack、Web 只需实现对应 ChannelAdapter。
2. ChannelAdapter 负责: 通道收发、专属字段到通用字段的映射、提及解析、
   回复关系解析、群聊与私聊形态识别。
3. 新通道无需改动通用核心、编排层、人类控制逻辑。
4. 新通道的多 Bot 治理由 MultiBot 模型统一描述，不各自实现。

六、不做的事

1. 不在本阶段实现各通道的 ChannelAdapter 运行时代码。
2. 不绑定 Telegram Bot API 的任何具体接口签名。
3. 不在通用模型中保留任何通道专属字段作为可选回退。
