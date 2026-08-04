# 13 Telegram 三 Bot 与原生配置切片

## 状态

实施日期：2026-08-05。代码、Fake Telegram、合成 Token、Windows Credential Manager 和 Windows 11 合法受管运行已通过；整体为 PARTIAL。真实 Telegram 为 PENDING USER LIVE VALIDATION，Windows 10 为 PENDING WINDOWS 10 VALIDATION，Hermes 为 pending_component_install，原生 Group Chat 过滤与 deep health 为 unsupported。

## 门禁顺序

阶段 A 先完成 Windows CredentialBackend、managed/native 分离、锁定 Schema/环境变量替换证明、合法 Project 持续运行和 external 检测修正。阶段 B 才允许三个固定 Bot slot 的 getMe、临时 getUpdates、一次性绑定与配置生成。默认健康检查不调用 Telegram，不发送消息。

## 凭据边界

公开引用固定为 telegram/hermes-bot-token、telegram/claude-bot-token、telegram/codex-bot-token。内部引用只用于 cc-connect management Bearer 与绑定 HMAC Key。Windows 后端必须是 keyring.backends.Windows.WinVaultKeyring；不匹配时返回 backend_unavailable，不允许明文文件回退。

API Secret 字段 writeOnly。SQLite 只保存 reference、purpose、backend、revision、status 和 verified_at；Operation 幂等只保存 body digest，不保存原始 Secret body。Secret 不进入 TOML、argv、日志、SSE、Diagnostic 或报告。Python/keyring 无法保证物理内存完全清零。

## Bot 身份与 Telegram Client

每个 slot 使用独立 CredentialRef 调用 getMe，保存 bot_id、username、first_name、群能力、credential revision 与 verified_at。bot_id 在三个 slot 间唯一，凭据轮换后身份必须重新验证。

Telegram Client 只实现 getMe、getWebhookInfo、getUpdates 和显式 deleteWebhook。它支持取消、响应大小限制、一次有界 429 retry_after，以及 401、403、409、超时、DNS/TLS 和网络错误的稳定脱敏映射。不引入完整 Bot Framework，不实现业务消息发送。

## Update Stream 单一所有权

TelegramUpdateLease 以 bot slot 为键保存 owner、operation_id、credential_revision、acquired/expires/heartbeat、offset、release_reason 与 revision。Owner 枚举为 none、control_plane_binding、hermes_runtime、cc_connect_runtime、external、conflict、unknown。

绑定前产品受管 runtime 必须停止，且先检查 webhook。Control Plane 只在显式 poll Operation 内获取 control_plane_binding Lease；offset 只前进，完成、取消、失败或超时后释放。运行 cc-connect 前先获取 Claude/Codex runtime Lease，reconcile 续期，stop/crash 释放。Webhook 不会被静默删除。

## 一次性绑定

创建会话前要求三个身份均有效。随机 bind code 只在创建响应显示一次；数据库保存 HMAC(session_id, code)，不保存明文。会话有 expires_at、revision、逐 slot 私聊/群聊进度和审计。

私聊只接受 private chat、有效 from.id 和 /bind CODE；第一个用户锁定 operator_user_id，其余 Bot 必须由同一用户完成。群聊只接受 group/supergroup、同一 operator 和 /bind@BotUsername CODE；channel 拒绝，Topic ID 不当作 Group ID。旧 Update、错误 code、重放、其他用户抢绑定和不同群均被忽略、拒绝或进入 conflict。三个 slot 的 private_user_id 与 group_chat_id 一致后状态为 completed、3/3 bound。

## managed/native 分离与 Renderer

state/managed/cc-connect-state.json 保存 product instance、artifact、ManagementOwner/LifecycleOwner、configuration/runtime revision、CredentialRef、Bot/binding metadata、进程/健康/备份/审计引用。

state/runtime-config/cc-connect.toml 由 cc-connect-fc315d2-native-v1 Renderer 生成，只包含锁定 commit 支持的 data_dir、management、Project、Agent、work_dir、Telegram Platform、allow_from/admin_from 和 Secret 环境变量占位符。Renderer 不输出产品 Owner、Operation、CredentialRef、group_chat_id 或审计字段。

Claude slot 映射 claudecode 与 AIAD_TELEGRAM_CLAUDE_BOT_TOKEN；Codex slot 映射 codex 与 AIAD_TELEGRAM_CODEX_BOT_TOKEN。启动前验证 claude/codex 可执行入口存在，认证证据不足返回 unknown，不安装 Agent、不写模型 API Key、不接管 CC Switch Provider。

原生配置继续使用不可变计划、plan/context digest、显式 confirmation、revision、备份、同目录原子替换、重解析、漂移检测与回滚。配置必须在运行期间持续存在。

## 受管运行与 external 检测

RuntimeSecretInjector 只给目标进程构造系统必要环境、PATH 和三个 Secret 变量；PATH 保留用于发现已安装 Agent，不改变用户或系统环境。进程身份继续绑定 PID/创建时间、exe 路径/SHA、命令摘要、configuration revision 与端口 PID。

external 状态拆分为 installed、process_running、port_active、supervisor_detected、configuration_detected、owner_known、conflict 与 unknown。PATH 仅安装不阻塞；相同目标端口、相同配置作用域或 Supervisor 才硬阻塞。产品不停止、删除或修改外部对象。

## Hermes 与已知上游限制

Hermes 未安装时保存 pending_component_install 计划，不阻塞 Claude/Codex；已安装但配置 Owner 为 external 时只生成非 Secret 计划，不直接写入未知 Schema。

锁定版 cc-connect management API 无 bind host 字段，实测监听所有网卡，虽有 Bearer 仍只记 partial。Telegram 原生 options 无 Group Chat ID 白名单，只能限制 operator user，状态为 unsupported。上游无正式 deep health endpoint，deep health 为 unsupported。以上限制不通过新增 Patch 规避。

## 验证证据

锁定 commit 为 fc315d213b49d62e9d90ea4a510189d4115e636f，既有 patchset 为 0.1，产物 SHA256 为 cd1b0787709c0401a42f7c3ce5321184889adbfbf3b080190fee180afc977eec。Windows 11 合成验收完成三 Fake getMe、三私聊、三同群、revision 4、三份备份、漂移恢复、真实进程 start/stop/restart/reconcile、Bearer 200/401、Lease 释放、Secret 扫描与无残留进程。真实 Token 和 Windows 10 证据仍待用户现场完成。
