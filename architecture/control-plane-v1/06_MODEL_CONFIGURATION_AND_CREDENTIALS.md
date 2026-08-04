# 06 模型配置与凭据

## 配置作用域与唯一写入权

管理权作用于明确的 `configuration_scope`，而不是含糊的“整个工具”。一个组件可有互不重叠的 scope，例如 `model_selection`、`api_endpoint`、`official_authentication`、`runtime_preferences`。同一 scope 同一时刻只有一个 ManagementOwner，scope 之间不得引用同一可写字段。

Owner 类型：

- `application`：本应用通过 ModelConfigurationProvider 写入
- `official_login`：上游官方登录流程独占写入
- `cc_switch`：用户主动启用的高级管理入口
- `external`：其他受用户管理的工具或手工配置，本应用只读

配置保存非敏感值和 `credential_ref`。CredentialProvider 保存 Secret；ModelConfigurationProvider 永远收不到“把 Secret 写入普通配置”的指令。

## Hermes 原生模型配置流程

该流程是十分钟引导中的应用原生路径，设计目标如下：

1. CapabilityRegistry 确认 ModelConfigurationProvider 支持 schema/read/validate/write。
2. GUI 获取模型、endpoint、基础参数和敏感字段引用的 schema，不读取内部配置文件。
3. 用户选择模型并输入凭据。Secret 直接提交 CredentialProvider，返回 `credential_ref`。
4. ModelConfigurationProvider 生成候选配置，Owner 必须是 `application`。
5. 先执行纯结构校验；用户同意后可执行最小连通校验。校验不会激活候选配置。
6. 写入前记录当前 revision、创建配置备份并再次检查 Owner。
7. 原子提交新配置引用；失败保留上一份有效配置和凭据，未使用凭据可由用户决定删除。
8. Adapter 重新读取并验证 observed revision，成功后 ConfigurationState=valid。

本流程不要求用户打开或编辑配置文件，也不把模型 API Key 放入模板、环境变量永久区或普通日志。

## Claude Code 与 Codex 官方登录

默认推荐官方登录：

1. `official_authentication` scope 的 Owner 设置为 `official_login`。
2. Control Plane 只启动官方登录入口并获取脱敏状态，不代填密码、不拦截 OAuth token、不修改官方凭据文件。
3. Adapter 将结果映射为 required/authenticating/authenticated/expired/invalid。
4. 登录完成后只记录状态、观测时间和官方管理标记。
5. 注销或重新授权同样由官方流程执行；本应用不通过删除文件伪造注销。

基础 API 配置是独立路线：仅当 Provider 明确声明可安全管理时，`api_endpoint` 或 `model_selection` scope 可以归 `application`。它不得覆盖 `official_authentication` scope，也不能在同一字段上与官方登录混写。

如果用户从官方登录切换到自定义 API，必须走 Owner 交接；仅切换 GUI 单选框不构成完成。

## CC Switch 的高级定位

- CC Switch 不出现在新手必选清单，不影响首次安装完成条件。
- 只有本机发现、版本兼容且用户主动选择时，才显示“由 CC Switch 管理”。
- 本应用不假设其内部文件格式稳定；通过专用 Adapter 做只读检测、备份和边界写入。
- 启用后，其负责 scope 的 Owner 为 `cc_switch`，本应用的写控件变只读。
- 用户可以查看差异摘要，但默认不展示 Secret 或整份私有配置。
- 无法证明 CC Switch 已停止写入时，Owner 切换不得提交。

## ManagementOwner 切换协议

### 准备阶段

1. 客户端提交 from、to、scope、expected revision 与 idempotency key。
2. Control Plane 对 scope 加短期写锁，普通写入全部返回冲突。
3. 读取双方能力和当前观测，检测未知外部修改。
4. 创建非 Secret 配置快照；CredentialProvider 创建独立加密恢复点或确认凭据仍由原 Owner 保管。
5. 生成 TransferPlan：影响字段、不可迁移项、验证方法和回滚点。

### 提交阶段

1. 将旧 Owner 置只读或确认其官方流程已退出。
2. 目标 Owner 写入候选配置并验证，但尚不删除原备份。
3. 原子写入新 Owner、配置 revision 与 owner revision。
4. 重新观测目标组件；通过后释放写锁。

### 失败与回滚

- 任一校验失败即恢复原配置和 Owner；目标方保持只读。
- revision 变化表示发生并发写，进入 conflict，不自动合并。
- 进程崩溃后根据 transfer journal 探测双方实际状态；证据不足进入 conflict。
- 只有用户重新选择权威来源后才能继续。

切换操作重放同一 idempotency key 返回原 TransferPlan/Operation，不再次写入。

## 配置写入安全

- 候选配置与当前配置分离；validate 不原地修改。
- 写入采用临时文件、权限校验、fsync 和原子替换，或使用上游正式事务 API。
- 写入前备份，写入后由 Adapter 重新读取并比较语义摘要。
- 配置 schema 标记 secret reference、实验字段、默认值、允许范围与重启要求。
- 不识别的字段默认保留但不修改；若无法安全保留，拒绝写入并说明原因。
- 本应用不通过全局环境变量长期注入 Secret；只允许给受管子进程构造最小环境。

## CredentialProvider 数据模型

CredentialMetadata 只含：`credential_ref`、purpose、owner、backend、created_at、updated_at、last_validated_at、status、revision 和可选 expires_at。它不含明文、部分明文、请求 header 或可逆摘要。

Secret 类型至少包括 API key、OAuth material、Bearer、Channel token 与 receiver secret。类型只影响校验和使用策略，不改变“GUI 不可读取明文”的原则。

## 保存与使用

### 保存

1. GUI 在受鉴权 TLS 之外的 loopback API 上提交 Secret body；服务端禁止请求体日志。
2. CredentialProvider 立即写入安全后端并清理中间 buffer；返回 credential_ref。
3. 业务配置只保存 credential_ref，不保存环境变量展开值。
4. 保存事件只含 ref、purpose 和状态。

### 使用

1. 受信 Adapter 以 adapter_id、purpose、目标 component 和 TTL 请求 lease。
2. CredentialProvider 验证调用方与 scope，返回一次性受控句柄或在进程启动时直接注入。
3. lease 到期、Operation 结束或 Adapter 崩溃后撤销。
4. Adapter 不缓存、打印、回传或拼入命令行参数；优先使用标准输入、受限 handle 或子进程环境。
5. GUI、本地事件、Diagnostic 与导出包均不能取得明文。

## 校验、移除与轮换

- 格式校验本地完成；连通校验必须说明会访问哪个服务、设置短 timeout，并限流。
- 401 等结果映射为 invalid，不在错误中回显请求或 header。
- 移除前列出引用该 credential_ref 的配置；存在必需引用时默认拒绝。
- 删除是不可逆操作，需要 expected revision、显式确认和审计；重复删除为成功 no-op。
- 轮换先保存新 ref、验证、原子切换配置引用，再删除或保留旧 ref 作为短期回滚点。

## Windows-first 安全存储

推荐抽象为 CredentialBackend，不在核心契约绑定语言库：

1. 小型独立 Secret 优先使用 Windows Credential Manager 一类的用户级系统 keystore。
2. 需要结构化或较大数据时，可使用 DPAPI 当前用户范围保护的加密 vault，并设置仅当前用户 ACL。
3. 不使用仓库目录、普通配置文件、注册表明文字段、命令行参数或用户级永久环境变量保存 Secret。
4. Control Plane 与提权 helper 分离；管理员 helper 不继承不需要的用户 Secret。
5. 后端不可用时状态为 degraded/failed，不退化到明文文件。

当前三个 Bot Token、cc-connect management Token 和绑定 HMAC Key 均为小型独立 Secret，已选择 keyring.backends.Windows.WinVaultKeyring，并在 Windows 11 普通用户下验证 put、replace、status、resolve_for_operation、delete、metadata 与 revision。后端类型不匹配或不可用时 fail closed，禁止明文文件回退。DPAPI vault 仅保留给未来结构化大凭据，不是当前依赖。

## 跨平台抽象

CredentialBackend 的最小操作为 store、metadata、use/lease、delete、health、export_encrypted、import_encrypted。未来后端可映射 macOS Keychain、Secret Service 或其他系统 keystore。

系统 keystore 的本机加密不能直接复制到新电脑，因此迁移协议独立于后端：

1. 用户明确选择凭据范围并设置迁移保护策略。
2. 源 Backend 在内存中解封，直接写入经过认证加密的迁移容器。
3. 容器清单只有 ref、purpose、算法、版本和完整性信息，不列明文。
4. 目标机验证来源和完整性后解密，再用目标 Backend 重新封装。
5. 目标验证成功前不删除源凭据；临时材料安全清理。

## 备份、恢复与冲突

- 普通配置备份与凭据备份是两个对象，可由同一 Backup 清单关联。
- 没有用户授权时，备份默认不包含可迁移 Secret。
- 恢复先校验清单和版本，再恢复到临时 scope；验证通过后切换引用。
- 恢复失败不覆盖当前有效凭据。
- 发现同一 scope 被未知进程写入时，ConfigurationState=conflict、Owner state=conflict，所有自动写入停止。

## 脱敏规则

- 日志字段名可保留，值统一写 `[REDACTED]`，不显示首尾字符。
- URL 在记录前删除 userinfo、query 与 fragment。
- 异常链先结构化提取允许字段，再进入 Diagnostic；不能事后只靠正则替换。
- Secret 变量、请求 body、Authorization、登录回调、迁移口令和解密错误上下文不进入普通日志。
- 开发 debug 模式也不得关闭上述规则。

## 当前与目标的区别

Reference Baseline 仍存在分散的配置文件、环境注入和上游登录存储，本阶段没有读取或迁移这些 Secret。Control Plane 只管理三个固定 Telegram Bot CredentialRef 与两个内部运行 CredentialRef；API 只返回 metadata。cc-connect 原生 TOML 只保存环境变量占位符，启动时向目标子进程注入，Operation 完成后释放父进程引用。Python/keyring 无法保证物理内存完全清零，该限制必须持续公开。
