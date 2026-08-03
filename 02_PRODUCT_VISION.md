02 产品愿景
============

一、产品定位
------------

面向 Windows 开发者的 Telegram AI 编程团队安装、配置、管理、诊断与恢复中心。

产品把 Hermes、Claude Code、Codex、cc-connect、Telegram 和可选 CC Switch 组合成低摩擦体验，价值在于减少配置、降低失败率、统一状态与恢复，而不是重复开发上游。

二、首发范围
------------

- Windows 10/11
- Telegram
- Hermes、Claude Code、Codex
- cc-connect 作为 Claude Code/Codex 与 Telegram 的 V1 核心桥梁
- CC Switch 作为推荐但非强制的供应商配置入口
- PySide6 作为未来 GUI 首选，本阶段不实现 GUI

三、三个 Bot 与六条目标链路
----------------------------

用户可见 Hermes Bot、Claude Code Bot、Codex Bot。

目标链路为 Hermes 私聊与群聊、Claude Code 私聊与群聊、Codex 私聊与群聊。当前只存在部分真实证据；自动配置和六链路自动验收尚未实现。

四、未来用户体验
----------------

用户未来只需提供模型账号或 API 凭据，创建三个 Telegram Bot 并粘贴三个 Token，创建群聊并加入三个 Bot，完成 Telegram 官方必须由用户执行的少量操作，例如首次 /start 和权限设置，然后在 GUI 点击配置或验证。

产品未来负责识别 Bot、验证 Token、获取 User ID 与 Group/Chat ID、建立绑定和白名单、生成 Hermes 与 cc-connect 配置、创建 cc-connect Project、处理端口/Hook/Session/后台启动、检测六条链路并给出修复。以上均为目标，不是当前已实现能力。

五、架构方向
------------

Desktop GUI -> Local Control Plane -> Provider/Adapter -> 成熟上游。GUI 不直接写上游私有配置；Control Plane 不充当新 Runtime、通用 DAG 或第二套消息桥梁。

六、核心价值
------------

减少配置、降低失败率、降低首次使用摩擦，统一安装、状态、诊断、更新、回滚与恢复，让用户无需自行查找配置文件和日志。
