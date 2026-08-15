模型配置管理权归属 MODEL_CONFIGURATION_OWNERSHIP
================================================

一、唯一管理权
--------------

每个配置作用域同一时刻只能有一个 ManagementOwner。非所有者只读；切换所有者必须经过用户确认、备份、revision 比较、一致性校验和两阶段交接，不得存在双写窗口。

二、职责
--------

本产品未来管理 Hermes、cc-connect 与 Telegram 绑定所需的受控配置；Claude Code 和 Codex 的官方登录材料仍由官方流程管理。本产品只读取脱敏状态，不截取密码、OAuth Token 或 Session。

Secret 与业务配置分离。Bot Token、API Key 和 Bearer 进入 CredentialProvider，业务配置只保存 SecretRef。InMemory 后端只用于测试；Windows Credential Manager 后端已真实实现 put、replace、status、resolve_for_operation、delete、metadata 与 revision，且禁止退化到明文文件。当前只开放三个固定 Telegram Bot Token 引用及产品内部运行凭据，不扩展为通用凭据平台。

三、CC Switch
-------------

CC Switch 是推荐但非强制的供应商配置入口。新手无需安装 CC Switch。若用户选择由 CC Switch 管理某个供应商作用域，该作用域的 ManagementOwner 为 cc_switch，本产品立即转为只读；本产品与 CC Switch 不得同时写同一作用域。

本阶段 CC Switch ExternalToolProvider 可以基于公开可执行入口检测 installed/not_installed/unknown 并受控打开应用。版本仅在有可靠证据时报告；install、update、configuration 和 ownership_handoff 无稳定证据时均为 unknown。它不读取、导入、导出或写入 Provider 与 Secret。

四、用户输入边界
----------------

当前最小 GUI 中，用户只输入三个 Telegram Bot Token，并在 Telegram 客户端完成 Start、建群/加 Bot 等官方操作；不输入 User ID 或 Group/Chat ID。Token 通过 Control Plane 写入 Windows Credential Manager，GUI 快照、日志和二维码不保存明文。

Claude/Codex 原生配置、受控端口和后台启动仍由 Control Plane 的受管路径处理。Hermes 既有配置保持 external-first；对已安装但 Telegram 未配置的 Hermes，Control Plane 可通过官方公开 `.env` 与 Gateway CLI 完成最小 Telegram 接入，已有 Bot 冲突必须显式选择，失败可回滚。Provider、Model、Tool、Studio 与其它 Hermes 配置仍由 Hermes/外部工具管理。Agent Detector 不读取模型官方登录或 Secret，installed/healthy 不等于 authenticated。六链路真实消息 E2E 由用户明确确认后逐条执行，不会默认发送。新 GUI Telegram 与 Hermes Native Telegram 为 `PENDING USER LIVE VALIDATION`。
