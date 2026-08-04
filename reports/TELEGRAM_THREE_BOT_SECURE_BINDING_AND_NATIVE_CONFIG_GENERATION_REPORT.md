# Telegram 三 Bot 安全凭据、合法受管运行与原生配置生成报告

## 结论

阶段状态：PARTIAL。

代码、契约、Fake Telegram、合成 Token、Windows Credential Manager 和 Windows 11 合法 cc-connect 受管运行已完成。未使用真实 Telegram Token，真实身份与三 Bot 同群绑定为 PENDING USER LIVE VALIDATION；Windows 10 为 PENDING WINDOWS 10 VALIDATION；Hermes 为 pending_component_install；锁定上游原生 Group Chat 过滤和 deep health 为 unsupported。不得将本阶段标为 COMPLETE。

## 起点与范围

- 实施提示词时间：2026-08-05 00:33 +08:00
- 本机验收证据采集起点：2026-08-05 01:58 +08:00
- 起始 main SHA：1d42997c0ad2d2111f37decd58f18dac436cacf2
- 起始 origin/main：与起始 SHA 一致
- 工作分支：main；未创建分支或 PR
- 产品方向：未改变，仍为 Windows 10/11 + Telegram + Hermes/Claude Code/Codex + cc-connect；CC Switch 仍为推荐但非强制入口
- 未执行：六链路真实消息 E2E、正式 GUI、Provider 编辑器、其他 Agent/Channel、Hermes 安装/升级、cc-connect 升级或新增 Patch

## 阶段 A：合法受管运行门槛

状态：PASSED WITH DECLARED UPSTREAM LIMITATIONS。

### Windows CredentialBackend

实现 WindowsCredentialManagerBackend 与 CredentialService，固定公开引用为 telegram/hermes-bot-token、telegram/claude-bot-token、telegram/codex-bot-token。支持 put、replace、status、resolve_for_operation、delete、list_metadata、revision 与 capability probe。

Windows 11 普通用户合成验收结果为 PASSED：backend_class 为 keyring.backends.Windows.WinVaultKeyring，put revision 1、replace revision 2、delete revision 3，最终状态 missing，metadata-only 和 resolve 均通过，plaintext_file_fallback_allowed=false。验收凭据使用随机 acceptance/ 引用并在 finally 删除。Python/keyring 使用不可变字符串，physical_memory_zeroing_guaranteed=false。

### managed state 与 native config 分离

产品状态写入 state/managed/cc-connect-state.json，保存 product instance、artifact、ManagementOwner/LifecycleOwner、configuration/runtime revision、CredentialRef、Bot/binding metadata 与证据引用。

锁定上游运行配置写入 state/runtime-config/cc-connect.toml，只包含 data_dir、management、Project、Agent、work_dir、Telegram Platform、allow_from/admin_from 和 Secret 环境变量占位符。Owner、Operation、审计、CredentialRef 与 group_chat_id 不进入上游 TOML。

CcConnectNativeConfigRenderer 固定版本为 cc-connect-fc315d2-native-v1，绑定 source commit fc315d213b49d62e9d90ea4a510189d4115e636f。

### 锁定源码与 Secret 注入证明

继续使用既有 patchset 0.1，没有升级 cc-connect 或增加 Patch。锁定产物信息：

- artifact：cc-connect-v1.4.1-patchset0.1-fc315d2-windows-amd64
- Go：1.26.5 windows/amd64
- PE machine：0x8664
- size：26928640 bytes
- SHA256：cd1b0787709c0401a42f7c3ce5321184889adbfbf3b080190fee180afc977eec
- signature：unsigned

锁定源码 Config.Load 使用 `${NAME}` 环境变量替换。上游 TestConfigValidate、缺失占位符测试和 Telegram Patch 测试通过。上游正向占位符测试在 Windows 的 data_dir 斜杠断言处失败，失败点是 `/` 与 `\` 的测试期望，不是 Token 展开；因此另用临时外部 Go 探针直接导入精确锁定 config 包，正向 Telegram Token 展开、Project/Agent/Platform 解析和缺少 Platform 反例均通过。探针运行后删除，未修改锁定源码、Patchset 或产物。

RuntimeSecretInjector 从 CredentialBackend 临时解析 Claude、Codex 和 management Token，只注入目标子进程。TOML 保留占位符，Token 不进入 argv。审计只保存环境变量名和 CredentialRef，不保存值。

首次真实进程验收发现最小环境缺少 PATH，导致已安装 Claude/Codex 无法被 cc-connect 发现。修复为保留 PATH、PATHEXT 等必要非敏感系统环境，并增加 Agent 可执行入口预检；没有写入或改变系统/用户 PATH。

### 合法 cc-connect 真实进程

Windows 11 普通用户、非系统盘、中文/空格/括号路径合成验收为 PASSED。配置包含合法 Claude Code 与 Codex Project、独立 Telegram Platform 和合成 Token。证据包括：

- install 与 ownership Operation succeeded
- native configuration revision 4，备份 3 份
- 漂移检测与恢复通过
- start succeeded，进程通过 startup stable window
- PID/创建时间、exe 路径/SHA256、configuration revision、目标端口到 PID 所有权均通过
- stop、restart、Control Plane 重启 reconcile、final stop 均通过
- management API 正确 Bearer 返回 200，错误 Bearer 返回 401
- Update Lease 已释放，无受管进程残留

锁定上游 management 配置只有 port，没有 bind host。实测监听所有网卡，因此 management_api_bind_scope=upstream_all_interfaces，健康只记 partial。上游没有正式 deep health endpoint，deep health=unsupported。

### external cc-connect 检测

状态拆分为 external_installed、external_process_running、external_port_active、external_supervisor_detected、external_configuration_detected、external_owner_known、conflict 和 unknown。

PATH 中仅存在外部可执行文件不再阻塞产品实例。相同目标端口、相同配置作用域或外部 Supervisor 构成硬冲突；不同端口外部进程只记录证据。无法读取进程路径返回 unknown。产品不停止、删除或修改外部进程、配置、计划任务或 Watchdog。

## 阶段 B：三 Bot 安全绑定

状态：CODE AND SYNTHETIC ACCEPTANCE PASSED；LIVE PENDING。

### Telegram Client 与 Bot 身份

TelegramBotApiClient 实现 getMe、getWebhookInfo、getUpdates 和显式 deleteWebhook。支持请求取消、响应大小限制、一次有界 429 retry_after，以及 401、403、409、超时、DNS/TLS 和网络错误的稳定脱敏映射；不无限重试，不实现消息发送，不引入完整 Bot Framework。

三个固定 slot 分别验证 Credential revision 和 getMe，保存非敏感 Bot metadata。相同 bot_id 不能占两个 slot，凭据轮换后旧身份失效。Fake 验收获得三个唯一身份；没有保存或报告合成 ID、username 或 Token 值。

### Update Stream 所有权

TelegramUpdateLease 保存 slot、owner、operation_id、credential_revision、acquired/expires/heartbeat、offset、release_reason 和 revision。绑定前要求 runtime 停止且 Lease owner=none；Control Plane 只在显式 poll Operation 内临时持有 control_plane_binding。offset 只前进，凭据 revision 变化时重置；完成、取消、失败和超时均释放。

启动 Claude/Codex runtime 前检查 webhook 并获取 cc_connect_runtime Lease，reconcile 续期，stop/crash 释放。Webhook 不会被静默删除，删除必须 explicit_confirmation。

### 一次性绑定、防重放与 3/3 一致性

bind code 使用 secrets 生成，只在创建响应展示一次；SQLite 只保存 HMAC(session_id, code)。会话有 expires_at、revision、逐 slot progress 与审计。

私聊只接受 private chat、有效 from.id 与 /bind CODE；第一个用户锁定 operator_user_id。群聊只接受 group/supergroup、同一 operator 与 /bind@BotUsername CODE；channel 拒绝，Topic ID 不当 Group ID。旧 Update、错误 code、重放、其他用户抢绑定和不同群均被忽略、拒绝或标 conflict。

Fake Telegram 联合验收结果：三私聊 3/3、三群聊 3/3、同一 operator、同一 group、binding state=completed、Update Lease 全部释放。该证据不能替代真实 Telegram。

### Claude/Codex 原生配置

绑定完成后生成两个稳定 Project：Claude slot 映射 claudecode 与 AIAD_TELEGRAM_CLAUDE_BOT_TOKEN；Codex slot 映射 codex 与 AIAD_TELEGRAM_CODEX_BOT_TOKEN。allow_from/admin_from 固定为绑定 operator，禁用上游 upgrade 命令，work_dir 必须为产品计划中的绝对路径。

锁定原生 Telegram options 不支持 Group Chat ID 白名单。group_chat_id 只保存在 managed state，native_group_chat_filter_status=unsupported；当前只能限制 operator user，不能声称仅目标群可用。

### Hermes 与 CC Switch 边界

Hermes 未在隔离验收环境中发现，状态为 pending_component_install；三 Bot 身份和群绑定仍可完成，Claude/Codex 不被阻塞。若发现 Hermes，当前只生成 external-owner 非 Secret 计划，不猜未知 Schema、不安装、不升级、不接管 Hermes Studio 或 Provider。

CC Switch 仍为外部可选工具，只做公开可执行入口检测和普通打开，不读私有数据库或 Secret，不做 GUI 自动点击，不管理 Telegram Token 或 cc-connect 原生配置。

## API、契约与持久化

OpenAPI v1 与 managed-runtime.schema.json 已向后兼容增加：Credential capability/put/replace/status/delete；Bot identity/webhook；Update Lease；Binding create/get/cancel/poll；Native Renderer/plan/apply/state；external cc-connect；Hermes Telegram plan/state；RuntimeHealth management API 字段。Secret 输入为 writeOnly，响应 Schema 不含 Secret。

Alembic 0004 增加 credential reference/revision、Bot identity、binding session/slot/group/audit、update lease/offset、native configuration plan/revision/backup、renderer、Hermes plan 和 runtime Secret injection audit。SQLite 不保存 Secret、绑定码明文、完整 Telegram Update 或消息正文。

## 依赖、复用与 License

没有新增运行时依赖。复用现有 keyring、httpx、SQLAlchemy/Pydantic/FastAPI/psutil 和 Python 标准库。Windows Credential Manager、Telegram Bot API、锁定 cc-connect 源码和现有上游 License 边界均按窄接口使用；没有复制完整项目或引入 Bot Framework、Vault、Redis/Celery、消息队列或工作流引擎。

## 自动化与本机验证

本地最终检查：

- pytest：167 passed、1 skipped
- ruff check：passed
- ruff format --check：passed
- mypy control_plane：passed，75 source files
- compileall：passed
- contracts validation：OpenAPI 与三个 JSON Schema passed
- 锁定 artifact verify：passed
- Windows isolated regression：passed
- Windows managed secretless regression：PARTIAL，符合旧上游无 Secret 限制
- Windows credential acceptance：PASSED
- Windows native runtime acceptance：synthetic_acceptance=PASSED，整体 PARTIAL
- Windows 10 wrapper：当前 Windows 11 主机返回 NOT_WINDOWS_10_X64，没有虚报

GitHub Actions 最终成功 Run ID：30943550897，head SHA 为 72a3b356c173eb8e1c16c05b49e3e1d12d037a13，三个作业均为 success。Windows 锁定产物作业已实际执行 Credential Manager、isolated、managed、native runtime 与 Windows 10 wrapper 验收，并上传对应证据。

首次推送 Run 30941858673 的既有质量、Ubuntu、锁定构建、Credential Manager、isolated 和 managed 步骤均通过，但新增 native runtime 步骤发现 GitHub runner 没有 Claude/Codex 可执行入口。修复只作用于验收脚本：优先使用现有用户入口，缺失时在隔离临时目录生成 no-op shim 并临时加入当前进程 PATH，成功或异常均恢复；没有安装 Agent 或修改系统 PATH。修复后本机以真实入口和清空 PATH 两种场景均通过，随后 Run 30943550897 全绿。

## Secret 与环境不变证明

自动化和本机验收只使用 Fake Credential/Fake Telegram/合成 Token；真实消息发送数为 0。产品文件扫描未发现合成 Secret 或绑定码。Reference Baseline、src/、既有 5 个 Patch、真实配置、系统/用户 PATH、注册表、计划任务、Watchdog、Windows Service 和外部 cc-connect 均未修改。验收结束无残留受管进程。

## 未解决问题与技术债

- PENDING USER LIVE VALIDATION：三个真实测试 Bot 的 getMe、三私聊、三同群和 3/3 绑定
- PENDING WINDOWS 10 VALIDATION：Windows 10 x64 普通用户打包实机
- pending_component_install：Hermes 隔离环境未安装
- unsupported：原生 Group Chat ID 过滤
- partial：management API 监听所有网卡，依赖高熵 Bearer 与本机防火墙
- unsupported：deep health
- unsigned：cc-connect 产物可能触发 SmartScreen
- Python/keyring 不能保证 Secret 物理内存完全清零

## 下一阶段

准确名称为“六链路可观测性、真实消息 E2E 与会话隔离修复切片”。进入真实消息测试前必须由用户显式完成 live 三 Bot 绑定，并确认 Windows 10、Hermes 状态、Update Lease 和配置回滚门禁。下一阶段才逐条验证三个私聊、三个群聊、命令、Mention、Reply、Topic 和 Session 隔离；正式 GUI 继续延后。

## Git 与回滚

- 功能实现提交 SHA：8c1a2016f4d587a301e90d54c95191f68a808015
- CI 环境修复提交 SHA：72a3b356c173eb8e1c16c05b49e3e1d12d037a13
- Windows CI Run ID：30943550897（success）
- 报告回填提交 SHA：由 Git 提交元数据记录，报告不做自引用
- 最终远端分支要求：仅 main
- 回滚方法：对本阶段功能实现提交执行普通 git revert，并重新运行迁移、测试和 Windows 验收；不得使用 force push 或破坏性 reset
