模型配置管理权归属 MODEL_CONFIGURATION_OWNERSHIP
================================================

一、唯一管理权
--------------

每个配置作用域同一时刻只能有一个 ManagementOwner。非所有者只读；切换所有者必须经过用户确认、备份、revision 比较、一致性校验和两阶段交接，不得存在双写窗口。

二、职责
--------

本产品未来管理 Hermes、cc-connect 与 Telegram 绑定所需的受控配置；Claude Code 和 Codex 的官方登录材料仍由官方流程管理。本产品只读取脱敏状态，不截取密码、OAuth Token 或 Session。

Secret 与业务配置分离。Bot Token、API Key 和 Bearer 进入 CredentialProvider，业务配置只保存 SecretRef。当前 Control Plane 尚未实现真实凭据写入。

三、CC Switch
-------------

CC Switch 是推荐但非强制的供应商配置入口。新手无需安装 CC Switch。若用户选择由 CC Switch 管理某个供应商作用域，该作用域的 ManagementOwner 为 cc_switch，本产品立即转为只读；本产品与 CC Switch 不得同时写同一作用域。

本阶段 CC Switch Adapter 只报告 installed、not_installed 或 unknown；版本仅在有可靠证据时报告；configuration、authentication、runtime 和 health 无直接证据时均为 unknown。它不读取、导入、导出或写入 Provider 与 Secret。

四、用户输入边界
----------------

目标体验中，用户只输入正确的模型账号或 API 凭据，以及三个 Telegram Bot Token。User ID、Group/Chat ID、配置文件、端口、Hook、Session 和后台启动由产品未来自动处理。该自动化当前尚未实现。
