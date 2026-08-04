ADR-004 CredentialBackend 组合与 Secret 边界
=============================================

状态: Accepted / Frozen
日期: 2026-07-31

上下文
------

提示词 §十一要求:本阶段不实现完整凭据写入,但必须冻结 CredentialProvider 接口、确定 Windows Credential Manager / DPAPI 正式策略、实现 SecretRef 模型、Readiness Scan 只判断引用是否存在或可访问、所有 API 响应与结构化日志默认脱敏、不得为测试提交任何真实 Secret/ID/路径/用户资料。

契约要求(CREDENTIAL_PROVIDER_REQUIREMENTS、06 §89-162、core-models CredentialMetadata):Secret 与业务配置分离;凭据不进 Git、不进普通日志、不进错误堆栈、不进 URL query(用 Header 传递);后端不可用必须报错,不允许回退明文;不自行设计加密算法;不把 SQLite 当 Secret Vault。

当前真实环境(供只读发现复用,本阶段不读取明文):Telegram bot token 在 .cc-connect/bot-tokens.env(不入 Git);Hermes 自身 token 在运行配置(不入 Git);bot username 在 multiagent.yaml;group chat id 在 multiagent.yaml;代理 socks5://127.0.0.1:10808。

决策
----

1. CredentialProvider 接口本阶段冻结,定义能力:metadata(只读列出凭据元数据,不含值)、has_reference(判断 SecretRef 是否存在或可访问)、store/validate/remove/use/export/import 标记为 unavailable(本阶段不实现真实写入与使用)。
2. SecretRef 模型本阶段新增为 core-models 向后兼容增量:只承载 credential_ref、purpose、owner、backend、status(枚举同 CredentialMetadata.status),永不承载值或值片段。配置中的敏感字段以 SecretRef 引用,不以明文存在。
3. CredentialBackend 正式策略:
   a. 小型 Secret(bot token、API key、bearer)使用 Windows Credential Manager,通过成熟封装库 keyring 访问;
   b. 结构化材料(如需)使用 DPAPI 当前用户范围 vault;
   c. 后端不可用必须返回结构化错误,绝不回退明文;
   d. 本阶段只实现 has_reference 与 metadata 读取,不实现 store/validate/remove/use 的真实写入。
4. 脱敏规则(默认开启,不可由高级模式绕过):
   a. API 响应在序列化层统一脱敏,匹配 Telegram bot token、OpenAI/Anthropic 类 API key、bearer token、cookie、Authorization header、URL 内凭据、JSON/YAML/TOML/.env 敏感字段;
   b. 结构化日志在 Formatter 层脱敏,同一套规则;
   c. Operation store、Diagnostic、ReadinessReport 一律不存储明文 Secret;
   d. redaction_applied 恒为 true(Diagnostic、LogEntry 契约要求)。
5. 本地 API 只绑 127.0.0.1 / ::1,禁止 query token,使用高熵 Bearer + Host/Origin 校验。
6. 测试用 Fake Adapter 与合成 fixture,不提交任何真实 token、chat id、user id、路径或用户资料;Secret 脱敏与扫描有专门测试覆盖。

替代方案
--------

A. 直接用 DPAPI(pywin32)手写 vault:控制力强但实现量大,且 keyring 已是成熟封装并默认走 Windows Credential Manager,自实现属重复造轮子。不作为本阶段主方案,但保留为 keyring 不足时的退路。

B. 文件加密 vault(自实现):违反“不自行设计加密算法”。不采用。

C. SQLite 存 Secret:契约明确禁止。不采用。

D. 本阶段不定义 SecretRef、推迟到阶段 2:提示词 §十一明确要求本阶段实现 SecretRef 模型与只读引用判断。不采用。

后果
----

正面:
- CredentialProvider 边界冻结,阶段 2 可在不改接口的前提下补全写入。
- SecretRef 使配置中的敏感引用有结构化承载,Readiness Scan 可判断引用是否存在而不接触明文。
- 脱敏默认且不可绕过,满足契约与安全审查。

负面 / 约束:
- 本阶段无法真正写入或校验凭据有效性,只能判断引用存在性,状态为 unknown 时如实返回 unknown,不伪造。
- keyring 在某些 Windows 环境下后端不可用时需明确报错(后端不可用不回退明文)。

回退条件
--------

1. keyring 在目标 Windows 上无法稳定访问 Windows Credential Manager(可复现失败)。
2. 脱敏规则在契约测试中漏脱敏(扫描命中真实 token/key)。
3. SecretRef 模型与现有 CredentialMetadata 产生语义冲突无法调和。

回退路径:CredentialProvider 接口冻结不变;后端可在 keyring 与 DPAPI(pywin32)之间替换;SecretRef 为增量模型,可移除而不影响已有 15 个核心模型。

未来重审触发器
----------------

1. 阶段 2 实现真实凭据写入与校验,需用安全测试验证后端选择。
2. 引入 OAuth token 等结构化凭据,需评估 DPAPI vault 是否必要。
3. 凭据迁移(阶段 3)需评估加密导出/导入边界。
4. keyring 上游主版本破坏性变更或 Windows 凭据管理 API 变化。

实施记录（2026-08-05）
----------------------

阶段 2 已在不改变既有 SecretRef 边界的前提下落地固定 Telegram CredentialRef。Windows 后端经普通用户验收确认使用 `keyring.backends.Windows.WinVaultKeyring`，支持 put、replace、status、operation-scoped resolve、delete、仅元数据列表、revision 与 capability probe；后端不可用时不允许明文文件回退。

Secret 只在明确 Operation 内短暂解析，并仅注入目标 cc-connect 子进程；API 响应、SQLite、原生配置、日志和 argv 均不保存或回显值。Fake 后端只用于自动化。加密导出/导入、跨机迁移、通用 Provider Secret 与 Python 物理内存完全清零保证仍未实现，因此本 ADR 的迁移重审触发器继续有效。
