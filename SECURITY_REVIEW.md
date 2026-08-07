安全审查
========

更新时间：2026-08-07
结论：代码、Fake、Windows 11 合成安全门禁和六链路用户体验验收通过；整体交付因 Windows 10 与结构化 live 证据边界保持 PARTIAL

一、仓库内容
------------

未发现真实 Token、API Key、Bearer、Bot Token、Telegram 数字标识、用户名、机器名、个人消息正文、数据库、日志、PID、Session 或 Transcript。配置示例继续使用占位符。

二、Control Plane 安全边界
--------------------------

- 本地 API 仅允许 loopback，使用 Bearer，禁止 URL query token。
- API、Diagnostic、ReadinessReport 和结构化输出统一脱敏。
- SecretRef 不承载明文；SQLite 不作为 Secret Vault。
- Telegram Adapter 只判断配置或 Token 引用文件是否存在，不读取内容，不验证或输出 Token。
- CC Switch Adapter 只检查 PATH 与官方 ccswitch 协议注册，不读取供应商配置或 Secret。
- Diagnostic 不包含私有路径、异常堆栈或底层配置正文。
- 安装下载仅允许锁定 HTTPS 主机并保留 TLS 校验；重定向、大小、文件名、平台、架构和 SHA256 均在执行前校验。
- 安装目标限制在 platformdirs 生成的当前用户 LocalAppData 产品目录，拒绝路径穿越、符号链接和 junction 逃逸。
- 健康探针使用参数数组、隔离环境、临时配置、随机 loopback 端口、无窗口进程和进程树清理，不读取真实用户配置。
- 产品配置仅能写入固定的产品自有路径；使用不可变计划、revision、备份、同目录临时文件、fsync、os.replace、重解析和回滚。
- 生命周期启动使用参数数组、shell=False、固定 cwd、环境白名单和 Windows 无窗口标志；停止前核验 PID 创建时间、exe 路径/SHA256、命令摘要与产品所有权。
- Windows CredentialBackend 只接受固定 CredentialRef，真实落到 keyring.backends.Windows.WinVaultKeyring；支持 put、replace、status、resolve_for_operation、delete、元数据与 revision，后端不可用时不退化为明文文件。
- Telegram Client 对 401、403、409、429、超时、DNS/TLS、取消和响应大小做稳定错误映射，不把 Token 放入日志或错误正文，不无限重试。
- 一次性绑定码只展示一次，数据库只保存 HMAC digest；Update offset 单调前进，旧 Update、重放、其他用户抢绑定、错误群和 channel 均被拒绝或审计。
- cc-connect 原生 TOML 只保存 AIAD_TELEGRAM_CLAUDE_BOT_TOKEN、AIAD_TELEGRAM_CODEX_BOT_TOKEN 与 AIAD_CC_CONNECT_MANAGEMENT_TOKEN 占位符；Secret 仅注入目标子进程环境，不进入 argv。
- 子进程保留 PATH 等必要非敏感系统环境，使已安装 Claude/Codex 可被锁定版 cc-connect 发现；不写入或改变系统/用户 PATH。
- Python/keyring 使用不可变字符串，无法保证物理内存完全清零；实现只缩短引用生命周期并在 Operation 结束后释放，不作虚假保证。

三、本阶段无副作用证明
----------------------

自动化只在临时、非系统盘、含中文/空格/括号的隔离产品目录中安装、写入合成配置并运行锁定版 cc-connect。Windows Credential Manager 验收只写入随机 acceptance/ 引用并在 finally 删除；未读取用户旧 Token。仓库代码未修改真实 Bot/Provider 配置、系统 PATH、注册表、计划任务定义、Windows Service 或 Reference Baseline；external/conflict Owner 会阻断操作，不自动接管。

2026-08-07 的真实 Telegram 消息由用户在 Telegram 客户端内直接发送，Token 未提供给本任务，消息正文未写入仓库或最终报告。本轮绕过验收向导，因此没有伪造 getMe、3/3 绑定或 correlation 持久化证据。Hermes 黑窗口修复位于本机外部运行层，修改前有独立备份；最终报告只引用脱敏的事件类型、Agent、私聊/群聊范围和时间，不复制上游日志正文。

四、验证
--------

Control Plane 自动化覆盖 Secret API 不回显与不落库、Credential 后端错误、Telegram getMe/webhook/getUpdates、Update Lease、绑定过期/重放/抢绑定/同群一致性、六 LinkState、一次性 E2E、消息关联、Session 隔离、代理策略、原生 Renderer、配置竞态/漂移/回滚、external 检测、PID/SHA/端口/Owner 和重启恢复。最终本地门禁为 ruff、格式、mypy、合同、compileall、生产依赖 smoke 和 pytest 187 passed、1 skipped；候选包文本扫描未发现 Secret 形态或消息正文关键字段。详细证据记录于 reports/SIX_LINK_OBSERVABILITY_LIVE_E2E_AND_USER_VALIDATION_REPORT.md。

五、分发限制
------------

当前 cc-connect 产物 signature_status=unsigned。系统不会绕过 SmartScreen、关闭 Defender 或添加白名单；正式外部分发体验仍受 Windows 未签名提示影响。

锁定上游 management API 配置没有 bind host 字段，实测监听所有网卡。当前以随机高熵 Bearer、产品受控端口和本机防火墙边界降低风险，但不能标为 loopback-only；在上游提供正式 bind host 能力或升级门禁通过前，管理 API 健康只记为 partial。原生 Telegram 配置也不支持 Group Chat ID 白名单，当前只能限制 operator user，状态为 unsupported。
